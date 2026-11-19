"""
Database Repository for the All-India PDF Intelligence Engine.

Supports:
1. Supreme Court of India (`court_type = 'supreme_court'`, nullable state/district)
2. High Courts & Benches (`court_type = 'high_court'`, State -> High Court -> Bench)
3. District & Subordinate Courts (`court_type = 'district_court'`, State -> District -> Complex -> Establishment)

Uses the existing PostgreSQL connection configuration (`DATABASE_URL` / `DB_*`)
without modifying `deployment/data_service.py`, and provides an automatic local
SQLite store when PostgreSQL credentials are absent in offline/test environments.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from .case_parser import ParsedCaseRecord
from .pdf_extractor import PDFExtractionResult
from .source_discovery import (
    ALL_INDIA_STATES_UTS,
    COURT_LOCATIONS_CATALOG,
    SHARED_HIGH_COURT_NOTES,
    CourtLocationSpec,
    DiscoveredDocument,
)

logger = logging.getLogger(__name__)

DEPLOYMENT_DIR = Path(__file__).resolve().parents[2]
MIGRATION_SQL_PATH = DEPLOYMENT_DIR / "migrations" / "20261118_create_pdf_intelligence_tables.sql"
DEFAULT_SQLITE_FALLBACK_PATH = DEPLOYMENT_DIR / "downloaded_pdfs" / "pdf_intelligence" / "pi_engine.sqlite3"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def _fmt_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    return s[:10] if len(s) >= 10 else (s or None)


def _fmt_dt(val: Any) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def _parse_json_field(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


class _UnifiedCursor:
    """
    Normalizes parameter placeholders (`%s` -> `?` on SQLite) and returns rows as dicts.
    """

    def __init__(self, raw_cursor, is_sqlite: bool):
        self._cur = raw_cursor
        self._is_sqlite = is_sqlite

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> None:
        param_tuple = tuple(params) if params is not None else ()
        if self._is_sqlite:
            adapted_sql = sql.replace("%s", "?")
            adapted_sql = adapted_sql.replace("ILIKE", "LIKE")
            adapted_sql = adapted_sql.replace("::jsonb", "")
            adapted_sql = adapted_sql.replace("NOW()", "CURRENT_TIMESTAMP")
            self._cur.execute(adapted_sql, param_tuple)
        else:
            self._cur.execute(sql, param_tuple)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self._cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self) -> Any:
        return getattr(self._cur, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def close(self) -> None:
        self._cur.close()


class PDFIntelligenceRepository:
    """
    Isolated repository managing all persistence for the PDF Intelligence Engine.
    """

    def __init__(self, sqlite_path: Optional[str | Path] = None):
        self._sqlite_override = Path(sqlite_path) if sqlite_path else (
            Path(os.environ["PI_SQLITE_PATH"]) if os.getenv("PI_SQLITE_PATH") else None
        )
        self._sqlite_lock = threading.RLock()
        self._initialized = False
        self._backend_type: Optional[str] = None

    def _try_postgres_connection(self):
        if self._sqlite_override is not None:
            return None

        db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
        db_password = os.getenv("DB_PASSWORD")
        db_host = os.getenv("DB_HOST", "db.dvsjnzrouwywaqcacwsl.supabase.co")

        if not db_url and not db_password:
            return None

        try:
            if db_url:
                return psycopg2.connect(
                    db_url,
                    connect_timeout=4,
                    sslmode=os.getenv("DB_SSLMODE") or "require",
                )
            return psycopg2.connect(
                host=db_host,
                port=int(os.getenv("DB_PORT", 5432)),
                database=os.getenv("DB_NAME", "postgres"),
                user=os.getenv("DB_USER", "postgres"),
                password=db_password,
                connect_timeout=4,
                sslmode=os.getenv("DB_SSLMODE") or "require",
            )
        except Exception as exc:
            logger.warning("[PDFIntelligenceRepository] PostgreSQL unreachable (%s); using durable local SQLite store.", exc)
            return None

    def _open_sqlite_connection(self) -> sqlite3.Connection:
        target = self._sqlite_override or DEFAULT_SQLITE_FALLBACK_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def transaction(self):
        """
        Context manager yielding `(cursor, is_sqlite)` within an atomic transaction.
        """
        pg_conn = self._try_postgres_connection()
        if pg_conn is not None:
            self._backend_type = "postgresql"
            raw_cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            cur = _UnifiedCursor(raw_cur, is_sqlite=False)
            try:
                yield cur, False
                pg_conn.commit()
            except Exception:
                pg_conn.rollback()
                raise
            finally:
                cur.close()
                pg_conn.close()
        else:
            self._backend_type = "sqlite"
            with self._sqlite_lock:
                sq_conn = self._open_sqlite_connection()
                raw_cur = sq_conn.cursor()
                cur = _UnifiedCursor(raw_cur, is_sqlite=True)
                try:
                    yield cur, True
                    sq_conn.commit()
                except Exception:
                    sq_conn.rollback()
                    raise
                finally:
                    cur.close()
                    sq_conn.close()

    @property
    def backend_type(self) -> str:
        if not self._backend_type:
            self.ensure_initialized()
        return self._backend_type or "postgresql"

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self.transaction() as (cur, is_sqlite):
            if is_sqlite:
                self._init_sqlite_schema(cur)
            else:
                self._init_postgres_schema(cur)
            self._seed_court_locations(cur, is_sqlite)
        self._initialized = True

    @staticmethod
    def _init_postgres_schema(cur: _UnifiedCursor) -> None:
        sql_text = MIGRATION_SQL_PATH.read_text(encoding="utf-8")
        cleaned = "\n".join(
            line for line in sql_text.splitlines()
            if line.strip().upper() not in ("BEGIN;", "COMMIT;")
        )
        cur.execute(cleaned)

    @staticmethod
    def _init_sqlite_schema(cur: _UnifiedCursor) -> None:
        # Check if an older schema without `complex_code` exists and upgrade cleanly
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pi_court_locations'")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(pi_court_locations)")
            existing_cols = {r["name"] for r in cur.fetchall()}
            if "complex_code" not in existing_cols:
                for tbl in (
                    "pi_daily_analytics",
                    "pi_case_records",
                    "pi_extraction_jobs",
                    "pi_documents",
                    "pi_scrape_jobs",
                    "pi_court_locations",
                ):
                    cur.execute(f"DROP TABLE IF EXISTS {tbl}")

        statements = [
            """
            CREATE TABLE IF NOT EXISTS pi_court_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_key TEXT NOT NULL UNIQUE,
                court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
                state_code TEXT,
                state_iso_code TEXT,
                state_name TEXT,
                is_union_territory INTEGER NOT NULL DEFAULT 0,
                district_code TEXT,
                district_name TEXT,
                complex_code TEXT,
                complex_name TEXT,
                establishment_code TEXT,
                establishment_name TEXT,
                court_code TEXT NOT NULL,
                court_name TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_name TEXT NOT NULL,
                source_system TEXT NOT NULL,
                source_supported INTEGER NOT NULL DEFAULT 1,
                requires_manual_verification INTEGER NOT NULL DEFAULT 0,
                supported_doc_categories TEXT NOT NULL DEFAULT '["daily_cause_list", "supplementary_cause_list"]',
                source_limitation TEXT,
                latitude REAL,
                longitude REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pi_court_locations_tier ON pi_court_locations (court_type, state_code)",
            "CREATE INDEX IF NOT EXISTS idx_pi_court_locations_district ON pi_court_locations (state_code, district_code)",
            "CREATE INDEX IF NOT EXISTS idx_pi_court_locations_complex ON pi_court_locations (state_code, district_code, complex_code)",
            """
            CREATE TABLE IF NOT EXISTS pi_scrape_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_uid TEXT NOT NULL UNIQUE,
                scope_key TEXT NOT NULL,
                court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
                state_code TEXT,
                state_name TEXT,
                district_code TEXT,
                district_name TEXT,
                complex_code TEXT,
                complex_name TEXT,
                establishment_code TEXT,
                establishment_name TEXT,
                court_code TEXT,
                court_name TEXT,
                bench_code TEXT,
                bench_name TEXT,
                document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                preset_label TEXT NOT NULL DEFAULT 'custom',
                status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')),
                discovered_count INTEGER NOT NULL DEFAULT 0,
                downloaded_count INTEGER NOT NULL DEFAULT 0,
                skipped_duplicate_count INTEGER NOT NULL DEFAULT 0,
                extracted_doc_count INTEGER NOT NULL DEFAULT 0,
                case_records_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                progress_pct INTEGER NOT NULL DEFAULT 0,
                current_step TEXT,
                log_entries TEXT NOT NULL DEFAULT '[]',
                error_summary TEXT,
                limitation_notice TEXT,
                requires_manual_verification INTEGER NOT NULL DEFAULT 0,
                worker_id TEXT,
                recovered_from_restart INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pi_scrape_jobs_status ON pi_scrape_jobs (status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pi_scrape_jobs_scope ON pi_scrape_jobs (scope_key, status)",
            """
            CREATE TABLE IF NOT EXISTS pi_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_identity TEXT NOT NULL UNIQUE,
                scrape_job_id INTEGER REFERENCES pi_scrape_jobs(id) ON DELETE SET NULL,
                location_id INTEGER REFERENCES pi_court_locations(id) ON DELETE RESTRICT,
                court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
                state_code TEXT,
                state_name TEXT,
                district_code TEXT,
                district_name TEXT,
                complex_code TEXT,
                complex_name TEXT,
                establishment_code TEXT,
                establishment_name TEXT,
                court_code TEXT NOT NULL,
                court_name TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_name TEXT NOT NULL,
                document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
                listing_date TEXT NOT NULL,
                order_date TEXT,
                judgment_date TEXT,
                cause_list_type TEXT,
                coram_judge_raw TEXT,
                court_number TEXT,
                diary_number TEXT,
                source_portal TEXT,
                source_reference TEXT NOT NULL,
                source_url TEXT NOT NULL,
                pdf_filename TEXT NOT NULL,
                storage_namespace TEXT NOT NULL DEFAULT 'pdf-intelligence/high-court',
                storage_object_key TEXT,
                local_fallback_path TEXT,
                content_sha256 TEXT,
                file_size_bytes INTEGER,
                page_count INTEGER,
                download_status TEXT NOT NULL DEFAULT 'pending',
                extraction_status TEXT NOT NULL DEFAULT 'pending',
                extraction_method TEXT,
                extraction_confidence REAL,
                case_count INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                source_metadata TEXT NOT NULL DEFAULT '{}',
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                downloaded_at TEXT,
                processed_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pi_documents_tier_date ON pi_documents (court_type, state_code, district_code, bench_code, listing_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pi_documents_sha256 ON pi_documents (content_sha256)",
            """
            CREATE TABLE IF NOT EXISTS pi_extraction_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES pi_documents(id) ON DELETE CASCADE,
                scrape_job_id INTEGER REFERENCES pi_scrape_jobs(id) ON DELETE SET NULL,
                attempt_number INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                extraction_method TEXT,
                used_ocr INTEGER NOT NULL DEFAULT 0,
                pages_processed INTEGER NOT NULL DEFAULT 0,
                extracted_chars INTEGER NOT NULL DEFAULT 0,
                cases_extracted INTEGER NOT NULL DEFAULT 0,
                confidence_score REAL,
                error_message TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pi_case_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES pi_documents(id) ON DELETE CASCADE,
                location_id INTEGER REFERENCES pi_court_locations(id) ON DELETE SET NULL,
                case_sequence INTEGER NOT NULL,
                document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
                item_number TEXT,
                case_number TEXT NOT NULL,
                case_type TEXT NOT NULL,
                case_year INTEGER,
                cnr_number TEXT,
                diary_number TEXT,
                filing_number TEXT,
                case_title TEXT NOT NULL,
                petitioner TEXT,
                respondent TEXT,
                advocates TEXT,
                advocate_on_record TEXT,
                listing_date TEXT NOT NULL,
                order_date TEXT,
                judgment_date TEXT,
                judge_names TEXT,
                court_room TEXT,
                court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
                state_code TEXT,
                state_name TEXT,
                district_code TEXT,
                district_name TEXT,
                complex_code TEXT,
                complex_name TEXT,
                establishment_code TEXT,
                establishment_name TEXT,
                court_code TEXT NOT NULL,
                court_name TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_name TEXT NOT NULL,
                pdf_filename TEXT NOT NULL,
                page_number INTEGER,
                extraction_status TEXT NOT NULL DEFAULT 'completed',
                confidence REAL NOT NULL DEFAULT 0.8000,
                confidence_label TEXT NOT NULL DEFAULT 'high',
                raw_excerpt TEXT,
                extracted_details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (document_id, case_sequence)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pi_case_records_tier_date ON pi_case_records (court_type, state_code, district_code, bench_code, listing_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pi_case_records_document ON pi_case_records (document_id)",
            """
            CREATE TABLE IF NOT EXISTS pi_daily_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analytics_scope_key TEXT NOT NULL UNIQUE,
                analytics_date TEXT NOT NULL,
                court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
                state_code TEXT,
                state_name TEXT,
                district_code TEXT,
                district_name TEXT,
                complex_code TEXT,
                complex_name TEXT,
                establishment_code TEXT,
                establishment_name TEXT,
                court_code TEXT NOT NULL,
                court_name TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_name TEXT NOT NULL,
                pdfs_discovered INTEGER NOT NULL DEFAULT 0,
                pdfs_downloaded INTEGER NOT NULL DEFAULT 0,
                pdfs_processed INTEGER NOT NULL DEFAULT 0,
                cause_list_pdfs INTEGER NOT NULL DEFAULT 0,
                order_judgment_pdfs INTEGER NOT NULL DEFAULT 0,
                total_case_records INTEGER NOT NULL DEFAULT 0,
                cause_list_cases INTEGER NOT NULL DEFAULT 0,
                order_judgment_cases INTEGER NOT NULL DEFAULT 0,
                extraction_failures INTEGER NOT NULL DEFAULT 0,
                processing_success_rate REAL NOT NULL DEFAULT 0.00,
                cases_by_type TEXT NOT NULL DEFAULT '{}',
                cases_by_judge TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]
        for stmt in statements:
            cur.execute(stmt)

    @staticmethod
    def _seed_court_locations(cur: _UnifiedCursor, is_sqlite: bool) -> None:
        for loc in COURT_LOCATIONS_CATALOG:
            doc_cats_json = json.dumps(list(loc.supported_doc_categories))
            cur.execute(
                """
                INSERT INTO pi_court_locations (
                    location_key, court_type, state_code, state_iso_code, state_name,
                    is_union_territory, district_code, district_name,
                    complex_code, complex_name, establishment_code, establishment_name,
                    court_code, court_name, bench_code, bench_name,
                    source_system, source_supported, requires_manual_verification,
                    supported_doc_categories, source_limitation, latitude, longitude
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s, %s, %s
                )
                ON CONFLICT (location_key) DO UPDATE SET
                    court_type = EXCLUDED.court_type,
                    state_iso_code = EXCLUDED.state_iso_code,
                    state_name = EXCLUDED.state_name,
                    district_name = EXCLUDED.district_name,
                    complex_code = EXCLUDED.complex_code,
                    complex_name = EXCLUDED.complex_name,
                    establishment_code = EXCLUDED.establishment_code,
                    establishment_name = EXCLUDED.establishment_name,
                    court_name = EXCLUDED.court_name,
                    bench_name = EXCLUDED.bench_name,
                    source_supported = EXCLUDED.source_supported,
                    requires_manual_verification = EXCLUDED.requires_manual_verification,
                    supported_doc_categories = EXCLUDED.supported_doc_categories,
                    source_limitation = EXCLUDED.source_limitation,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude
                """,
                (
                    loc.location_key,
                    loc.court_type,
                    loc.state_code,
                    loc.state_iso_code,
                    loc.state_name,
                    int(loc.is_union_territory) if is_sqlite else loc.is_union_territory,
                    loc.district_code,
                    loc.district_name,
                    loc.complex_code,
                    loc.complex_name,
                    loc.establishment_code,
                    loc.establishment_name,
                    loc.court_code,
                    loc.court_name,
                    loc.bench_code,
                    loc.bench_name,
                    loc.source_system,
                    int(loc.source_supported) if is_sqlite else loc.source_supported,
                    int(loc.requires_manual_verification) if is_sqlite else loc.requires_manual_verification,
                    doc_cats_json,
                    loc.source_limitation,
                    loc.latitude,
                    loc.longitude,
                ),
            )

    # -------------------------------------------------------------------------
    # Court Locations & Hierarchy Navigation Queries (Requirements E & G)
    # -------------------------------------------------------------------------
    def get_location_id(self, location_key: str) -> Optional[int]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute("SELECT id FROM pi_court_locations WHERE location_key = %s", (location_key,))
            row = cur.fetchone()
            return int(row["id"]) if row else None

    def get_states_hierarchy(self, court_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return all 36 Indian States and Union Territories with their verified High Court
        and District Court counts, plus actual stored PDF & case record counts.
        """
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute(
                """
                SELECT
                    state_code,
                    state_iso_code,
                    state_name,
                    COUNT(DISTINCT district_code) AS districts_with_courts,
                    COUNT(CASE WHEN court_type = 'high_court' THEN 1 END) AS high_court_benches,
                    COUNT(DISTINCT CASE WHEN court_type = 'district_court' THEN complex_code END) AS district_court_complexes,
                    COUNT(CASE WHEN court_type = 'district_court' THEN 1 END) AS district_court_establishments,
                    MAX(CASE WHEN source_supported THEN 1 ELSE 0 END) AS has_supported_source
                FROM pi_court_locations
                WHERE state_iso_code IS NOT NULL
                GROUP BY state_code, state_iso_code, state_name
                """
            )
            loc_rows = {r["state_iso_code"]: r for r in cur.fetchall()}

            doc_where = ""
            doc_params: List[Any] = []
            if court_type and court_type in ("high_court", "district_court"):
                doc_where = "AND court_type = %s"
                doc_params.append(court_type)

            cur.execute(
                f"""
                SELECT
                    state_code,
                    COUNT(*) AS total_pdfs,
                    COUNT(CASE WHEN extraction_status IN ('completed', 'ocr_completed') THEN 1 END) AS processed_pdfs,
                    COALESCE(SUM(case_count), 0) AS total_cases
                FROM pi_documents
                WHERE state_code IS NOT NULL {doc_where}
                GROUP BY state_code
                """,
                doc_params,
            )
            doc_rows = {r["state_code"]: r for r in cur.fetchall()}

        result: List[Dict[str, Any]] = []
        for st in ALL_INDIA_STATES_UTS:
            iso = st["state_iso_code"]
            scode = st["state_code"]
            loc_info = loc_rows.get(iso, {})
            doc_info = doc_rows.get(scode, {})
            result.append(
                {
                    "state_code": scode,
                    "state_iso_code": iso,
                    "state_name": st["state_name"],
                    "is_union_territory": bool(st["is_union_territory"]),
                    "districts_with_courts": int(loc_info.get("districts_with_courts") or 0),
                    "high_court_benches": int(loc_info.get("high_court_benches") or 0),
                    "district_court_complexes": int(loc_info.get("district_court_complexes") or 0),
                    "district_court_establishments": int(loc_info.get("district_court_establishments") or 0),
                    "district_court_benches": int(loc_info.get("district_court_establishments") or 0),
                    "has_supported_source": bool(loc_info.get("has_supported_source")),
                    "total_pdfs": int(doc_info.get("total_pdfs") or 0),
                    "processed_pdfs": int(doc_info.get("processed_pdfs") or 0),
                    "total_cases": int(doc_info.get("total_cases") or 0),
                    "jurisdiction_note": SHARED_HIGH_COURT_NOTES.get(scode),
                }
            )
        return sorted(result, key=lambda x: x["state_name"].casefold())

    def get_districts(self, state_code: Optional[str] = None, court_type: Optional[str] = None) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        clauses: List[str] = ["l.district_code IS NOT NULL"]
        params: List[Any] = []
        if state_code:
            clauses.append("(UPPER(l.state_code) = UPPER(%s) OR UPPER(l.state_iso_code) = UPPER(%s))")
            params.extend([state_code.strip(), state_code.strip()])
        if court_type:
            clauses.append("l.court_type = %s")
            params.append(court_type.strip().lower())

        where_sql = f"WHERE {' AND '.join(clauses)}"
        with self.transaction() as (cur, _):
            cur.execute(
                f"""
                SELECT
                    l.state_code,
                    l.state_iso_code,
                    l.state_name,
                    l.district_code,
                    l.district_name,
                    COUNT(DISTINCT l.bench_code) AS bench_count,
                    COUNT(DISTINCT CASE WHEN l.court_type = 'high_court' THEN l.bench_code END) AS hc_bench_count,
                    COUNT(DISTINCT CASE WHEN l.court_type = 'district_court' THEN l.complex_code END) AS dc_complex_count,
                    COUNT(DISTINCT CASE WHEN l.court_type = 'district_court' THEN l.bench_code END) AS dc_bench_count,
                    COUNT(DISTINCT d.id) AS pdf_count,
                    COALESCE(SUM(d.case_count), 0) AS case_count
                FROM pi_court_locations l
                LEFT JOIN pi_documents d
                    ON d.location_id = l.id
                {where_sql}
                GROUP BY l.state_code, l.state_iso_code, l.state_name, l.district_code, l.district_name
                ORDER BY l.district_name ASC
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            {
                "state_code": r["state_code"],
                "state_iso_code": r["state_iso_code"],
                "state_name": r["state_name"],
                "district_code": r["district_code"],
                "district_name": r["district_name"],
                "bench_count": int(r["bench_count"] or 0),
                "hc_bench_count": int(r["hc_bench_count"] or 0),
                "dc_complex_count": int(r["dc_complex_count"] or 0),
                "dc_bench_count": int(r["dc_bench_count"] or 0),
                "pdf_count": int(r["pdf_count"] or 0),
                "case_count": int(r["case_count"] or 0),
            }
            for r in rows
        ]

    def get_complexes(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return District Court Complexes for a State / District, with counts of
        courts/establishments, PDFs, and extracted cases.
        """
        self.ensure_initialized()
        clauses: List[str] = ["l.court_type = 'district_court'", "l.complex_code IS NOT NULL"]
        params: List[Any] = []
        if state_code:
            clauses.append("(UPPER(l.state_code) = UPPER(%s) OR UPPER(l.state_iso_code) = UPPER(%s))")
            params.extend([state_code.strip(), state_code.strip()])
        if district_code:
            clauses.append("UPPER(l.district_code) = UPPER(%s)")
            params.append(district_code.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}"
        with self.transaction() as (cur, _):
            cur.execute(
                f"""
                SELECT
                    l.state_code,
                    l.state_name,
                    l.district_code,
                    l.district_name,
                    l.complex_code,
                    l.complex_name,
                    COUNT(DISTINCT l.establishment_code) AS establishment_count,
                    COUNT(DISTINCT d.id) AS pdf_count,
                    COALESCE(SUM(d.case_count), 0) AS case_count
                FROM pi_court_locations l
                LEFT JOIN pi_documents d ON d.location_id = l.id
                {where_sql}
                GROUP BY
                    l.state_code, l.state_name, l.district_code, l.district_name,
                    l.complex_code, l.complex_name
                ORDER BY l.district_name ASC, l.complex_name ASC
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            {
                "state_code": r["state_code"],
                "state_name": r["state_name"],
                "district_code": r["district_code"],
                "district_name": r["district_name"],
                "complex_code": r["complex_code"],
                "complex_name": r["complex_name"],
                "establishment_count": int(r["establishment_count"] or 0),
                "pdf_count": int(r["pdf_count"] or 0),
                "case_count": int(r["case_count"] or 0),
            }
            for r in rows
        ]

    def get_establishments(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        complex_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return individual District Court Establishments inside a Court Complex.
        """
        return self.get_benches(
            state_code=state_code,
            district_code=district_code,
            court_type="district_court",
            complex_code=complex_code,
        )

    def get_courts(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        court_type: Optional[str] = None,
        complex_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        clauses: List[str] = []
        params: List[Any] = []
        if state_code:
            clauses.append("(UPPER(l.state_code) = UPPER(%s) OR UPPER(l.state_iso_code) = UPPER(%s))")
            params.extend([state_code.strip(), state_code.strip()])
        if district_code:
            clauses.append("UPPER(l.district_code) = UPPER(%s)")
            params.append(district_code.strip())
        if court_type:
            clauses.append("l.court_type = %s")
            params.append(court_type.strip().lower())
        if complex_code:
            clauses.append("UPPER(l.complex_code) = UPPER(%s)")
            params.append(complex_code.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.transaction() as (cur, _):
            cur.execute(
                f"""
                SELECT
                    l.state_code,
                    l.state_name,
                    l.district_code,
                    l.district_name,
                    l.complex_code,
                    l.complex_name,
                    l.court_type,
                    l.court_code,
                    l.court_name,
                    COUNT(DISTINCT l.bench_code) AS bench_count,
                    COUNT(DISTINCT d.id) AS pdf_count,
                    COALESCE(SUM(d.case_count), 0) AS case_count
                FROM pi_court_locations l
                LEFT JOIN pi_documents d
                    ON d.location_id = l.id
                {where_sql}
                GROUP BY
                    l.state_code, l.state_name, l.district_code, l.district_name,
                    l.complex_code, l.complex_name, l.court_type, l.court_code, l.court_name
                ORDER BY l.court_type ASC, l.court_name ASC
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            {
                "state_code": r["state_code"],
                "state_name": r["state_name"],
                "district_code": r["district_code"],
                "district_name": r["district_name"],
                "complex_code": r["complex_code"],
                "complex_name": r["complex_name"],
                "court_type": r["court_type"],
                "court_code": r["court_code"],
                "court_name": r["court_name"],
                "bench_count": int(r["bench_count"] or 0),
                "pdf_count": int(r["pdf_count"] or 0),
                "case_count": int(r["case_count"] or 0),
            }
            for r in rows
        ]

    def get_benches(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        court_type: Optional[str] = None,
        court_code: Optional[str] = None,
        complex_code: Optional[str] = None,
        establishment_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        clauses: List[str] = []
        params: List[Any] = []
        if court_type:
            clauses.append("l.court_type = %s")
            params.append(court_type.strip().lower())
        if state_code:
            clauses.append("(UPPER(l.state_code) = UPPER(%s) OR UPPER(l.state_iso_code) = UPPER(%s))")
            params.extend([state_code.strip(), state_code.strip()])
        if district_code:
            clauses.append("UPPER(l.district_code) = UPPER(%s)")
            params.append(district_code.strip())
        if court_code:
            clauses.append("UPPER(l.court_code) = UPPER(%s)")
            params.append(court_code.strip())
        if complex_code:
            clauses.append("UPPER(l.complex_code) = UPPER(%s)")
            params.append(complex_code.strip())
        if establishment_code:
            clauses.append("(UPPER(l.establishment_code) = UPPER(%s) OR UPPER(l.bench_code) = UPPER(%s))")
            params.extend([establishment_code.strip(), establishment_code.strip()])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.transaction() as (cur, _):
            cur.execute(
                f"""
                SELECT
                    l.id AS location_id,
                    l.location_key,
                    l.court_type,
                    l.state_code,
                    l.state_iso_code,
                    l.state_name,
                    l.district_code,
                    l.district_name,
                    l.complex_code,
                    l.complex_name,
                    l.establishment_code,
                    l.establishment_name,
                    l.court_code,
                    l.court_name,
                    l.bench_code,
                    l.bench_name,
                    l.source_system,
                    l.source_supported,
                    l.requires_manual_verification,
                    l.supported_doc_categories,
                    l.source_limitation,
                    l.latitude,
                    l.longitude,
                    COUNT(d.id) AS pdf_count,
                    COALESCE(SUM(d.case_count), 0) AS case_count,
                    MAX(d.listing_date) AS latest_listing_date
                FROM pi_court_locations l
                LEFT JOIN pi_documents d ON d.location_id = l.id
                {where_sql}
                GROUP BY
                    l.id, l.location_key, l.court_type, l.state_code, l.state_iso_code, l.state_name,
                    l.district_code, l.district_name, l.complex_code, l.complex_name,
                    l.establishment_code, l.establishment_name, l.court_code, l.court_name,
                    l.bench_code, l.bench_name, l.source_system, l.source_supported,
                    l.requires_manual_verification, l.supported_doc_categories,
                    l.source_limitation, l.latitude, l.longitude
                ORDER BY
                    CASE l.court_type WHEN 'supreme_court' THEN 1 WHEN 'high_court' THEN 2 ELSE 3 END,
                    COALESCE(l.state_name, 'National') ASC,
                    COALESCE(l.district_name, '') ASC,
                    l.bench_code ASC
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            {
                "location_id": int(r["location_id"]),
                "location_key": r["location_key"],
                "court_type": r["court_type"],
                "state_code": r["state_code"],
                "state_iso_code": r["state_iso_code"],
                "state_name": r["state_name"],
                "district_code": r["district_code"],
                "district_name": r["district_name"],
                "complex_code": r["complex_code"],
                "complex_name": r["complex_name"],
                "establishment_code": r["establishment_code"],
                "establishment_name": r["establishment_name"],
                "court_code": r["court_code"],
                "court_name": r["court_name"],
                "bench_code": r["bench_code"],
                "bench_name": r["bench_name"],
                "source_system": r["source_system"],
                "source_supported": bool(r["source_supported"]),
                "requires_manual_verification": bool(r.get("requires_manual_verification")),
                "supported_doc_categories": _parse_json_field(
                    r.get("supported_doc_categories"),
                    ["daily_cause_list", "supplementary_cause_list"],
                ),
                "source_limitation": r["source_limitation"],
                "latitude": float(r["latitude"]) if r["latitude"] is not None else None,
                "longitude": float(r["longitude"]) if r["longitude"] is not None else None,
                "pdf_count": int(r["pdf_count"] or 0),
                "case_count": int(r["case_count"] or 0),
                "latest_listing_date": _fmt_date(r["latest_listing_date"]),
            }
            for r in rows
        ]

    # -------------------------------------------------------------------------
    # Durable Scrape Jobs Management (Step 10)
    # -------------------------------------------------------------------------
    def find_active_job_for_scope(self, scope_key: str) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute(
                """
                SELECT * FROM pi_scrape_jobs
                WHERE scope_key = %s AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scope_key,),
            )
            row = cur.fetchone()
            return self._serialize_job_row(row) if row else None

    def create_scrape_job(
        self,
        job_uid: str,
        scope_key: str,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
        preset_label: str = "custom",
        worker_id: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        with self.transaction() as (cur, is_sqlite):
            if not allow_duplicate:
                cur.execute(
                    """
                    SELECT * FROM pi_scrape_jobs
                    WHERE scope_key = %s AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (scope_key,),
                )
                existing = cur.fetchone()
                if existing:
                    raise RuntimeError(
                        f"An active scrape job ({existing['job_uid']}) is already {existing['status']} "
                        f"for {location.bench_name} ({start_date.isoformat()} to {end_date.isoformat()})."
                    )

            scope_desc = (
                f"Supreme Court / {location.bench_name}"
                if location.court_type == "supreme_court"
                else (
                    f"{location.state_name} / {location.district_name} / {location.complex_name} / {location.establishment_name}"
                    if location.court_type == "district_court"
                    else f"{location.state_name} / {location.district_name} / {location.bench_name}"
                )
            )
            initial_logs = json.dumps(
                [
                    {
                        "timestamp": _utc_now_iso(),
                        "level": "INFO",
                        "message": (
                            f"Job queued for {scope_desc} [{document_category}] "
                            f"from {start_date.isoformat()} to {end_date.isoformat()}."
                        ),
                    }
                ]
            )
            params = (
                job_uid,
                scope_key,
                location.court_type,
                location.state_code,
                location.state_name,
                location.district_code,
                location.district_name,
                location.complex_code,
                location.complex_name,
                location.establishment_code,
                location.establishment_name,
                location.court_code,
                location.court_name,
                location.bench_code,
                location.bench_name,
                document_category,
                start_date.isoformat() if is_sqlite else start_date,
                end_date.isoformat() if is_sqlite else end_date,
                preset_label,
                "queued",
                "Queued for execution",
                initial_logs,
                int(location.requires_manual_verification) if is_sqlite else location.requires_manual_verification,
                worker_id,
            )

            if is_sqlite:
                cur.execute(
                    """
                    INSERT INTO pi_scrape_jobs (
                        job_uid, scope_key, court_type, state_code, state_name,
                        district_code, district_name, complex_code, complex_name,
                        establishment_code, establishment_name, court_code, court_name,
                        bench_code, bench_name, document_category, start_date, end_date,
                        preset_label, status, current_step, log_entries,
                        requires_manual_verification, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    params,
                )
                cur.execute("SELECT * FROM pi_scrape_jobs WHERE job_uid = %s", (job_uid,))
                row = cur.fetchone()
            else:
                cur.execute(
                    """
                    INSERT INTO pi_scrape_jobs (
                        job_uid, scope_key, court_type, state_code, state_name,
                        district_code, district_name, complex_code, complex_name,
                        establishment_code, establishment_name, court_code, court_name,
                        bench_code, bench_name, document_category, start_date, end_date,
                        preset_label, status, current_step, log_entries,
                        requires_manual_verification, worker_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
                    )
                    RETURNING *
                    """,
                    params,
                )
                row = cur.fetchone()

        return self._serialize_job_row(row)

    def update_scrape_job(
        self,
        job_uid: str,
        log_message: Optional[str] = None,
        log_level: str = "INFO",
        **fields: Any,
    ) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, is_sqlite):
            cur.execute("SELECT * FROM pi_scrape_jobs WHERE job_uid = %s", (job_uid,))
            existing = cur.fetchone()
            if not existing:
                return None

            logs = _parse_json_field(existing.get("log_entries"), [])
            if log_message:
                logs.append(
                    {
                        "timestamp": _utc_now_iso(),
                        "level": log_level,
                        "message": log_message,
                    }
                )
                if len(logs) > 500:
                    logs = logs[-500:]
                fields["log_entries"] = json.dumps(logs)

            set_parts: List[str] = ["updated_at = NOW()"]
            params: List[Any] = []
            for k, v in fields.items():
                if k == "log_entries" and not is_sqlite:
                    set_parts.append("log_entries = %s::jsonb")
                    params.append(v if isinstance(v, str) else json.dumps(v))
                elif isinstance(v, bool) and is_sqlite:
                    set_parts.append(f"{k} = %s")
                    params.append(int(v))
                elif isinstance(v, datetime) and is_sqlite:
                    set_parts.append(f"{k} = %s")
                    params.append(v.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    set_parts.append(f"{k} = %s")
                    params.append(v)

            params.append(job_uid)
            cur.execute(
                f"UPDATE pi_scrape_jobs SET {', '.join(set_parts)} WHERE job_uid = %s",
                params,
            )
            cur.execute("SELECT * FROM pi_scrape_jobs WHERE job_uid = %s", (job_uid,))
            updated = cur.fetchone()
            return self._serialize_job_row(updated) if updated else None

    def get_scrape_job(self, job_id_or_uid: str | int) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            if str(job_id_or_uid).isdigit():
                cur.execute("SELECT * FROM pi_scrape_jobs WHERE id = %s", (int(job_id_or_uid),))
            else:
                cur.execute("SELECT * FROM pi_scrape_jobs WHERE job_uid = %s", (str(job_id_or_uid),))
            row = cur.fetchone()
            return self._serialize_job_row(row) if row else None

    def list_scrape_jobs(
        self,
        limit: int = 25,
        status: Optional[str] = None,
        court_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        limit = max(1, min(100, int(limit)))
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if court_type:
            clauses.append("court_type = %s")
            params.append(court_type)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.transaction() as (cur, _):
            cur.execute(
                f"SELECT * FROM pi_scrape_jobs {where_sql} ORDER BY created_at DESC, id DESC LIMIT %s",
                params + [limit],
            )
            rows = cur.fetchall()
        return [self._serialize_job_row(r) for r in rows]

    def recover_interrupted_jobs(self, resume: bool = False) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        recovered: List[Dict[str, Any]] = []
        with self.transaction() as (cur, is_sqlite):
            cur.execute(
                "SELECT * FROM pi_scrape_jobs WHERE status IN ('running', 'queued') ORDER BY id ASC"
            )
            stale_rows = cur.fetchall()
            for row in stale_rows:
                logs = _parse_json_field(row.get("log_entries"), [])
                new_status = "queued" if resume else "failed"
                msg = (
                    "Application restarted while job was active; job recovered and re-queued for resumption."
                    if resume
                    else "Application restarted while job was in progress; marked interrupted by startup recovery."
                )
                logs.append({"timestamp": _utc_now_iso(), "level": "WARN", "message": msg})
                log_json = json.dumps(logs)
                now_val = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if is_sqlite else datetime.now(timezone.utc)

                if is_sqlite:
                    cur.execute(
                        """
                        UPDATE pi_scrape_jobs
                        SET status = %s,
                            recovered_from_restart = 1,
                            current_step = %s,
                            error_summary = %s,
                            finished_at = %s,
                            updated_at = CURRENT_TIMESTAMP,
                            log_entries = %s
                        WHERE id = %s
                        """,
                        (
                            new_status,
                            "Recovered after restart" if resume else "Interrupted by restart",
                            None if resume else msg,
                            None if resume else now_val,
                            log_json,
                            row["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE pi_scrape_jobs
                        SET status = %s,
                            recovered_from_restart = TRUE,
                            current_step = %s,
                            error_summary = %s,
                            finished_at = %s,
                            updated_at = NOW(),
                            log_entries = %s::jsonb
                        WHERE id = %s
                        """,
                        (
                            new_status,
                            "Recovered after restart" if resume else "Interrupted by restart",
                            None if resume else msg,
                            None if resume else now_val,
                            log_json,
                            row["id"],
                        ),
                    )
                cur.execute("SELECT * FROM pi_scrape_jobs WHERE id = %s", (row["id"],))
                updated = cur.fetchone()
                if updated:
                    recovered.append(self._serialize_job_row(updated))
        return recovered

    @staticmethod
    def _serialize_job_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "job_uid": row["job_uid"],
            "scope_key": row["scope_key"],
            "court_type": row["court_type"],
            "state_code": row.get("state_code"),
            "state_name": row.get("state_name"),
            "district_code": row.get("district_code"),
            "district_name": row.get("district_name"),
            "complex_code": row.get("complex_code"),
            "complex_name": row.get("complex_name"),
            "establishment_code": row.get("establishment_code"),
            "establishment_name": row.get("establishment_name"),
            "court_code": row.get("court_code"),
            "court_name": row.get("court_name"),
            "bench_code": row.get("bench_code"),
            "bench_name": row.get("bench_name"),
            "document_category": row.get("document_category", "daily_cause_list"),
            "start_date": _fmt_date(row["start_date"]),
            "end_date": _fmt_date(row["end_date"]),
            "preset_label": row.get("preset_label", "custom"),
            "status": row["status"],
            "discovered_count": int(row.get("discovered_count") or 0),
            "downloaded_count": int(row.get("downloaded_count") or 0),
            "skipped_duplicate_count": int(row.get("skipped_duplicate_count") or 0),
            "extracted_doc_count": int(row.get("extracted_doc_count") or 0),
            "case_records_count": int(row.get("case_records_count") or 0),
            "failed_count": int(row.get("failed_count") or 0),
            "progress_pct": int(row.get("progress_pct") or 0),
            "current_step": row.get("current_step"),
            "log_entries": _parse_json_field(row.get("log_entries"), []),
            "error_summary": row.get("error_summary"),
            "limitation_notice": row.get("limitation_notice"),
            "requires_manual_verification": bool(row.get("requires_manual_verification")),
            "worker_id": row.get("worker_id"),
            "recovered_from_restart": bool(row.get("recovered_from_restart")),
            "created_at": _fmt_dt(row.get("created_at")),
            "started_at": _fmt_dt(row.get("started_at")),
            "updated_at": _fmt_dt(row.get("updated_at")),
            "finished_at": _fmt_dt(row.get("finished_at")),
        }

    # -------------------------------------------------------------------------
    # Documents & Extraction Persistence
    # -------------------------------------------------------------------------
    def get_document_by_identity(self, document_identity: str) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute("SELECT * FROM pi_documents WHERE document_identity = %s", (document_identity,))
            row = cur.fetchone()
            return self._serialize_document_row(row) if row else None

    def get_processed_document_by_sha256(self, content_sha256: str, exclude_doc_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            if exclude_doc_id is not None:
                cur.execute(
                    """
                    SELECT * FROM pi_documents
                    WHERE content_sha256 = %s
                      AND id <> %s
                      AND extraction_status IN ('completed', 'ocr_completed')
                    LIMIT 1
                    """,
                    (content_sha256, exclude_doc_id),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM pi_documents
                    WHERE content_sha256 = %s
                      AND extraction_status IN ('completed', 'ocr_completed')
                    LIMIT 1
                    """,
                    (content_sha256,),
                )
            row = cur.fetchone()
            return self._serialize_document_row(row) if row else None

    def register_discovered_document(
        self,
        doc: DiscoveredDocument,
        scrape_job_id: Optional[int],
        location_id: Optional[int],
    ) -> Tuple[Dict[str, Any], bool]:
        self.ensure_initialized()
        with self.transaction() as (cur, is_sqlite):
            cur.execute("SELECT * FROM pi_documents WHERE document_identity = %s", (doc.document_identity,))
            existing = cur.fetchone()
            if existing:
                already_done = (
                    existing.get("download_status") in ("downloaded", "already_processed", "duplicate_hash")
                    and existing.get("extraction_status") in ("completed", "ocr_completed")
                )
                return self._serialize_document_row(existing), already_done

            listing_date_val = doc.listing_date.isoformat() if is_sqlite else doc.listing_date
            order_date_val = (
                (doc.order_date.isoformat() if is_sqlite else doc.order_date)
                if getattr(doc, "order_date", None)
                else None
            )
            judgment_date_val = (
                (doc.judgment_date.isoformat() if is_sqlite else doc.judgment_date)
                if getattr(doc, "judgment_date", None)
                else None
            )
            doc_cat = getattr(doc, "document_category", "daily_cause_list") or "daily_cause_list"
            meta_json = json.dumps(getattr(doc, "source_metadata", {}) or {})

            params = (
                doc.document_identity,
                scrape_job_id,
                location_id,
                doc.court_type,
                doc.state_code,
                doc.state_name,
                doc.district_code,
                doc.district_name,
                getattr(doc, "complex_code", None),
                getattr(doc, "complex_name", None),
                getattr(doc, "establishment_code", None),
                getattr(doc, "establishment_name", None),
                doc.court_code,
                doc.court_name,
                doc.bench_code,
                doc.bench_name,
                doc_cat,
                listing_date_val,
                order_date_val,
                judgment_date_val,
                doc.cause_list_type,
                doc.coram_judge_raw,
                getattr(doc, "court_number", "") or "",
                getattr(doc, "diary_number", "") or "",
                getattr(doc, "source_portal", "") or "",
                doc.source_reference,
                doc.source_url,
                doc.pdf_filename,
                meta_json,
            )
            if is_sqlite:
                cur.execute(
                    """
                    INSERT INTO pi_documents (
                        document_identity, scrape_job_id, location_id,
                        court_type, state_code, state_name, district_code, district_name,
                        complex_code, complex_name, establishment_code, establishment_name,
                        court_code, court_name, bench_code, bench_name,
                        document_category, listing_date, order_date, judgment_date,
                        cause_list_type, coram_judge_raw, court_number, diary_number,
                        source_portal, source_reference, source_url, pdf_filename,
                        source_metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    params,
                )
                cur.execute("SELECT * FROM pi_documents WHERE document_identity = %s", (doc.document_identity,))
                row = cur.fetchone()
            else:
                cur.execute(
                    """
                    INSERT INTO pi_documents (
                        document_identity, scrape_job_id, location_id,
                        court_type, state_code, state_name, district_code, district_name,
                        complex_code, complex_name, establishment_code, establishment_name,
                        court_code, court_name, bench_code, bench_name,
                        document_category, listing_date, order_date, judgment_date,
                        cause_list_type, coram_judge_raw, court_number, diary_number,
                        source_portal, source_reference, source_url, pdf_filename,
                        source_metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::jsonb
                    )
                    RETURNING *
                    """,
                    params,
                )
                row = cur.fetchone()

        return self._serialize_document_row(row), False

    def record_download_outcome(
        self,
        document_id: int,
        download_status: str,
        content_sha256: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        storage_namespace: str = "pdf-intelligence/high-court",
        storage_object_key: Optional[str] = None,
        local_fallback_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self.ensure_initialized()
        with self.transaction() as (cur, is_sqlite):
            now_val = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if is_sqlite else datetime.now(timezone.utc)
            cur.execute(
                """
                UPDATE pi_documents
                SET download_status = %s,
                    content_sha256 = COALESCE(%s, content_sha256),
                    file_size_bytes = COALESCE(%s, file_size_bytes),
                    storage_namespace = %s,
                    storage_object_key = COALESCE(%s, storage_object_key),
                    local_fallback_path = COALESCE(%s, local_fallback_path),
                    last_error = %s,
                    downloaded_at = CASE WHEN %s = 'downloaded' THEN %s ELSE downloaded_at END,
                    extraction_status = CASE WHEN %s = 'failed' THEN 'failed' ELSE extraction_status END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    download_status,
                    content_sha256,
                    file_size_bytes,
                    storage_namespace,
                    storage_object_key,
                    local_fallback_path,
                    error_message,
                    download_status,
                    now_val,
                    download_status,
                    document_id,
                ),
            )

    def save_extraction_and_cases(
        self,
        document_id: int,
        scrape_job_id: Optional[int],
        extraction: PDFExtractionResult,
        parsed_cases: List[ParsedCaseRecord],
        increment_retry: bool = False,
    ) -> Dict[str, Any]:
        """
        Atomically record an extraction job attempt, replace any existing case
        records for `document_id` (preventing duplicates on reprocessing), and
        update the parent `pi_documents` row.
        """
        self.ensure_initialized()
        with self.transaction() as (cur, is_sqlite):
            cur.execute("SELECT * FROM pi_documents WHERE id = %s", (document_id,))
            doc_row = cur.fetchone()
            if not doc_row:
                raise ValueError(f"Document id {document_id} does not exist")

            cur.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) AS max_att FROM pi_extraction_jobs WHERE document_id = %s",
                (document_id,),
            )
            attempt_no = int((cur.fetchone() or {}).get("max_att") or 0) + 1
            now_val = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if is_sqlite else datetime.now(timezone.utc)

            ej_status = "completed" if extraction.success else "failed"
            cur.execute(
                """
                INSERT INTO pi_extraction_jobs (
                    document_id, scrape_job_id, attempt_number, status,
                    extraction_method, used_ocr, pages_processed, extracted_chars,
                    cases_extracted, confidence_score, error_message, finished_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    scrape_job_id,
                    attempt_no,
                    ej_status,
                    extraction.extraction_method,
                    int(extraction.used_ocr) if is_sqlite else extraction.used_ocr,
                    extraction.page_count,
                    extraction.total_chars,
                    len(parsed_cases),
                    extraction.confidence_score,
                    extraction.error_message,
                    now_val,
                ),
            )

            # Remove previous case records for this document so re-extraction never duplicates cases
            cur.execute("DELETE FROM pi_case_records WHERE document_id = %s", (document_id,))

            doc_category = doc_row.get("document_category") or "daily_cause_list"

            for case in parsed_cases:
                details_json = json.dumps(case.extracted_details or {})
                listing_dt_val = case.listing_date if is_sqlite else date.fromisoformat(case.listing_date)
                o_dt_val = (
                    (case.order_date if is_sqlite else date.fromisoformat(case.order_date))
                    if getattr(case, "order_date", None)
                    else None
                )
                j_dt_val = (
                    (case.judgment_date if is_sqlite else date.fromisoformat(case.judgment_date))
                    if case.judgment_date
                    else None
                )
                params = (
                    document_id,
                    doc_row.get("location_id"),
                    case.case_sequence,
                    getattr(case, "document_category", doc_category) or doc_category,
                    case.item_number,
                    case.case_number,
                    case.case_type,
                    case.case_year,
                    case.cnr_number,
                    getattr(case, "diary_number", "") or doc_row.get("diary_number") or "",
                    getattr(case, "filing_number", "") or "",
                    case.case_title,
                    case.petitioner,
                    case.respondent,
                    case.advocates,
                    getattr(case, "advocate_on_record", "") or "",
                    listing_dt_val,
                    o_dt_val,
                    j_dt_val,
                    case.judge_names or doc_row.get("coram_judge_raw") or "",
                    case.court_room or doc_row.get("court_number") or "",
                    doc_row["court_type"],
                    doc_row.get("state_code"),
                    doc_row.get("state_name"),
                    doc_row.get("district_code"),
                    doc_row.get("district_name"),
                    doc_row.get("complex_code"),
                    doc_row.get("complex_name"),
                    doc_row.get("establishment_code"),
                    doc_row.get("establishment_name"),
                    doc_row["court_code"],
                    doc_row["court_name"],
                    doc_row["bench_code"],
                    doc_row["bench_name"],
                    doc_row["pdf_filename"],
                    case.page_number,
                    case.extraction_status,
                    case.confidence,
                    case.confidence_label,
                    case.raw_excerpt,
                    details_json,
                )
                if is_sqlite:
                    cur.execute(
                        """
                        INSERT INTO pi_case_records (
                            document_id, location_id, case_sequence, document_category,
                            item_number, case_number, case_type, case_year,
                            cnr_number, diary_number, filing_number,
                            case_title, petitioner, respondent, advocates, advocate_on_record,
                            listing_date, order_date, judgment_date, judge_names, court_room,
                            court_type, state_code, state_name, district_code, district_name,
                            complex_code, complex_name, establishment_code, establishment_name,
                            court_code, court_name, bench_code, bench_name,
                            pdf_filename, page_number, extraction_status, confidence,
                            confidence_label, raw_excerpt, extracted_details
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        params,
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO pi_case_records (
                            document_id, location_id, case_sequence, document_category,
                            item_number, case_number, case_type, case_year,
                            cnr_number, diary_number, filing_number,
                            case_title, petitioner, respondent, advocates, advocate_on_record,
                            listing_date, order_date, judgment_date, judge_names, court_room,
                            court_type, state_code, state_name, district_code, district_name,
                            complex_code, complex_name, establishment_code, establishment_name,
                            court_code, court_name, bench_code, bench_name,
                            pdf_filename, page_number, extraction_status, confidence,
                            confidence_label, raw_excerpt, extracted_details
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                        )
                        """,
                        params,
                    )

            avg_conf = (
                round(sum(c.confidence for c in parsed_cases) / len(parsed_cases), 4)
                if parsed_cases
                else extraction.confidence_score
            )
            doc_ext_status = extraction.status if extraction.success else "failed"

            cur.execute(
                """
                UPDATE pi_documents
                SET page_count = %s,
                    extraction_status = %s,
                    extraction_method = %s,
                    extraction_confidence = %s,
                    case_count = %s,
                    retry_count = retry_count + %s,
                    last_error = %s,
                    processed_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    extraction.page_count,
                    doc_ext_status,
                    extraction.extraction_method,
                    avg_conf,
                    len(parsed_cases),
                    1 if increment_retry else 0,
                    extraction.error_message,
                    now_val,
                    document_id,
                ),
            )
            cur.execute("SELECT * FROM pi_documents WHERE id = %s", (document_id,))
            updated_doc = cur.fetchone()

        return self._serialize_document_row(updated_doc)

    def get_document(self, document_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute("SELECT * FROM pi_documents WHERE id = %s", (int(document_id),))
            row = cur.fetchone()
            return self._serialize_document_row(row) if row else None

    def list_documents(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        court_type: Optional[str] = None,
        court_code: Optional[str] = None,
        bench_code: Optional[str] = None,
        complex_code: Optional[str] = None,
        establishment_code: Optional[str] = None,
        document_category: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        listing_date: Optional[str] = None,
        extraction_status: Optional[str] = None,
        scrape_job_id: Optional[int] = None,
        query: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        clauses: List[str] = []
        params: List[Any] = []

        if court_type:
            clauses.append("court_type = %s")
            params.append(court_type.strip().lower())
        if state_code:
            clauses.append("UPPER(state_code) = UPPER(%s)")
            params.append(state_code.strip())
        if district_code:
            clauses.append("UPPER(district_code) = UPPER(%s)")
            params.append(district_code.strip())
        if complex_code:
            clauses.append("UPPER(complex_code) = UPPER(%s)")
            params.append(complex_code.strip())
        if establishment_code:
            clauses.append("(UPPER(establishment_code) = UPPER(%s) OR UPPER(bench_code) = UPPER(%s))")
            params.extend([establishment_code.strip(), establishment_code.strip()])
        if court_code:
            clauses.append("UPPER(court_code) = UPPER(%s)")
            params.append(court_code.strip())
        if bench_code:
            clauses.append("UPPER(bench_code) = UPPER(%s)")
            params.append(bench_code.strip())
        if document_category:
            clauses.append("document_category = %s")
            params.append(document_category.strip())
        if listing_date:
            clauses.append("listing_date = %s")
            params.append(listing_date.strip())
        if start_date:
            clauses.append("listing_date >= %s")
            params.append(start_date.strip())
        if end_date:
            clauses.append("listing_date <= %s")
            params.append(end_date.strip())
        if extraction_status:
            clauses.append("extraction_status = %s")
            params.append(extraction_status.strip())
        if scrape_job_id is not None:
            clauses.append("scrape_job_id = %s")
            params.append(int(scrape_job_id))
        if query and query.strip():
            q = f"%{query.strip()}%"
            clauses.append("(pdf_filename ILIKE %s OR coram_judge_raw ILIKE %s OR bench_name ILIKE %s)")
            params.extend([q, q, q])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        page = max(1, int(page))
        limit = max(1, min(200, int(limit)))
        offset = (page - 1) * limit

        with self.transaction() as (cur, _):
            cur.execute(f"SELECT COUNT(*) AS total FROM pi_documents {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute(
                f"""
                SELECT * FROM pi_documents
                {where_sql}
                ORDER BY listing_date DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

        total_pages = math.ceil(total / limit) if total > 0 else 1
        return {
            "items": [self._serialize_document_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

    @staticmethod
    def _serialize_document_row(row: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = int(row["id"])
        return {
            "id": doc_id,
            "document_identity": row["document_identity"],
            "scrape_job_id": int(row["scrape_job_id"]) if row.get("scrape_job_id") is not None else None,
            "location_id": int(row["location_id"]) if row.get("location_id") is not None else None,
            "court_type": row["court_type"],
            "state_code": row.get("state_code"),
            "state_name": row.get("state_name"),
            "district_code": row.get("district_code"),
            "district_name": row.get("district_name"),
            "complex_code": row.get("complex_code"),
            "complex_name": row.get("complex_name"),
            "establishment_code": row.get("establishment_code"),
            "establishment_name": row.get("establishment_name"),
            "court_code": row["court_code"],
            "court_name": row["court_name"],
            "bench_code": row["bench_code"],
            "bench_name": row["bench_name"],
            "document_category": row.get("document_category", "daily_cause_list"),
            "listing_date": _fmt_date(row["listing_date"]),
            "order_date": _fmt_date(row.get("order_date")),
            "judgment_date": _fmt_date(row.get("judgment_date")),
            "cause_list_type": row.get("cause_list_type"),
            "coram_judge_raw": row.get("coram_judge_raw"),
            "court_number": row.get("court_number"),
            "diary_number": row.get("diary_number"),
            "source_portal": row.get("source_portal"),
            "source_reference": row["source_reference"],
            "source_url": row["source_url"],
            "pdf_filename": row["pdf_filename"],
            "storage_namespace": row.get("storage_namespace", "pdf-intelligence/high-court"),
            "storage_object_key": row.get("storage_object_key"),
            "local_fallback_path": row.get("local_fallback_path"),
            "content_sha256": row.get("content_sha256"),
            "file_size_bytes": int(row["file_size_bytes"]) if row.get("file_size_bytes") is not None else 0,
            "page_count": int(row["page_count"]) if row.get("page_count") is not None else 0,
            "download_status": row["download_status"],
            "extraction_status": row["extraction_status"],
            "extraction_method": row.get("extraction_method"),
            "extraction_confidence": float(row["extraction_confidence"]) if row.get("extraction_confidence") is not None else None,
            "case_count": int(row.get("case_count") or 0),
            "retry_count": int(row.get("retry_count") or 0),
            "last_error": row.get("last_error"),
            "source_metadata": _parse_json_field(row.get("source_metadata"), {}),
            "original_pdf_link": f"/api/pdf-intelligence/documents/{doc_id}/file",
            "discovered_at": _fmt_dt(row.get("discovered_at")),
            "downloaded_at": _fmt_dt(row.get("downloaded_at")),
            "processed_at": _fmt_dt(row.get("processed_at")),
        }

    # -------------------------------------------------------------------------
    # Case Records Query, Filtering, Sorting, Pagination & CSV Export
    # -------------------------------------------------------------------------
    def list_case_records(
        self,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        court_type: Optional[str] = None,
        court_code: Optional[str] = None,
        bench_code: Optional[str] = None,
        complex_code: Optional[str] = None,
        establishment_code: Optional[str] = None,
        document_category: Optional[str] = None,
        document_id: Optional[int] = None,
        case_type: Optional[str] = None,
        judge: Optional[str] = None,
        extraction_status: Optional[str] = None,
        listing_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query: Optional[str] = None,
        sort_by: str = "listing_date",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 25,
    ) -> Dict[str, Any]:
        self.ensure_initialized()
        clauses: List[str] = []
        params: List[Any] = []

        if court_type:
            clauses.append("court_type = %s")
            params.append(court_type.strip().lower())
        if state_code:
            clauses.append("UPPER(state_code) = UPPER(%s)")
            params.append(state_code.strip())
        if district_code:
            clauses.append("UPPER(district_code) = UPPER(%s)")
            params.append(district_code.strip())
        if complex_code:
            clauses.append("UPPER(complex_code) = UPPER(%s)")
            params.append(complex_code.strip())
        if establishment_code:
            clauses.append("(UPPER(establishment_code) = UPPER(%s) OR UPPER(bench_code) = UPPER(%s))")
            params.extend([establishment_code.strip(), establishment_code.strip()])
        if court_code:
            clauses.append("UPPER(court_code) = UPPER(%s)")
            params.append(court_code.strip())
        if bench_code:
            clauses.append("UPPER(bench_code) = UPPER(%s)")
            params.append(bench_code.strip())
        if document_category:
            clauses.append("document_category = %s")
            params.append(document_category.strip())
        if document_id is not None:
            clauses.append("document_id = %s")
            params.append(int(document_id))
        if case_type:
            clauses.append("UPPER(case_type) = UPPER(%s)")
            params.append(case_type.strip())
        if judge:
            clauses.append("judge_names ILIKE %s")
            params.append(f"%{judge.strip()}%")
        if extraction_status:
            clauses.append("extraction_status = %s")
            params.append(extraction_status.strip())
        if listing_date:
            clauses.append("listing_date = %s")
            params.append(listing_date.strip())
        if start_date:
            clauses.append("listing_date >= %s")
            params.append(start_date.strip())
        if end_date:
            clauses.append("listing_date <= %s")
            params.append(end_date.strip())
        if query and query.strip():
            q = f"%{query.strip()}%"
            clauses.append(
                "(case_number ILIKE %s OR case_title ILIKE %s OR petitioner ILIKE %s "
                "OR respondent ILIKE %s OR judge_names ILIKE %s OR pdf_filename ILIKE %s "
                "OR cnr_number ILIKE %s OR diary_number ILIKE %s OR filing_number ILIKE %s)"
            )
            params.extend([q, q, q, q, q, q, q, q, q])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        allowed_sorts = {
            "listing_date": "listing_date",
            "case_number": "case_number",
            "case_title": "case_title",
            "case_type": "case_type",
            "petitioner": "petitioner",
            "respondent": "respondent",
            "judge_names": "judge_names",
            "confidence": "confidence",
            "order_date": "order_date",
            "judgment_date": "judgment_date",
            "pdf_filename": "pdf_filename",
        }
        sort_col = allowed_sorts.get(sort_by, "listing_date")
        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"

        page = max(1, int(page))
        limit = max(1, min(1000, int(limit)))
        offset = (page - 1) * limit

        with self.transaction() as (cur, _):
            cur.execute(f"SELECT COUNT(*) AS total FROM pi_case_records {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)

            cur.execute(
                f"""
                SELECT * FROM pi_case_records
                {where_sql}
                ORDER BY {sort_col} {direction}, id ASC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

            cur.execute("SELECT DISTINCT case_type FROM pi_case_records ORDER BY case_type ASC")
            available_types = [r["case_type"] for r in cur.fetchall() if r.get("case_type")]

        total_pages = math.ceil(total / limit) if total > 0 else 1
        return {
            "items": [self._serialize_case_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "available_case_types": available_types,
        }

    def get_case_record(self, case_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_initialized()
        with self.transaction() as (cur, _):
            cur.execute("SELECT * FROM pi_case_records WHERE id = %s", (int(case_id),))
            row = cur.fetchone()
            return self._serialize_case_row(row) if row else None

    @staticmethod
    def _serialize_case_row(row: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = int(row["document_id"])
        return {
            "id": int(row["id"]),
            "document_id": doc_id,
            "location_id": int(row["location_id"]) if row.get("location_id") is not None else None,
            "case_sequence": int(row["case_sequence"]),
            "document_category": row.get("document_category") or "daily_cause_list",
            "item_number": row.get("item_number") or "",
            "case_number": row["case_number"],
            "case_title": row["case_title"],
            "petitioner": row.get("petitioner") or "",
            "respondent": row.get("respondent") or "",
            "advocates": row.get("advocates") or "",
            "advocate_on_record": row.get("advocate_on_record") or "",
            "case_type": row["case_type"],
            "case_year": int(row["case_year"]) if row.get("case_year") is not None else None,
            "cnr_number": row.get("cnr_number") or "",
            "diary_number": row.get("diary_number") or "",
            "filing_number": row.get("filing_number") or "",
            "listing_date": _fmt_date(row["listing_date"]),
            "order_date": _fmt_date(row.get("order_date")),
            "judgment_date": _fmt_date(row.get("judgment_date")),
            "judge_names": row.get("judge_names") or "",
            "court_room": row.get("court_room") or "",
            "court_type": row["court_type"],
            "state_code": row.get("state_code"),
            "state_name": row.get("state_name"),
            "district_code": row.get("district_code"),
            "district_name": row.get("district_name"),
            "complex_code": row.get("complex_code"),
            "complex_name": row.get("complex_name"),
            "establishment_code": row.get("establishment_code"),
            "establishment_name": row.get("establishment_name"),
            "court_code": row["court_code"],
            "court_name": row["court_name"],
            "bench_code": row["bench_code"],
            "bench_name": row["bench_name"],
            "pdf_filename": row["pdf_filename"],
            "page_number": int(row["page_number"]) if row.get("page_number") is not None else 1,
            "extraction_status": row["extraction_status"],
            "confidence": float(row["confidence"]),
            "confidence_pct": round(float(row["confidence"]) * 100, 1),
            "confidence_label": row.get("confidence_label") or "high",
            "original_pdf_link": f"/api/pdf-intelligence/documents/{doc_id}/file",
            "raw_excerpt": row.get("raw_excerpt") or "",
            "extracted_details": _parse_json_field(row.get("extracted_details"), {}),
        }


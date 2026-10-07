"""
Data Service for eCourts Judicial Intelligence & Document Explorer
Uses strictly the confirmed PostgreSQL queries and local PDF storage.
Zero PDF-content parsing, zero fake metrics.
"""

import os
import re
import time
import math
from datetime import datetime, date
import psycopg2
from psycopg2.extras import RealDictCursor

from court_mapper import HIGH_COURTS
import storage_service

POSTGRES_CONFIG = {
    "host": os.getenv("DB_HOST", "db.dvsjnzrouwywaqcacwsl.supabase.co"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD")
}
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "downloaded_pdfs")

# Build court mapping lookup
COURT_LOOKUP = {}
for state_code, court_code, state_name, bench_name in HIGH_COURTS:
    s_key = str(state_code)
    c_key = str(court_code) if court_code is not None else "1"
    COURT_LOOKUP[(s_key, c_key)] = {
        "state_name": state_name,
        "court_name": bench_name
    }

def get_court_info(state_code, court_code):
    s_key = str(state_code) if state_code is not None else "1"
    c_key = str(court_code) if court_code is not None else "1"
    info = COURT_LOOKUP.get((s_key, c_key))
    if not info:
        info = {
            "state_name": f"State {s_key}",
            "court_name": f"Court {c_key}"
        }
    return info

def get_db_connection():
    try:
        if DATABASE_URL:
            return psycopg2.connect(
                DATABASE_URL,
                connect_timeout=4,
                sslmode=os.getenv("DB_SSLMODE") or "require"
            )

        conn = psycopg2.connect(
            host=POSTGRES_CONFIG["host"],
            port=POSTGRES_CONFIG["port"],
            database=POSTGRES_CONFIG["database"],
            user=POSTGRES_CONFIG["user"],
            password=POSTGRES_CONFIG["password"],
            connect_timeout=4,
            sslmode=os.getenv("DB_SSLMODE") or "require"
        )
        return conn
    except Exception as e:
        print(f"[DB Warning] Connection to PostgreSQL failed: {e}", flush=True)
        return None

# Disk PDF indexing with fast cache
_DISK_CACHE = {
    "files": {},
    "last_scanned": 0
}

def get_disk_pdf_index(force=False):
    now = time.time()
    if not force and _DISK_CACHE["files"] and (now - _DISK_CACHE["last_scanned"] < 30):
        return _DISK_CACHE["files"]

    files_map = {}
    if os.path.isdir(PDF_DIR):
        for root, _, filenames in os.walk(PDF_DIR):
            for fn in filenames:
                if fn.lower().endswith(".pdf"):
                    full_path = os.path.join(root, fn)
                    rel_path = os.path.relpath(full_path, PDF_DIR).replace("\\", "/")
                    try:
                        sz = os.path.getsize(full_path)
                    except OSError:
                        sz = 0
                    files_map[fn] = {
                        "filename": fn,
                        "rel_path": rel_path,
                        "full_path": full_path,
                        "file_size": sz
                    }

    _DISK_CACHE["files"] = files_map
    _DISK_CACHE["last_scanned"] = now
    return files_map

def compute_expected_filename(cause_list_date, reference_name):
    if not reference_name:
        return None
    dstr = cause_list_date.strftime("%Y%m%d") if hasattr(cause_list_date, "strftime") else str(cause_list_date).replace("-", "")
    safe_ref = "".join(c for c in reference_name if c.isalnum() or c in "._- ")
    return f"{dstr}_{safe_ref}.pdf"

def get_safe_pdf_path(filename_or_rel):
    """
    Safely locates a PDF file on disk.
    Prevents path traversal and confirms the file is inside PDF_DIR.
    """
    if not filename_or_rel:
        return None

    # Disallow traversal tokens
    if ".." in filename_or_rel or filename_or_rel.startswith(("/", "\\")):
        return None

    disk_index = get_disk_pdf_index()

    # 1. Exact filename lookup in disk index
    base_name = os.path.basename(filename_or_rel)
    if base_name in disk_index:
        full_path = disk_index[base_name]["full_path"]
        if os.path.isfile(full_path) and os.path.commonpath([PDF_DIR, full_path]) == PDF_DIR:
            return full_path

    # 2. Check direct relative path
    candidate = os.path.normpath(os.path.join(PDF_DIR, filename_or_rel))
    if os.path.isfile(candidate) and os.path.commonpath([PDF_DIR, candidate]) == PDF_DIR:
        return candidate

    return None

def get_overview_stats():
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Overview KPIs
        cur.execute("""
            SELECT
                COUNT(DISTINCT judge_name) AS total_judges,
                COUNT(*) AS total_pdfs,
                MIN(cause_list_date) AS first_seen,
                MAX(cause_list_date) AS last_seen
            FROM ecourts_pdfs
            WHERE judge_name IS NOT NULL
              AND TRIM(judge_name) <> '';
        """)
        overview_row = cur.fetchone() or {}

        # 2. Judge Activity (Query 1 - top judges by total PDFs)
        cur.execute("""
            SELECT
                judge_name,
                COUNT(*) AS total_pdfs,
                MIN(cause_list_date) AS first_seen,
                MAX(cause_list_date) AS last_seen
            FROM ecourts_pdfs
            WHERE judge_name IS NOT NULL
              AND TRIM(judge_name) <> ''
            GROUP BY judge_name
            ORDER BY total_pdfs DESC
            LIMIT 15;
        """)
        top_judges = cur.fetchall()

        # 3. Recent Activity (Query 3 - judge activity by date)
        cur.execute("""
            SELECT
                judge_name,
                cause_list_date,
                COUNT(*) AS pdf_count
            FROM ecourts_pdfs
            WHERE judge_name IS NOT NULL
            GROUP BY judge_name, cause_list_date
            ORDER BY cause_list_date DESC, pdf_count DESC
            LIMIT 25;
        """)
        recent_activity = cur.fetchall()

        # 4. Court Activity (Query 2 - aggregated across judges)
        cur.execute("""
            SELECT
                state_code,
                district_code,
                court_code,
                COUNT(*) AS pdf_count,
                COUNT(DISTINCT judge_name) AS judges_count
            FROM ecourts_pdfs
            GROUP BY state_code, district_code, court_code
            ORDER BY pdf_count DESC;
        """)
        raw_courts = cur.fetchall()

        court_activity = []
        for c in raw_courts:
            info = get_court_info(c["state_code"], c["court_code"])
            court_activity.append({
                "state_code": c["state_code"],
                "district_code": c["district_code"] or "All",
                "court_code": c["court_code"] or "1",
                "state_name": info["state_name"],
                "court_name": info["court_name"],
                "pdf_count": c["pdf_count"],
                "judges_count": c["judges_count"]
            })

        # Disk PDF count
        disk_index = get_disk_pdf_index()

        cur.close()
        conn.close()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        return {
            "total_judges": overview_row.get("total_judges", 0),
            "total_pdfs": overview_row.get("total_pdfs", 0),
            "downloaded_pdfs_count": len(disk_index),
            "first_seen": fmt_date(overview_row.get("first_seen")),
            "last_seen": fmt_date(overview_row.get("last_seen")),
            "top_judges": [
                {
                    "judge_name": r["judge_name"],
                    "total_pdfs": r["total_pdfs"],
                    "first_seen": fmt_date(r["first_seen"]),
                    "last_seen": fmt_date(r["last_seen"])
                }
                for r in top_judges
            ],
            "recent_activity": [
                {
                    "date": fmt_date(r["cause_list_date"]),
                    "judge_name": r["judge_name"],
                    "pdf_count": r["pdf_count"]
                }
                for r in recent_activity
            ],
            "court_activity": court_activity
        }
    except Exception as e:
        if conn: conn.close()
        raise e

def get_judges(query=None, sort_by="total_pdfs", sort_order="desc", page=1, limit=20):
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        allowed_sorts = {
            "total_pdfs": "total_pdfs",
            "first_seen": "first_seen",
            "last_seen": "last_seen",
            "judge_name": "judge_name"
        }
        sort_col = allowed_sorts.get(sort_by, "total_pdfs")
        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"

        where_clauses = ["judge_name IS NOT NULL", "TRIM(judge_name) <> ''"]
        params = []

        if query and query.strip():
            where_clauses.append("judge_name ILIKE %s")
            params.append(f"%{query.strip()}%")

        where_sql = " AND ".join(where_clauses)

        # Count total matching judges
        count_sql = f"""
            SELECT COUNT(*) AS total FROM (
                SELECT judge_name
                FROM ecourts_pdfs
                WHERE {where_sql}
                GROUP BY judge_name
            ) AS sub;
        """
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]

        # Pagination
        page = max(1, int(page))
        limit = max(1, min(100, int(limit)))
        offset = (page - 1) * limit
        total_pages = math.ceil(total / limit) if total > 0 else 1

        # Query 1
        query_sql = f"""
            SELECT
                judge_name,
                COUNT(*) AS total_pdfs,
                MIN(cause_list_date) AS first_seen,
                MAX(cause_list_date) AS last_seen
            FROM ecourts_pdfs
            WHERE {where_sql}
            GROUP BY judge_name
            ORDER BY {sort_col} {direction}, judge_name ASC
            LIMIT %s OFFSET %s;
        """
        cur.execute(query_sql, params + [limit, offset])
        rows = cur.fetchall()

        cur.close()
        conn.close()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        items = [
            {
                "judge_name": r["judge_name"],
                "total_pdfs": r["total_pdfs"],
                "first_seen": fmt_date(r["first_seen"]),
                "last_seen": fmt_date(r["last_seen"])
            }
            for r in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }
    except Exception as e:
        if conn: conn.close()
        raise e


def get_judge_directory(query=None, court="all", sort_by="record_count", sort_order="desc", page=1, limit=20):
    """Return one searchable directory combining Supreme Court and other-court judges."""
    court = court if court in {"all", "supreme", "other"} else "all"
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT to_regclass('public.supreme_court_judges') AS judges_table")
        has_supreme_judges = cur.fetchone()["judges_table"] is not None

        conditions = []
        params = []
        if query and query.strip():
            conditions.append("judge_name ILIKE %s")
            params.append(f"%{query.strip()}%")
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        page = max(1, int(page))
        limit = max(1, min(100, int(limit)))

        if court == "supreme" and not has_supreme_judges:
            cur.close()
            conn.close()
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "total_pages": 1
            }

        sources = []
        if court in {"all", "supreme"} and has_supreme_judges:
            sources.append(f"""
                SELECT
                    judge_name,
                    total_cases AS record_count,
                    earliest_judgment AS first_seen,
                    latest_judgment AS last_seen,
                    ARRAY['Supreme Court of India']::text[] AS court_keys,
                    'supreme_court'::text AS court_type
                FROM supreme_court_judges
                {where_sql}
            """)

        if court in {"all", "other"}:
            if query and query.strip():
                other_where = "AND p.judge_name ILIKE %s"
            else:
                other_where = ""
            supreme_exclusion = """
                  AND NOT EXISTS (
                      SELECT 1
                      FROM supreme_court_judges scj
                      WHERE UPPER(TRIM(scj.judge_name)) = UPPER(TRIM(p.judge_name))
                  )
            """ if has_supreme_judges else ""
            sources.append(f"""
                SELECT
                    p.judge_name,
                    COUNT(*) AS record_count,
                    MIN(p.cause_list_date) AS first_seen,
                    MAX(p.cause_list_date) AS last_seen,
                    ARRAY_AGG(DISTINCT COALESCE(p.state_code::text, '1') || '|' ||
                        COALESCE(p.court_code::text, '1')) AS court_keys,
                    'other_court'::text AS court_type
                FROM ecourts_pdfs p
                WHERE p.judge_name IS NOT NULL
                  AND TRIM(p.judge_name) <> ''
                  {supreme_exclusion}
                  {other_where}
                GROUP BY p.judge_name
            """)

        sort_columns = {
            "record_count": "record_count",
            "total_pdfs": "record_count",
            "total_cases": "record_count",
            "judge_name": "judge_name",
            "first_seen": "first_seen",
            "earliest_judgment": "first_seen",
            "last_seen": "last_seen",
            "latest_judgment": "last_seen"
        }
        sort_col = sort_columns.get(sort_by, "record_count")
        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
        union_sql = " UNION ALL ".join(sources)
        query_params = params * len(sources)

        cur.execute(f"""
            WITH directory AS ({union_sql})
            SELECT COUNT(*) AS total FROM directory;
        """, query_params)
        total = cur.fetchone()["total"]

        offset = (page - 1) * limit
        total_pages = math.ceil(total / limit) if total else 1

        cur.execute(f"""
            WITH directory AS ({union_sql})
            SELECT judge_name, record_count, first_seen, last_seen, court_keys, court_type
            FROM directory
            ORDER BY {sort_col} {direction}, judge_name ASC
            LIMIT %s OFFSET %s;
        """, query_params + [limit, offset])
        rows = cur.fetchall()
        cur.close()
        conn.close()

        def fmt_date(value):
            return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else (str(value) if value else "")

        items = []
        for row in rows:
            if row["court_type"] == "supreme_court":
                court_name = "Supreme Court of India"
            else:
                court_names = set()
                for key in row["court_keys"] or []:
                    state_code, _, court_code = key.partition("|")
                    court_info = get_court_info(state_code, court_code)
                    court_names.add(court_info["court_name"])
                court_name = ", ".join(sorted(court_names)) or "Court assignment unavailable"

            items.append({
                "judge_name": row["judge_name"],
                "record_count": row["record_count"],
                "first_seen": fmt_date(row["first_seen"]),
                "last_seen": fmt_date(row["last_seen"]),
                "court_name": court_name,
                "court_type": row["court_type"]
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }
    except Exception:
        conn.close()
        raise


def get_judge_detail(judge_name, start_date=None, end_date=None):
    if not judge_name:
        return None

    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Judge summary (Query 1 filtered by judge)
        cur.execute("""
            SELECT
                judge_name,
                COUNT(*) AS total_pdfs,
                MIN(cause_list_date) AS first_seen,
                MAX(cause_list_date) AS last_seen
            FROM ecourts_pdfs
            WHERE judge_name = %s
            GROUP BY judge_name;
        """, (judge_name,))
        summary_row = cur.fetchone()

        if not summary_row:
            cur.close()
            conn.close()
            return None

        # 2. Judge + court (Query 2)
        cur.execute("""
            SELECT
                judge_name,
                state_code,
                district_code,
                court_code,
                COUNT(*) AS pdf_count
            FROM ecourts_pdfs
            WHERE judge_name = %s
            GROUP BY
                judge_name,
                state_code,
                district_code,
                court_code
            ORDER BY pdf_count DESC;
        """, (judge_name,))
        courts_rows = cur.fetchall()

        courts_list = []
        for c in courts_rows:
            info = get_court_info(c["state_code"], c["court_code"])
            courts_list.append({
                "state_code": c["state_code"],
                "district_code": c["district_code"] or "All",
                "court_code": c["court_code"] or "1",
                "state_name": info["state_name"],
                "court_name": info["court_name"],
                "pdf_count": c["pdf_count"]
            })

        # 3. Judge activity by date (Query 3)
        activity_where = ["judge_name = %s"]
        activity_params = [judge_name]
        if start_date:
            activity_where.append("cause_list_date >= %s")
            activity_params.append(start_date)
        if end_date:
            activity_where.append("cause_list_date <= %s")
            activity_params.append(end_date)

        cur.execute(f"""
            SELECT
                judge_name,
                cause_list_date,
                COUNT(*) AS pdf_count
            FROM ecourts_pdfs
            WHERE {" AND ".join(activity_where)}
            GROUP BY judge_name, cause_list_date
            ORDER BY cause_list_date ASC;
        """, activity_params)
        activity_rows = cur.fetchall()

        # 4. Actual PDFs for this judge
        cur.execute("""
            SELECT
                id,
                judge_name,
                cause_list_date,
                reference_name,
                state_code,
                district_code,
                court_code
            FROM ecourts_pdfs
            WHERE judge_name = %s
            ORDER BY cause_list_date DESC, id DESC;
        """, (judge_name,))
        pdf_rows = cur.fetchall()

        cur.close()
        conn.close()

        disk_index = get_disk_pdf_index()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        pdfs_list = []
        for r in pdf_rows:
            cdate = r["cause_list_date"]
            expected_fn = compute_expected_filename(cdate, r["reference_name"])
            disk_info = disk_index.get(expected_fn)
            storage_info = (
                storage_service.get_pdf_object_info(expected_fn)
                if expected_fn else None
            )
            info = get_court_info(r["state_code"], r["court_code"])

            pdfs_list.append({
                "id": r["id"],
                "filename": expected_fn or f"doc_{r['id']}.pdf",
                "cause_list_date": fmt_date(cdate),
                "reference_name": r["reference_name"],
                "state_code": r["state_code"],
                "district_code": r["district_code"] or "All",
                "court_code": r["court_code"] or "1",
                "state_name": info["state_name"],
                "court_name": info["court_name"],
                "has_file": bool(disk_info or storage_info),
                "file_size": (
                    disk_info["file_size"] if disk_info
                    else storage_info["file_size"] if storage_info else 0
                ),
                "rel_path": disk_info["rel_path"] if disk_info else None
            })

        return {
            "summary": {
                "judge_name": summary_row["judge_name"],
                "total_pdfs": summary_row["total_pdfs"],
                "first_seen": fmt_date(summary_row["first_seen"]),
                "last_seen": fmt_date(summary_row["last_seen"]),
                "courts_count": len(courts_list)
            },
            "courts": courts_list,
            "activity": [
                {
                    "date": fmt_date(r["cause_list_date"]),
                    "pdf_count": r["pdf_count"]
                }
                for r in activity_rows
            ],
            "pdfs": pdfs_list
        }
    except Exception as e:
        if conn: conn.close()
        raise e

def get_pdfs(query=None, judge=None, date_filter=None, court_code=None, state_code=None, page=1, limit=50):
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where_clauses = []
        params = []

        if judge and judge.strip():
            where_clauses.append("judge_name = %s")
            params.append(judge.strip())

        if date_filter and date_filter.strip():
            where_clauses.append("cause_list_date = %s")
            params.append(date_filter.strip())

        if court_code and court_code.strip():
            where_clauses.append("court_code = %s")
            params.append(court_code.strip())

        if state_code and state_code.strip():
            where_clauses.append("state_code = %s")
            params.append(state_code.strip())

        if query and query.strip():
            q_clean = f"%{query.strip()}%"
            where_clauses.append("(judge_name ILIKE %s OR reference_name ILIKE %s)")
            params.extend([q_clean, q_clean])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Total count
        cur.execute(f"SELECT COUNT(*) AS total FROM ecourts_pdfs {where_sql};", params)
        total = cur.fetchone()["total"]

        # Pagination
        page = max(1, int(page))
        limit = max(1, min(100, int(limit)))
        offset = (page - 1) * limit
        total_pages = math.ceil(total / limit) if total > 0 else 1

        # Fetch records
        cur.execute(f"""
            SELECT
                id,
                judge_name,
                cause_list_date,
                reference_name,
                state_code,
                district_code,
                court_code
            FROM ecourts_pdfs
            {where_sql}
            ORDER BY cause_list_date DESC, id DESC
            LIMIT %s OFFSET %s;
        """, params + [limit, offset])
        rows = cur.fetchall()

        # Available filters for real values
        cur.execute("""
            SELECT DISTINCT judge_name
            FROM ecourts_pdfs
            WHERE judge_name IS NOT NULL AND TRIM(judge_name) <> ''
            ORDER BY judge_name ASC;
        """)
        available_judges = [r["judge_name"] for r in cur.fetchall()]

        cur.execute("""
            SELECT DISTINCT cause_list_date
            FROM ecourts_pdfs
            WHERE cause_list_date IS NOT NULL
            ORDER BY cause_list_date DESC;
        """)
        available_dates = [
            (r["cause_list_date"].strftime("%Y-%m-%d") if hasattr(r["cause_list_date"], "strftime") else str(r["cause_list_date"]))
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT DISTINCT state_code, court_code
            FROM ecourts_pdfs
            ORDER BY state_code, court_code;
        """)
        raw_courts = cur.fetchall()
        available_courts = []
        for rc in raw_courts:
            info = get_court_info(rc["state_code"], rc["court_code"])
            available_courts.append({
                "state_code": rc["state_code"],
                "court_code": rc["court_code"] or "1",
                "label": f"{info['state_name']} - {info['court_name']}"
            })

        cur.close()
        conn.close()

        disk_index = get_disk_pdf_index()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        items = []
        for r in rows:
            cdate = r["cause_list_date"]
            expected_fn = compute_expected_filename(cdate, r["reference_name"])
            disk_info = disk_index.get(expected_fn)
            storage_info = (
                storage_service.get_pdf_object_info(expected_fn)
                if expected_fn else None
            )
            info = get_court_info(r["state_code"], r["court_code"])

            items.append({
                "id": r["id"],
                "filename": expected_fn or f"doc_{r['id']}.pdf",
                "judge_name": r["judge_name"] or "Unknown Judge",
                "cause_list_date": fmt_date(cdate),
                "reference_name": r["reference_name"],
                "state_code": r["state_code"],
                "district_code": r["district_code"] or "All",
                "court_code": r["court_code"] or "1",
                "state_name": info["state_name"],
                "court_name": info["court_name"],
                "has_file": bool(disk_info or storage_info),
                "file_size": (
                    disk_info["file_size"] if disk_info
                    else storage_info["file_size"] if storage_info else 0
                ),
                "rel_path": disk_info["rel_path"] if disk_info else None
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "filters": {
                "judges": available_judges,
                "dates": available_dates,
                "courts": available_courts
            }
        }
    except Exception as e:
        if conn: conn.close()
        raise e

def get_pdf_details(filename=None, pdf_id=None):
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        row = None
        if pdf_id:
            cur.execute("""
                SELECT id, judge_name, cause_list_date, reference_name, state_code, district_code, court_code
                FROM ecourts_pdfs
                WHERE id = %s;
            """, (pdf_id,))
            row = cur.fetchone()

        if not row and filename:
            # Match by reference name part or find in DB
            cur.execute("""
                SELECT id, judge_name, cause_list_date, reference_name, state_code, district_code, court_code
                FROM ecourts_pdfs;
            """)
            all_rows = cur.fetchall()
            target_fn = os.path.basename(filename)
            for r in all_rows:
                efn = compute_expected_filename(r["cause_list_date"], r["reference_name"])
                if efn == target_fn:
                    row = r
                    break

        cur.close()
        conn.close()

        if not row:
            return None

        cdate = row["cause_list_date"]
        expected_fn = compute_expected_filename(cdate, row["reference_name"])
        disk_index = get_disk_pdf_index()
        disk_info = disk_index.get(expected_fn)
        storage_info = (
            storage_service.get_pdf_object_info(expected_fn)
            if expected_fn else None
        )
        info = get_court_info(row["state_code"], row["court_code"])

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        return {
            "id": row["id"],
            "filename": expected_fn or f"doc_{row['id']}.pdf",
            "judge_name": row["judge_name"],
            "cause_list_date": fmt_date(cdate),
            "reference_name": row["reference_name"],
            "state_code": row["state_code"],
            "district_code": row["district_code"] or "All",
            "court_code": row["court_code"] or "1",
            "state_name": info["state_name"],
            "court_name": info["court_name"],
            "has_file": bool(disk_info or storage_info),
            "file_size": (
                disk_info["file_size"] if disk_info
                else storage_info["file_size"] if storage_info else 0
            ),
            "rel_path": disk_info["rel_path"] if disk_info else None
        }
    except Exception as e:
        if conn: conn.close()
        raise e

def get_scraper_runs():
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, started_at, finished_at, state_code, district_code, court_code, status,
                   cause_lists, pdfs_downloaded, pdfs_skipped, error
            FROM scraper_runs
            ORDER BY started_at DESC
            LIMIT 50;
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        def fmt_dt(t):
            return t.strftime("%Y-%m-%d %H:%M:%S") if hasattr(t, "strftime") else (str(t) if t else "")

        runs = []
        for r in rows:
            c_info = get_court_info(r["state_code"], r["court_code"])
            runs.append({
                "id": r["id"],
                "started_at": fmt_dt(r["started_at"]),
                "finished_at": fmt_dt(r["finished_at"]),
                "state_code": r["state_code"],
                "district_code": r["district_code"] or "All",
                "court_code": r["court_code"] or "1",
                "state_name": c_info["state_name"],
                "court_name": c_info["court_name"],
                "status": r["status"],
                "cause_lists": r["cause_lists"] or 0,
                "pdfs_downloaded": r["pdfs_downloaded"] or 0,
                "pdfs_skipped": r["pdfs_skipped"] or 0,
                "error": r["error"]
            })
        return runs
    except Exception as e:
        if conn: conn.close()
        print(f"[Error fetching scraper runs]: {e}", flush=True)
        return []


# =====================================================
# Supreme Court Cases (from supreme_court_cases table)
# =====================================================

def get_supreme_court_overview():
    """Get Supreme Court overview stats."""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                COUNT(*) AS total_cases,
                COUNT(DISTINCT judge_name) AS total_judges,
                MIN(judgment_date) AS earliest_judgment,
                MAX(judgment_date) AS latest_judgment,
                COUNT(DISTINCT year) AS years_covered
            FROM supreme_court_cases
            WHERE judge_name IS NOT NULL;
        """)
        overview = cur.fetchone()

        cur.close()
        conn.close()

        if not overview or overview["total_cases"] == 0:
            return None

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        return {
            "total_cases": overview["total_cases"],
            "total_judges": overview["total_judges"],
            "earliest_judgment": fmt_date(overview["earliest_judgment"]),
            "latest_judgment": fmt_date(overview["latest_judgment"]),
            "years_covered": overview["years_covered"]
        }
    except Exception as e:
        if conn: conn.close()
        print(f"[Error] get_supreme_court_overview: {e}", flush=True)
        return None


def get_supreme_court_judges(query=None, sort_by="total_cases", sort_order="desc", page=1, limit=20):
    """Get paginated list of Supreme Court judges."""
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        allowed_sorts = {
            "total_cases": "total_cases",
            "judge_name": "judge_name",
            "earliest_judgment": "earliest_judgment",
            "latest_judgment": "latest_judgment"
        }
        sort_col = allowed_sorts.get(sort_by, "total_cases")
        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"

        where_clauses = ["judge_name IS NOT NULL", "TRIM(judge_name) <> ''"]
        params = []

        if query and query.strip():
            where_clauses.append("judge_name ILIKE %s")
            params.append(f"%{query.strip()}%")

        where_sql = " AND ".join(where_clauses)

        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM supreme_court_judges
            WHERE {where_sql};
        """, params)
        total = cur.fetchone()["total"]

        page = max(1, int(page))
        limit = max(1, min(100, int(limit)))
        offset = (page - 1) * limit
        total_pages = math.ceil(total / limit) if total > 0 else 1
        cur.execute(f"""
            SELECT
                judge_name,
                total_cases,
                earliest_judgment,
                latest_judgment,
                years_active,
                unique_cases
            FROM supreme_court_judges
            WHERE {where_sql}
            ORDER BY {sort_col} {direction}, judge_name ASC
            LIMIT %s OFFSET %s;
        """, params + [limit, offset])
        rows = cur.fetchall()

        cur.close()
        conn.close()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        items = [
            {
                "judge_name": r["judge_name"],
                "total_cases": r["total_cases"],
                "earliest_judgment": fmt_date(r["earliest_judgment"]),
                "latest_judgment": fmt_date(r["latest_judgment"]),
                "years_active": r["years_active"],
                "unique_cases": r["unique_cases"]
            }
            for r in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }
    except Exception as e:
        if conn: conn.close()
        raise e


def get_supreme_court_judge_detail(judge_name):
    """Get Supreme Court case details for a specific judge."""
    if not judge_name:
        return None

    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Summary
        cur.execute("""
            SELECT
                judge_name,
                COUNT(*) AS total_cases,
                MIN(judgment_date) AS earliest_judgment,
                MAX(judgment_date) AS latest_judgment,
                COUNT(DISTINCT year) AS years_active,
                COUNT(DISTINCT case_id) AS unique_cases,
                COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) AS completed_cases,
                COUNT(CASE WHEN judgment_url IS NOT NULL AND judgment_url <> '' THEN 1 END) AS with_judgment
            FROM supreme_court_cases
            WHERE judge_name = %s
            GROUP BY judge_name;
        """, (judge_name,))
        summary = cur.fetchone()

        if not summary:
            cur.close()
            conn.close()
            return None

        # Cases list
        cur.execute("""
            SELECT
                id, judge_name, tier, year, case_id, title, state, bench,
                status, diary_number, advocates, judgment_by,
                judgment_date, duration_days, judgment_url, citation
            FROM supreme_court_cases
            WHERE judge_name = %s
            ORDER BY judgment_date DESC NULLS LAST, id DESC;
        """, (judge_name,))
        cases = cur.fetchall()

        # Activity by year
        cur.execute("""
            SELECT
                year,
                COUNT(*) AS case_count
            FROM supreme_court_cases
            WHERE judge_name = %s AND year IS NOT NULL
            GROUP BY year
            ORDER BY year ASC;
        """, (judge_name,))
        yearly_activity = cur.fetchall()

        cur.close()
        conn.close()

        def fmt_date(d):
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d) if d else "")

        return {
            "summary": {
                "judge_name": summary["judge_name"],
                "total_cases": summary["total_cases"],
                "earliest_judgment": fmt_date(summary["earliest_judgment"]),
                "latest_judgment": fmt_date(summary["latest_judgment"]),
                "years_active": summary["years_active"],
                "unique_cases": summary["unique_cases"],
                "completed_cases": summary["completed_cases"],
                "with_judgment": summary["with_judgment"]
            },
            "cases": [
                {
                    "id": c["id"],
                    "case_id": c["case_id"],
                    "title": c["title"],
                    "year": c["year"],
                    "status": c["status"],
                    "judgment_date": fmt_date(c["judgment_date"]),
                    "judgment_by": c["judgment_by"],
                    "duration_days": c["duration_days"],
                    "judgment_url": c["judgment_url"],
                    "citation": c["citation"],
                    "advocates": c["advocates"],
                    "bench": c["bench"],
                    "tier": c["tier"]
                }
                for c in cases
            ],
            "yearly_activity": [
                {
                    "year": r["year"],
                    "case_count": r["case_count"]
                }
                for r in yearly_activity
            ]
        }
    except Exception as e:
        if conn: conn.close()
        raise e

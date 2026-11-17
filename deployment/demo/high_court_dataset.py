"""Import and query High Court decision metadata for judge dossiers."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV_PATH = BASE_DIR / "high_court_test_1000k.csv"
DEFAULT_DB_PATH = Path(
    os.getenv("HIGH_COURT_DECISIONS_DB", str(BASE_DIR / "high_court_decisions.sqlite3"))
)
REQUIRED_FIELDS = {
    "case_title",
    "docket_number",
    "cnr_number",
    "neutral_citation",
    "law_report_citation",
    "court_name",
    "bench_name",
    "presiding_judge",
    "coram_members",
    "party_petitioner",
    "party_respondent",
    "decision_date",
    "registration_date",
    "disposition_text",
    "source_pdf_s3_url",
}
REMOVED_NAME_TOKENS = {
    "chief",
    "dr",
    "hon",
    "honble",
    "honourable",
    "honorable",
    "justice",
    "mr",
    "mrs",
    "ms",
    "smt",
    "sri",
    "shri",
    "the",
}
CRIMINAL_APPEAL_CASE_ID = re.compile(
    r"\b(?:CRL\.?\s*(?:A|APPEAL)(?:\s*\([^)]+\))?|C\.?\s*R\.?\s*A\.?"
    r"|CR\.?\s*(?:APP(?:EAL)?|A)|CRIMINAL\s+APPEAL|CRA)\b",
    re.IGNORECASE,
)
GOVERNMENT_PARTY_PREFIX = re.compile(
    r"^(?:THE\s+)?(?:STATE(?:\s+\(NCT\))?(?:\s+OF\b|\s+REP(?:RESENTED)?\b|\s+GOVT\b|$)"
    r"|UNION\s+OF\s+INDIA\b|CENTRAL\s+BURO?EAU\b|CBI\b"
    r"|DIRECTORATE\s+OF\s+ENFORCEMENT\b|ENFORCEMENT\s+DIRECTORATE\b"
    r"|NARCOTICS\s+CONTROL\s+BURO?EAU\b|CUSTOMS\b|INCOME\s+TAX\b"
    r"|GOVERNMENT\s+OF\b|GOVT\.?\s+OF\b|(?:INSPECTOR|OFFICER|SUPERINTENDENT|STATION\s+HOUSE\s+OFFICER)\s+OF\s+POLICE\b"
    r"|POLICE\s+STATION\b|PUBLIC\s+PROSECUTOR\b|STATE\s+PROSECUTOR\b)",
    re.IGNORECASE,
)
HIGH_COURT_JUDGE_NOISE = re.compile(
    r"\b(?:CRIMINAL\s+APPEAL|APPELLANT|RESPONDENT|PETITIONER|ACCUSED|"
    r"OCCUPATION|VILLAGE|POLICE\s+STATION|S\s*/\s*O|D\s*/\s*O|R\s*/\s*O|"
    r"IN\s+CUSTODY)\b",
    re.IGNORECASE,
)


def normalize_judge_name(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", (value or "").casefold())
    return " ".join(token for token in tokens if token not in REMOVED_NAME_TOKENS)


def _valid_high_court_judge_name(value: str) -> bool:
    normalized = normalize_judge_name(value)
    return not HIGH_COURT_JUDGE_NOISE.search(value or "") and 2 <= len(normalized.split()) <= 8


def _is_government_party(value: str) -> bool:
    return bool(GOVERNMENT_PARTY_PREFIX.match((value or "").strip()))


def _case_category(docket_number: str) -> str:
    docket = re.sub(r"[^A-Z0-9]+", " ", (docket_number or "").upper()).strip()
    if re.match(r"^(?:CRL|CRIM|CRIMINAL|CR|BAIL|NDPS|POCSO)\b", docket):
        return "criminal"
    if re.match(
        r"^(?:WP|W P|WRIT|CWJC|SCA|LPA|RFA|RSA|FA|SA|AO|CA|MCA|CIVIL|ARB|COMPANY|COM)\b",
        docket,
    ):
        return "civil"
    return "other"


def _conviction_outcome(row: dict[str, Any]) -> str | None:
    """Conservatively infer an appeal result; this is not a verified legal finding."""
    if not _is_classifiable_appeal_candidate(row):
        return None

    disposition = re.sub(
        r"[^A-Z0-9]+", " ", _text(row.get("disposition_text")).upper()
    ).strip()
    if not disposition:
        return None
    if re.search(r"\b(?:ACQUITTED|CONVICTION SET ASIDE|CONVICTION REVERSED|CONVICTION QUASHED|CONVICTION OVERTURNED)\b", disposition):
        return "CONVICTION_SET_ASIDE"
    if re.search(r"\b(?:CONVICTION MODIFIED|SENTENCE REDUCED|SENTENCE MODIFIED|SENTENCE ALTERED|PARTLY ALLOWED|PARTIALLY ALLOWED)\b", disposition):
        return "CONVICTION_MODIFIED"
    if re.search(r"\b(?:ADMISSION STAGE|ADM STAGE|DEFAULT|WITHDRAWN|GRANTED|ADMITTED|REMANDED|REMAND|DE NOVO)\b", disposition):
        return None
    if re.search(r"\b(?:DISMISSED|RULE DISCHARGED|CONVICTION AFFIRMED|CONVICTION UPHELD|SENTENCE CONFIRMED)\b", disposition):
        return "CONVICTION_UPHELD"
    if re.search(r"\b(?:ALLOWED|RULE ABSOLUTE)\b", disposition):
        return "CONVICTION_SET_ASIDE"
    return None


def _is_classifiable_appeal_candidate(row: dict[str, Any]) -> bool:
    """Identify an accused-versus-government criminal appeal with a disposition."""
    if not CRIMINAL_APPEAL_CASE_ID.search(_text(row.get("docket_number"))):
        return False
    appellant = _text(row.get("party_petitioner"))
    respondent = _text(row.get("party_respondent"))
    if not appellant or not respondent or not _text(row.get("disposition_text")):
        return False
    return not _is_government_party(appellant) and _is_government_party(respondent)


def _conviction_outcome_metrics(rows) -> dict[str, Any]:
    counts = {
        "upheld": 0,
        "set_aside": 0,
        "modified": 0,
    }
    candidate_appeals = 0
    for row in rows:
        if not _is_classifiable_appeal_candidate(row):
            continue
        candidate_appeals += 1
        outcome = _conviction_outcome(row)
        if outcome == "CONVICTION_UPHELD":
            counts["upheld"] += 1
        elif outcome == "CONVICTION_SET_ASIDE":
            counts["set_aside"] += 1
        elif outcome == "CONVICTION_MODIFIED":
            counts["modified"] += 1

    return _metrics_from_counts(
        candidate_appeals, counts["upheld"], counts["set_aside"], counts["modified"]
    )


def _metrics_from_counts(candidate_appeals: int, upheld: int, set_aside: int, modified: int) -> dict[str, Any]:
    counts = {"upheld": int(upheld or 0), "set_aside": int(set_aside or 0), "modified": int(modified or 0)}
    candidate_appeals = int(candidate_appeals or 0)
    classified = sum(counts.values())

    def rate(count: int, denominator: int) -> float | None:
        return round(count * 100 / denominator, 2) if denominator else None

    return {
        "candidate_appeals": candidate_appeals,
        "classified_appeals": classified,
        "classification_coverage_rate": rate(classified, candidate_appeals),
        "outcomes": {
            "upheld": {"count": counts["upheld"], "rate": rate(counts["upheld"], classified)},
            "set_aside": {"count": counts["set_aside"], "rate": rate(counts["set_aside"], classified)},
            "modified": {"count": counts["modified"], "rate": rate(counts["modified"], classified)},
        },
        "method_note": (
            "Estimated from scraped criminal appeal docket types, party roles, and disposition text. "
            "Dismissed/rule-discharged labels are treated as upheld; allowed/rule-absolute as set aside; "
            "partly allowed as modified. Only classified appeals are in the outcome percentages."
        ),
    }


def _case_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {"criminal": 0, "civil": 0, "other": 0}
    disposition_counts: dict[str, int] = {}
    unique_cases: set[str] = set()
    decision_dates: list[str] = []
    durations: list[int] = []

    for row in rows:
        category = _case_category(_text(row.get("docket_number")))
        categories[category] += 1
        cnr = _text(row.get("cnr_number"))
        docket = _text(row.get("docket_number"))
        case_identifier = cnr or docket or _text(row.get("case_title"))
        unique_cases.add(
            f"{_text(row.get('court_name')).casefold()}|{case_identifier.casefold()}"
        )

        disposition = _text(row.get("disposition_text"))
        disposition_key = disposition or "Not recorded"
        disposition_counts[disposition_key] = disposition_counts.get(disposition_key, 0) + 1
        if row.get("decision_date"):
            try:
                decision_date = date.fromisoformat(str(row["decision_date"])[:10])
                decision_dates.append(decision_date.isoformat())
            except ValueError:
                pass
        if row.get("decision_date") and row.get("registration_date"):
            try:
                decision = date.fromisoformat(str(row["decision_date"])[:10])
                filed = date.fromisoformat(str(row["registration_date"])[:10])
                duration = (decision - filed).days
                if duration >= 0:
                    durations.append(duration)
            except ValueError:
                pass

    conviction_analysis = _conviction_outcome_metrics(rows)

    disposition_items = [
        {"label": label, "count": count}
        for label, count in sorted(
            disposition_counts.items(), key=lambda item: (-item[1], item[0].casefold())
        )[:12]
    ]
    return {
        "summary": {
            "case_records": len(rows),
            "unique_cases": len(unique_cases),
            "first_decision": min(decision_dates) if decision_dates else "",
            "latest_decision": max(decision_dates) if decision_dates else "",
            "years_active": len({value[:4] for value in decision_dates if len(value) >= 4}),
            "median_duration_days": round(statistics.median(durations), 1) if durations else None,
            "max_duration_days": max(durations) if durations else None,
            "duration_records": len(durations),
        },
        "case_analysis": {
            "case_types": categories,
            "dispositions": disposition_items,
        },
        "conviction_analysis": conviction_analysis,
    }


def _judge_names(row: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    encoded_coram = row.get("coram_members", "")
    if encoded_coram:
        try:
            decoded = json.loads(encoded_coram)
            if isinstance(decoded, list):
                candidates.extend(str(value).strip() for value in decoded if value)
        except json.JSONDecodeError:
            candidates.extend(part.strip() for part in encoded_coram.split("|") if part.strip())
    if not candidates and row.get("presiding_judge"):
        candidates.extend(
            part.strip()
            for part in re.split(r"\s*[;|]\s*", row["presiding_judge"])
            if part.strip()
        )

    unique_names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_judge_name(candidate)
        if key and key not in seen:
            seen.add(key)
            unique_names.append(candidate)
    return unique_names


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _build_lookup_tables(connection: sqlite3.Connection) -> None:
    """Build indexed judge links and cached overview metrics for a fresh import."""
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE decision_judges (
            decision_id INTEGER NOT NULL,
            normalized_name TEXT NOT NULL,
            PRIMARY KEY (decision_id, normalized_name)
        ) WITHOUT ROWID;
        CREATE INDEX idx_decision_judges_name_id
            ON decision_judges(normalized_name, decision_id);
        CREATE TABLE high_court_overview_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_cases INTEGER NOT NULL,
            total_judges INTEGER NOT NULL,
            rows_with_judge INTEGER NOT NULL,
            rows_with_disposition INTEGER NOT NULL,
            candidate_appeals INTEGER NOT NULL,
            classified_appeals INTEGER NOT NULL,
            upheld INTEGER NOT NULL,
            set_aside INTEGER NOT NULL,
            modified INTEGER NOT NULL
        );
        CREATE TABLE high_court_judge_stats (
            normalized_name TEXT PRIMARY KEY,
            record_count INTEGER NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            court_names TEXT NOT NULL
        );
        CREATE TABLE high_court_judge_outcomes (
            normalized_name TEXT PRIMARY KEY,
            candidate_appeals INTEGER NOT NULL,
            classified_appeals INTEGER NOT NULL,
            upheld INTEGER NOT NULL,
            set_aside INTEGER NOT NULL,
            modified INTEGER NOT NULL
        );
        CREATE TABLE high_court_judge_metrics (
            normalized_name TEXT PRIMARY KEY,
            median_duration_days REAL,
            max_duration_days INTEGER,
            duration_records INTEGER NOT NULL
        );
    """)
    insert_link = connection.cursor()
    links: list[tuple[int, str]] = []
    totals = {"rows_with_judge": 0, "rows_with_disposition": 0,
              "candidate_appeals": 0, "upheld": 0, "set_aside": 0, "modified": 0}
    judge_stats: dict[str, dict[str, Any]] = {}
    judge_outcomes: dict[str, dict[str, int]] = {}
    cursor = connection.execute("""
        SELECT id, judge_search_text, docket_number, party_petitioner,
               party_respondent, disposition_text, court_name, decision_date,
               registration_date
        FROM decisions ORDER BY id
    """)
    for row in cursor:
        names = [part for part in _text(row["judge_search_text"]).split("|") if part]
        totals["rows_with_judge"] += bool(names)
        totals["rows_with_disposition"] += bool(_text(row["disposition_text"]))
        links.extend((row["id"], name) for name in names)
        if len(links) >= 20000:
            insert_link.executemany(
                "INSERT OR IGNORE INTO decision_judges VALUES (?, ?)", links
            )
            links.clear()
        record = dict(row)
        outcome = _conviction_outcome(record)
        if _is_classifiable_appeal_candidate(record):
            totals["candidate_appeals"] += 1
            if outcome == "CONVICTION_UPHELD": totals["upheld"] += 1
            elif outcome == "CONVICTION_SET_ASIDE": totals["set_aside"] += 1
            elif outcome == "CONVICTION_MODIFIED": totals["modified"] += 1
        for name in names:
            summary = judge_stats.setdefault(name, {
                "record_count": 0, "first_seen": "", "last_seen": "", "courts": set(),
                "durations": [],
            })
            summary["record_count"] += 1
            decision_date = _text(row["decision_date"])
            if decision_date and (not summary["first_seen"] or decision_date < summary["first_seen"]):
                summary["first_seen"] = decision_date
            if decision_date and decision_date > summary["last_seen"]:
                summary["last_seen"] = decision_date
            if row["court_name"]:
                summary["courts"].add(row["court_name"])
            try:
                decision = date.fromisoformat(_text(row["decision_date"])[:10])
                filed = date.fromisoformat(_text(row["registration_date"])[:10])
                duration = (decision - filed).days
                if duration >= 0:
                    summary["durations"].append(duration)
            except ValueError:
                pass
            if _is_classifiable_appeal_candidate(record):
                counts = judge_outcomes.setdefault(name, {
                    "candidate_appeals": 0, "upheld": 0, "set_aside": 0, "modified": 0
                })
                counts["candidate_appeals"] += 1
                if outcome == "CONVICTION_UPHELD": counts["upheld"] += 1
                elif outcome == "CONVICTION_SET_ASIDE": counts["set_aside"] += 1
                elif outcome == "CONVICTION_MODIFIED": counts["modified"] += 1
    if links:
        insert_link.executemany("INSERT OR IGNORE INTO decision_judges VALUES (?, ?)", links)
    connection.executemany("""
        INSERT INTO high_court_judge_stats VALUES (?, ?, ?, ?, ?)
    """, [
        (name, row["record_count"], row["first_seen"], row["last_seen"],
         json.dumps(sorted(row["courts"]), ensure_ascii=False))
        for name, row in judge_stats.items()
    ])
    connection.executemany("""
        INSERT INTO high_court_judge_outcomes VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (name, counts["candidate_appeals"],
         counts["upheld"] + counts["set_aside"] + counts["modified"],
         counts["upheld"], counts["set_aside"], counts["modified"])
        for name, counts in judge_outcomes.items()
    ])
    connection.executemany("""
        INSERT INTO high_court_judge_metrics VALUES (?, ?, ?, ?)
    """, [
        (name,
         statistics.median(row["durations"]) if row["durations"] else None,
         max(row["durations"]) if row["durations"] else None,
         len(row["durations"]))
        for name, row in judge_stats.items()
    ])
    classified = totals["upheld"] + totals["set_aside"] + totals["modified"]
    connection.execute("""
        INSERT INTO high_court_overview_stats VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM high_court_judges").fetchone()[0],
        totals["rows_with_judge"], totals["rows_with_disposition"],
        totals["candidate_appeals"], classified, totals["upheld"],
        totals["set_aside"], totals["modified"],
    ))


def import_high_court_csv(
    csv_path: Path = DEFAULT_CSV_PATH,
    database_path: Path = DEFAULT_DB_PATH,
    overwrite: bool = False,
) -> dict[str, int | str]:
    """Create an indexed SQLite file containing only High Court case metadata."""
    csv_path = Path(csv_path)
    database_path = Path(database_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"Dataset CSV not found: {csv_path}")
    if database_path.exists() and not overwrite:
        raise FileExistsError(
            f"Database already exists: {database_path}. Use --overwrite to rebuild it."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{database_path.stem}-",
        suffix=".sqlite3",
        dir=database_path.parent,
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    stats: dict[str, int | str] = {
        "source_rows": 0,
        "high_court_rows": 0,
        "rows_with_judge": 0,
        "rows_with_disposition": 0,
        "rows_with_both": 0,
        "high_courts": 0,
        "judges_indexed": 0,
    }

    try:
        connection = sqlite3.connect(temporary_path)
        try:
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute("""
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY,
                    case_title TEXT NOT NULL,
                    docket_number TEXT,
                    cnr_number TEXT,
                    citation TEXT,
                    court_name TEXT NOT NULL,
                    court_code TEXT,
                    bench_name TEXT,
                    judge_names TEXT,
                    judge_search_text TEXT NOT NULL,
                    party_petitioner TEXT,
                    party_respondent TEXT,
                    decision_date TEXT,
                    registration_date TEXT,
                    disposition_text TEXT,
                    source_pdf_url TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE high_court_judges (
                    normalized_name TEXT PRIMARY KEY,
                    judge_name TEXT NOT NULL,
                    criminal_cases INTEGER NOT NULL DEFAULT 0,
                    conviction_cases INTEGER NOT NULL DEFAULT 0
                )
            """)
            judge_name_index: dict[str, str] = {}
            judge_case_counts: dict[str, list[int]] = {}
            with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                missing = REQUIRED_FIELDS.difference(reader.fieldnames or [])
                if missing:
                    raise ValueError(
                        f"Dataset CSV is missing required columns: {', '.join(sorted(missing))}"
                    )

                batch: list[tuple[Any, ...]] = []
                courts: set[str] = set()
                for row in reader:
                    stats["source_rows"] = int(stats["source_rows"]) + 1
                    court_name = _text(row.get("court_name"))
                    if "high court" not in court_name.casefold():
                        continue

                    names = _judge_names(row)
                    normalized_names = [
                        normalize_judge_name(name)
                        for name in names
                        if normalize_judge_name(name)
                    ]
                    for name, normalized_name in zip(names, normalized_names):
                        judge_name_index.setdefault(normalized_name, name)
                    disposition = _text(row.get("disposition_text"))
                    docket_number = _text(row.get("docket_number"))
                    criminal_case = _case_category(docket_number) == "criminal" and bool(disposition)
                    conviction_case = _conviction_outcome(row) in {
                        "CONVICTION_UPHELD",
                        "CONVICTION_MODIFIED",
                    }
                    for normalized_name in normalized_names:
                        counts = judge_case_counts.setdefault(normalized_name, [0, 0])
                        if criminal_case:
                            counts[0] += 1
                        if conviction_case:
                            counts[1] += 1
                    stats["high_court_rows"] = int(stats["high_court_rows"]) + 1
                    stats["rows_with_judge"] = int(stats["rows_with_judge"]) + bool(names)
                    stats["rows_with_disposition"] = (
                        int(stats["rows_with_disposition"]) + bool(disposition)
                    )
                    stats["rows_with_both"] = (
                        int(stats["rows_with_both"]) + bool(names and disposition)
                    )
                    courts.add(court_name)
                    citation = _text(row.get("neutral_citation")) or _text(
                        row.get("law_report_citation")
                    )
                    batch.append((
                        _text(row.get("case_title")),
                        _text(row.get("docket_number")),
                        _text(row.get("cnr_number")),
                        citation,
                        court_name,
                        _text(row.get("court_code")),
                        _text(row.get("bench_name")),
                        " | ".join(names),
                        f"|{'|'.join(normalized_names)}|" if normalized_names else "",
                        _text(row.get("party_petitioner")),
                        _text(row.get("party_respondent")),
                        _text(row.get("decision_date")),
                        _text(row.get("registration_date")),
                        disposition,
                        _text(row.get("source_pdf_s3_url")),
                    ))
                    if len(batch) >= 1000:
                        connection.executemany("""
                            INSERT INTO decisions (
                                case_title, docket_number, cnr_number, citation,
                                court_name, court_code, bench_name, judge_names, judge_search_text,
                                party_petitioner, party_respondent,
                                decision_date, registration_date, disposition_text,
                                source_pdf_url
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        batch.clear()

                if batch:
                    connection.executemany("""
                        INSERT INTO decisions (
                            case_title, docket_number, cnr_number, citation,
                            court_name, court_code, bench_name, judge_names, judge_search_text,
                            party_petitioner, party_respondent,
                            decision_date, registration_date, disposition_text,
                            source_pdf_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                connection.executemany(
                    "INSERT INTO high_court_judges "
                    "(normalized_name, judge_name, criminal_cases, conviction_cases) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (normalized, name, *judge_case_counts.get(normalized, [0, 0]))
                        for normalized, name in judge_name_index.items()
                    ],
                )
                stats["judges_indexed"] = len(judge_name_index)
                stats["high_courts"] = len(courts)

            connection.execute(
                "CREATE INDEX idx_decisions_judge_date "
                "ON decisions(judge_search_text, decision_date DESC)"
            )
            connection.execute(
                "CREATE INDEX idx_decisions_court ON decisions(court_name)"
            )
            _build_lookup_tables(connection)
            connection.commit()
        finally:
            connection.close()

        os.replace(temporary_path, database_path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise

    stats["database_path"] = str(database_path)
    return stats


def get_judge_decisions(
    judge_name: str,
    page: int = 1,
    limit: int = 20,
    court_name: str = "",
    database_path: Path = DEFAULT_DB_PATH,
    summary_only: bool = False,
) -> dict[str, Any]:
    """Return a paginated, judge-matched set of scraped High Court decisions."""
    normalized_name = normalize_judge_name(judge_name)
    if not normalized_name:
        raise ValueError("A judge name with searchable letters or numbers is required.")

    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError(
            f"High Court decision index not found: {database_path}. "
            "Run python high_court_dataset.py first."
        )

    page = max(1, int(page))
    limit = max(1, min(100, int(limit)))
    offset = (page - 1) * limit
    where_clause = "dj.normalized_name = ?"
    query_params: list[Any] = [normalized_name]
    if court_name:
        where_clause += " AND court_name = ?"
        query_params.append(court_name)

    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        cached = connection.execute("""
            SELECT s.record_count, s.first_seen, s.last_seen, s.court_names,
                   m.median_duration_days, m.max_duration_days, m.duration_records,
                   o.candidate_appeals, o.upheld, o.set_aside, o.modified
            FROM high_court_judge_stats s
            LEFT JOIN high_court_judge_metrics m USING (normalized_name)
            LEFT JOIN high_court_judge_outcomes o USING (normalized_name)
            WHERE s.normalized_name = ?
        """, (normalized_name,)).fetchone()
        if not cached:
            return {"items": [], "total": 0, "page": page, "limit": limit,
                    "total_pages": 1, "available_courts": [], "selected_court": court_name}
        available_courts = json.loads(cached["court_names"] or "[]")
        cached_summary = {
            "case_records": int(cached["record_count"] or 0),
            "first_decision": cached["first_seen"] or "",
            "latest_decision": cached["last_seen"] or "",
            "median_duration_days": cached["median_duration_days"],
            "max_duration_days": cached["max_duration_days"],
            "duration_records": int(cached["duration_records"] or 0),
        }
        conviction_analysis = _metrics_from_counts(
            cached["candidate_appeals"], cached["upheld"], cached["set_aside"], cached["modified"]
        )
        if court_name:
            matching_rows = [
                dict(row)
                for row in connection.execute("""
                    SELECT d.case_title, d.docket_number, d.cnr_number, d.citation,
                           d.court_name, d.court_code, d.bench_name, d.judge_names,
                           d.party_petitioner, d.party_respondent, d.decision_date,
                           d.registration_date, d.disposition_text, d.source_pdf_url
                    FROM decisions d JOIN decision_judges dj ON dj.decision_id = d.id
                    WHERE dj.normalized_name = ? AND d.court_name = ?
                """, (normalized_name, court_name))
            ]
            total = len(matching_rows)
            filtered_metrics = _case_metrics(matching_rows)
            cached_summary = filtered_metrics["summary"]
            conviction_analysis = filtered_metrics["conviction_analysis"]
        else:
            total = int(cached["record_count"] or 0)
        rows = [] if summary_only else connection.execute(f"""
            SELECT d.case_title, d.docket_number, d.cnr_number, d.citation, d.court_name,
                   d.court_code, d.bench_name, d.judge_names, d.party_petitioner,
                   d.party_respondent, d.decision_date, d.registration_date,
                   d.disposition_text, d.source_pdf_url
            FROM decisions d
            JOIN decision_judges dj ON dj.decision_id = d.id
            WHERE {where_clause}
            ORDER BY d.decision_date DESC, d.id DESC
            LIMIT ? OFFSET ?
        """, query_params + [limit, offset]).fetchall()
        coverage = connection.execute("""
            SELECT total_cases AS high_court_rows,
                   rows_with_judge, rows_with_disposition
            FROM high_court_overview_stats WHERE id = 1
        """).fetchone()
    finally:
        connection.close()

    page_items = [dict(row) for row in rows]
    for item in page_items:
        item["case_type"] = _case_category(_text(item.get("docket_number")))
        if item.get("decision_date") and item.get("registration_date"):
            try:
                decision = date.fromisoformat(str(item["decision_date"])[:10])
                filed = date.fromisoformat(str(item["registration_date"])[:10])
                duration = (decision - filed).days
                item["duration_days"] = duration if duration >= 0 else None
            except ValueError:
                item["duration_days"] = None
        else:
            item["duration_days"] = None

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if total else 1,
        "available_courts": available_courts,
        "selected_court": court_name,
        "summary": cached_summary,
        "conviction_analysis": conviction_analysis,
        "coverage": {
            "dataset": "Scraped High Court case records",
            "high_court_rows": coverage["high_court_rows"] or 0,
            "rows_with_judge": coverage["rows_with_judge"] or 0,
            "rows_with_disposition": coverage["rows_with_disposition"] or 0,
            "limitation": (
                "Uses scraped case records and recorded dispositions; conviction outcomes "
                "are estimated from appeal direction and disposition text."
            ),
        },
    }


def get_high_court_overview(database_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Return the number of scraped High Court records in the local index."""
    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"High Court scraped case index not found: {database_path}")
    connection = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        stats = connection.execute("""
            SELECT total_cases, total_judges, candidate_appeals, classified_appeals,
                   upheld, set_aside, modified
            FROM high_court_overview_stats WHERE id = 1
        """).fetchone()
        judges_with_analysis = sum(
            _valid_high_court_judge_name(row[0])
            for row in connection.execute("""
                SELECT j.judge_name FROM high_court_judges j
                JOIN high_court_judge_outcomes o USING (normalized_name)
                WHERE o.classified_appeals > 0
            """)
        )
        conviction_analysis = _metrics_from_counts(
            stats["candidate_appeals"], stats["upheld"], stats["set_aside"], stats["modified"]
        )
        return {
            "total_cases": int(stats["total_cases"] or 0),
            "total_judges": int(stats["total_judges"] or 0),
            "judges_with_outcome_analysis": int(judges_with_analysis),
            "conviction_analysis": conviction_analysis,
        }
    finally:
        connection.close()


def search_high_court_judges(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Search scraped High Court judge names and return directory-ready records."""
    query = _text(query)
    if len(normalize_judge_name(query)) < 3:
        return []
    database_path = DEFAULT_DB_PATH
    if not database_path.is_file():
        return []

    connection = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        candidates = connection.execute("""
            SELECT j.normalized_name, j.judge_name, s.record_count, s.first_seen,
                   s.last_seen, s.court_names
            FROM high_court_judges j
            JOIN high_court_judge_stats s USING (normalized_name)
            WHERE j.judge_name LIKE ? COLLATE NOCASE
            ORDER BY s.record_count DESC, j.judge_name ASC
            LIMIT ?
        """, (f"%{query}%", max(1, min(100, int(limit))))).fetchall()
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            name = _text(candidate["judge_name"])
            if not _valid_high_court_judge_name(name):
                continue
            normalized_name = candidate["normalized_name"]
            if not candidate["record_count"]:
                continue
            court_names = json.loads(candidate["court_names"] or "[]")
            results.append({
                "judge_name": name,
                "record_count": candidate["record_count"],
                "first_seen": candidate["first_seen"] or "",
                "last_seen": candidate["last_seen"] or "",
                "court_name": ", ".join(court_names),
                "court_type": "high_court_index",
            })
        return results
    finally:
        connection.close()


def list_high_court_judges(
    query: str = "", page: int = 1, limit: int = 20,
    sort_by: str = "record_count", sort_order: str = "desc",
) -> dict[str, Any]:
    """Return paginated High Court judge records for the directory."""
    database_path = DEFAULT_DB_PATH
    if not database_path.is_file():
        raise FileNotFoundError(f"High Court scraped case index not found: {database_path}")
    page = max(1, int(page))
    limit = max(1, min(100, int(limit)))
    sort_key = sort_by if sort_by in {"record_count", "judge_name", "first_seen", "last_seen"} else "record_count"
    direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
    conditions = []
    params: list[Any] = []
    if _text(query):
        conditions.append("j.judge_name LIKE ? COLLATE NOCASE")
        params.append(f"%{_text(query)}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(f"""
            SELECT j.judge_name, s.record_count, s.first_seen, s.last_seen, s.court_names
            FROM high_court_judges j
            JOIN high_court_judge_stats s USING (normalized_name)
            {where}
        """, params).fetchall()
        items = []
        for row in rows:
            items.append({
                "judge_name": row["judge_name"],
                "record_count": int(row["record_count"] or 0),
                "first_seen": row["first_seen"] or "",
                "last_seen": row["last_seen"] or "",
                "court_name": ", ".join(json.loads(row["court_names"] or "[]")),
                "court_type": "high_court_index",
            })
        items = [item for item in items if _valid_high_court_judge_name(item["judge_name"])]
        total = len(items)
        items.sort(key=lambda item: item["judge_name"].casefold())
        if sort_key == "judge_name":
            items.sort(key=lambda item: item[sort_key].casefold())
        elif sort_key == "record_count":
            items.sort(key=lambda item: int(item[sort_key] or 0))
        else:
            items.sort(key=lambda item: item[sort_key] or "")
        if direction == "DESC":
            items.reverse()
        items = items[(page - 1) * limit:page * limit]
        return {
            "items": items, "total": total, "page": page, "limit": limit,
            "total_pages": (total + limit - 1) // limit if total else 1,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a local High Court case index from high_court_test_1000k.csv."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the existing SQLite index after a successful import.",
    )
    args = parser.parse_args()
    try:
        stats = import_high_court_csv(args.input, args.output, args.overwrite)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("High Court case index created:")
    for name, value in stats.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Seed local PostgreSQL PDF metadata from the laptop's existing listings and PDFs."""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path, PurePosixPath

import psycopg2
from dotenv import load_dotenv

from court_mapper import HIGH_COURTS


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
load_dotenv(BASE_DIR / ".env")


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def local_pdf_root() -> Path:
    configured = Path(os.getenv("LOCAL_PDF_DIR", "../downloaded_pdfs"))
    return (configured if configured.is_absolute() else BASE_DIR / configured).resolve()


def resolve_source_file(source_file: str, pdf_root: Path) -> tuple[Path, PurePosixPath] | None:
    relative = PurePosixPath((source_file or "").replace("\\", "/"))
    parts = list(relative.parts)
    if parts and parts[0].casefold() == "downloaded_pdfs":
        parts.pop(0)
    if not parts or any(part in {".", ".."} for part in parts):
        return None
    relative = PurePosixPath(*parts)
    full_path = (pdf_root / Path(*relative.parts)).resolve()
    try:
        full_path.relative_to(pdf_root)
    except ValueError:
        return None
    return (full_path, relative) if full_path.is_file() else None


def find_court_codes(relative_path: PurePosixPath) -> tuple[str, str]:
    if len(relative_path.parts) < 2:
        return "", "1"
    state_folder, bench_folder = relative_path.parts[0], relative_path.parts[1]
    state_key = normalize(state_folder)
    bench_key = normalize(bench_folder)
    candidates = [court for court in HIGH_COURTS if normalize(court[2]) == state_key]
    if not candidates:
        candidates = [court for court in HIGH_COURTS if state_key in normalize(court[2]) or normalize(court[2]) in state_key]
    if not candidates:
        return "", "1"

    def score(court: tuple[str, str | None, str, str]) -> int:
        bench = normalize(court[3])
        if bench == bench_key:
            return 1000 + len(bench)
        if bench_key in bench or bench in bench_key:
            return 500 + min(len(bench), len(bench_key))
        return len(set(bench.split()) & set(bench_key.split()))

    match = max(candidates, key=score)
    return match[0], str(match[1] or "1")


def clean_judge_label(raw: str) -> str:
    label = (raw or "").split("|")[-1].strip()
    for _ in range(4):
        next_label = re.sub(
            r"^(?:THE\s+)?(?:HON'?BLE|HONOURABLE|HONORABLE|SHRI|SRI|SMT|JUSTICE|DR\.?)\s+",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip()
        if next_label == label:
            break
        label = next_label
    return label or "Unknown Judge"


def collect_local_pdfs(csv_path: Path, pdf_root: Path) -> dict[str, dict[str, object]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Listings CSV not found: {csv_path}")
    if not pdf_root.is_dir():
        raise FileNotFoundError(f"Local PDF folder not found: {pdf_root}")

    records: dict[str, dict[str, object]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            source_name = (row.get("source_file") or "").strip()
            resolved = resolve_source_file(source_name, pdf_root)
            if not resolved:
                continue
            full_path, relative_path = resolved
            filename = full_path.name
            match = re.match(r"^(\d{8})_(.+)\.pdf$", filename, flags=re.IGNORECASE)
            if not match:
                continue
            date_text = match.group(1)
            date_value = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
            reference_name = match.group(2)
            state_code, court_code = find_court_codes(relative_path)
            item = records.setdefault(
                relative_path.as_posix(),
                {
                    "full_path": full_path,
                    "relative_path": relative_path.as_posix(),
                    "filename": filename,
                    "date": date_value,
                    "reference_name": reference_name,
                    "judges": set(),
                    "state_code": state_code,
                    "court_code": court_code,
                },
            )
            item["judges"].add(clean_judge_label(row.get("court_hall_bench_judge_names", "")))
    return records


def main() -> None:
    pdf_root = local_pdf_root()
    csv_path = PROJECT_ROOT / "all_listings.csv"
    records = collect_local_pdfs(csv_path, pdf_root)
    if not records:
        raise RuntimeError("No local PDFs matched the source_file values in all_listings.csv.")

    connection = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "ecourts_demo"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
    )
    try:
        with connection, connection.cursor() as cursor:
            for item in records.values():
                judges = sorted(item["judges"] - {"Unknown Judge"})
                judge_label = " | ".join(judges) if judges else "Unknown Judge"
                pdf_path = item["full_path"]
                cursor.execute(
                    """
                    INSERT INTO ecourts_pdfs (
                        local_pdf_path, pdf_filename, judge_names, cause_list_type,
                        cause_list_date, eliminated, file_size_bytes, download_status,
                        content_type, judge_name, reference_name, state_code,
                        district_code, court_code
                    ) VALUES (%s, %s, %s, %s, %s, FALSE, %s, 'downloaded',
                              'application/pdf', %s, %s, %s, 'All', %s)
                    ON CONFLICT (cause_list_date, reference_name) DO UPDATE SET
                        local_pdf_path = EXCLUDED.local_pdf_path,
                        pdf_filename = EXCLUDED.pdf_filename,
                        judge_names = EXCLUDED.judge_names,
                        judge_name = EXCLUDED.judge_name,
                        state_code = EXCLUDED.state_code,
                        court_code = EXCLUDED.court_code,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        download_status = 'downloaded'
                    """,
                    (
                        str(pdf_path), item["filename"], judge_label, "Cause list",
                        item["date"], pdf_path.stat().st_size, judge_label,
                        item["reference_name"], item["state_code"], item["court_code"],
                    ),
                )
    finally:
        connection.close()

    print(f"Local PDF metadata ready: {len(records):,} PDFs")
    print(f"PostgreSQL: {os.getenv('DB_HOST', '127.0.0.1')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'ecourts_demo')}")
    print(f"PDF folder: {pdf_root}")


if __name__ == "__main__":
    main()

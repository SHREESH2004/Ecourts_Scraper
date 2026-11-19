"""Restore the ignored SQLite sample from its compressed deployment asset."""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ARCHIVE_PATH = BASE_DIR / "high_court_decisions.sqlite3.gz"
DATABASE_PATH = BASE_DIR / "high_court_decisions.sqlite3"
TEMP_PATH = BASE_DIR / "high_court_decisions.sqlite3.tmp"


def main() -> None:
    if not ARCHIVE_PATH.is_file():
        raise FileNotFoundError(f"Compressed demo database not found: {ARCHIVE_PATH}")

    try:
        with gzip.open(ARCHIVE_PATH, "rb") as source, TEMP_PATH.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)

        with TEMP_PATH.open("rb") as database_file:
            if database_file.read(16) != b"SQLite format 3\x00":
                raise RuntimeError("Restored file is not a valid SQLite database.")

        with sqlite3.connect(TEMP_PATH) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {result}")

        os.replace(TEMP_PATH, DATABASE_PATH)
    finally:
        if TEMP_PATH.exists():
            TEMP_PATH.unlink()

    print(
        f"Restored High Court demo index: {DATABASE_PATH.name} "
        f"({DATABASE_PATH.stat().st_size:,} bytes)",
        flush=True,
    )


if __name__ == "__main__":
    main()

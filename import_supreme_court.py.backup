"""
Import Supreme Court case data into PostgreSQL and refresh its judge directory.
"""

import os
import sys
import csv

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# PostgreSQL Configuration
POSTGRES_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "ecourts_scraper"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "shs2004")
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "supreme_court_all_judges.csv")


def create_table(conn):
    """Create the Supreme Court case and judge-directory tables if needed."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supreme_court_cases (
            id SERIAL PRIMARY KEY,
            judge_name TEXT,
            tier TEXT,
            year INTEGER,
            case_id TEXT,
            title TEXT,
            state TEXT,
            bench TEXT,
            district TEXT,
            complex TEXT,
            status TEXT,
            diary_number TEXT,
            advocates TEXT,
            judgment_by TEXT,
            judgment_date DATE,
            duration_days INTEGER,
            judgment_url TEXT,
            citation TEXT,
            citation_url TEXT,
            source_url TEXT,
            imported_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    # Create indexes for common queries
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_judge_name ON supreme_court_cases(judge_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_judgment_date ON supreme_court_cases(judgment_date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_year ON supreme_court_cases(year);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_status ON supreme_court_cases(status);")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supreme_court_judges (
            judge_name TEXT PRIMARY KEY,
            total_cases INTEGER NOT NULL DEFAULT 0,
            unique_cases INTEGER NOT NULL DEFAULT 0,
            earliest_judgment DATE,
            latest_judgment DATE,
            years_active INTEGER NOT NULL DEFAULT 0,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_judges_total_cases ON supreme_court_judges(total_cases);")
    conn.commit()
    cur.close()
    print("[OK] Supreme Court case and judge tables ensured.")


def refresh_judges_table(conn):
    """Rebuild the judge directory from the case records without changing cases."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE supreme_court_judges;")
    cur.execute("""
        INSERT INTO supreme_court_judges (
            judge_name, total_cases, unique_cases, earliest_judgment,
            latest_judgment, years_active, refreshed_at
        )
        SELECT
            TRIM(judge_name),
            COUNT(*),
            COUNT(DISTINCT case_id),
            MIN(judgment_date),
            MAX(judgment_date),
            COUNT(DISTINCT year),
            NOW()
        FROM supreme_court_cases
        WHERE judge_name IS NOT NULL AND TRIM(judge_name) <> ''
        GROUP BY TRIM(judge_name);
    """)
    conn.commit()
    cur.close()
    print("[OK] Supreme Court judge directory refreshed.")


def import_csv(conn):
    """Read CSV and insert all rows into supreme_court_cases."""
    if not os.path.isfile(CSV_FILE):
        print(f"ERROR: CSV file not found: {CSV_FILE}")
        sys.exit(1)

    cur = conn.cursor()

    # Truncate existing data for clean re-import
    cur.execute("TRUNCATE TABLE supreme_court_cases RESTART IDENTITY;")
    conn.commit()
    print("[OK] Truncated existing data.")

    inserted = 0
    skipped = 0

    with open(CSV_FILE, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Parse year
                year_val = None
                if row.get("year"):
                    try:
                        year_val = int(row["year"])
                    except ValueError:
                        year_val = None

                # Parse judgment_date
                judgment_date_val = None
                if row.get("judgment_date") and row["judgment_date"].strip():
                    judgment_date_val = row["judgment_date"].strip()

                # Parse duration_days
                duration_val = None
                if row.get("duration_days"):
                    try:
                        duration_val = int(row["duration_days"])
                    except ValueError:
                        duration_val = None

                cur.execute("""
                    INSERT INTO supreme_court_cases
                        (judge_name, tier, year, case_id, title, state, bench,
                         district, complex, status, diary_number, advocates,
                         judgment_by, judgment_date, duration_days, judgment_url,
                         citation, citation_url, source_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    row.get("judge_name", "").strip() or None,
                    row.get("tier", "").strip() or None,
                    year_val,
                    row.get("case_id", "").strip() or None,
                    row.get("title", "").strip() or None,
                    row.get("state", "").strip() or None,
                    row.get("bench", "").strip() or None,
                    row.get("district", "").strip() or None,
                    row.get("complex", "").strip() or None,
                    row.get("status", "").strip() or None,
                    row.get("diary_number", "").strip() or None,
                    row.get("advocates", "").strip() or None,
                    row.get("judgment_by", "").strip() or None,
                    judgment_date_val,
                    duration_val,
                    row.get("judgment_url", "").strip() or None,
                    row.get("citation", "").strip() or None,
                    row.get("citation_url", "").strip() or None,
                    row.get("source_url", "").strip() or None
                ))
                inserted += 1
            except Exception as e:
                skipped += 1
                print(f"  [SKIP] Row error: {e}")
                conn.rollback()
                # Re-open cursor after rollback
                cur = conn.cursor()
                continue

    conn.commit()
    cur.close()
    print(f"\n{'='*50}")
    print(f"  Import Complete!")
    print(f"  Inserted: {inserted} rows")
    print(f"  Skipped:  {skipped} rows")
    print(f"{'='*50}")


def verify(conn):
    """Show verification stats."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM supreme_court_cases;")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT judge_name) FROM supreme_court_cases;")
    judges = cur.fetchone()[0]

    cur.execute("SELECT MIN(judgment_date), MAX(judgment_date) FROM supreme_court_cases WHERE judgment_date IS NOT NULL;")
    date_range = cur.fetchone()

    cur.execute("SELECT judge_name, COUNT(*) as cnt FROM supreme_court_cases GROUP BY judge_name ORDER BY cnt DESC LIMIT 5;")
    top_judges = cur.fetchall()

    cur.close()

    print(f"\n  Verification:")
    print(f"  Total cases:   {total}")
    print(f"  Unique judges: {judges}")
    print(f"  Date range:    {date_range[0]} to {date_range[1]}")
    print(f"\n  Top 5 judges by case count:")
    for name, cnt in top_judges:
        print(f"    {name}: {cnt} cases")


def main():
    print(f"Connecting to PostgreSQL: {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")

    try:
        conn = psycopg2.connect(
            host=POSTGRES_CONFIG["host"],
            port=POSTGRES_CONFIG["port"],
            database=POSTGRES_CONFIG["database"],
            user=POSTGRES_CONFIG["user"],
            password=POSTGRES_CONFIG["password"]
        )
        print("[OK] Connected to PostgreSQL.")
    except Exception as e:
        print(f"ERROR: Could not connect to PostgreSQL: {e}")
        sys.exit(1)

    create_table(conn)
    import_csv(conn)
    refresh_judges_table(conn)
    verify(conn)

    conn.close()
    print("\n[DONE] Supreme Court data is now in your PostgreSQL database.")
    print("  Table: supreme_court_cases")
    print("  Verify: SELECT * FROM supreme_court_cases LIMIT 10;")


if __name__ == "__main__":
    main()

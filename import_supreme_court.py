"""
Import Supreme Court case data into PostgreSQL and refresh its judge directory.
"""

import os
import sys

try:
    import psycopg2
    import pandas as pd
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install psycopg2-binary pandas openpyxl")
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
# Use the new Excel file that contains verdict information
EXCEL_FILE = os.path.join(BASE_DIR, "supreme_court_all_judges_verdict.csv.xlsx")


def create_table(conn):
    """Create the Supreme Court case and judge-directory tables if needed."""
    cur = conn.cursor()
    
    # Check if table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'supreme_court_cases'
        );
    """)
    table_exists = cur.fetchone()[0]
    
    if not table_exists:
        # Create table if it doesn't exist
        cur.execute("""
            CREATE TABLE supreme_court_cases (
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
                verdict TEXT,
                verified_outcome TEXT,
                outcome_verified_at TIMESTAMPTZ,
                imported_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created supreme_court_cases table.")
    else:
        # Table exists, check if verdict column exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'supreme_court_cases'
                AND column_name = 'verdict'
            );
        """)
        column_exists = cur.fetchone()[0]
        
        if not column_exists:
            # Add verdict column if it doesn't exist
            cur.execute("ALTER TABLE supreme_court_cases ADD COLUMN verdict TEXT;")
            print("[OK] Added verdict column to supreme_court_cases table.")

    cur.execute("""
        ALTER TABLE supreme_court_cases
        ADD COLUMN IF NOT EXISTS verified_outcome TEXT;
    """)
    cur.execute("""
        ALTER TABLE supreme_court_cases
        ADD COLUMN IF NOT EXISTS outcome_verified_at TIMESTAMPTZ;
    """)
    
    # Create indexes for common queries (they will be ignored if already exist)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_judge_name ON supreme_court_cases(judge_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_judgment_date ON supreme_court_cases(judgment_date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_year ON supreme_court_cases(year);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_status ON supreme_court_cases(status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sc_verdict ON supreme_court_cases(verdict);")
    
    # Ensure supreme_court_judges table exists
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
    """Read Excel and insert all rows into supreme_court_cases."""
    if not os.path.isfile(EXCEL_FILE):
        print(f"ERROR: Excel file not found: {EXCEL_FILE}")
        sys.exit(1)

    cur = conn.cursor()

    # Keep manual outcome reviews when imported case records are refreshed.
    df = pd.read_excel(EXCEL_FILE)
    cur.execute("""
        SELECT judge_name, case_id, title, judgment_date,
               verified_outcome, outcome_verified_at
        FROM supreme_court_cases
        WHERE verified_outcome IS NOT NULL;
    """)
    existing_reviews = {}
    for review in cur.fetchall():
        key = tuple(_normalize_case_key_part(value) for value in review[:3]) + (
            _normalize_case_date(review[3]),
        )
        existing_reviews[key] = (review[4], review[5])

    # Truncate only after the workbook and manual-review snapshot are available.
    cur.execute("TRUNCATE TABLE supreme_court_cases RESTART IDENTITY;")
    conn.commit()
    print("[OK] Truncated existing data.")

    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        try:
            judge_name_val = _normalize_case_key_part(row.get("judge_name"))
            case_id_val = _normalize_case_key_part(row.get("case_id"))
            title_val = _normalize_case_key_part(row.get("title"))

            # Parse year
            year_val = None
            if pd.notna(row.get("year")):
                try:
                    year_val = int(row["year"])
                except ValueError:
                    year_val = None

            # Parse judgment_date
            judgment_date_val = None
            if pd.notna(row.get("judgment_date")):
                # Convert pandas Timestamp to string format YYYY-MM-DD
                if hasattr(row["judgment_date"], 'strftime'):
                    judgment_date_val = row["judgment_date"].strftime("%Y-%m-%d")
                else:
                    judgment_date_val = str(row["judgment_date"])

            review_key = tuple(_normalize_case_key_part(value) for value in (
                judge_name_val, case_id_val, title_val
            )) + (_normalize_case_date(judgment_date_val),)
            verified_outcome_val, outcome_verified_at_val = existing_reviews.get(
                review_key, (None, None)
            )

            # Parse duration_days
            duration_val = None
            if pd.notna(row.get("duration_days")):
                try:
                    duration_val = int(row["duration_days"])
                except ValueError:
                    duration_val = None

            # Get verdict value
            verdict_val = None
            if pd.notna(row.get("verdict")):
                verdict_val = str(row["verdict"]).strip()

            cur.execute("""
                INSERT INTO supreme_court_cases
                    (judge_name, tier, year, case_id, title, state, bench,
                     district, complex, status, diary_number, advocates,
                     judgment_by, judgment_date, duration_days, judgment_url,
                     citation, citation_url, source_url, verdict,
                     verified_outcome, outcome_verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                judge_name_val or None,
                str(row.get("tier", "")).strip() or None,
                year_val,
                case_id_val or None,
                title_val or None,
                str(row.get("state", "")).strip() or None,
                str(row.get("bench", "")).strip() or None,
                str(row.get("district", "")).strip() or None,
                str(row.get("complex", "")).strip() or None,
                str(row.get("status", "")).strip() or None,
                str(row.get("diary_number", "")).strip() or None,
                str(row.get("advocates", "")).strip() or None,
                str(row.get("judgment_by", "")).strip() or None,
                judgment_date_val,
                duration_val,
                str(row.get("judgment_url", "")).strip() or None,
                str(row.get("citation", "")).strip() or None,
                str(row.get("citation_url", "")).strip() or None,
                str(row.get("source_url", "")).strip() or None,
                verdict_val,
                verified_outcome_val,
                outcome_verified_at_val
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


def _normalize_case_key_part(value):
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _normalize_case_date(value):
    normalized = _normalize_case_key_part(value)
    if len(normalized) >= 10 and normalized[4:5] == "-" and normalized[7:8] == "-":
        return normalized[:10]
    return normalized


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

    # Get verdict distribution
    cur.execute("""
        SELECT verdict, COUNT(*) as cnt 
        FROM supreme_court_cases 
        WHERE verdict IS NOT NULL 
        GROUP BY verdict 
        ORDER BY cnt DESC
    """)
    verdict_dist = cur.fetchall()

    cur.close()

    print(f"\n  Verification:")
    print(f"  Total cases:   {total}")
    print(f"  Unique judges: {judges}")
    print(f"  Date range:    {date_range[0]} to {date_range[1]}")
    print(f"\n  Top 5 judges by case count:")
    for name, cnt in top_judges:
        print(f"    {name}: {cnt} cases")
    
    print(f"\n  Verdict distribution (top 10):")
    for verdict, cnt in verdict_dist[:10]:
        print(f"    {verdict}: {cnt}")


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

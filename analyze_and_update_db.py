#!/usr/bin/env python3
"""
Analyze Supreme Court cases data and update PostgreSQL database with analysis results.
This script analyzes the supreme_court_cases table to compute additional metrics
and stores them back in the database.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# PostgreSQL Configuration (same as in data_service.py and import_supreme_court.py)
POSTGRES_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "ecourts_scraper"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "shs2004")
}

def get_db_connection():
    """Create and return a PostgreSQL database connection."""
    try:
        conn = psycopg2.connect(
            host=POSTGRES_CONFIG["host"],
            port=POSTGRES_CONFIG["port"],
            database=POSTGRES_CONFIG["database"],
            user=POSTGRES_CONFIG["user"],
            password=POSTGRES_CONFIG["password"]
        )
        return conn
    except Exception as e:
        print(f"ERROR: Could not connect to PostgreSQL: {e}")
        return None

def add_analysis_columns(conn):
    """Add analysis columns to supreme_court_cases table if they don't exist."""
    cur = conn.cursor()

    # List of columns to add with their definitions
    columns_to_add = [
        ("is_likely_criminal", "BOOLEAN DEFAULT FALSE"),
        ("is_likely_civil", "BOOLEAN DEFAULT FALSE"),
        ("case_type", "VARCHAR(20) DEFAULT 'UNKNOWN'"),
        ("duration_years", "FLOAT DEFAULT 0.0"),
        ("is_completed", "BOOLEAN DEFAULT FALSE"),
        ("is_pending", "BOOLEAN DEFAULT FALSE"),
        ("priority_score", "INTEGER DEFAULT 0")
    ]

    for column_name, column_def in columns_to_add:
        try:
            cur.execute(f"""
                ALTER TABLE supreme_court_cases
                ADD COLUMN IF NOT EXISTS {column_name} {column_def};
            """)
            print(f"[OK] Added column: {column_name}")
        except Exception as e:
            print(f"[WARNING] Could not add column {column_name}: {e}")

    conn.commit()
    cur.close()

def analyze_and_update_cases(conn):
    """Analyze Supreme Court cases and update the database with results."""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch all supreme court cases with relevant fields for analysis
    print("Fetching Supreme Court cases data for analysis...")
    cur.execute("""
        SELECT id, judge_name, title, status, duration_days, year, case_id
        FROM supreme_court_cases
        WHERE duration_days IS NOT NULL
    """)
    cases = cur.fetchall()
    print(f"[OK] Loaded {len(cases)} cases for analysis")

    # Keywords that suggest criminal cases (where conviction/acquittal is relevant)
    criminal_indicators = ['STATE OF', 'CRIMINAL', 'CRL.', 'IPC ', 'CRPC ']
    # Keywords that suggest civil cases
    civil_indicators = ['VSB', 'VST', ' COMPANY', ' CORPORATION', ' BANK', ' AUTHORITY', ' W.', ' W.S.']

    updated_count = 0

    for case in cases:
        case_id = case['id']
        title = case['title'] or ''
        status = case['status'] or ''
        duration_days = case['duration_days'] or 0

        # Convert title to uppercase for pattern matching
        title_upper = title.upper()

        # Determine if likely criminal case
        is_likely_criminal = any(indicator in title_upper for indicator in criminal_indicators)
        is_likely_civil = any(indicator in title_upper for indicator in civil_indicators)

        # Determine case type
        if is_likely_criminal:
            case_type = 'CRIMINAL'
        elif is_likely_civil:
            case_type = 'CIVIL'
        else:
            case_type = 'OTHER'

        # Duration analysis
        duration_years = duration_days / 365.25 if duration_days > 0 else 0.0

        # Status analysis
        status_upper = status.upper()
        is_completed = status_upper == 'COMPLETED'
        is_pending = status_upper in ['PENDING', 'HEARING', 'RESERVED']

        # Priority score: for criminal cases, higher score for longer duration
        # This helps identify cases where justice might be delayed
        priority_score = 0
        if is_likely_criminal and is_completed:
            priority_score = duration_days
        elif is_likely_criminal and is_pending:
            # Even higher score for pending criminal cases (justice delayed)
            priority_score = int(duration_days * 2)

        # Update the case with analysis results
        try:
            cur.execute("""
                UPDATE supreme_court_cases
                SET is_likely_criminal = %s,
                    is_likely_civil = %s,
                    case_type = %s,
                    duration_years = %s,
                    is_completed = %s,
                    is_pending = %s,
                    priority_score = %s
                WHERE id = %s
            """, (
                is_likely_criminal,
                is_likely_civil,
                case_type,
                duration_years,
                is_completed,
                is_pending,
                priority_score,
                case_id
            ))
            updated_count += 1

            # Commit every 50 records to avoid large transactions
            if updated_count % 50 == 0:
                conn.commit()
                print(f"[PROGRESS] Updated {updated_count} cases...")

        except Exception as e:
            print(f"[ERROR] Failed to update case ID {case_id}: {e}")
            conn.rollback()

    # Final commit
    conn.commit()
    cur.close()

    print(f"[OK] Successfully updated {updated_count} cases with analysis results")
    return updated_count

def print_analysis_summary(conn):
    """Print summary statistics of the analyzed cases."""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    print("\n" + "="*60)
    print("SUPREME COURT CASES ANALYSIS SUMMARY")
    print("="*60)

    # Overall statistics
    cur.execute("""
        SELECT
            COUNT(*) as total_cases,
            COUNT(CASE WHEN is_likely_criminal THEN 1 END) as criminal_cases,
            COUNT(CASE WHEN is_likely_civil THEN 1 END) as civil_cases,
            COUNT(CASE WHEN is_completed THEN 1 END) as completed_cases,
            COUNT(CASE WHEN is_pending THEN 1 END) as pending_cases,
            AVG(duration_days) as avg_duration_days,
            MAX(duration_days) as max_duration_days
        FROM supreme_court_cases
        WHERE duration_days IS NOT NULL AND duration_days > 0
    """)

    stats = cur.fetchone()

    if stats:
        total = stats['total_cases']
        if total > 0:
            print(f"Total cases analyzed: {total}")
            print(f"Likely criminal cases: {stats['criminal_cases']} ({stats['criminal_cases']/total*100:.1f}%)")
            print(f"Likely civil cases: {stats['civil_cases']} ({stats['civil_cases']/total*100:.1f}%)")
            print(f"Completed cases: {stats['completed_cases']} ({stats['completed_cases']/total*100:.1f}%)")
            print(f"Pending cases: {stats['pending_cases']} ({stats['pending_cases']/total*100:.1f}%)")
            print(f"Average duration: {stats['avg_duration_days']:.1f} days ({stats['avg_duration_days']/365.25:.2f} years)")
            print(f"Maximum duration: {stats['max_duration_days']} days ({stats['max_duration_days']/365.25:.2f} years)")

    # Top criminal cases by priority score
    print("\nTOP 10 CASES BY PRIORITY SCORE (Criminal cases weighted by duration):")
    print("-" * 70)
    cur.execute("""
        SELECT id, title, duration_days, priority_score, case_type
        FROM supreme_court_cases
        WHERE is_likely_criminal = TRUE
        ORDER BY priority_score DESC, duration_days DESC
        LIMIT 10
    """)

    top_criminal = cur.fetchall()
    for i, case in enumerate(top_criminal, 1):
        years = case['duration_days'] / 365.25
        print(f"{i:2d}. ID:{case['id']:4d} | {case['title'][:40]:<40} | {case['duration_days']:4d} days ({years:4.1f} yrs) | Score: {case['priority_score']}")

    # Top civil cases by duration
    print("\nTOP 10 LONGEST-RUNNING LIKELY CIVIL CASES:")
    print("-" * 70)
    cur.execute("""
        SELECT id, title, duration_days, case_type
        FROM supreme_court_cases
        WHERE is_likely_civil = TRUE
        ORDER BY duration_days DESC
        LIMIT 10
    """)

    top_civil = cur.fetchall()
    for i, case in enumerate(top_civil, 1):
        years = case['duration_days'] / 365.25
        print(f"{i:2d}. ID:{case['id']:4d} | {case['title'][:40]:<40} | {case['duration_days']:4d} days ({years:4.1f} yrs) | Type: {case['case_type']}")

    cur.close()
    print("="*60)

def main():
    """Main analysis function."""
    print("Supreme Court Case Analysis and Database Update")
    print("=" * 50)

    # Load the data
    conn = get_db_connection()

    if not conn:
        print("Failed to connect to database. Exiting.")
        return 1

    try:
        print("[OK] Connected to PostgreSQL database")

        # Add analysis columns if they don't exist
        print("\nAdding analysis columns to supreme_court_cases table...")
        add_analysis_columns(conn)

        # Analyze cases and update database
        print("\nAnalyzing cases and updating database...")
        updated_count = analyze_and_update_cases(conn)

        if updated_count > 0:
            # Print analysis summary
            print_analysis_summary(conn)
            print(f"\n[SUCCESS] Analysis complete! {updated_count} cases updated in the database.")
        else:
            print("\n[WARNING] No cases were updated.")

        return 0

    except Exception as e:
        print(f"[ERROR] An error occurred: {e}")
        return 1
    finally:
        if conn:
            conn.close()
            print("[OK] Database connection closed.")

if __name__ == "__main__":
    exit(main())
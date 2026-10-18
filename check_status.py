#!/usr/bin/env python3
"""
Check what values exist in the status and judgment_by fields for Supreme Court cases.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_service import get_db_connection

def check_status_values():
    """Check distinct values in status and judgment_by fields."""
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database")
        return

    try:
        cur = conn.cursor()

        # Check what values exist in the status field
        print("=== STATUS FIELD VALUES ===")
        cur.execute("""
            SELECT DISTINCT status, COUNT(*) as count
            FROM supreme_court_cases
            WHERE status IS NOT NULL
            GROUP BY status
            ORDER BY count DESC;
        """)
        status_results = cur.fetchall()
        for status, count in status_results:
            print(f"'{status}': {count}")

        print("\n=== JUDGMENT_BY FIELD VALUES ===")
        cur.execute("""
            SELECT DISTINCT judgment_by, COUNT(*) as count
            FROM supreme_court_cases
            WHERE judgment_by IS NOT NULL AND judgment_by <> ''
            GROUP BY judgment_by
            ORDER BY count DESC
            LIMIT 20;
        """)
        judgment_results = cur.fetchall()
        for judgment, count in judgment_results:
            print(f"'{judgment}': {count}")

        print("\n=== SAMPLE RECORDS ===")
        cur.execute("""
            SELECT id, title, status, judgment_by, duration_days
            FROM supreme_court_cases
            WHERE duration_days IS NOT NULL
            ORDER BY duration_days DESC
            LIMIT 10;
        """)
        samples = cur.fetchall()
        for sample in samples:
            print(f"ID: {sample[0]}, Title: {sample[1][:50]}..., Status: {sample[2]}, Judgment_by: {sample[3]}, Duration: {sample[4]} days")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        if conn:
            conn.close()

if __name__ == "__main__":
    check_status_values()
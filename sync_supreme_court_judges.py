"""Create and populate the Supreme Court judge directory from existing case data."""

import sys

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from import_supreme_court import POSTGRES_CONFIG, create_table, refresh_judges_table


def main():
    conn = None
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        create_table(conn)
        refresh_judges_table(conn)
        print("[DONE] supreme_court_judges is ready; existing case data was not modified.")
    except Exception as exc:
        print(f"ERROR: Could not sync Supreme Court judges: {exc}")
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()

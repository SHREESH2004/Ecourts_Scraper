import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Database configuration (same as in scraper)
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', 5432))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'ecourts_scraper')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')

def main():
    conn = None
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )

        if conn is None:
            print("Failed to connect to PostgreSQL")
            return

        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT COUNT(*) as total FROM eCourts_pdfs;")
        total = cursor.fetchone()['total']
        print(f"Total rows: {total}")

        cursor.execute("SELECT COUNT(*) as non_null_district FROM eCourts_pdfs WHERE district_code IS NOT NULL;")
        non_null_district = cursor.fetchone()['non_null_district']
        print(f"Rows with non-null district_code: {non_null_district}")

        cursor.execute("SELECT COUNT(*) as non_null_court FROM eCourts_pdfs WHERE court_code IS NOT NULL;")
        non_null_court = cursor.fetchone()['non_null_court']
        print(f"Rows with non-null court_code: {non_null_court}")

        # Show a few rows with non-null if any
        if non_null_district > 0 or non_null_court > 0:
            cursor.execute("SELECT * FROM eCourts_pdfs WHERE district_code IS NOT NULL OR court_code IS NOT NULL LIMIT 5;")
            rows = cursor.fetchall()
            if rows:
                columns = rows[0].keys() if rows else []
                print(" | ".join(columns))
                print("-" * (len(" | ".join(columns)) + 2))
                for row in rows:
                    values = [str(row[col]) for col in columns]
                    print(" | ".join(values))
        else:
            print("No rows with non-null district_code or court_code.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
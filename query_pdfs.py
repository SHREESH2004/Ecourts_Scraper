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
        cursor.execute("SELECT * FROM eCourts_pdfs;")
        rows = cursor.fetchall()

        if not rows:
            print("No records found in eCourts_pdfs table")
            return

        # Print column names
        columns = rows[0].keys() if rows else []
        print(" | ".join(columns))
        print("-" * (len(" | ".join(columns)) + 2))

        # Print each row
        for row in rows:
            values = [str(row[col]) for col in columns]
            print(" | ".join(values))

        print(f"\nTotal rows: {len(rows)}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
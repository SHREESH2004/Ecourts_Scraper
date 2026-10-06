"""
eCourts Judge Scraper - Direct PostgreSQL Insertion Version
Saves PDFs locally, inserts metadata directly into PostgreSQL,
with CSV export as backup. Skips Google Drive entirely per your request.
"""

import requests
import csv
import re
import time
import json
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to import PostgreSQL adapter - if not available, we'll still work with CSV only
try:
    import psycopg2
    from psycopg2.extras import execute_values
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("Warning: psycopg2 not installed. Install with: pip install psycopg2-binary")
    print("Working in CSV-only mode for now.")

# Try to import Redis - if not available, we'll still work without caching
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# =============================================
# ===== POSTGRESQL CONFIGURATION =============
# =============================================
# <<< UPDATE THESE VALUES WITH YOUR POSTGRESQL DETAILS >>>
POSTGRES_ENABLED = True  # Set to False to disable DB insertion
POSTGRES_HOST = "localhost"     # Your PostgreSQL host
POSTGRES_PORT = 5432            # Your PostgreSQL port
POSTGRES_DB = "ecourts_scraper" # Your database name
POSTGRES_USER = "postgres"      # Your username
POSTGRES_PASSWORD = "shs2004"   # ← YOUR PASSWORD (as provided)
# <<< END POSTGRESQL CONFIGURATION >>>

# Base URL for the eCourts HC services
BASE_URL = "https://hcservices.ecourts.gov.in/ecourtindiaHC"

# Base URL for PDF downloads (observed from working Chrome session)
PDF_BASE_URL = "https://hcservices.ecourts.gov.in/hcservices/cases"

# Directory to save downloaded PDFs
PDF_SAVE_DIR = "downloaded_pdfs"

# Metadata CSV file for backup/import
METADATA_CSV = "scraper_metadata.csv"

# Headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Redis configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_TTL = 86400  # 24 hours

# =============================================
# ===== POSTGRESQL FUNCTIONS =================
# =============================================

def get_postgres_connection():
    """Create and return PostgreSQL connection if enabled and available"""
    if not POSTGRES_ENABLED or not POSTGRES_AVAILABLE:
        return None
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        return conn
    except Exception as e:
        print(f"Warning: Could not connect to PostgreSQL: {e}")
        print("Falling back to CSV-only mode.")
        return None

def init_postgres_table():
    """Initialize the PostgreSQL table if it doesn't exist"""
    conn = get_postgres_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        create_table_query = """
        CREATE TABLE IF NOT EXISTS new_judges_records (
            id SERIAL PRIMARY KEY,
            timestamp_utc TIMESTAMP WITH TIME ZONE,
            judge_names TEXT,
            court_name TEXT,
            cause_list_date DATE,
            cause_list_id TEXT,
            cause_list_reference TEXT
        );
        """
        cursor.execute(create_table_query)
        conn.commit()
        cursor.close()
        conn.close()
        print("✓ PostgreSQL table ensured: new_judges_records")
        return True
    except Exception as e:
        print(f"Warning: Could not initialize PostgreSQL table: {e}")
        if conn:
            conn.close()
        return False
def save_to_postgres(metadata_record):
    """Save metadata record directly to PostgreSQL"""
    conn = get_postgres_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        insert_query = """
        INSERT INTO new_judges_records
        (timestamp_utc, judge_names, court_name, cause_list_date, cause_list_id, cause_list_reference)
        VALUES %s
        """

        # Convert None/empty values appropriately for PostgreSQL
        values = (
            metadata_record['timestamp_utc'],
            metadata_record['judge_names'],
            metadata_record['court_name'],
            metadata_record['cause_list_date'],
            metadata_record['cause_list_id'],
            metadata_record['cause_list_reference']
        )

        execute_values(cursor, insert_query, [values])
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Warning: Failed to insert into PostgreSQL: {e}")
        if conn:
            conn.close()
        return False
def save_metadata_record(metadata_record):
    """
    Save metadata record to PostgreSQL (primary) with CSV fallback.
    Returns True if saved to either PostgreSQL or CSV.
    """
    # Try PostgreSQL first if enabled
    postgres_success = False
    if POSTGRES_ENABLED:
        postgres_success = save_to_postgres(metadata_record)
        if postgres_success:
            # Uncomment below if you want to see each DB insert
            # print("  ✓ Metadata inserted into PostgreSQL")
            pass

    # Always save to CSV as backup/fallback
    csv_success = save_metadata_to_csv(metadata_record)

    # Return True if either succeeded
    return postgres_success or csv_success

def save_metadata_to_csv(metadata_record):
    """Save a metadata record to the CSV file (backup method)"""
    # Define CSV headers matching the minimal metadata format
    headers = [
        'timestamp_utc',
        'judge_names',
        'court_name',
        'cause_list_date',
        'cause_list_id',
        'cause_list_reference'
    ]

    # Check if file exists to determine if we need to write headers
    file_exists = os.path.isfile(METADATA_CSV)

    try:
        with open(METADATA_CSV, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)

            # Write header if file is new
            if not file_exists:
                writer.writeheader()

            # Write the record
            writer.writerow(metadata_record)

        # Uncomment below if you want to see each CSV save
        # print(f"  Metadata saved to CSV: {METADATA_CSV}")
        return True
    except Exception as e:
        print(f"  Warning: Could not save metadata to CSV: {e}")
        return False

# =============================================
# ===== REMAINING FUNCTIONS (UNCHANGED) =======
# =============================================

def get_redis_client():
    """Initialize and return Redis client if available"""
    if not REDIS_AVAILABLE:
        return None
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=False)
        client.ping()
        return client
    except Exception as e:
        print(f"Warning: Could not connect to Redis: {e}")
        print("Running without caching.")
        return None

def get_cache_key(state_code, district_code, court_code, date):
    """Generate a unique cache key"""
    date_str = date.strftime("%Y-%m-%d")
    court_part = court_code if court_code is not None else "none"
    return f"ecourts:{state_code}:{district_code}:{court_part}:{date_str}".encode('utf-8')

def get_cause_lists_from_cache(redis_client, state_code, district_code, court_code, date):
    """Try to get cause lists from Redis cache"""
    if not redis_client:
        return None
    try:
        key = get_cache_key(state_code, district_code, court_code, date)
        cached_data = redis_client.get(key)
        if cached_data is not None:
            return json.loads(cached_data.decode('utf-8'))
    except Exception as e:
        print(f"Warning: Redis get error: {e}")
    return None

def save_cause_lists_to_cache(redis_client, state_code, district_code, court_code, date, cause_lists):
    """Save cause lists to Redis cache"""
    if not redis_client:
        return
    try:
        key = get_cache_key(state_code, district_code, court_code, date)
        serializable_lists = []
        for cl in cause_lists:
            cl_copy = cl.copy()
            cl_copy['date'] = cl_copy['date'].isoformat()
            serializable_lists.append(cl_copy)
        redis_client.setex(key, REDIS_TTL, json.dumps(serializable_lists))
    except Exception as e:
        print(f"Warning: Redis set error: {e}")

def get_cause_lists_for_court(state_code, district_code, court_code, date, redis_client=None):
    """
    Fetch cause lists for a given court and date.
    Returns (cause_lists, session) where session is the requests.Session used
    (to reuse cookies for PDF downloads).
    Uses Redis cache if available, otherwise fetches from API.
    """
    # Try cache first
    cached_data = get_cause_lists_from_cache(redis_client, state_code, district_code, court_code, date)
    if cached_data is not None:
        for cl in cached_data:
            cl['date'] = datetime.fromisoformat(cl['date'])
        # Return cached data with a dummy session (we won't use it for PDFs from cache)
        # For cached data, we cannot reuse session; PDF download will need to create a new session.
        # We'll return None for session to indicate no session available.
        return cached_data, None

    # Cache miss - fetch from API
    url = f"{BASE_URL}/cases/highcourt_causelist_qry.php"
    params = {
        "state_code": state_code,
        "dist_code": district_code,
        "court_code": court_code if court_code is not None else "1",
        "causelist_dt": date.strftime("%d-%m-%Y"),
        "action_code": "pulishedCauselist"
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.post(url, data=params, timeout=15)
        resp.raise_for_status()
        text = resp.content.decode('utf-8-sig')
        text_upper = text.upper()[:30]
        if "ERROR" in text_upper or "INVALID CAPTCHA" in text_upper:
            print(f"Error in response for {date.date()}: {text[:200]}")
            return [], session
        if not text.strip():
            print(f"Empty response for {date.date()}")
            return [], session
        records = text.strip().split("^#")
        cause_lists = []
        for record in records:
            fields = record.split("~")
            if len(fields) < 9:
                continue
            bench = fields[1].strip()
            ctype = fields[2].strip()
            filename = fields[4].strip()
            eliminated = fields[5].strip() == "Y"
            bench_id = fields[6].strip()
            causelist_id = fields[7].strip()

            cause_lists.append({
                "judge": bench,
                "type": ctype,
                "filename": filename,
                "eliminated": eliminated,
                "bench_id": bench_id,
                "cause_list_id": causelist_id,
                "date": date
            })
        save_cause_lists_to_cache(redis_client, state_code, district_code, court_code, date, cause_lists)
        return cause_lists, session
    except Exception as e:
        print(f"Error fetching cause lists for {date.date()}: {e}")
        return [], session

def get_cause_list_pdf_url(filename, date):
    """
    Construct URL to download the actual cause list PDF.
    Based on observed working Chrome session:
    https://hcservices.ecourts.gov.in/hcservices/cases/display_causelist_pdf.php?filename=...&causelistYear=YYYY
    """
    year = date.strftime("%Y")
    return f"{PDF_BASE_URL}/display_causelist_pdf.php?filename={filename}&causelistYear={year}"

def extract_case_information_from_text(text):
    """
    Extract case information from cause list document text
    Returns a dictionary with case numbers, parties, and other details
    """

    # Initialize result dictionary
    info = {
        'case_numbers': [],
        'petitioners': [],
        'respondents': [],
        'advocates': [],
        'hearing_dates': [],
        'status_indicators': [],
        'raw_text_preview': text[:500] if text else ''
    }

    if not text:
        return info

    # Case number patterns
    case_patterns = [
        r'[A-Z&\(\)]+\s*\d+/\d{4}',  # e.g., CRLMC 123/2026
        r'[A-Z&\(\)]+\s*\d+/\d{2}',   # e.g., WP(C) 456/26
        r'\d+/\d{4}',                 # e.g., 123/2026 (fallback)
    ]

    # Party name patterns (simplified)
    party_patterns = [
        r'(?:Petitioner|Appellant|Applicant)[:\s]+([^\n\r]+)',
        r'(?:Respondent|Opposite Party)[:\s]+([^\n\r]+)',
        r'(?:Vs|v\.?|VS)\s*[:\s]+([^\n\r]+)',
    ]

    # Advocate patterns
    advocate_patterns = [
        r'(?:Advocate|Counsel for)[:\s]+([^\n\r]+)',
        r'(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+\([^)]*\))*',
    ]

    # Date patterns
    date_patterns = [
        r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}',
        r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}',
    ]

    # Status indicators
    status_keywords = [
        'pending', 'disposed', 'judgment pronounced', 'allowed', 'dismissed',
        'acquitted', 'convicted', 'sentenced', 'bail granted', 'bail refused',
        'arguments', 'hearing', 'final orders', 'order reserved'
    ]

    # Extract case numbers
    for pattern in case_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        info['case_numbers'].extend(matches)

    # Extract potential petitioner/respondent names
    for pattern in party_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        info['petitioners'].extend([m.strip() for m in matches if m.strip()])

    # Extract advocates
    for pattern in advocate_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        info['advocates'].extend([m.strip() for m in matches if m.strip()])

    # Extract dates
    for pattern in date_patterns:
        matches = re.findall(pattern, text)
        info['hearing_dates'].extend(matches)

    # Extract status indicators (case-insensitive)
    text_lower = text.lower()
    for keyword in status_keywords:
        if keyword in text_lower:
            info['status_indicators'].append(keyword)

    # Remove duplicates while preserving order
    def deduplicate(seq):
        seen = set()
        return [x for x in seq if not (x in seen or seen.add(x))]

    info['case_numbers'] = deduplicate(info['case_numbers'])
    info['petitioners'] = deduplicate(info['petitioners'])
    info['respondents'] = deduplicate(info['respondents'])  # Simplified - in reality we'd parse Vs patterns better
    info['advocates'] = deduplicate(info['advocates'])
    info['hearing_dates'] = deduplicate(info['hearing_dates'])
    info['status_indicators'] = deduplicate(info['status_indicators'])

    # Limit lists to prevent overly verbose output
    info['case_numbers'] = info['case_numbers'][:10]
    info['petitioners'] = info['petitioners'][:5]
    info['respondents'] = info['respondents'][:5]
    info['advocates'] = info['advocates'][:5]
    info['hearing_dates'] = info['hearing_dates'][:5]
    info['status_indicators'] = info['status_indicators'][:10]

    return info

def init_metadata_csv():
    """
    Initialize the metadata CSV file with headers if it doesn't exist
    (kept for backup purposes)
    """
    if not os.path.isfile(METADATA_CSV):
        headers = [
            'timestamp_utc',
            'judge_names',
            'court_name',
            'cause_list_date',
            'cause_list_id',
            'cause_list_reference'
        ]
        try:
            with open(METADATA_CSV, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
            print(f"Initialized metadata CSV (backup): {METADATA_CSV}")
        except Exception as e:
            print(f"Warning: Could not initialize metadata CSV: {e}")

def fetch_and_parse_cause_list_document(session, filename, date, judge_names=None, court_name=None, cause_list_id=None):
    """
    Download and save the cause list PDF to a folder.
    Uses the provided session (with cookies) to mimic the working Chrome session.
    Does NOT extract text or case information (as per user request).
    Note: state_code, district_code, and court_code parameters are not used in this function
    as they are not required for the current PDF URL construction pattern.
    """
    try:
        # Construct PDF URL
        pdf_url = get_cause_list_pdf_url(filename, date)
        # Set Referer header to the eCourts main page (as seen in Chrome)
        headers = session.headers.copy()
        headers['Referer'] = 'https://hcservices.ecourts.gov.in/ecourtindiaHC/'
        # Optional: also set Origin?
        # headers['Origin'] = 'https://hcservices.ecourts.gov.in'

        print(f"  Downloading PDF: {pdf_url}")
        resp = session.get(pdf_url, headers=headers, timeout=15)
        print(f"  PDF request status: {resp.status_code}, Content-Type: {resp.headers.get('Content-Type', 'unknown')}, Size: {len(resp.content)} bytes")

        if resp.status_code != 200:
            print(f"  PDF download failed with status {resp.status_code}")
            return {}

        content = resp.content

        # Save PDF to disk
        try:
            # Create PDF save directory if it doesn't exist
            if not os.path.exists(PDF_SAVE_DIR):
                os.makedirs(PDF_SAVE_DIR)

            # Sanitize filename for filesystem safety (remove/replace problematic chars)
            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._- ')
            if not safe_filename:
                safe_filename = "unknown"
            # Add timestamp to avoid collisions
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_save_path = os.path.join(PDF_SAVE_DIR, f"{timestamp}_{safe_filename}.pdf")

            # Save the PDF
            with open(pdf_save_path, "wb") as f:
                f.write(content)
            print(f"  PDF saved to: {pdf_save_path}")
        except Exception as e:
            print(f"  Warning: Could not save PDF to disk: {e}")

        # Validate PDF content - only save metadata for actual PDFs
        if content.startswith(b'%PDF'):
            # Prepare metadata record with only the 5 requested fields + timestamp_utc
            metadata_record = {
                'timestamp_utc': datetime.now().isoformat(),
                'judge_names': ' | '.join(judge_names) if judge_names else '',
                'court_name': court_name,
                'cause_list_date': date.date().isoformat() if hasattr(date, 'date') else str(date),
                'cause_list_id': cause_list_id,
                'cause_list_reference': filename
            }

            # Save metadata record (to PostgreSQL with CSV fallback)
            save_metadata_record(metadata_record)

            return metadata_record
        else:
            print(f"  Warning: Downloaded content does not appear to be a valid PDF (does not start with %PDF)")
            print(f"  First 20 bytes: {content[:20]}")
            print(f"  Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
            # Don't save metadata for non-PDF content
            return {}
    except Exception as e:
        print(f"  Error fetching/saving PDF: {e}")
        return {}

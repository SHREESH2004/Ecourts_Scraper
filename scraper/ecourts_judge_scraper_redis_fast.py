"""
eCourts Judge Scraper - Redis Cached + Parallel Version
Combines Redis caching with parallel day checking for maximum performance
"""

import requests
import csv
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# Try to import Redis - if not available, we'll still work without caching
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("Warning: Redis package not installed. Install with: pip install redis")
    print("Running without caching - consider installing redis for better performance on repeated runs.")

# Base URL for the eCourts HC services
BASE_URL = "https://hcservices.ecourts.gov.in/ecourtindiaHC"

# Headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Redis configuration (adjust if your Docker setup is different)
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_TTL = 86400  # 24 hours in seconds - cause lists don't change after the date passes

def get_redis_client():
    """Initialize and return Redis client if available"""
    if not REDIS_AVAILABLE:
        return None
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=False)
        # Test connection
        client.ping()
        return client
    except Exception as e:
        print(f"Warning: Could not connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
        print("Running without caching.")
        return None

def get_cache_key(state_code, district_code, court_code, date):
    """Generate a unique cache key for the given parameters"""
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
            import json
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
        import json
        # Convert date objects to strings for JSON serialization
        serializable_lists = []
        for cl in cause_lists:
            cl_copy = cl.copy()
            cl_copy['date'] = cl_copy['date'].isoformat()  # Convert datetime to string
            serializable_lists.append(cl_copy)
        redis_client.setex(key, REDIS_TTL, json.dumps(serializable_lists))
    except Exception as e:
        print(f"Warning: Redis set error: {e}")

def get_cause_lists_for_court(state_code, district_code, court_code, date, redis_client=None):
    """
    Fetch cause lists for a given court and date.
    Uses Redis cache if available, otherwise fetches from API.
    Returns a list of dictionaries with cause list information.
    """
    # Try cache first
    cached_data = get_cause_lists_from_cache(redis_client, state_code, district_code, court_code, date)
    if cached_data is not None:
        # Convert date strings back to datetime objects
        for cl in cached_data:
            cl['date'] = datetime.fromisoformat(cl['date'])
        return cached_data

    # Cache miss - fetch from API
    url = f"{BASE_URL}/cases/highcourt_causelist_qry.php"
    # Parameters: state_code, dist_code, court_code, causelist_dt, and action_code
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
        resp = session.post(url, data=params, timeout=10)
        resp.raise_for_status()
        # Decode with UTF-8-SIG to strip BOM if present
        text = resp.content.decode('utf-8-sig')
        # The ecourts library checks for ERROR or INVALID CAPTCHA in the first 30 chars uppercase
        text_upper = text.upper()[:30]
        if "ERROR" in text_upper or "INVALID CAPTCHA" in text_upper:
            print(f"Error in response: {text[:200]}")
            return []
        # Parse the response
        # Format: records separated by "^#", fields by "~"
        if not text.strip():
            print("Empty response")
            return []
        records = text.strip().split("^#")
        cause_lists = []
        for record in records:
            fields = record.split("~")
            if len(fields) < 9:
                continue
            # According to the parser in ecourts/parsers/cause_lists.py
            bench = fields[1].strip()
            ctype = fields[2].strip()
            # date1 = fields[3].strip()  # DD-MM-YYYY
            filename = fields[4].strip()
            eliminated = fields[5].strip() == "Y"
            bench_id = fields[6].strip()
            causelist_id = fields[7].strip()
            # date2 = fields[8].strip()  # YYYY-MM-DD
            cause_lists.append({
                "judge": bench,
                "type": ctype,
                "filename": filename,
                "eliminated": eliminated,
                "bench_id": bench_id,
                "causelist_id": causelist_id,
                # We can also store the date if needed
                "date": date
            })
        # Save to cache for future use
        save_cause_lists_to_cache(redis_client, state_code, district_code, court_code, date, cause_lists)
        return cause_lists
    except Exception as e:
        print(f"Error fetching cause lists for {date.date()}: {e}")
        return []

def main():
    """
    Main function to scrape judge information from eCourts cause lists
    Uses Redis caching and parallel day checking for performance
    """
    # Use a raw string for the Windows path to courts.csv
    # Update this path if your courts.csv is located elsewhere
    courts_csv_path = r'C:\Users\Shreesh\AppData\Local\Temp\ecourts-main\courts.csv'

    # Alternative: if you have courts.csv in the same directory as this script:
    # courts_csv_path = 'courts.csv'

    # Get user input for state code
    print("\n=== eCourts Judge Scraper (Redis Cached + Parallel) ===")
    state_code = input("Enter State Code (e.g., 1 for Maharashtra): ").strip()
    if not state_code:
        state_code = "1"  # Default to Maharashtra
        print(f"Using default state code: {state_code}")

    # Load courts.csv to let user select a court
    courts = []
    try:
        with open(courts_csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['state_code'] == state_code and row['court_code'].strip() != '':
                    courts.append(row)
    except FileNotFoundError:
        print(f"Error: Could not find courts.csv at {courts_csv_path}")
        print("Please make sure the file exists and the path is correct.")
        return

    if not courts:
        print(f"No courts found for state code {state_code} with court codes in the CSV file")
        return

    # Display available courts and let user choose
    print(f"\nAvailable courts for state code {state_code}:")
    for i, court in enumerate(courts, 1):
        print(f"{i}. {court['name']} (Court Code: {court['court_code']})")

    # Get user selection
    while True:
        try:
            choice = input(f"\nSelect a court (1-{len(courts)}): ").strip()
            if not choice:
                choice = "1"  # Default to first court
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(courts):
                break
            else:
                print(f"Please enter a number between 1 and {len(courts)}")
        except ValueError:
            print("Please enter a valid number")

    court_data = courts[choice_idx]
    state_code = court_data['state_code']
    # district_code is always "1" as per the Court class in the ecourts library
    district_code = "1"
    court_code = court_data['court_code']
    # If court_code is empty string, treat as None
    if court_code == '':
        court_code = None

    print(f"\nSelected court: {state_code}, {district_code}, {court_code} - {court_data['state_name']} - {court_data['name']}")

    # Get number of days to check back
    while True:
        try:
            days_input = input("\nEnter number of days to check back (including today): ").strip()
            if not days_input:
                days_input = "10"  # Default to 10 days for better caching demonstration
            days_to_check = int(days_input)
            if days_to_check > 0:
                break
            else:
                print("Please enter a positive number")
        except ValueError:
            print("Please enter a valid number")

    # Initialize Redis client
    redis_client = get_redis_client()
    if redis_client:
        print(f"✓ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
    else:
        print("⚠ Running without Redis caching")

    # Prepare list of dates to check
    dates_to_check = []
    for days_ago in range(0, days_to_check):
        date = datetime.today() - timedelta(days=days_ago)
        dates_to_check.append(date)

    print(f"\nChecking {len(dates_to_check)} days going back from {dates_to_check[0].date()}...")
    if redis_client:
        print("  (Using Redis cache - previously fetched dates will be instant)")

    # Check multiple days in parallel
    all_cause_lists = []
    successful_dates = []

    # Use ThreadPoolExecutor for parallel fetching
    # Limit workers to avoid overwhelming the server - 5 is usually good
    max_workers = min(5, len(dates_to_check))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_date = {
            executor.submit(get_cause_lists_for_court, state_code, district_code, court_code, date, redis_client): date
            for date in dates_to_check
        }

        # Process completed tasks
        for future in as_completed(future_to_date):
            date = future_to_date[future]
            try:
                cause_lists = future.result()
                if cause_lists:
                    print(f"  ✓ {date.date()}: {len(cause_lists)} cause lists")
                    all_cause_lists.extend(cause_lists)
                    successful_dates.append(date)
                else:
                    print(f"  ✗ {date.date()}: No cause lists")
            except Exception as e:
                print(f"  ✗ {date.date()}: Error - {e}")

    if not all_cause_lists:
        print(f"\nNo cause lists found in the last {days_to_check} days.")
        return

    print(f"\n=== Successfully processed {len(successful_dates)} days with cause list data ===")
    if successful_dates:
        print(f"Date range: {min(successful_dates).date()} to {max(successful_dates).date()}")

    # Process all cause lists to collect unique judges and their cause list types
    judge_info = {}  # key: judge name, value: dict with metadata
    for cl in all_cause_lists:
        judge = cl['judge']
        if judge not in judge_info:
            judge_info[judge] = {
                'types': set(),
                'filenames': set(),
                'eliminated': set(),
                'bench_ids': set(),
                'cause_list_ids': set(),
                'dates': set()
            }
        judge_info[judge]['types'].add(cl['type'])
        judge_info[judge]['filenames'].add(cl['filename'])
        judge_info[judge]['eliminated'].add(cl['eliminated'])
        judge_info[judge]['bench_ids'].add(cl['bench_id'])
        judge_info[judge]['cause_list_ids'].add(cl['causelist_id'])
        judge_info[judge]['dates'].add(cl['date'])

    print(f"\n=== Summary of Unique Judges (Across {len(successful_dates)} Days) ===")
    print(f"Court: {court_data['state_name']} - {court_data['name']} (State Code: {state_code}, Court Code: {court_code})")
    print(f"Total unique judges found: {len(judge_info)}")
    print(f"Total cause lists processed: {len(all_cause_lists)}")

    # Count eliminations
    eliminated_count = sum(1 for cl in all_cause_lists if cl['eliminated'])
    active_count = len(all_cause_lists) - eliminated_count
    print(f"Active cause lists: {active_count}, Eliminated: {eliminated_count}")
    print()

    # Show breakdown by cause list type
    type_counts = {}
    for cl in all_cause_lists:
        ctype = cl['type']
        type_counts[ctype] = type_counts.get(ctype, 0) + 1

    print("Cause List Type Distribution (Across All Days):")
    for ctype, count in sorted(type_counts.items()):
        print(f"  {ctype}: {count}")
    print()

    # Show breakdown by date
    date_counts = {}
    for cl in all_cause_lists:
        date_str = cl['date'].date().isoformat()
        date_counts[date_str] = date_counts.get(date_str, 0) + 1

    print("Daily Cause List Count:")
    for date_str in sorted(date_counts.keys(), reverse=True):
        print(f"  {date_str}: {date_counts[date_str]} cause lists")
    print()

    for judge, info in judge_info.items():
        print(f"Judge: {judge}")
        print(f"  Associated Cause List Types: {', '.join(sorted(info['types']))}")
        print(f"  Number of Cause List Entries: {len(info['filenames'])}")
        # Show cause list filenames/IDs for reference
        if info['filenames']:
            # Show first few filenames if there are many
            filenames_list = sorted(info['filenames'])
            if len(filenames_list) <= 3:
                filenames_str = ', '.join(filenames_list)
            else:
                filenames_str = ', '.join(filenames_list[:3]) + f", and {len(filenames_list) - 3} more"
            print(f"  Cause List References: {filenames_str}")
        # Show eliminated vs active
        eliminated_count = sum(info['eliminated'])
        active_count = len(info['filenames']) - eliminated_count
        if eliminated_count > 0:
            print(f"  Active/Eliminated: {active_count}/{eliminated_count}")
        # Show date range for this judge
        dates_list = sorted(info['dates'])
        if len(dates_list) <= 3:
            dates_str = ', '.join([str(d.date()) for d in dates_list])
        else:
            dates_str = f"{dates_list[0].date()} to {dates_list[-1].date()} ({len(dates_list)} days)"
        print(f"  Date(s): {dates_str}")
        print()

if __name__ == "__main__":
    main()
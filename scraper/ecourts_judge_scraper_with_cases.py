"""
eCourts Judge Scraper - Enhanced with Case References
Shows judge assignments plus case list references for manual case lookup
"""

import requests
import csv
import re
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to import Redis - if not available, we'll still work without caching
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Base URL for the eCourts HC services
BASE_URL = "https://hcservices.ecourts.gov.in/ecourtindiaHC"

# Headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Redis configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_TTL = 86400  # 24 hours

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
        serializable_lists = []
        for cl in cause_lists:
            cl_copy = cl.copy()
            cl_copy['date'] = cl_copy['date'].isoformat()
            serializable_lists.append(cl_copy)
        redis_client.setex(key, REDIS_TTL, json.dumps(serializable_lists))
    except Exception as e:
        print(f"Warning: Redis set error: {e}")

def get_cause_list_document_url(state_code, district_code, court_code, filename):
    """
    Construct URL to download the actual cause list document
    The filename from cause list API is typically a reference to download the PDF/HTML
    """
    # Attempt to construct URL with court codes - adjust pattern as needed for specific court
    # Common patterns might include the codes in the path
    if state_code and district_code and court_code:
        return f"{BASE_URL}/{state_code}/{district_code}/{court_code}/views/{filename}"
    else:
        # Fallback to simple pattern
        return f"{BASE_URL}/views/{filename}"

def extract_case_numbers_from_text(text):
    """
    Extract potential case numbers from text using common patterns
    This is a heuristic - actual format may vary by court
    """
    # Common case number patterns in Indian courts:
    # - CRLMC 123/2026
    # - WP(C) 456/2026
    # - CRR 789/2026
    # - CS(OS) 101/2026
    # - etc.

    patterns = [
        r'[A-Z&\(\)]+\s*\d+/\d{4}',  # e.g., CRLMC 123/2026
        r'[A-Z&\(\)]+\s*\d+/\d{2}',   # e.g., WP(C) 456/26
        r'\d+/\d{4}',                 # e.g., 123/2026 (fallback)
    ]

    case_numbers = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        case_numbers.extend(matches)

    # Remove duplicates while preserving order
    seen = set()
    unique_case_numbers = []
    for cn in case_numbers:
        if cn not in seen:
            seen.add(cn)
            unique_case_numbers.append(cn)

    return unique_case_numbers

def get_cause_lists_for_court(state_code, district_code, court_code, date, redis_client=None):
    """
    Fetch cause lists for a given court and date.
    Uses Redis cache if available, otherwise fetches from API.
    """
    # Try cache first
    cached_data = get_cause_lists_from_cache(redis_client, state_code, district_code, court_code, date)
    if cached_data is not None:
        for cl in cached_data:
            cl['date'] = datetime.fromisoformat(cl['date'])
        return cached_data

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
            return []
        if not text.strip():
            print(f"Empty response for {date.date()}")
            return []
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
                "causelist_id": causelist_id,
                "date": date
            })
        save_cause_lists_to_cache(redis_client, state_code, district_code, court_code, date, cause_lists)
        return cause_lists
    except Exception as e:
        print(f"Error fetching cause lists for {date.date()}: {e}")
        return []

def extract_case_information_from_text(text):
    """
    Extract case information from cause list document text
    Returns a dictionary with case numbers, parties, and other details
    """
    import re

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


def fetch_and_parse_cause_list_document(state_code, district_code, court_code, filename):
    """
    Attempt to fetch and parse the actual cause list document to extract case information
    Returns a dictionary with extracted information or empty dict on failure
    """
    try:
        doc_url = get_cause_list_document_url(state_code, district_code, court_code, filename)
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(doc_url, timeout=15)
        if resp.status_code == 200:
            # Check if document is a PDF
            content = resp.content
            text = ""

            # Check for PDF signature
            if content.startswith(b'%PDF'):
                # Try to extract text from PDF
                try:
                    import PyPDF2
                    import io
                    pdf_file = io.BytesIO(content)
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                except ImportError:
                    # PyPDF2 not available, fall back to treating as text (may not work well)
                    text = resp.text
                except Exception:
                    # PDF parsing failed, fall back to treating as text
                    text = resp.text
            else:
                # Not a PDF, treat as regular text
                text = resp.text

            # Try to extract case information from the document text
            return extract_case_information_from_text(text)
        else:
            # Document might be PDF, require different access, or be unavailable
            return {}
    except Exception:
        # Silently fail - document fetching is bonus feature
        return {}

def main():
    """
    Main function to scrape judge information with case references
    """
    courts_csv_path = r'C:\Users\Shreesh\AppData\Local\Temp\ecourts-main\courts.csv'

    print("\n=== eCourts Judge Scraper (Enhanced with Case References) ===")
    print("This version shows judge assignments plus cause list references")
    print("so you can manually look up case numbers and status on eCourts website.")
    print()

    state_code = input("Enter State Code (e.g., 1 for Maharashtra): ").strip()
    if not state_code:
        state_code = "1"
        print(f"Using default state code: {state_code}")

    courts = []
    try:
        with open(courts_csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['state_code'] == state_code and row['court_code'].strip() != '':
                    courts.append(row)
    except FileNotFoundError:
        print(f"Error: Could not find courts.csv at {courts_csv_path}")
        return

    if not courts:
        print(f"No courts found for state code {state_code}")
        return

    print(f"\nAvailable courts for state code {state_code}:")
    for i, court in enumerate(courts, 1):
        print(f"{i}. {court['name']} (Court Code: {court['court_code']})")

    while True:
        try:
            choice = input(f"\nSelect a court (1-{len(courts)}): ").strip()
            if not choice:
                choice = "1"
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(courts):
                break
            else:
                print(f"Please enter a number between 1 and {len(courts)}")
        except ValueError:
            print("Please enter a valid number")

    court_data = courts[choice_idx]
    state_code = court_data['state_code']
    district_code = "1"
    court_code = court_data['court_code']
    if court_code == '':
        court_code = None

    print(f"\nSelected court: {state_code}, {district_code}, {court_code} - {court_data['state_name']} - {court_data['name']}")

    while True:
        try:
            days_input = input("\nEnter number of days to check back (including today): ").strip()
            if not days_input:
                days_input = "3"
            days_to_check = int(days_input)
            if days_to_check > 0:
                break
            else:
                print("Please enter a positive number")
        except ValueError:
            print("Please enter a valid number")

    redis_client = get_redis_client()
    if redis_client:
        print(f"✓ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
    else:
        print("⚠ Running without Redis caching")

    # Prepare dates
    dates_to_check = [datetime.today() - timedelta(days=i) for i in range(0, days_to_check)]

    print(f"\nChecking {len(dates_to_check)} days going back from {dates_to_check[0].date()}...")
    if redis_client:
        print("  (Using Redis cache)")

    # Parallel processing
    all_cause_lists = []
    successful_dates = []

    max_workers = min(5, len(dates_to_check))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_date = {
            executor.submit(get_cause_lists_for_court, state_code, district_code, court_code, date, redis_client): date
            for date in dates_to_check
        }

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

    print(f"\n=== Successfully processed {len(successful_dates)} days ===")
    if successful_dates:
        print(f"Date range: {min(successful_dates).date()} to {max(successful_dates).date()}")

    # Process cause lists to collect judge info
    judge_info = {}
    case_references = {}  # Track case list filenames for each judge

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
            case_references[judge] = set()

        judge_info[judge]['types'].add(cl['type'])
        judge_info[judge]['filenames'].add(cl['filename'])
        judge_info[judge]['eliminated'].add(cl['eliminated'])
        judge_info[judge]['bench_ids'].add(cl['bench_id'])
        judge_info[judge]['cause_list_ids'].add(cl['causelist_id'])
        judge_info[judge]['dates'].add(cl['date'])
        case_references[judge].add(cl['filename'])

    print(f"\n=== Summary of Unique Judges (Across {len(successful_dates)} Days) ===")
    print(f"Court: {court_data['state_name']} - {court_data['name']} (State Code: {state_code}, Court Code: {court_code})")
    print(f"Total unique judges found: {len(judge_info)}")
    print(f"Total cause lists processed: {len(all_cause_lists)}")

    eliminated_count = sum(1 for cl in all_cause_lists if cl['eliminated'])
    active_count = len(all_cause_lists) - eliminated_count
    print(f"Active cause lists: {active_count}, Eliminated: {eliminated_count}")
    print()

    # Cause list type distribution
    type_counts = {}
    for cl in all_cause_lists:
        ctype = cl['type']
        type_counts[ctype] = type_counts.get(ctype, 0) + 1

    print("Cause List Type Distribution:")
    for ctype, count in sorted(type_counts.items()):
        print(f"  {ctype}: {count}")
    print()

    # Daily breakdown
    date_counts = {}
    for cl in all_cause_lists:
        date_str = cl['date'].date().isoformat()
        date_counts[date_str] = date_counts.get(date_str, 0) + 1

    print("Daily Cause List Count:")
    for date_str in sorted(date_counts.keys(), reverse=True):
        print(f"  {date_str}: {date_counts[date_str]} cause lists")
    print()

    # Fetch and parse cause list documents to extract case information
    print("🔍 Fetching cause list documents to extract case details...")
    document_info_cache = {}  # Cache document info by filename to avoid re-fetching

    # Get unique filenames across all cause lists
    all_filenames = set()
    for info in judge_info.values():
        all_filenames.update(info['filenames'])

    print(f"  Found {len(all_filenames)} unique cause list documents to process")

    # Process each unique filename
    for i, filename in enumerate(sorted(all_filenames), 1):
        if i % 10 == 0 or i == len(all_filenames):
            print(f"  Processing document {i}/{len(all_filenames)}: {filename[:30]}...")

        # Check cache first
        if filename in document_info_cache:
            continue

        # Fetch and parse document
        # We need state_code, district_code, court_code for URL construction
        # These are consistent for all documents in this court
        doc_info = fetch_and_parse_cause_list_document(
            state_code=court_data['state_code'],
            district_code=district_code,  # This is always "1" for High Courts
            court_code=court_code,
            filename=filename
        )
        document_info_cache[filename] = doc_info

        # Small delay to be respectful to the server
        if i < len(all_filenames):
            time.sleep(0.1)

    print(f"  ✓ Completed processing {len(document_info_cache)} documents\n")

    # Enhanced judge details with case references
    print("=== Judge Assignments with Case References ===")
    print("(Case list filenames point to actual cause list documents where case numbers can be found)\n")

    for judge, info in judge_info.items():
        print(f"Judge: {judge}")
        print(f"  Cause List Types: {', '.join(sorted(info['types']))}")
        print(f"  Total Appearances: {len(info['filenames'])}")

        # Show eliminated vs active
        eliminated_count = sum(info['eliminated'])
        active_count = len(info['filenames']) - eliminated_count
        if eliminated_count > 0:
            print(f"  Active/Eliminated: {active_count}/{eliminated_count}")

        # Show case list references (the key to finding case numbers)
        if info['filenames']:
            filenames_list = sorted(info['filenames'])
            if len(filenames_list) <= 5:
                refs_str = ', '.join(filenames_list)
            else:
                refs_str = ', '.join(filenames_list[:3]) + f", and {len(filenames_list) - 3} more"
            print(f"  Case List References: {refs_str}")
            print(f"    → Visit eCourts website and search for these references to see case numbers")

            # Show extracted case information from documents
            doc_info_list = []
            for filename in info['filenames']:
                if filename in document_info_cache:
                    doc_info = document_info_cache[filename]
                    if doc_info:  # Only show if we extracted information
                        doc_info_list.append(doc_info)

            if doc_info_list:
                # Combine information from all documents for this judge
                combined_case_numbers = set()
                combined_petitioners = set()
                combined_respondents = set()
                combined_advocates = set()
                combined_hearing_dates = set()
                combined_status_indicators = set()

                for doc_info in doc_info_list:
                    combined_case_numbers.update(doc_info.get('case_numbers', []))
                    combined_petitioners.update(doc_info.get('petitioners', []))
                    combined_respondents.update(doc_info.get('respondents', []))
                    combined_advocates.update(doc_info.get('advocates', []))
                    combined_hearing_dates.update(doc_info.get('hearing_dates', []))
                    combined_status_indicators.update(doc_info.get('status_indicators', []))

                if combined_case_numbers:
                    print(f"  🔢 Case Numbers Found: {', '.join(sorted(combined_case_numbers)[:10])}{'...' if len(combined_case_numbers) > 10 else ''}")
                if combined_petitioners:
                    print(f"  👥 Petitioners/Applicants: {', '.join(sorted(combined_petitioners)[:5])}{'...' if len(combined_petitioners) > 5 else ''}")
                if combined_respondents:
                    print(f"  👥 Respondents: {', '.join(sorted(combined_respondents)[:5])}{'...' if len(combined_respondents) > 5 else ''}")
                if combined_advocates:
                    print(f"  👨‍⚖️ Advocates/Counsel: {', '.join(sorted(combined_advocates)[:5])}{'...' if len(combined_advocates) > 5 else ''}")
                if combined_status_indicators:
                    print(f"  📊 Status Indicators: {', '.join(sorted(combined_status_indicators))}")
                if combined_hearing_dates:
                    print(f"  📅 Hearing Dates: {', '.join(sorted(combined_hearing_dates)[:5])}{'...' if len(combined_hearing_dates) > 5 else ''}")

        # Show date range
        dates_list = sorted(info['dates'])
        if len(dates_list) <= 3:
            dates_str = ', '.join([str(d.date()) for d in dates_list])
        else:
            dates_str = f"{dates_list[0].date()} to {dates_list[-1].date()} ({len(dates_list)} days)"
        print(f"  Date(s): {dates_str}")
        print()

    print("=== NEXT STEPS FOR CASE DETAILS ===")
    print("1. Use the 'Case List References' above to locate cause list documents on eCourts website")
    print("2. Open each cause list document to see:")
    print("   - Case numbers")
    print("   - Party names (Petitioner vs Respondent)")
    print("   - Advocate details")
    print("   - Sometimes hearing stage")
    print("3. Use case numbers with eCourts' 'Case Status' search to check:")
    print("   - Pending/Framed/Arguments/Hearing")
    print("   - Disposed/Judgment Pronounced")
    print("   - If judgment: Conviction/Acquittal/Sentencing details")
    print()
    print("💡 Tip: Focus on judges with multiple appearances or interesting cause list types")
    print("💡 Tip: Case list types like 'Daily Main' usually have substantive hearings")
    print("💡 Tip: 'Supplemental' lists often have additional or urgent matters")

if __name__ == "__main__":
    main()
"""
eCourts Judge Scraper
Extracts judge information from cause lists on the eCourts website
"""

import requests
import csv
from datetime import datetime, timedelta

# Base URL for the eCourts HC services
BASE_URL = "https://hcservices.ecourts.gov.in/ecourtindiaHC"

# Headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_cause_lists_for_court(state_code, district_code, court_code, date):
    """
    Fetch cause lists for a given court and date.
    Returns a list of dictionaries with cause list information.
    """
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
        print(f"  Number of records split by '^#': {len(records)}")
        if len(records) > 0:
            print(f"  First record: {records[0][:200]}")
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
        print(f"  Parsed {len(cause_lists)} cause lists from records")
        return cause_lists
    except Exception as e:
        print(f"Error fetching cause lists: {e}")
        return []

def main():
    """
    Main function to scrape judge information from eCourts cause lists
    """
    # Use a raw string for the Windows path to courts.csv
    # Update this path if your courts.csv is located elsewhere
    courts_csv_path = r'C:\Users\Shreesh\AppData\Local\Temp\ecourts-main\courts.csv'

    # Alternative: if you have courts.csv in the same directory as this script:
    # courts_csv_path = 'courts.csv'

    # Get user input for state code
    print("\n=== eCourts Judge Scraper ===")
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
                days_input = "2"  # Default to 2 days
            days_to_check = int(days_input)
            if days_to_check > 0:
                break
            else:
                print("Please enter a positive number")
        except ValueError:
            print("Please enter a valid number")

    # Try the specified number of days if today yields no cause lists
    found_date = None
    all_cause_lists = []
    for days_ago in range(0, days_to_check):
        date = datetime.today() - timedelta(days=days_ago)
        print(f"\nFetching cause lists for {date.date()}")
        cause_lists = get_cause_lists_for_court(state_code, district_code, court_code, date)
        if cause_lists:
            print(f"Found {len(cause_lists)} cause lists for {date.date()}")
            found_date = date
            all_cause_lists = cause_lists
            break
        else:
            print(f"No cause lists found for {date.date()}")
    else:
        print(f"No cause lists found in the last {days_to_check} days.")
        return
    
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
    
    print(f"\n=== Summary of Unique Judges for {found_date.date()} ===")
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

    print("Cause List Type Distribution:")
    for ctype, count in sorted(type_counts.items()):
        print(f"  {ctype}: {count}")
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
        # We can also show the date(s)
        dates_str = ', '.join([str(d) for d in sorted(info['dates'])])
        print(f"  Date(s): {dates_str}")
        print()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Analyze Supreme Court cases data to examine duration and conviction patterns.
This script analyzes downloaded/imported Supreme Court case data to:
1. Extract case duration (duration_days)
2. Identify likely criminal cases (which may result in conviction/acquittal)
3. Filter and rank cases based on duration and conviction likelihood
4. Output analysis results

Note: Actual conviction/acquittal outcomes are not available in the current dataset.
This script uses heuristics to identify criminal cases where conviction outcomes
would be relevant.
"""

import csv
import os
import sys
from datetime import datetime

def analyze_supreme_court_cases(csv_path=None, use_database=True):
    """
    Analyze Supreme Court cases data.

    Args:
        csv_path: Path to CSV file (if use_database=False)
        use_database: Whether to try fetching data from database first

    Returns:
        List of case dictionaries with analysis fields
    """
    cases = []

    # Try to get data from database first
    if use_database:
        try:
            import data_service
            conn = data_service.get_db_connection()
            if conn:
                print("Fetching data from PostgreSQL database...")
                cur = conn.cursor()
                # Get all supreme court cases with relevant fields
                cur.execute("""
                    SELECT id, judge_name, title, status, duration_days,
                           judgment_date, year, case_id
                    FROM supreme_court_cases
                    WHERE duration_days IS NOT NULL
                    ORDER BY duration_days DESC
                """)
                rows = cur.fetchall()

                # Get column names
                colnames = [desc[0] for desc in cur.description]

                for row in rows:
                    case = dict(zip(colnames, row))
                    cases.append(case)

                cur.close()
                conn.close()
                print(f"Loaded {len(cases)} cases from database")
                return cases
            else:
                print("Database connection failed, falling back to CSV")
        except Exception as e:
            print(f"Error accessing database: {e}")
            print("Falling back to CSV")

    # Fallback to CSV
    if csv_path is None:
        csv_path = "supreme_court_all_judges.csv"

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return []

    print(f"Loading data from CSV: {csv_path}")
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert duration_days to int if possible
                try:
                    row['duration_days'] = int(row['duration_days']) if row['duration_days'].strip() else 0
                except (ValueError, KeyError):
                    row['duration_days'] = 0
                cases.append(row)
        print(f"Loaded {len(cases)} cases from CSV")
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return []

    return cases

def analyze_case_characteristics(cases):
    """
    Add analysis fields to each case.

    Args:
        cases: List of case dictionaries

    Returns:
        List of case dictionaries with added analysis fields
    """
    # Keywords that suggest criminal cases (where conviction/acquittal is relevant)
    criminal_indicators = ['STATE OF', 'CRIMINAL', 'CRL.', 'IPC ', 'CRPC ']
    # Keywords that suggest civil cases
    civil_indicators = ['VSB', 'VST', ' COMPANY', ' CORPORATION', ' BANK', ' AUTHORITY', ' W.', ' W.S.']

    for case in cases:
        title = case.get('title', '').upper()

        # Determine if likely criminal case
        is_likely_criminal = any(indicator in title for indicator in criminal_indicators)
        is_likely_civil = any(indicator in title for indicator in civil_indicators)

        case['is_likely_criminal'] = is_likely_criminal
        case['is_likely_civil'] = is_likely_civil
        case['case_type'] = 'CRIMINAL' if is_likely_criminal else ('CIVIL' if is_likely_civil else 'OTHER')

        # Duration analysis
        duration = case.get('duration_days', 0)
        case['duration_years'] = duration / 365.25 if duration > 0 else 0

        # Status analysis
        status = case.get('status', '').upper()
        case['is_completed'] = status == 'COMPLETED'
        case['is_pending'] = status in ['PENDING', 'HEARING', 'RESERVED']  # Common pending statuses

        # For ranking: criminal cases with long duration might be of particular interest
        case['priority_score'] = 0
        if case['is_likely_criminal'] and case['is_completed']:
            # Higher score for longer-running criminal cases that completed
            case['priority_score'] = case.get('duration_days', 0)
        elif case['is_likely_criminal'] and case['is_pending']:
            # Even higher score for pending criminal cases (justice delayed)
            case['priority_score'] = case.get('duration_days', 0) * 2

    return cases

def rank_and_filter_cases(cases, top_n=20, min_duration_days=0, case_type_filter=None):
    """
    Rank and filter cases based on analysis criteria.

    Args:
        cases: List of analyzed case dictionaries
        top_n: Number of top cases to return
        min_duration_days: Minimum duration in days to include
        case_type_filter: Filter by 'CRIMINAL', 'CIVIL', or None for all

    Returns:
        List of filtered and ranked case dictionaries
    """
    # Filter by minimum duration
    filtered = [case for case in cases if case.get('duration_days', 0) >= min_duration_days]

    # Filter by case type if specified
    if case_type_filter:
        filtered = [case for case in filtered if case.get('case_type') == case_type_filter]

    # Sort by priority score (descending), then by duration (descending)
    ranked = sorted(filtered,
                   key=lambda x: (x.get('priority_score', 0), x.get('duration_days', 0)),
                   reverse=True)

    return ranked[:top_n]

def print_analysis_summary(cases):
    """Print summary statistics of the analyzed cases."""
    if not cases:
        print("No cases to analyze")
        return

    total = len(cases)
    completed = sum(1 for c in cases if c.get('is_completed'))
    pending = sum(1 for c in cases if c.get('is_pending'))
    criminal = sum(1 for c in cases if c.get('is_likely_criminal'))
    civil = sum(1 for c in cases if c.get('is_likely_civil'))

    durations = [c.get('duration_days', 0) for c in cases if c.get('duration_days', 0) > 0]
    avg_duration = sum(durations) / len(durations) if durations else 0
    max_duration = max(durations) if durations else 0
    min_duration = min(durations) if durations else 0

    print("\n" + "="*60)
    print("SUPREME COURT CASES DURATION ANALYSIS")
    print("="*60)
    print(f"Total cases analyzed: {total}")
    print(f"Completed cases: {completed} ({completed/total*100:.1f}%)")
    print(f"Pending cases: {pending} ({pending/total*100:.1f}%)")
    print(f"Likely criminal cases: {criminal} ({criminal/total*100:.1f}%)")
    print(f"Likely civil cases: {civil} ({civil/total*100:.1f}%)")
    print(f"Average duration: {avg_duration:.1f} days ({avg_duration/365.25:.2f} years)")
    print(f"Median duration: {sorted(durations)[len(durations)//2] if durations else 0:.1f} days")
    print(f"Max duration: {max_duration} days ({max_duration/365.25:.2f} years)")
    print(f"Min duration: {min_duration} days")
    print("="*60)

def print_top_cases(cases, title="Top Cases"):
    """Print top cases in a formatted table."""
    if not cases:
        print(f"No cases to display for {title}")
        return

    print(f"\n{title}")
    print("-" * 100)
    print(f"{'Rank':<4} {'Case ID':<20} {'Title':<30} {'Type':<8} {'Status':<12} {'Duration (days)':<15} {'Years':<8} {'Priority':<10}")
    print("-" * 100)

    for i, case in enumerate(cases, 1):
        case_id = case.get('case_id', 'N/A')[:19]
        title = case.get('title', 'N/A')[:29]
        case_type = case.get('case_type', 'N/A')[:7]
        status = case.get('status', 'N/A')[:11]
        duration = case.get('duration_days', 0)
        years = f"{case.get('duration_years', 0):.1f}"
        priority = case.get('priority_score', 0)

        print(f"{i:<4} {case_id:<20} {title:<30} {case_type:<8} {status:<12} {duration:<15} {years:<8} {priority:<10}")

    print("-" * 100)

def save_analysis_to_file(cases, filename="case_analysis_results.txt"):
    """Save analysis results to a text file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("SUPREME COURT CASES DURATION AND CONVICTION ANALYSIS\n")
            f.write("="*60 + "\n")
            f.write(f"Analysis generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total cases analyzed: {len(cases)}\n\n")

            # Summary statistics
            total = len(cases)
            completed = sum(1 for c in cases if c.get('is_completed'))
            pending = sum(1 for c in cases if c.get('is_pending'))
            criminal = sum(1 for c in cases if c.get('is_likely_criminal'))
            civil = sum(1 for c in cases if c.get('is_likely_civil'))

            durations = [c.get('duration_days', 0) for c in cases if c.get('duration_days', 0) > 0]
            avg_duration = sum(durations) / len(durations) if durations else 0

            f.write("SUMMARY STATISTICS:\n")
            f.write(f"  Total cases: {total}\n")
            f.write(f"  Completed cases: {completed} ({completed/total*100:.1f}%)\n")
            f.write(f"  Pending cases: {pending} ({pending/total*100:.1f}%)\n")
            f.write(f"  Likely criminal cases: {criminal} ({criminal/total*100:.1f}%)\n")
            f.write(f"  Likely civil cases: {civil} ({civil/total*100:.1f}%)\n")
            f.write(f"  Average duration: {avg_duration:.1f} days ({avg_duration/365.25:.2f} years)\n\n")

            # Top criminal cases by duration
            top_criminal = [c for c in cases if c.get('is_likely_criminal')]
            top_criminal = sorted(top_criminal, key=lambda x: x.get('duration_days', 0), reverse=True)[:10]

            f.write("TOP 10 LONGEST-RUNNING LIKELY CRIMINAL CASES:\n")
            f.write("-" * 80 + "\n")
            for i, case in enumerate(top_criminal, 1):
                f.write(f"{i:2d}. {case.get('case_id', 'N/A'):<20} {case.get('title', 'N/A'):<40} ")
                f.write(f"{case.get('duration_days', 0):<6} days ({case.get('duration_years', 0):.1f} years)\n")
            f.write("\n")

            # Top civil cases by duration
            top_civil = [c for c in cases if c.get('is_likely_civil')]
            top_civil = sorted(top_civil, key=lambda x: x.get('duration_days', 0), reverse=True)[:10]

            f.write("TOP 10 LONGEST-RUNNING LIKELY CIVIL CASES:\n")
            f.write("-" * 80 + "\n")
            for i, case in enumerate(top_civil, 1):
                f.write(f"{i:2d}. {case.get('case_id', 'N/A'):<20} {case.get('title', 'N/A'):<40} ")
                f.write(f"{case.get('duration_days', 0):<6} days ({case.get('duration_years', 0):.1f} years)\n")
            f.write("\n")

            # Cases with highest priority scores (long-running criminal cases)
            top_priority = sorted(cases, key=lambda x: x.get('priority_score', 0), reverse=True)[:10]

            f.write("TOP 10 CASES BY PRIORITY SCORE (Criminal cases weighted by duration):\n")
            f.write("-" * 80 + "\n")
            for i, case in enumerate(top_priority, 1):
                f.write(f"{i:2d}. {case.get('case_id', 'N/A'):<20} {case.get('title', 'N/A'):<40} ")
                f.write(f"Score: {case.get('priority_score', 0):<8} ")
                f.write(f"({case.get('duration_days', 0)} days, {case.get('case_type', 'N/A')})\n")

        print(f"Analysis results saved to: {filename}")
        return True
    except Exception as e:
        print(f"Error saving analysis to file: {e}")
        return False

def main():
    """Main analysis function."""
    print("Supreme Court Case Duration and Conviction Analysis")
    print("=" * 55)

    # Load the data
    cases = analyze_supreme_court_cases()

    if not cases:
        print("No case data available for analysis.")
        return 1

    # Add analysis fields
    cases = analyze_case_characteristics(cases)

    # Print overall summary
    print_analysis_summary(cases)

    # Show top cases by different criteria
    print_top_cases(cases, "TOP 10 CASES BY DURATION (ALL TYPES)")

    # Show top criminal cases
    criminal_cases = [c for c in cases if c.get('is_likely_criminal')]
    if criminal_cases:
        print_top_cases(criminal_cases[:10], "TOP 10 LIKELY CRIMINAL CASES BY DURATION")

    # Show top civil cases
    civil_cases = [c for c in cases if c.get('is_likely_civil')]
    if civil_cases:
        print_top_cases(civil_cases[:10], "TOP 10 LIKELY CIVIL CASES BY DURATION")

    # Show cases with highest priority scores
    priority_cases = [c for c in cases if c.get('priority_score', 0) > 0]
    if priority_cases:
        print_top_cases(priority_cases[:10], "TOP 10 CASES BY PRIORITY SCORE")

    # Show pending cases (if any exist)
    pending_cases = [c for c in cases if c.get('is_pending')]
    if pending_cases:
        print_top_cases(pending_cases, "PENDING CASES")
    else:
        print("\nNo pending cases found in current dataset.")

    # Save detailed analysis to file
    save_analysis_to_file(cases)

    print("\nAnalysis complete!")
    print("Results have been saved to 'case_analysis_results.txt'")
    print("\nNote: Actual conviction/acquittal outcomes are not available in this dataset.")
    print("This analysis identifies likely criminal cases where such outcomes would be relevant.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""
Final PDF Analyzer for eCourts Causelists
Analyzes downloaded PDFs and shows available information in output window.
"""

import os
import PyPDF2
import re
from datetime import datetime
import sys

def analyze_pdfs(pdf_directory):
    """Analyze all PDFs in the directory and return results."""
    print("Analyzing eCourts Causelist PDFs...")
    print("=" * 50)

    # Statistics
    total_files = 0
    processed_files = 0
    error_files = 0
    total_cases = 0

    # Sets for unique values
    judges = set()
    courts = set()
    dates = set()

    # Walk through directory
    for root, _, files in os.walk(pdf_directory):
        pdf_files = [f for f in files if f.lower().endswith('.pdf')]
        total_files += len(pdf_files)

        for filename in pdf_files:
            file_path = os.path.join(root, filename)

            # Extract text (first page only for efficiency)
            try:
                with open(file_path, 'rb') as f:
                    pdf = PyPDF2.PdfReader(f)
                    if len(pdf.pages) > 0:
                        text = pdf.pages[0].extract_text()
                    else:
                        text = ""
            except Exception:
                error_files += 1
                continue

            # Parse information
            info = parse_causelist_info(text, filename)

            # Update statistics
            processed_files += 1
            total_cases += info['case_count']

            if info['date'] != 'Not found':
                dates.add(info['date'])
            if info['judge'] != 'Not found':
                judges.add(info['judge'])
            if info['court'] != 'Not found':
                courts.add(info['court'])

            # Show progress every 100 files
            if processed_files % 100 == 0:
                print(f"Processed {processed_files}/{total_files} files...")

    # Print results
    print("\n" + "=" * 50)
    print("ANALYSIS COMPLETE")
    print("=" * 50)
    print(f"Total PDF files found: {total_files}")
    print(f"Successfully processed: {processed_files}")
    print(f"Errors encountered: {error_files}")
    print(f"Total cases listed: {total_cases}")
    if processed_files > 0:
        print(f"Average cases per PDF: {total_cases/processed_files:.1f}")

    print(f"\nUnique values found:")
    print(f"  • Different dates: {len(dates)}")
    print(f"  • Unique judges: {len(judges)}")
    print(f"  • Unique courts: {len(courts)}")

    if judges:
        print(f"\nJudges encountered:")
        for judge in sorted(list(judges))[:10]:  # Show first 10
            print(f"  - {judge}")
        if len(judges) > 10:
            print(f"  - ... and {len(judges) - 10} more")

    if courts:
        print(f"\nCourts encountered:")
        for court in sorted(list(courts))[:10]:  # Show first 10
            print(f"  - {court}")
        if len(courts) > 10:
            print(f"  - ... and {len(courts) - 10} more")

    if dates:
        print(f"\nDate range:")
        sorted_dates = sorted(list(dates))
        print(f"  • From: {sorted_dates[0]}")
        print(f"  • To: {sorted_dates[-1]}")
        print(f"  • Total: {len(sorted_dates)} different dates")

    # Important: Inform user what information is NOT available
    print("\n" + "=" * 50)
    print("INFORMATION AVAILABLE IN THESE PDFS:")
    print("  + Date of causelist (from filename)")
    print("  + Judge name(s)")
    print("  + Court name")
    print("  + Case numbers and basic case information")
    print("  + Total number of cases listed for hearing")

    print("\nINFORMATION NOT AVAILABLE IN CAUSELIST PDFS:")
    print("  - Number of days case went")
    print("  - Whether case is over or not")
    print("  - CNR (Case Number Registry) number")
    print("  - Convicted or acquitted status")
    print("")
    print("NOTE: These items require JUDGMENT/ORDER PDFs,")
    print("      not causelist (scheduling) PDFs.")
    print("      The downloaded PDFs appear to be causelists.")

    print("\n" + "=" * 50)
    print("Analysis finished. Results shown above.")
    print("=" * 50)

def parse_causelist_info(text, filename):
    """Parse information from causelist PDF text."""
    info = {
        'filename': filename,
        'date': 'Not found',
        'judge': 'Not found',
        'court': 'Not found',
        'case_count': 0
    }

    # Extract date from filename (YYYYMMDD_*.pdf)
    date_match = re.match(r'(\d{8})_', os.path.basename(filename))
    if date_match:
        try:
            date_obj = datetime.strptime(date_match.group(1), '%Y%m%d')
            info['date'] = date_obj.strftime('%Y-%m-%d')
        except:
            info['date'] = date_match.group(1)

    # Extract judge name
    judge_patterns = [
        r'HON\'?BLE\s+(?:THE\s+)?CHIEF\s+JUSTICE[^\n\r]*',
        r'HON\'?BLE\s+JUSTICE\s+[A-Z\s\.\-]+',
        r'BEFORE\s*:?\s*[^\n\r]*JUSTICE[^\n\r]*'
    ]
    for pattern in judge_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['judge'] = re.sub(r'\s+', ' ', match.group(0).strip())
            # Clean up brackets
            info['judge'] = info['judge'].replace(']', '').replace('[', '')
            break

    # Extract court name
    court_patterns = [
        r'HIGH\s+COURT\s+OF\s+[A-Z\s\-]+',
        r'[A-Z\s\-]+\s+HIGH\s+COURT',
        r'GAUHATI\s+HIGH\s+COURT'
    ]
    for pattern in court_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['court'] = re.sub(r'\s+', ' ', match.group(0).strip())
            break

    # Count cases by looking for case number patterns
    case_pattern = r'^\s*\d+\s+[A-Z]{2,}\/[A-Z0-9\/]+'
    lines = text.split('\n')
    info['case_count'] = sum(1 for line in lines if re.match(case_pattern, line.strip()))

    return info

def main():
    """Main function."""
    pdf_dir = r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\downloaded_pdfs"

    if not os.path.exists(pdf_dir):
        print(f"Error: Directory not found: {pdf_dir}")
        print("Please verify the path to the downloaded_pdfs directory.")
        return 1

    try:
        analyze_pdfs(pdf_dir)
        return 0
    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user.")
        return 1
    except Exception:
        print(f"Unexpected error occurred during analysis.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
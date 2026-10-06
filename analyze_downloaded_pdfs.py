#!/usr/bin/env python3
"""
Analyze downloaded PDFs from eCourts scraper and extract available information.
This script processes causelist PDFs to show what information is available:
- Date (from filename)
- Judge name
- Court name
- Bench/session timing
- Case count and basic case details

Note: Information like "number of days case went", "case over status",
"CNR no", and "convicted or acquitted" is NOT available in causelist PDFs,
as these are scheduling documents, not judgments/orders.
"""

import os
import PyPDF2
import re
from datetime import datetime
import time
import sys

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file."""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            # Limit to first 2 pages for performance since causelists are usually short
            max_pages = min(2, len(pdf_reader.pages))
            for page_num in range(max_pages):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n"
            return text
    except Exception as e:
        return f"Error reading PDF: {e}"

def parse_causelist_info(text, filename):
    """Parse information from causelist PDF text."""
    info = {
        'filename': os.path.basename(filename),
        'judge_name': 'Not found',
        'court_name': 'Not found',
        'date': 'Not found',
        'bench_info': 'Not found',
        'case_count': 0,
        'cases': [],  # Will store simplified case info
        # Fields that are NOT available in causelists:
        'days_case_went': 'Not available in causelist',
        'case_over_status': 'Not available in causelist',
        'cnr_no': 'Not available in causelist',
        'convicted_acquitted': 'Not available in causelist'
    }

    # Extract date from filename (format: YYYYMMDD_*.pdf)
    date_match = re.match(r'(\d{8})_', os.path.basename(filename))
    if date_match:
        date_str = date_match.group(1)
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            info['date'] = date_obj.strftime('%Y-%m-%d (%A)')
        except:
            info['date'] = date_str

    # Extract judge name - improved patterns
    judge_patterns = [
        r'HON\'?BLE\s+(?:THE\s+)?CHIEF\s+JUSTICE[^\n\r]*',
        r'HON\'?BLE\s+JUSTICE\s+[A-Z\s\.\-]+',
        r'BEFORE\s*:?\s*[^\n\r]*JUSTICE[^\n\r]*',
        r'HON\'?BLE\s+[A-Z\s\.\-]+(?:JUSTICE|THE\s+CHIEF\s+JUSTICE)'
    ]

    for pattern in judge_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            judge_text = match.group(0).strip()
            # Clean up extra characters
            judge_text = re.sub(r'[\]\[]', '', judge_text)
            judge_text = re.sub(r'\s+', ' ', judge_text)
            info['judge_name'] = judge_text
            break

    # Extract court name - improved patterns
    court_patterns = [
        r'HIGH\s+COURT\s+OF\s+[A-Z\s\-]+',
        r'[A-Z\s\-]+\s+HIGH\s+COURT[^\n\r]*',
        r'THE\s+[A-Z\s\-]+\s+HIGH\s+COURT',
        r'GAUHATI\s+HIGH\s+COURT',
        r'HIGH\s+COURT\s+[A-Z\s\-]+'
    ]

    for pattern in court_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            court_text = match.group(0).strip()
            court_text = re.sub(r'\s+', ' ', court_text)
            info['court_name'] = court_text
            break

    # Extract bench/session information
    bench_patterns = [
        r'COURT\s+NO\s*\.\s*\d+',
        r'SECTION\s*[-]?\s*\d+',
        r'SINGLE\s+BENCH\s*\([^)]+\)',
        r'DIVISION\s+BENCH\s*\([^)]+\)',
        r'AT\s+\d+:\d+\s*(?:AM|PM)',
        r'FROM\s+\d{1,2}[A-Z]{2}\s+\w+\s+\d{4}'
    ]

    bench_info = []
    for pattern in bench_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        bench_info.extend(matches)

    if bench_info:
        info['bench_info'] = ' | '.join(bench_info[:3])  # Limit to first 3 matches

    # Count cases by looking for case number patterns
    # Look for lines that start with numbers followed by case numbers
    case_patterns = [
        r'^\s*\d+\s+[A-Z]{2,}\/[A-Z0-9\/]+\s+',  # WP(C)/123/2024 format
        r'^\s*\d+\s+[A-Z]+\/\d+\/\d+\s+',         # WPO/123/2024 format
        r'^\s*\d+\s+[A-Z]{2,}\d+\/\d+\/\d+\s+'    # WP123/2024 format
    ]

    case_count = 0
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if line starts with a case entry
        for pattern in case_patterns:
            if re.match(pattern, line):
                case_count += 1
                # Try to extract basic case info
                parts = line.split(None, 2)  # Split into max 3 parts
                if len(parts) >= 3:
                    sl_no = parts[0]
                    case_no = parts[1]
                    case_title = parts[2][:50] + ('...' if len(parts[2]) > 50 else '')
                    info['cases'].append({
                        'sl_no': sl_no,
                        'case_no': case_no,
                        'title': case_title
                    })
                break

    info['case_count'] = case_count

    return info

def analyze_pdfs_directory(root_dir, show_details=False):
    """Walk through downloaded_pdfs directory and analyze PDFs."""
    results = []
    files_processed = 0
    errors = 0

    print("Scanning for PDF files...")

    # First, count total PDFs
    total_pdfs = 0
    for root, dirs, files in os.walk(root_dir):
        total_pdfs += len([f for f in files if f.lower().endswith('.pdf')])

    print(f"Found {total_pdfs} PDF files to analyze\n")

    # Now process them
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_path = os.path.join(root, file)

                # Show progress
                if files_processed % 50 == 0 and files_processed > 0:
                    print(f"Progress: {files_processed}/{total_pdfs} files processed...")

                # Extract text and parse
                text = extract_text_from_pdf(pdf_path)
                if text.startswith("Error"):
                    errors += 1
                    if errors <= 5:  # Only show first few errors
                        print(f"Error processing {file}: {text}")
                else:
                    info = parse_causelist_info(text, pdf_path)
                    results.append(info)

                    # Show detailed info for first few files if requested
                    if show_details and files_processed < 5:
                        print_detailed_info(info)

                files_processed += 1

    return results, errors

def print_detailed_info(info):
    """Print detailed information for a single PDF."""
    print(f"\n{'='*60}")
    print(f"ANALYZING: {info['filename']}")
    print('='*60)
    print(f"DATE: {info['date']}")
    print(f"JUDGE: {info['judge_name']}")
    print(f"COURT: {info['court_name']}")
    if info['bench_info'] != 'Not found':
        print(f"BENCH/SESSION: {info['bench_info']}")
    print(f"NUMBER OF CASES LISTED: {info['case_count']}")

    if info['case_count'] > 0:
        print(f"\nFIRST 10 CASES:")
        print(f"{'SL':<4} {'CASE NUMBER':<20} {'CASE TITLE':<40}")
        print("-" * 65)
        for case in info['cases'][:10]:
            print(f"{case['sl_no']:<4} {case['case_no']:<20} {case['title']:<40}")
        if len(info['cases']) > 10:
            print(f"    ... and {len(info['cases']) - 10} more cases")
    else:
        print("\nNO CASES LISTED IN THIS CAUSELIST")
    print()

def print_summary(results, errors):
    """Print a summary of all analyzed PDFs."""
    print("\n" + "="*70)
    print("FINAL ANALYSIS SUMMARY")
    print("="*70)

    total_pdfs = len(results)
    total_cases = sum(r['case_count'] for r in results)

    print(f"Total PDFs successfully analyzed: {total_pdfs}")
    print(f"Total PDFs with errors: {errors}")
    print(f"Total cases found across all PDFs: {total_cases}")

    if total_pdfs > 0:
        print(f"Average cases per PDF: {total_cases/total_pdfs:.1f}")
        print(f"PDFs with cases: {len([r for r in results if r['case_count'] > 0])}")
        print(f"PDFs without cases: {len([r for r in results if r['case_count'] == 0])}")

    # Unique judges and courts
    judges = set(r['judge_name'] for r in results if r['judge_name'] != 'Not found')
    courts = set(r['court_name'] for r in results if r['court_name'] != 'Not found')
    dates = set(r['date'] for r in results if r['date'] != 'Not found')

    print(f"\nUNIQUE VALUES FOUND:")
    print(f"  • Judges: {len(judges)}")
    print(f"  • Courts: {len(courts)}")
    print(f"  • Different dates: {len(dates)}")

    # Show what information IS available vs NOT available
    print(f"\nINFORMATION AVAILABLE FROM THESE CAUSELIST PDFS:")
    print(f"  ✓ Date of causelist")
    print(f"  ✓ Judge name")
    print(f"  ✓ Court name")
    print(f"  ✓ Bench/session timing")
    print(f"  ✓ Case numbers and basic case titles")
    print(f"  ✓ Total number of cases listed")

    print(f"\nINFORMATION NOT AVAILABLE IN CAUSELIST PDFS:")
    print(f"  ✗ Number of days case went")
    print(f"  ✗ Whether case is over or not")
    print(f"  ✗ CNR (Case Number Registry) number")
    print(f"  ✗ Convicted or acquitted status")
    print(f"  ✓ Note: This information would be found in JUDGMENT/ORDER PDFs, not causelists")

    # Show top judges and courts
    if judges:
        sorted_judges = sorted(list(judges))
        print(f"\nTOP JUDGES (by frequency):")
        # Count judge frequencies
        judge_counts = {}
        for r in results:
            judge = r['judge_name']
            if judge != 'Not found':
                judge_counts[judge] = judge_counts.get(judge, 0) + 1

        sorted_by_count = sorted(judge_counts.items(), key=lambda x: x[1], reverse=True)
        for judge, count in sorted_by_count[:5]:
            print(f"  • {judge}: {count} causelists")

    if courts:
        sorted_courts = sorted(list(courts))
        print(f"\nCOURTS FOUND:")
        for court in sorted_courts:
            count = len([r for r in results if r['court_name'] == court])
            print(f"  • {court}: {count} causelists")

def main():
    """Main function to run the PDF analysis."""
    downloaded_pdfs_dir = r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\downloaded_pdfs"

    if not os.path.exists(downloaded_pdfs_dir):
        print(f"Error: Directory not found: {downloaded_pdfs_dir}")
        print("Please check the path and try again.")
        return 1

    print("Starting analysis of downloaded eCourts PDFs...")
    print("="*50)

    start_time = time.time()

    # Analyze all PDFs
    results, errors = analyze_pdfs_directory(downloaded_pdfs_dir, show_details=True)

    end_time = time.time()

    print(f"\nAnalysis completed in {end_time - start_time:.2f} seconds")

    if results or errors > 0:
        print_summary(results, errors)
        return 0
    else:
        print("No PDFs were found or processed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
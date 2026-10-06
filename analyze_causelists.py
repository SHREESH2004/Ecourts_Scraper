#!/usr/bin/env python3
"""
Analyze downloaded causelist PDFs from eCourts scraper and extract available information.
Focuses on showing judge, court, date, and case details in a clean format.
"""

import os
import PyPDF2
import re
from datetime import datetime
import time

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
        'cases': []  # Will store simplified case info
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

def analyze_pdfs_directory(root_dir, max_files=None):
    """Walk through downloaded_pdfs directory and analyze PDFs."""
    results = []
    files_processed = 0

    for root, dirs, files in os.walk(root_dir):
        pdf_files = [f for f in files if f.lower().endswith('.pdf')]

        for file in pdf_files:
            if max_files and files_processed >= max_files:
                break

            pdf_path = os.path.join(root, file)

            # Extract text and parse
            text = extract_text_from_pdf(pdf_path)
            if not text.startswith("Error"):
                info = parse_causelist_info(text, pdf_path)
                results.append(info)
                files_processed += 1

                # Print progress every 50 files
                if files_processed % 50 == 0:
                    print(f"Processed {files_processed} files...")

    return results

def print_summary(results):
    """Print a summary of all analyzed PDFs."""
    print("\n" + "="*80)
    print("CAUSELIST ANALYSIS SUMMARY")
    print("="*80)

    total_pdfs = len(results)
    total_cases = sum(r['case_count'] for r in results)

    print(f"Total PDFs analyzed: {total_pdfs}")
    print(f"Total cases found: {total_cases}")
    print(f"Average cases per PDF: {total_cases/total_pdfs:.1f}" if total_pdfs > 0 else "N/A")

    # Unique judges and courts
    judges = set(r['judge_name'] for r in results if r['judge_name'] != 'Not found')
    courts = set(r['court_name'] for r in results if r['court_name'] != 'Not found')
    dates = set(r['date'] for r in results if r['date'] != 'Not found')

    print(f"\nUnique judges: {len(judges)}")
    print(f"Unique courts: {len(courts)}")
    print(f"Date range covered: {len(dates)} different dates")

    if judges:
        sorted_judges = sorted(list(judges))
        print(f"\nJudges ({len(sorted_judges)}):")
        for i, judge in enumerate(sorted_judges[:10]):  # Show first 10
            print(f"  {i+1}. {judge}")
        if len(sorted_judges) > 10:
            print(f"  ... and {len(sorted_judges) - 10} more")

    if courts:
        sorted_courts = sorted(list(courts))
        print(f"\nCourts ({len(sorted_courts)}):")
        for i, court in enumerate(sorted_courts[:10]):  # Show first 10
            print(f"  {i+1}. {court}")
        if len(sorted_courts) > 10:
            print(f"  ... and {len(sorted_courts) - 10} more")

    # Show sample of detailed info from first few PDFs
    print(f"\n" + "-"*80)
    print("SAMPLE DETAILED INFO (First 5 PDFs)")
    print("-"*80)

    for i, info in enumerate(results[:5]):
        print(f"\n{i+1}. {info['filename']}")
        print(f"   Date: {info['date']}")
        print(f"   Judge: {info['judge_name']}")
        print(f"   Court: {info['court_name']}")
        if info['bench_info'] != 'Not found':
            print(f"   Bench/Session: {info['bench_info']}")
        print(f"   Cases: {info['case_count']}")
        if info['cases']:
            print("   Sample cases:")
            for case in info['cases'][:3]:  # Show first 3 cases
                print(f"     {case['sl_no']}. {case['case_no']} - {case['title']}")

def main():
    """Main function to run the causelist analysis."""
    downloaded_pdfs_dir = r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\downloaded_pdfs"

    if not os.path.exists(downloaded_pdfs_dir):
        print(f"Directory not found: {downloaded_pdfs_dir}")
        return

    print("Starting causelist PDF analysis...")
    print("="*50)

    start_time = time.time()

    # Analyze all PDFs (remove max_files=None to process all, or set a number for testing)
    results = analyze_pdfs_directory(downloaded_pdfs_dir, max_files=None)

    end_time = time.time()

    print(f"\nAnalysis completed in {end_time - start_time:.2f} seconds")

    if results:
        print_summary(results)
    else:
        print("No PDFs were successfully analyzed.")

if __name__ == "__main__":
    main()
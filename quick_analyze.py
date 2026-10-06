#!/usr/bin/env python3
"""
Quick analysis of downloaded PDFs - shows what information is available.
Processes a sample first for quick feedback, then can process all if needed.
"""

import os
import PyPDF2
import re
from datetime import datetime
import sys

def extract_text_fast(pdf_path):
    """Fast text extraction - first page only for causelists."""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            if len(pdf_reader.pages) > 0:
                # Only read first page - causelists usually have info on first page
                page = pdf_reader.pages[0]
                return page.extract_text()
            return ""
    except Exception as e:
        return f"Error: {e}"

def parse_info(text, filename):
    """Parse available information from causelist text."""
    info = {
        'file': os.path.basename(filename),
        'date': 'Not found',
        'judge': 'Not found',
        'court': 'Not found',
        'cases': 0
    }

    # Extract date from filename
    date_match = re.match(r'(\d{8})_', os.path.basename(filename))
    if date_match:
        try:
            date_obj = datetime.strptime(date_match.group(1), '%Y%m%d')
            info['date'] = date_obj.strftime('%Y-%m-%d')
        except:
            info['date'] = date_match.group(1)

    # Extract judge
    judge_patterns = [
        r'HON\'?BLE\s+(?:THE\s+)?CHIEF\s+JUSTICE[^\n\r]*',
        r'HON\'?BLE\s+JUSTICE\s+[A-Z\s\.\-]+',
        r'BEFORE\s*:?\s*[^\n\r]*JUSTICE[^\n\r]*'
    ]
    for pattern in judge_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['judge'] = re.sub(r'\s+', ' ', match.group(0).strip())
            break

    # Extract court
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

    # Count case numbers
    case_pattern = r'^\s*\d+\s+[A-Z]{2,}\/[A-Z0-9\/]+'
    lines = text.split('\n')
    info['cases'] = sum(1 for line in lines if re.match(case_pattern, line.strip()))

    return info

def analyze_sample(root_dir, sample_size=20):
    """Analyze a sample of PDFs for quick feedback."""
    print(f"Analyzing sample of {sample_size} PDFs from {root_dir}")
    print("-" * 60)

    # Collect PDF files
    pdf_files = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))

    # Take sample
    sample = pdf_files[:sample_size] if len(pdf_files) >= sample_size else pdf_files

    results = []
    for i, pdf_path in enumerate(sample, 1):
        text = extract_text_fast(pdf_path)
        if not text.startswith("Error"):
            info = parse_info(text, pdf_path)
            results.append(info)

            # Show every 5th file to avoid too much output
            if i % 5 == 0 or i <= 5:
                print(f"{i:2d}. {info['file']:<25} | {info['date']} | {info['judge']:<25} | {info['court']:<20} | {info['cases']:2d} cases")
        else:
            print(f"{i:2d}. ERROR: {os.path.basename(pdf_path)}")

    # Summary
    print("-" * 60)
    if results:
        total_cases = sum(r['cases'] for r in results)
        judges = set(r['judge'] for r in results if r['judge'] != 'Not found')
        courts = set(r['court'] for r in results if r['court'] != 'Not found')
        dates = set(r['date'] for r in results if r['date'] != 'Not found')

        print(f"Sample Results ({len(results)} PDFs):")
        print(f"  Total cases found: {total_cases}")
        print(f"  Average cases per PDF: {total_cases/len(results):.1f}")
        print(f"  Unique judges: {len(judges)}")
        print(f"  Unique courts: {len(courts)}")
        print(f"  Date range: {len(dates)} different dates")

        print(f"\nInformation Available:")
        print(f"  + Date, Judge, Court, Case count")
        print(f"  - Days case went, Case status, CNR, Convicted/Acquitted")
        print(f"  -> These require judgment PDFs, not causelists")

    return results

def main():
    """Main function."""
    pdf_dir = r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\downloaded_pdfs"

    if not os.path.exists(pdf_dir):
        print(f"Error: Directory not found: {pdf_dir}")
        return 1

    print("Quick Analysis of eCourts Causelist PDFs")
    print("=" * 50)

    # Analyze sample first
    results = analyze_sample(pdf_dir, sample_size=30)

    print(f"\nTo analyze ALL PDFs, modify the script or run:")
    print(f"  The full analysis would process ~1,559 PDFs")
    print(f"  Estimated time: 2-5 minutes depending on system")

    return 0

if __name__ == "__main__":
    sys.exit(main())
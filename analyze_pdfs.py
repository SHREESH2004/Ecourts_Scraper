#!/usr/bin/env python3
"""
Analyze downloaded PDFs from eCourts scraper and extract available information.
Focuses on causelist PDFs to show judge, court, date, and case details.
"""

import os
import PyPDF2
import re
from datetime import datetime

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file."""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
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
        'cases': []
    }

    # Extract date from filename (format: YYYYMMDD_*.pdf)
    date_match = re.match(r'(\d{8})_', os.path.basename(filename))
    if date_match:
        date_str = date_match.group(1)
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            info['date'] = date_obj.strftime('%Y-%m-%d')
        except:
            info['date'] = date_str

    # Extract judge name
    judge_patterns = [
        r'HON\'?BLE\s+JUSTICE\s+[A-Z\s\.\-]+',
        r'HON\'?BLE\s+THE\s+CHIEF\s+JUSTICE[^\n]*',
        r'BEFORE:\s*[^\n]*JUSTICE[^\n]*',
        r'HON\'?BLE\s+[A-Z\s\.\-]+JUSTICE'
    ]

    for pattern in judge_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['judge_name'] = match.group(0).strip()
            break

    # Extract court name
    court_patterns = [
        r'HIGH\s+COURT\s+OF\s+[A-Z\s\-]+',
        r'[A-Z\s\-]+\s+HIGH\s+COURT',
        r'THE\s+[A-Z\s\-]+\s+HIGH\s+COURT'
    ]

    for pattern in court_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['court_name'] = match.group(0).strip()
            break

    # Extract case information (simplified)
    # Look for case numbers and parties
    lines = text.split('\n')
    in_case_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect start of case listing
        if re.match(r'^\d+\s+[A-Z0-9\/]+\s+', line) or 'WP(' in line or 'WPO(' in line or 'CR' in line:
            in_case_section = True
            # Try to extract case number and parties
            case_match = re.match(r'^(\d+)\s+([A-Z0-9\/\(\)\.]+)\s+(.+)$', line)
            if case_match:
                sl_no = case_match.group(1)
                case_no = case_match.group(2)
                parties = case_match.group(3)

                # Try to split petitioner vs respondent
                if 'VS' in parties.upper():
                    parts = re.split(r'\s+VS\s+', parties, flags=re.IGNORECASE)
                    if len(parts) >= 2:
                        petitioner = parts[0].strip()
                        respondent = ' VS '.join(parts[1:]).strip()
                    else:
                        petitioner = parties
                        respondent = 'Not found'
                else:
                    petitioner = parties
                    respondent = 'Not found'

                info['cases'].append({
                    'sl_no': sl_no,
                    'case_no': case_no,
                    'petitioner': petitioner,
                    'respondent': respondent
                })
        elif in_case_section and line.startswith('----------------------------------------------------------------'):
            # End of case section
            break

    return info

def analyze_pdfs_directory(root_dir):
    """Walk through downloaded_pdfs directory and analyze each PDF."""
    results = []

    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_path = os.path.join(root, file)
                print(f"Analyzing: {pdf_path}")

                # Extract text
                text = extract_text_from_pdf(pdf_path)

                # Parse information
                info = parse_causelist_info(text, pdf_path)
                results.append(info)

                # Print results for this PDF
                print_pdf_info(info)
                print("-" * 80)

    return results

def print_pdf_info(info):
    """Print parsed PDF information in a readable format."""
    print(f"FILE: {info['filename']}")
    print(f"DATE: {info['date']}")
    print(f"JUDGE: {info['judge_name']}")
    print(f"COURT: {info['court_name']}")
    print(f"NUMBER OF CASES: {len(info['cases'])}")

    if info['cases']:
        print("\nCASE DETAILS:")
        print(f"{'SL':<4} {'CASE NO':<20} {'PETITIONER':<30} {'RESPONDENT':<30}")
        print("-" * 90)
        for case in info['cases'][:10]:  # Show first 10 cases
            petitioner = (case['petitioner'][:27] + '...') if len(case['petitioner']) > 30 else case['petitioner']
            respondent = (case['respondent'][:27] + '...') if len(case['respondent']) > 30 else case['respondent']
            print(f"{case['sl_no']:<4} {case['case_no']:<20} {petitioner:<30} {respondent:<30}")

        if len(info['cases']) > 10:
            print(f"... and {len(info['cases']) - 10} more cases")
    print()

def main():
    """Main function to run the PDF analysis."""
    downloaded_pdfs_dir = r"C:\Users\Shreesh\Downloads\scraper_codex - Copy\downloaded_pdfs"

    if not os.path.exists(downloaded_pdfs_dir):
        print(f"Directory not found: {downloaded_pdfs_dir}")
        return

    print("Starting PDF analysis...")
    print("=" * 80)

    results = analyze_pdfs_directory(downloaded_pdfs_dir)

    # Summary
    total_pdfs = len(results)
    total_cases = sum(len(r['cases']) for r in results)

    print("SUMMARY")
    print("=" * 80)
    print(f"Total PDFs analyzed: {total_pdfs}")
    print(f"Total cases found: {total_cases}")

    # Show unique judges and courts
    judges = set(r['judge_name'] for r in results if r['judge_name'] != 'Not found')
    courts = set(r['court_name'] for r in results if r['court_name'] != 'Not found')

    print(f"Unique judges: {len(judges)}")
    print(f"Unique courts: {len(courts)}")

    if judges:
        print(f"\nJudges found: {', '.join(sorted(list(judges)[:5]))}{'...' if len(judges) > 5 else ''}")
    if courts:
        print(f"Courts found: {', '.join(sorted(list(courts)[:5]))}{'...' if len(courts) > 5 else ''}")

if __name__ == "__main__":
    main()
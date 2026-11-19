"""
PDF Cause List Analyzer for eCourts Website
Downloads and analyzes PDF cause lists to extract case details
"""

import requests
import re
import sys
import io

def extract_text_from_pdf(pdf_content):
    """
    Extract text from PDF content using PyPDF2
    Returns extracted text or None if PyPDF2 is not available
    """
    try:
        import PyPDF2
        pdf_file = io.BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except ImportError:
        print("Error: PyPDF2 module not found. Please install it using:")
        print("pip install PyPDF2")
        return None
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None

def extract_case_information_from_text(text):
    """
    Extract case information from cause list document text
    Returns a dictionary with case numbers, parties, and other details
    """
    if not text:
        return {
            'case_numbers': [],
            'petitioners': [],
            'respondents': [],
            'advocates': [],
            'hearing_dates': [],
            'status_indicators': [],
            'raw_text_preview': ''
        }

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

def download_and_analyze_pdf(url):
    """
    Download PDF from URL and analyze it for case information
    """
    print(f"Downloading PDF from: {url}")

    try:
        # Add headers to mimic a browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Check if we got a PDF
        content_type = response.headers.get('content-type', '').lower()
        content = response.content

        is_pdf = (
            content.startswith(b'%PDF') or
            'pdf' in content_type or
            url.lower().endswith('.pdf')
        )

        if not is_pdf:
            print("Warning: The downloaded file doesn't appear to be a PDF. Attempting to process it anyway...")

        # Extract text from PDF
        print("Extracting text from PDF...")
        text = extract_text_from_pdf(content)

        if text is None:
            # PyPDF2 not available, try to use response.text as fallback
            print("Falling back to treating content as text...")
            text = response.text

        if not text or len(text.strip()) == 0:
            print("Error: Could not extract any text from the PDF.")
            return None

        print(f"Extracted {len(text)} characters of text")

        # Extract case information
        print("Analyzing text for case information...")
        info = extract_case_information_from_text(text)

        return info

    except requests.exceptions.RequestException as e:
        print(f"Error downloading PDF: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def display_results(info):
    """
    Display the extracted case information in a readable format
    """
    if not info:
        print("No information to display.")
        return

    print("\n" + "="*60)
    print("eCourts Cause List Analysis Results")
    print("="*60)

    print(f"\nText Preview (first 500 chars):")
    print("-" * 40)
    # Handle potential encoding issues in the text preview
    preview_text = info['raw_text_preview']
    try:
        print(preview_text)
    except UnicodeEncodeError:
        # If we can't display the text directly, show a safe version
        print(preview_text.encode('ascii', 'replace').decode('ascii'))

    print(f"\nCase Numbers Found ({len(info['case_numbers'])}):")
    print("-" * 40)
    if info['case_numbers']:
        for i, case_num in enumerate(info['case_numbers'], 1):
            print(f"{i}. {case_num}")
    else:
        print("No case numbers found")

    print(f"\nPetitioners/Applicants Found ({len(info['petitioners'])}):")
    print("-" * 40)
    if info['petitioners']:
        for i, petitioner in enumerate(info['petitioners'], 1):
            print(f"{i}. {petitioner}")
    else:
        print("No petitioners found")

    print(f"\nRespondents Found ({len(info['respondents'])}):")
    print("-" * 40)
    if info['respondents']:
        for i, respondent in enumerate(info['respondents'], 1):
            print(f"{i}. {respondent}")
    else:
        print("No respondents found")

    print(f"\nAdvocates/Counsel Found ({len(info['advocates'])}):")
    print("-" * 40)
    if info['advocates']:
        for i, advocate in enumerate(info['advocates'], 1):
            print(f"{i}. {advocate}")
    else:
        print("No advocates found")

    print(f"\nHearing Dates Found ({len(info['hearing_dates'])}):")
    print("-" * 40)
    if info['hearing_dates']:
        for i, date in enumerate(info['hearing_dates'], 1):
            print(f"{i}. {date}")
    else:
        print("No hearing dates found")

    print(f"\nStatus Indicators Found ({len(info['status_indicators'])}):")
    print("-" * 40)
    if info['status_indicators']:
        for i, status in enumerate(info['status_indicators'], 1):
            print(f"{i}. {status}")
    else:
        print("No status indicators found")

    print("\n" + "="*60)

def main():
    """
    Main function to run the PDF cause list analyzer
    """
    print("eCourts PDF Cause List Analyzer")
    print("="*40)

    # Get URL from command line argument or user input
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        try:
            url = input("\nEnter the PDF URL from eCourts website: ").strip()
        except EOFError:
            # Handle case where input is not available (e.g., background process)
            print("Error: No URL provided and unable to read from stdin")
            return

    if not url:
        print("Error: No URL provided")
        return

    # Download and analyze the PDF
    info = download_and_analyze_pdf(url)

    if info:
        display_results(info)

        # Offer to save results to file (only if running interactively)
        try:
            save_option = input("\nSave results to a text file? (y/n): ").strip().lower()
            if save_option == 'y':
                filename = input("Enter filename (default: ecourts_analysis.txt): ").strip()
                if not filename:
                    filename = "ecourts_analysis.txt"

                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write("eCourts Cause List Analysis Results\n")
                        f.write("="*50 + "\n\n")
                        f.write(f"Source URL: {url}\n\n")
                        f.write(f"Text Preview (first 500 chars):\n{info['raw_text_preview']}\n\n")
                        f.write(f"Case Numbers Found ({len(info['case_numbers'])}):\n")
                        for i, case_num in enumerate(info['case_numbers'], 1):
                            f.write(f"{i}. {case_num}\n")
                        f.write("\n")
                        f.write(f"Petitioners/Applicants Found ({len(info['petitioners'])}):\n")
                        for i, petitioner in enumerate(info['petitioners'], 1):
                            f.write(f"{i}. {petitioner}\n")
                        f.write("\n")
                        f.write(f"Respondents Found ({len(info['respondents'])}):\n")
                        for i, respondent in enumerate(info['respondents'], 1):
                            f.write(f"{i}. {respondent}\n")
                        f.write("\n")
                        f.write(f"Advocates/Counsel Found ({len(info['advocates'])}):\n")
                        for i, advocate in enumerate(info['advocates'], 1):
                            f.write(f"{i}. {advocate}\n")
                        f.write("\n")
                        f.write(f"Hearing Dates Found ({len(info['hearing_dates'])}):\n")
                        for i, date in enumerate(info['hearing_dates'], 1):
                            f.write(f"{i}. {date}\n")
                        f.write("\n")
                        f.write(f"Status Indicators Found ({len(info['status_indicators'])}):\n")
                        for i, status in enumerate(info['status_indicators'], 1):
                            f.write(f"{i}. {status}\n")
                    print(f"Results saved to {filename}")
                except Exception as e:
                    print(f"Error saving file: {e}")
        except EOFError:
            # Skip save prompt if running in non-interactive mode
            pass
    else:
        print("Failed to analyze the PDF. Please check the URL and try again.")

if __name__ == "__main__":
    main()
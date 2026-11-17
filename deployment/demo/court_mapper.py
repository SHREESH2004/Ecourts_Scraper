
import os
import re
import glob
import json
import psycopg2
import PyPDF2
from datetime import datetime

# High Court and Bench catalog from 1.py
HIGH_COURTS = [
    ("1", None, "Bombay", "Appellate Side, Bombay"),
    ("1", "2", "Bombay", "Original Side, Bombay"),
    ("1", "3", "Bombay", "Bench At Aurangabad"),
    ("1", "4", "Bombay", "Bench At Nagpur"),
    ("1", "5", "Bombay", "High Court of Bombay at Goa"),
    ("1", "6", "Bombay", "Special Court (TORTS) Bombay High Court"),
    ("10", None, "Madras", "Madras High Court - Principal Bench"),
    ("10", "2", "Madras", "Madras High Court - Madurai Bench"),
    ("11", None, "Odisha", "High Court of Orissa"),
    ("12", None, "Jammu and Kashmir", "High Court of Jammu and Kashmir - Jammu Wing"),
    ("12", "2", "Jammu and Kashmir", "High Court of Jammu and Kashmir - Srinagar Wing"),
    ("13", None, "Uttar Pradesh", "High Court of Judicature at Allahabad"),
    ("13", "2", "Uttar Pradesh", "Allahabad High Court Lucknow Bench"),
    ("15", None, "Uttarakhand", "High Court of Uttarakhand"),
    ("16", None, "Calcutta", "Calcutta High Court - Original Side"),
    ("16", "2", "Calcutta", "Calcutta High Court - Circuit Bench At Jalpaiguri"),
    ("16", "3", "Calcutta", "Calcutta High Court - Appellate side"),
    ("16", "4", "Calcutta", "Calcutta High Court - Circuit Bench At Port Blair"),
    ("17", None, "Gujarat", "High Court of Gujarat"),
    ("18", None, "Chhattisgarh", "High Court of Chhattisgarh"),
    ("2", None, "Andhra Pradesh", "High Court of Andhra Pradesh"),
    ("20", None, "Tripura", "High Court of Tripura"),
    ("21", None, "Meghalaya", "High Court of Meghalaya"),
    ("24", None, "Sikkim", "High Court of Sikkim"),
    ("25", None, "Manipur", "High Court of Manipur"),
    ("29", None, "Telangana", "High Court for the State of Telangana"),
    ("3", None, "Karnataka", "High Court of Karnataka - Principal Bench at Bengaluru"),
    ("3", "2", "Karnataka", "High Court of Karnataka - Dharwad Bench At Karnataka"),
    ("3", "3", "Karnataka", "High Court of Karnataka - Kalburagi Bench At Karnataka"),
    ("4", None, "Kerala", "High Court of Kerala"),
    ("5", None, "Himachal Pradesh", "High Court of Himachal Pradesh"),
    ("6", None, "Assam", "Gawahati High Court - Principal Seat at Guwahati"),
    ("6", "2", "Assam", "Gawahati High Court - Kohima Bench"),
    ("6", "3", "Assam", "Gawahati High Court - Aizawl Bench"),
    ("6", "4", "Assam", "Gawahati High Court - Itanagar Bench"),
    ("7", None, "Jharkhand", "High Court of Jharkhand"),
    ("8", None, "Patna", "The High Court of Judicature at Patna"),
    ("9", None, "Rajasthan", "Rajasthan High Court Bench at Jaipur"),
    ("9", "2", "Rajasthan", "Rajasthan High Court Principal Seat, Jodhpur"),
]

def clean_judge_string(raw_name):
    """Split joint benches and clean up names"""
    if not raw_name:
        return []
    # Common delimiter between judges in division bench
    parts = re.split(r'\s*,\s*(?=HON|\bAND\b|JUSTICE|SMT|SHRI)|(?<=[A-Z\.\s])\s+AND\s+(?=HON|\bJUSTICE\b)', raw_name, flags=re.I)
    cleaned = []
    for p in parts:
        p_clean = re.sub(r'^(?:AND|WITH)\s+', '', p.strip(), flags=re.I).strip()
        if p_clean and len(p_clean) > 3:
            cleaned.append(p_clean)
    return cleaned if cleaned else [raw_name.strip()]

def determine_bench_type(raw_name):
    judges = clean_judge_string(raw_name)
    if 'Registrar' in raw_name or 'REGISTRAR' in raw_name:
        return 'Registrar Court'
    elif len(judges) >= 3:
        return 'Full Bench'
    elif len(judges) == 2:
        return 'Division Bench'
    return 'Single Bench'

def map_court_for_judge(raw_judge_name, pdf_court_header=None):
    """Map a judge to their court based on PDF header or judge name"""
    if pdf_court_header:
        for state_code, court_code, state_name, bench_name in HIGH_COURTS:
            if bench_name.lower() in pdf_court_header.lower() or state_name.lower() in pdf_court_header.lower():
                return {
                    'state_code': state_code,
                    'court_code': court_code or '1',
                    'state_name': state_name,
                    'court_name': bench_name
                }
    
    # Heuristics based on known judges in DB
    raw_upper = raw_judge_name.upper()
    if 'MRIDUL KUMAR KALITA' in raw_upper or 'HELEN DAWNGLIANI' in raw_upper:
        return {
            'state_code': '6',
            'court_code': '1',
            'state_name': 'Assam',
            'court_name': 'Gawahati High Court - Principal Seat at Guwahati'
        }
    elif 'AURANGABAD' in (pdf_court_header or '').upper():
        return {
            'state_code': '1',
            'court_code': '3',
            'state_name': 'Bombay',
            'court_name': 'Bench At Aurangabad'
        }
    elif 'NAGPUR' in (pdf_court_header or '').upper():
        return {
            'state_code': '1',
            'court_code': '4',
            'state_name': 'Bombay',
            'court_name': 'Bench At Nagpur'
        }
    else:
        # Default Bombay HC Appellate Side
        return {
            'state_code': '1',
            'court_code': '1',
            'state_name': 'Bombay',
            'court_name': 'Appellate Side, Bombay'
        }

print("Loaded mapper definitions.")

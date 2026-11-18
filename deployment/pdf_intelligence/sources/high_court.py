"""
Independent High Court Source Adapter
(`deployment/pdf_intelligence/sources/high_court.py`).

Official Portal: https://hcservices.ecourts.gov.in/
Supports State -> High Court -> Bench/Establishment discovery, inclusive date ranges,
Daily & Supplementary Cause Lists, and Orders/Judgments (where supported by the portal,
reporting explicit CAPTCHA/portal limitations when gated).
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .base import (
    BaseCourtSourceAdapter,
    CourtLocationSpec,
    DiscoveredDocument,
    build_safe_pdf_filename,
    compute_document_identity,
    detect_captcha_or_access_gate,
    generate_inclusive_date_range,
)

logger = logging.getLogger(__name__)

ECOURTS_HC_BASE_URL = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
ECOURTS_HC_CAUSELIST_QUERY_URL = f"{ECOURTS_HC_BASE_URL}/cases/highcourt_causelist_qry.php"
ECOURTS_HC_ORDER_QUERY_URL = f"{ECOURTS_HC_BASE_URL}/cases/s_orderdate_qry.php"
ECOURTS_HC_PDF_DISPLAY_URL = f"{ECOURTS_HC_BASE_URL}/cases/display_causelist.php"
ECOURTS_HC_ORDER_PDF_URL = f"{ECOURTS_HC_BASE_URL}/cases/display_pdf.php"

HIGH_COURT_SUPPORTED_CATEGORIES: Tuple[str, ...] = (
    "daily_cause_list",
    "supplementary_cause_list",
    "daily_order",
    "final_judgment",
    "other_case_pdf",
)

# Verified catalog of Indian High Courts and Benches
HIGH_COURT_LOCATIONS: List[CourtLocationSpec] = [
    # --- MAHARASHTRA (eCourts HC state_code = 1) ---
    CourtLocationSpec(
        location_key="hc:1:MH-MUM:1:1",
        court_type="high_court",
        state_code="1",
        state_iso_code="IN-MH",
        state_name="Maharashtra",
        is_union_territory=False,
        district_code="MH-MUM",
        district_name="Mumbai City",
        court_code="BOMBAY-HC",
        court_name="Bombay High Court",
        bench_code="1",
        bench_name="Appellate Side, Bombay",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=18.9290,
        longitude=72.8311,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:1:MH-MUM:1:2",
        court_type="high_court",
        state_code="1",
        state_iso_code="IN-MH",
        state_name="Maharashtra",
        is_union_territory=False,
        district_code="MH-MUM",
        district_name="Mumbai City",
        court_code="BOMBAY-HC",
        court_name="Bombay High Court",
        bench_code="2",
        bench_name="Original Side, Bombay",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=18.9290,
        longitude=72.8311,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    CourtLocationSpec(
        location_key="hc:1:MH-MUM:1:6",
        court_type="high_court",
        state_code="1",
        state_iso_code="IN-MH",
        state_name="Maharashtra",
        is_union_territory=False,
        district_code="MH-MUM",
        district_name="Mumbai City",
        court_code="BOMBAY-HC",
        court_name="Bombay High Court",
        bench_code="6",
        bench_name="Special Court (TORTS) Bombay High Court",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=18.9290,
        longitude=72.8311,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="6",
    ),
    CourtLocationSpec(
        location_key="hc:1:MH-AUR:1:3",
        court_type="high_court",
        state_code="1",
        state_iso_code="IN-MH",
        state_name="Maharashtra",
        is_union_territory=False,
        district_code="MH-AUR",
        district_name="Chhatrapati Sambhajinagar (Aurangabad)",
        court_code="BOMBAY-HC",
        court_name="Bombay High Court",
        bench_code="3",
        bench_name="Bench At Aurangabad",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=19.8762,
        longitude=75.3433,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="3",
    ),
    CourtLocationSpec(
        location_key="hc:1:MH-NAG:1:4",
        court_type="high_court",
        state_code="1",
        state_iso_code="IN-MH",
        state_name="Maharashtra",
        is_union_territory=False,
        district_code="MH-NAG",
        district_name="Nagpur",
        court_code="BOMBAY-HC",
        court_name="Bombay High Court",
        bench_code="4",
        bench_name="Bench At Nagpur",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=21.1458,
        longitude=79.0882,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="4",
    ),
    # --- GOA (Bombay High Court at Goa: state_code=1, court_code=5) ---
    CourtLocationSpec(
        location_key="hc:GA:GA-NGO:1:5",
        court_type="high_court",
        state_code="GA",
        state_iso_code="IN-GA",
        state_name="Goa",
        is_union_territory=False,
        district_code="GA-NGO",
        district_name="North Goa (Porvorim / Panaji)",
        court_code="BOMBAY-HC-GOA",
        court_name="High Court of Bombay at Goa",
        bench_code="5",
        bench_name="High Court of Bombay at Goa",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=15.5186,
        longitude=73.8318,
        portal_state_code="1",
        portal_dist_code="1",
        portal_court_code="5",
    ),
    # --- ANDHRA PRADESH (eCourts HC state_code = 2) ---
    CourtLocationSpec(
        location_key="hc:2:AP-GUN:1:1",
        court_type="high_court",
        state_code="2",
        state_iso_code="IN-AP",
        state_name="Andhra Pradesh",
        is_union_territory=False,
        district_code="AP-GUN",
        district_name="Guntur (Amaravati)",
        court_code="AP-HC",
        court_name="High Court of Andhra Pradesh",
        bench_code="1",
        bench_name="High Court of Andhra Pradesh - Principal Seat at Amaravati",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=16.5172,
        longitude=80.5150,
        portal_state_code="2",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- KARNATAKA (eCourts HC state_code = 3) ---
    CourtLocationSpec(
        location_key="hc:3:KA-BLR:1:1",
        court_type="high_court",
        state_code="3",
        state_iso_code="IN-KA",
        state_name="Karnataka",
        is_union_territory=False,
        district_code="KA-BLR",
        district_name="Bengaluru Urban",
        court_code="KARNATAKA-HC",
        court_name="High Court of Karnataka",
        bench_code="1",
        bench_name="High Court of Karnataka - Principal Bench at Bengaluru",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=12.9784,
        longitude=77.5924,
        portal_state_code="3",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:3:KA-DWR:1:2",
        court_type="high_court",
        state_code="3",
        state_iso_code="IN-KA",
        state_name="Karnataka",
        is_union_territory=False,
        district_code="KA-DWR",
        district_name="Dharwad",
        court_code="KARNATAKA-HC",
        court_name="High Court of Karnataka",
        bench_code="2",
        bench_name="High Court of Karnataka - Dharwad Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=15.4589,
        longitude=75.0078,
        portal_state_code="3",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    CourtLocationSpec(
        location_key="hc:3:KA-KLB:1:3",
        court_type="high_court",
        state_code="3",
        state_iso_code="IN-KA",
        state_name="Karnataka",
        is_union_territory=False,
        district_code="KA-KLB",
        district_name="Kalaburagi",
        court_code="KARNATAKA-HC",
        court_name="High Court of Karnataka",
        bench_code="3",
        bench_name="High Court of Karnataka - Kalaburagi Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=17.3297,
        longitude=76.8343,
        portal_state_code="3",
        portal_dist_code="1",
        portal_court_code="3",
    ),
    # --- KERALA (eCourts HC state_code = 4) ---
    CourtLocationSpec(
        location_key="hc:4:KL-ERN:1:1",
        court_type="high_court",
        state_code="4",
        state_iso_code="IN-KL",
        state_name="Kerala",
        is_union_territory=False,
        district_code="KL-ERN",
        district_name="Ernakulam (Kochi)",
        court_code="KERALA-HC",
        court_name="High Court of Kerala",
        bench_code="1",
        bench_name="High Court of Kerala - Principal Seat at Ernakulam",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=9.9854,
        longitude=76.2756,
        portal_state_code="4",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- HIMACHAL PRADESH (eCourts HC state_code = 5) ---
    CourtLocationSpec(
        location_key="hc:5:HP-SML:1:1",
        court_type="high_court",
        state_code="5",
        state_iso_code="IN-HP",
        state_name="Himachal Pradesh",
        is_union_territory=False,
        district_code="HP-SML",
        district_name="Shimla",
        court_code="HP-HC",
        court_name="High Court of Himachal Pradesh",
        bench_code="1",
        bench_name="High Court of Himachal Pradesh - Principal Seat at Shimla",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=31.1048,
        longitude=77.1734,
        portal_state_code="5",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- ASSAM & GAUHATI HC CIRCUIT BENCHES (eCourts HC state_code = 6) ---
    CourtLocationSpec(
        location_key="hc:6:AS-KMR:1:1",
        court_type="high_court",
        state_code="6",
        state_iso_code="IN-AS",
        state_name="Assam",
        is_union_territory=False,
        district_code="AS-KMR",
        district_name="Kamrup Metropolitan (Guwahati)",
        court_code="GAUHATI-HC",
        court_name="Gauhati High Court",
        bench_code="1",
        bench_name="Gauhati High Court - Principal Seat at Guwahati",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=26.1886,
        longitude=91.7453,
        portal_state_code="6",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:NL:NL-KHM:1:2",
        court_type="high_court",
        state_code="NL",
        state_iso_code="IN-NL",
        state_name="Nagaland",
        is_union_territory=False,
        district_code="NL-KHM",
        district_name="Kohima",
        court_code="GAUHATI-HC",
        court_name="Gauhati High Court",
        bench_code="2",
        bench_name="Gauhati High Court - Kohima Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=25.6751,
        longitude=94.1086,
        portal_state_code="6",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    CourtLocationSpec(
        location_key="hc:MZ:MZ-AIZ:1:3",
        court_type="high_court",
        state_code="MZ",
        state_iso_code="IN-MZ",
        state_name="Mizoram",
        is_union_territory=False,
        district_code="MZ-AIZ",
        district_name="Aizawl",
        court_code="GAUHATI-HC",
        court_name="Gauhati High Court",
        bench_code="3",
        bench_name="Gauhati High Court - Aizawl Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=23.7271,
        longitude=92.7176,
        portal_state_code="6",
        portal_dist_code="1",
        portal_court_code="3",
    ),
    CourtLocationSpec(
        location_key="hc:AR:AR-PAP:1:4",
        court_type="high_court",
        state_code="AR",
        state_iso_code="IN-AR",
        state_name="Arunachal Pradesh",
        is_union_territory=False,
        district_code="AR-PAP",
        district_name="Papum Pare (Itanagar / Naharlagun)",
        court_code="GAUHATI-HC",
        court_name="Gauhati High Court",
        bench_code="4",
        bench_name="Gauhati High Court - Itanagar Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=27.1024,
        longitude=93.6920,
        portal_state_code="6",
        portal_dist_code="1",
        portal_court_code="4",
    ),
    # --- JHARKHAND (eCourts HC state_code = 7) ---
    CourtLocationSpec(
        location_key="hc:7:JH-RAN:1:1",
        court_type="high_court",
        state_code="7",
        state_iso_code="IN-JH",
        state_name="Jharkhand",
        is_union_territory=False,
        district_code="JH-RAN",
        district_name="Ranchi",
        court_code="JHARKHAND-HC",
        court_name="High Court of Jharkhand",
        bench_code="1",
        bench_name="High Court of Jharkhand - Principal Seat at Ranchi",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=23.3116,
        longitude=85.2722,
        portal_state_code="7",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- BIHAR (eCourts HC state_code = 8) ---
    CourtLocationSpec(
        location_key="hc:8:BR-PAT:1:1",
        court_type="high_court",
        state_code="8",
        state_iso_code="IN-BR",
        state_name="Bihar",
        is_union_territory=False,
        district_code="BR-PAT",
        district_name="Patna",
        court_code="PATNA-HC",
        court_name="The High Court of Judicature at Patna",
        bench_code="1",
        bench_name="The High Court of Judicature at Patna",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=25.6095,
        longitude=85.1235,
        portal_state_code="8",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- RAJASTHAN (eCourts HC state_code = 9) ---
    CourtLocationSpec(
        location_key="hc:9:RJ-JPR:1:1",
        court_type="high_court",
        state_code="9",
        state_iso_code="IN-RJ",
        state_name="Rajasthan",
        is_union_territory=False,
        district_code="RJ-JPR",
        district_name="Jaipur",
        court_code="RAJASTHAN-HC",
        court_name="Rajasthan High Court",
        bench_code="1",
        bench_name="Rajasthan High Court Bench at Jaipur",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=26.9012,
        longitude=75.8022,
        portal_state_code="9",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:9:RJ-JDH:1:2",
        court_type="high_court",
        state_code="9",
        state_iso_code="IN-RJ",
        state_name="Rajasthan",
        is_union_territory=False,
        district_code="RJ-JDH",
        district_name="Jodhpur",
        court_code="RAJASTHAN-HC",
        court_name="Rajasthan High Court",
        bench_code="2",
        bench_name="Rajasthan High Court Principal Seat, Jodhpur",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=26.2081,
        longitude=73.0350,
        portal_state_code="9",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    # --- TAMIL NADU (eCourts HC state_code = 10) ---
    CourtLocationSpec(
        location_key="hc:10:TN-CHN:1:1",
        court_type="high_court",
        state_code="10",
        state_iso_code="IN-TN",
        state_name="Tamil Nadu",
        is_union_territory=False,
        district_code="TN-CHN",
        district_name="Chennai",
        court_code="MADRAS-HC",
        court_name="Madras High Court",
        bench_code="1",
        bench_name="Madras High Court - Principal Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=13.0878,
        longitude=80.2870,
        portal_state_code="10",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:10:TN-MDU:1:2",
        court_type="high_court",
        state_code="10",
        state_iso_code="IN-TN",
        state_name="Tamil Nadu",
        is_union_territory=False,
        district_code="TN-MDU",
        district_name="Madurai",
        court_code="MADRAS-HC",
        court_name="Madras High Court",
        bench_code="2",
        bench_name="Madras High Court - Madurai Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=9.9693,
        longitude=78.1704,
        portal_state_code="10",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    # --- ODISHA (eCourts HC state_code = 11) ---
    CourtLocationSpec(
        location_key="hc:11:OR-CTC:1:1",
        court_type="high_court",
        state_code="11",
        state_iso_code="IN-OR",
        state_name="Odisha",
        is_union_territory=False,
        district_code="OR-CTC",
        district_name="Cuttack",
        court_code="ORISSA-HC",
        court_name="High Court of Orissa",
        bench_code="1",
        bench_name="High Court of Orissa - Principal Seat at Cuttack",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=20.4625,
        longitude=85.8628,
        portal_state_code="11",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- JAMMU AND KASHMIR (UT, eCourts HC state_code = 12) ---
    CourtLocationSpec(
        location_key="hc:12:JK-JMU:1:1",
        court_type="high_court",
        state_code="12",
        state_iso_code="IN-JK",
        state_name="Jammu and Kashmir",
        is_union_territory=True,
        district_code="JK-JMU",
        district_name="Jammu",
        court_code="JK-HC",
        court_name="High Court of Jammu & Kashmir and Ladakh",
        bench_code="1",
        bench_name="High Court of Jammu and Kashmir - Jammu Wing",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=32.7520,
        longitude=74.8643,
        portal_state_code="12",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:12:JK-SGR:1:2",
        court_type="high_court",
        state_code="12",
        state_iso_code="IN-JK",
        state_name="Jammu and Kashmir",
        is_union_territory=True,
        district_code="JK-SGR",
        district_name="Srinagar",
        court_code="JK-HC",
        court_name="High Court of Jammu & Kashmir and Ladakh",
        bench_code="2",
        bench_name="High Court of Jammu and Kashmir - Srinagar Wing",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=34.0728,
        longitude=74.8065,
        portal_state_code="12",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    # --- UTTAR PRADESH (eCourts HC state_code = 13) ---
    CourtLocationSpec(
        location_key="hc:13:UP-PRG:1:1",
        court_type="high_court",
        state_code="13",
        state_iso_code="IN-UP",
        state_name="Uttar Pradesh",
        is_union_territory=False,
        district_code="UP-PRG",
        district_name="Prayagraj (Allahabad)",
        court_code="ALLAHABAD-HC",
        court_name="High Court of Judicature at Allahabad",
        bench_code="1",
        bench_name="High Court of Judicature at Allahabad",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=25.4517,
        longitude=81.8168,
        portal_state_code="13",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:13:UP-LKO:1:2",
        court_type="high_court",
        state_code="13",
        state_iso_code="IN-UP",
        state_name="Uttar Pradesh",
        is_union_territory=False,
        district_code="UP-LKO",
        district_name="Lucknow",
        court_code="ALLAHABAD-HC",
        court_name="High Court of Judicature at Allahabad",
        bench_code="2",
        bench_name="Allahabad High Court Lucknow Bench",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=26.8680,
        longitude=81.0068,
        portal_state_code="13",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    # --- UTTARAKHAND (eCourts HC state_code = 15) ---
    CourtLocationSpec(
        location_key="hc:15:UT-NAI:1:1",
        court_type="high_court",
        state_code="15",
        state_iso_code="IN-UT",
        state_name="Uttarakhand",
        is_union_territory=False,
        district_code="UT-NAI",
        district_name="Nainital",
        court_code="UTTARAKHAND-HC",
        court_name="High Court of Uttarakhand",
        bench_code="1",
        bench_name="High Court of Uttarakhand",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=29.3919,
        longitude=79.4542,
        portal_state_code="15",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- WEST BENGAL & ANDAMAN (eCourts HC state_code = 16) ---
    CourtLocationSpec(
        location_key="hc:16:WB-KOL:1:1",
        court_type="high_court",
        state_code="16",
        state_iso_code="IN-WB",
        state_name="West Bengal",
        is_union_territory=False,
        district_code="WB-KOL",
        district_name="Kolkata",
        court_code="CALCUTTA-HC",
        court_name="Calcutta High Court",
        bench_code="1",
        bench_name="Calcutta High Court - Original Side",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=22.5686,
        longitude=88.3435,
        portal_state_code="16",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="hc:16:WB-KOL:1:3",
        court_type="high_court",
        state_code="16",
        state_iso_code="IN-WB",
        state_name="West Bengal",
        is_union_territory=False,
        district_code="WB-KOL",
        district_name="Kolkata",
        court_code="CALCUTTA-HC",
        court_name="Calcutta High Court",
        bench_code="3",
        bench_name="Calcutta High Court - Appellate Side",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=22.5686,
        longitude=88.3435,
        portal_state_code="16",
        portal_dist_code="1",
        portal_court_code="3",
    ),
    CourtLocationSpec(
        location_key="hc:16:WB-JPG:1:2",
        court_type="high_court",
        state_code="16",
        state_iso_code="IN-WB",
        state_name="West Bengal",
        is_union_territory=False,
        district_code="WB-JPG",
        district_name="Jalpaiguri",
        court_code="CALCUTTA-HC",
        court_name="Calcutta High Court",
        bench_code="2",
        bench_name="Calcutta High Court - Circuit Bench At Jalpaiguri",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=26.5215,
        longitude=88.7196,
        portal_state_code="16",
        portal_dist_code="1",
        portal_court_code="2",
    ),
    CourtLocationSpec(
        location_key="hc:AN:AN-PBL:1:4",
        court_type="high_court",
        state_code="AN",
        state_iso_code="IN-AN",
        state_name="Andaman and Nicobar Islands",
        is_union_territory=True,
        district_code="AN-PBL",
        district_name="South Andaman (Port Blair)",
        court_code="CALCUTTA-HC",
        court_name="Calcutta High Court",
        bench_code="4",
        bench_name="Calcutta High Court - Circuit Bench At Port Blair",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=11.6661,
        longitude=92.7463,
        portal_state_code="16",
        portal_dist_code="1",
        portal_court_code="4",
    ),
    # --- GUJARAT (eCourts HC state_code = 17) ---
    CourtLocationSpec(
        location_key="hc:17:GJ-AMD:1:1",
        court_type="high_court",
        state_code="17",
        state_iso_code="IN-GJ",
        state_name="Gujarat",
        is_union_territory=False,
        district_code="GJ-AMD",
        district_name="Ahmedabad",
        court_code="GUJARAT-HC",
        court_name="High Court of Gujarat",
        bench_code="1",
        bench_name="High Court of Gujarat",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=23.0815,
        longitude=72.5256,
        portal_state_code="17",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- CHHATTISGARH (eCourts HC state_code = 18) ---
    CourtLocationSpec(
        location_key="hc:18:CT-BSP:1:1",
        court_type="high_court",
        state_code="18",
        state_iso_code="IN-CT",
        state_name="Chhattisgarh",
        is_union_territory=False,
        district_code="CT-BSP",
        district_name="Bilaspur",
        court_code="CHHATTISGARH-HC",
        court_name="High Court of Chhattisgarh",
        bench_code="1",
        bench_name="High Court of Chhattisgarh",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=22.0084,
        longitude=82.1388,
        portal_state_code="18",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- TRIPURA (eCourts HC state_code = 20) ---
    CourtLocationSpec(
        location_key="hc:20:TR-AGT:1:1",
        court_type="high_court",
        state_code="20",
        state_iso_code="IN-TR",
        state_name="Tripura",
        is_union_territory=False,
        district_code="TR-AGT",
        district_name="West Tripura (Agartala)",
        court_code="TRIPURA-HC",
        court_name="High Court of Tripura",
        bench_code="1",
        bench_name="High Court of Tripura",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=23.8648,
        longitude=91.2869,
        portal_state_code="20",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- MEGHALAYA (eCourts HC state_code = 21) ---
    CourtLocationSpec(
        location_key="hc:21:ML-SHL:1:1",
        court_type="high_court",
        state_code="21",
        state_iso_code="IN-ML",
        state_name="Meghalaya",
        is_union_territory=False,
        district_code="ML-SHL",
        district_name="East Khasi Hills (Shillong)",
        court_code="MEGHALAYA-HC",
        court_name="High Court of Meghalaya",
        bench_code="1",
        bench_name="High Court of Meghalaya",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=25.5788,
        longitude=91.8933,
        portal_state_code="21",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- SIKKIM (eCourts HC state_code = 24) ---
    CourtLocationSpec(
        location_key="hc:24:SK-GTK:1:1",
        court_type="high_court",
        state_code="24",
        state_iso_code="IN-SK",
        state_name="Sikkim",
        is_union_territory=False,
        district_code="SK-GTK",
        district_name="Gangtok",
        court_code="SIKKIM-HC",
        court_name="High Court of Sikkim",
        bench_code="1",
        bench_name="High Court of Sikkim",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=27.3389,
        longitude=88.6065,
        portal_state_code="24",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- MANIPUR (eCourts HC state_code = 25) ---
    CourtLocationSpec(
        location_key="hc:25:MN-IMP:1:1",
        court_type="high_court",
        state_code="25",
        state_iso_code="IN-MN",
        state_name="Manipur",
        is_union_territory=False,
        district_code="MN-IMP",
        district_name="Imphal West",
        court_code="MANIPUR-HC",
        court_name="High Court of Manipur",
        bench_code="1",
        bench_name="High Court of Manipur",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=24.8287,
        longitude=93.9437,
        portal_state_code="25",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- TELANGANA (eCourts HC state_code = 29) ---
    CourtLocationSpec(
        location_key="hc:29:TG-HYD:1:1",
        court_type="high_court",
        state_code="29",
        state_iso_code="IN-TG",
        state_name="Telangana",
        is_union_territory=False,
        district_code="TG-HYD",
        district_name="Hyderabad",
        court_code="TELANGANA-HC",
        court_name="High Court for the State of Telangana",
        bench_code="1",
        bench_name="High Court for the State of Telangana",
        source_system="ecourts_hc_services",
        source_supported=True,
        supported_doc_categories=HIGH_COURT_SUPPORTED_CATEGORIES,
        latitude=17.3688,
        longitude=78.4682,
        portal_state_code="29",
        portal_dist_code="1",
        portal_court_code="1",
    ),
    # --- STANDALONE PORTAL HIGH COURTS (Explicitly documented portal limitations) ---
    CourtLocationSpec(
        location_key="hc:DL:DL-NDL:1:1",
        court_type="high_court",
        state_code="DL",
        state_iso_code="IN-DL",
        state_name="Delhi",
        is_union_territory=True,
        district_code="DL-NDL",
        district_name="New Delhi",
        court_code="DELHI-HC",
        court_name="High Court of Delhi",
        bench_code="1",
        bench_name="High Court of Delhi - Principal Bench",
        source_system="standalone_delhi_hc",
        source_supported=False,
        source_limitation=(
            "High Court of Delhi publishes cause lists and orders on its standalone portal "
            "(delhihighcourt.nic.in) rather than hcservices.ecourts.gov.in."
        ),
        latitude=28.6094,
        longitude=77.2370,
    ),
    CourtLocationSpec(
        location_key="hc:MP:MP-JBP:1:1",
        court_type="high_court",
        state_code="MP",
        state_iso_code="IN-MP",
        state_name="Madhya Pradesh",
        is_union_territory=False,
        district_code="MP-JBP",
        district_name="Jabalpur",
        court_code="MP-HC",
        court_name="High Court of Madhya Pradesh",
        bench_code="1",
        bench_name="High Court of Madhya Pradesh - Principal Seat at Jabalpur",
        source_system="standalone_mp_hc",
        source_supported=False,
        source_limitation=(
            "High Court of Madhya Pradesh hosts cause lists and judgments on its standalone portal "
            "(mphc.gov.in) rather than hcservices.ecourts.gov.in."
        ),
        latitude=23.1670,
        longitude=79.9510,
    ),
    CourtLocationSpec(
        location_key="hc:CH:CH-CHD:1:1",
        court_type="high_court",
        state_code="CH",
        state_iso_code="IN-CH",
        state_name="Chandigarh",
        is_union_territory=True,
        district_code="CH-CHD",
        district_name="Chandigarh",
        court_code="PH-HC",
        court_name="High Court of Punjab and Haryana",
        bench_code="1",
        bench_name="High Court of Punjab and Haryana at Chandigarh",
        source_system="standalone_ph_hc",
        source_supported=False,
        source_limitation=(
            "High Court of Punjab and Haryana publishes cause lists on highcourtchd.gov.in "
            "(serving Punjab, Haryana, and Chandigarh) rather than hcservices.ecourts.gov.in."
        ),
        latitude=30.7589,
        longitude=76.8074,
    ),
]


def build_hc_pdf_display_url(source_reference: str, document_category: str = "daily_cause_list") -> str:
    ref = source_reference.strip()
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    encoded = ref if "%" in ref else urllib.parse.quote(ref, safe="")
    if document_category in ("daily_order", "final_judgment"):
        return f"{ECOURTS_HC_ORDER_PDF_URL}?filename={encoded}"
    return f"{ECOURTS_HC_PDF_DISPLAY_URL}?filename={encoded}"


class HighCourtSourceAdapter(BaseCourtSourceAdapter):
    """
    Independent source adapter for Indian High Courts (`https://hcservices.ecourts.gov.in/`).
    """

    court_type = "high_court"
    portal_base_url = ECOURTS_HC_BASE_URL

    def get_supported_document_categories(self) -> List[str]:
        return list(HIGH_COURT_SUPPORTED_CATEGORIES)

    def get_locations_catalog(self) -> List[CourtLocationSpec]:
        return list(HIGH_COURT_LOCATIONS)

    def discover_for_date_range(
        self,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Tuple[List[DiscoveredDocument], Dict[date, requests.Session], List[str]]:
        if not location.source_supported or not location.portal_state_code:
            limitation = location.source_limitation or (
                f"High Court source {location.source_system} does not support automated date-range scraping."
            )
            raise ValueError(limitation)

        dates = generate_inclusive_date_range(start_date, end_date)
        discovered: List[DiscoveredDocument] = []
        sessions_by_date: Dict[date, requests.Session] = {}
        errors: List[str] = []
        seen_identities: set[str] = set()

        for idx, target_date in enumerate(dates, start=1):
            if progress_callback:
                progress_callback(
                    f"Querying {location.bench_name} [{document_category}] for {target_date.isoformat()} ({idx}/{len(dates)})",
                    idx,
                    len(dates),
                )

            try:
                day_docs, session, day_err = self.discover_for_single_date(
                    location=location,
                    target_date=target_date,
                    document_category=document_category,
                )
                if session is not None:
                    sessions_by_date[target_date] = session
                if day_err:
                    errors.append(f"{target_date.isoformat()}: {day_err}")
                for doc in day_docs:
                    if doc.document_identity not in seen_identities:
                        seen_identities.add(doc.document_identity)
                        discovered.append(doc)
            except Exception as exc:
                err_msg = f"{target_date.isoformat()}: Discovery error - {exc}"
                logger.warning(err_msg)
                errors.append(err_msg)

        return discovered, sessions_by_date, errors

    def discover_for_single_date(
        self,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> Tuple[List[DiscoveredDocument], Optional[requests.Session], Optional[str]]:
        session = self._new_session()
        hc_state = location.portal_state_code or location.state_code or "1"
        hc_dist = location.portal_dist_code or "1"
        hc_court = location.portal_court_code or location.bench_code or "1"

        if document_category in ("daily_order", "final_judgment"):
            url = ECOURTS_HC_ORDER_QUERY_URL
            payload = {
                "state_code": hc_state,
                "dist_code": hc_dist,
                "court_code": hc_court,
                "from_date": target_date.strftime("%d-%m-%Y"),
                "to_date": target_date.strftime("%d-%m-%Y"),
                "report_type": "J" if document_category == "final_judgment" else "O",
                "action_code": "showRecords",
            }
        else:
            url = ECOURTS_HC_CAUSELIST_QUERY_URL
            payload = {
                "state_code": hc_state,
                "dist_code": hc_dist,
                "court_code": hc_court,
                "causelist_dt": target_date.strftime("%d-%m-%Y"),
                "action_code": "pulishedCauselist",
            }

        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = session.post(url, data=payload, timeout=self.request_timeout)
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {response.status_code} from portal"
                    if attempt < self.max_retries:
                        time.sleep(0.8 * (2 ** (attempt - 1)))
                        continue
                    return [], session, last_error

                response.raise_for_status()
                raw_text = response.content.decode("utf-8-sig", errors="replace").strip()

                if not raw_text:
                    return [], session, None

                gate = detect_captcha_or_access_gate(raw_text, response.status_code)
                if gate:
                    return (
                        [],
                        session,
                        f"Official eCourts High Court portal requires CAPTCHA verification for {document_category}: {gate}",
                    )

                upper_head = raw_text[:60].upper()
                if upper_head.startswith("ERROR"):
                    return [], session, f"Portal returned message: {raw_text[:160]}"

                documents = self._parse_hc_response(
                    raw_text=raw_text,
                    location=location,
                    target_date=target_date,
                    document_category=document_category,
                )
                return documents, session, None

            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.8 * (2 ** (attempt - 1)))
                    continue

        return [], session, last_error

    @staticmethod
    def _parse_hc_response(
        raw_text: str,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> List[DiscoveredDocument]:
        records = [rec.strip() for rec in raw_text.split("^#") if rec.strip()]
        docs: List[DiscoveredDocument] = []

        hc_state = location.portal_state_code or location.state_code or "1"
        hc_dist = location.portal_dist_code or "1"
        hc_court = location.portal_court_code or location.bench_code or "1"

        for rec in records:
            fields = rec.split("~")
            if len(fields) < 5:
                continue

            coram_judge = fields[1].strip() if len(fields) > 1 else ""
            cl_type = fields[2].strip() if len(fields) > 2 else "Cause List"
            source_ref = fields[4].strip() if len(fields) > 4 else ""
            if not source_ref:
                continue

            eliminated = (fields[5].strip().upper() == "Y") if len(fields) > 5 else False
            bench_id = fields[6].strip() if len(fields) > 6 else ""
            causelist_id = fields[7].strip() if len(fields) > 7 else ""

            # Classify cause list sub-type if returned from cause list endpoint
            effective_category = document_category
            upper_type = cl_type.upper()
            if document_category in ("daily_cause_list", "supplementary_cause_list"):
                is_supp = any(k in upper_type for k in ("SUPP", "ADDITIONAL", "SPECIAL"))
                if document_category == "supplementary_cause_list" and not is_supp:
                    continue
                if is_supp:
                    effective_category = "supplementary_cause_list"
                else:
                    effective_category = "daily_cause_list"

            doc_identity = compute_document_identity(
                court_type="high_court",
                state_code=location.state_code,
                court_code=location.court_code,
                bench_code=location.bench_code,
                document_category=effective_category,
                listing_date=target_date,
                source_reference=source_ref,
            )
            pdf_url = build_hc_pdf_display_url(source_ref, document_category=effective_category)
            pdf_filename = build_safe_pdf_filename(
                court_type_prefix="HC",
                listing_date=target_date,
                bench_or_est_code=location.bench_code,
                document_category=effective_category,
                source_reference=source_ref,
            )

            order_dt = target_date if effective_category == "daily_order" else None
            judgment_dt = target_date if effective_category == "final_judgment" else None

            docs.append(
                DiscoveredDocument(
                    document_identity=doc_identity,
                    court_type="high_court",
                    state_code=location.state_code,
                    state_name=location.state_name,
                    district_code=location.district_code,
                    district_name=location.district_name,
                    court_code=location.court_code,
                    court_name=location.court_name,
                    bench_code=location.bench_code,
                    bench_name=location.bench_name,
                    document_category=effective_category,
                    listing_date=target_date,
                    cause_list_type=cl_type,
                    coram_judge_raw=coram_judge,
                    source_reference=source_ref,
                    source_url=pdf_url,
                    pdf_filename=pdf_filename,
                    order_date=order_dt,
                    judgment_date=judgment_dt,
                    bench_id=bench_id,
                    cause_list_id=causelist_id,
                    eliminated=eliminated,
                    source_portal="https://hcservices.ecourts.gov.in/",
                    source_metadata={
                        "portal": "https://hcservices.ecourts.gov.in/",
                        "ecourts_hc_state_code": hc_state,
                        "ecourts_hc_court_code": hc_court,
                        "bench_id": bench_id,
                        "cause_list_id": causelist_id,
                        "cause_list_type": cl_type,
                    },
                    ecourts_hc_state_code=hc_state,
                    ecourts_hc_dist_code=hc_dist,
                    ecourts_hc_court_code=hc_court,
                )
            )

        return docs

    def resolve_download_url(self, doc: DiscoveredDocument) -> str:
        return build_hc_pdf_display_url(doc.source_reference, document_category=doc.document_category)

    def extract_source_metadata(self, doc: DiscoveredDocument) -> Dict[str, Any]:
        return {
            "source_portal": "https://hcservices.ecourts.gov.in/",
            "court_type": "high_court",
            "document_category": doc.document_category,
            "bench_id": doc.bench_id,
            "cause_list_id": doc.cause_list_id,
            "ecourts_hc_state_code": doc.ecourts_hc_state_code,
            "ecourts_hc_court_code": doc.ecourts_hc_court_code,
        }

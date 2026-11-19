"""
Unified Source Discovery & Court Hierarchy Catalog (`source_discovery.py`).

Delegates portal-specific discovery to the three independent source adapters in
`deployment/pdf_intelligence/sources/`:
- `SupremeCourtSourceAdapter` (`https://www.sci.gov.in/`)
- `HighCourtSourceAdapter` (`https://hcservices.ecourts.gov.in/`)
- `DistrictCourtSourceAdapter` (`https://services.ecourts.gov.in/`)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .sources import (
    COURT_CATEGORIES,
    DISTRICT_COURT_LOCATIONS,
    DOCUMENT_CATEGORIES,
    HIGH_COURT_LOCATIONS,
    STORAGE_NAMESPACES,
    SUPREME_COURT_LOCATIONS,
    CourtLocationSpec,
    DiscoveredDocument,
    DistrictCourtSourceAdapter,
    HighCourtSourceAdapter,
    PortalAccessLimitation,
    SupremeCourtSourceAdapter,
    build_safe_pdf_filename,
    compute_document_identity,
    generate_inclusive_date_range,
    get_source_adapter,
)
from .sources.base import DEFAULT_BROWSER_HEADERS as DEFAULT_HEADERS, MAX_DATE_RANGE_DAYS
from .sources.high_court import (
    ECOURTS_HC_BASE_URL,
    ECOURTS_HC_CAUSELIST_QUERY_URL,
    ECOURTS_HC_PDF_DISPLAY_URL,
    build_hc_pdf_display_url as build_pdf_display_url,
)

# Alias for backward compatibility
ECourtsHCDiscoveryAdapter = HighCourtSourceAdapter

# Complete verified catalog of Indian States and Union Territories for the India Map
ALL_INDIA_STATES_UTS: List[Dict[str, Any]] = [
    {"state_code": "2", "state_iso_code": "IN-AP", "state_name": "Andhra Pradesh", "is_union_territory": False},
    {"state_code": "AR", "state_iso_code": "IN-AR", "state_name": "Arunachal Pradesh", "is_union_territory": False},
    {"state_code": "6", "state_iso_code": "IN-AS", "state_name": "Assam", "is_union_territory": False},
    {"state_code": "8", "state_iso_code": "IN-BR", "state_name": "Bihar", "is_union_territory": False},
    {"state_code": "18", "state_iso_code": "IN-CT", "state_name": "Chhattisgarh", "is_union_territory": False},
    {"state_code": "GA", "state_iso_code": "IN-GA", "state_name": "Goa", "is_union_territory": False},
    {"state_code": "17", "state_iso_code": "IN-GJ", "state_name": "Gujarat", "is_union_territory": False},
    {"state_code": "HR", "state_iso_code": "IN-HR", "state_name": "Haryana", "is_union_territory": False},
    {"state_code": "5", "state_iso_code": "IN-HP", "state_name": "Himachal Pradesh", "is_union_territory": False},
    {"state_code": "7", "state_iso_code": "IN-JH", "state_name": "Jharkhand", "is_union_territory": False},
    {"state_code": "3", "state_iso_code": "IN-KA", "state_name": "Karnataka", "is_union_territory": False},
    {"state_code": "4", "state_iso_code": "IN-KL", "state_name": "Kerala", "is_union_territory": False},
    {"state_code": "MP", "state_iso_code": "IN-MP", "state_name": "Madhya Pradesh", "is_union_territory": False},
    {"state_code": "1", "state_iso_code": "IN-MH", "state_name": "Maharashtra", "is_union_territory": False},
    {"state_code": "25", "state_iso_code": "IN-MN", "state_name": "Manipur", "is_union_territory": False},
    {"state_code": "21", "state_iso_code": "IN-ML", "state_name": "Meghalaya", "is_union_territory": False},
    {"state_code": "MZ", "state_iso_code": "IN-MZ", "state_name": "Mizoram", "is_union_territory": False},
    {"state_code": "NL", "state_iso_code": "IN-NL", "state_name": "Nagaland", "is_union_territory": False},
    {"state_code": "11", "state_iso_code": "IN-OR", "state_name": "Odisha", "is_union_territory": False},
    {"state_code": "PB", "state_iso_code": "IN-PB", "state_name": "Punjab", "is_union_territory": False},
    {"state_code": "9", "state_iso_code": "IN-RJ", "state_name": "Rajasthan", "is_union_territory": False},
    {"state_code": "24", "state_iso_code": "IN-SK", "state_name": "Sikkim", "is_union_territory": False},
    {"state_code": "10", "state_iso_code": "IN-TN", "state_name": "Tamil Nadu", "is_union_territory": False},
    {"state_code": "29", "state_iso_code": "IN-TG", "state_name": "Telangana", "is_union_territory": False},
    {"state_code": "20", "state_iso_code": "IN-TR", "state_name": "Tripura", "is_union_territory": False},
    {"state_code": "13", "state_iso_code": "IN-UP", "state_name": "Uttar Pradesh", "is_union_territory": False},
    {"state_code": "15", "state_iso_code": "IN-UT", "state_name": "Uttarakhand", "is_union_territory": False},
    {"state_code": "16", "state_iso_code": "IN-WB", "state_name": "West Bengal", "is_union_territory": False},
    # Union Territories
    {"state_code": "AN", "state_iso_code": "IN-AN", "state_name": "Andaman and Nicobar Islands", "is_union_territory": True},
    {"state_code": "CH", "state_iso_code": "IN-CH", "state_name": "Chandigarh", "is_union_territory": True},
    {"state_code": "DH", "state_iso_code": "IN-DN", "state_name": "Dadra and Nagar Haveli and Daman and Diu", "is_union_territory": True},
    {"state_code": "DL", "state_iso_code": "IN-DL", "state_name": "Delhi", "is_union_territory": True},
    {"state_code": "12", "state_iso_code": "IN-JK", "state_name": "Jammu and Kashmir", "is_union_territory": True},
    {"state_code": "LA", "state_iso_code": "IN-LA", "state_name": "Ladakh", "is_union_territory": True},
    {"state_code": "LD", "state_iso_code": "IN-LD", "state_name": "Lakshadweep", "is_union_territory": True},
    {"state_code": "PY", "state_iso_code": "IN-PY", "state_name": "Puducherry", "is_union_territory": True},
]

# Combined verified catalog across all three tiers (Supreme Court, High Courts, District Courts)
COURT_LOCATIONS_CATALOG: List[CourtLocationSpec] = (
    list(SUPREME_COURT_LOCATIONS) + list(HIGH_COURT_LOCATIONS) + list(DISTRICT_COURT_LOCATIONS)
)

SHARED_HIGH_COURT_NOTES: Dict[str, str] = {
    "PB": "Punjab is under the jurisdiction of the High Court of Punjab and Haryana at Chandigarh.",
    "HR": "Haryana is under the jurisdiction of the High Court of Punjab and Haryana at Chandigarh.",
    "DH": "Dadra and Nagar Haveli and Daman and Diu is under the jurisdiction of the Bombay High Court (Appellate Side, Mumbai).",
    "LD": "Lakshadweep is under the jurisdiction of the High Court of Kerala at Ernakulam.",
    "PY": "Puducherry is under the jurisdiction of the Madras High Court at Chennai.",
    "LA": "Ladakh is under the jurisdiction of the High Court of Jammu & Kashmir and Ladakh (Jammu & Srinagar Wings).",
}


def find_location_spec(
    state_code: Optional[str] = None,
    court_type: str = "high_court",
    district_code: Optional[str] = None,
    bench_code: Optional[str] = None,
    complex_code: Optional[str] = None,
    establishment_code: Optional[str] = None,
    court_code: Optional[str] = None,
) -> Tuple[Optional[CourtLocationSpec], Optional[str]]:
    """
    Resolve a `CourtLocationSpec` for Supreme Court, High Court, or District Court,
    or return an explicit limitation message if the requested scope is unsupported.
    """
    ctype_norm = str(court_type or "high_court").strip().lower()
    if ctype_norm not in COURT_CATEGORIES:
        return None, f"Unsupported court_type '{court_type}'. Supported: {list(COURT_CATEGORIES)}."

    # 1. National-level Supreme Court (no state or district)
    if ctype_norm == "supreme_court":
        sc_matches = list(SUPREME_COURT_LOCATIONS)
        if bench_code:
            b_norm = str(bench_code).strip().casefold()
            filtered = [
                loc for loc in sc_matches
                if loc.bench_code.casefold() == b_norm
                or loc.bench_name.casefold() == b_norm
                or loc.location_key.casefold() == b_norm
                or (loc.portal_court_code or "").casefold() == b_norm
            ]
            if not filtered:
                avail = ", ".join(f"{l.bench_name} ({l.bench_code})" for l in sc_matches)
                return None, f"Supreme Court bench '{bench_code}' not found. Available: {avail}."
            sc_matches = filtered
        return sc_matches[0], None

    # 2. State-scoped High Courts & District Courts
    state_norm = str(state_code or "").strip()
    if not state_norm:
        return None, f"state_code is required for {ctype_norm.replace('_', ' ')} scraping."

    state_matches = [
        loc for loc in COURT_LOCATIONS_CATALOG
        if loc.court_type == ctype_norm
        and (
            (loc.state_code or "").casefold() == state_norm.casefold()
            or (loc.state_iso_code or "").casefold() == state_norm.casefold()
            or (loc.state_name or "").casefold() == state_norm.casefold()
        )
    ]

    if not state_matches:
        if ctype_norm == "high_court" and state_norm.upper() in SHARED_HIGH_COURT_NOTES:
            return None, SHARED_HIGH_COURT_NOTES[state_norm.upper()]
        return None, f"No verified {ctype_norm.replace('_', ' ')} source found for state '{state_code}'."

    if district_code:
        dist_norm = str(district_code).strip().casefold()
        dist_matches = [
            loc for loc in state_matches
            if (loc.district_code or "").casefold() == dist_norm
            or (loc.district_name or "").casefold() == dist_norm
        ]
        if not dist_matches:
            avail_dists = sorted({loc.district_name or "" for loc in state_matches if loc.district_name})
            return None, (
                f"District '{district_code}' has no registered {ctype_norm.replace('_', ' ')} in the catalog. "
                f"Available district(s): {', '.join(avail_dists)}."
            )
        state_matches = dist_matches

    if complex_code and ctype_norm == "district_court":
        cx_norm = str(complex_code).strip().casefold()
        cx_matches = [
            loc for loc in state_matches
            if (loc.complex_code or "").casefold() == cx_norm
            or (loc.complex_name or "").casefold() == cx_norm
        ]
        if not cx_matches:
            avail_cx = sorted({f"{loc.complex_name} ({loc.complex_code})" for loc in state_matches if loc.complex_code})
            return None, f"Court complex '{complex_code}' not found. Available complexes: {', '.join(avail_cx)}."
        state_matches = cx_matches

    if court_code:
        cc_norm = str(court_code).strip().casefold()
        cc_matches = [
            loc for loc in state_matches
            if loc.court_code.casefold() == cc_norm or loc.court_name.casefold() == cc_norm
        ]
        if cc_matches:
            state_matches = cc_matches

    target_est_or_bench = establishment_code or bench_code
    if target_est_or_bench:
        eb_norm = str(target_est_or_bench).strip().casefold()
        eb_matches = [
            loc for loc in state_matches
            if loc.bench_code.casefold() == eb_norm
            or loc.bench_name.casefold() == eb_norm
            or (loc.establishment_code or "").casefold() == eb_norm
            or (loc.establishment_name or "").casefold() == eb_norm
            or loc.location_key.casefold() == eb_norm
        ]
        if not eb_matches:
            avail_b = ", ".join(f"{loc.bench_name} ({loc.bench_code})" for loc in state_matches)
            return None, f"Bench/Establishment '{target_est_or_bench}' not found. Available: {avail_b}."
        state_matches = eb_matches

    chosen = state_matches[0]
    if not chosen.source_supported:
        return chosen, chosen.source_limitation or "Selected court source does not support automated scraping."

    return chosen, None

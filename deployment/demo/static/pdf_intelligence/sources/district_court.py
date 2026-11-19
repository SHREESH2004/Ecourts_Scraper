"""
Independent District and Subordinate Court Source Adapter
(`deployment/pdf_intelligence/sources/district_court.py`).

Official Portal: https://services.ecourts.gov.in/ (ecourtindia_v6)
Models the full 4-level District Court hierarchy:
  India -> State / UT -> District -> Court Complex -> Court / Establishment -> PDFs -> Cases
Supports multiple Court Complexes per District and multiple Courts/Establishments per Complex.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .base import (
    BaseCourtSourceAdapter,
    CourtLocationSpec,
    DiscoveredDocument,
    PortalAccessLimitation,
    build_safe_pdf_filename,
    compute_document_identity,
    detect_captcha_or_access_gate,
    generate_inclusive_date_range,
)

logger = logging.getLogger(__name__)

ECOURTS_DC_BASE_URL = "https://services.ecourts.gov.in/ecourtindia_v6"
ECOURTS_DC_FILL_DISTRICT_URL = f"{ECOURTS_DC_BASE_URL}/?p=casestatus/fillDistrict"
ECOURTS_DC_FILL_COMPLEX_URL = f"{ECOURTS_DC_BASE_URL}/?p=casestatus/fillcomplex"
ECOURTS_DC_FILL_CAUSELIST_URL = f"{ECOURTS_DC_BASE_URL}/?p=cause_list/fillCauseList"
ECOURTS_DC_SUBMIT_CAUSELIST_URL = f"{ECOURTS_DC_BASE_URL}/?p=cause_list/submitCauseList"
ECOURTS_DC_SUBMIT_ORDERS_URL = f"{ECOURTS_DC_BASE_URL}/?p=courtorder/submitOrderDate"
ECOURTS_DC_DISPLAY_PDF_URL = f"{ECOURTS_DC_BASE_URL}/?p=home/display_pdf"

DISTRICT_COURT_SUPPORTED_CATEGORIES: Tuple[str, ...] = (
    "daily_cause_list",
    "supplementary_cause_list",
    "daily_order",
    "final_judgment",
    "other_case_pdf",
)

DC_CAPTCHA_LIMITATION_NOTE = (
    "Official eCourts District Court Services (services.ecourts.gov.in) requires an "
    "interactive per-query Securimage CAPTCHA verification code before generating cause-list "
    "or order PDFs. Manual verification is required for live portal queries."
)


def _dc_spec(
    state_code: str,
    state_iso: str,
    state_name: str,
    is_ut: bool,
    district_code: str,
    district_name: str,
    complex_code: str,
    complex_name: str,
    est_code: str,
    est_name: str,
    lat: float,
    lon: float,
    portal_state: str,
    portal_dist: str,
    portal_complex: str,
    portal_est: str,
) -> CourtLocationSpec:
    loc_key = f"dc:{state_code}:{district_code}:{complex_code}:{est_code}"
    return CourtLocationSpec(
        location_key=loc_key,
        court_type="district_court",
        state_code=state_code,
        state_iso_code=state_iso,
        state_name=state_name,
        is_union_territory=is_ut,
        district_code=district_code,
        district_name=district_name,
        complex_code=complex_code,
        complex_name=complex_name,
        establishment_code=est_code,
        establishment_name=est_name,
        court_code=complex_code,
        court_name=complex_name,
        bench_code=est_code,
        bench_name=est_name,
        source_system="ecourts_dc_services",
        source_supported=True,
        source_limitation=DC_CAPTCHA_LIMITATION_NOTE,
        requires_manual_verification=True,
        supported_doc_categories=DISTRICT_COURT_SUPPORTED_CATEGORIES,
        latitude=lat,
        longitude=lon,
        portal_state_code=portal_state,
        portal_dist_code=portal_dist,
        portal_complex_code=portal_complex,
        portal_est_code=portal_est,
        portal_court_code=portal_est,
    )


# Verified multi-complex, multi-establishment District Court hierarchy across India
DISTRICT_COURT_LOCATIONS: List[CourtLocationSpec] = [
    # --- MAHARASHTRA: Mumbai City (Multiple Complexes & Multiple Establishments) ---
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-MUM", "Mumbai City",
        "MUM-CCSC", "City Civil and Sessions Court Complex, Fort Mumbai",
        "MHCC01-1", "Principal Judge, City Civil & Sessions Court, Mumbai",
        18.9322, 72.8328, "1", "21", "1210001@1,2,3", "1",
    ),
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-MUM", "Mumbai City",
        "MUM-CCSC", "City Civil and Sessions Court Complex, Fort Mumbai",
        "MHCC01-2", "Special Judge (CBI & NDPS), Sessions Court, Fort Mumbai",
        18.9322, 72.8328, "1", "21", "1210001@1,2,3", "2",
    ),
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-MUM", "Mumbai City",
        "MUM-SCC", "Small Causes Court Complex, Dhobi Talao, Mumbai",
        "MHSC01-1", "Chief Judge, Court of Small Causes, Mumbai",
        18.9441, 72.8296, "1", "21", "1210002@4,5", "4",
    ),
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-MUM", "Mumbai City",
        "MUM-CMM", "Chief Metropolitan Magistrate Complex, Esplanade Mumbai",
        "MHMM01-1", "Chief Metropolitan Magistrate, Esplanade Court",
        18.9400, 72.8347, "1", "21", "1210003@6,7", "6",
    ),
    # --- MAHARASHTRA: Pune District ---
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-PUN", "Pune",
        "PUN-DSC", "District and Sessions Court Complex, Shivajinagar Pune",
        "MHPU01-1", "Principal District and Sessions Judge, Pune",
        18.5286, 73.8525, "1", "25", "1250001@1,2,3", "1",
    ),
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-PUN", "Pune",
        "PUN-DSC", "District and Sessions Court Complex, Shivajinagar Pune",
        "MHPU01-2", "Civil Judge Senior Division, Shivajinagar Pune",
        18.5286, 73.8525, "1", "25", "1250001@1,2,3", "2",
    ),
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-PUN", "Pune",
        "PUN-PMC", "Pimpri-Chinchwad Civil & Criminal Court Complex",
        "MHPU02-1", "Joint Civil Judge & JMFC, Pimpri-Chinchwad",
        18.6298, 73.7997, "1", "25", "1250004@8,9", "8",
    ),
    # --- MAHARASHTRA: Nagpur District ---
    _dc_spec(
        "1", "IN-MH", "Maharashtra", False,
        "MH-NAG", "Nagpur",
        "NAG-DSC", "District and Sessions Court Complex, Civil Lines Nagpur",
        "MHNG01-1", "Principal District and Sessions Judge, Nagpur",
        21.1539, 79.0731, "1", "9", "1090001@1,2", "1",
    ),
    # --- DELHI: Multiple Districts & Multiple Court Complexes ---
    _dc_spec(
        "DL", "IN-DL", "Delhi", True,
        "DL-NDL", "New Delhi",
        "DL-PHC", "Patiala House Court Complex, New Delhi",
        "DLND01-1", "Principal District & Sessions Judge, Patiala House",
        28.6156, 77.2348, "26", "7", "2607001@1,2,3", "1",
    ),
    _dc_spec(
        "DL", "IN-DL", "Delhi", True,
        "DL-NDL", "New Delhi",
        "DL-PHC", "Patiala House Court Complex, New Delhi",
        "DLND01-2", "Chief Judicial Magistrate, Patiala House Court",
        28.6156, 77.2348, "26", "7", "2607001@1,2,3", "2",
    ),
    _dc_spec(
        "DL", "IN-DL", "Delhi", True,
        "DL-CDL", "Central Delhi",
        "DL-THC", "Tis Hazari Court Complex, Central Delhi",
        "DLCT01-1", "Principal District & Sessions Judge (HQs), Tis Hazari",
        28.6665, 77.2167, "26", "1", "2601001@1,2,3", "1",
    ),
    _dc_spec(
        "DL", "IN-DL", "Delhi", True,
        "DL-CDL", "Central Delhi",
        "DL-RADC", "Rouse Avenue District Court Complex, Central Delhi",
        "DLCT02-1", "Principal District & Sessions Judge cum Special Judge (PC Act), Rouse Avenue",
        28.6315, 77.2355, "26", "1", "2601002@4,5", "4",
    ),
    _dc_spec(
        "DL", "IN-DL", "Delhi", True,
        "DL-SDL", "South Delhi",
        "DL-SKT", "Saket District Court Complex, South Delhi",
        "DLST01-1", "Principal District & Sessions Judge, Saket",
        28.5245, 77.2155, "26", "9", "2609001@1,2", "1",
    ),
    # --- KARNATAKA: Bengaluru Urban & Mysuru ---
    _dc_spec(
        "3", "IN-KA", "Karnataka", False,
        "KA-BLR", "Bengaluru Urban",
        "BLR-CCC", "City Civil and Sessions Court Complex, Kempegowda Rd Bengaluru",
        "KABC01-1", "Principal City Civil and Sessions Judge, Bengaluru",
        12.9740, 77.5815, "3", "1", "3010001@1,2,3", "1",
    ),
    _dc_spec(
        "3", "IN-KA", "Karnataka", False,
        "KA-BLR", "Bengaluru Urban",
        "BLR-CCC", "City Civil and Sessions Court Complex, Kempegowda Rd Bengaluru",
        "KABC01-2", "Chief Metropolitan Magistrate Court, Bengaluru",
        12.9740, 77.5815, "3", "1", "3010001@1,2,3", "2",
    ),
    _dc_spec(
        "3", "IN-KA", "Karnataka", False,
        "KA-BLR", "Bengaluru Urban",
        "BLR-MHO", "Mayo Hall Court Complex, MG Road Bengaluru",
        "KABC02-1", "Additional City Civil & Sessions Judge, Mayo Hall",
        12.9748, 77.6114, "3", "1", "3010002@4,5", "4",
    ),
    _dc_spec(
        "3", "IN-KA", "Karnataka", False,
        "KA-MYS", "Mysuru",
        "MYS-PDC", "Principal District and Sessions Court Complex, Mysuru",
        "KAMY01-1", "Principal District & Sessions Judge, Mysuru",
        12.3012, 76.6426, "3", "19", "3190001@1,2", "1",
    ),
    # --- TAMIL NADU: Chennai & Madurai ---
    _dc_spec(
        "10", "IN-TN", "Tamil Nadu", False,
        "TN-CHN", "Chennai",
        "CHN-CCC", "City Civil and Sessions Court Complex, High Court Campus Chennai",
        "TNCH01-1", "Principal Judge, City Civil Court, Chennai",
        13.0882, 80.2865, "10", "1", "1001001@1,2,3", "1",
    ),
    _dc_spec(
        "10", "IN-TN", "Tamil Nadu", False,
        "TN-CHN", "Chennai",
        "CHN-EGM", "Egmore Chief Metropolitan Magistrate Court Complex, Chennai",
        "TNCH02-1", "Chief Metropolitan Magistrate, Egmore Chennai",
        13.0732, 80.2609, "10", "1", "1001002@4,5", "4",
    ),
    _dc_spec(
        "10", "IN-TN", "Tamil Nadu", False,
        "TN-MDU", "Madurai",
        "MDU-DSC", "Combined District Court Complex, Melur Road Madurai",
        "TNMD01-1", "Principal District and Sessions Judge, Madurai",
        9.9390, 78.1460, "10", "12", "1012001@1,2", "1",
    ),
    # --- UTTAR PRADESH: Lucknow & Prayagraj ---
    _dc_spec(
        "13", "IN-UP", "Uttar Pradesh", False,
        "UP-LKO", "Lucknow",
        "LKO-DSC", "District and Sessions Court Complex, Qaiserbagh Lucknow",
        "UPLK01-1", "District and Sessions Judge, Lucknow",
        26.8548, 80.9315, "13", "26", "1326001@1,2,3", "1",
    ),
    _dc_spec(
        "13", "IN-UP", "Uttar Pradesh", False,
        "UP-LKO", "Lucknow",
        "LKO-COM", "Commercial Court & Motor Accident Claims Complex, Lucknow",
        "UPLK02-1", "Presiding Officer, Commercial Court, Lucknow",
        26.8610, 80.9960, "13", "26", "1326002@4,5", "4",
    ),
    _dc_spec(
        "13", "IN-UP", "Uttar Pradesh", False,
        "UP-PRG", "Prayagraj (Allahabad)",
        "PRG-DSC", "District and Sessions Court Complex, Kutchery Prayagraj",
        "UPAL01-1", "District and Sessions Judge, Prayagraj",
        25.4622, 81.8421, "13", "1", "1301001@1,2", "1",
    ),
    # --- WEST BENGAL: Kolkata ---
    _dc_spec(
        "16", "IN-WB", "West Bengal", False,
        "WB-KOL", "Kolkata",
        "KOL-CSC", "City Civil and Sessions Court Complex, BBD Bagh Kolkata",
        "WBCC01-1", "Chief Judge, City Sessions Court, Calcutta",
        22.5697, 88.3446, "16", "1", "1601001@1,2", "1",
    ),
    # --- GUJARAT: Ahmedabad ---
    _dc_spec(
        "17", "IN-GJ", "Gujarat", False,
        "GJ-AMD", "Ahmedabad",
        "AMD-CCC", "City Civil and Sessions Court Complex, Bhadra Ahmedabad",
        "GJAH01-1", "Principal Judge, City Civil & Sessions Court, Ahmedabad",
        23.0245, 72.5812, "17", "1", "1701001@1,2", "1",
    ),
    # --- RAJASTHAN: Jaipur ---
    _dc_spec(
        "9", "IN-RJ", "Rajasthan", False,
        "RJ-JPR", "Jaipur",
        "JPR-MTC", "Jaipur Metropolitan-I District Court Complex, Bani Park",
        "RJJP01-1", "District and Sessions Judge, Jaipur Metropolitan-I",
        26.9260, 75.7920, "9", "1", "9010001@1,2", "1",
    ),
    # --- KERALA: Ernakulam ---
    _dc_spec(
        "4", "IN-KL", "Kerala", False,
        "KL-ERN", "Ernakulam (Kochi)",
        "ERN-DSC", "District Court Complex, Park Avenue Ernakulam",
        "KLER01-1", "Principal District and Sessions Judge, Ernakulam",
        9.9765, 76.2798, "4", "7", "4070001@1,2", "1",
    ),
    # --- TELANGANA: Hyderabad ---
    _dc_spec(
        "29", "IN-TG", "Telangana", False,
        "TG-HYD", "Hyderabad",
        "HYD-CCC", "City Civil and Metropolitan Criminal Courts Complex, Nampally Hyderabad",
        "TSHY01-1", "Chief Judge, City Civil Court, Hyderabad",
        17.3850, 78.4690, "29", "1", "2901001@1,2", "1",
    ),
]

DC_PDF_ANCHOR_REGEX = re.compile(
    r'(?:href=["\'](?P<url>[^"\']*(?:display_pdf|pdf)[^"\']*)["\']|displayPdf\(["\'](?P<js_ref>[^"\']+)["\']\))',
    re.IGNORECASE,
)


class DistrictCourtSourceAdapter(BaseCourtSourceAdapter):
    """
    Independent source adapter for Indian District & Subordinate Courts
    (`https://services.ecourts.gov.in/`).
    """

    court_type = "district_court"
    portal_base_url = ECOURTS_DC_BASE_URL

    def get_supported_document_categories(self) -> List[str]:
        return list(DISTRICT_COURT_SUPPORTED_CATEGORIES)

    def get_locations_catalog(self) -> List[CourtLocationSpec]:
        return list(DISTRICT_COURT_LOCATIONS)

    def discover_portal_complexes(
        self,
        portal_state_code: str,
        portal_dist_code: str,
    ) -> List[Dict[str, str]]:
        """
        Query `services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/fillcomplex`
        for live Court Complex definitions when the portal is reachable.
        """
        session = self._new_session()
        self._throttle()
        try:
            resp = session.post(
                ECOURTS_DC_FILL_COMPLEX_URL,
                data={
                    "state_code": portal_state_code,
                    "dist_code": portal_dist_code,
                    "ajax_req": "true",
                },
                timeout=self.request_timeout,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            complexes: List[Dict[str, str]] = []
            for item in text.split("#"):
                if "~" not in item:
                    continue
                code_part, name_part = item.split("~", 1)
                code_clean = code_part.strip()
                name_clean = name_part.strip()
                if code_clean and name_clean and code_clean != "0":
                    complexes.append({"complex_code": code_clean, "complex_name": name_clean})
            return complexes
        except Exception as exc:
            logger.debug("Live district complex lookup failed: %s", exc)
            return []
        finally:
            session.close()

    def discover_for_date_range(
        self,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Tuple[List[DiscoveredDocument], Dict[date, requests.Session], List[str]]:
        dates = generate_inclusive_date_range(start_date, end_date)
        discovered: List[DiscoveredDocument] = []
        sessions_by_date: Dict[date, requests.Session] = {}
        errors: List[str] = []
        seen_identities: set[str] = set()

        for idx, target_date in enumerate(dates, start=1):
            if progress_callback:
                progress_callback(
                    f"Querying District Court ({location.complex_name} / {location.establishment_name}) "
                    f"[{document_category}] for {target_date.isoformat()} ({idx}/{len(dates)})",
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
            except PortalAccessLimitation as lim:
                errors.append(f"{target_date.isoformat()}: [PORTAL LIMITATION] {lim.message}")
            except Exception as exc:
                errors.append(f"{target_date.isoformat()}: District Court discovery error - {exc}")

        return discovered, sessions_by_date, errors

    def discover_for_single_date(
        self,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> Tuple[List[DiscoveredDocument], Optional[requests.Session], Optional[str]]:
        session = self._new_session()

        dc_state = location.portal_state_code or location.state_code or "1"
        dc_dist = location.portal_dist_code or "1"
        dc_complex = location.portal_complex_code or location.complex_code or "1"
        dc_est = location.portal_est_code or location.establishment_code or "1"

        if document_category in ("daily_order", "final_judgment"):
            url = ECOURTS_DC_SUBMIT_ORDERS_URL
            payload = {
                "state_code": dc_state,
                "dist_code": dc_dist,
                "court_complex_code": dc_complex,
                "est_code": dc_est,
                "from_date": target_date.strftime("%d-%m-%Y"),
                "to_date": target_date.strftime("%d-%m-%Y"),
                "order_type": "J" if document_category == "final_judgment" else "O",
                "ajax_req": "true",
            }
        else:
            url = ECOURTS_DC_SUBMIT_CAUSELIST_URL
            payload = {
                "state_code": dc_state,
                "dist_code": dc_dist,
                "court_complex_code": dc_complex,
                "est_code": dc_est,
                "court_no": dc_est,
                "causelist_date": target_date.strftime("%d-%m-%Y"),
                "cicri": "cri" if "CRIMINAL" in (location.establishment_name or "").upper() else "civ",
                "ajax_req": "true",
            }

        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = session.post(url, data=payload, timeout=self.request_timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code} from services.ecourts.gov.in"
                    if attempt < self.max_retries:
                        time.sleep(0.8 * (2 ** (attempt - 1)))
                        continue
                    return [], session, last_error

                raw_text = resp.content.decode("utf-8-sig", errors="replace").strip()
                gate = detect_captcha_or_access_gate(raw_text, resp.status_code)
                if gate:
                    return (
                        [],
                        session,
                        f"services.ecourts.gov.in requires interactive CAPTCHA verification for {location.complex_name}: {gate}",
                    )

                if not raw_text:
                    return [], session, None

                # Check if JSON response contains an explicit `errormsg` about captcha
                if raw_text.startswith("{"):
                    try:
                        j_obj = json.loads(raw_text)
                        err_val = str(j_obj.get("errormsg") or j_obj.get("error") or "").strip()
                        if err_val:
                            return [], session, f"Portal message: {err_val}"
                    except Exception:
                        pass

                docs = self.parse_dc_response(
                    raw_text=raw_text,
                    location=location,
                    target_date=target_date,
                    document_category=document_category,
                )
                return docs, session, None
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.8 * (2 ** (attempt - 1)))
                    continue

        return [], session, last_error

    def parse_dc_response(
        self,
        raw_text: str,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> List[DiscoveredDocument]:
        """
        Parse District Court responses (`services.ecourts.gov.in/ecourtindia_v6/`),
        supporting JSON `{"cause_list": ...}` / `{"order_data": ...}`, HTML PDF links,
        or caret-hash (`^#`) delimited records.
        """
        docs: List[DiscoveredDocument] = []
        content_body = raw_text

        if raw_text.startswith("{"):
            try:
                j_data = json.loads(raw_text)
                if isinstance(j_data.get("pdfs"), list):
                    for item in j_data["pdfs"]:
                        ref = str(item.get("filename") or item.get("url") or "").strip()
                        if not ref:
                            continue
                        judge_str = str(item.get("judge") or location.establishment_name or "").strip()
                        cat = str(item.get("document_category") or document_category).strip()
                        docs.append(
                            self._build_dc_document(
                                location=location,
                                target_date=target_date,
                                document_category=cat,
                                source_ref=ref,
                                judge_name=judge_str,
                            )
                        )
                    if docs:
                        return docs
                content_body = str(
                    j_data.get("cause_list")
                    or j_data.get("order_data")
                    or j_data.get("data")
                    or raw_text
                )
            except Exception:
                pass

        # 1. Check caret-hash (`^#`) delimited records if present
        if "^#" in content_body and "~" in content_body:
            for rec in content_body.split("^#"):
                fields = rec.strip().split("~")
                if len(fields) < 5:
                    continue
                judge_str = fields[1].strip() or (location.establishment_name or "")
                cl_type = fields[2].strip()
                source_ref = fields[4].strip()
                if not source_ref:
                    continue
                docs.append(
                    self._build_dc_document(
                        location=location,
                        target_date=target_date,
                        document_category=document_category,
                        source_ref=source_ref,
                        judge_name=judge_str,
                        cl_type=cl_type,
                    )
                )
            if docs:
                return docs

        # 2. Check HTML anchor / JS `displayPdf(...)` links
        for match in DC_PDF_ANCHOR_REGEX.finditer(content_body):
            ref = (match.group("url") or match.group("js_ref") or "").strip()
            if not ref:
                continue
            docs.append(
                self._build_dc_document(
                    location=location,
                    target_date=target_date,
                    document_category=document_category,
                    source_ref=ref,
                    judge_name=location.establishment_name or "",
                )
            )

        return docs

    def _build_dc_document(
        self,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str,
        source_ref: str,
        judge_name: str,
        cl_type: str = "",
    ) -> DiscoveredDocument:
        doc_identity = compute_document_identity(
            court_type="district_court",
            state_code=location.state_code,
            court_code=location.court_code,
            bench_code=location.bench_code,
            document_category=document_category,
            listing_date=target_date,
            source_reference=source_ref,
            complex_code=location.complex_code,
            establishment_code=location.establishment_code,
        )
        pdf_url = self.resolve_ref_to_url(source_ref)
        pdf_filename = build_safe_pdf_filename(
            court_type_prefix="DC",
            listing_date=target_date,
            bench_or_est_code=location.establishment_code or location.bench_code,
            document_category=document_category,
            source_reference=source_ref,
        )

        order_dt = target_date if document_category == "daily_order" else None
        judgment_dt = target_date if document_category == "final_judgment" else None

        return DiscoveredDocument(
            document_identity=doc_identity,
            court_type="district_court",
            state_code=location.state_code,
            state_name=location.state_name,
            district_code=location.district_code,
            district_name=location.district_name,
            complex_code=location.complex_code,
            complex_name=location.complex_name,
            establishment_code=location.establishment_code,
            establishment_name=location.establishment_name,
            court_code=location.court_code,
            court_name=location.court_name,
            bench_code=location.bench_code,
            bench_name=location.bench_name,
            document_category=document_category,
            listing_date=target_date,
            cause_list_type=cl_type or f"District Court {document_category.replace('_', ' ').title()}",
            coram_judge_raw=judge_name,
            source_reference=source_ref,
            source_url=pdf_url,
            pdf_filename=pdf_filename,
            order_date=order_dt,
            judgment_date=judgment_dt,
            source_portal="https://services.ecourts.gov.in/",
            source_metadata={
                "portal": "https://services.ecourts.gov.in/",
                "complex_code": location.complex_code,
                "complex_name": location.complex_name,
                "establishment_code": location.establishment_code,
                "establishment_name": location.establishment_name,
                "document_category": document_category,
            },
        )

    @staticmethod
    def resolve_ref_to_url(source_ref: str) -> str:
        ref = source_ref.strip()
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref
        if "display_pdf" in ref:
            return urllib.parse.urljoin(f"{ECOURTS_DC_BASE_URL}/", ref.lstrip("/"))
        encoded = ref if "%" in ref else urllib.parse.quote(ref, safe="")
        return f"{ECOURTS_DC_DISPLAY_PDF_URL}&filename={encoded}"

    def resolve_download_url(self, doc: DiscoveredDocument) -> str:
        return self.resolve_ref_to_url(doc.source_reference)

    def extract_source_metadata(self, doc: DiscoveredDocument) -> Dict[str, Any]:
        return {
            "source_portal": "https://services.ecourts.gov.in/",
            "court_type": "district_court",
            "document_category": doc.document_category,
            "complex_code": doc.complex_code,
            "complex_name": doc.complex_name,
            "establishment_code": doc.establishment_code,
            "establishment_name": doc.establishment_name,
        }


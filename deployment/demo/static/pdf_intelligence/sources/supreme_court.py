"""
Independent Supreme Court of India Source Adapter
(`deployment/pdf_intelligence/sources/supreme_court.py`).

Official Portal: https://www.sci.gov.in/ (and https://api.sci.gov.in/)
Models the Supreme Court strictly as a national-level court (`state_code=None`,
`district_code=None`), supporting Daily Cause Lists, Supplementary Cause Lists,
Daily Orders, Final Judgments, and Other Official Case PDFs.
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

SCI_BASE_URL = "https://www.sci.gov.in"
SCI_AJAX_URL = f"{SCI_BASE_URL}/wp-admin/admin-ajax.php"
SCI_CAUSELIST_PAGE_URL = f"{SCI_BASE_URL}/cause-list/"
SCI_DAILY_ORDER_PAGE_URL = f"{SCI_BASE_URL}/daily-order/"
SCI_JUDGMENTS_PAGE_URL = f"{SCI_BASE_URL}/judgements/"

SUPREME_COURT_SUPPORTED_CATEGORIES: Tuple[str, ...] = (
    "daily_cause_list",
    "supplementary_cause_list",
    "daily_order",
    "final_judgment",
    "other_case_pdf",
)

# Verified Supreme Court bench / court groupings (National level: state_code=None, district_code=None)
SUPREME_COURT_LOCATIONS: List[CourtLocationSpec] = [
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-ALL",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-ALL",
        bench_name="All Benches (Consolidated Cause Lists & Judgments)",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=(
            "Cause Lists on sci.gov.in are publicly accessible by date; Daily Order and "
            "Judgment date-range searches on sci.gov.in may require interactive math/image "
            "CAPTCHA verification depending on portal session state."
        ),
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="ALL",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-CJI",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-CJI",
        bench_name="Chief Justice's Court (Court No. 1)",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="1",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-C2",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-C2",
        bench_name="Supreme Court — Court No. 2",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="2",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-C3",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-C3",
        bench_name="Supreme Court — Court No. 3",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="3",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-C4",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-C4",
        bench_name="Supreme Court — Court No. 4",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="4",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-CHAMBER",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-CHAMBER",
        bench_name="Supreme Court — Chamber Judge Bench",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="CHAMBER",
    ),
    CourtLocationSpec(
        location_key="sc:NATIONAL:SC:SC-REG",
        court_type="supreme_court",
        court_code="SC",
        court_name="Supreme Court of India",
        bench_code="SC-REG",
        bench_name="Supreme Court — Registrar Court (Court No. 21 & 22)",
        source_system="sci_gov_in",
        source_supported=True,
        source_limitation=None,
        requires_manual_verification=False,
        supported_doc_categories=SUPREME_COURT_SUPPORTED_CATEGORIES,
        state_code=None,
        state_iso_code=None,
        state_name=None,
        is_union_territory=False,
        district_code=None,
        district_name=None,
        latitude=28.6223,
        longitude=77.2396,
        portal_court_code="REGISTRAR",
    ),
]

PDF_ANCHOR_REGEX = re.compile(
    r'<a[^>]+href=["\'](?P<url>[^"\']+\.pdf(?:\?[^"\']*)?)["\'][^>]*>(?P<label>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
DIARY_NO_REGEX = re.compile(r"\b(?:Diary\s*No\.?\s*[:\-]?\s*)?(\d{1,6}\s*[/\-]\s*(?:19|20)\d{2})\b", re.IGNORECASE)
COURT_NO_REGEX = re.compile(
    r"\b(Chief\s+Justice'?s?\s+Court|Court\s+No\.?\s*\d{1,2}|Chamber\s+Court|Registrar\s+Court(?:\s+No\.?\s*\d+)?)\b",
    re.IGNORECASE,
)


class SupremeCourtSourceAdapter(BaseCourtSourceAdapter):
    """
    Independent source adapter for the Supreme Court of India (`https://www.sci.gov.in/`).
    """

    court_type = "supreme_court"
    portal_base_url = SCI_BASE_URL

    def get_supported_document_categories(self) -> List[str]:
        return list(SUPREME_COURT_SUPPORTED_CATEGORIES)

    def get_locations_catalog(self) -> List[CourtLocationSpec]:
        return list(SUPREME_COURT_LOCATIONS)

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
                    f"Querying Supreme Court ({location.bench_name}) [{document_category}] for {target_date.isoformat()} ({idx}/{len(dates)})",
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
                errors.append(f"{target_date.isoformat()}: Supreme Court discovery error - {exc}")

        return discovered, sessions_by_date, errors

    def discover_for_single_date(
        self,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> Tuple[List[DiscoveredDocument], Optional[requests.Session], Optional[str]]:
        session = self._new_session()
        action_map = {
            "daily_cause_list": ("get_cause_list", "daily"),
            "supplementary_cause_list": ("get_cause_list", "supplementary"),
            "daily_order": ("get_daily_orders", "order"),
            "final_judgment": ("get_judgements", "judgment"),
            "other_case_pdf": ("get_cause_list", "other"),
        }
        action_name, sub_type = action_map.get(document_category, ("get_cause_list", "daily"))

        params = {
            "action": action_name,
            "listing_date": target_date.strftime("%d-%m-%Y"),
            "from_date": target_date.strftime("%d-%m-%Y"),
            "to_date": target_date.strftime("%d-%m-%Y"),
            "court": location.portal_court_code or "ALL",
            "list_type": sub_type,
        }

        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = session.post(SCI_AJAX_URL, data=params, timeout=self.request_timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code} from sci.gov.in"
                    if attempt < self.max_retries:
                        time.sleep(0.8 * (2 ** (attempt - 1)))
                        continue
                    return [], session, last_error

                raw_text = resp.content.decode("utf-8-sig", errors="replace").strip()
                gate_reason = detect_captcha_or_access_gate(raw_text, resp.status_code)
                if gate_reason:
                    return (
                        [],
                        session,
                        f"sci.gov.in requires manual verification for {document_category}: {gate_reason}",
                    )

                if not raw_text or raw_text == "0":
                    return [], session, None

                docs = self.parse_portal_response(
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

    def parse_portal_response(
        self,
        raw_text: str,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str = "daily_cause_list",
    ) -> List[DiscoveredDocument]:
        """
        Parse Supreme Court portal responses (supports JSON envelopes from admin-ajax.php,
        HTML tables/anchors with `.pdf` links, or pipe/tilde delimited feeds).
        Never treats a cause list as a judgment (`judgment_date` is set ONLY for
        `final_judgment` documents).
        """
        html_or_text = raw_text
        structured_items: List[Dict[str, Any]] = []

        # 1. Check if response is JSON
        if raw_text.startswith("{") or raw_text.startswith("["):
            try:
                parsed_json = json.loads(raw_text)
                if isinstance(parsed_json, dict):
                    if isinstance(parsed_json.get("data"), dict):
                        html_or_text = str(parsed_json["data"].get("results_html") or parsed_json["data"].get("html") or "")
                        if isinstance(parsed_json["data"].get("items"), list):
                            structured_items = parsed_json["data"]["items"]
                    elif isinstance(parsed_json.get("data"), list):
                        structured_items = parsed_json["data"]
                    elif isinstance(parsed_json.get("results_html"), str):
                        html_or_text = parsed_json["results_html"]
                elif isinstance(parsed_json, list):
                    structured_items = parsed_json
            except Exception:
                pass

        docs: List[DiscoveredDocument] = []

        # 2. Process structured JSON items if returned
        for item in structured_items:
            if not isinstance(item, dict):
                continue
            pdf_url = str(item.get("pdf_url") or item.get("url") or item.get("judgment_url") or "").strip()
            if not pdf_url:
                continue
            full_url = self._normalize_sci_url(pdf_url)
            diary_no = str(item.get("diary_number") or item.get("diary_no") or "").strip()
            case_no = str(item.get("case_number") or item.get("case_no") or "").strip()
            court_no = str(item.get("court_number") or item.get("court_no") or location.bench_name).strip()
            judge_raw = str(item.get("judge_names") or item.get("coram") or item.get("honble_judge") or "").strip()
            doc_cat = str(item.get("document_category") or document_category).strip()
            source_ref = str(item.get("reference") or pdf_url).strip()

            docs.append(
                self._create_discovered_doc(
                    location=location,
                    target_date=target_date,
                    document_category=doc_cat,
                    source_ref=source_ref,
                    pdf_url=full_url,
                    court_number=court_no,
                    coram_judge=judge_raw,
                    diary_number=diary_no,
                    case_number_hint=case_no,
                )
            )

        if docs:
            return docs

        # 3. Parse HTML `<a href="...pdf">` links
        for match in PDF_ANCHOR_REGEX.finditer(html_or_text):
            raw_url = match.group("url").strip()
            label_html = match.group("label")
            clean_label = re.sub(r"<[^>]+>", " ", label_html)
            clean_label = re.sub(r"\s+", " ", clean_label).strip()

            # Check surrounding row context (up to 350 chars before link) for diary/judge/court metadata
            ctx_start = max(0, match.start() - 350)
            ctx_end = min(len(html_or_text), match.end() + 250)
            context_snippet = re.sub(r"<[^>]+>", " ", html_or_text[ctx_start:ctx_end])
            context_snippet = re.sub(r"\s+", " ", context_snippet).strip()

            doc_cat = document_category
            if "SUPPLEMENTARY" in (clean_label + " " + context_snippet).upper() and document_category == "daily_cause_list":
                doc_cat = "supplementary_cause_list"

            diary_m = DIARY_NO_REGEX.search(context_snippet)
            diary_no = re.sub(r"\s+", "", diary_m.group(1)).replace("-", "/") if diary_m else ""

            court_m = COURT_NO_REGEX.search(context_snippet)
            court_no = court_m.group(1).strip() if court_m else location.bench_name

            judge_m = re.search(
                r"\b((?:HON'?BLE\s+)?(?:MR\.?\s+|MRS\.?\s+|MS\.?\s+)?(?:CHIEF\s+)?JUSTICE\s+[A-Z][A-Za-z.\s,]{3,90})",
                context_snippet,
                re.IGNORECASE,
            )
            coram_judge = judge_m.group(1).strip() if judge_m else ""

            full_url = self._normalize_sci_url(raw_url)
            docs.append(
                self._create_discovered_doc(
                    location=location,
                    target_date=target_date,
                    document_category=doc_cat,
                    source_ref=raw_url,
                    pdf_url=full_url,
                    court_number=court_no,
                    coram_judge=coram_judge,
                    diary_number=diary_no,
                    case_number_hint=clean_label,
                )
            )

        return docs

    def _create_discovered_doc(
        self,
        location: CourtLocationSpec,
        target_date: date,
        document_category: str,
        source_ref: str,
        pdf_url: str,
        court_number: str,
        coram_judge: str,
        diary_number: str = "",
        case_number_hint: str = "",
    ) -> DiscoveredDocument:
        doc_identity = compute_document_identity(
            court_type="supreme_court",
            state_code=None,
            court_code=location.court_code,
            bench_code=location.bench_code,
            document_category=document_category,
            listing_date=target_date,
            source_reference=source_ref,
        )
        pdf_filename = build_safe_pdf_filename(
            court_type_prefix="SC",
            listing_date=target_date,
            bench_or_est_code=location.bench_code,
            document_category=document_category,
            source_reference=source_ref,
        )

        # Do NOT treat a cause list as a judgment
        order_dt = target_date if document_category == "daily_order" else None
        judgment_dt = target_date if document_category == "final_judgment" else None

        cl_type_label = {
            "daily_cause_list": "Supreme Court Daily Cause List",
            "supplementary_cause_list": "Supreme Court Supplementary Cause List",
            "daily_order": "Supreme Court Daily Order",
            "final_judgment": "Supreme Court Final Judgment",
            "other_case_pdf": "Supreme Court Case Document",
        }.get(document_category, "Supreme Court Document")

        return DiscoveredDocument(
            document_identity=doc_identity,
            court_type="supreme_court",
            court_code=location.court_code,
            court_name=location.court_name,
            bench_code=location.bench_code,
            bench_name=location.bench_name,
            document_category=document_category,
            listing_date=target_date,
            source_reference=source_ref,
            source_url=pdf_url,
            pdf_filename=pdf_filename,
            state_code=None,
            state_name=None,
            district_code=None,
            district_name=None,
            complex_code=None,
            complex_name=None,
            establishment_code=None,
            establishment_name=None,
            cause_list_type=cl_type_label,
            coram_judge_raw=coram_judge,
            court_number=court_number,
            diary_number=diary_number,
            case_number_hint=case_number_hint,
            order_date=order_dt,
            judgment_date=judgment_dt,
            source_portal="https://www.sci.gov.in/",
            source_metadata={
                "portal": "https://www.sci.gov.in/",
                "court_number": court_number,
                "diary_number": diary_number,
                "case_number_hint": case_number_hint,
                "document_category": document_category,
            },
        )

    @staticmethod
    def _normalize_sci_url(raw_url: str) -> str:
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            return raw_url
        return urllib.parse.urljoin(f"{SCI_BASE_URL}/", raw_url.lstrip("/"))

    def resolve_download_url(self, doc: DiscoveredDocument) -> str:
        return self._normalize_sci_url(doc.source_url)

    def extract_source_metadata(self, doc: DiscoveredDocument) -> Dict[str, Any]:
        return {
            "source_portal": "https://www.sci.gov.in/",
            "court_type": "supreme_court",
            "document_category": doc.document_category,
            "court_number": doc.court_number,
            "diary_number": doc.diary_number,
            "coram_judge_raw": doc.coram_judge_raw,
        }


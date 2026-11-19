"""
Base Source Adapter & Unified Domain Models for All-India Court Coverage
(`deployment/pdf_intelligence/sources/base.py`).

Defines the common contracts for:
- Supreme Court of India (`https://www.sci.gov.in/`)
- High Courts & Benches (`https://hcservices.ecourts.gov.in/`)
- District & Subordinate Courts (`https://services.ecourts.gov.in/`)
"""

from __future__ import annotations

import hashlib
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

MAX_DATE_RANGE_DAYS = 31

COURT_CATEGORIES = {
    "supreme_court": "Supreme Court of India",
    "high_court": "High Courts",
    "district_court": "District & Subordinate Courts",
}

DOCUMENT_CATEGORIES = {
    "daily_cause_list": "Daily Cause Lists",
    "supplementary_cause_list": "Supplementary Cause Lists",
    "daily_order": "Daily Orders",
    "final_judgment": "Final Judgments",
    "other_case_pdf": "Other Official Case PDFs",
}

STORAGE_NAMESPACES = {
    "supreme_court": "pdf-intelligence/supreme-court",
    "high_court": "pdf-intelligence/high-court",
    "district_court": "pdf-intelligence/district-court",
}

DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,text/plain,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
}


class PortalAccessLimitation(Exception):
    """
    Raised or reported when an official court portal restricts automated access
    (e.g., mandatory CAPTCHA challenge, anti-bot Turnstile gate, or unsupported
    document feed on that portal).
    """

    def __init__(
        self,
        message: str,
        portal_url: str,
        court_type: str,
        document_category: str = "all",
        requires_manual_verification: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.portal_url = portal_url
        self.court_type = court_type
        self.document_category = document_category
        self.requires_manual_verification = requires_manual_verification

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "portal_url": self.portal_url,
            "court_type": self.court_type,
            "document_category": self.document_category,
            "requires_manual_verification": self.requires_manual_verification,
        }


@dataclass(frozen=True)
class CourtLocationSpec:
    """
    Normalized geographic and court hierarchy node.
    Note: `state_*` and `district_*` are `None` for the national-level Supreme Court.
    `complex_*` and `establishment_*` are populated for District & Subordinate Courts.
    """

    location_key: str
    court_type: str  # 'supreme_court', 'high_court', 'district_court'
    court_code: str
    court_name: str
    bench_code: str
    bench_name: str
    source_system: str
    source_supported: bool
    source_limitation: Optional[str] = None
    requires_manual_verification: bool = False
    supported_doc_categories: Tuple[str, ...] = ("daily_cause_list", "supplementary_cause_list")
    # Geographic fields (None for Supreme Court)
    state_code: Optional[str] = None
    state_iso_code: Optional[str] = None
    state_name: Optional[str] = None
    is_union_territory: bool = False
    district_code: Optional[str] = None
    district_name: Optional[str] = None
    # District Court specific hierarchy fields
    complex_code: Optional[str] = None
    complex_name: Optional[str] = None
    establishment_code: Optional[str] = None
    establishment_name: Optional[str] = None
    # Coordinates (optional for map pins)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Portal-specific parameters
    portal_state_code: Optional[str] = None
    portal_dist_code: Optional[str] = None
    portal_court_code: Optional[str] = None
    portal_complex_code: Optional[str] = None
    portal_est_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["supported_doc_categories"] = list(self.supported_doc_categories)
        return d


@dataclass
class DiscoveredDocument:
    """
    Represents an official PDF document discovered by one of the three court adapters.
    """

    document_identity: str
    court_type: str  # 'supreme_court', 'high_court', 'district_court'
    court_code: str
    court_name: str
    bench_code: str
    bench_name: str
    document_category: str  # 'daily_cause_list', 'supplementary_cause_list', 'daily_order', 'final_judgment', 'other_case_pdf'
    listing_date: date
    source_reference: str
    source_url: str
    pdf_filename: str
    # Nullable geographic fields (None for Supreme Court)
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    district_code: Optional[str] = None
    district_name: Optional[str] = None
    # Nullable District Court hierarchy fields
    complex_code: Optional[str] = None
    complex_name: Optional[str] = None
    establishment_code: Optional[str] = None
    establishment_name: Optional[str] = None
    # Document-level judicial metadata
    cause_list_type: str = ""
    coram_judge_raw: str = ""
    court_number: str = ""
    diary_number: str = ""
    case_number_hint: str = ""
    order_date: Optional[date] = None
    judgment_date: Optional[date] = None
    bench_id: str = ""
    cause_list_id: str = ""
    eliminated: bool = False
    source_portal: str = ""
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    # Portal session replay parameters
    ecourts_hc_state_code: str = ""
    ecourts_hc_dist_code: str = "1"
    ecourts_hc_court_code: str = "1"


@dataclass
class SourceDiscoveryRequest:
    location: CourtLocationSpec
    start_date: date
    end_date: date
    document_category: str = "daily_cause_list"  # or 'all'
    manual_verification_token: Optional[str] = None


@dataclass
class SourceDiscoveryResult:
    court_type: str
    portal_url: str
    documents: List[DiscoveredDocument] = field(default_factory=list)
    sessions_by_date: Dict[date, requests.Session] = field(default_factory=dict)
    warnings_and_errors: List[str] = field(default_factory=list)
    limitations: List[PortalAccessLimitation] = field(default_factory=list)
    requires_manual_verification: bool = False


def generate_inclusive_date_range(start_date: date | str, end_date: date | str) -> List[date]:
    """Return every calendar date from start_date through end_date, inclusive."""
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date.strip())
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date.strip())

    if end_date < start_date:
        raise ValueError(
            f"end_date ({end_date.isoformat()}) cannot be earlier than start_date ({start_date.isoformat()})"
        )

    span_days = (end_date - start_date).days + 1
    if span_days > MAX_DATE_RANGE_DAYS:
        raise ValueError(
            f"Requested date range spans {span_days} days, exceeding the {MAX_DATE_RANGE_DAYS}-day "
            "per-job portal safety limit. Please select a range of 31 days or fewer."
        )

    return [start_date + timedelta(days=offset) for offset in range(span_days)]


def compute_document_identity(
    court_type: str,
    state_code: Optional[str],
    court_code: str,
    bench_code: str,
    document_category: str,
    listing_date: date,
    source_reference: str,
    complex_code: Optional[str] = None,
    establishment_code: Optional[str] = None,
) -> str:
    """
    Create a deterministic, stable identity across runs for any Supreme Court,
    High Court, or District Court PDF document.
    """
    ref_digest = hashlib.sha256(source_reference.strip().encode("utf-8")).hexdigest()[:24]
    date_str = listing_date.isoformat() if hasattr(listing_date, "isoformat") else str(listing_date)
    st_part = state_code or "NAT"
    cx_part = complex_code or "-"
    est_part = establishment_code or "-"
    return f"pi:{court_type}:{st_part}:{court_code}:{bench_code}:{cx_part}:{est_part}:{document_category}:{date_str}:{ref_digest}"


def build_safe_pdf_filename(
    court_type_prefix: str,
    listing_date: date,
    bench_or_est_code: str,
    document_category: str,
    source_reference: str,
) -> str:
    """Build a safe, descriptive PDF filename."""
    d_str = listing_date.strftime("%Y%m%d") if hasattr(listing_date, "strftime") else str(listing_date).replace("-", "")
    cleaned_ref = "".join(ch for ch in source_reference if ch.isalnum() or ch in "._-")
    if not cleaned_ref:
        cleaned_ref = hashlib.sha256(source_reference.encode("utf-8")).hexdigest()[:16]
    cleaned_ref = cleaned_ref[:44]
    cat_short = {
        "daily_cause_list": "DCL",
        "supplementary_cause_list": "SCL",
        "daily_order": "ORD",
        "final_judgment": "JDG",
        "other_case_pdf": "DOC",
    }.get(document_category, "PDF")
    safe_bench = "".join(ch for ch in str(bench_or_est_code) if ch.isalnum() or ch in "-_")[:16] or "B1"
    return f"PI_{court_type_prefix}_{cat_short}_{d_str}_{safe_bench}_{cleaned_ref}.pdf"


def detect_captcha_or_access_gate(text: str, status_code: int = 200) -> Optional[str]:
    """
    Inspect an HTTP response from a court portal for CAPTCHA challenges or anti-bot
    gates. Never attempts to solve or bypass them; returns a diagnostic reason.
    """
    if status_code == 403:
        return "Portal returned HTTP 403 Forbidden (access control or anti-bot firewall)."
    upper = (text or "")[:4000].upper()
    if "INVALID CAPTCHA" in upper or "ENTER CAPTCHA" in upper or "CAUSE_LIST_CAPTCHA_CODE" in upper:
        return "Official portal requires interactive CAPTCHA verification before serving documents."
    if "SECURIMAGE_SHOW.PHP" in upper and "PDF" not in upper:
        return "Official portal form requires a Securimage session CAPTCHA challenge."
    if "SIWP_CAPTCHA" in upper or "CF-TURNSTILE" in upper or "G-RECAPTCHA" in upper or "HCAPTCHA" in upper:
        return "Official portal requires human CAPTCHA verification (Turnstile / reCAPTCHA / math CAPTCHA)."
    return None


class BaseCourtSourceAdapter(ABC):
    """
    Abstract base class for the three court source adapters (`SupremeCourtSourceAdapter`,
    `HighCourtSourceAdapter`, `DistrictCourtSourceAdapter`).
    """

    court_type: str = ""
    portal_base_url: str = ""

    def __init__(
        self,
        rate_limit_seconds: float = 0.35,
        max_retries: int = 3,
        request_timeout: int = 18,
        session_factory: Optional[Callable[[], requests.Session]] = None,
    ):
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))
        self.max_retries = max(1, int(max_retries))
        self.request_timeout = max(5, int(request_timeout))
        self._session_factory = session_factory or requests.Session
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        if self.rate_limit_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_ts = time.monotonic()

    def _new_session(self) -> requests.Session:
        sess = self._session_factory()
        sess.headers.update(DEFAULT_BROWSER_HEADERS)
        return sess

    @abstractmethod
    def get_supported_document_categories(self) -> List[str]:
        """Return document category keys supported by this source adapter."""

    @abstractmethod
    def get_locations_catalog(self) -> List[CourtLocationSpec]:
        """Return verified court hierarchy locations for this court tier."""

    @abstractmethod
    def discover_for_date_range(
        self,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Tuple[List[DiscoveredDocument], Dict[date, requests.Session], List[str]]:
        """
        Discover PDF documents for `location` over `[start_date, end_date]` inclusive.
        """

    @abstractmethod
    def resolve_download_url(self, doc: DiscoveredDocument) -> str:
        """Resolve the official PDF download URL for a discovered document."""

    @abstractmethod
    def extract_source_metadata(self, doc: DiscoveredDocument) -> Dict[str, Any]:
        """Return portal-specific metadata dictionary for persistence."""


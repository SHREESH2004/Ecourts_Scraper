"""
Independent PDF Downloader, Validator, SHA-256 Hasher, and Namespace Storage Manager.

Uses three independent object-key namespaces in private Supabase Storage:
- Supreme Court:  `pdf-intelligence/supreme-court/...`
- High Courts:    `pdf-intelligence/high-court/...`
- District Court: `pdf-intelligence/district-court/...`
With isolated local fallback storage under `deployment/downloaded_pdfs/pdf_intelligence/`
when cloud storage is not configured in local/test environments.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests

from .sources.base import (
    DEFAULT_BROWSER_HEADERS as DEFAULT_HEADERS,
    STORAGE_NAMESPACES,
    DiscoveredDocument,
)
from .sources.high_court import (
    ECOURTS_HC_BASE_URL,
    ECOURTS_HC_CAUSELIST_QUERY_URL,
)

logger = logging.getLogger(__name__)

STORAGE_NAMESPACE = "pdf-intelligence"

DEPLOYMENT_DIR = Path(__file__).resolve().parents[2]
LOCAL_FALLBACK_ROOT = DEPLOYMENT_DIR / "downloaded_pdfs" / "pdf_intelligence"

def _local_fallback_path_for_key(object_key: str) -> Path:
    """Use a compact local filename so Windows path limits do not break saves."""
    parts = object_key.split("/")
    if not parts or not parts[-1]:
        raise ValueError("Invalid PDF storage object key")
    digest_prefix = parts[-1].split("_", 1)[0]
    local_name = f"{digest_prefix}.pdf"
    return LOCAL_FALLBACK_ROOT / Path(*parts[:-1]) / local_name


def _get_storage_service():
    """
    Import storage_service lazily so environments without botocore installed
    still function cleanly when Supabase S3 is not configured.
    """
    try:
        import storage_service
        return storage_service
    except ImportError:
        return None


@dataclass
class DownloadResult:
    success: bool
    status: str  # 'downloaded', 'already_in_storage', 'invalid_pdf', 'failed'
    pdf_bytes: Optional[bytes] = None
    content_sha256: Optional[str] = None
    file_size_bytes: int = 0
    storage_namespace: str = STORAGE_NAMESPACE
    storage_object_key: Optional[str] = None
    local_fallback_path: Optional[str] = None
    error_message: Optional[str] = None


def validate_and_normalize_pdf_bytes(raw_bytes: bytes) -> Tuple[bool, Optional[bytes], Optional[str]]:
    """
    Validate that downloaded bytes represent a genuine PDF document.
    Strips leading BOM/whitespace before `%PDF-` header if present.
    """
    if not raw_bytes:
        return False, None, "Empty response body"

    pdf_start = raw_bytes.find(b"%PDF-")
    if pdf_start == -1 or pdf_start > 1024:
        preview = raw_bytes[:160].decode("utf-8", errors="replace").strip()
        return False, None, f"Missing %PDF- header (received: {preview!r})"

    normalized = raw_bytes[pdf_start:]
    if len(normalized) < 64:
        return False, None, f"PDF payload too small ({len(normalized)} bytes)"

    if b"%%EOF" not in normalized[-2048:] and b"endobj" not in normalized:
        return False, None, "Corrupted PDF payload (missing %%EOF and object markers)"

    return True, normalized, None


def compute_sha256(content: bytes) -> str:
    """Compute hex SHA-256 digest of PDF content."""
    return hashlib.sha256(content).hexdigest()


def get_namespace_for_court_type(court_type: str) -> str:
    """Return the independent storage namespace for Supreme, High, or District Court."""
    return STORAGE_NAMESPACES.get((court_type or "high_court").strip().lower(), "pdf-intelligence/high-court")


def build_storage_object_key(
    doc: DiscoveredDocument,
    content_sha256: str,
    namespace: Optional[str] = None,
) -> str:
    """
    Construct an independent object-key path inside the private Supabase Storage bucket
    for Supreme Court, High Court, or District Court documents.
    """
    ctype = (doc.court_type or "high_court").strip().lower()
    ns = namespace or get_namespace_for_court_type(ctype)
    date_part = doc.listing_date.isoformat() if hasattr(doc.listing_date, "isoformat") else str(doc.listing_date)
    sha_prefix = content_sha256[:16]
    doc_cat = "".join(c for c in str(getattr(doc, "document_category", "daily_cause_list") or "daily_cause_list") if c.isalnum() or c in "-_")

    def _clean_seg(val: Optional[str], fallback: str) -> str:
        s = "".join(c for c in str(val or "") if c.isalnum() or c in "-_")
        return s or fallback

    if ctype == "supreme_court":
        safe_bench = _clean_seg(doc.bench_code, "SC-ALL")
        return f"{ns}/{safe_bench}/{doc_cat}/{date_part}/{sha_prefix}_{doc.pdf_filename}"

    if ctype == "district_court":
        safe_state = _clean_seg(doc.state_code, "state")
        safe_dist = _clean_seg(doc.district_code, "district")
        safe_complex = _clean_seg(getattr(doc, "complex_code", None) or doc.court_code, "complex")
        safe_est = _clean_seg(getattr(doc, "establishment_code", None) or doc.bench_code, "est")
        return f"{ns}/{safe_state}/{safe_dist}/{safe_complex}/{safe_est}/{doc_cat}/{date_part}/{sha_prefix}_{doc.pdf_filename}"

    # Default: high_court
    safe_state = _clean_seg(doc.state_code, "state")
    safe_court = _clean_seg(doc.court_code, "court")
    safe_bench = _clean_seg(doc.bench_code, "bench")
    return f"{ns}/{safe_state}/{safe_court}/{safe_bench}/{doc_cat}/{date_part}/{sha_prefix}_{doc.pdf_filename}"


class PDFDownloader:
    """
    Independent PDF downloader with rate limiting, retries, session refresh,
    SHA-256 content hashing, and private Supabase Storage upload under the
    tier-specific `pdf-intelligence/{tier}/` namespace.
    """

    def __init__(
        self,
        rate_limit_seconds: float = 0.25,
        max_retries: int = 3,
        request_timeout: int = 25,
        session_factory: Optional[Callable[[], requests.Session]] = None,
        allow_local_fallback: bool = True,
    ):
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))
        self.max_retries = max(1, int(max_retries))
        self.request_timeout = max(5, int(request_timeout))
        self._session_factory = session_factory or requests.Session
        self.allow_local_fallback = allow_local_fallback
        self._last_download_ts = 0.0

    def _throttle(self) -> None:
        if self.rate_limit_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_download_ts
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_download_ts = time.monotonic()

    def _refresh_court_session(self, session: requests.Session, doc: DiscoveredDocument) -> None:
        """
        Re-establish the eCourts High Court session cookie for the document's date
        when the portal returns 'CauseList is not available'.
        """
        if doc.court_type != "high_court":
            return
        qry_params = {
            "state_code": doc.ecourts_hc_state_code or doc.state_code or "1",
            "dist_code": doc.ecourts_hc_dist_code or "1",
            "court_code": doc.ecourts_hc_court_code or doc.bench_code or "1",
            "causelist_dt": doc.listing_date.strftime("%d-%m-%Y"),
            "action_code": "pulishedCauselist",
        }
        session.post(ECOURTS_HC_CAUSELIST_QUERY_URL, data=qry_params, timeout=self.request_timeout)

    @staticmethod
    def _build_portal_headers(doc: DiscoveredDocument) -> dict[str, str]:
        ctype = (doc.court_type or "high_court").strip().lower()
        if ctype == "supreme_court":
            return {
                "Referer": "https://www.sci.gov.in/cause-list/",
                "Origin": "https://www.sci.gov.in",
                "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
            }
        if ctype == "district_court":
            return {
                "Referer": "https://services.ecourts.gov.in/ecourtindia_v6/?p=cause_list/index",
                "Origin": "https://services.ecourts.gov.in",
                "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
            }
        hc_state = doc.ecourts_hc_state_code or doc.state_code or "1"
        hc_dist = doc.ecourts_hc_dist_code or "1"
        hc_court = doc.ecourts_hc_court_code or doc.bench_code or "1"
        return {
            "Referer": (
                f"{ECOURTS_HC_BASE_URL}/cases/highcourt_causelist.php"
                f"?state_cd={hc_state}&dist_cd={hc_dist}&court_code={hc_court}"
            ),
            "Origin": "https://hcservices.ecourts.gov.in",
            "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        }

    def download_and_store(
        self,
        doc: DiscoveredDocument,
        source_session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        """
        Download a PDF from the court source, validate its content, compute SHA-256,
        and store it in the private Supabase Storage bucket under the tier-specific
        `pdf-intelligence/{tier}/` namespace.
        """
        session = self._session_factory()
        session.headers.update(DEFAULT_HEADERS)
        if source_session is not None:
            session.headers.update(source_session.headers)
            session.cookies.update(source_session.cookies)

        headers = self._build_portal_headers(doc)
        last_error = "Unknown download failure"
        validated_bytes: Optional[bytes] = None
        tier_namespace = get_namespace_for_court_type(doc.court_type)

        try:
            for attempt in range(1, self.max_retries + 1):
                self._throttle()
                try:
                    resp = session.get(doc.source_url, headers=headers, timeout=self.request_timeout)

                    if resp.status_code == 200:
                        is_valid, normalized, err = validate_and_normalize_pdf_bytes(resp.content)
                        if is_valid and normalized is not None:
                            validated_bytes = normalized
                            break

                        last_error = err or "Response is not a valid PDF"
                        if attempt < self.max_retries and (
                            b"CauseList is not available" in resp.content or b"%PDF" not in resp.content
                        ):
                            try:
                                self._refresh_court_session(session, doc)
                            except Exception:
                                pass
                            time.sleep(0.5 * attempt)
                            continue
                    elif resp.status_code in (429, 500, 502, 503, 504):
                        last_error = f"HTTP {resp.status_code} during PDF download"
                        if attempt < self.max_retries:
                            time.sleep(0.8 * (2 ** (attempt - 1)))
                            continue
                    else:
                        last_error = f"HTTP {resp.status_code} during PDF download"
                        break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt < self.max_retries:
                        time.sleep(0.8 * (2 ** (attempt - 1)))
                        continue
        finally:
            session.close()

        if validated_bytes is None:
            return DownloadResult(
                success=False,
                status="failed",
                storage_namespace=tier_namespace,
                error_message=last_error,
            )

        sha256_hex = compute_sha256(validated_bytes)
        object_key = build_storage_object_key(doc, sha256_hex, namespace=tier_namespace)
        storage_mod = _get_storage_service()

        # 1. Store in configured private Supabase Storage bucket under tier-specific namespace
        if storage_mod is not None and storage_mod.is_storage_configured():
            try:
                existing_info = storage_mod.get_pdf_object_info(object_key)
                if not existing_info:
                    storage_mod.upload_pdf_bytes(validated_bytes, object_key)
                return DownloadResult(
                    success=True,
                    status="downloaded",
                    pdf_bytes=validated_bytes,
                    content_sha256=sha256_hex,
                    file_size_bytes=len(validated_bytes),
                    storage_namespace=tier_namespace,
                    storage_object_key=object_key,
                    local_fallback_path=None,
                )
            except Exception as exc:
                if not self.allow_local_fallback:
                    return DownloadResult(
                        success=False,
                        status="failed",
                        content_sha256=sha256_hex,
                        file_size_bytes=len(validated_bytes),
                        storage_namespace=tier_namespace,
                        error_message=f"Supabase Storage upload failed: {exc}",
                    )
                logger.warning("Supabase Storage upload failed (%s); using isolated local fallback.", exc)

        # 2. Local fallback under deployment/downloaded_pdfs/pdf_intelligence/... when S3 is unconfigured
        if self.allow_local_fallback:
            try:
                target_path = _local_fallback_path_for_key(object_key)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(validated_bytes)
                rel_to_deployment = str(target_path.relative_to(DEPLOYMENT_DIR)).replace("\\", "/")
                return DownloadResult(
                    success=True,
                    status="downloaded",
                    pdf_bytes=validated_bytes,
                    content_sha256=sha256_hex,
                    file_size_bytes=len(validated_bytes),
                    storage_namespace=tier_namespace,
                    storage_object_key=object_key,
                    local_fallback_path=rel_to_deployment,
                )
            except Exception as exc:
                return DownloadResult(
                    success=False,
                    status="failed",
                    content_sha256=sha256_hex,
                    file_size_bytes=len(validated_bytes),
                    storage_namespace=tier_namespace,
                    error_message=f"Local storage fallback failed: {exc}",
                )

        return DownloadResult(
            success=False,
            status="failed",
            content_sha256=sha256_hex,
            file_size_bytes=len(validated_bytes),
            storage_namespace=tier_namespace,
            error_message="Supabase PDF storage is not configured and local fallback is disabled.",
        )

    @staticmethod
    def load_stored_pdf_bytes(
        storage_object_key: Optional[str],
        local_fallback_path: Optional[str],
    ) -> Optional[bytes]:
        if local_fallback_path:
            candidate = Path(local_fallback_path) if os.path.isabs(local_fallback_path) else (DEPLOYMENT_DIR / local_fallback_path)
            if candidate.is_file():
                return candidate.read_bytes()

        if storage_object_key:
            alt_local = _local_fallback_path_for_key(storage_object_key)
            if alt_local.is_file():
                return alt_local.read_bytes()

            storage_mod = _get_storage_service()
            if storage_mod is not None and storage_mod.is_storage_configured():
                try:
                    url = storage_mod.create_pdf_download_url(
                        storage_object_key,
                        os.path.basename(storage_object_key),
                        download=False,
                    )
                    if url:
                        resp = requests.get(url, timeout=20)
                        if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                            return resp.content
                except Exception as exc:
                    logger.warning("Could not fetch stored PDF from Supabase Storage: %s", exc)

        return None

    @staticmethod
    def resolve_download_url_or_path(
        storage_object_key: Optional[str],
        local_fallback_path: Optional[str],
        pdf_filename: str,
        download: bool = False,
    ) -> Tuple[Optional[str], Optional[Path]]:
        storage_mod = _get_storage_service()
        if storage_object_key and storage_mod is not None and storage_mod.is_storage_configured():
            try:
                if storage_mod.get_pdf_object_info(storage_object_key):
                    url = storage_mod.create_pdf_download_url(
                        storage_object_key,
                        pdf_filename,
                        download=download,
                    )
                    if url:
                        return url, None
            except Exception as exc:
                logger.warning("Supabase Storage presigned URL check failed: %s", exc)

        if local_fallback_path:
            candidate = (Path(local_fallback_path) if os.path.isabs(local_fallback_path) else (DEPLOYMENT_DIR / local_fallback_path)).resolve()
            if candidate.is_file():
                return None, candidate

        if storage_object_key:
            alt_local = _local_fallback_path_for_key(storage_object_key).resolve()
            if alt_local.is_file() and str(alt_local).startswith(str(LOCAL_FALLBACK_ROOT.resolve())):
                return None, alt_local

        return None, None


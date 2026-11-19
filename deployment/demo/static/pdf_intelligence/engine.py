"""
Independent PDF Scraping, Extraction, and Case Analysis Engine (`engine.py`).

Routes discovery to the three independent court source adapters:
1. `SupremeCourtSourceAdapter` (`https://www.sci.gov.in/`)
2. `HighCourtSourceAdapter` (`https://hcservices.ecourts.gov.in/`)
3. `DistrictCourtSourceAdapter` (`https://services.ecourts.gov.in/`)

Feeds all discovered PDFs through the unified validation, SHA-256 hashing,
tier-namespaced storage, text/OCR extraction, multi-case parsing, and daily
analytics pipeline. Never imports or invokes `deployment/scraper/1.py`.
"""

from __future__ import annotations

import argparse
import inspect
import logging
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .analytics import PDFAnalyticsService
from .case_parser import CaseRecordParser
from .downloader import PDFDownloader
from .pdf_extractor import PDFTextExtractor
from .repository import PDFIntelligenceRepository
from .source_discovery import (
    CourtLocationSpec,
    DiscoveredDocument,
    find_location_spec,
    generate_inclusive_date_range,
    get_source_adapter,
)
from .sources.base import BaseCourtSourceAdapter

logger = logging.getLogger(__name__)


class PDFIntelligenceEngine:
    """
    Coordinates end-to-end discovery across Supreme Court, High Courts, and
    District Courts, deduplicated PDF downloading, SHA-256 hashing, text/OCR
    extraction, multi-case parsing, and daily analytics.
    """

    def __init__(
        self,
        repository: Optional[PDFIntelligenceRepository] = None,
        discovery_adapter: Optional[BaseCourtSourceAdapter] = None,
        adapters_by_tier: Optional[Dict[str, BaseCourtSourceAdapter]] = None,
        downloader: Optional[PDFDownloader] = None,
        extractor: Optional[PDFTextExtractor] = None,
        case_parser: Optional[CaseRecordParser] = None,
    ):
        self.repo = repository or PDFIntelligenceRepository()
        self._default_discovery = discovery_adapter
        self._adapters_by_tier = adapters_by_tier or {}
        self.downloader = downloader or PDFDownloader()
        self.extractor = extractor or PDFTextExtractor()
        self.parser = case_parser or CaseRecordParser()
        self.analytics = PDFAnalyticsService(self.repo)

    def _get_adapter_for_location(self, location: CourtLocationSpec) -> BaseCourtSourceAdapter:
        if self._default_discovery is not None:
            return self._default_discovery
        ctype = (location.court_type or "high_court").strip().lower()
        if ctype in self._adapters_by_tier:
            return self._adapters_by_tier[ctype]
        adapter = get_source_adapter(ctype)
        self._adapters_by_tier[ctype] = adapter
        return adapter

    def run_scrape_pipeline(
        self,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
        job_uid: Optional[str] = None,
        scrape_job_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a complete date-range scrape and extraction run for `location`
        over the inclusive range `[start_date, end_date]`.
        """
        self.repo.ensure_initialized()

        if not location.source_supported:
            limitation = location.source_limitation or (
                f"Source {location.source_system} does not support automated scraping."
            )
            if job_uid:
                self.repo.update_scrape_job(
                    job_uid,
                    status="failed",
                    current_step="Blocked by source limitation",
                    limitation_notice=limitation,
                    error_summary=limitation,
                    finished_at=datetime.now(timezone.utc),
                    log_message=f"SOURCE LIMITATION: {limitation}",
                    log_level="ERROR",
                )
            raise ValueError(limitation)

        dates = generate_inclusive_date_range(start_date, end_date)
        location_id = self.repo.get_location_id(location.location_key)
        adapter = self._get_adapter_for_location(location)

        scope_label = (
            f"Supreme Court -> {location.bench_name}"
            if location.court_type == "supreme_court"
            else (
                f"{location.state_name} -> {location.district_name} -> {location.complex_name} -> {location.establishment_name}"
                if location.court_type == "district_court"
                else f"{location.state_name} -> {location.district_name} -> {location.bench_name}"
            )
        )

        if job_uid:
            self.repo.update_scrape_job(
                job_uid,
                status="running",
                started_at=datetime.now(timezone.utc),
                progress_pct=5,
                current_step=f"Discovering {document_category} PDFs across {len(dates)} day(s)",
                log_message=(
                    f"Starting independent discovery for {scope_label} [{document_category}] "
                    f"({start_date.isoformat()} to {end_date.isoformat()}, {len(dates)} day(s))."
                ),
            )

        def on_discovery_progress(msg: str, idx: int, total: int) -> None:
            if job_uid:
                pct = min(30, 5 + int((idx / max(1, total)) * 25))
                self.repo.update_scrape_job(
                    job_uid,
                    progress_pct=pct,
                    current_step=msg,
                    log_message=msg,
                )

        # Support adapters with or without `document_category` parameter
        sig = inspect.signature(adapter.discover_for_date_range)
        if "document_category" in sig.parameters:
            discovered_docs, sessions_by_date, discovery_errors = adapter.discover_for_date_range(
                location=location,
                start_date=start_date,
                end_date=end_date,
                document_category=document_category,
                progress_callback=on_discovery_progress,
            )
        else:
            discovered_docs, sessions_by_date, discovery_errors = adapter.discover_for_date_range(
                location=location,
                start_date=start_date,
                end_date=end_date,
                progress_callback=on_discovery_progress,
            )

        discovered_count = len(discovered_docs)
        downloaded_count = 0
        skipped_duplicate_count = 0
        extracted_doc_count = 0
        case_records_count = 0
        failed_count = 0
        run_errors: List[str] = list(discovery_errors)

        if job_uid:
            self.repo.update_scrape_job(
                job_uid,
                discovered_count=discovered_count,
                progress_pct=35 if discovered_count > 0 else 95,
                current_step=f"Discovered {discovered_count} PDF document(s)",
                log_message=f"Discovery finished: {discovered_count} unique PDF(s) found across {len(dates)} day(s).",
            )

        try:
            for idx, disc_doc in enumerate(discovered_docs, start=1):
                doc_record, already_processed = self.repo.register_discovered_document(
                    disc_doc,
                    scrape_job_id=scrape_job_id,
                    location_id=location_id,
                )
                doc_id = int(doc_record["id"])

                if already_processed:
                    skipped_duplicate_count += 1
                    if job_uid:
                        pct = 35 + int((idx / max(1, discovered_count)) * 60)
                        self.repo.update_scrape_job(
                            job_uid,
                            skipped_duplicate_count=skipped_duplicate_count,
                            progress_pct=min(95, pct),
                            current_step=f"Skipped already-processed PDF ({idx}/{discovered_count})",
                            log_message=f"Skipped duplicate document {disc_doc.pdf_filename} (identity already processed).",
                        )
                    continue

                source_session = sessions_by_date.get(disc_doc.listing_date)
                dl_result = self.downloader.download_and_store(disc_doc, source_session=source_session)

                if not dl_result.success or dl_result.pdf_bytes is None:
                    failed_count += 1
                    err_msg = dl_result.error_message or "PDF download failed"
                    run_errors.append(f"{disc_doc.pdf_filename}: {err_msg}")
                    self.repo.record_download_outcome(
                        document_id=doc_id,
                        download_status="failed",
                        storage_namespace=dl_result.storage_namespace,
                        error_message=err_msg,
                    )
                    if job_uid:
                        self.repo.update_scrape_job(
                            job_uid,
                            failed_count=failed_count,
                            log_message=f"Download failed for {disc_doc.pdf_filename}: {err_msg}",
                            log_level="ERROR",
                        )
                    continue

                dup_hash_doc = (
                    self.repo.get_processed_document_by_sha256(dl_result.content_sha256, exclude_doc_id=doc_id)
                    if dl_result.content_sha256
                    else None
                )
                dl_status = "duplicate_hash" if dup_hash_doc else "downloaded"
                downloaded_count += 1

                self.repo.record_download_outcome(
                    document_id=doc_id,
                    download_status=dl_status,
                    content_sha256=dl_result.content_sha256,
                    file_size_bytes=dl_result.file_size_bytes,
                    storage_namespace=dl_result.storage_namespace,
                    storage_object_key=dl_result.storage_object_key,
                    local_fallback_path=dl_result.local_fallback_path,
                    error_message=None,
                )

                extraction_res = self.extractor.extract_from_bytes(dl_result.pdf_bytes)
                if not extraction_res.success:
                    failed_count += 1
                    ext_err = extraction_res.error_message or "Text/OCR extraction failed"
                    run_errors.append(f"{disc_doc.pdf_filename}: {ext_err}")
                    self.repo.save_extraction_and_cases(
                        document_id=doc_id,
                        scrape_job_id=scrape_job_id,
                        extraction=extraction_res,
                        parsed_cases=[],
                    )
                    if job_uid:
                        self.repo.update_scrape_job(
                            job_uid,
                            downloaded_count=downloaded_count,
                            failed_count=failed_count,
                            log_message=f"Extraction failed for {disc_doc.pdf_filename}: {ext_err}",
                            log_level="ERROR",
                        )
                    continue

                parsed_cases = self.parser.parse_document(
                    extraction=extraction_res,
                    default_listing_date=disc_doc.listing_date,
                    fallback_judge=disc_doc.coram_judge_raw,
                    cause_list_type=disc_doc.cause_list_type,
                    document_category=getattr(disc_doc, "document_category", document_category) or document_category,
                    fallback_court_room=getattr(disc_doc, "court_number", "") or "",
                    fallback_diary_number=getattr(disc_doc, "diary_number", "") or "",
                )

                self.repo.save_extraction_and_cases(
                    document_id=doc_id,
                    scrape_job_id=scrape_job_id,
                    extraction=extraction_res,
                    parsed_cases=parsed_cases,
                )

                extracted_doc_count += 1
                case_records_count += len(parsed_cases)

                if job_uid:
                    pct = 35 + int((idx / max(1, discovered_count)) * 60)
                    self.repo.update_scrape_job(
                        job_uid,
                        downloaded_count=downloaded_count,
                        skipped_duplicate_count=skipped_duplicate_count,
                        extracted_doc_count=extracted_doc_count,
                        case_records_count=case_records_count,
                        failed_count=failed_count,
                        progress_pct=min(95, pct),
                        current_step=f"Processed {idx}/{discovered_count} PDFs ({case_records_count} cases)",
                        log_message=(
                            f"Processed {disc_doc.pdf_filename} [{extraction_res.extraction_method}]: "
                            f"{len(parsed_cases)} case record(s) extracted."
                        ),
                    )
        finally:
            for sess in sessions_by_date.values():
                try:
                    sess.close()
                except Exception:
                    pass

        self.analytics.refresh_daily_analytics(
            court_type=location.court_type,
            state_code=location.state_code,
            bench_code=location.bench_code,
            target_dates=dates,
        )

        final_status = "completed"
        if failed_count > 0 and extracted_doc_count == 0 and skipped_duplicate_count == 0:
            final_status = "failed"
        elif failed_count > 0:
            final_status = "completed_with_errors"

        err_summary = "; ".join(run_errors[:5]) if run_errors else None
        limitation_notice = None
        if any("CAPTCHA" in e.upper() or "MANUAL VERIFICATION" in e.upper() for e in run_errors):
            limitation_notice = err_summary

        if job_uid:
            self.repo.update_scrape_job(
                job_uid,
                status=final_status,
                discovered_count=discovered_count,
                downloaded_count=downloaded_count,
                skipped_duplicate_count=skipped_duplicate_count,
                extracted_doc_count=extracted_doc_count,
                case_records_count=case_records_count,
                failed_count=failed_count,
                progress_pct=100,
                current_step="Completed",
                error_summary=err_summary,
                limitation_notice=limitation_notice,
                finished_at=datetime.now(timezone.utc),
                log_message=(
                    f"Job finished with status '{final_status}': "
                    f"discovered={discovered_count}, downloaded={downloaded_count}, "
                    f"skipped_duplicates={skipped_duplicate_count}, extracted_docs={extracted_doc_count}, "
                    f"cases={case_records_count}, failed={failed_count}."
                ),
            )

        return {
            "status": final_status,
            "discovered_count": discovered_count,
            "downloaded_count": downloaded_count,
            "skipped_duplicate_count": skipped_duplicate_count,
            "extracted_doc_count": extracted_doc_count,
            "case_records_count": case_records_count,
            "failed_count": failed_count,
            "errors": run_errors,
            "limitation_notice": limitation_notice,
        }

    def retry_document(self, document_id: int) -> Dict[str, Any]:
        """
        Retry downloading and/or extracting a previously failed (or existing) PDF document.
        Never duplicates case records on retry.
        """
        self.repo.ensure_initialized()
        doc_row = self.repo.get_document(document_id)
        if not doc_row:
            raise ValueError(f"Document {document_id} not found")

        pdf_bytes = self.downloader.load_stored_pdf_bytes(
            storage_object_key=doc_row.get("storage_object_key"),
            local_fallback_path=doc_row.get("local_fallback_path"),
        )

        if pdf_bytes is None:
            loc_spec, _ = find_location_spec(
                state_code=doc_row.get("state_code"),
                court_type=doc_row["court_type"],
                district_code=doc_row.get("district_code"),
                bench_code=doc_row["bench_code"],
                complex_code=doc_row.get("complex_code"),
                establishment_code=doc_row.get("establishment_code"),
            )
            listing_dt = date.fromisoformat(doc_row["listing_date"])
            disc_doc = DiscoveredDocument(
                document_identity=doc_row["document_identity"],
                court_type=doc_row["court_type"],
                state_code=doc_row.get("state_code"),
                state_name=doc_row.get("state_name"),
                district_code=doc_row.get("district_code"),
                district_name=doc_row.get("district_name"),
                complex_code=doc_row.get("complex_code"),
                complex_name=doc_row.get("complex_name"),
                establishment_code=doc_row.get("establishment_code"),
                establishment_name=doc_row.get("establishment_name"),
                court_code=doc_row["court_code"],
                court_name=doc_row["court_name"],
                bench_code=doc_row["bench_code"],
                bench_name=doc_row["bench_name"],
                document_category=doc_row.get("document_category") or "daily_cause_list",
                listing_date=listing_dt,
                cause_list_type=doc_row.get("cause_list_type") or "",
                coram_judge_raw=doc_row.get("coram_judge_raw") or "",
                court_number=doc_row.get("court_number") or "",
                diary_number=doc_row.get("diary_number") or "",
                source_reference=doc_row["source_reference"],
                source_url=doc_row["source_url"],
                pdf_filename=doc_row["pdf_filename"],
                ecourts_hc_state_code=(loc_spec.portal_state_code if loc_spec else doc_row.get("state_code")) or "1",
                ecourts_hc_dist_code=(loc_spec.portal_dist_code if loc_spec else "1") or "1",
                ecourts_hc_court_code=(loc_spec.portal_court_code if loc_spec else doc_row["bench_code"]) or "1",
            )
            dl_res = self.downloader.download_and_store(disc_doc)
            if not dl_res.success or dl_res.pdf_bytes is None:
                err_msg = dl_res.error_message or "Retry download failed"
                self.repo.record_download_outcome(
                    document_id=document_id,
                    download_status="failed",
                    storage_namespace=dl_res.storage_namespace,
                    error_message=err_msg,
                )
                raise RuntimeError(err_msg)

            pdf_bytes = dl_res.pdf_bytes
            self.repo.record_download_outcome(
                document_id=document_id,
                download_status="downloaded",
                content_sha256=dl_res.content_sha256,
                file_size_bytes=dl_res.file_size_bytes,
                storage_namespace=dl_res.storage_namespace,
                storage_object_key=dl_res.storage_object_key,
                local_fallback_path=dl_res.local_fallback_path,
                error_message=None,
            )

        extraction_res = self.extractor.extract_from_bytes(pdf_bytes)
        parsed_cases: List[Any] = []
        if extraction_res.success:
            parsed_cases = self.parser.parse_document(
                extraction=extraction_res,
                default_listing_date=date.fromisoformat(doc_row["listing_date"]),
                fallback_judge=doc_row.get("coram_judge_raw") or "",
                cause_list_type=doc_row.get("cause_list_type") or "",
                document_category=doc_row.get("document_category") or "daily_cause_list",
                fallback_court_room=doc_row.get("court_number") or "",
                fallback_diary_number=doc_row.get("diary_number") or "",
            )

        updated_doc = self.repo.save_extraction_and_cases(
            document_id=document_id,
            scrape_job_id=doc_row.get("scrape_job_id"),
            extraction=extraction_res,
            parsed_cases=parsed_cases,
            increment_retry=True,
        )

        self.analytics.refresh_daily_analytics(
            court_type=doc_row["court_type"],
            state_code=doc_row.get("state_code"),
            bench_code=doc_row["bench_code"],
            target_dates=[doc_row["listing_date"]],
        )
        return updated_doc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="PDF Intelligence Engine — All-India Court PDF Scraper & Case Analyzer"
    )
    parser.add_argument(
        "--court-type",
        default="high_court",
        choices=["supreme_court", "high_court", "district_court"],
    )
    parser.add_argument("--state", default=None, help="State code, ISO code (e.g. IN-MH), or state name (omit for supreme_court)")
    parser.add_argument("--district", default=None, help="District code or name")
    parser.add_argument("--complex", default=None, help="District Court complex code or name")
    parser.add_argument("--establishment", default=None, help="District Court establishment code or name")
    parser.add_argument("--bench", default=None, help="Bench code or name")
    parser.add_argument(
        "--document-category",
        default="daily_cause_list",
        choices=["daily_cause_list", "supplementary_cause_list", "daily_order", "final_judgment", "other_case_pdf"],
    )
    parser.add_argument("--start-date", required=True, help="Inclusive start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="Inclusive end date (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    loc, limitation = find_location_spec(
        state_code=args.state,
        court_type=args.court_type,
        district_code=args.district,
        bench_code=args.bench,
        complex_code=args.complex,
        establishment_code=args.establishment,
    )
    if limitation or loc is None:
        print(f"[LIMITATION] {limitation or 'Court location not found'}", file=sys.stderr)
        return 2

    start_dt = date.fromisoformat(args.start_date)
    end_dt = date.fromisoformat(args.end_date)

    engine = PDFIntelligenceEngine()
    result = engine.run_scrape_pipeline(
        location=loc,
        start_date=start_dt,
        end_date=end_dt,
        document_category=args.document_category,
    )
    print(f"Completed PDF Intelligence run: {result}")
    return 0 if result["status"] in ("completed", "completed_with_errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())


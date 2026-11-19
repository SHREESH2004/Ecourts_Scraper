"""
Durable Job Processor (`worker.py`) for the All-India PDF Intelligence Engine.

Supports Supreme Court (`supreme_court`), High Courts (`high_court`), and
District & Subordinate Courts (`district_court`) across all document categories.
Operates completely independently of the existing scraper and never touches
`CURRENT_SCRAPER_JOB`.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .engine import PDFIntelligenceEngine
from .repository import PDFIntelligenceRepository
from .source_discovery import CourtLocationSpec, find_location_spec, generate_inclusive_date_range

logger = logging.getLogger(__name__)


def build_scope_key(
    location: CourtLocationSpec,
    start_date: date,
    end_date: date,
    document_category: str = "daily_cause_list",
) -> str:
    return f"{location.location_key}:{document_category}:{start_date.isoformat()}:{end_date.isoformat()}"


class PDFIntelligenceWorker:
    """
    Durable background worker managing `pi_scrape_jobs` execution and restart recovery.
    """

    def __init__(
        self,
        engine: Optional[PDFIntelligenceEngine] = None,
        worker_id: Optional[str] = None,
    ):
        self.engine = engine or PDFIntelligenceEngine()
        self.repo: PDFIntelligenceRepository = self.engine.repo
        self.worker_id = worker_id or f"pi-worker-{os.getpid()}"
        self._submission_lock = threading.Lock()
        self._active_threads: Dict[str, threading.Thread] = {}

    def recover_on_startup(self, auto_resume: bool = False) -> List[Dict[str, Any]]:
        """
        Recover any jobs that were left in `running` or `queued` state due to an
        application restart or crash.
        """
        recovered_jobs = self.repo.recover_interrupted_jobs(resume=auto_resume)
        if auto_resume:
            for job in recovered_jobs:
                if job["status"] == "queued":
                    loc, err = find_location_spec(
                        state_code=job.get("state_code"),
                        court_type=job["court_type"],
                        district_code=job.get("district_code"),
                        bench_code=job.get("bench_code"),
                        complex_code=job.get("complex_code"),
                        establishment_code=job.get("establishment_code"),
                    )
                    if loc and not err:
                        start_dt = date.fromisoformat(job["start_date"])
                        end_dt = date.fromisoformat(job["end_date"])
                        doc_cat = job.get("document_category") or "daily_cause_list"
                        self._dispatch_background_thread(
                            job_uid=job["job_uid"],
                            scrape_job_id=int(job["id"]),
                            location=loc,
                            start_date=start_dt,
                            end_date=end_dt,
                            document_category=doc_cat,
                        )
        return recovered_jobs

    def submit_job(
        self,
        start_date: str | date,
        end_date: str | date,
        court_type: str = "high_court",
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        complex_code: Optional[str] = None,
        establishment_code: Optional[str] = None,
        bench_code: Optional[str] = None,
        document_category: str = "daily_cause_list",
        preset_label: str = "custom",
        allow_duplicate: bool = False,
        run_async: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate request parameters, verify source support, create a persistent
        `pi_scrape_jobs` row, and start execution.
        """
        if isinstance(start_date, str):
            start_dt = date.fromisoformat(start_date.strip())
        else:
            start_dt = start_date

        if isinstance(end_date, str):
            end_dt = date.fromisoformat(end_date.strip())
        else:
            end_dt = end_date

        generate_inclusive_date_range(start_dt, end_dt)

        location, limitation = find_location_spec(
            state_code=state_code,
            court_type=court_type,
            district_code=district_code,
            bench_code=bench_code,
            complex_code=complex_code,
            establishment_code=establishment_code,
        )
        if limitation or location is None:
            raise PermissionError(limitation or f"Court location not supported for {court_type} / {state_code!r}")

        scope_key = build_scope_key(location, start_dt, end_dt, document_category=document_category)
        job_uid = f"pi-job-{uuid.uuid4().hex[:12]}"

        with self._submission_lock:
            job_record = self.repo.create_scrape_job(
                job_uid=job_uid,
                scope_key=scope_key,
                location=location,
                start_date=start_dt,
                end_date=end_dt,
                document_category=document_category or "daily_cause_list",
                preset_label=preset_label or "custom",
                worker_id=self.worker_id,
                allow_duplicate=allow_duplicate,
            )

        scrape_job_id = int(job_record["id"])
        if run_async:
            self._dispatch_background_thread(
                job_uid=job_uid,
                scrape_job_id=scrape_job_id,
                location=location,
                start_date=start_dt,
                end_date=end_dt,
                document_category=document_category or "daily_cause_list",
            )
            return self.repo.get_scrape_job(job_uid) or job_record
        else:
            self._execute_job_target(
                job_uid=job_uid,
                scrape_job_id=scrape_job_id,
                location=location,
                start_date=start_dt,
                end_date=end_dt,
                document_category=document_category or "daily_cause_list",
            )
            return self.repo.get_scrape_job(job_uid) or job_record

    def _dispatch_background_thread(
        self,
        job_uid: str,
        scrape_job_id: int,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
    ) -> None:
        thread = threading.Thread(
            target=self._execute_job_target,
            kwargs={
                "job_uid": job_uid,
                "scrape_job_id": scrape_job_id,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "document_category": document_category,
            },
            name=f"PDFIntelWorker-{job_uid}",
            daemon=True,
        )
        self._active_threads[job_uid] = thread
        thread.start()

    def _execute_job_target(
        self,
        job_uid: str,
        scrape_job_id: int,
        location: CourtLocationSpec,
        start_date: date,
        end_date: date,
        document_category: str = "daily_cause_list",
    ) -> None:
        try:
            self.engine.run_scrape_pipeline(
                location=location,
                start_date=start_date,
                end_date=end_date,
                document_category=document_category,
                job_uid=job_uid,
                scrape_job_id=scrape_job_id,
            )
        except Exception as exc:
            logger.exception("PDF Intelligence job %s failed: %s", job_uid, exc)
            self.repo.update_scrape_job(
                job_uid,
                status="failed",
                current_step="Failed with error",
                error_summary=str(exc),
                finished_at=datetime.now(timezone.utc),
                log_message=f"JOB FAILED: {exc}",
                log_level="ERROR",
            )
        finally:
            self._active_threads.pop(job_uid, None)


"""
Comprehensive Test Suite for the All-India PDF Intelligence Scraping & Analysis System.

Verifies:
1. Baseline preservation of existing scraper files and routes.
2. Supreme Court source adapter (`SupremeCourtSourceAdapter`): national-level (nullable state/district),
   Diary number, AOR, Court number, cause-list vs judgment separation, and `pdf-intelligence/supreme-court/` namespace.
3. High Court source adapter (`HighCourtSourceAdapter`): State -> High Court -> Bench, custom date ranges,
   SHA-256 deduplication, and `pdf-intelligence/high-court/` namespace.
4. District Court source adapter (`DistrictCourtSourceAdapter`): State -> District -> Court Complex -> Establishment
   (multiple complexes per district, multiple establishments per complex), CNR number, Filing number,
   CAPTCHA gate detection, and `pdf-intelligence/district-court/` namespace.
5. Digital text & OCR fallback extraction and multi-case record parsing.
6. Separate & combined Daily Analytics across Supreme Court, High Courts, and District Courts.
7. Durable job concurrency guard and restart recovery.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOYMENT_DIR = Path(__file__).resolve().parent.parent

if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

if "dotenv" not in sys.modules:
    try:
        import dotenv  # noqa: F401
    except ImportError:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *args, **kwargs: False
        dotenv_stub.find_dotenv = lambda *args, **kwargs: ""
        sys.modules["dotenv"] = dotenv_stub

if "botocore" not in sys.modules:
    try:
        import botocore.exceptions  # noqa: F401
    except ImportError:
        botocore_mod = types.ModuleType("botocore")
        botocore_exc = types.ModuleType("botocore.exceptions")

        class ClientError(Exception):
            def __init__(self, error_response=None, operation_name=None):
                super().__init__(str(error_response))
                self.response = error_response or {}

        botocore_exc.ClientError = ClientError
        botocore_mod.exceptions = botocore_exc
        sys.modules["botocore"] = botocore_mod
        sys.modules["botocore.exceptions"] = botocore_exc


def build_valid_pdf_with_text(lines: list[str]) -> bytes:
    """
    Construct a genuine, valid single-page PDF byte stream containing the given text lines
    readable by PyPDF2 / pdfplumber.
    """
    escaped_ops = ["BT", "/F1 10 Tf", "40 760 Td", "14 TL"]
    for idx, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if idx == 0:
            escaped_ops.append(f"({safe}) Tj")
        else:
            escaped_ops.append(f"T* ({safe}) Tj")
    escaped_ops.append("ET")
    stream_data = "\n".join(escaped_ops).encode("latin-1", errors="replace")

    objs: list[bytes] = []
    objs.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objs.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objs.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
    )
    objs.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    objs.append(
        f"5 0 obj\n<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
        + stream_data
        + b"\nendstream\nendobj\n"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def build_scanned_image_only_pdf() -> bytes:
    return build_valid_pdf_with_text([])


class MockHTTPResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class MockPortalSession:
    """
    Mocked `requests.Session` simulating Supreme Court (`sci.gov.in`),
    High Court (`hcservices.ecourts.gov.in`), and District Court (`services.ecourts.gov.in`)
    endpoints.
    """

    def __init__(self, post_responses_by_date: dict[str, str], pdf_by_ref: dict[str, bytes]):
        self.headers = {}
        self.cookies = {}
        self.post_responses_by_date = post_responses_by_date
        self.pdf_by_ref = pdf_by_ref
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []

    def post(self, url: str, data: dict = None, timeout: int = 15):
        payload = dict(data or {})
        self.post_calls.append({"url": url, "data": payload})
        dt_str = (
            payload.get("causelist_dt")
            or payload.get("listing_date")
            or payload.get("causelist_date")
            or payload.get("from_date")
            or ""
        )
        body = self.post_responses_by_date.get(dt_str, "")
        return MockHTTPResponse(200, body.encode("utf-8"))

    def get(self, url: str, headers: dict = None, timeout: int = 20):
        self.get_calls.append(url)
        for ref, pdf_bytes in self.pdf_by_ref.items():
            if ref in url:
                return MockHTTPResponse(200, pdf_bytes)
        return MockHTTPResponse(404, b"Not found")

    def close(self):
        pass


class PDFIntelligenceSystemTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.temp_dir.name) / "test_pi.sqlite3"
        os.environ["PI_SQLITE_PATH"] = str(self.sqlite_path)

        from pdf_intelligence.case_parser import CaseRecordParser
        from pdf_intelligence.downloader import PDFDownloader
        from pdf_intelligence.engine import PDFIntelligenceEngine
        from pdf_intelligence.pdf_extractor import PDFTextExtractor
        from pdf_intelligence.repository import PDFIntelligenceRepository
        from pdf_intelligence.source_discovery import find_location_spec
        from pdf_intelligence.sources import (
            DistrictCourtSourceAdapter,
            HighCourtSourceAdapter,
            SupremeCourtSourceAdapter,
        )
        from pdf_intelligence.worker import PDFIntelligenceWorker

        self.repo = PDFIntelligenceRepository(sqlite_path=self.sqlite_path)
        self.repo.ensure_initialized()
        self.find_location_spec = find_location_spec
        self.SupremeCourtSourceAdapter = SupremeCourtSourceAdapter
        self.HighCourtSourceAdapter = HighCourtSourceAdapter
        self.DistrictCourtSourceAdapter = DistrictCourtSourceAdapter
        self.PDFDownloader = PDFDownloader
        self.PDFTextExtractor = PDFTextExtractor
        self.CaseRecordParser = CaseRecordParser
        self.PDFIntelligenceEngine = PDFIntelligenceEngine
        self.PDFIntelligenceWorker = PDFIntelligenceWorker

    def tearDown(self):
        os.environ.pop("PI_SQLITE_PATH", None)
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Check 1: Protected existing scraper files have not changed
    # -------------------------------------------------------------------------
    def test_01_protected_files_unchanged(self):
        protected_files = [
            "deployment/scraper/1.py",
            "deployment/data_service.py",
            "deployment/storage_service.py",
            "deployment/court_mapper.py",
            "deployment/migrations/20261007_create_court_reference_tables.sql",
        ]
        for rel_path in protected_files:
            proc = subprocess.run(
                ["git", "diff", "--name-only", "HEAD", "--", rel_path],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                proc.stdout.strip(),
                "",
                f"Protected file {rel_path} was modified!",
            )

    # -------------------------------------------------------------------------
    # Check 2 & 3: Existing scraper endpoints and dashboard pages still work
    # -------------------------------------------------------------------------
    def test_02_existing_routes_and_pages_intact(self):
        import app as flask_app_module

        client = flask_app_module.app.test_client()

        for route in [
            "/health",
            "/",
            "/judges.html",
            "/judge.html",
            "/supreme-court-judge.html",
            "/pdfs.html",
            "/pdf-viewer.html",
            "/runs.html",
            "/pdf-analysis.html",
            "/pdf-intelligence",
            "/pdf-analysis.css",
            "/pdf-analysis.js",
            "/api/pdf-intelligence/map-geojson",
        ]:
            resp = client.get(route)
            try:
                self.assertEqual(resp.status_code, 200, f"Route {route} failed with {resp.status_code}")
            finally:
                resp.close()

        status_resp = client.get("/api/scraper/status")
        self.assertEqual(status_resp.status_code, 200)
        self.assertTrue(status_resp.get_json()["success"])

        options_resp = client.get("/api/scraper/options")
        self.assertEqual(options_resp.status_code, 200)
        self.assertTrue(options_resp.get_json()["success"])

    # -------------------------------------------------------------------------
    # Check 4: Independent Supreme Court Adapter (National level, Diary No, AOR)
    # -------------------------------------------------------------------------
    def test_03_supreme_court_adapter_national_hierarchy_and_extraction(self):
        sc_causelist_pdf = build_valid_pdf_with_text(
            [
                "SUPREME COURT OF INDIA",
                "DAILY CAUSE LIST FOR TUESDAY THE 10TH NOVEMBER 2026",
                "CHIEF JUSTICE'S COURT",
                "CORAM: HON'BLE THE CHIEF JUSTICE OF INDIA",
                "1 SLP(C)/4501/2026 Diary No. 28901/2026 RAJESHWARI DEVI VS UNION OF INDIA AOR: MR. VIPIN NAIR",
                "2 W.P.(C)/310/2026 Diary No. 19044/2026 CITIZENS FORUM VS ELECTION COMMISSION OF INDIA AOR: MS. PRAGYA BAGHEL",
            ]
        )
        sc_judgment_pdf = build_valid_pdf_with_text(
            [
                "IN THE SUPREME COURT OF INDIA CIVIL APPELLATE JURISDICTION",
                "COURT NO. 2",
                "HON'BLE MR. JUSTICE SANJIV KHANNA",
                "Date of Judgment : 10-11-2026",
                "1 C.A./897/2024 Diary No. 11220/2024 TATA MOTORS LTD VS STATE OF MAHARASHTRA AOR: MR. KARANJAWALA",
            ]
        )

        html_causelist = (
            '<table><tr><td>Chief Justice\'s Court</td>'
            '<td>HON\'BLE THE CHIEF JUSTICE</td>'
            '<td><a href="https://main.sci.gov.in/causelist/2026/sc_daily_10112026.pdf">Daily Cause List Court 1</a></td>'
            '</tr></table>'
        )
        json_judgment = json.dumps(
            {
                "data": {
                    "items": [
                        {
                            "pdf_url": "https://api.sci.gov.in/supremecourt/2024/11220/11220_2024_judgment.pdf",
                            "diary_number": "11220/2024",
                            "case_number": "C.A./897/2024",
                            "court_number": "Court No. 2",
                            "judge_names": "HON'BLE MR. JUSTICE SANJIV KHANNA",
                            "document_category": "final_judgment",
                        }
                    ]
                }
            }
        )

        pdf_map = {
            "sc_daily_10112026.pdf": sc_causelist_pdf,
            "11220_2024_judgment.pdf": sc_judgment_pdf,
        }

        # 1. Run Supreme Court Daily Cause List scrape
        sc_loc, err = self.find_location_spec(court_type="supreme_court", bench_code="SC-CJI")
        self.assertIsNone(err)
        self.assertIsNotNone(sc_loc)
        # Verify Supreme Court is NOT assigned to any state or district
        self.assertIsNone(sc_loc.state_code)
        self.assertIsNone(sc_loc.district_code)

        sc_adapter_cl = self.SupremeCourtSourceAdapter(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession({"10-11-2026": html_causelist}, pdf_map),
        )
        downloader = self.PDFDownloader(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession({"10-11-2026": html_causelist}, pdf_map),
            allow_local_fallback=True,
        )
        engine = self.PDFIntelligenceEngine(
            repository=self.repo,
            adapters_by_tier={"supreme_court": sc_adapter_cl},
            downloader=downloader,
        )

        res_cl = engine.run_scrape_pipeline(
            location=sc_loc,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 10),
            document_category="daily_cause_list",
        )
        self.assertEqual(res_cl["status"], "completed")
        self.assertEqual(res_cl["case_records_count"], 2)

        # 2. Run Supreme Court Final Judgment scrape
        sc_adapter_jdg = self.SupremeCourtSourceAdapter(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession({"10-11-2026": json_judgment}, pdf_map),
        )
        engine_jdg = self.PDFIntelligenceEngine(
            repository=self.repo,
            adapters_by_tier={"supreme_court": sc_adapter_jdg},
            downloader=downloader,
        )
        res_jdg = engine_jdg.run_scrape_pipeline(
            location=sc_loc,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 10),
            document_category="final_judgment",
        )
        self.assertEqual(res_jdg["status"], "completed")
        self.assertEqual(res_jdg["case_records_count"], 1)

        # Verify stored Supreme Court documents and cases
        sc_docs = self.repo.list_documents(court_type="supreme_court")["items"]
        self.assertEqual(len(sc_docs), 2)
        for d in sc_docs:
            self.assertIsNone(d["state_code"])
            self.assertIsNone(d["district_code"])
            self.assertEqual(d["storage_namespace"], "pdf-intelligence/supreme-court")
            self.assertTrue(d["storage_object_key"].startswith("pdf-intelligence/supreme-court/"))

        sc_cases = self.repo.list_case_records(court_type="supreme_court")["items"]
        self.assertEqual(len(sc_cases), 3)
        cl_cases = [c for c in sc_cases if c["document_category"] == "daily_cause_list"]
        jdg_cases = [c for c in sc_cases if c["document_category"] == "final_judgment"]
        self.assertEqual(len(cl_cases), 2)
        self.assertEqual(len(jdg_cases), 1)

        # Cause list cases must NOT have a fabricated judgment_date
        for c in cl_cases:
            self.assertIsNone(c["judgment_date"])
            self.assertTrue(c["diary_number"].endswith("/2026"))
            self.assertTrue(len(c["advocate_on_record"]) > 0)

        # Final judgment case has explicit judgment_date
        self.assertEqual(jdg_cases[0]["judgment_date"], "2026-11-10")
        self.assertEqual(jdg_cases[0]["diary_number"], "11220/2024")

    # -------------------------------------------------------------------------
    # Check 5: High Court Adapter (Custom Date Range, Deduplication, Namespace)
    # -------------------------------------------------------------------------
    def test_04_high_court_adapter_date_range_deduplication_and_namespace(self):
        hc_pdf = build_valid_pdf_with_text(
            [
                "HIGH COURT OF BOMBAY BENCH AT AURANGABAD",
                "DAILY MAIN CAUSELIST FOR MONDAY THE 10TH NOVEMBER 2026",
                "COURT NO. 11",
                "HON'BLE SHRI JUSTICE R. M. JOSHI",
                "1 WP/101/2026 RAMESH PATIL VS THE STATE OF MAHARASHTRA Adv. A. B. Kale",
                "2 ABA/205/2026 SURESH DESHMUKH VS THE STATE OF MAHARASHTRA Adv. C. D. More",
            ]
        )

        causelist_map = {
            "09-11-2026": "1~HON'BLE SHRI JUSTICE R. M. JOSHI~Daily Main~0~ref_aur_20261109_A~N~11~CL101~1^#",
            "10-11-2026": "1~HON'BLE SHRI JUSTICE R. M. JOSHI~Daily Main~0~ref_aur_20261110_B~N~11~CL102~1^#",
            "11-11-2026": "",
        }
        pdf_map = {
            "ref_aur_20261109_A": hc_pdf,
            "ref_aur_20261110_B": hc_pdf,
        }

        created_sessions: list[MockPortalSession] = []

        def session_factory():
            s = MockPortalSession(causelist_map, pdf_map)
            created_sessions.append(s)
            return s

        hc_adapter = self.HighCourtSourceAdapter(rate_limit_seconds=0.0, session_factory=session_factory)
        downloader = self.PDFDownloader(rate_limit_seconds=0.0, session_factory=session_factory, allow_local_fallback=True)
        engine = self.PDFIntelligenceEngine(
            repository=self.repo,
            adapters_by_tier={"high_court": hc_adapter},
            downloader=downloader,
        )

        loc, limitation = self.find_location_spec(
            state_code="1",
            court_type="high_court",
            district_code="MH-AUR",
            bench_code="3",
        )
        self.assertIsNone(limitation)

        res1 = engine.run_scrape_pipeline(
            location=loc,
            start_date=date(2026, 11, 9),
            end_date=date(2026, 11, 11),
            document_category="daily_cause_list",
        )
        self.assertEqual(res1["discovered_count"], 2)
        self.assertEqual(res1["downloaded_count"], 2)
        self.assertEqual(res1["case_records_count"], 4)

        docs = self.repo.list_documents(court_type="high_court", state_code="1", bench_code="3")["items"]
        self.assertEqual(len(docs), 2)
        for d in docs:
            self.assertEqual(d["storage_namespace"], "pdf-intelligence/high-court")
            self.assertTrue(d["storage_object_key"].startswith("pdf-intelligence/high-court/1/BOMBAY-HC/3/"))

        # Second run skips already-processed documents without re-downloading
        get_count_before = sum(len(s.get_calls) for s in created_sessions)
        res2 = engine.run_scrape_pipeline(
            location=loc,
            start_date=date(2026, 11, 9),
            end_date=date(2026, 11, 11),
            document_category="daily_cause_list",
        )
        get_count_after = sum(len(s.get_calls) for s in created_sessions)
        self.assertEqual(res2["skipped_duplicate_count"], 2)
        self.assertEqual(get_count_before, get_count_after)

    # -------------------------------------------------------------------------
    # Check 6: District Court Adapter (State -> District -> Complex -> Establishment)
    # -------------------------------------------------------------------------
    def test_05_district_court_adapter_hierarchy_cnr_filing_and_captcha_detection(self):
        # 1. Verify multiple complexes in Mumbai City and multiple establishments in Fort Complex
        complexes = self.repo.get_complexes(state_code="1", district_code="MH-MUM")
        self.assertGreaterEqual(len(complexes), 3)
        fort_ests = self.repo.get_establishments(
            state_code="1",
            district_code="MH-MUM",
            complex_code="MUM-CCSC",
        )
        self.assertGreaterEqual(len(fort_ests), 2)

        # 2. Verify District Court PDF discovery & extraction of CNR, Filing No, Complex, Establishment
        dc_pdf = build_valid_pdf_with_text(
            [
                "IN THE CITY CIVIL AND SESSIONS COURT AT MUMBAI",
                "COURT ROOM NO. 1",
                "BEFORE PRINCIPAL JUDGE SHRI A. K. SHINDE",
                "1 RCS/102/2026 CNR: MHCC010012342026 Filing No. 4512/2026 MAHESH SHAH VS BRIHANMUMBAI MUNICIPAL CORPORATION Adv. S. P. Kulkarni",
                "2 SPL.CASE/45/2025 CNR: MHCC010098762025 Filing No. 8810/2025 STATE OF MAHARASHTRA VS DEEPAK RAO Adv. P.P. Patil",
            ]
        )
        dc_json_resp = json.dumps(
            {
                "pdfs": [
                    {
                        "filename": "dc_mumbai_ccsc_20261112.pdf",
                        "judge": "PRINCIPAL JUDGE SHRI A. K. SHINDE",
                        "document_category": "daily_cause_list",
                    }
                ]
            }
        )
        pdf_map = {"dc_mumbai_ccsc_20261112.pdf": dc_pdf}

        dc_loc, err = self.find_location_spec(
            state_code="1",
            court_type="district_court",
            district_code="MH-MUM",
            complex_code="MUM-CCSC",
            establishment_code="MHCC01-1",
        )
        self.assertIsNone(err)
        self.assertEqual(dc_loc.complex_code, "MUM-CCSC")
        self.assertEqual(dc_loc.establishment_code, "MHCC01-1")

        dc_adapter = self.DistrictCourtSourceAdapter(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession({"12-11-2026": dc_json_resp}, pdf_map),
        )
        downloader = self.PDFDownloader(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession({"12-11-2026": dc_json_resp}, pdf_map),
            allow_local_fallback=True,
        )
        engine = self.PDFIntelligenceEngine(
            repository=self.repo,
            adapters_by_tier={"district_court": dc_adapter},
            downloader=downloader,
        )

        res_dc = engine.run_scrape_pipeline(
            location=dc_loc,
            start_date=date(2026, 11, 12),
            end_date=date(2026, 11, 12),
            document_category="daily_cause_list",
        )
        self.assertEqual(res_dc["status"], "completed")
        self.assertEqual(res_dc["case_records_count"], 2)

        dc_docs = self.repo.list_documents(
            court_type="district_court",
            state_code="1",
            complex_code="MUM-CCSC",
        )["items"]
        self.assertEqual(len(dc_docs), 1)
        self.assertEqual(dc_docs[0]["storage_namespace"], "pdf-intelligence/district-court")
        self.assertTrue(
            dc_docs[0]["storage_object_key"].startswith("pdf-intelligence/district-court/1/MH-MUM/MUM-CCSC/MHCC01-1/")
        )

        dc_cases = self.repo.list_case_records(
            court_type="district_court",
            complex_code="MUM-CCSC",
            establishment_code="MHCC01-1",
        )["items"]
        self.assertEqual(len(dc_cases), 2)
        self.assertEqual(dc_cases[0]["cnr_number"], "MHCC010012342026")
        self.assertEqual(dc_cases[0]["filing_number"], "4512/2026")
        self.assertEqual(dc_cases[0]["complex_name"], "City Civil and Sessions Court Complex, Fort Mumbai")
        self.assertEqual(dc_cases[0]["establishment_name"], "Principal Judge, City Civil & Sessions Court, Mumbai")

        # 3. Verify CAPTCHA gate detection when portal demands Securimage verification
        captcha_adapter = self.DistrictCourtSourceAdapter(
            rate_limit_seconds=0.0,
            session_factory=lambda: MockPortalSession(
                {"13-11-2026": '{"status": 0, "errormsg": "Invalid Captcha Code"}'},
                {},
            ),
        )
        docs_cap, _, err_cap = captcha_adapter.discover_for_single_date(dc_loc, date(2026, 11, 13))
        self.assertEqual(len(docs_cap), 0)
        self.assertIn("CAPTCHA", (err_cap or "").upper())

    # -------------------------------------------------------------------------
    # Check 7: OCR Fallback & Multi-Tier Analytics + Retry + Restart Recovery
    # -------------------------------------------------------------------------
    def test_06_ocr_fallback_multi_tier_analytics_and_restart_recovery(self):
        from flask import Flask
        from pdf_intelligence import register_pdf_intelligence

        scanned_pdf = build_scanned_image_only_pdf()
        ocr_extractor = self.PDFTextExtractor(
            ocr_provider=lambda b, idx: (
                "MADRAS HIGH COURT - PRINCIPAL BENCH\n"
                "HON'BLE MR. JUSTICE S. M. SUBRAMANIAM\n"
                "101 WP/3344/2026 VELMURUGAN VS THE DISTRICT COLLECTOR CHENNAI Adv. R. Natarajan\n"
            )
        )
        ocr_res = ocr_extractor.extract_from_bytes(scanned_pdf)
        self.assertTrue(ocr_res.success)
        self.assertTrue(ocr_res.used_ocr)
        self.assertEqual(ocr_res.extraction_method, "ocr_fallback")

        # Test Flask API endpoints for complexes, establishments, SC benches, and multi-tier analytics
        engine = self.PDFIntelligenceEngine(repository=self.repo, extractor=ocr_extractor)
        worker = self.PDFIntelligenceWorker(engine=engine)
        test_app = Flask(__name__)
        register_pdf_intelligence(test_app, worker=worker)
        client = test_app.test_client()

        cx_res = client.get("/api/pdf-intelligence/complexes?state_code=DL").get_json()
        self.assertTrue(cx_res["success"])
        self.assertGreaterEqual(len(cx_res["complexes"]), 3)

        est_res = client.get("/api/pdf-intelligence/establishments?state_code=DL&complex_code=DL-PHC").get_json()
        self.assertTrue(est_res["success"])
        self.assertGreaterEqual(len(est_res["establishments"]), 2)

        sc_benches_res = client.get("/api/pdf-intelligence/supreme-court/benches").get_json()
        self.assertTrue(sc_benches_res["success"])
        self.assertGreaterEqual(len(sc_benches_res["benches"]), 5)

        analytics_res = client.get("/api/pdf-intelligence/analytics/daily").get_json()
        self.assertTrue(analytics_res["success"])
        self.assertIn("by_court_category", analytics_res["data"])
        self.assertIn("supreme_court", analytics_res["data"]["by_court_category"])
        self.assertIn("high_court", analytics_res["data"]["by_court_category"])
        self.assertIn("district_court", analytics_res["data"]["by_court_category"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

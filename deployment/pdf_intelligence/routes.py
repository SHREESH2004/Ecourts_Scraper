"""
Flask Blueprint & Route Handlers for the `/api/pdf-intelligence/` Namespace
and `/pdf-analysis.html` Frontend Assets.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from flask import Blueprint, Response, abort, jsonify, redirect, request, send_file, send_from_directory

from .downloader import PDFDownloader
from .engine import PDFIntelligenceEngine
from .repository import PDFIntelligenceRepository
from .worker import PDFIntelligenceWorker

DEPLOYMENT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = DEPLOYMENT_DIR / "static"


def create_pdf_intelligence_blueprint(
    worker: Optional[PDFIntelligenceWorker] = None,
) -> Blueprint:
    bp = Blueprint("pdf_intelligence", __name__)

    active_worker = worker or PDFIntelligenceWorker()
    engine: PDFIntelligenceEngine = active_worker.engine
    repo: PDFIntelligenceRepository = active_worker.repo

    try:
        active_worker.recover_on_startup(auto_resume=False)
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # Frontend Page & Asset Routes
    # -------------------------------------------------------------------------
    @bp.route("/pdf-intelligence")
    @bp.route("/pdf-analysis")
    @bp.route("/pdf-analysis.html")
    def serve_pdf_analysis_page():
        return send_from_directory(str(STATIC_DIR), "pdf-analysis.html")

    @bp.route("/pdf-analysis.css")
    def serve_pdf_analysis_css():
        return send_from_directory(str(STATIC_DIR / "css"), "pdf-analysis.css")

    @bp.route("/pdf-analysis.js")
    def serve_pdf_analysis_js():
        return send_from_directory(str(STATIC_DIR / "js"), "pdf-analysis.js")

    @bp.route("/api/pdf-intelligence/map-geojson")
    def api_pi_map_geojson():
        return send_from_directory(str(STATIC_DIR / "data"), "india-states.geojson", mimetype="application/geo+json")

    # -------------------------------------------------------------------------
    # Hierarchy & Court Location Endpoints (Supreme, High, District Courts)
    # -------------------------------------------------------------------------
    @bp.route("/api/pdf-intelligence/states", methods=["GET"])
    def api_pi_states():
        try:
            court_type = request.args.get("court_type")
            states = repo.get_states_hierarchy(court_type=court_type)
            return jsonify({"success": True, "states": states})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/districts", methods=["GET"])
    def api_pi_districts():
        try:
            state_code = request.args.get("state_code") or request.args.get("state")
            court_type = request.args.get("court_type")
            districts = repo.get_districts(state_code=state_code, court_type=court_type)
            return jsonify({"success": True, "districts": districts})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/complexes", methods=["GET"])
    def api_pi_complexes():
        try:
            state_code = request.args.get("state_code") or request.args.get("state")
            district_code = request.args.get("district_code") or request.args.get("district")
            complexes = repo.get_complexes(state_code=state_code, district_code=district_code)
            return jsonify({"success": True, "complexes": complexes})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/establishments", methods=["GET"])
    def api_pi_establishments():
        try:
            state_code = request.args.get("state_code") or request.args.get("state")
            district_code = request.args.get("district_code") or request.args.get("district")
            complex_code = request.args.get("complex_code") or request.args.get("complex")
            establishments = repo.get_establishments(
                state_code=state_code,
                district_code=district_code,
                complex_code=complex_code,
            )
            return jsonify({"success": True, "establishments": establishments})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/courts", methods=["GET"])
    def api_pi_courts():
        try:
            state_code = request.args.get("state_code") or request.args.get("state")
            district_code = request.args.get("district_code") or request.args.get("district")
            court_type = request.args.get("court_type")
            complex_code = request.args.get("complex_code") or request.args.get("complex")
            courts = repo.get_courts(
                state_code=state_code,
                district_code=district_code,
                court_type=court_type,
                complex_code=complex_code,
            )
            return jsonify({"success": True, "courts": courts})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/benches", methods=["GET"])
    def api_pi_benches():
        try:
            state_code = request.args.get("state_code") or request.args.get("state")
            district_code = request.args.get("district_code") or request.args.get("district")
            court_type = request.args.get("court_type")
            court_code = request.args.get("court_code") or request.args.get("court")
            complex_code = request.args.get("complex_code") or request.args.get("complex")
            establishment_code = request.args.get("establishment_code") or request.args.get("establishment")
            benches = repo.get_benches(
                state_code=state_code,
                district_code=district_code,
                court_type=court_type,
                court_code=court_code,
                complex_code=complex_code,
                establishment_code=establishment_code,
            )
            return jsonify({"success": True, "benches": benches})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/supreme-court/benches", methods=["GET"])
    def api_pi_sc_benches():
        try:
            benches = repo.get_benches(court_type="supreme_court")
            return jsonify({"success": True, "benches": benches})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # -------------------------------------------------------------------------
    # Scrape Jobs Endpoints
    # -------------------------------------------------------------------------
    @bp.route("/api/pdf-intelligence/jobs", methods=["POST"])
    def api_pi_create_job():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "Expected a JSON request body"}), 400

        court_type = str(payload.get("court_type") or "high_court").strip().lower()
        state_code = str(payload.get("state_code") or payload.get("state") or "").strip() or None

        if court_type != "supreme_court" and not state_code:
            return jsonify({"success": False, "error": "state_code is required for High Court and District Court jobs"}), 400

        district_code = payload.get("district_code") or payload.get("district")
        complex_code = payload.get("complex_code") or payload.get("complex")
        establishment_code = payload.get("establishment_code") or payload.get("establishment")
        bench_code = payload.get("bench_code") or payload.get("bench") or establishment_code
        document_category = str(payload.get("document_category") or "daily_cause_list").strip()
        preset_label = str(payload.get("preset") or payload.get("preset_label") or "custom").strip()
        allow_duplicate = bool(payload.get("allow_duplicate", False))
        run_async = bool(payload.get("run_async", True))

        start_date_str = payload.get("start_date") or payload.get("from_date")
        end_date_str = payload.get("end_date") or payload.get("to_date")

        today = date.today()
        if not start_date_str or not end_date_str:
            if preset_label == "previous_3_days":
                end_dt = today
                start_dt = today - timedelta(days=2)
            elif preset_label == "previous_7_days":
                end_dt = today
                start_dt = today - timedelta(days=6)
            elif preset_label == "previous_15_days":
                end_dt = today
                start_dt = today - timedelta(days=14)
            else:
                return jsonify({"success": False, "error": "Both start_date and end_date (YYYY-MM-DD) are required"}), 400
            start_date_str = start_dt.isoformat()
            end_date_str = end_dt.isoformat()

        try:
            job = active_worker.submit_job(
                start_date=str(start_date_str),
                end_date=str(end_date_str),
                court_type=court_type,
                state_code=state_code,
                district_code=str(district_code).strip() if district_code else None,
                complex_code=str(complex_code).strip() if complex_code else None,
                establishment_code=str(establishment_code).strip() if establishment_code else None,
                bench_code=str(bench_code).strip() if bench_code else None,
                document_category=document_category,
                preset_label=preset_label,
                allow_duplicate=allow_duplicate,
                run_async=run_async,
            )
            return jsonify({"success": True, "job": job}), 201
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except PermissionError as exc:
            return jsonify(
                {
                    "success": False,
                    "error": str(exc),
                    "limitation": True,
                }
            ), 422
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc), "duplicate_active_job": True}), 409
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/jobs", methods=["GET"])
    def api_pi_list_jobs():
        try:
            limit = int(request.args.get("limit", 25))
            status = request.args.get("status")
            court_type = request.args.get("court_type")
            jobs = repo.list_scrape_jobs(limit=limit, status=status, court_type=court_type)
            return jsonify({"success": True, "jobs": jobs})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/jobs/<job_id>", methods=["GET"])
    def api_pi_get_job(job_id: str):
        try:
            job = repo.get_scrape_job(job_id)
            if not job:
                return jsonify({"success": False, "error": "Scrape job not found"}), 404
            return jsonify({"success": True, "job": job})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # -------------------------------------------------------------------------
    # Documents & Retry Endpoints
    # -------------------------------------------------------------------------
    @bp.route("/api/pdf-intelligence/documents", methods=["GET"])
    def api_pi_list_documents():
        try:
            result = repo.list_documents(
                state_code=request.args.get("state_code") or request.args.get("state"),
                district_code=request.args.get("district_code") or request.args.get("district"),
                court_type=request.args.get("court_type"),
                court_code=request.args.get("court_code") or request.args.get("court"),
                bench_code=request.args.get("bench_code") or request.args.get("bench"),
                complex_code=request.args.get("complex_code") or request.args.get("complex"),
                establishment_code=request.args.get("establishment_code") or request.args.get("establishment"),
                document_category=request.args.get("document_category") or request.args.get("category"),
                start_date=request.args.get("start_date") or request.args.get("from_date"),
                end_date=request.args.get("end_date") or request.args.get("to_date"),
                listing_date=request.args.get("listing_date") or request.args.get("date"),
                extraction_status=request.args.get("extraction_status") or request.args.get("status"),
                scrape_job_id=int(request.args["job_id"]) if request.args.get("job_id", "").isdigit() else None,
                query=request.args.get("q") or request.args.get("query"),
                page=int(request.args.get("page", 1)),
                limit=int(request.args.get("limit", 25)),
            )
            return jsonify({"success": True, **result})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/documents/<int:document_id>/file", methods=["GET"])
    def api_pi_serve_document_file(document_id: int):
        doc = repo.get_document(document_id)
        if not doc:
            abort(404, description="PDF document record not found")

        download = request.args.get("download", "").lower() in ("1", "true", "yes")
        redirect_url, local_path = PDFDownloader.resolve_download_url_or_path(
            storage_object_key=doc.get("storage_object_key"),
            local_fallback_path=doc.get("local_fallback_path"),
            pdf_filename=doc["pdf_filename"],
            download=download,
        )
        if redirect_url:
            return redirect(redirect_url, code=302)
        if local_path and local_path.is_file():
            return send_file(
                str(local_path),
                mimetype="application/pdf",
                as_attachment=download,
                download_name=doc["pdf_filename"],
            )
        abort(404, description="PDF file not available in Supabase Storage or local cache")

    @bp.route("/api/pdf-intelligence/documents/<int:document_id>/retry", methods=["POST"])
    def api_pi_retry_document(document_id: int):
        try:
            updated_doc = engine.retry_document(document_id)
            return jsonify({"success": True, "document": updated_doc})
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # -------------------------------------------------------------------------
    # Extracted Case Records & CSV Export Endpoints
    # -------------------------------------------------------------------------
    @bp.route("/api/pdf-intelligence/cases", methods=["GET"])
    def api_pi_list_cases():
        try:
            export_fmt = (request.args.get("format") or request.args.get("export") or "").strip().lower()
            is_csv = export_fmt == "csv"

            doc_id_arg = request.args.get("document_id")
            doc_id = int(doc_id_arg) if doc_id_arg and str(doc_id_arg).isdigit() else None

            result = repo.list_case_records(
                state_code=request.args.get("state_code") or request.args.get("state"),
                district_code=request.args.get("district_code") or request.args.get("district"),
                court_type=request.args.get("court_type"),
                court_code=request.args.get("court_code") or request.args.get("court"),
                bench_code=request.args.get("bench_code") or request.args.get("bench"),
                complex_code=request.args.get("complex_code") or request.args.get("complex"),
                establishment_code=request.args.get("establishment_code") or request.args.get("establishment"),
                document_category=request.args.get("document_category") or request.args.get("category"),
                document_id=doc_id,
                case_type=request.args.get("case_type"),
                judge=request.args.get("judge"),
                extraction_status=request.args.get("extraction_status") or request.args.get("status"),
                listing_date=request.args.get("listing_date") or request.args.get("date"),
                start_date=request.args.get("start_date") or request.args.get("from_date"),
                end_date=request.args.get("end_date") or request.args.get("to_date"),
                query=request.args.get("q") or request.args.get("query"),
                sort_by=request.args.get("sort", "listing_date"),
                sort_order=request.args.get("order", "desc"),
                page=1 if is_csv else int(request.args.get("page", 1)),
                limit=1000 if is_csv else int(request.args.get("limit", 25)),
            )

            if is_csv:
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(
                    [
                        "Court Category",
                        "Document Category",
                        "Case Number",
                        "Diary Number",
                        "CNR Number",
                        "Filing Number",
                        "Case Title",
                        "Petitioner",
                        "Respondent",
                        "Advocates / AOR",
                        "Case Type",
                        "Listing Date",
                        "Order Date",
                        "Judgment Date",
                        "Judge(s)",
                        "State",
                        "District",
                        "Court / Complex",
                        "Bench / Establishment",
                        "PDF Filename",
                        "Extraction Status",
                        "Confidence (%)",
                        "Original PDF Link",
                    ]
                )
                for item in result["items"]:
                    writer.writerow(
                        [
                            item["court_type"],
                            item.get("document_category") or "daily_cause_list",
                            item["case_number"],
                            item.get("diary_number") or "",
                            item.get("cnr_number") or "",
                            item.get("filing_number") or "",
                            item["case_title"],
                            item["petitioner"],
                            item["respondent"],
                            item.get("advocate_on_record") or item.get("advocates") or "",
                            item["case_type"],
                            item["listing_date"] or "",
                            item.get("order_date") or "",
                            item["judgment_date"] or "",
                            item["judge_names"] or "",
                            item["state_name"] or "National (Supreme Court)",
                            item["district_name"] or "—",
                            item.get("complex_name") or item["court_name"],
                            item.get("establishment_name") or item["bench_name"],
                            item["pdf_filename"],
                            item["extraction_status"],
                            item["confidence_pct"],
                            item["original_pdf_link"],
                        ]
                    )
                csv_bytes = output.getvalue().encode("utf-8-sig")
                return Response(
                    csv_bytes,
                    mimetype="text/csv; charset=utf-8",
                    headers={
                        "Content-Disposition": "attachment; filename=pdf_intelligence_cases.csv"
                    },
                )

            return jsonify({"success": True, **result})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/pdf-intelligence/cases/<int:case_id>", methods=["GET"])
    def api_pi_get_case(case_id: int):
        try:
            record = repo.get_case_record(case_id)
            if not record:
                return jsonify({"success": False, "error": "Case record not found"}), 404
            return jsonify({"success": True, "case": record})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # -------------------------------------------------------------------------
    # Daily Analytics & Drill-down Endpoint
    # -------------------------------------------------------------------------
    @bp.route("/api/pdf-intelligence/analytics/daily", methods=["GET"])
    def api_pi_daily_analytics():
        try:
            data = engine.analytics.get_daily_analytics(
                start_date=request.args.get("start_date") or request.args.get("from_date"),
                end_date=request.args.get("end_date") or request.args.get("to_date"),
                state_code=request.args.get("state_code") or request.args.get("state"),
                district_code=request.args.get("district_code") or request.args.get("district"),
                court_type=request.args.get("court_type"),
                bench_code=request.args.get("bench_code") or request.args.get("bench"),
                complex_code=request.args.get("complex_code") or request.args.get("complex"),
                establishment_code=request.args.get("establishment_code") or request.args.get("establishment"),
                drilldown_date=request.args.get("drilldown_date") or request.args.get("date"),
            )
            return jsonify({"success": True, "data": data})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    return bp

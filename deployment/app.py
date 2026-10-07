"""
Flask Web Application for eCourts Judicial Intelligence & Document Explorer
Production API and static web server.
Strictly serves confirmed metadata from PostgreSQL and local PDFs.
No fake statistics, no PDF-content extraction.
"""

import os
import sys
import ast
import threading
import subprocess
from functools import lru_cache
from datetime import datetime
from flask import Flask, jsonify, request, send_file, send_from_directory, abort, redirect
from dotenv import load_dotenv

# Load local development settings before importing modules that read the environment.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import data_service
import storage_service

app = Flask(__name__, static_folder="static", static_url_path="")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "downloaded_pdfs")
SCRAPER_LOG_MAX_LINES = 1000

# Live scraper worker tracking
CURRENT_SCRAPER_JOB = {
    "is_running": False,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "court_info": None,
    "log_lines": [],
    "log_lines_dropped": 0,
    "error": None,
    "return_code": None
}
SCRAPER_JOB_LOCK = threading.Lock()

# -------------------------------------------------------------
# Frontend Page Routes
# -------------------------------------------------------------
@app.route("/health")
def health_check():
    return jsonify({"status": "ok"})

@app.route("/")
def serve_index():
    return send_from_directory("static", "index.html")

@app.route("/judges")
@app.route("/judges.html")
def serve_judges_page():
    return send_from_directory("static", "judges.html")

@app.route("/supreme-court-judges")
@app.route("/supreme-court-judges.html")
def serve_supreme_court_judges_page():
    return redirect("/judges.html?court=supreme", code=302)

@app.route("/judge")
@app.route("/judge.html")
def serve_judge_detail_page():
    return send_from_directory("static", "judge.html")

@app.route("/supreme-court-judge")
@app.route("/supreme-court-judge.html")
def serve_supreme_court_judge_detail_page():
    return send_from_directory("static", "supreme-court-judge.html")

@app.route("/pdfs")
@app.route("/pdfs.html")
def serve_pdfs_page():
    return send_from_directory("static", "pdfs.html")

@app.route("/pdf-viewer")
@app.route("/pdf-viewer.html")
def serve_pdf_viewer_page():
    return send_from_directory("static", "pdf-viewer.html")

@app.route("/runs")
@app.route("/runs.html")
def serve_runs_page():
    return send_from_directory("static", "runs.html")


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
@app.route("/api/overview")
def api_overview():
    try:
        stats = data_service.get_overview_stats()
        return jsonify({"success": True, "data": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/judges")
def api_judges():
    try:
        q = request.args.get("q") or request.args.get("query")
        sort_by = request.args.get("sort", "total_pdfs")
        order = request.args.get("order", "desc")
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))

        result = data_service.get_judges(
            query=q,
            sort_by=sort_by,
            sort_order=order,
            page=page,
            limit=limit
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/judge-directory")
def api_judge_directory():
    try:
        result = data_service.get_judge_directory(
            query=request.args.get("q") or request.args.get("query"),
            court=request.args.get("court", "all"),
            sort_by=request.args.get("sort", "record_count"),
            sort_order=request.args.get("order", "desc"),
            page=int(request.args.get("page", 1)),
            limit=int(request.args.get("limit", 20))
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/judges/<path:judge_name>")
def api_judge_detail_path(judge_name):
    try:
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        judge = data_service.get_judge_detail(judge_name, start_date=start_date, end_date=end_date)
        if not judge:
            return jsonify({"success": False, "error": "Judge not found"}), 404
        return jsonify({"success": True, "data": judge})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/judge")
def api_judge_detail_param():
    try:
        judge_name = request.args.get("name")
        if not judge_name:
            return jsonify({"success": False, "error": "Judge name required"}), 400
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        judge = data_service.get_judge_detail(judge_name, start_date=start_date, end_date=end_date)
        if not judge:
            return jsonify({"success": False, "error": "Judge not found"}), 404
        return jsonify({"success": True, "data": judge})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/pdfs")
def api_pdfs():
    try:
        q = request.args.get("q") or request.args.get("query")
        judge = request.args.get("judge")
        date_filter = request.args.get("date")
        court_code = request.args.get("court")
        state_code = request.args.get("state")
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 25))

        result = data_service.get_pdfs(
            query=q,
            judge=judge,
            date_filter=date_filter,
            court_code=court_code,
            state_code=state_code,
            page=page,
            limit=limit
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/pdf/metadata")
def api_pdf_metadata():
    try:
        filename = request.args.get("file") or request.args.get("filename")
        pdf_id = request.args.get("id")
        doc = data_service.get_pdf_details(filename=filename, pdf_id=pdf_id)
        if not doc:
            return jsonify({"success": False, "error": "Document metadata not found"}), 404
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/pdf/<path:filename>")
def serve_pdf(filename):
    """
    Safely streams a cause list PDF directly to browser.
    Supports inline rendering for viewer and attachment for downloads.
    Guards against path traversal attacks.
    """
    download = request.args.get("download", "").lower() in ("1", "true", "yes")
    download_name = os.path.basename(filename)
    safe_path = data_service.get_safe_pdf_path(filename)
    if safe_path and os.path.isfile(safe_path):
        return send_file(
            safe_path,
            mimetype="application/pdf",
            as_attachment=download,
            download_name=download_name
        )

    document = data_service.get_pdf_details(filename=filename)
    if not document or not document.get("has_file"):
        abort(404, description="PDF file not found in local or cloud storage")

    storage_url = storage_service.create_pdf_download_url(
        document["filename"],
        download_name,
        download=download,
    )
    if not storage_url:
        abort(404, description="PDF file not found on disk")
    return redirect(storage_url, code=302)

# -------------------------------------------------------------
# Supreme Court API Endpoints
# -------------------------------------------------------------
@app.route("/api/supreme-court/overview")
def api_supreme_court_overview():
    try:
        stats = data_service.get_supreme_court_overview()
        if not stats:
            return jsonify({"success": True, "data": None, "message": "No Supreme Court data available. Run import_supreme_court.py first."})
        return jsonify({"success": True, "data": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/supreme-court/judges")
def api_supreme_court_judges():
    try:
        q = request.args.get("q") or request.args.get("query")
        sort_by = request.args.get("sort", "total_cases")
        order = request.args.get("order", "desc")
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))

        result = data_service.get_supreme_court_judges(
            query=q,
            sort_by=sort_by,
            sort_order=order,
            page=page,
            limit=limit
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/supreme-court/judges/<path:judge_name>")
def api_supreme_court_judge_detail(judge_name):
    try:
        detail = data_service.get_supreme_court_judge_detail(judge_name)
        if not detail:
            return jsonify({"success": False, "error": "Supreme Court judge not found"}), 404
        return jsonify({"success": True, "data": detail})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/scraper/status")
def api_scraper_status():
    """Returns the current live scraper job."""
    try:
        with SCRAPER_JOB_LOCK:
            live_job = {
                **CURRENT_SCRAPER_JOB,
                "log_lines": list(CURRENT_SCRAPER_JOB["log_lines"])
            }
        return jsonify({"success": True, "live_job": live_job})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@lru_cache(maxsize=1)
def _get_scraper_court_options():
    scraper_path = os.path.join(BASE_DIR, "scraper", "1.py")
    with open(scraper_path, "r", encoding="utf-8") as scraper_file:
        scraper_tree = ast.parse(scraper_file.read(), filename=scraper_path)

    scraper_assignments = {
        target.id: node.value
        for node in scraper_tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"HIGH_COURTS", "STATE_ALIASES"}
    }
    if "HIGH_COURTS" not in scraper_assignments:
        raise RuntimeError("HIGH_COURTS catalogue was not found in scraper/1.py")

    court_rows = ast.literal_eval(scraper_assignments["HIGH_COURTS"])
    aliases = ast.literal_eval(scraper_assignments.get("STATE_ALIASES", ast.Dict(keys=[], values=[])))
    states = sorted(
        { (state_code, state_name) for state_code, _, state_name, _ in court_rows },
        key=lambda state: state[1].casefold()
    )
    return {
        "states": [
            {
                "state_code": state_code,
                "state_name": state_name,
                "aliases": [
                    alias.title()
                    for alias, alias_code in aliases.items()
                    if alias_code == state_code and alias.casefold() != state_name.casefold()
                ]
            }
            for state_code, state_name in states
        ],
        "courts": [
        {
            "state_code": state_code,
            "state_name": state_name,
            "court_code": court_code or "1",
            "court_name": court_name
        }
        for state_code, court_code, state_name, court_name in court_rows
        ]
    }

@app.route("/api/scraper/options")
def api_scraper_options():
    try:
        return jsonify({"success": True, **_get_scraper_court_options()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def _append_scraper_log_locked(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines = CURRENT_SCRAPER_JOB["log_lines"]
    log_lines.append(f"[{timestamp}] {message}")
    overflow = len(log_lines) - SCRAPER_LOG_MAX_LINES
    if overflow > 0:
        del log_lines[:overflow]
        CURRENT_SCRAPER_JOB["log_lines_dropped"] += overflow


def _append_scraper_log(message):
    with SCRAPER_JOB_LOCK:
        _append_scraper_log_locked(message)

def _run_scraper_worker(state_arg, court_arg, days_arg):
    try:
        # Launch scraper/1.py without altering its code
        cmd = [
            sys.executable,
            "-u",
            os.path.join(BASE_DIR, "scraper", "1.py"),
            "--state", str(state_arg),
            "--court", str(court_arg) if court_arg else "1",
            "--days", str(days_arg)
        ]

        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )

        for line in iter(proc.stdout.readline, ''):
            if line:
                _append_scraper_log(line.rstrip())

        proc.wait()
        with SCRAPER_JOB_LOCK:
            CURRENT_SCRAPER_JOB["return_code"] = proc.returncode
        if proc.returncode != 0:
            raise RuntimeError(f"Scraper exited with code {proc.returncode}")

        # Refresh disk cache after download
        data_service.get_disk_pdf_index(force=True)
    except Exception as e:
        with SCRAPER_JOB_LOCK:
            CURRENT_SCRAPER_JOB["error"] = str(e)
    finally:
        with SCRAPER_JOB_LOCK:
            failed = bool(CURRENT_SCRAPER_JOB["error"])
            CURRENT_SCRAPER_JOB["status"] = "failed" if failed else "completed"
            CURRENT_SCRAPER_JOB["is_running"] = False
            CURRENT_SCRAPER_JOB["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            started_at = datetime.strptime(CURRENT_SCRAPER_JOB["started_at"], "%Y-%m-%d %H:%M:%S")
            finished_at = datetime.strptime(CURRENT_SCRAPER_JOB["finished_at"], "%Y-%m-%d %H:%M:%S")
            CURRENT_SCRAPER_JOB["duration_seconds"] = max(0, int((finished_at - started_at).total_seconds()))
            outcome = (
                f"SCRAPE FAILED: {CURRENT_SCRAPER_JOB['error']}"
                if failed else "SCRAPE SUCCESSFUL: scraper finished and the PDF index was refreshed."
            )
            _append_scraper_log_locked(outcome)

@app.route("/api/scraper/trigger", methods=["POST"])
def api_scraper_trigger():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Expected a JSON object"}), 400

    state_code = str(payload.get("state_code", "1")).strip()
    court_code = str(payload.get("court_code", "1")).strip()
    try:
        days = int(payload.get("days", 3))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Days must be a positive whole number"}), 400

    if not state_code.isdigit() or not court_code.isdigit():
        return jsonify({"success": False, "error": "State and court codes must be numeric"}), 400
    if days < 1:
        return jsonify({"success": False, "error": "Days must be at least 1"}), 400

    court_options = _get_scraper_court_options()
    selected_court = next(
        (
            court for court in court_options["courts"]
            if court["state_code"] == state_code and court["court_code"] == court_code
        ),
        None
    )
    if selected_court:
        court_info = (
            f"{selected_court['state_name']} - {selected_court['court_name']} "
            f"(state {state_code}, court {court_code}), last {days} day(s)"
        )
        start_message = (
            f"Starting scrape for {selected_court['state_name']} - "
            f"{selected_court['court_name']}, last {days} day(s)."
        )
    else:
        court_info = f"State {state_code}, court {court_code}, last {days} day(s)"
        start_message = f"Starting scrape: {court_info}."

    with SCRAPER_JOB_LOCK:
        if CURRENT_SCRAPER_JOB["is_running"]:
            return jsonify({"success": False, "error": "A scraper job is already active"}), 400

        CURRENT_SCRAPER_JOB.update({
            "is_running": True,
            "status": "running",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "duration_seconds": None,
            "court_info": court_info,
            "log_lines": [],
            "log_lines_dropped": 0,
            "error": None,
            "return_code": None
        })

    _append_scraper_log(start_message)

    t = threading.Thread(
        target=_run_scraper_worker,
        args=(state_code, court_code, days),
        daemon=True
    )
    try:
        t.start()
    except RuntimeError as e:
        with SCRAPER_JOB_LOCK:
            CURRENT_SCRAPER_JOB.update({
                "is_running": False,
                "status": "failed",
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e)
            })
        return jsonify({"success": False, "error": f"Could not start scraper: {e}"}), 500

    return jsonify({"success": True, "message": "Scraper job started in background"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Starting eCourts Judicial Intelligence Platform on http://127.0.0.1:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)

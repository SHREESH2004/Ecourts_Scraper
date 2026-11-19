"""
Daily Analytics Service for the All-India PDF Intelligence Engine.

Provides separate and combined daily analytics for:
- Supreme Court (`supreme_court`)
- High Courts (`high_court`)
- District & Subordinate Courts (`district_court`)

Supports comparison by:
- Date
- State
- District
- Court category (`supreme_court`, `high_court`, `district_court`)
- High Court bench
- District court complex
- Court establishment

Counts PDFs and individual extracted cases separately and tracks cause-list
documents/cases separately from daily orders and final judgments (never mixing
cause-list listings with judgment outcomes).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from typing import Any, Dict, List, Optional

from .repository import PDFIntelligenceRepository, _fmt_date, _parse_json_field

CAUSE_LIST_CATEGORIES = {"daily_cause_list", "supplementary_cause_list"}
ORDER_JUDGMENT_CATEGORIES = {"daily_order", "final_judgment"}


class PDFAnalyticsService:
    """
    Aggregates and queries daily intelligence metrics across Supreme Court,
    High Courts, and District Courts from `pi_documents`, `pi_case_records`,
    and `pi_daily_analytics`.
    """

    def __init__(self, repo: PDFIntelligenceRepository):
        self.repo = repo

    def refresh_daily_analytics(
        self,
        court_type: Optional[str] = None,
        state_code: Optional[str] = None,
        bench_code: Optional[str] = None,
        target_dates: Optional[List[date | str]] = None,
    ) -> int:
        """
        Recompute daily analytics from stored `pi_documents` and `pi_case_records`
        and upsert rows into `pi_daily_analytics`.
        """
        self.repo.ensure_initialized()

        clauses: List[str] = []
        params: List[Any] = []
        if court_type:
            clauses.append("court_type = %s")
            params.append(court_type.strip().lower())
        if state_code:
            clauses.append("UPPER(state_code) = UPPER(%s)")
            params.append(state_code.strip())
        if bench_code:
            clauses.append("UPPER(bench_code) = UPPER(%s)")
            params.append(bench_code.strip())
        if target_dates:
            placeholders = ", ".join(["%s"] * len(target_dates))
            clauses.append(f"listing_date IN ({placeholders})")
            params.extend([d.isoformat() if hasattr(d, "isoformat") else str(d) for d in target_dates])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.repo.transaction() as (cur, is_sqlite):
            cur.execute(
                f"""
                SELECT
                    listing_date,
                    court_type,
                    state_code,
                    state_name,
                    district_code,
                    district_name,
                    complex_code,
                    complex_name,
                    establishment_code,
                    establishment_name,
                    court_code,
                    court_name,
                    bench_code,
                    bench_name,
                    COUNT(*) AS pdfs_discovered,
                    COUNT(CASE WHEN download_status IN ('downloaded', 'already_processed', 'duplicate_hash') THEN 1 END) AS pdfs_downloaded,
                    COUNT(CASE WHEN extraction_status IN ('completed', 'ocr_completed') THEN 1 END) AS pdfs_processed,
                    COUNT(CASE WHEN document_category IN ('daily_cause_list', 'supplementary_cause_list') THEN 1 END) AS cause_list_pdfs,
                    COUNT(CASE WHEN document_category IN ('daily_order', 'final_judgment') THEN 1 END) AS order_judgment_pdfs,
                    COUNT(CASE WHEN download_status = 'failed' OR extraction_status = 'failed' THEN 1 END) AS extraction_failures
                FROM pi_documents
                {where_sql}
                GROUP BY
                    listing_date, court_type, state_code, state_name,
                    district_code, district_name, complex_code, complex_name,
                    establishment_code, establishment_name,
                    court_code, court_name, bench_code, bench_name
                """,
                params,
            )
            doc_groups = cur.fetchall()

            updated_count = 0
            for grp in doc_groups:
                ldate = _fmt_date(grp["listing_date"]) or ""
                ctype = grp["court_type"]
                scode = grp.get("state_code")
                dcode = grp.get("district_code")
                cx_code = grp.get("complex_code")
                est_code = grp.get("establishment_code")
                ccode = grp["court_code"]
                bcode = grp["bench_code"]

                scope_key = (
                    f"{ldate}|{ctype}|{scode or 'NAT'}|{dcode or '-'}|"
                    f"{cx_code or '-'}|{est_code or '-'}|{ccode}|{bcode}"
                )

                case_clauses = [
                    "listing_date = %s",
                    "court_type = %s",
                    "court_code = %s",
                    "bench_code = %s",
                ]
                case_params: List[Any] = [
                    ldate if is_sqlite else grp["listing_date"],
                    ctype,
                    ccode,
                    bcode,
                ]
                if scode is not None:
                    case_clauses.append("state_code = %s")
                    case_params.append(scode)
                else:
                    case_clauses.append("state_code IS NULL")

                if dcode is not None:
                    case_clauses.append("district_code = %s")
                    case_params.append(dcode)
                else:
                    case_clauses.append("district_code IS NULL")

                if cx_code is not None:
                    case_clauses.append("complex_code = %s")
                    case_params.append(cx_code)

                cur.execute(
                    f"""
                    SELECT case_type, judge_names, document_category
                    FROM pi_case_records
                    WHERE {' AND '.join(case_clauses)}
                    """,
                    case_params,
                )
                case_rows = cur.fetchall()

                total_cases = len(case_rows)
                cause_list_cases = 0
                order_judgment_cases = 0
                type_counter: Counter[str] = Counter()
                judge_counter: Counter[str] = Counter()

                for cr in case_rows:
                    doc_cat = (cr.get("document_category") or "daily_cause_list").strip()
                    if doc_cat in CAUSE_LIST_CATEGORIES:
                        cause_list_cases += 1
                    elif doc_cat in ORDER_JUDGMENT_CATEGORIES:
                        order_judgment_cases += 1

                    ct = (cr.get("case_type") or "UNKNOWN").strip()
                    type_counter[ct] += 1
                    j_raw = (cr.get("judge_names") or "").strip()
                    if j_raw:
                        for j_part in j_raw.split(";"):
                            jp = j_part.strip()
                            if jp:
                                judge_counter[jp] += 1

                discovered = int(grp["pdfs_discovered"] or 0)
                downloaded = int(grp["pdfs_downloaded"] or 0)
                processed = int(grp["pdfs_processed"] or 0)
                cl_pdfs = int(grp["cause_list_pdfs"] or 0)
                oj_pdfs = int(grp["order_judgment_pdfs"] or 0)
                failures = int(grp["extraction_failures"] or 0)
                success_rate = round((processed / discovered) * 100.0, 2) if discovered > 0 else 0.0

                type_json = json.dumps(dict(type_counter.most_common(50)))
                judge_json = json.dumps(dict(judge_counter.most_common(50)))

                upsert_params = (
                    scope_key,
                    ldate if is_sqlite else grp["listing_date"],
                    ctype,
                    scode,
                    grp.get("state_name"),
                    dcode,
                    grp.get("district_name"),
                    cx_code,
                    grp.get("complex_name"),
                    est_code,
                    grp.get("establishment_name"),
                    ccode,
                    grp["court_name"],
                    bcode,
                    grp["bench_name"],
                    discovered,
                    downloaded,
                    processed,
                    cl_pdfs,
                    oj_pdfs,
                    total_cases,
                    cause_list_cases,
                    order_judgment_cases,
                    failures,
                    success_rate,
                    type_json,
                    judge_json,
                )

                if is_sqlite:
                    cur.execute(
                        """
                        INSERT INTO pi_daily_analytics (
                            analytics_scope_key, analytics_date, court_type,
                            state_code, state_name, district_code, district_name,
                            complex_code, complex_name, establishment_code, establishment_name,
                            court_code, court_name, bench_code, bench_name,
                            pdfs_discovered, pdfs_downloaded, pdfs_processed,
                            cause_list_pdfs, order_judgment_pdfs,
                            total_case_records, cause_list_cases, order_judgment_cases,
                            extraction_failures, processing_success_rate,
                            cases_by_type, cases_by_judge, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (analytics_scope_key)
                        DO UPDATE SET
                            pdfs_discovered = EXCLUDED.pdfs_discovered,
                            pdfs_downloaded = EXCLUDED.pdfs_downloaded,
                            pdfs_processed = EXCLUDED.pdfs_processed,
                            cause_list_pdfs = EXCLUDED.cause_list_pdfs,
                            order_judgment_pdfs = EXCLUDED.order_judgment_pdfs,
                            total_case_records = EXCLUDED.total_case_records,
                            cause_list_cases = EXCLUDED.cause_list_cases,
                            order_judgment_cases = EXCLUDED.order_judgment_cases,
                            extraction_failures = EXCLUDED.extraction_failures,
                            processing_success_rate = EXCLUDED.processing_success_rate,
                            cases_by_type = EXCLUDED.cases_by_type,
                            cases_by_judge = EXCLUDED.cases_by_judge,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        upsert_params,
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO pi_daily_analytics (
                            analytics_scope_key, analytics_date, court_type,
                            state_code, state_name, district_code, district_name,
                            complex_code, complex_name, establishment_code, establishment_name,
                            court_code, court_name, bench_code, bench_name,
                            pdfs_discovered, pdfs_downloaded, pdfs_processed,
                            cause_list_pdfs, order_judgment_pdfs,
                            total_case_records, cause_list_cases, order_judgment_cases,
                            extraction_failures, processing_success_rate,
                            cases_by_type, cases_by_judge, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s::jsonb, %s::jsonb, NOW()
                        )
                        ON CONFLICT (analytics_scope_key)
                        DO UPDATE SET
                            pdfs_discovered = EXCLUDED.pdfs_discovered,
                            pdfs_downloaded = EXCLUDED.pdfs_downloaded,
                            pdfs_processed = EXCLUDED.pdfs_processed,
                            cause_list_pdfs = EXCLUDED.cause_list_pdfs,
                            order_judgment_pdfs = EXCLUDED.order_judgment_pdfs,
                            total_case_records = EXCLUDED.total_case_records,
                            cause_list_cases = EXCLUDED.cause_list_cases,
                            order_judgment_cases = EXCLUDED.order_judgment_cases,
                            extraction_failures = EXCLUDED.extraction_failures,
                            processing_success_rate = EXCLUDED.processing_success_rate,
                            cases_by_type = EXCLUDED.cases_by_type,
                            cases_by_judge = EXCLUDED.cases_by_judge,
                            updated_at = NOW()
                        """,
                        upsert_params,
                    )
                updated_count += 1

        return updated_count

    def get_daily_analytics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        court_type: Optional[str] = None,
        bench_code: Optional[str] = None,
        complex_code: Optional[str] = None,
        establishment_code: Optional[str] = None,
        drilldown_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return comprehensive daily analytics with separate and combined summaries
        for Supreme Court, High Courts, and District Courts, plus comparison by
        date, state, district, court category, High Court bench, District Court
        complex, and establishment.
        """
        self.repo.ensure_initialized()
        self.refresh_daily_analytics(
            court_type=court_type,
            state_code=state_code,
            bench_code=bench_code,
        )

        clauses: List[str] = []
        params: List[Any] = []

        if start_date:
            clauses.append("analytics_date >= %s")
            params.append(start_date.strip())
        if end_date:
            clauses.append("analytics_date <= %s")
            params.append(end_date.strip())
        if court_type:
            clauses.append("court_type = %s")
            params.append(court_type.strip().lower())
        if state_code:
            clauses.append("UPPER(state_code) = UPPER(%s)")
            params.append(state_code.strip())
        if district_code:
            clauses.append("UPPER(district_code) = UPPER(%s)")
            params.append(district_code.strip())
        if complex_code:
            clauses.append("UPPER(complex_code) = UPPER(%s)")
            params.append(complex_code.strip())
        if establishment_code:
            clauses.append("(UPPER(establishment_code) = UPPER(%s) OR UPPER(bench_code) = UPPER(%s))")
            params.extend([establishment_code.strip(), establishment_code.strip()])
        if bench_code:
            clauses.append("UPPER(bench_code) = UPPER(%s)")
            params.append(bench_code.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.repo.transaction() as (cur, _):
            cur.execute(
                f"""
                SELECT * FROM pi_daily_analytics
                {where_sql}
                ORDER BY analytics_date DESC, court_type ASC, COALESCE(state_name, 'National') ASC, bench_name ASC
                """,
                params,
            )
            rows = cur.fetchall()

        total_discovered = 0
        total_downloaded = 0
        total_processed = 0
        total_cl_pdfs = 0
        total_oj_pdfs = 0
        total_cases = 0
        total_cl_cases = 0
        total_oj_cases = 0
        total_failures = 0

        by_category_summary: Dict[str, Dict[str, Any]] = {
            "supreme_court": {
                "court_type": "supreme_court",
                "label": "Supreme Court of India",
                "pdfs_discovered": 0,
                "pdfs_downloaded": 0,
                "pdfs_processed": 0,
                "cause_list_pdfs": 0,
                "order_judgment_pdfs": 0,
                "total_case_records": 0,
                "cause_list_cases": 0,
                "order_judgment_cases": 0,
                "extraction_failures": 0,
            },
            "high_court": {
                "court_type": "high_court",
                "label": "High Courts",
                "pdfs_discovered": 0,
                "pdfs_downloaded": 0,
                "pdfs_processed": 0,
                "cause_list_pdfs": 0,
                "order_judgment_pdfs": 0,
                "total_case_records": 0,
                "cause_list_cases": 0,
                "order_judgment_cases": 0,
                "extraction_failures": 0,
            },
            "district_court": {
                "court_type": "district_court",
                "label": "District & Subordinate Courts",
                "pdfs_discovered": 0,
                "pdfs_downloaded": 0,
                "pdfs_processed": 0,
                "cause_list_pdfs": 0,
                "order_judgment_pdfs": 0,
                "total_case_records": 0,
                "cause_list_cases": 0,
                "order_judgment_cases": 0,
                "extraction_failures": 0,
            },
        }

        by_date_map: Dict[str, Dict[str, Any]] = {}
        by_bench_map: Dict[str, Dict[str, Any]] = {}
        by_complex_map: Dict[str, Dict[str, Any]] = {}
        type_totals: Counter[str] = Counter()
        judge_totals: Counter[str] = Counter()

        for r in rows:
            d_str = _fmt_date(r["analytics_date"]) or ""
            ctype = r["court_type"]
            disc = int(r["pdfs_discovered"] or 0)
            dl = int(r["pdfs_downloaded"] or 0)
            proc = int(r["pdfs_processed"] or 0)
            cl_pdfs = int(r.get("cause_list_pdfs") or 0)
            oj_pdfs = int(r.get("order_judgment_pdfs") or 0)
            cases = int(r["total_case_records"] or 0)
            cl_cases = int(r.get("cause_list_cases") or 0)
            oj_cases = int(r.get("order_judgment_cases") or 0)
            fails = int(r["extraction_failures"] or 0)

            total_discovered += disc
            total_downloaded += dl
            total_processed += proc
            total_cl_pdfs += cl_pdfs
            total_oj_pdfs += oj_pdfs
            total_cases += cases
            total_cl_cases += cl_cases
            total_oj_cases += oj_cases
            total_failures += fails

            if ctype in by_category_summary:
                cat_s = by_category_summary[ctype]
                cat_s["pdfs_discovered"] += disc
                cat_s["pdfs_downloaded"] += dl
                cat_s["pdfs_processed"] += proc
                cat_s["cause_list_pdfs"] += cl_pdfs
                cat_s["order_judgment_pdfs"] += oj_pdfs
                cat_s["total_case_records"] += cases
                cat_s["cause_list_cases"] += cl_cases
                cat_s["order_judgment_cases"] += oj_cases
                cat_s["extraction_failures"] += fails

            if d_str not in by_date_map:
                by_date_map[d_str] = {
                    "date": d_str,
                    "pdfs_discovered": 0,
                    "pdfs_downloaded": 0,
                    "pdfs_processed": 0,
                    "cause_list_pdfs": 0,
                    "order_judgment_pdfs": 0,
                    "total_case_records": 0,
                    "cause_list_cases": 0,
                    "order_judgment_cases": 0,
                    "extraction_failures": 0,
                    "processing_success_rate": 0.0,
                }
            d_entry = by_date_map[d_str]
            d_entry["pdfs_discovered"] += disc
            d_entry["pdfs_downloaded"] += dl
            d_entry["pdfs_processed"] += proc
            d_entry["cause_list_pdfs"] += cl_pdfs
            d_entry["order_judgment_pdfs"] += oj_pdfs
            d_entry["total_case_records"] += cases
            d_entry["cause_list_cases"] += cl_cases
            d_entry["order_judgment_cases"] += oj_cases
            d_entry["extraction_failures"] += fails

            bench_key = f"{ctype}|{r.get('state_code') or 'NAT'}|{r.get('district_code') or '-'}|{r['court_code']}|{r['bench_code']}"
            if bench_key not in by_bench_map:
                by_bench_map[bench_key] = {
                    "court_type": ctype,
                    "state_code": r.get("state_code"),
                    "state_name": r.get("state_name") or "National (Supreme Court)",
                    "district_code": r.get("district_code"),
                    "district_name": r.get("district_name") or "National",
                    "complex_code": r.get("complex_code"),
                    "complex_name": r.get("complex_name"),
                    "establishment_code": r.get("establishment_code"),
                    "establishment_name": r.get("establishment_name"),
                    "court_code": r["court_code"],
                    "court_name": r["court_name"],
                    "bench_code": r["bench_code"],
                    "bench_name": r["bench_name"],
                    "pdfs_discovered": 0,
                    "pdfs_downloaded": 0,
                    "pdfs_processed": 0,
                    "total_case_records": 0,
                    "extraction_failures": 0,
                    "processing_success_rate": 0.0,
                }
            b_entry = by_bench_map[bench_key]
            b_entry["pdfs_discovered"] += disc
            b_entry["pdfs_downloaded"] += dl
            b_entry["pdfs_processed"] += proc
            b_entry["total_case_records"] += cases
            b_entry["extraction_failures"] += fails

            if ctype == "district_court" and r.get("complex_code"):
                cx_key = f"{r.get('state_code')}|{r.get('district_code')}|{r.get('complex_code')}"
                if cx_key not in by_complex_map:
                    by_complex_map[cx_key] = {
                        "state_code": r.get("state_code"),
                        "state_name": r.get("state_name"),
                        "district_code": r.get("district_code"),
                        "district_name": r.get("district_name"),
                        "complex_code": r.get("complex_code"),
                        "complex_name": r.get("complex_name"),
                        "pdfs_discovered": 0,
                        "pdfs_processed": 0,
                        "total_case_records": 0,
                    }
                by_complex_map[cx_key]["pdfs_discovered"] += disc
                by_complex_map[cx_key]["pdfs_processed"] += proc
                by_complex_map[cx_key]["total_case_records"] += cases

            c_by_type = _parse_json_field(r.get("cases_by_type"), {})
            if isinstance(c_by_type, dict):
                for k, v in c_by_type.items():
                    type_totals[str(k)] += int(v or 0)

            c_by_judge = _parse_json_field(r.get("cases_by_judge"), {})
            if isinstance(c_by_judge, dict):
                for k, v in c_by_judge.items():
                    judge_totals[str(k)] += int(v or 0)

        daily_series: List[Dict[str, Any]] = []
        for d_str in sorted(by_date_map.keys(), reverse=True):
            item = by_date_map[d_str]
            disc = item["pdfs_discovered"]
            item["processing_success_rate"] = round((item["pdfs_processed"] / disc) * 100.0, 2) if disc > 0 else 0.0
            daily_series.append(item)

        cases_by_court_bench: List[Dict[str, Any]] = []
        for b_item in by_bench_map.values():
            disc = b_item["pdfs_discovered"]
            b_item["processing_success_rate"] = round((b_item["pdfs_processed"] / disc) * 100.0, 2) if disc > 0 else 0.0
            cases_by_court_bench.append(b_item)
        cases_by_court_bench.sort(key=lambda x: (x["total_case_records"], x["pdfs_processed"]), reverse=True)

        overall_success_rate = (
            round((total_processed / total_discovered) * 100.0, 2) if total_discovered > 0 else 0.0
        )

        drilldown_payload = None
        if drilldown_date:
            docs_page = self.repo.list_documents(
                court_type=court_type,
                state_code=state_code,
                district_code=district_code,
                complex_code=complex_code,
                establishment_code=establishment_code,
                bench_code=bench_code,
                listing_date=drilldown_date,
                page=1,
                limit=100,
            )
            cases_page = self.repo.list_case_records(
                court_type=court_type,
                state_code=state_code,
                district_code=district_code,
                complex_code=complex_code,
                establishment_code=establishment_code,
                bench_code=bench_code,
                listing_date=drilldown_date,
                page=1,
                limit=200,
            )
            drilldown_payload = {
                "date": drilldown_date,
                "documents": docs_page["items"],
                "documents_total": docs_page["total"],
                "cases": cases_page["items"],
                "cases_total": cases_page["total"],
            }

        return {
            "summary": {
                "pdfs_discovered": total_discovered,
                "pdfs_downloaded": total_downloaded,
                "pdfs_processed": total_processed,
                "cause_list_pdfs": total_cl_pdfs,
                "order_judgment_pdfs": total_oj_pdfs,
                "total_case_records": total_cases,
                "cause_list_cases": total_cl_cases,
                "order_judgment_cases": total_oj_cases,
                "extraction_failures": total_failures,
                "processing_success_rate": overall_success_rate,
                "days_count": len(daily_series),
            },
            "by_court_category": by_category_summary,
            "daily_series": daily_series,
            "cases_by_type": [
                {"case_type": ct, "count": cnt}
                for ct, cnt in type_totals.most_common(30)
            ],
            "cases_by_court_bench": cases_by_court_bench,
            "cases_by_complex": sorted(
                list(by_complex_map.values()),
                key=lambda x: x["total_case_records"],
                reverse=True,
            ),
            "cases_by_judge": [
                {"judge_name": jn, "case_count": cnt}
                for jn, cnt in judge_totals.most_common(30)
            ],
            "drilldown": drilldown_payload,
        }


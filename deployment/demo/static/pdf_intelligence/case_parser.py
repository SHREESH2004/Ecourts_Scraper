"""
Multi-Case Record Parser for Supreme Court, High Court, and District Court PDFs.

Splits a PDF's extracted text into individual structured case records
(1 PDF -> N cases) with confidence scoring and tier-specific field extraction:
- Supreme Court: Diary number, Case number, Case type, Petitioner, Respondent,
  Advocate-on-Record (AOR), Court number, Judge(s), Listing date, Order/Judgment date.
- High Courts: Case number, Case type, CNR, Petitioner, Respondent, Advocates,
  Court hall/room, Judge(s), Listing date, Order/Judgment date.
- District Courts: CNR number, Case number, Filing number, Case type, Party names,
  Petitioner, Respondent, Advocate, Court complex, Court establishment, Judge,
  Listing date, Order date, Judgment date.
Never fabricates missing values or treats a cause list as a judgment.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .pdf_extractor import PDFExtractionResult

# Comprehensive regex patterns for Supreme Court, High Court, and District Court case numbers
CASE_NUMBER_REGEX = re.compile(
    r"(?:(?P<item_no>\b\d{1,4}(?:\.\d+)?)\s*[\).:-]?\s+)?"
    r"(?P<connected_prefix>\b(?:WITH|AND\s+WITH)\s+)?"
    r"(?P<case_type>"
    r"(?:SLP\s*\(\s*(?:C|CRL\.?|CIVIL|CRIMINAL)\s*\)|"
    r"W\.?P\.?\s*\(\s*(?:C|CRL\.?|CIVIL|CRIMINAL)\s*\)|"
    r"CRL\.?\s*[A-Z.()]{1,10}|"
    r"C\.?A\.?|"
    r"T\.?P\.?\s*\(\s*(?:C|CRL\.?)\s*\)|"
    r"R\.?P\.?\s*\(\s*(?:C|CRL\.?)\s*\)|"
    r"CURATIVE\s+PET|MA|CONTMT\.?\s*PET|"
    r"SPL\.?\s*CASE|CRI\.?\s*M\.?A\.?|RCS|R\.?C\.?S\.?|M\.?A\.?C\.?P\.?|CC|O\.?S\.?|"
    r"[A-Z][A-Z0-9.()&-]{1,18})"
    r"(?:\s+(?:NO\.?|APPLN\.?|APPEAL|PETITION|CASE|PIL|WRIT|SIDE|[A-Z0-9.()&-]{1,10})){0,2}"
    r")"
    r"\s*(?:/|\s+No\.?\s*[-:]?\s*|\s+)"
    r"(?P<case_num>\d{1,7}(?:\s*-\s*\d{1,7})?)"
    r"\s*(?:/|\s+of\s+|\s*-\s*)"
    r"(?P<case_year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)

CNR_REGEX = re.compile(r"\b([A-Z]{4}\d{12})\b")

DIARY_NUMBER_REGEX = re.compile(
    r"\b(?:Diary\s*(?:No\.?|Number)\s*[:\-]?\s*)(?P<dnum>\d{1,7}\s*[/\-]\s*(?:19|20)\d{2})\b",
    re.IGNORECASE,
)

FILING_NUMBER_REGEX = re.compile(
    r"\b(?:Filing\s*(?:No\.?|Number)\s*[:\-]?\s*)(?P<fnum>[A-Z0-9/\-]{2,18}\s*[/\-]\s*(?:19|20)\d{2})\b",
    re.IGNORECASE,
)

AOR_REGEX = re.compile(
    r"\b(?:AOR|Advocate[- ]on[- ]Record)\s*[:\-]?\s*(?P<aor>[A-Z][A-Za-z.\s,&()-]{3,90})",
    re.IGNORECASE,
)

EXPLICIT_JUDGMENT_DATE_REGEX = re.compile(
    r"\b(?:Date\s+of\s+(?:Judgment|Judgement|Decision|Pronouncement)|"
    r"(?:Judgment|Judgement)\s+(?:Dated|Pronounced\s+on)|"
    r"Decided\s+on)\s*[:\-]?\s*"
    r"(?P<jdate>"
    r"\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,]?\s+(?:19|20)\d{2}"
    r")",
    re.IGNORECASE,
)

EXPLICIT_ORDER_DATE_REGEX = re.compile(
    r"\b(?:Date\s+of\s+Order|Order\s+Dated|Order\s+Pronounced\s+on)\s*[:\-]?\s*"
    r"(?P<odate>"
    r"\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,]?\s+(?:19|20)\d{2}"
    r")",
    re.IGNORECASE,
)

HEADER_LISTING_DATE_REGEX = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[,]?\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)

COURT_ROOM_REGEX = re.compile(
    r"\b(CHIEF\s+JUSTICE'?S?\s+COURT|COURT\s*(?:NO\.?|NUMBER|HALL)\s*[:.\-]?\s*[A-Z0-9-]+(?:\s+[^\n\r]{1,35})?)",
    re.IGNORECASE,
)

ADVOCATE_MARKER_REGEX = re.compile(
    r"\b(?:AOR\s*[:\-]?|Advocate[- ]on[- ]Record\s*[:\-]?|Adv(?:ocate)?s?\s*(?:for)?|Counsel\s+for|"
    r"GP\s+FOR|G\.?P\.?\s+FOR|P\.?P\.?\s+FOR|APP\s+FOR|A\.?G\.?P\.?\s+FOR|SC\s+FOR|"
    r"MR\.?\s+|MS\.?\s+|MRS\.?\s+|SHRI\s+|SMT\.?\s+)",
    re.IGNORECASE,
)

NOISE_LINE_REGEX = re.compile(
    r"^(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|"
    r"\d+\s*/\s*\d+|"
    r"sr\.?\s*no\.?\s+case\s+no|"
    r"s\.?\s*no\.?\s+case|"
    r"item\s+no\.?\s+case|"
    r"[-=_*]{4,}|"
    r"published\s+under\s+the\s+authority.*)$",
    re.IGNORECASE,
)

DISALLOWED_CASE_TYPES = {
    "PAGE", "COURT", "DATE", "TIME", "ROOM", "HALL", "FLOOR", "ITEM",
    "PART", "LIST", "DATED", "ORDER", "RULE", "SECTION", "ACT", "UNDER",
    "COPY", "TOTAL", "FOR", "AND", "WITH", "FROM", "BEFORE", "CORAM",
    "DIARY", "FILING",
}


@dataclass
class ParsedCaseRecord:
    case_sequence: int
    item_number: str
    case_number: str
    case_type: str
    case_year: Optional[int]
    cnr_number: str
    diary_number: str
    filing_number: str
    case_title: str
    petitioner: str
    respondent: str
    advocates: str
    advocate_on_record: str
    listing_date: str
    order_date: Optional[str]  # Populated ONLY if document provides an order date
    judgment_date: Optional[str]  # Populated ONLY if document provides a judgment date
    judge_names: str
    court_room: str
    document_category: str
    page_number: int
    extraction_status: str
    confidence: float
    confidence_label: str
    raw_excerpt: str
    extracted_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _parse_date_string(raw_date: str) -> Optional[str]:
    """Parse common Indian judicial date formats into YYYY-MM-DD."""
    cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)\b", r"\1", raw_date.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned.replace(",", "")).strip()
    formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_case_type(raw_type: str) -> str:
    """Clean and normalize a parsed case type token."""
    cleaned = re.sub(r"^(?:WITH|AND|IN|FOR|ON|PP|ADVOCATE|ED)\s+", "", raw_type.strip(), flags=re.I)
    cleaned = re.sub(r"\s+NO\.?$", "", cleaned.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-/").upper()
    return cleaned


def _is_valid_case_type(case_type: str) -> bool:
    if not case_type or len(case_type) < 2 or len(case_type) > 28:
        return False
    first_word = case_type.split()[0].strip(".()")
    if first_word in DISALLOWED_CASE_TYPES:
        return False
    if not any(ch.isalpha() for ch in case_type):
        return False
    return True


def _extract_header_metadata(
    full_text: str,
    fallback_judge: str = "",
    fallback_date: Optional[date] = None,
    fallback_court_room: str = "",
    document_category: str = "daily_cause_list",
) -> Dict[str, Any]:
    """
    Extract document-level court room/number, presiding judge(s), listing date,
    order date, and explicit judgment date from the document header.
    Never sets judgment_date on a cause list unless the document explicitly states it.
    """
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    header_slice = "\n".join(lines[:40])

    # 1. Court room / number
    court_room = fallback_court_room or ""
    cr_match = COURT_ROOM_REGEX.search(header_slice)
    if cr_match:
        court_room = re.sub(r"\s+", " ", cr_match.group(1)).strip()

    # 2. Judges / Coram
    judges_found: List[str] = []
    for i, ln in enumerate(lines[:40]):
        upper = ln.upper()
        if any(tok in upper for tok in ("HON'BLE", "HONBLE", "HONOURABLE", "JUSTICE", "CORAM", "JUDGE")):
            if "CAUSE LIST" in upper or "HIGH COURT" in upper or "SUPREME COURT" in upper:
                continue
            cleaned_j = re.sub(r"^(?:CORAM|BEFORE)\s*[:\-]?\s*", "", ln, flags=re.I).strip()
            if cleaned_j and len(cleaned_j) > 4:
                judges_found.append(cleaned_j)
            elif i + 1 < len(lines[:40]):
                next_ln = lines[i + 1].strip()
                if "JUSTICE" in next_ln.upper() or "HON" in next_ln.upper() or "JUDGE" in next_ln.upper():
                    judges_found.append(next_ln)

    judge_names = "; ".join(dict.fromkeys(judges_found)) if judges_found else (fallback_judge or "").strip()

    # 3. Listing date
    listing_date_iso = (
        fallback_date.isoformat()
        if hasattr(fallback_date, "isoformat")
        else (str(fallback_date) if fallback_date else "")
    )
    if not listing_date_iso:
        m_date = HEADER_LISTING_DATE_REGEX.search(header_slice)
        if m_date:
            parsed = _parse_date_string(f"{m_date.group('day')} {m_date.group('month')} {m_date.group('year')}")
            if parsed:
                listing_date_iso = parsed

    # 4. Explicit order date & judgment date
    explicit_odate: Optional[str] = None
    o_match = EXPLICIT_ORDER_DATE_REGEX.search(full_text)
    if o_match:
        explicit_odate = _parse_date_string(o_match.group("odate"))
    elif document_category == "daily_order" and listing_date_iso:
        explicit_odate = listing_date_iso

    explicit_jdate: Optional[str] = None
    j_match = EXPLICIT_JUDGMENT_DATE_REGEX.search(full_text)
    if j_match:
        explicit_jdate = _parse_date_string(j_match.group("jdate"))
    elif document_category == "final_judgment" and listing_date_iso:
        explicit_jdate = listing_date_iso

    return {
        "court_room": court_room,
        "judge_names": judge_names,
        "listing_date": listing_date_iso,
        "order_date": explicit_odate,
        "judgment_date": explicit_jdate,
    }


def _split_parties_and_counsel(block_lines: List[str]) -> tuple[str, str, str, str]:
    """
    Extract `(petitioner, respondent, advocates, advocate_on_record)` from the lines
    belonging to a single case entry.
    """
    filtered: List[str] = []
    for raw in block_lines:
        ln = re.sub(r"\s+", " ", raw).strip()
        if not ln or NOISE_LINE_REGEX.match(ln):
            continue
        ln = re.sub(r"^\[(?:Criminal|Civil|Original|Appellate)\]\s*", "", ln, flags=re.I).strip()
        # Strip inline Diary No / Filing No / CNR tokens so they don't pollute party names
        ln = DIARY_NUMBER_REGEX.sub("", ln).strip()
        ln = FILING_NUMBER_REGEX.sub("", ln).strip()
        ln = re.sub(r"\bCNR\s*(?:No\.?|Number)?\s*[:\-]?\s*[A-Z]{4}\d{12}\b", "", ln, flags=re.I).strip()
        if not ln:
            continue
        filtered.append(ln)

    combined = re.sub(r"\s+", " ", " ".join(filtered)).strip()

    aor_val = ""
    aor_m = AOR_REGEX.search(combined)
    if aor_m:
        aor_val = aor_m.group("aor").strip(" ,;:-")[:140]

    # Check for explicit labeled Petitioner / Respondent first
    pet_label = re.search(
        r"(?:Petitioner|Appellant|Applicant|Plaintiff|Complainant)s?\s*[:\-]\s*(.+?)(?=(?:Vs\.?|Versus|V/s|Respondent|Defendant|Opposite\s+Party|Accused|$))",
        combined,
        re.I,
    )
    resp_label = re.search(
        r"(?:Respondent|Defendant|Opposite\s+Party|Accused)s?\s*[:\-]\s*(.+?)(?=(?:AOR|Advocate|Counsel|For\s+Petitioner|For\s+Respondent|$))",
        combined,
        re.I,
    )
    if pet_label and resp_label:
        pet = pet_label.group(1).strip(" ,;:-")
        resp = resp_label.group(1).strip(" ,;:-")
        adv_match = re.search(r"(?:AOR|Advocates?|Counsel)\s*[:\-]\s*(.+)$", combined, re.I)
        adv = adv_match.group(1).strip(" ,;:-") if adv_match else aor_val
        return pet[:180], resp[:180], adv[:240], aor_val

    # Standard "PETITIONER VS RESPONDENT" pattern
    vs_match = re.search(r"\b(?:VS\.?|VERSUS|V/S)\b", combined, re.IGNORECASE)
    if not vs_match:
        vs_match = re.search(r"(?<=[A-Z0-9.)])\s*(?:VS\.?)\s*(?=[A-Z])", combined)

    if not vs_match:
        return "", "", aor_val, aor_val

    left_text = combined[: vs_match.start()].strip(" ,;:-")
    right_text = combined[vs_match.end() :].strip(" ,;:-")

    left_text = re.sub(
        r"^(?:FOR\s+(?:ADMISSION|ORDERS|HEARING|FINAL\s+DISPOSAL|PRONOUNCEMENT\s+OF\s+JUDGEMENT)\s*)*",
        "",
        left_text,
        flags=re.I,
    ).strip(" ,;:-")

    advocates = ""
    adv_m = ADVOCATE_MARKER_REGEX.search(right_text)
    if adv_m and adv_m.start() > 3:
        respondent = right_text[: adv_m.start()].strip(" ,;:-")
        advocates = right_text[adv_m.start() :].strip(" ,;:-")
    else:
        rem_m = re.search(
            r"\b(?:COPY\s+NOT\s+SERVED|NOTICE\s+ISSUED|FOR\s+ORDERS|FOR\s+ADMISSION|REMARKS?)\b",
            right_text,
            re.I,
        )
        if rem_m and rem_m.start() > 3:
            respondent = right_text[: rem_m.start()].strip(" ,;:-")
            advocates = right_text[rem_m.start() :].strip(" ,;:-")
        else:
            respondent = right_text

    if not advocates and aor_val:
        advocates = aor_val

    return left_text[:180], respondent[:180], advocates[:240], aor_val


class CaseRecordParser:
    """
    Parses extracted PDF pages into individual structured case records for
    Supreme Court, High Courts, and District Courts.
    """

    def parse_document(
        self,
        extraction: PDFExtractionResult,
        default_listing_date: date,
        fallback_judge: str = "",
        cause_list_type: str = "",
        document_category: str = "daily_cause_list",
        fallback_court_room: str = "",
        fallback_diary_number: str = "",
    ) -> List[ParsedCaseRecord]:
        if not extraction.success or not extraction.full_text.strip():
            return []

        header_meta = _extract_header_metadata(
            extraction.full_text,
            fallback_judge=fallback_judge,
            fallback_date=default_listing_date,
            fallback_court_room=fallback_court_room,
            document_category=document_category,
        )
        listing_date_str = header_meta["listing_date"] or default_listing_date.isoformat()
        doc_order_date = header_meta["order_date"]
        doc_judgment_date = header_meta["judgment_date"]
        doc_judge_names = header_meta["judge_names"]
        doc_court_room = header_meta["court_room"]

        records: List[ParsedCaseRecord] = []
        seen_case_keys: set[tuple[str, str]] = set()
        seq_counter = 0

        pages_to_scan = extraction.pages if extraction.pages else []
        if not pages_to_scan and extraction.full_text:
            from .pdf_extractor import PageTextResult
            pages_to_scan = [
                PageTextResult(
                    page_number=1,
                    text=extraction.full_text,
                    char_count=len(extraction.full_text),
                    used_ocr=extraction.used_ocr,
                )
            ]

        current_page_judge = doc_judge_names
        current_page_room = doc_court_room

        for page in pages_to_scan:
            lines = page.text.splitlines()
            case_anchors: List[tuple[int, re.Match]] = []

            for line_idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                cr_m = COURT_ROOM_REGEX.search(stripped)
                if cr_m and len(stripped) < 85:
                    current_page_room = re.sub(r"\s+", " ", cr_m.group(1)).strip()

                if any(k in stripped.upper() for k in ("HON'BLE", "HONBLE", "JUSTICE")) and not CASE_NUMBER_REGEX.search(stripped):
                    cleaned_j = re.sub(r"^(?:CORAM|BEFORE)\s*[:\-]?\s*", "", stripped, flags=re.I).strip()
                    if 5 < len(cleaned_j) < 120:
                        current_page_judge = cleaned_j

                for match in CASE_NUMBER_REGEX.finditer(stripped):
                    raw_type = match.group("case_type")
                    norm_type = _normalize_case_type(raw_type)
                    if not _is_valid_case_type(norm_type):
                        continue
                    case_anchors.append((line_idx, match))
                    break

            for anchor_idx, (start_line_idx, match) in enumerate(case_anchors):
                end_line_idx = (
                    case_anchors[anchor_idx + 1][0]
                    if anchor_idx + 1 < len(case_anchors)
                    else min(len(lines), start_line_idx + 18)
                )

                raw_type = match.group("case_type")
                case_type = _normalize_case_type(raw_type)
                case_num = re.sub(r"\s+", "", match.group("case_num").strip())
                case_year_str = match.group("case_year").strip()
                case_year = int(case_year_str)
                normalized_case_number = f"{case_type}/{case_num}/{case_year_str}"

                item_no = (match.group("item_no") or "").strip()
                if not item_no and start_line_idx > 0:
                    prev_line = lines[start_line_idx - 1].strip()
                    if re.fullmatch(r"\d{1,4}(?:\.\d+)?[\).]?", prev_line):
                        item_no = prev_line.rstrip(").")

                block_lines = lines[start_line_idx:end_line_idx]
                raw_excerpt = "\n".join(ln.strip() for ln in block_lines if ln.strip())[:600]

                first_line_tail = lines[start_line_idx][match.end() :].strip()
                party_lines = ([first_line_tail] if first_line_tail else []) + block_lines[1:]

                petitioner, respondent, advocates, aor_val = _split_parties_and_counsel(party_lines)

                dedup_key = (normalized_case_number, petitioner[:40].upper())
                if dedup_key in seen_case_keys:
                    continue
                seen_case_keys.add(dedup_key)

                if petitioner and respondent:
                    case_title = f"{petitioner} vs. {respondent}"
                elif petitioner:
                    case_title = petitioner
                else:
                    fallback_snippet = " ".join(
                        ln.strip() for ln in party_lines if ln.strip() and not NOISE_LINE_REGEX.match(ln.strip())
                    )
                    fallback_snippet = re.sub(r"\s+", " ", fallback_snippet).strip(" ,;:-")
                    case_title = fallback_snippet[:140] if fallback_snippet else f"Case {normalized_case_number}"

                cnr_m = CNR_REGEX.search(raw_excerpt)
                cnr_number = cnr_m.group(1) if cnr_m else ""

                diary_m = DIARY_NUMBER_REGEX.search(raw_excerpt)
                diary_number = (
                    re.sub(r"\s+", "", diary_m.group("dnum")).replace("-", "/")
                    if diary_m
                    else fallback_diary_number
                )

                filing_m = FILING_NUMBER_REGEX.search(raw_excerpt)
                filing_number = re.sub(r"\s+", "", filing_m.group("fnum")) if filing_m else ""

                case_odate = doc_order_date
                block_om = EXPLICIT_ORDER_DATE_REGEX.search(raw_excerpt)
                if block_om:
                    parsed_bo = _parse_date_string(block_om.group("odate"))
                    if parsed_bo:
                        case_odate = parsed_bo

                case_jdate = doc_judgment_date
                block_jm = EXPLICIT_JUDGMENT_DATE_REGEX.search(raw_excerpt)
                if block_jm:
                    parsed_bj = _parse_date_string(block_jm.group("jdate"))
                    if parsed_bj:
                        case_jdate = parsed_bj

                # Never fabricate judgment_date from a cause list
                if document_category in ("daily_cause_list", "supplementary_cause_list") and not block_jm and not EXPLICIT_JUDGMENT_DATE_REGEX.search(extraction.full_text):
                    case_jdate = None

                score = extraction.confidence_score * 0.45
                if normalized_case_number and case_type:
                    score += 0.20
                if petitioner and respondent:
                    score += 0.20
                elif petitioner or case_title:
                    score += 0.08
                if current_page_judge:
                    score += 0.08
                if item_no or cnr_number or diary_number or filing_number or advocates:
                    score += 0.07

                confidence = round(min(0.99, max(0.35, score)), 4)
                if confidence >= 0.80:
                    conf_label = "high"
                elif confidence >= 0.60:
                    conf_label = "medium"
                else:
                    conf_label = "low"

                seq_counter += 1
                records.append(
                    ParsedCaseRecord(
                        case_sequence=seq_counter,
                        item_number=item_no,
                        case_number=normalized_case_number,
                        case_type=case_type,
                        case_year=case_year,
                        cnr_number=cnr_number,
                        diary_number=diary_number,
                        filing_number=filing_number,
                        case_title=case_title,
                        petitioner=petitioner,
                        respondent=respondent,
                        advocates=advocates,
                        advocate_on_record=aor_val,
                        listing_date=listing_date_str,
                        order_date=case_odate,
                        judgment_date=case_jdate,
                        judge_names=current_page_judge,
                        court_room=current_page_room,
                        document_category=document_category,
                        page_number=page.page_number,
                        extraction_status="ocr_completed" if page.used_ocr else "completed",
                        confidence=confidence,
                        confidence_label=conf_label,
                        raw_excerpt=raw_excerpt,
                        extracted_details={
                            "item_number": item_no,
                            "cnr_number": cnr_number,
                            "diary_number": diary_number,
                            "filing_number": filing_number,
                            "advocates": advocates,
                            "advocate_on_record": aor_val,
                            "court_room": current_page_room,
                            "cause_list_type": cause_list_type,
                            "document_category": document_category,
                            "order_date": case_odate,
                            "judgment_date": case_jdate,
                            "page_number": page.page_number,
                            "used_ocr": page.used_ocr,
                            "extraction_method": extraction.extraction_method,
                            "raw_excerpt": raw_excerpt,
                        },
                    )
                )

        return records


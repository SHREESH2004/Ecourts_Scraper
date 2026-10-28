#!/usr/bin/env python3
"""Extract case listings from High Court cause-list PDFs."""

from __future__ import annotations

import argparse
import csv
import io
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from pdfminer.pdfdocument import PDFException as PDFDocumentException
from pdfminer.pdfparser import PDFException as PDFParserException
from pdfplumber.utils.exceptions import PdfminerException


FIELDNAMES = [
    "listing_date",
    "court_hall_bench_judge_names",
    "item_number",
    "case_type",
    "case_number",
    "year",
    "cnr_number",
    "petitioner_appellant",
    "respondent_state",
    "advocate_names",
    "source_file",
    "page_number",
    "parse_confidence",
]

CASE_PATTERN = re.compile(
    r"(?P<case_type>[A-Z][A-Z0-9().&-]*(?:\s+[A-Z][A-Z0-9().&-]*){0,2}?)"
    r"\s*/\s*(?P<number>\d+)\s*/\s*(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)
CNR_PATTERN = re.compile(r"\b[A-Z]{4}\d{12}\b", re.IGNORECASE)
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
DATE_PATTERNS = [
    re.compile(
        rf"\b(?:the\s+)?(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:\s+day\s+of)?\s+(?P<month>{MONTHS})[,]?\s+(?P<year>20\d{{2}})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<month>{MONTHS})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?"
        rf"\s+(?P<year>20\d{{2}})\b",
        re.IGNORECASE,
    ),
]
ORDINAL_ITEM = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[\).]?\s*$")
CASE_TYPE_PREFIX = re.compile(r"^[A-Z][A-Z0-9().&-]*(?:\s+[A-Z][A-Z0-9().&-]*){0,2}$", re.I)
ADVOCATE_MARKER = re.compile(
    r"\b(?:GP\s+FOR|G\.?\s*P\.?\s+FOR|SC\s+FOR|S\.?\s*C\.?\s+FOR|"
    r"MR\.?|MRS\.?|MS\.?|ADVOCATE|ADV\.?|COUNSEL\s+FOR)\b",
    re.IGNORECASE,
)
NOISE_PATTERN = re.compile(
    r"^(?:high court\b|court\s*(?:no|number)?\s*[:.\-]?\s*\d+|"
    r"(?:daily|supplementary|additional|cause)\s*list\b|"
    r"(?:sr\.?\s*no\.?|s\.?\s*no\.?|case\s*(?:no|number)|"
    r"parties|petitioner|respondent|advocate|remarks?)\b|"
    r"page\s+\d+\s*(?:/\s*\d+)?|[-\s]*\d+\s*[-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaseStart:
    line_index: int
    match: re.Match[str]
    item_number: str


def parse_date(text: str, source_file: Path) -> str:
    filename_date = re.match(r"^(20\d{2})(\d{2})(\d{2})_", source_file.name)
    if filename_date:
        try:
            return datetime.strptime("".join(filename_date.groups()), "%Y%m%d").date().isoformat()
        except ValueError:
            pass

    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                date = datetime.strptime(
                    f"{match.group('day')} {match.group('month')} {match.group('year')}",
                    "%d %B %Y",
                )
                return date.date().isoformat()
            except ValueError:
                continue
    return ""


def court_metadata(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    court = ""
    hall = ""
    judges: list[str] = []
    for index, line in enumerate(lines):
        if CASE_PATTERN.search(line):
            break
        upper = line.upper()
        if "PUBLISHED UNDER" in upper or "AUTHORITY OF" in upper:
            continue
        if not court and re.search(r"\bHIGH\s*COURT\b", upper):
            court = line
        if not hall and re.search(r"\bCOURT\s*(?:NO|NUMBER)\s*[:.\-]?\s*\d+", line, re.I):
            hall = line
        if re.search(r"\b(?:HON'?BLE|HONOURABLE|JUSTICE)\b", line, re.I):
            if "JUSTICE" in upper or "HON" in upper:
                candidate = line
                if re.search(r"\bBEFORE\s*:?\s*$", line, re.I) and index + 1 < len(lines):
                    candidate = lines[index + 1]
                if candidate not in judges:
                    judges.append(candidate)
    return " | ".join(part for part in [court, hall, "; ".join(judges)] if part)


def _ocr_page(page_number: int, pdf_path: Path) -> str:
    try:
        import pypdfium2
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR is needed for a text-poor page. Install pypdfium2 and pytesseract, "
            "and install the Tesseract OCR application."
        ) from exc

    try:
        document = pypdfium2.PdfDocument(str(pdf_path))
        page = document[page_number]
        bitmap = page.render(scale=2)
        return pytesseract.image_to_string(bitmap.to_pil())
    except (
        OSError,
        pypdfium2.PdfiumError,
        pytesseract.TesseractError,
        pytesseract.TesseractNotFoundError,
    ) as exc:
        raise RuntimeError(
            f"OCR failed on page {page_number + 1}: {exc}. Confirm Tesseract is installed "
            "and available on PATH."
        ) from exc


def extract_pdf_pages(pdf_path: Path) -> list[tuple[str, list[dict[str, Any]]]]:
    pages: list[tuple[str, list[dict[str, Any]]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages):
            text = page.extract_text(layout=False) or ""
            if len(re.sub(r"\s+", "", text)) < 30 and page.images:
                text = _ocr_page(page_number, pdf_path)
                words: list[dict[str, Any]] = []
            else:
                words = page.extract_words(x_tolerance=2, y_tolerance=3)
            pages.append((text, words))
    return pages


def _case_starts(lines: list[str]) -> list[CaseStart]:
    starts: list[CaseStart] = []
    for index, line in enumerate(lines):
        match = CASE_PATTERN.search(line)
        if not match:
            continue
        prefix = line[: match.start()].strip()
        item_number = ""
        if prefix:
            item_match = re.fullmatch(r"[\s]*(\d+(?:\.\d+)*)[\s().]*", prefix)
            if not item_match:
                continue
            item_number = item_match.group(1)
        if not item_number and index:
            previous = ORDINAL_ITEM.fullmatch(lines[index - 1])
            if previous:
                item_number = previous.group(1)

        case_type = match.group("case_type").strip()
        if not CASE_TYPE_PREFIX.fullmatch(case_type):
            continue
        starts.append(CaseStart(index, match, item_number))
    return starts


def _clean_entry_lines(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or NOISE_PATTERN.match(line):
            continue
        if re.match(r"^(?:IA|I\.A\.|M\.?P\.?)\s*\d+\s*/\s*\d{4}\b", line, re.I):
            line = re.sub(
                r"^(?:IA|I\.A\.|M\.?P\.?)\s*\d+\s*/\s*\d{4}\s*",
                "",
                line,
                flags=re.I,
            ).strip()
            if not line:
                continue
        if re.fullmatch(
            r"(?:direction|stay|suspension|condone delay|vacate stay|"
            r"implead|dispense with|leave|amendment|modification)\s+petition",
            line,
            re.I,
        ):
            continue
        line = re.sub(
            r"^(?:direction|stay|suspension|condone delay|vacate stay|"
            r"implead|dispense with|leave|amendment|modification)\s+petition\s*",
            "",
            line,
            flags=re.I,
        ).strip()
        if not line:
            continue
        if re.match(r"^(?:FOR\s+(?:ORDERS|ADMISSION|HEARING|COMPLIANCE)|"
                    r"ADMISSION\s*\(|PART[- ]HEARD|CONNECTED CASES)", line, re.I):
            continue
        if re.match(r"^(?:remark|note|r\d+\s+notice)\b", line, re.I):
            continue
        cleaned.append(line)
    return cleaned


def _split_parties_and_advocates(lines: list[str]) -> tuple[str, str, str]:
    text = " ".join(lines)
    vs_match = re.search(r"\b(?:vs\.?|versus)\b", text, re.I)
    if not vs_match:
        return "", "", ""

    petitioner = text[: vs_match.start()].strip(" ,;:-")
    respondent_and_counsel = text[vs_match.end() :].strip(" ,;:-")
    marker = ADVOCATE_MARKER.search(respondent_and_counsel)
    if marker and marker.start() == 0 and re.match(r"MR\.?|MRS\.?|MS\.?", marker.group(0), re.I):
        marker = ADVOCATE_MARKER.search(respondent_and_counsel, marker.end())
    respondent = respondent_and_counsel
    advocates = ""
    if marker:
        respondent = respondent_and_counsel[: marker.start()].strip(" ,;:-")
        advocates = respondent_and_counsel[marker.start() :].strip(" ,;:-")

    petitioner = re.sub(r"\s+", " ", petitioner).strip()
    respondent = re.sub(r"\s+", " ", respondent).strip()
    advocates = re.sub(r"\s+", " ", advocates).strip()
    return petitioner, respondent, advocates


def _column_parties(
    words: list[dict[str, Any]], start: CaseStart, end_y: float
) -> tuple[str, str, str] | None:
    case_word = next(
        (
            word
            for word in words
            if word["top"] < end_y
            and CASE_PATTERN.search(word["text"])
            and CASE_PATTERN.search(word["text"]).group("number") == start.match.group("number")
            and CASE_PATTERN.search(word["text"]).group("year") == start.match.group("year")
        ),
        None,
    )
    if case_word is None:
        return None

    start_y = float(case_word["top"])
    vs_word = next(
        (
            word
            for word in words
            if start_y <= word["top"] < end_y
            and re.fullmatch(r"vs\.?|versus", word["text"].strip(".,:;"), re.I)
        ),
        None,
    )
    if vs_word is None:
        return None

    headers = [
        word
        for word in words
        if word["top"] < start_y
        and word["text"].strip(".,:;").casefold() in {"party", "parties"}
    ]
    party_header = max(headers, key=lambda word: word["top"]) if headers else None
    header_words: list[dict[str, Any]] = []
    if party_header:
        header_words = [
            word
            for word in words
            if abs(word["top"] - party_header["top"]) < 2.5
            and word["x0"] >= party_header["x0"]
        ]
    header_text = " ".join(word["text"].lower() for word in header_words)
    next_header = next(
        (
            word
            for word in sorted(header_words, key=lambda item: item["x0"])
            if word["x0"] > party_header["x0"]
            and word["text"].strip(".,:;").casefold()
            in {"petitioner", "advocate", "advocates"}
        ),
        None,
    ) if party_header else None

    if not party_header:
        party_limit = float(vs_word["x0"]) + 160
    elif "petnr" in header_text:
        party_limit = float(next_header["x0"]) + 80 if next_header else float(vs_word["x0"]) + 200
    elif "advocates" in header_text and next_header:
        party_limit = float(next_header["x0"]) - 50
    elif next_header:
        party_limit = float(next_header["x0"])
    else:
        party_limit = float(vs_word["x0"]) + 120

    if party_header and abs(float(party_header["x0"]) - float(vs_word["x0"])) < 50:
        party_min = max(0.0, float(party_header["x0"]) - 35)
    else:
        party_min = max(0.0, float(vs_word["x0"]) - 60)
    if party_limit <= party_min:
        return None

    advocate_limit = float("inf")
    if header_words:
        later_columns = [
            word["x0"]
            for word in header_words
            if word["x0"] > party_limit
            and word["text"].strip(".,:;").casefold() in {"district/case", "remarks"}
        ]
        if later_columns:
            advocate_limit = min(later_columns) - 20

    def collect(left: float, right: float, top: float, bottom: float) -> str:
        selected = [
            word
            for word in words
            if top <= word["top"] < bottom and left <= word["x0"] < right
        ]
        selected.sort(key=lambda word: (word["top"], word["x0"]))
        text = " ".join(word["text"] for word in selected)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^(?:Vs\.?|Versus)\s+", "", text, flags=re.I)
        return text.strip(" ,;:-")

    content_end_y = end_y
    stop_words = {
        "notice",
        "remark",
        "remarks",
        "note",
        "coram",
        "motion",
        "received",
    }
    stop_positions = [
        float(word["top"])
        for word in words
        if float(vs_word["top"]) <= float(word["top"]) < end_y
        and word["text"].strip(".,:;").casefold() in stop_words
    ]
    if stop_positions:
        content_end_y = min(end_y, min(stop_positions) + 0.5)

    petitioner = collect(party_min, party_limit, start_y, float(vs_word["top"]))
    respondent = collect(
        party_min,
        party_limit,
        float(vs_word["top"]) + 0.5,
        content_end_y,
    )
    advocates = collect(party_limit, advocate_limit, start_y, content_end_y)
    advocates = re.sub(
        r"\b(?:APPELLANT|RESPONDENT|PETITIONER|NOTICE|REMARKS?|MOTION)\b.*$",
        "",
        advocates,
        flags=re.I,
    ).strip(" ,;:-")
    respondent = re.sub(
        r"\b(?:NOTICE|REMARKS?|NOTE|R\.?\s*NO\.?S?|COURT'?S\s+ORDER|"
        r"ORDER\s+DATED|CORAM|CIRCULATION|FOR\s+REG|PRE-ADMISSION|WITH)\b.*$",
        "",
        respondent,
        flags=re.I,
    ).strip(" ,;:-")
    respondent = re.sub(
        r"^(?:direction|stay|suspension|condone delay|vacate stay|"
        r"implead|dispense with|leave|amendment|modification)?\s*petition\s+",
        "",
        respondent,
        flags=re.I,
    ).strip()
    respondent = re.sub(r"(?:\s+petition)+$", "", respondent, flags=re.I).strip()

    for field_name in ("petitioner", "respondent"):
        party_text = petitioner if field_name == "petitioner" else respondent
        counsel_marker = re.search(
            r"\b(?:GP\s+FOR|G\.?\s*P\.?\s+FOR|SC\s+FOR|S\.?\s*C\.?\s+FOR|"
            r"MR\.?|MRS\.?|MS\.?|ADVOCATE|ADV\.?|COUNSEL\s+FOR)\b",
            party_text,
            re.I,
        )
        if counsel_marker and counsel_marker.start() > 0:
            advocates = " ".join(
                part for part in (advocates, party_text[counsel_marker.start() :]) if part
            )
            if field_name == "petitioner":
                petitioner = party_text[: counsel_marker.start()].strip(" ,;:-")
            else:
                respondent = party_text[: counsel_marker.start()].strip(" ,;:-")
    advocates = re.sub(r"\s+", " ", advocates).strip()
    advocates = re.sub(r"\bMOTION\b.*$", "", advocates, flags=re.I).strip(" ,;:-")
    advocates = re.sub(r"\s+(?:MR\.?|MRS\.?|MS\.?)$", "", advocates, flags=re.I).strip()
    advocates = re.sub(r"\s+(?:[a-z]\s+){1,}[a-z]?$", "", advocates).strip()
    return petitioner, respondent, advocates


def parse_page(
    text: str,
    page_number: int,
    listing_date: str,
    metadata: str,
    source_file: str,
    words: list[dict[str, Any]] | None = None,
) -> list[dict[str, str | int]]:
    lines = text.splitlines()
    starts = _case_starts(lines)
    rows: list[dict[str, str | int]] = []

    for start_index, start in enumerate(starts):
        end = starts[start_index + 1].line_index if start_index + 1 < len(starts) else len(lines)
        entry_lines = lines[start.line_index:end]
        case_line = entry_lines[0]
        case_line_prefix_end = start.match.end()
        if case_line_prefix_end < len(case_line):
            entry_lines = [case_line[case_line_prefix_end:]] + entry_lines[1:]
        content = _clean_entry_lines(entry_lines)
        petitioner, respondent, advocates = _split_parties_and_advocates(content)
        segment_text = "\n".join(lines[start.line_index:end])
        case_word = None
        if words:
            case_word = next(
                (
                    word
                    for word in words
                    if CASE_PATTERN.search(word["text"])
                    and CASE_PATTERN.search(word["text"]).group("number")
                    == start.match.group("number")
                    and CASE_PATTERN.search(word["text"]).group("year")
                    == start.match.group("year")
                ),
                None,
            )
        if case_word is not None:
            next_case_word = None
            if start_index + 1 < len(starts):
                next_start = starts[start_index + 1]
                next_case_word = next(
                    (
                        word
                        for word in words
                        if CASE_PATTERN.search(word["text"])
                        and CASE_PATTERN.search(word["text"]).group("number")
                        == next_start.match.group("number")
                        and CASE_PATTERN.search(word["text"]).group("year")
                        == next_start.match.group("year")
                        and word["top"] > case_word["top"]
                    ),
                    None,
                )
            end_y = float(next_case_word["top"]) if next_case_word else float("inf")
            column_parties = _column_parties(words, start, end_y)
            if column_parties:
                petitioner, respondent, advocates = column_parties
        cnr_match = CNR_PATTERN.search(segment_text)
        case_type = re.sub(r"\s+", "", start.match.group("case_type")).upper()
        confidence = "medium"
        extracted_fields = " ".join((petitioner, respondent, advocates))
        uncertain_markers = re.search(
            r"\b(?:petition|notice|remarks?|court'?s?\s+order|received|served|"
            r"appeal\s+is\s+at|pre-admission|versus|vs\.?)\b",
            extracted_fields,
            re.I,
        )
        if (
            not listing_date
            or not metadata
            or not start.item_number
            or not petitioner
            or not respondent
            or uncertain_markers
            or len(petitioner) > 120
            or len(respondent) > 120
            or len(advocates) > 250
            or CASE_PATTERN.search(petitioner)
            or CASE_PATTERN.search(respondent)
        ):
            confidence = "low"

        rows.append(
            {
                "listing_date": listing_date,
                "court_hall_bench_judge_names": metadata,
                "item_number": start.item_number,
                "case_type": case_type,
                "case_number": start.match.group("number"),
                "year": start.match.group("year"),
                "cnr_number": cnr_match.group(0).upper() if cnr_match else "",
                "petitioner_appellant": petitioner,
                "respondent_state": respondent,
                "advocate_names": advocates,
                "source_file": source_file,
                "page_number": page_number,
                "parse_confidence": confidence,
            }
        )
    return rows


def _case_key(row: dict[str, str | int]) -> tuple[str, str, str]:
    normalized_type = re.sub(r"[^A-Z0-9]", "", str(row["case_type"]).upper())
    return normalized_type, str(row["case_number"]), str(row["year"])


def _completeness(row: dict[str, str | int]) -> tuple[int, int]:
    confidence_score = {"low": 0, "medium": 1, "high": 2}.get(
        str(row["parse_confidence"]), 0
    )
    fields = (
        "listing_date",
        "court_hall_bench_judge_names",
        "item_number",
        "cnr_number",
        "petitioner_appellant",
        "respondent_state",
        "advocate_names",
    )
    return confidence_score, sum(bool(row[field]) for field in fields)


def write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_random_rows(rows: list[dict[str, str | int]], sample_size: int) -> None:
    sample = random.SystemRandom().sample(rows, min(sample_size, len(rows)))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sample)
    print(f"\nRandom verification sample ({len(sample)} rows):")
    print(output.getvalue(), end="")


def extract_cause_lists(input_dir: Path, output_dir: Path, sample_size: int) -> int:
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    pdf_paths = sorted(path for path in input_dir.rglob("*.pdf") if path.is_file())
    if not pdf_paths:
        raise ValueError(f"No PDF files found under: {input_dir}")

    listings: list[dict[str, str | int]] = []
    failures: list[tuple[Path, str]] = []
    empty_files: list[Path] = []
    confidence_counts: Counter[str] = Counter()

    for file_index, pdf_path in enumerate(pdf_paths, start=1):
        try:
            page_contents = extract_pdf_pages(pdf_path)
            page_texts = [text for text, _ in page_contents]
            document_text = "\n".join(page_texts)
            listing_date = parse_date(document_text, pdf_path)
            metadata = court_metadata(page_texts[0] if page_texts else "")
            relative_path = str(pdf_path.relative_to(input_dir))
            file_rows = [
                row
                for page_number, (page_text, page_words) in enumerate(page_contents, start=1)
                for row in parse_page(
                    page_text,
                    page_number,
                    listing_date,
                    metadata,
                    relative_path,
                    page_words,
                )
            ]
            if not file_rows:
                empty_files.append(pdf_path)
            else:
                listings.extend(file_rows)
                confidence_counts.update(str(row["parse_confidence"]) for row in file_rows)
        except (
            OSError,
            ValueError,
            RuntimeError,
            PDFDocumentException,
            PDFParserException,
            PdfminerException,
        ) as exc:
            failures.append((pdf_path, str(exc)))
            print(f"ERROR: {pdf_path}: {exc}", file=sys.stderr)

        if file_index % 100 == 0 or file_index == len(pdf_paths):
            print(f"Processed {file_index}/{len(pdf_paths)} PDFs; extracted {len(listings)} listings.")

    if not listings:
        raise RuntimeError(
            f"No case listings were extracted from {len(pdf_paths)} PDFs. "
            "Check the PDF text/OCR setup and cause-list layout."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    listings_path = output_dir / "all_listings.csv"
    unique_path = output_dir / "unique_cases.csv"
    write_csv(listings_path, listings)

    unique_by_key: dict[tuple[str, str, str], dict[str, str | int]] = {}
    for row in listings:
        key = _case_key(row)
        current = unique_by_key.get(key)
        if current is None or _completeness(row) > _completeness(current):
            unique_by_key[key] = row
    unique_rows = list(unique_by_key.values())
    write_csv(unique_path, unique_rows)

    print(f"\nPDF files: {len(pdf_paths)}")
    print(f"Listings: {len(listings)}")
    print(f"Unique case numbers: {len(unique_rows)}")
    print(f"Parse confidence: {dict(confidence_counts)}")
    print(f"PDFs with no detected listings: {len(empty_files)}")
    if empty_files:
        for path in empty_files[:20]:
            print(f"WARNING: no case entries detected: {path}", file=sys.stderr)
        if len(empty_files) > 20:
            print(f"WARNING: and {len(empty_files) - 20} more PDFs without detected entries.", file=sys.stderr)
    print(f"All listings CSV: {listings_path.resolve()}")
    print(f"Unique cases CSV: {unique_path.resolve()}")
    print_random_rows(listings, sample_size)
    if failures:
        print(f"\nCompleted with {len(failures)} PDF error(s); see ERROR lines above.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "downloaded_pdfs",
        help="Folder containing PDFs (searched recursively; default: ./downloaded_pdfs).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Folder for all_listings.csv and unique_cases.csv (default: current directory).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of random listing rows printed for verification (default: 10).",
    )
    args = parser.parse_args()
    if args.sample_size < 0:
        parser.error("--sample-size must be zero or greater")
    try:
        return extract_cause_lists(args.input_dir, args.output_dir, args.sample_size)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
PDF Text & OCR Fallback Extraction Pipeline for PDF Intelligence.

Extracts text page-by-page from PDF payloads using digital text extraction first
(pdfplumber / PyPDF2) and automatically falls back to OCR when a scanned PDF or
page has insufficient usable text.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

MIN_USABLE_CHARS_PER_PAGE = 25


@dataclass
class PageTextResult:
    page_number: int  # 1-based
    text: str
    char_count: int
    used_ocr: bool = False
    ocr_error: Optional[str] = None


@dataclass
class PDFExtractionResult:
    success: bool
    status: str  # 'completed', 'ocr_completed', 'empty', 'failed'
    extraction_method: str  # 'digital_text', 'ocr_fallback', 'hybrid', 'failed'
    used_ocr: bool
    page_count: int
    total_chars: int
    confidence_score: float
    pages: List[PageTextResult] = field(default_factory=list)
    full_text: str = ""
    error_message: Optional[str] = None


OCRProviderCallable = Callable[[bytes, int], str]


class PDFTextExtractor:
    """
    Multi-stage PDF text extractor with automatic OCR fallback for scanned PDFs.
    """

    def __init__(
        self,
        min_chars_per_page: int = MIN_USABLE_CHARS_PER_PAGE,
        ocr_provider: Optional[OCRProviderCallable] = None,
    ):
        self.min_chars_per_page = max(5, int(min_chars_per_page))
        self.ocr_provider = ocr_provider

    def extract_from_bytes(self, pdf_bytes: bytes) -> PDFExtractionResult:
        """
        Extract text from PDF bytes, invoking OCR fallback on pages that contain
        no usable digital text.
        """
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            return PDFExtractionResult(
                success=False,
                status="failed",
                extraction_method="failed",
                used_ocr=False,
                page_count=0,
                total_chars=0,
                confidence_score=0.0,
                error_message="Invalid or empty PDF byte stream.",
            )

        try:
            raw_pages, has_images_per_page = self._extract_digital_pages(pdf_bytes)
        except Exception as exc:
            return PDFExtractionResult(
                success=False,
                status="failed",
                extraction_method="failed",
                used_ocr=False,
                page_count=0,
                total_chars=0,
                confidence_score=0.0,
                error_message=f"PDF parsing failed: {exc}",
            )

        if not raw_pages:
            return PDFExtractionResult(
                success=False,
                status="failed",
                extraction_method="failed",
                used_ocr=False,
                page_count=0,
                total_chars=0,
                confidence_score=0.0,
                error_message="PDF contains zero pages.",
            )

        page_results: List[PageTextResult] = []
        ocr_pages_count = 0
        digital_pages_count = 0
        ocr_errors: List[str] = []

        for idx, digital_text in enumerate(raw_pages):
            page_num = idx + 1
            non_ws_chars = len(re.sub(r"\s+", "", digital_text or ""))

            if non_ws_chars >= self.min_chars_per_page:
                digital_pages_count += 1
                page_results.append(
                    PageTextResult(
                        page_number=page_num,
                        text=digital_text.strip(),
                        char_count=non_ws_chars,
                        used_ocr=False,
                    )
                )
                continue

            # Page has insufficient digital text -> attempt OCR fallback
            ocr_text, ocr_err = self._run_ocr_for_page(pdf_bytes, idx, has_images_per_page[idx])
            ocr_non_ws = len(re.sub(r"\s+", "", ocr_text or ""))

            if ocr_non_ws > non_ws_chars and ocr_non_ws > 0:
                ocr_pages_count += 1
                page_results.append(
                    PageTextResult(
                        page_number=page_num,
                        text=ocr_text.strip(),
                        char_count=ocr_non_ws,
                        used_ocr=True,
                    )
                )
            else:
                if ocr_err:
                    ocr_errors.append(f"Page {page_num}: {ocr_err}")
                if non_ws_chars > 0:
                    digital_pages_count += 1
                page_results.append(
                    PageTextResult(
                        page_number=page_num,
                        text=(digital_text or "").strip(),
                        char_count=non_ws_chars,
                        used_ocr=False,
                        ocr_error=ocr_err,
                    )
                )

        total_chars = sum(p.char_count for p in page_results)
        full_text = "\n\n".join(p.text for p in page_results if p.text)
        used_ocr = ocr_pages_count > 0

        if total_chars == 0:
            err_detail = (
                "; ".join(ocr_errors)
                if ocr_errors
                else "Scanned or blank PDF with no extractable text and no OCR output."
            )
            return PDFExtractionResult(
                success=False,
                status="failed",
                extraction_method="failed",
                used_ocr=used_ocr,
                page_count=len(page_results),
                total_chars=0,
                confidence_score=0.0,
                pages=page_results,
                full_text="",
                error_message=err_detail,
            )

        if used_ocr and digital_pages_count > 0:
            method = "hybrid"
            status = "ocr_completed"
            base_conf = 0.78
        elif used_ocr:
            method = "ocr_fallback"
            status = "ocr_completed"
            base_conf = 0.72
        else:
            method = "digital_text"
            status = "completed"
            base_conf = 0.92

        avg_chars_per_page = total_chars / max(1, len(page_results))
        if avg_chars_per_page < 50:
            base_conf = max(0.45, base_conf - 0.20)

        return PDFExtractionResult(
            success=True,
            status=status,
            extraction_method=method,
            used_ocr=used_ocr,
            page_count=len(page_results),
            total_chars=total_chars,
            confidence_score=round(base_conf, 4),
            pages=page_results,
            full_text=full_text,
            error_message="; ".join(ocr_errors) if ocr_errors else None,
        )

    @staticmethod
    def _extract_digital_pages(pdf_bytes: bytes) -> tuple[List[str], List[bool]]:
        """
        Extract digital text per page using pdfplumber if installed, else PyPDF2.
        Also detects whether each page contains embedded images.
        """
        # Try pdfplumber first if available
        try:
            import pdfplumber
            texts: List[str] = []
            has_images: List[bool] = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text(layout=False) or ""
                    texts.append(txt)
                    has_images.append(bool(getattr(page, "images", None)))
            return texts, has_images
        except ImportError:
            pass

        # Standard PyPDF2 extraction
        import PyPDF2

        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        texts = []
        has_images = []
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            texts.append(txt)
            page_has_img = False
            try:
                resources = page.get("/Resources") or {}
                if hasattr(resources, "get_object"):
                    resources = resources.get_object()
                xobj = resources.get("/XObject") if isinstance(resources, dict) else None
                if xobj is not None:
                    page_has_img = True
            except Exception:
                pass
            has_images.append(page_has_img)
        return texts, has_images

    def _run_ocr_for_page(
        self,
        pdf_bytes: bytes,
        page_index: int,
        page_has_images: bool,
    ) -> tuple[str, Optional[str]]:
        """
        Run OCR on a single 0-indexed page when digital text extraction yields
        insufficient characters.
        """
        # 1. Custom/injected OCR provider (used in tests or custom OCR hooks)
        if self.ocr_provider is not None:
            try:
                text = self.ocr_provider(pdf_bytes, page_index)
                return text or "", None
            except Exception as exc:
                return "", f"OCR provider error: {exc}"

        # 2. Try pypdfium2 + pytesseract if installed
        try:
            import pypdfium2
            import pytesseract

            doc = pypdfium2.PdfDocument(pdf_bytes)
            page = doc[page_index]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            ocr_text = pytesseract.image_to_string(pil_image)
            return (ocr_text or "").strip(), None
        except ImportError:
            pass
        except Exception as exc:
            return "", f"pypdfium2/pytesseract OCR failed: {exc}"

        # 3. Try extracting embedded images from the PDF page via PyPDF2 + PIL + tesseract CLI / pytesseract
        try:
            import PyPDF2
            from PIL import Image

            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            page = reader.pages[page_index]
            images = getattr(page, "images", []) or []
            if images:
                extracted_chunks: List[str] = []
                for img_file in images:
                    pil_img = Image.open(io.BytesIO(img_file.data))
                    chunk_text = self._ocr_pil_image(pil_img)
                    if chunk_text:
                        extracted_chunks.append(chunk_text)
                if extracted_chunks:
                    return "\n".join(extracted_chunks), None
        except Exception as exc:
            logger.debug("Embedded image OCR attempt failed: %s", exc)

        if page_has_images:
            return "", (
                "Scanned PDF page detected, but OCR runtime (tesseract / pypdfium2) "
                "is not installed on PATH."
            )
        return "", "Page contains no extractable text or embedded images."

    @staticmethod
    def _ocr_pil_image(pil_image) -> str:
        """Run OCR on a PIL Image via pytesseract or the tesseract CLI binary."""
        try:
            import pytesseract
            return (pytesseract.image_to_string(pil_image) or "").strip()
        except ImportError:
            pass

        tesseract_bin = shutil.which("tesseract")
        if not tesseract_bin:
            raise RuntimeError("Tesseract OCR binary not found on system PATH")

        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "page.png"
            pil_image.save(img_path, format="PNG")
            proc = subprocess.run(
                [tesseract_bin, str(img_path), "stdout", "--oem", "1", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode == 0:
                return (proc.stdout or "").strip()
            raise RuntimeError(proc.stderr.strip() or f"tesseract exited with {proc.returncode}")

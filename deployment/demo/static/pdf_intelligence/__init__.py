"""
PDF Intelligence Package (`deployment/pdf_intelligence/`).

Provides an independent PDF discovery, download, SHA-256 deduplication,
text/OCR extraction, multi-case record parsing, durable job processing,
India map court navigation, and daily analytics engine.
"""

from __future__ import annotations

from typing import Optional
from flask import Flask

from .routes import create_pdf_intelligence_blueprint
from .worker import PDFIntelligenceWorker


def register_pdf_intelligence(app: Flask, worker: Optional[PDFIntelligenceWorker] = None) -> None:
    """
    Register the isolated `/api/pdf-intelligence/` API routes and `/pdf-analysis.html`
    page routes onto the Flask application without altering any existing routes.
    """
    bp = create_pdf_intelligence_blueprint(worker=worker)
    app.register_blueprint(bp)


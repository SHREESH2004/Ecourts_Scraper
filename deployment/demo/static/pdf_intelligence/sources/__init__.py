"""
Independent Court Source Adapters Package (`deployment/pdf_intelligence/sources/`).

Provides three separate source adapters:
- `SupremeCourtSourceAdapter` (`https://www.sci.gov.in/`)
- `HighCourtSourceAdapter` (`https://hcservices.ecourts.gov.in/`)
- `DistrictCourtSourceAdapter` (`https://services.ecourts.gov.in/`)
"""

from __future__ import annotations

from typing import Dict, Optional

from .base import (
    COURT_CATEGORIES,
    DOCUMENT_CATEGORIES,
    STORAGE_NAMESPACES,
    BaseCourtSourceAdapter,
    CourtLocationSpec,
    DiscoveredDocument,
    PortalAccessLimitation,
    SourceDiscoveryRequest,
    SourceDiscoveryResult,
    build_safe_pdf_filename,
    compute_document_identity,
    detect_captcha_or_access_gate,
    generate_inclusive_date_range,
)
from .district_court import DISTRICT_COURT_LOCATIONS, DistrictCourtSourceAdapter
from .high_court import HIGH_COURT_LOCATIONS, HighCourtSourceAdapter
from .supreme_court import SUPREME_COURT_LOCATIONS, SupremeCourtSourceAdapter


def get_source_adapter(court_type: str, **kwargs) -> BaseCourtSourceAdapter:
    ct = (court_type or "high_court").strip().lower()
    if ct == "supreme_court":
        return SupremeCourtSourceAdapter(**kwargs)
    if ct == "high_court":
        return HighCourtSourceAdapter(**kwargs)
    if ct == "district_court":
        return DistrictCourtSourceAdapter(**kwargs)
    raise ValueError(f"Unsupported court_type {court_type!r}. Expected one of {list(COURT_CATEGORIES)}")


__all__ = [
    "COURT_CATEGORIES",
    "DOCUMENT_CATEGORIES",
    "STORAGE_NAMESPACES",
    "BaseCourtSourceAdapter",
    "CourtLocationSpec",
    "DiscoveredDocument",
    "PortalAccessLimitation",
    "SourceDiscoveryRequest",
    "SourceDiscoveryResult",
    "SupremeCourtSourceAdapter",
    "HighCourtSourceAdapter",
    "DistrictCourtSourceAdapter",
    "SUPREME_COURT_LOCATIONS",
    "HIGH_COURT_LOCATIONS",
    "DISTRICT_COURT_LOCATIONS",
    "get_source_adapter",
    "build_safe_pdf_filename",
    "compute_document_identity",
    "detect_captcha_or_access_gate",
    "generate_inclusive_date_range",
]


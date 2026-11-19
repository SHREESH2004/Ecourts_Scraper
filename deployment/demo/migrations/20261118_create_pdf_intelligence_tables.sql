-- =============================================================================
-- Migration: 20261118_create_pdf_intelligence_tables.sql
-- Purpose: Separate database schema for the independent PDF Intelligence Engine
--          supporting All-India Court Coverage:
--          1. Supreme Court of India (national level: nullable state/district)
--          2. High Courts and Benches (State -> High Court -> Bench)
--          3. District & Subordinate Courts (State -> District -> Court Complex -> Establishment)
-- Note: Does NOT alter or touch existing ecourts_pdfs, scraper_runs, states,
--       high_courts, supreme_court_cases, or supreme_court_judges tables.
-- =============================================================================

BEGIN;

-- 1. Unified Geographic & Court Hierarchy Table
CREATE TABLE IF NOT EXISTS public.pi_court_locations (
    id SERIAL PRIMARY KEY,
    location_key TEXT NOT NULL UNIQUE,
    court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
    state_code TEXT,
    state_iso_code TEXT,
    state_name TEXT,
    is_union_territory BOOLEAN NOT NULL DEFAULT FALSE,
    district_code TEXT,
    district_name TEXT,
    complex_code TEXT,
    complex_name TEXT,
    establishment_code TEXT,
    establishment_name TEXT,
    court_code TEXT NOT NULL,
    court_name TEXT NOT NULL,
    bench_code TEXT NOT NULL,
    bench_name TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_supported BOOLEAN NOT NULL DEFAULT TRUE,
    requires_manual_verification BOOLEAN NOT NULL DEFAULT FALSE,
    supported_doc_categories JSONB NOT NULL DEFAULT '["daily_cause_list", "supplementary_cause_list"]'::jsonb,
    source_limitation TEXT,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pi_court_locations_tier ON public.pi_court_locations (court_type, state_code);
CREATE INDEX IF NOT EXISTS idx_pi_court_locations_district ON public.pi_court_locations (state_code, district_code);
CREATE INDEX IF NOT EXISTS idx_pi_court_locations_complex ON public.pi_court_locations (state_code, district_code, complex_code);
CREATE INDEX IF NOT EXISTS idx_pi_court_locations_iso ON public.pi_court_locations (state_iso_code);

-- 2. Durable Scrape Jobs Table
CREATE TABLE IF NOT EXISTS public.pi_scrape_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_uid TEXT NOT NULL UNIQUE,
    scope_key TEXT NOT NULL,
    court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
    state_code TEXT,
    state_name TEXT,
    district_code TEXT,
    district_name TEXT,
    complex_code TEXT,
    complex_name TEXT,
    establishment_code TEXT,
    establishment_name TEXT,
    court_code TEXT,
    court_name TEXT,
    bench_code TEXT,
    bench_name TEXT,
    document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    preset_label TEXT NOT NULL DEFAULT 'custom',
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')),
    discovered_count INTEGER NOT NULL DEFAULT 0,
    downloaded_count INTEGER NOT NULL DEFAULT 0,
    skipped_duplicate_count INTEGER NOT NULL DEFAULT 0,
    extracted_doc_count INTEGER NOT NULL DEFAULT 0,
    case_records_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    progress_pct INTEGER NOT NULL DEFAULT 0,
    current_step TEXT,
    log_entries JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_summary TEXT,
    limitation_notice TEXT,
    requires_manual_verification BOOLEAN NOT NULL DEFAULT FALSE,
    worker_id TEXT,
    recovered_from_restart BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_pi_scrape_jobs_status ON public.pi_scrape_jobs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pi_scrape_jobs_scope ON public.pi_scrape_jobs (scope_key, status);

-- 3. Discovered & Downloaded PDF Documents Table
CREATE TABLE IF NOT EXISTS public.pi_documents (
    id BIGSERIAL PRIMARY KEY,
    document_identity TEXT NOT NULL UNIQUE,
    scrape_job_id BIGINT REFERENCES public.pi_scrape_jobs(id) ON DELETE SET NULL,
    location_id INTEGER REFERENCES public.pi_court_locations(id) ON DELETE RESTRICT,
    court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
    state_code TEXT,
    state_name TEXT,
    district_code TEXT,
    district_name TEXT,
    complex_code TEXT,
    complex_name TEXT,
    establishment_code TEXT,
    establishment_name TEXT,
    court_code TEXT NOT NULL,
    court_name TEXT NOT NULL,
    bench_code TEXT NOT NULL,
    bench_name TEXT NOT NULL,
    document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
    listing_date DATE NOT NULL,
    order_date DATE,
    judgment_date DATE,
    cause_list_type TEXT,
    coram_judge_raw TEXT,
    court_number TEXT,
    diary_number TEXT,
    source_portal TEXT,
    source_reference TEXT NOT NULL,
    source_url TEXT NOT NULL,
    pdf_filename TEXT NOT NULL,
    storage_namespace TEXT NOT NULL DEFAULT 'pdf-intelligence/high-court',
    storage_object_key TEXT,
    local_fallback_path TEXT,
    content_sha256 TEXT,
    file_size_bytes INTEGER,
    page_count INTEGER,
    download_status TEXT NOT NULL DEFAULT 'pending',
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extraction_method TEXT,
    extraction_confidence NUMERIC(5, 4),
    case_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    downloaded_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pi_documents_tier_date ON public.pi_documents (court_type, state_code, district_code, bench_code, listing_date DESC);
CREATE INDEX IF NOT EXISTS idx_pi_documents_sha256 ON public.pi_documents (content_sha256);
CREATE INDEX IF NOT EXISTS idx_pi_documents_extraction_status ON public.pi_documents (extraction_status);
CREATE INDEX IF NOT EXISTS idx_pi_documents_listing_date ON public.pi_documents (listing_date DESC);

-- 4. PDF Text & OCR Extraction Jobs Audit Table
CREATE TABLE IF NOT EXISTS public.pi_extraction_jobs (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES public.pi_documents(id) ON DELETE CASCADE,
    scrape_job_id BIGINT REFERENCES public.pi_scrape_jobs(id) ON DELETE SET NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    extraction_method TEXT,
    used_ocr BOOLEAN NOT NULL DEFAULT FALSE,
    pages_processed INTEGER NOT NULL DEFAULT 0,
    extracted_chars INTEGER NOT NULL DEFAULT 0,
    cases_extracted INTEGER NOT NULL DEFAULT 0,
    confidence_score NUMERIC(5, 4),
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pi_extraction_jobs_doc ON public.pi_extraction_jobs (document_id, attempt_number DESC);

-- 5. Individual Extracted Case Records Table (1 PDF -> Many Cases)
CREATE TABLE IF NOT EXISTS public.pi_case_records (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES public.pi_documents(id) ON DELETE CASCADE,
    location_id INTEGER REFERENCES public.pi_court_locations(id) ON DELETE SET NULL,
    case_sequence INTEGER NOT NULL,
    document_category TEXT NOT NULL DEFAULT 'daily_cause_list',
    item_number TEXT,
    case_number TEXT NOT NULL,
    case_type TEXT NOT NULL,
    case_year INTEGER,
    cnr_number TEXT,
    diary_number TEXT,
    filing_number TEXT,
    case_title TEXT NOT NULL,
    petitioner TEXT,
    respondent TEXT,
    advocates TEXT,
    advocate_on_record TEXT,
    listing_date DATE NOT NULL,
    order_date DATE,
    judgment_date DATE,
    judge_names TEXT,
    court_room TEXT,
    court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
    state_code TEXT,
    state_name TEXT,
    district_code TEXT,
    district_name TEXT,
    complex_code TEXT,
    complex_name TEXT,
    establishment_code TEXT,
    establishment_name TEXT,
    court_code TEXT NOT NULL,
    court_name TEXT NOT NULL,
    bench_code TEXT NOT NULL,
    bench_name TEXT NOT NULL,
    pdf_filename TEXT NOT NULL,
    page_number INTEGER,
    extraction_status TEXT NOT NULL DEFAULT 'completed',
    confidence NUMERIC(5, 4) NOT NULL DEFAULT 0.8000,
    confidence_label TEXT NOT NULL DEFAULT 'high',
    raw_excerpt TEXT,
    extracted_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, case_sequence)
);

CREATE INDEX IF NOT EXISTS idx_pi_case_records_tier_date ON public.pi_case_records (court_type, state_code, district_code, bench_code, listing_date DESC);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_case_number ON public.pi_case_records (case_number);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_cnr ON public.pi_case_records (cnr_number);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_diary ON public.pi_case_records (diary_number);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_case_type ON public.pi_case_records (case_type);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_listing_date ON public.pi_case_records (listing_date DESC);
CREATE INDEX IF NOT EXISTS idx_pi_case_records_document ON public.pi_case_records (document_id);

-- 6. Daily Analytics Summary Table (Supports Supreme Court, High Courts, District Courts)
CREATE TABLE IF NOT EXISTS public.pi_daily_analytics (
    id BIGSERIAL PRIMARY KEY,
    analytics_scope_key TEXT NOT NULL UNIQUE,
    analytics_date DATE NOT NULL,
    court_type TEXT NOT NULL CHECK (court_type IN ('supreme_court', 'high_court', 'district_court')),
    state_code TEXT,
    state_name TEXT,
    district_code TEXT,
    district_name TEXT,
    complex_code TEXT,
    complex_name TEXT,
    establishment_code TEXT,
    establishment_name TEXT,
    court_code TEXT NOT NULL,
    court_name TEXT NOT NULL,
    bench_code TEXT NOT NULL,
    bench_name TEXT NOT NULL,
    pdfs_discovered INTEGER NOT NULL DEFAULT 0,
    pdfs_downloaded INTEGER NOT NULL DEFAULT 0,
    pdfs_processed INTEGER NOT NULL DEFAULT 0,
    cause_list_pdfs INTEGER NOT NULL DEFAULT 0,
    order_judgment_pdfs INTEGER NOT NULL DEFAULT 0,
    total_case_records INTEGER NOT NULL DEFAULT 0,
    cause_list_cases INTEGER NOT NULL DEFAULT 0,
    order_judgment_cases INTEGER NOT NULL DEFAULT 0,
    extraction_failures INTEGER NOT NULL DEFAULT 0,
    processing_success_rate NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    cases_by_type JSONB NOT NULL DEFAULT '{}'::jsonb,
    cases_by_judge JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pi_daily_analytics_date_tier ON public.pi_daily_analytics (analytics_date DESC, court_type, state_code);

COMMIT;


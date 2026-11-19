-- Local-only demo schema. Run this only against the ecourts_demo database.
CREATE TABLE IF NOT EXISTS public.ecourts_pdfs (
    id SERIAL PRIMARY KEY,
    timestamp_utc TIMESTAMPTZ,
    local_pdf_path TEXT,
    pdf_filename TEXT,
    judge_names TEXT,
    cause_list_type TEXT,
    cause_list_date DATE,
    bench_id TEXT,
    cause_list_id TEXT,
    eliminated BOOLEAN DEFAULT FALSE,
    file_size_bytes BIGINT,
    download_status TEXT,
    content_type TEXT,
    judge_name TEXT,
    reference_name TEXT,
    state_code TEXT,
    district_code TEXT,
    court_code TEXT,
    UNIQUE (cause_list_date, reference_name)
);
CREATE INDEX IF NOT EXISTS idx_demo_pdfs_date ON public.ecourts_pdfs(cause_list_date DESC);
CREATE INDEX IF NOT EXISTS idx_demo_pdfs_judge ON public.ecourts_pdfs(judge_name);

CREATE TABLE IF NOT EXISTS public.scraper_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    state_code TEXT,
    district_code TEXT,
    court_code TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    cause_lists INTEGER DEFAULT 0,
    pdfs_downloaded INTEGER DEFAULT 0,
    pdfs_skipped INTEGER DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS public.supreme_court_cases (
    id SERIAL PRIMARY KEY,
    judge_name TEXT,
    tier TEXT,
    year INTEGER,
    case_id TEXT,
    title TEXT,
    state TEXT,
    bench TEXT,
    district TEXT,
    complex TEXT,
    status TEXT,
    diary_number TEXT,
    advocates TEXT,
    judgment_by TEXT,
    judgment_date DATE,
    duration_days INTEGER,
    judgment_url TEXT,
    citation TEXT,
    citation_url TEXT,
    source_url TEXT,
    verdict TEXT,
    verified_outcome TEXT,
    outcome_verified_at TIMESTAMPTZ,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.supreme_court_judges (
    judge_name TEXT PRIMARY KEY,
    total_cases INTEGER NOT NULL DEFAULT 0,
    unique_cases INTEGER NOT NULL DEFAULT 0,
    earliest_judgment DATE,
    latest_judgment DATE,
    years_active INTEGER NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

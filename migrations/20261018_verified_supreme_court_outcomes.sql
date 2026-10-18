ALTER TABLE supreme_court_cases
    ADD COLUMN IF NOT EXISTS verified_outcome TEXT;

ALTER TABLE supreme_court_cases
    ADD COLUMN IF NOT EXISTS outcome_verified_at TIMESTAMPTZ;

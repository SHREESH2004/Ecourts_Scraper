-- Check what values exist in the status field
SELECT DISTINCT status, COUNT(*) as count
FROM supreme_court_cases
WHERE status IS NOT NULL
GROUP BY status
ORDER BY count DESC;

-- Check judgment_by field for clues
SELECT DISTINCT judgment_by, COUNT(*) as count
FROM supreme_court_cases
WHERE judgment_by IS NOT NULL AND judgment_by <> ''
GROUP BY judgment_by
ORDER BY count DESC
LIMIT 20;

-- Check a few sample records to see what data looks like
SELECT id, title, status, judgment_by, duration_days
FROM supreme_court_cases
WHERE duration_days IS NOT NULL
ORDER BY duration_days DESC
LIMIT 10;
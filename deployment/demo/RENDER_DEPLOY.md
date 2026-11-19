# Render deployment

This guide deploys the demo as a Render Web Service and connects it to the separate Render PostgreSQL database. It does not use the PostgreSQL server on your laptop.

## Web service settings

- Repository branch: `demo-showcase`
- Root directory: `deployment/demo`
- Build command: `pip install -r requirements.txt && python restore_demo_database.py`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`

The `Procfile` contains the same start command. The service must bind to `0.0.0.0` and Render's assigned `$PORT`.

## Environment variables

In the web service's **Environment** page, add these values. Use the internal hostname from the Render Postgres **Connect** page, and keep the password in Render's secret field only.

```text
DB_HOST=dpg-dbuic5ek1f9s73abtd9g-a
DB_PORT=5432
DB_NAME=judges_ctdy
DB_USER=judges_ctdy_user
DB_PASSWORD=<set this as a secret in Render>
DEMO_MODE=1
LOCAL_PDF_DIR=downloaded_pdfs
```

Do not set `DB_HOST` to `localhost`; that would refer to the web service container. Do not commit the database password or put it in `.env.example`.

## Create the tables

Run `local-postgres-schema.sql` against the new Render database one time. From the Render Postgres **Connect** page, copy its external PSQL command/connection URL, then use the external URL from your laptop with `sslmode=require`:

```powershell
psql "<Render external database URL with sslmode=require>" -f ".\deployment\demo\local-postgres-schema.sql"
```

Confirm the target database is `judges_ctdy` before running the schema. This creates the demo tables; it does not copy any local PostgreSQL records or PDFs.

## Import 1,000 Supreme Court records

The demo folder includes `supreme_court_sample_1000.csv`, a 1,000-row copy from the project source CSV. It is about 0.51 MB. After connecting `psql` to the Render database above, import it once with this client-side command:

```text
\copy public.supreme_court_cases (judge_name, tier, year, case_id, title, state, bench, district, complex, status, diary_number, advocates, judgment_by, judgment_date, duration_days, judgment_url, citation, citation_url, source_url) FROM 'C:/Users/Shreesh/Downloads/scraper_codex - Copy/deployment/demo/supreme_court_sample_1000.csv' WITH (FORMAT csv, HEADER true)
```

This loads the 19 CSV columns into the matching table columns. Run it once to avoid duplicate rows. It does not modify the original source CSV.

## Data limitations

- The schema alone has no PDF metadata rows. The existing local import script writes laptop-specific PDF paths, so do not run it against Render unchanged.
- PDF files must also be made available to the service under `downloaded_pdfs` or served from another storage service before the PDF viewer can open them.
- `high_court_decisions.sqlite3` remains ignored by Git. The compressed read-only sample `high_court_decisions.sqlite3.gz` is bundled with this demo; the build command restores and checks the SQLite file before the service starts.
- `DEMO_MODE=1` disables the scraper in the deployed demo.

The Render service should use the Postgres internal hostname when it runs in the same Render region as the database. Use the external URL only for the one-time schema command from your laptop.

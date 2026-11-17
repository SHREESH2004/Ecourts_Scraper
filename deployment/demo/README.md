# Local eCourts demo

This is a local-only copy of the app. It uses the demo High Court SQLite sample, a separate `ecourts_demo` PostgreSQL database, and PDFs already in `deployment/downloaded_pdfs`. It does not use Supabase or a tunnel. Flask binds to `127.0.0.1`, so the app is reachable only from this laptop. The scraper is enabled and writes only to `ecourts_demo` and `deployment/demo/downloaded_pdfs`.

## Included

- The Flask app and static frontend.
- `high_court_decisions.sqlite3`: a real scraped-data sample of about 250 MB. See `demo-data-details.md` for its exact counts and date range.
- A local PostgreSQL schema and importer for PDF metadata.
- A script that reads the project’s `all_listings.csv` and local PDFs without modifying the CSV.

Existing PDFs are not copied or changed; they remain inside `deployment/downloaded_pdfs` and are read through `../downloaded_pdfs`. Newly scraped PDFs go in `deployment/demo/downloaded_pdfs`, also inside the deployment folder. The app searches both folders. If you move the demo folder, set `LOCAL_PDF_DIR` in `.env` to the correct existing-PDF path.

## Set up local PostgreSQL once

PostgreSQL must be running on `127.0.0.1:5432`. The demo uses a separate local database named `ecourts_demo`; it does not write to the main app's `ecourts_scraper` database.

1. Install PostgreSQL for Windows if it is not already installed. During setup, note the password you choose for the `postgres` user and keep the default port `5432`.
2. Open PowerShell in this folder and create the local environment file:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Put your local PostgreSQL password in `DB_PASSWORD`. The host and database should remain `127.0.0.1` and `ecourts_demo`.

3. Install the demo's Python dependencies and create the local database/schema, then import metadata:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\setup-local-postgres.ps1
   ```

The setup script reads the password from `.env`, creates `ecourts_demo` if needed, applies `local-postgres-schema.sql`, then imports metadata. The importer reads the project `all_listings.csv` and `deployment/downloaded_pdfs`; it writes rows only to the `ecourts_demo` PostgreSQL database. It skips entries whose PDF file is not present locally. It does not copy or edit the CSV or PDF files.

## Start the local app

Run:

```powershell
.\start-demo.ps1
```

Then open `http://127.0.0.1:3000/`. High Court pages use the included SQLite sample. The PDFs page searches metadata in local PostgreSQL and opens files from the laptop’s local PDF folder. Supreme Court and scraper-history tables are created empty; this demo does not import their production records or enable scraping.

## Refresh the High Court sample

From the project root, with Node.js 22 or newer:

```powershell
node --experimental-sqlite .\deployment\demo\build_demo_database.mjs
```

This reads the full index read-only, keeps every 32nd decision ID, and writes only inside this demo folder. The CSV source files are not modified. Sample totals must not be presented as totals for the full scraped index.

## Local data and safety

- `.env` is local and ignored; never share it.
- The PostgreSQL database name is `ecourts_demo` to keep this demo separate from any other local database.
- The local PDF API only serves files under `LOCAL_PDF_DIR` and the app listens only on localhost.
- Estimated appeal outcomes are based on scraped docket, party, and disposition text, not verified trial-court conviction rates.

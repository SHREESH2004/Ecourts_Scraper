# eCourts Judicial Intelligence

A Python-based scraper and Flask application for collecting, indexing, and exploring eCourts cause-list PDFs and judicial metadata. The project combines automated scraping, PostgreSQL persistence, local PDF storage, and a lightweight dashboard for searching judges, court records, and recent activity.

This repository is designed for real-world deployment and local operation. It includes:

- a cause-list scraper for Indian High Courts
- safe, organized PDF storage by state/court
- PostgreSQL-backed metadata indexing
- a browser dashboard and REST API
- Supreme Court judgment import tooling
- deployment notes for AWS/Supabase-style hosting

## Overview

The application follows a simple flow:

1. The scraper visits eCourts court data and downloads cause-list PDF files.
2. Files are saved under a state/court directory structure, such as:
   `downloaded_pdfs/Bombay/Appellate_Side_Bombay/`
3. PDF metadata and judicial references are stored in PostgreSQL.
4. The Flask web app serves a dashboard and API for searching judges, PDFs, and court activity.
5. Optional Supreme Court imports add an additional dataset for broader judicial intelligence.

This is not a generic legal dataset project; it is focused on operational access to eCourts records, stored in a searchable, deployable format.

## Features

- High Court cause-list scraping and PDF retrieval
- Automatic directory organization by state and court name
- PostgreSQL-backed indexing for documents and runs
- Judge directory and document search APIs
- Dashboard pages for overview, judges, PDFs, and scraper runs
- PDF serving with safe path validation
- Supreme Court case import and judge summary refresh
- Local development and production deployment support
- AWS / Elastic Beanstalk friendly Procfile and deployment configuration

## Tech Stack

- Python 3
- Flask
- PostgreSQL
- psycopg2
- PyPDF2
- Requests
- Gunicorn
- static HTML/CSS/JS frontend

## Repository Structure

```text
.
├── app.py                     # Flask application and API endpoints
├── data_service.py            # PostgreSQL + PDF query layer
├── court_mapper.py            # High court mapping metadata
├── import_supreme_court.py    # Supreme Court CSV ingestion script
├── requirements.txt           # Python dependencies
├── Procfile                   # Gunicorn startup config
├── .env.example              # Root local environment template
├── deployment/               # Hosted deployment settings and AWS notes
│   ├── .env.example
│   ├── .env
│   └── README.md
├── scraper/
│   └── 1.py                  # Main cause-list scraper
├── static/                    # Dashboard frontend assets
├── downloaded_pdfs/          # Downloaded PDFs saved by state/court
├── analyze_*.py              # Data analysis helper scripts
├── test_analyze.py            # Basic validation script
├── STATUS.txt                # Implementation status notes
├── IMPLEMENTATION_SUMMARY.md # Project implementation notes
└── README.md                 # This file
```

## Prerequisites

Before running the project, make sure you have:

- Python 3.10+ recommended
- PostgreSQL server running
- access to the eCourts data source
- a configured `.env` file or equivalent environment variables

## Getting Started

### 1) Clone the repository

```bash
git clone <your-repo-url>
cd scraper_codex
```

### 2) Create a virtual environment

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure environment variables

Copy the example file and fill in your database credentials:

```bash
copy .env.example .env
```

Then edit `.env` with your values:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ecourts_scraper
DB_USER=postgres
DB_PASSWORD=your_secure_password
PORT=5000
```

Important:

- never hardcode production credentials into source files
- never commit `.env` files to version control
- use a secure secret manager or environment variable store in real deployments

## Running the App

Start the Flask app locally:

```bash
python app.py
```

The app typically runs on:

```text
http://localhost:5000
```

For production-style deployment:

```bash
gunicorn --workers 1 --threads 4 --timeout 120 app:app
```

The app exposes pages and APIs including:

- `/` — dashboard overview
- `/judges` — judge directory
- `/pdfs` — PDF catalog
- `/runs` — scraper runs
- `/api/overview` — summary stats
- `/api/judges` — judge search and listing
- `/api/pdfs` — PDF metadata queries

## Running the Scraper

The main scraper is in `scraper/1.py`.

Basic usage:

```bash
python "scraper/1.py" --state "Maharashtra" --court 1 --days 7
```

The scraper supports additional options such as:

- `--state` — state name or code
- `--court` — court code
- `--days` — number of recent days to fetch
- `--date-workers` — parallel date fetch workers
- `--pdf-workers` — parallel PDF download workers
- `--loop-hours` — repeat in a loop

Example with a loop:

```bash
python "scraper/1.py" --state "Bombay" --court 1 --days 30 --loop-hours 12
```

The scraper writes run logs and records metadata in PostgreSQL while saving PDF files under `downloaded_pdfs/`.

## PDF Storage Behavior

PDFs are stored in a structured hierarchy:

```text
downloaded_pdfs/
  Bombay/
    Appellate_Side_Bombay/
      20260928_abc123.pdf
```

The system sanitizes file and folder names and stores records by state and court names for easier browsing and later retrieval.

## PostgreSQL Setup

The project expects a PostgreSQL database with the tables used by the app and scraper, including most importantly the document metadata table(s) used by `data_service.py` and the scraper run tracking records.

Typical configuration values:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ecourts_scraper
DB_USER=postgres
DB_PASSWORD=your_password
```

The application uses these values to build its database connection pool and should fail gracefully if the database is unavailable.

## Supreme Court Data Import

To import Supreme Court judgment data:

```bash
python import_supreme_court.py
```

This script reads `supreme_court_all_judges.csv` and populates the Supreme Court tables used by the dashboard and related APIs.

## Deployment Notes

The repository includes a deployment-ready configuration for hosting environments such as AWS Elastic Beanstalk or a Supabase-backed architecture.

Relevant deployment files:

- `Procfile`
- `deployment/.env.example`
- `deployment/README.md`

Deployment notes from this repo include:

- use environment secrets instead of hardcoded credentials
- configure PostgreSQL settings securely
- ensure the hosting platform’s health check path is `/health` when used in a platform deployment
- keep PDF storage bucket private if using Supabase Storage

For production deployment details, see [deployment/README.md](deployment/README.md).

## Security and Operational Notes

- never commit `.env` or secrets to the repository
- do not expose database credentials in logs or frontend code
- validate PDFs before serving them
- keep PDF storage private and restrict access by design
- use a protected Postgres connection in production environments

## Common Troubleshooting

### Database connection errors

Check:

- PostgreSQL is running
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are correct
- your database allows remote/local connections if applicable

### Incorrect PDF path or file missing

Check:

- the scraper has completed successfully
- the `downloaded_pdfs` directory exists
- the PDF filename is present on disk

### App does not load

Check:

- dependencies were installed with `pip install -r requirements.txt`
- environment variables are loaded correctly
- the Flask app can reach PostgreSQL

## Future Improvements

This project is already useful for legal data operations, and the following areas are natural next steps:

- better archival cleanup for stale PDFs
- stronger indexing for judge aliasing and normalization
- richer API filters and pagination
- scheduled scraping automation with cron or a worker service
- enhanced testing and CI validation
- optional Docker support for easier local environments

## License

This project does not currently declare a license file. If you are publishing or redistributing it, add a license before public release.

## Contributing

Contributions are welcome. The project works best when changes are made with these principles in mind:

- keep scraper logic isolated and readable
- maintain security around credentials and file access
- prefer clear, reproducible data flows over brittle shortcuts
- document any new environment variables or deployment assumptions

## Summary

This repository is a full-stack, Python-driven judicial document intelligence system focused on eCourts cause-list data. It is practical, deployable, and designed for real-world operation with PostgreSQL-backed storage, organized PDF records, and a dashboard for investigation and search.

If you are setting this up for the first time, start with:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Then run the scraper and explore the dashboard.

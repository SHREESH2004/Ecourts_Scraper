# AWS deployment

This folder contains the Flask application, static frontend, PostgreSQL data
service, and scraper. Its `Procfile` starts the app with Gunicorn and is suitable
for an AWS Elastic Beanstalk Python environment.

## Configure Supabase

The application and scraper issue PostgreSQL queries directly. The deployment
defaults are configured for the Supabase direct PostgreSQL endpoint
`db.dvsjnzrouwywaqcacwsl.supabase.co:5432`, database `postgres`, user
`postgres`, with SSL required. Set `DB_PASSWORD` to the database password from
Supabase Dashboard > Database Settings. Alternatively, set `DATABASE_URL` to a
connection string from Supabase Dashboard > Connect; it takes precedence over
the individual `DB_*` settings. If AWS cannot reach the direct endpoint, use
the Supabase session pooler connection string.

`SUPABASE_URL` and `SUPABASE_KEY` are Data API settings; the publishable key is
not a PostgreSQL credential and does not replace `DATABASE_URL`. This app does
not query Supabase's REST API. Its PostgreSQL database must contain the tables
used by the application (`ecourts_pdfs` and `scraper_runs`). The scraper
creates its own tables when triggered.

For local development, copy `.env.example` to `.env` and set `DB_PASSWORD` (or
`DATABASE_URL`). `.env` is ignored by Git. On AWS, configure the database
settings as Elastic Beanstalk environment properties; do not upload `.env`.

## Store PDFs in Supabase Storage

Create a private Storage bucket named `Ecourts`, then set
`SUPABASE_S3_ENDPOINT_URL`, `SUPABASE_S3_REGION`, `SUPABASE_S3_BUCKET`,
`SUPABASE_S3_ACCESS_KEY_ID`, and `SUPABASE_S3_SECRET_ACCESS_KEY` in the local
ignored `.env` or the hosting provider's secret environment settings. The
scraper validates each PDF in memory and uploads it directly to the bucket
using its filename as the object key. PDF bytes are not written to deployment
disk. The app checks for the object and redirects PDF views/downloads to a
short-lived signed URL; bucket objects remain private. Scraping is refused
when the Supabase Storage settings are missing.
Scraper output and errors are written to standard output/error so the hosting
platform captures them; the scraper does not create a local log file.

Imported Supreme Court cases use their judgment URLs from the source CSV and
redirect directly to `api.sci.gov.in`; those PDFs are not copied to the app's
disk or uploaded to the bucket.

Only these `SUPABASE_S3_*` settings are used for PDF storage. Keep the access
key secret server-side; never put it in frontend code or commit it. Existing
PDFs already on a local disk are not automatically migrated.

## Deploy

Create an Elastic Beanstalk Python application/environment and deploy the
contents of this `deployment` folder as the application source bundle. The
`Procfile` starts Gunicorn on the port supplied by the platform. Configure the
load balancer health check path as `/health`; this endpoint intentionally does
not require application credentials.

Scraped cause-list PDFs are stored in the private Supabase Storage bucket, not
on the instance disk. Supreme Court judgment links open the source URL supplied
with the imported case data.

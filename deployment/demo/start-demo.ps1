$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\high_court_decisions.sqlite3")) {
    throw "Demo database is missing. Build it from the project root using build_demo_database.mjs."
}

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install the demo requirements." }

$env:HIGH_COURT_DECISIONS_DB = Join-Path $PSScriptRoot "high_court_decisions.sqlite3"
$env:LOCAL_PDF_DIR = Join-Path $PSScriptRoot "..\downloaded_pdfs"
$env:DB_HOST = "127.0.0.1"
$env:DB_NAME = "ecourts_demo"
$env:PORT = "3000"
$env:DEMO_MODE = "0"
$pgStatus = Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue
if (-not $pgStatus.TcpTestSucceeded) {
    Write-Warning "Local PostgreSQL is not responding on 127.0.0.1:5432. High Court pages can run; PDF/PostgreSQL pages need the local database set up first. See README.md."
}
& ".\.venv\Scripts\python.exe" app.py

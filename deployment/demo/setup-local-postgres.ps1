$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.env")) {
    throw "Create .env from .env.example and set DB_PASSWORD to your local PostgreSQL password first."
}

$psqlCommand = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psqlCommand) {
    throw "psql was not found. Install PostgreSQL for Windows and add its bin folder to PATH, then reopen PowerShell."
}

$settings = @{}
foreach ($line in Get-Content ".\.env") {
    if ($line -match '^\s*([^#=]+)=(.*)$') {
        $settings[$matches[1].Trim()] = $matches[2].Trim().Trim('"').Trim("'")
    }
}

$dbHost = if ($settings.DB_HOST) { $settings.DB_HOST } else { "127.0.0.1" }
$dbPort = if ($settings.DB_PORT) { $settings.DB_PORT } else { "5432" }
$dbName = if ($settings.DB_NAME) { $settings.DB_NAME } else { "ecourts_demo" }
$dbUser = if ($settings.DB_USER) { $settings.DB_USER } else { "postgres" }
$env:PGPASSWORD = $settings.DB_PASSWORD

try {
    $pgStatus = Test-NetConnection -ComputerName $dbHost -Port ([int]$dbPort) -WarningAction SilentlyContinue
    if (-not $pgStatus.TcpTestSucceeded) {
        throw "PostgreSQL is not listening on ${dbHost}:${dbPort}. Start the local PostgreSQL service and retry."
    }

    $databaseExists = & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$dbName'"
    if ($LASTEXITCODE -ne 0) { throw "Could not connect to local PostgreSQL. Check DB_USER and DB_PASSWORD in .env." }
    if (-not ($databaseExists | Where-Object { $_.Trim() -eq "1" })) {
        & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $dbName"
        if ($LASTEXITCODE -ne 0) { throw "Could not create the local $dbName database." }
    }

    & psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -v ON_ERROR_STOP=1 -f ".\local-postgres-schema.sql"
    if ($LASTEXITCODE -ne 0) { throw "Could not apply the local demo schema." }

    if (Test-Path ".\.venv\Scripts\python.exe") {
        & ".\.venv\Scripts\python.exe" ".\seed_local_pdf_metadata.py"
    } else {
        py -3 ".\seed_local_pdf_metadata.py"
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not import local PDF metadata. Check the message above." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

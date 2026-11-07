# Local development: starts the bundled MariaDB (var/) and the Flask dev server.
# Usage:  .\run-local.ps1
$root = $PSScriptRoot
$mariadb = Join-Path $root "var\mariadb\bin\mariadbd.exe"
$dataDir = Join-Path $root "var\mysql-data"

if (-not (Get-Process mariadbd -ErrorAction SilentlyContinue)) {
    Write-Host "Starting MariaDB..."
    Start-Process -FilePath $mariadb `
        -ArgumentList "--defaults-file=`"$dataDir\my.ini`"", "--datadir=`"$dataDir`"", "--port=3306", "--bind-address=127.0.0.1" `
        -WindowStyle Hidden `
        -RedirectStandardError (Join-Path $root "var\logs\mariadb.err.log")
    Start-Sleep -Seconds 3
}

Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") -m flask db upgrade
& (Join-Path $root ".venv\Scripts\python.exe") -m flask run --host 127.0.0.1 --port 5000

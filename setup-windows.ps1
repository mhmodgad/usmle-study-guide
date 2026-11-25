# Prepares a fresh Windows machine (no prerequisites) to run the USMLE Study Guide app.
# Installs Python if needed, creates a virtual environment, installs dependencies,
# and builds the database. Run it once via setup-windows.bat (double-click).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  USMLE Study Guide - Windows setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# --- 1. Ensure Python is installed -------------------------------------------
$py = $null
if (Have "py")     { $py = "py -3" }
elseif (Have "python") { $py = "python" }

if (-not $py) {
    Write-Host "`nPython is not installed. Installing Python 3.12..." -ForegroundColor Yellow
    if (Have "winget") {
        winget install -e --id Python.Python.3.12 --scope machine `
            --accept-source-agreements --accept-package-agreements
    } else {
        $url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $out = Join-Path $env:TEMP "python-installer.exe"
        Write-Host "Downloading Python from python.org ..."
        Invoke-WebRequest -Uri $url -OutFile $out
        Write-Host "Installing Python (adds it to PATH)..."
        Start-Process -FilePath $out -Wait -ArgumentList `
            "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1"
    }
    # refresh PATH in this session
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
    if (Have "py")     { $py = "py -3" }
    elseif (Have "python") { $py = "python" }
    if (-not $py) {
        throw "Python was installed but is not on PATH yet. Close this window, open a NEW one, and run setup again."
    }
}
Write-Host "Using Python command: $py" -ForegroundColor Green

# --- 2. Virtual environment --------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "`nCreating virtual environment (.venv)..."
    Invoke-Expression "$py -m venv .venv"
}
$pyv = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# --- 3. Dependencies ---------------------------------------------------------
Write-Host "`nInstalling dependencies (Flask)..."
& $pyv -m pip install --upgrade pip --quiet
& $pyv -m pip install -r requirements.txt

# --- 4. Build the stylesheet (only if source CSS is present and app.css is missing)
if ((Test-Path "local\css") -and -not (Test-Path "static\css\app.css")) {
    Write-Host "`nBuilding stylesheet..."
    & $pyv -m tempu.build_css
}

# --- 5. Build the database ---------------------------------------------------
if (Test-Path "data\tempu.db") {
    Write-Host "`nDatabase already present (data\tempu.db) - skipping build."
} elseif (Test-Path "local\content") {
    Write-Host "`nBuilding database from local\content ..."
    & $pyv -m tempu.loader
} else {
    Write-Host "`n[!] No data\tempu.db and no local\content found." -ForegroundColor Yellow
    Write-Host "    Do ONE of these, then run setup again:" -ForegroundColor Yellow
    Write-Host "      - copy your prebuilt data\tempu.db into the data\ folder, OR" -ForegroundColor Yellow
    Write-Host "      - put your content under local\content\ (see local\README.md)" -ForegroundColor Yellow
}

Write-Host "`n==================================================" -ForegroundColor Green
Write-Host "  Setup complete." -ForegroundColor Green
Write-Host "  Start the app by double-clicking:  run-windows.bat" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

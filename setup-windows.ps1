# Prepares a fresh Windows machine (no prerequisites) to run the USMLE Study Guide app.
# Installs Git and Python if needed, creates a virtual environment, installs
# dependencies, and builds the database. Run it once via setup-windows.bat (double-click).
# (Code updates happen automatically on every launch - see run-windows.bat.)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  USMLE Study Guide - Windows setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# --- 0. Ensure Git is installed ----------------------------------------------
if (-not (Have "git")) {
    Write-Host "`nGit is not installed. Installing Git..." -ForegroundColor Yellow
    if (Have "winget") {
        winget install -e --id Git.Git `
            --accept-source-agreements --accept-package-agreements
    } else {
        $url = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe"
        $out = Join-Path $env:TEMP "git-installer.exe"
        Write-Host "Downloading Git ..."
        Invoke-WebRequest -Uri $url -OutFile $out
        Write-Host "Installing Git..."
        Start-Process -FilePath $out -Wait -ArgumentList "/VERYSILENT /NORESTART"
    }
    Refresh-Path
    $gitCmd = "C:\Program Files\Git\cmd"
    if (-not (Have "git") -and (Test-Path $gitCmd)) { $env:Path += ";$gitCmd" }
    if (-not (Have "git")) {
        Write-Host "Git was installed but is not on PATH yet. Close this window and run setup again." -ForegroundColor Yellow
    }
}
if (Have "git") { Write-Host "Git found: $(git --version)" -ForegroundColor Green }

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
    Refresh-Path
    if (Have "py")     { $py = "py -3" }
    elseif (Have "python") { $py = "python" }
    if (-not $py) {
        throw "Python was installed but is not on PATH yet. Close this window, open a NEW one, and run setup again."
    }
}
Write-Host "Using Python command: $py" -ForegroundColor Green

# --- 2. Virtual environment --------------------------------------------------
# A .venv copied from macOS/Linux has bin/ instead of Scripts\ and won't work on
# Windows, so rebuild it unless a valid Windows venv is already present.
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Test-Path ".venv") {
        Write-Host "`nFound a non-Windows .venv - removing and recreating it..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force ".venv"
    }
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

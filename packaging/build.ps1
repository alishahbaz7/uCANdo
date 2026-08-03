# Build a shareable uCANdo bundle (Windows). Run from the project root:
#     .\packaging\build.ps1
# Produces:  dist\uCANdo\uCANdo.exe   and   dist\uCANdo_v<version>.zip
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

$ver = (& $py -c "import ucando; print(ucando.__version__)").Trim()
Write-Host "Building uCANdo v$ver ..." -ForegroundColor Cyan

& $py -m pip install --quiet pyinstaller
& $py -m PyInstaller "packaging\uCANdo.spec" --noconfirm --distpath dist --workpath build\pyi --log-level WARN
if (-not (Test-Path "dist\uCANdo\uCANdo.exe")) { throw "Build failed — no exe produced." }

# drop a one-line launcher + readme next to the exe, then zip the folder
@"
uCANdo v$ver — Unified CAN Workbench
Double-click uCANdo.exe. It serves the UI at http://127.0.0.1:8765 and opens your browser.
Runs fully offline on localhost only — it does not use or affect your internet/network.
Your captures, logs and database are written to the 'data' folder next to the exe.
To stop: close the console window.
"@ | Set-Content "dist\uCANdo\README.txt"

$zip = "dist\uCANdo_v$ver.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\uCANdo\*" -DestinationPath $zip
Write-Host "Done: $zip" -ForegroundColor Green

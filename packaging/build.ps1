# Build a uCANdo release (Windows). Run from anywhere:
#     .\packaging\build.ps1               build what is missing, then package
#     .\packaging\build.ps1 --rebuild     a fresh program and launcher build
# Produces, in dist\:  uCANdo-v<version>.zip, latest.json, notes.md and a runnable
# uCANdo-v<version>\ install (uCANdo.exe = the launcher; the program in versions\).
# The work is packaging\build_release.py (app-updates: the launcher install that
# updates itself); this script only finds the venv and runs it.
#
# ASCII only, deliberately. Windows PowerShell 5.1 decodes a BOM-less script as
# cp1252 - any non-ASCII character becomes mojibake and breaks the parser.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No venv at .venv - see CLAUDE.md for setup." }

& $py -m pip install --quiet pyinstaller
& $py (Join-Path $root "packaging\build_release.py") @args
if ($LASTEXITCODE -ne 0) { throw "build_release.py failed ($LASTEXITCODE)" }

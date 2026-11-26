# Build a shareable uCANdo bundle (Windows). Run from the project root:
#     .\packaging\build.ps1
# Produces:  dist\uCANdo\uCANdo.exe   and   dist\uCANdo_v<version>.zip
#
# ASCII only, deliberately. This file is UTF-8 without a BOM, and Windows
# PowerShell 5.1 decodes such a script as cp1252 - any non-ASCII character
# (an em-dash, an arrow) becomes mojibake and breaks the parser. Keeping it
# plain ASCII means it runs the same under powershell.exe and pwsh.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No venv at .venv - see CLAUDE.md for setup." }

$ver = (& $py -c "import ucando; print(ucando.__version__)").Trim()
Write-Host "Building uCANdo v$ver ..." -ForegroundColor Cyan

& $py -m pip install --quiet pyinstaller
& $py -m PyInstaller "packaging\uCANdo.spec" --noconfirm --distpath dist --workpath build\pyi --log-level WARN
if (-not (Test-Path "dist\uCANdo\uCANdo.exe")) { throw "Build failed - no exe produced." }

# Sanity-check the bundle carries the assets the app reads at runtime, rather
# than finding out on the teammate's machine.
foreach ($rel in @("_internal\web\index.html", "_internal\web\app.js",
                   "_internal\oem_packs", "_internal\ucando\protocols")) {
    if (-not (Test-Path (Join-Path "dist\uCANdo" $rel))) {
        throw "Bundle is missing $rel - check datas in packaging\uCANdo.spec"
    }
}

@"
uCANdo v$ver - Unified CAN Workbench

Double-click uCANdo.exe. It serves the UI at http://127.0.0.1:8765 and opens
it in its own window. To stop it, close the console window.

Runs on localhost only and opens no network ports. Captures, logs, the parse
cache and the database are written to the 'data' folder next to the exe, so
keep this folder somewhere writable.

Usage reporting: uCANdo asks your name once, to greet you, and sends a small
usage report (your name, this computer, the version, how long it ran, the
views opened, errors and counts such as recordings) to its usage server. It
never sends CAN data, logs, DBCs or VINs. Settings -> Usage reporting shows
it all; set UCANDO_USAGE=off to switch it off. Offline is fine - reports wait.

Hardware
  Virtual bus       works out of the box (no adapter needed - good for a tour)
  PCAN              needs the PEAK PCAN-Basic driver installed
  Neo VI (Intrepid) needs the Intrepid API/driver kit installed
  Microchip/SLCAN   needs the analyzer flashed with SLCAN firmware
The Dashboard shows a hardware-readiness panel if a driver is missing.

What is new in this build
  New look     Auto / Light / Dark theme, a resizable side rail, and its own
               window with its own taskbar button (pin it to start uCANdo).
               Settings -> Views hides any view you do not use.
  TX Replay    upload several logs at once as a playlist, see which file is
               being sent, and replay PCAN-View .trc files as well as Vehicle
               Spy and .asc logs.
  Transmit     every transmitted signal as a tile, as the device's cloud
  signal       panel would show it (pin the ones your cloud shows), or every
               transmitted ID byte by byte with changed bytes lit.
  Lost bus     unplug the device under test, or let the bus go bus-off, and
               playback waits for the bus, resets the adapter and carries on
               by itself. Only Stop ends the wait.
  Usage        your name once at the first start, then "Hello, <name>".
"@ | Set-Content "dist\uCANdo\README.txt" -Encoding UTF8

$zip = "dist\uCANdo_v$ver.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\uCANdo\*" -DestinationPath $zip
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Done: $zip  ($mb MB)" -ForegroundColor Green

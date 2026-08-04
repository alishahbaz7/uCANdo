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
your browser. To stop it, close the console window.

Runs fully offline on localhost only. It does not use or affect your network.
Captures, logs, the parse cache and the database are written to the 'data'
folder next to the exe, so keep this folder somewhere writable.

Hardware
  Virtual bus       works out of the box (no adapter needed - good for a tour)
  PCAN              needs the PEAK PCAN-Basic driver installed
  Neo VI (Intrepid) needs the Intrepid API/driver kit installed
  Microchip/SLCAN   needs the analyzer flashed with SLCAN firmware
The Dashboard shows a hardware-readiness panel if a driver is missing.

What is new in this build
  TX Replay    replay a recorded log onto the bus in real time, with the
               bitrate read from the log itself. Repeat once / N times /
               endlessly. Build a playlist of several logs, in order, each
               with its own repeat count and lead-in gap, and save it as a
               named scenario.
  Signal patch force a signal to a value while the log plays (for example
               SOC = 8%) and keep the odometer climbing across a loop
               instead of snapping backwards.
  TX Monitor   preview the exact bytes being transmitted, decode them
               against a DBC or a cloud Signature JSON to see what should
               appear on the cloud, and diff them byte-for-byte against a
               raw-frame export from the device's cloud logs.
"@ | Set-Content "dist\uCANdo\README.txt" -Encoding UTF8

$zip = "dist\uCANdo_v$ver.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\uCANdo\*" -DestinationPath $zip
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Done: $zip  ($mb MB)" -ForegroundColor Green

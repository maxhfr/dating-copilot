# Build the Windows app (run this on the Windows PC, in PowerShell).
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .build-venv
& .\.build-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean packaging\dating-copilot.spec

Write-Host ""
Write-Host "Built: dist\dating-copilot\dating-copilot.exe"
Write-Host "Windows may say 'Windows protected your PC' because the app is unsigned:"
Write-Host "click 'More info' then 'Run anyway'. On first launch it downloads Chromium (~190 MB)."
Write-Host "Config and your run log live in %USERPROFILE%\.dating-copilot\"

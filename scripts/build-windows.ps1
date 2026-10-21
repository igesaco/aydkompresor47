$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne 'Windows_NT') { throw 'Windows EXE paketi Windows üzerinde hazırlanmalıdır.' }
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 kurulumu bulunamadı.' }
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-desktop.txt
if ($LASTEXITCODE -ne 0) { throw 'Paket kurulumu başarısız.' }
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Testler başarısız. Paketleme durduruldu.' }
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name 'AYD-Kompresor' --add-data 'web;web' --collect-all webview desktop.py
if ($LASTEXITCODE -ne 0) { throw 'EXE oluşturulamadı.' }
Write-Host "Hazır: $PWD\dist\AYD-Kompresor.exe"
Write-Host 'Windows 10/11 üzerinde Microsoft Edge WebView2 Runtime gereklidir.'

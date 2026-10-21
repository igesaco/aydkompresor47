$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows EXE on Windows.' }

# Python installed without the optional py.exe launcher is supported too.
$BuildPython = $null
$BuildPythonArgs = @()
foreach ($Candidate in @('py', 'python', 'python3')) {
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if (-not $Command) { continue }
    $CandidateArgs = @()
    if ($Candidate -eq 'py') { $CandidateArgs = @('-3.12') }
    try {
        & $Command.Source @CandidateArgs -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $BuildPython = $Command.Source
            $BuildPythonArgs = $CandidateArgs
            break
        }
    } catch { continue }
}
if (-not $BuildPython) {
    Write-Host ''
    Write-Host 'Yerel EXE olusturmak icin Python 3.12 bulunamadi.' -ForegroundColor Yellow
    Write-Host 'Python kurmadan kullanmak icin hazir EXE paketini GitHub Actions sayfasindan indirin:'
    Write-Host 'https://github.com/igesaco/aydkompresor47/actions/workflows/windows-build.yml'
    Write-Host 'Yerel derleme icin python.org adresinden Python 3.12 kurun; Add python.exe to PATH secenegini isaretleyin.'
    throw 'Python 3.12 is required only for building locally, not for running the packaged EXE.'
}
& $BuildPython @BuildPythonArgs -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
$VenvPython = Join-Path $PWD '.venv\Scripts\python.exe'
& $VenvPython -m pip install -r requirements-desktop.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
New-Item -ItemType Directory -Force -Path 'build' | Out-Null
# Write unittest output to stdout so Windows PowerShell 5.1 does not treat
# ordinary test progress on stderr as a terminating NativeCommandError.
& $VenvPython -u -c "import sys, unittest; result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(unittest.defaultTestLoader.discover('tests')); sys.exit(0 if result.wasSuccessful() else 1)" | Tee-Object -FilePath 'build/windows-tests.log'
$TestExitCode = $LASTEXITCODE
if ($TestExitCode -ne 0) { throw 'Tests failed. See build/windows-tests.log. Packaging stopped.' }
& $VenvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name 'AYD-Kompresor' --add-data 'web;web' --collect-all webview desktop.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
Write-Host "Hazir: $PWD\dist\AYD-Kompresor.exe"
Write-Host 'Hedef bilgisayarda Python gerekmez. Windows 10/11 ve Microsoft Edge WebView2 Runtime gereklidir.'

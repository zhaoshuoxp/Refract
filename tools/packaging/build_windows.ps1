# Build Refract for Windows: the PyInstaller folder build, its self-test, and
# an installer (dist\Refract-<version>-windows-x64-setup.exe, Inno Setup 6).
#
#   powershell -ExecutionPolicy Bypass -File tools\packaging\build_windows.ps1
#
# Needs Python 3.12 (x64) and Inno Setup 6 (iscc on PATH or in its default folder).
# Signing: set REFRACT_SIGNTOOL_ARGS (e.g. '/fd SHA256 /tr http://timestamp.digicert.com
# /td SHA256 /a') to sign Refract.exe and the installer with signtool; unset, they
# are not signed and SmartScreen warns on first start.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Venv = Join-Path $Root ".venv-build"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    py -3.12 -m venv $Venv
    & $Py -m pip install -q numpy scipy PySide6-Essentials "pyinstaller>=6.10"
}
$Version = & $Py -c "import refract; print(refract.__version__)"
$Build = Join-Path $Root "build\windows"
$Dist = Join-Path $Root "dist"
New-Item -ItemType Directory -Force $Build, $Dist | Out-Null

Write-Host "== icons"
& $Py tools\packaging\make_icon.py (Join-Path $Build "icons")
if ($LASTEXITCODE) { throw "make_icon failed" }

Write-Host "== pyinstaller"
$env:REFRACT_ICON_DIR = Join-Path $Build "icons"
& (Join-Path $Venv "Scripts\pyinstaller.exe") --noconfirm --clean --log-level WARN `
    --workpath (Join-Path $Build "work") --distpath (Join-Path $Build "dist") tools\packaging\refract.spec
if ($LASTEXITCODE) { throw "pyinstaller failed" }
$App = Join-Path $Build "dist\Refract"

Write-Host "== licenses"
$Lic = Join-Path $Build "LICENSES"
& $Py tools\packaging\collect_licenses.py $Lic
if ($LASTEXITCODE) { throw "collect_licenses failed" }

if ($env:REFRACT_SIGNTOOL_ARGS) {
    Write-Host "== sign exe"
    & signtool sign $env:REFRACT_SIGNTOOL_ARGS.Split(" ") (Join-Path $App "Refract.exe")
}

Write-Host "== self-test"
$St = Join-Path $Build "selftest"
$p = Start-Process -FilePath (Join-Path $App "Refract.exe") -ArgumentList "selftest", "--keep", "`"$St`"" -Wait -PassThru
Get-Content (Join-Path $St "selftest.txt")
if ($p.ExitCode) { throw "self-test failed" }

Write-Host "== installer"
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $Iscc /Q "/DAppVersion=$Version" "/DSourceDir=$App" "/DIconFile=$(Join-Path $Build 'icons\Refract.ico')" `
    "/DLicenseDir=$Lic" "/O$Dist" tools\packaging\refract.iss
if ($LASTEXITCODE) { throw "iscc failed" }
$Setup = Join-Path $Dist "Refract-$Version-windows-x64-setup.exe"
if ($env:REFRACT_SIGNTOOL_ARGS) { & signtool sign $env:REFRACT_SIGNTOOL_ARGS.Split(" ") $Setup }
Write-Host "built $Setup"

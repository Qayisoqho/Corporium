param([string]$Python='python',[string]$Iscc='',[switch]$SkipDependencies)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (!(Test-Path '.desktop-venv/Scripts/python.exe')) {
    & $Python -m venv .desktop-venv
    if ($LASTEXITCODE) { throw 'Could not create build environment' }
}
$buildPython=Join-Path $projectRoot '.desktop-venv/Scripts/python.exe'
if (!$SkipDependencies) {
    & $buildPython -m pip install -r packaging/requirements-windows.txt
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
}
& $buildPython packaging/prepare_example.py
if ($LASTEXITCODE) { throw 'Example preparation failed' }
& $buildPython packaging/collect_licenses.py
if ($LASTEXITCODE) { throw 'License collection failed' }
# Version changes belong to the user. Keep VERSION; same-version builds overwrite their existing outputs.
$releaseVersion=(& $buildPython -c "from app_info import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE) { throw 'Could not read application version' }
$appOutput=Join-Path $projectRoot "release/app-$releaseVersion"
& $buildPython -m PyInstaller --noconfirm --distpath $appOutput --workpath "build/release-$releaseVersion" packaging/Corporium.spec
if ($LASTEXITCODE) { throw 'Application build failed' }
if (!$Iscc) { $Iscc=Join-Path $projectRoot 'build-tools/inno/ISCC.exe' }
if (!(Test-Path -LiteralPath $Iscc)) { throw 'Pass -Iscc with the path to the Inno Setup compiler.' }
$runtime=Join-Path $projectRoot 'build-tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
if (!(Test-Path -LiteralPath $runtime)) { throw 'Download the official WebView2 x64 offline installer into build-tools first.' }
$signature=Get-AuthenticodeSignature -LiteralPath $runtime
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Microsoft Corporation*') { throw 'WebView2 signature verification failed' }
& $Iscc "/DAppSource=$(Join-Path $appOutput 'Corporium')" packaging/Corporium.iss
if ($LASTEXITCODE) { throw 'Installer compilation failed' }
$releaseVersion=(& $buildPython -c "from app_info import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE) { throw 'Could not read application version' }
Get-FileHash -LiteralPath (Join-Path $projectRoot "release/Corporium-$releaseVersion-Windows-x64-Setup.exe") -Algorithm SHA256 | Format-List

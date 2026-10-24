$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$corporiumPython = Join-Path $PSScriptRoot '.desktop-venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $corporiumPython)) { $corporiumPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe' }
if (!(Test-Path -LiteralPath $corporiumPython)) { $corporiumPython = 'python' }
& $corporiumPython -B server.py
exit $LASTEXITCODE

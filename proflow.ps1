$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enter-Environment.ps1')
& $env:SCB_PRO_PYTHON -X utf8 (Join-Path $PSScriptRoot 'scripts\proflow.py') @args
exit $LASTEXITCODE

$ErrorActionPreference = 'Stop'
$TaskRoot = Split-Path -Parent $PSScriptRoot
$TaskConfig = Join-Path $TaskRoot 'config.json'
if (-not (Test-Path -LiteralPath $TaskConfig -PathType Leaf)) {
    throw 'Local config.json is missing. Run scripts\setup.ps1 first.'
}
$TaskSettings = Get-Content -LiteralPath $TaskConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$TaskPython = $TaskSettings.runtime.python
if ($TaskPython -and -not [System.IO.Path]::IsPathRooted($TaskPython)) {
    $TaskPython = Join-Path $TaskRoot $TaskPython
}
if (-not $TaskPython -or -not (Test-Path -LiteralPath $TaskPython -PathType Leaf)) {
    throw 'Configured Python is missing. Refresh runtime paths in config.json.'
}
& $TaskPython -X utf8 (Join-Path $PSScriptRoot 'caseflow.py') --config $TaskConfig @args
exit $LASTEXITCODE

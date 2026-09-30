param([string]$Python)
$ErrorActionPreference = 'Stop'
$TaskRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $LocalPython = Join-Path $TaskRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $LocalPython) { $Python = $LocalPython }
    elseif (Test-Path -LiteralPath (Join-Path $TaskRoot 'config.json')) {
        $Python = (Get-Content -LiteralPath (Join-Path $TaskRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json).runtime.python
        if ($Python -and -not [System.IO.Path]::IsPathRooted($Python)) { $Python = Join-Path $TaskRoot $Python }
    } else { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
}
Push-Location $TaskRoot
try {
    & $Python -X utf8 -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    & node --test tests/test_capture_audit_reuse.cjs tests/test_capture_owner_repair.cjs tests/test_capture_transition.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Node tests failed.' }
} finally { Pop-Location }

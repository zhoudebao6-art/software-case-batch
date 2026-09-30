param([string]$Python, [switch]$InstallDependencies, [switch]$InstallSkill)
$ErrorActionPreference = 'Stop'
$TaskRoot = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $TaskRoot 'config.json')) {
    if ($InstallDependencies) { throw 'Existing config.json: dependencies are not replaced. Use doctor and repair specific missing tools.' }
}
if (-not $Python) {
    $BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $BundledPython) { $Python = $BundledPython }
    else {
        $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($PythonCommand) { $Python = $PythonCommand.Source }
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Install Python 3.11+ or supply -Python path\to\python.exe.' }
& $Python -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python probe failed.' }
Push-Location $TaskRoot
try {
    if ($InstallDependencies) {
        if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
            & $Python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Venv creation failed.' }
        }
        $Python = Join-Path $TaskRoot '.venv\Scripts\python.exe'
        & $Python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
        $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $Npm) { throw 'Install Node.js with npm first.' }
        & $Npm.Source ci --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        & node (Join-Path $TaskRoot 'node_modules\playwright\cli.js') install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
    }
    $SetupArgs = @((Join-Path $PSScriptRoot 'portable_setup.py'), '--root', $TaskRoot)
    if ($InstallSkill) { $SetupArgs += '--install-skill' }
    & $Python -X utf8 @SetupArgs
    if ($LASTEXITCODE -ne 0) { throw 'Local configuration setup failed.' }
} finally { Pop-Location }

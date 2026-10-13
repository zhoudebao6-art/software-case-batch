#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [Parameter(Mandatory=$true)][string]$DestinationRoot,
    [Parameter(Mandatory=$true)][string]$BatchRoot,
    [Parameter(Mandatory=$true)][string]$StateRoot,
    [ValidateSet('Plan','Apply')][string]$Mode = 'Plan',
    [string]$EnvironmentPath,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
if (-not $EnvironmentPath) { $EnvironmentPath=Join-Path (Split-Path $PSScriptRoot -Parent) 'Enter-Environment.ps1' }
$ArchiveLock = $null
$ArchiveSummaryPath = $null
$ArchiveExitCode = 2
$ArchiveSummary = [ordered]@{ schema_version=1; started_utc=[DateTime]::UtcNow.ToString('o'); mode=$Mode; status='starting' }
$ArchiveUtf8 = New-Object System.Text.UTF8Encoding($false)

function Get-ArchivePath([string]$Value) {
    if (-not [IO.Path]::IsPathRooted($Value) -or $Value -match '["\r\n\x00]') { throw 'Archive paths must be explicit absolute paths without command-line control characters.' }
    $ArchivePath = [IO.Path]::GetFullPath($Value)
    $ArchiveRoot = [IO.Path]::GetPathRoot($ArchivePath)
    if ($ArchivePath.TrimEnd('\','/') -eq $ArchiveRoot.TrimEnd('\','/')) { throw 'A whole drive cannot be an archive root.' }
    $ArchivePath = $ArchivePath.TrimEnd('\','/')
    $ArchiveCheck = $ArchivePath
    while ($ArchiveCheck) {
        if (Test-Path -LiteralPath $ArchiveCheck) {
            $ArchiveItem = Get-Item -LiteralPath $ArchiveCheck -Force
            if (($ArchiveItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Archive link/reparse point refused: ' + $ArchiveCheck) }
        }
        $ArchiveParent = [IO.Path]::GetDirectoryName($ArchiveCheck)
        if ($ArchiveParent -eq $ArchiveCheck) { break }
        $ArchiveCheck = $ArchiveParent
    }
    return $ArchivePath
}

function Invoke-ArchiveCli([string]$Command, [string]$LogBase) {
    # Arguments contain only validated paths, with no trailing slash or quote.
    $ArchiveArguments = @($ArchiveScript, $Command, '--source-root', $SourceRoot,
        '--destination-root', $DestinationRoot, '--batch-root', $BatchRoot, '--state-root', $StateRoot)
    $ArchiveStart = New-Object Diagnostics.ProcessStartInfo
    $ArchiveStart.FileName = $PythonPath
    $ArchiveStart.Arguments = ($ArchiveArguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $ArchiveStart.WorkingDirectory = Split-Path $ArchiveScript -Parent
    $ArchiveStart.UseShellExecute = $false
    $ArchiveStart.CreateNoWindow = $true
    $ArchiveStart.RedirectStandardOutput = $true
    $ArchiveStart.RedirectStandardError = $true
    $ArchiveStart.StandardOutputEncoding = $ArchiveUtf8
    $ArchiveStart.StandardErrorEncoding = $ArchiveUtf8
    $ArchiveProcess = New-Object Diagnostics.Process
    $ArchiveProcess.StartInfo = $ArchiveStart
    try {
        if (-not $ArchiveProcess.Start()) { throw 'Archive Python could not start.' }
        $ArchiveOutputTask = $ArchiveProcess.StandardOutput.ReadToEndAsync()
        $ArchiveErrorTask = $ArchiveProcess.StandardError.ReadToEndAsync()
        $ArchiveProcess.WaitForExit()
        $ArchiveOutput = $ArchiveOutputTask.GetAwaiter().GetResult()
        $ArchiveError = $ArchiveErrorTask.GetAwaiter().GetResult()
        [IO.File]::WriteAllText($LogBase + '.json', $ArchiveOutput, $ArchiveUtf8)
        [IO.File]::WriteAllText($LogBase + '.stderr.log', $ArchiveError, $ArchiveUtf8)
        $ArchiveResult = $ArchiveOutput | ConvertFrom-Json
        if ($ArchiveProcess.ExitCode -notin @(0,2)) { throw ('Unexpected archive CLI exit: ' + $ArchiveProcess.ExitCode) }
        return @{ exit_code=$ArchiveProcess.ExitCode; result=$ArchiveResult; json_log=($LogBase + '.json'); stderr_log=($LogBase + '.stderr.log') }
    } finally { $ArchiveProcess.Dispose() }
}

try {
    # Only this process and its children receive the cache environment.
    $env:TEMP = 'D:\codex+\temp'
    $env:TMP = $env:TEMP
    $env:TMPDIR = $env:TEMP
    $SourceRoot = Get-ArchivePath $SourceRoot
    $DestinationRoot = Get-ArchivePath $DestinationRoot
    $BatchRoot = Get-ArchivePath $BatchRoot
    $StateRoot = Get-ArchivePath $StateRoot
    $ArchiveRoots = @($SourceRoot,$DestinationRoot,$BatchRoot,$StateRoot)
    for ($ArchiveLeft=0; $ArchiveLeft -lt $ArchiveRoots.Count; $ArchiveLeft++) {
        for ($ArchiveRight=$ArchiveLeft+1; $ArchiveRight -lt $ArchiveRoots.Count; $ArchiveRight++) {
            $ArchiveA=$ArchiveRoots[$ArchiveLeft]; $ArchiveB=$ArchiveRoots[$ArchiveRight]
            if ($ArchiveA -eq $ArchiveB -or $ArchiveA.StartsWith($ArchiveB+'\',[StringComparison]::OrdinalIgnoreCase) -or $ArchiveB.StartsWith($ArchiveA+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive, source, batch and state roots must be disjoint.' }
        }
    }
    [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
    $StateRoot = Get-ArchivePath $StateRoot
    $ArchiveLockPath = Get-ArchivePath (Join-Path $StateRoot 'weekly-run.lock')
    # FileShare.None denies competing wrappers; a stale filename is never deleted.
    $ArchiveLock = [IO.File]::Open($ArchiveLockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $ArchiveLogRoot = Get-ArchivePath (Join-Path $StateRoot 'logs')
    [IO.Directory]::CreateDirectory($ArchiveLogRoot) | Out-Null
    $ArchiveLogRoot = Get-ArchivePath $ArchiveLogRoot
    $ArchiveRunId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N')
    $ArchiveLogBase = Join-Path $ArchiveLogRoot $ArchiveRunId
    $ArchiveSummaryPath = $ArchiveLogBase + '.runner.json'
    $ArchiveSummary.source_root=$SourceRoot; $ArchiveSummary.destination_root=$DestinationRoot
    $ArchiveSummary.batch_root=$BatchRoot; $ArchiveSummary.state_root=$StateRoot
    $EnvironmentPath = Get-ArchivePath $EnvironmentPath
    if (-not (Test-Path -LiteralPath $EnvironmentPath -PathType Leaf)) { throw 'Candidate Enter-Environment.ps1 is missing.' }
    . $EnvironmentPath
    # Reassert temp after the entrypoint; never modify user/system settings.
    $env:TEMP='D:\codex+\temp'; $env:TMP=$env:TEMP; $env:TMPDIR=$env:TEMP
    if (-not $PythonPath) { $PythonPath=$env:SCB_PRO_PYTHON }
    $PythonPath = Get-ArchivePath $PythonPath
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Explicit configured Python executable is missing.' }
    $ArchiveScript = Get-ArchivePath (Join-Path $PSScriptRoot 'archive_products.py')
    if (-not (Test-Path -LiteralPath $ArchiveScript -PathType Leaf)) { throw 'Receipt-bound archive CLI is missing.' }
    $ArchiveSummary.python=$PythonPath; $ArchiveSummary.environment=$EnvironmentPath
    $env:SCB_PRO_ARCHIVE_STATE_ROOT=$StateRoot
    $ArchivePlan=Invoke-ArchiveCli 'plan' ($ArchiveLogBase + '.plan')
    $ArchiveSummary.plan_exit_code=$ArchivePlan.exit_code
    $ArchiveSummary.plan_log=$ArchivePlan.json_log
    $ArchiveExitCode=$ArchivePlan.exit_code
    if ($ArchivePlan.result.PSObject.Properties.Name -contains 'error') {
        $ArchiveSummary.status='retained'; $ArchiveSummary.reason=$ArchivePlan.result.error
    } elseif ($Mode -eq 'Apply' -and @($ArchivePlan.result.eligible).Count -gt 0) {
        # apply generates a fresh plan and reacquires the archive/batch protections.
        $ArchiveApply=Invoke-ArchiveCli 'apply' ($ArchiveLogBase + '.apply')
        $ArchiveSummary.apply_exit_code=$ArchiveApply.exit_code
        $ArchiveSummary.apply_log=$ArchiveApply.json_log
        $ArchiveExitCode=$ArchiveApply.exit_code
        $ArchiveSummary.status=if ($ArchiveExitCode -eq 0) { 'completed' } else { 'retained' }
    } else {
        $ArchiveSummary.status=if ($ArchiveExitCode -ne 0) { 'retained' } elseif ($Mode -eq 'Plan') { 'planned' } else { 'no_eligible_products' }
    }
} catch {
    $ArchiveSummary.status='retained'; $ArchiveSummary.reason=$_.Exception.Message
    $ArchiveExitCode=2
} finally {
    $ArchiveSummary.exit_code=$ArchiveExitCode
    $ArchiveSummary.completed_utc=[DateTime]::UtcNow.ToString('o')
    if ($ArchiveSummaryPath) { [IO.File]::WriteAllText($ArchiveSummaryPath,($ArchiveSummary | ConvertTo-Json -Depth 6),$ArchiveUtf8) }
    if ($ArchiveLock) { $ArchiveLock.Dispose() }
}
$ArchiveSummary | ConvertTo-Json -Depth 6
exit $ArchiveExitCode

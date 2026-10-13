[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [Parameter(Mandatory=$true)][string]$BatchRoot,
    [Parameter(Mandatory=$true)][string]$StateRoot,
    [string]$SourceRoot = 'D:\研发图表',
    [string]$DestinationRoot = 'F:\研发图表',
    [string]$TaskName = 'SoftwareCase-WeeklyArchive',
    [string]$EnvironmentPath,
    [string]$PythonPath,
    [string]$PowerShellPath
)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Use the existing PowerShell 7 launcher; execution policies are not changed.' }
if (-not $EnvironmentPath) { $EnvironmentPath=Join-Path (Split-Path $PSScriptRoot -Parent) 'Enter-Environment.ps1' }
$env:TEMP='D:\codex+\temp'; $env:TMP=$env:TEMP; $env:TMPDIR=$env:TEMP

function Get-ArchivePlanPath([string]$Value) {
    if (-not [IO.Path]::IsPathRooted($Value) -or $Value -match '["\r\n\x00]') { throw 'Explicit absolute paths without command-line control characters are required.' }
    $ArchiveValue=[IO.Path]::GetFullPath($Value).TrimEnd('\','/')
    if ($ArchiveValue -eq [IO.Path]::GetPathRoot($ArchiveValue).TrimEnd('\','/')) { throw 'A whole drive cannot be an archive root.' }
    $ArchiveCheck=$ArchiveValue
    while ($ArchiveCheck) {
        if (Test-Path -LiteralPath $ArchiveCheck) {
            if (((Get-Item -LiteralPath $ArchiveCheck -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Archive link/reparse point refused: '+$ArchiveCheck) }
        }
        $ArchiveCheck=[IO.Path]::GetDirectoryName($ArchiveCheck)
    }
    return $ArchiveValue
}
$SourceRoot=Get-ArchivePlanPath $SourceRoot; $DestinationRoot=Get-ArchivePlanPath $DestinationRoot
$BatchRoot=Get-ArchivePlanPath $BatchRoot; $StateRoot=Get-ArchivePlanPath $StateRoot
$EnvironmentPath=Get-ArchivePlanPath $EnvironmentPath
if (-not (Test-Path -LiteralPath $EnvironmentPath -PathType Leaf)) { throw 'Deployment environment entrypoint is missing.' }
. $EnvironmentPath
$env:TEMP='D:\codex+\temp'; $env:TMP=$env:TEMP; $env:TMPDIR=$env:TEMP
if (-not $PythonPath) { $PythonPath=$env:SCB_PRO_PYTHON }
$PythonPath=Get-ArchivePlanPath $PythonPath
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Configured Python is missing.' }
$ArchiveWrapper=Get-ArchivePlanPath (Join-Path $PSScriptRoot 'Run-WeeklyArchive.ps1')
if (-not (Test-Path -LiteralPath $ArchiveWrapper -PathType Leaf)) { throw 'Weekly archive wrapper is missing.' }
if ($TaskName -match '[\\/\r\n\x00]' -or -not $TaskName.Trim()) { throw 'A plain nonempty Task Scheduler name is required.' }
$ArchiveRoots=@($SourceRoot,$DestinationRoot,$BatchRoot,$StateRoot)
for ($ArchiveLeft=0; $ArchiveLeft -lt $ArchiveRoots.Count; $ArchiveLeft++) {
    for ($ArchiveRight=$ArchiveLeft+1; $ArchiveRight -lt $ArchiveRoots.Count; $ArchiveRight++) {
        $ArchiveA=$ArchiveRoots[$ArchiveLeft]; $ArchiveB=$ArchiveRoots[$ArchiveRight]
        if ($ArchiveA -eq $ArchiveB -or $ArchiveA.StartsWith($ArchiveB+'\',[StringComparison]::OrdinalIgnoreCase) -or $ArchiveB.StartsWith($ArchiveA+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive, source, batch and state roots must be disjoint.' }
    }
}
$ArchiveUser=[Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not $PowerShellPath) { $PowerShellPath=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName }
if (-not [IO.Path]::IsPathRooted($PowerShellPath) -or $PowerShellPath -match '["\r\n\x00]') { throw 'An explicit PowerShell 7 executable path is required.' }
$ArchivePowerShell=[IO.Path]::GetFullPath($PowerShellPath)
if (-not (Test-Path -LiteralPath $ArchivePowerShell -PathType Leaf) -or [IO.Path]::GetFileName($ArchivePowerShell) -ne 'pwsh.exe') { throw 'Use the existing pwsh.exe launcher; no policy bypass or shell fallback is allowed.' }
$ArchiveShellVersion=& $ArchivePowerShell -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.Major'
if ($LASTEXITCODE -ne 0 -or [string]$ArchiveShellVersion -notmatch '^\s*[7-9][0-9]*\s*$') { throw 'The selected launcher must be PowerShell 7 or newer.' }
$ArchiveArguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$ArchiveWrapper+'" -Mode Apply -SourceRoot "'+$SourceRoot+'" -DestinationRoot "'+$DestinationRoot+'" -BatchRoot "'+$BatchRoot+'" -StateRoot "'+$StateRoot+'" -EnvironmentPath "'+$EnvironmentPath+'" -PythonPath "'+$PythonPath+'"'
$ArchivePlan=[ordered]@{ schema_version=1; task_name=$TaskName; task_path='\'; user=$ArchiveUser;
    logon_type='InteractiveToken'; run_level='Limited'; hidden=$true; day='Sunday'; local_time='22:00';
    start_when_available=$true; multiple_instances='IgnoreNew'; execution=$ArchivePowerShell;
    arguments=$ArchiveArguments; working_directory=(Split-Path $ArchiveWrapper -Parent);
    source_root=$SourceRoot; destination_root=$DestinationRoot; batch_root=$BatchRoot; state_root=$StateRoot;
    registered=$false; note='Preparation only; review and explicitly invoke the generated script with -Register.' }
$ArchivePlanPath=Join-Path $StateRoot 'weekly-task-plan.json'
$ArchiveRegisterPath=Join-Path $StateRoot 'Register-WeeklyArchive.ps1'

$ArchiveRegisterScript=@'
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$Register)
$ErrorActionPreference='Stop'
$ArchivePlan=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'weekly-task-plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Register) { $ArchivePlan | ConvertTo-Json -Depth 6; return }
$ArchiveIdentity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($ArchiveIdentity -ne $ArchivePlan.user) { throw 'The registration identity differs from the reviewed current user.' }
if ($ArchivePlan.logon_type -ne 'InteractiveToken' -or $ArchivePlan.run_level -ne 'Limited' -or $ArchivePlan.day -ne 'Sunday' -or $ArchivePlan.local_time -ne '22:00' -or -not $ArchivePlan.hidden) { throw 'The reviewed archive task policy differs.' }
$ArchiveExisting=Get-ScheduledTask -TaskPath $ArchivePlan.task_path -TaskName $ArchivePlan.task_name -ErrorAction SilentlyContinue
if ($ArchiveExisting) {
    $ArchiveActions=@($ArchiveExisting.Actions)
    $ArchiveTriggers=@($ArchiveExisting.Triggers)
    if ($ArchiveActions.Count -ne 1 -or $ArchiveActions[0].Execute -ne $ArchivePlan.execution -or $ArchiveActions[0].Arguments -ne $ArchivePlan.arguments -or $ArchiveActions[0].WorkingDirectory -ne $ArchivePlan.working_directory -or $ArchiveExisting.Principal.UserId -ne $ArchivePlan.user -or $ArchiveExisting.Principal.LogonType -ne 'Interactive' -or $ArchiveExisting.Principal.RunLevel -ne 'Limited' -or -not $ArchiveExisting.Settings.Hidden -or $ArchiveExisting.Settings.MultipleInstances -ne 'IgnoreNew' -or -not $ArchiveExisting.Settings.StartWhenAvailable -or $ArchiveTriggers.Count -ne 1 -or $ArchiveTriggers[0].DaysOfWeek -ne 1 -or $ArchiveTriggers[0].WeeksInterval -ne 1 -or ([datetime]$ArchiveTriggers[0].StartBoundary).TimeOfDay -ne ([timespan]::FromHours(22))) { throw 'An existing same-name task has different paths, user or policy; it will not be overwritten.' }
    [pscustomobject]@{ status='already_present'; task_name=$ArchivePlan.task_name; changed=$false } | ConvertTo-Json
    return
}
if (-not (Test-Path -LiteralPath $ArchivePlan.execution -PathType Leaf)) { throw 'The reviewed PowerShell executable is missing.' }
if ($PSCmdlet.ShouldProcess($ArchivePlan.task_name,'Register the reviewed weekly archive task')) {
    $ArchiveAction=New-ScheduledTaskAction -Execute $ArchivePlan.execution -Argument $ArchivePlan.arguments -WorkingDirectory $ArchivePlan.working_directory
    $ArchiveTrigger=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Sunday -At ([datetime]::Today.AddHours(22))
    $ArchivePrincipal=New-ScheduledTaskPrincipal -UserId $ArchivePlan.user -LogonType Interactive -RunLevel Limited
    $ArchiveSettings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -Hidden -ExecutionTimeLimit ([timespan]::FromHours(2))
    Register-ScheduledTask -TaskName $ArchivePlan.task_name -TaskPath $ArchivePlan.task_path -Action $ArchiveAction -Trigger $ArchiveTrigger -Principal $ArchivePrincipal -Settings $ArchiveSettings -Description 'Receipt-verified completed products: daily D to weekly F archive; current user, no stored credentials.' -ErrorAction Stop | Out-Null
    [pscustomobject]@{ status='registered'; task_name=$ArchivePlan.task_name } | ConvertTo-Json
}
'@
if ($PSCmdlet.ShouldProcess($StateRoot,'Write reviewable archive task plan and explicit registration script; no task registration')) {
    [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
    $StateRoot=Get-ArchivePlanPath $StateRoot
    Get-ArchivePlanPath $ArchivePlanPath | Out-Null
    Get-ArchivePlanPath $ArchiveRegisterPath | Out-Null
    # No overwrite: preserve earlier reviewed plans and user scripts.
    $ArchiveUtf8=New-Object Text.UTF8Encoding($false)
    foreach ($ArchiveTarget in @($ArchivePlanPath,$ArchiveRegisterPath)) { if (Test-Path -LiteralPath $ArchiveTarget) { throw ('Review artifact already exists; preserve it: '+$ArchiveTarget) } }
    $ArchivePlanStream=New-Object IO.FileStream($ArchivePlanPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $ArchiveBytes=$ArchiveUtf8.GetBytes(($ArchivePlan | ConvertTo-Json -Depth 6)); $ArchivePlanStream.Write($ArchiveBytes,0,$ArchiveBytes.Length); $ArchivePlanStream.Flush($true) } finally { $ArchivePlanStream.Dispose() }
    $ArchiveScriptStream=New-Object IO.FileStream($ArchiveRegisterPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $ArchiveBytes=$ArchiveUtf8.GetBytes($ArchiveRegisterScript); $ArchiveScriptStream.Write($ArchiveBytes,0,$ArchiveBytes.Length); $ArchiveScriptStream.Flush($true) } finally { $ArchiveScriptStream.Dispose() }
}
[pscustomobject]@{ status='prepared_only'; task_registered=$false; plan=$ArchivePlanPath; registration_script=$ArchiveRegisterPath; trigger='Sunday 22:00 local'; user=$ArchiveUser } | ConvertTo-Json

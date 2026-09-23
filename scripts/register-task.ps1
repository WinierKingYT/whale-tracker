<#
.SYNOPSIS
    Registers a Windows Scheduled Task that runs the whale-tracker Observer
    every N minutes. NOT run automatically -- Ahmet runs this manually after
    reviewing it, per Brain-Eleven's "don't silently create standing
    background automation" practice.

.DESCRIPTION
    Creates a task that runs, from this project's own directory:
        uv run python -m whale_tracker.observe --min-usd 1000000 --log-file data\observer.log
    Output goes to data\observer.log (timestamped, appended) since a
    scheduled task's stdout is otherwise discarded.

.PARAMETER IntervalMinutes
    How often to run. Default 15 -- frequent enough to catch real activity,
    infrequent enough not to hammer the free public RPC/APIs this project
    relies on (see docs/DATA-SOURCES.md and docs/TECHNICAL-APPROACH.md for
    why these are rate-sensitive).

.EXAMPLE
    .\scripts\register-task.ps1
    .\scripts\register-task.ps1 -IntervalMinutes 30

.NOTES
    To remove the task later:
        Unregister-ScheduledTask -TaskName "whale-tracker-observer" -Confirm:$false
    To see its recent run history:
        Get-ScheduledTaskInfo -TaskName "whale-tracker-observer"
#>

param(
    [int]$IntervalMinutes = 15
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$UvPath = (Get-Command uv -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $UvPath `
    -Argument "run python -m whale_tracker.observe --min-usd 1000000 --log-file data\observer.log" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -DontStopOnIdleEnd `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "whale-tracker-observer" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "whale-tracker Gozlemci -- her $IntervalMinutes dakikada bir veri toplar, islem yapmaz." `
    -Force

Write-Host "Task registered: whale-tracker-observer (every $IntervalMinutes min)"
Write-Host "Log file: $ProjectRoot\data\observer.log"
Write-Host "To remove: Unregister-ScheduledTask -TaskName 'whale-tracker-observer' -Confirm:`$false"

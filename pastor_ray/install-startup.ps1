$ErrorActionPreference = 'Stop'
$rayRoot = Split-Path -Parent $PSScriptRoot
$rayPython = (& python -c "import sys; print(sys.executable)").Trim()
$rayPythonw = Join-Path (Split-Path -Parent $rayPython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $rayPythonw)) { throw 'pythonw.exe is required for hidden startup.' }
$rayAction = New-ScheduledTaskAction -Execute $rayPythonw -Argument '-m pastor_ray.supervisor' -WorkingDirectory $rayRoot
$rayTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$raySettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
try {
    Register-ScheduledTask -TaskName 'Pastor Ray' -Action $rayAction -Trigger $rayTrigger -Settings $raySettings -Description 'Start local Pastor Ray and recover from process crashes.' -Force | Out-Null
    Write-Output 'Installed Pastor Ray login scheduled task.'
} catch {
    # Per-user startup needs no administrator credentials.
    $rayStartup = [Environment]::GetFolderPath('Startup')
    $rayShell = New-Object -ComObject WScript.Shell
    $rayLink = $rayShell.CreateShortcut((Join-Path $rayStartup 'Pastor Ray.lnk'))
    $rayLink.TargetPath = $rayPythonw
    $rayLink.Arguments = '-m pastor_ray.supervisor'
    $rayLink.WorkingDirectory = $rayRoot
    $rayLink.WindowStyle = 7
    $rayLink.Save()
    Write-Output 'Installed per-user Windows login startup shortcut (Task Scheduler registration unavailable).'
}

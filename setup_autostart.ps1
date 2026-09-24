# Makes the house hunter start silently every time you log in to Windows,
# and starts it right now. Run once:  powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
# To remove it later:  Unregister-ScheduledTask -TaskName "Bristol House Hunter" -Confirm:$false

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw -ErrorAction Stop).Source

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$here\house_hunter.py`" --loop" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "Bristol House Hunter" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Emails new Bristol student house listings" -Force | Out-Null
Start-ScheduledTask -TaskName "Bristol House Hunter"
Write-Host "Done. The house hunter is running and will start again whenever you log in."
Write-Host "Activity is logged to $here\hunter.log"

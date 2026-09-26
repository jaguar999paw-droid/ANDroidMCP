# ANDroidMCP — Windows installer for the standalone release build.
# Installs the 4 prebuilt .exe binaries + bundled adb/fastboot, and
# registers them as logon-triggered Scheduled Tasks that restart on
# failure. (Scheduled Tasks, not a true Windows Service — see README
# for the NSSM upgrade path if you need SCM-managed services.)
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\ANDroidMCP"
)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing ANDroidMCP to $InstallDir"
New-Item -ItemType Directory -Force -Path "$InstallDir\bin","$InstallDir\platform-tools","$InstallDir\logs","$InstallDir\staging" | Out-Null

Copy-Item "$ScriptDir\bin\*" "$InstallDir\bin\" -Force
if (Test-Path "$ScriptDir\platform-tools") {
    Copy-Item "$ScriptDir\platform-tools\*" "$InstallDir\platform-tools\" -Force -Recurse
}

$env:Path = "$InstallDir\platform-tools;$env:Path"

function Register-AndroidMcpTask {
    param([string]$Name, [string]$Exe, [int]$Port, [hashtable]$ExtraEnv = @{})

    $taskName = "ANDroidMCP-$Name"
    $exePath = Join-Path $InstallDir "bin\$Exe.exe"

    $envSets = ($ExtraEnv.GetEnumerator() | ForEach-Object { "set `"$($_.Key)=$($_.Value)`" &&" }) -join " "
    $argument = "/c `"$envSets set `"MCP_PORT=$Port`" && set `"PATH=$InstallDir\platform-tools;%PATH%`" && `"$exePath`" >> `"$InstallDir\logs\$Name.log`" 2>&1`""

    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $argument -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Host "  [$Name] registered + started as task '$taskName' -> http://127.0.0.1:$Port/mcp"
}

Register-AndroidMcpTask -Name "userspace"    -Exe "android-userspace"    -Port 8110 -ExtraEnv @{ ADB_SERVER_HOST = "127.0.0.1"; ADB_SERVER_PORT = "5037"; ORCHESTRATOR_MCP_URL = "http://127.0.0.1:8112/mcp" }
Register-AndroidMcpTask -Name "bootloader"   -Exe "android-bootloader"   -Port 8111 -ExtraEnv @{ ORCHESTRATOR_MCP_URL = "http://127.0.0.1:8112/mcp"; ANDROIDMCP_STAGING_ROOT = "$InstallDir\staging" }
Register-AndroidMcpTask -Name "orchestrator" -Exe "android-orchestrator" -Port 8112
Register-AndroidMcpTask -Name "network"      -Exe "android-network"      -Port 8113

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Task status:"
Get-ScheduledTask -TaskName "ANDroidMCP-*" | Get-ScheduledTaskInfo | Select-Object TaskName, LastTaskResult

$tsIp = "<this-host-tailscale-ip>"
try {
    $tsOut = & tailscale ip -4 2>$null
    if ($tsOut) { $tsIp = $tsOut.Trim() }
} catch {}

Write-Host ""
Write-Host "MCP endpoints (reachable over your tailnet):"
Write-Host "  http://$($tsIp):8110/mcp  (userspace)"
Write-Host "  http://$($tsIp):8111/mcp  (bootloader)"
Write-Host "  http://$($tsIp):8112/mcp  (orchestrator)"
Write-Host "  http://$($tsIp):8113/mcp  (network)"

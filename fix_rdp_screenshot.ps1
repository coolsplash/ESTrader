# fix_rdp_screenshot.ps1
# Fixes screenshot capture issues when RDP session is minimized or disconnected
# Run this script as Administrator on your LOCAL machine (the one running RDP client)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "RDP Screenshot Fix Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script adds a registry key to prevent Windows from" -ForegroundColor White
Write-Host "suppressing GUI rendering when RDP window is minimized." -ForegroundColor White
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Registry path and values
$regPath = "HKLM:\Software\Microsoft\Terminal Server Client"
$valueName = "RemoteDesktop_SuppressWhenMinimized"
$valueData = 2  # 2 = Never suppress GUI rendering

Write-Host "Registry Path: $regPath" -ForegroundColor Gray
Write-Host "Value Name: $valueName" -ForegroundColor Gray
Write-Host "Value Data: $valueData" -ForegroundColor Gray
Write-Host ""

# Check if key already exists
if (Test-Path $regPath) {
    $currentValue = Get-ItemProperty -Path $regPath -Name $valueName -ErrorAction SilentlyContinue
    if ($currentValue) {
        Write-Host "Current value: $($currentValue.$valueName)" -ForegroundColor Yellow
        if ($currentValue.$valueName -eq $valueData) {
            Write-Host "Registry key already set correctly!" -ForegroundColor Green
            Write-Host ""
            Read-Host "Press Enter to exit"
            exit 0
        }
    }
} else {
    Write-Host "Creating registry path..." -ForegroundColor Yellow
    New-Item -Path $regPath -Force | Out-Null
}

# Set the registry value
try {
    Set-ItemProperty -Path $regPath -Name $valueName -Value $valueData -Type DWord
    Write-Host ""
    Write-Host "SUCCESS: Registry key has been set!" -ForegroundColor Green
    Write-Host ""
    Write-Host "IMPORTANT:" -ForegroundColor Yellow
    Write-Host "  - You may need to restart your RDP session for changes to take effect" -ForegroundColor White
    Write-Host "  - This fix is applied to your LOCAL machine (RDP client)" -ForegroundColor White
    Write-Host "  - Screenshots should now work even when RDP window is minimized" -ForegroundColor White
} catch {
    Write-Host "ERROR: Failed to set registry key: $_" -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to exit"


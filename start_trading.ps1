# Start ES Trading System
# Activates venv and starts the main screenshot uploader trading bot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "ES Futures Trading System" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Change to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Check if market data context exists for today
$today = Get-Date -Format "yyMMdd"
$contextFile = "context\$today.txt"

if (-not (Test-Path $contextFile)) {
    Write-Host ""
    Write-Host "No market context found for today." -ForegroundColor Yellow
    Write-Host "Attempting to fetch market data from Yahoo Finance..." -ForegroundColor Yellow
    Write-Host ""
}

# Start the trading system
Write-Host "Starting ES Trading System..." -ForegroundColor Green
Write-Host ""

python screenshot_uploader.py


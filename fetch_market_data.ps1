# Fetch Market Data Script
# Run this before market open to fetch and store ES and VIX data

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "ES Futures Market Data Fetcher" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Change to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Run market data fetcher
Write-Host "Fetching market data from Yahoo Finance..." -ForegroundColor Yellow
Write-Host ""

python market_data.py

Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")


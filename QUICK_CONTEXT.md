# ESTrader - Quick Context for AI Assistant

## What This Is
Automated ES futures trading system using GPT-4o vision to analyze Bookmap screenshots and execute trades via TopstepX API.

## Core Files
- **screenshot_uploader.py** (5553 lines) - Main trading bot with system tray, scheduler, API integration, Supabase logging
- **market_data.py** (433 lines) - Fetches Yahoo Finance data, calculates VWAP/volume profile
- **config.ini** (297 lines) - All settings, prompts, credentials, interval scheduling
- **start_trading.ps1** - Launcher script
- **backfill_supabase.py** - Import historical CSV data to Supabase database

## How It Works
1. Dynamic interval: Capture Bookmap screenshot based on time-based schedule (e.g., 30s during RTH, 5min pre-market)
2. Fetch TopstepX 5m bar data: Cache OHLCV bars for price action context
3. Every 30 minutes: Refresh base market context from Yahoo Finance (VWAP, volume profile, VIX)
4. Query TopstepX API for current position status
5. Send screenshot + market context + bar data to GPT-4o with appropriate prompt:
   - **No position**: Look for sweep/reclaim/retest setups (buy/sell/hold)
   - **Has position**: Manage it (hold/adjust/scale/close)
6. Parse JSON response and execute trades
7. Log everything to daily logs, monthly CSV trade journal, **and Supabase database**
8. Send Telegram notifications

## Market Context Provided to LLM
- ES price, daily range, 5-day trend
- VWAP (5-day) and intraday (5m)
- VIX volatility level
- Volume Profile top 5 levels (daily + intraday)
- TopstepX 5m OHLCV bars (36 bars = 3 hours)
- Key support/resistance levels
- Context updates dynamically based on LLM observations (stored separately as _LLM.txt)

## Trading Parameters
- **Account**: TopstepX #14789500
- **Contract**: ES Dec 2025 (CON.F.US.EP.Z25)
- **Size**: 3 contracts
- **Max Risk**: 8 points per contract
- **Max Target**: 30 points per contract
- **Stop Loss Orders**: Disabled (LLM-managed)
- **Take Profit Orders**: Disabled (LLM-managed)
- **LLM Model**: gpt-5.1-chat-latest
- **Strategy**: Sweep → Reclaim → Retest → Reversal setups, trend continuation, aim for 20-30+ points

## Key Configuration Flags
- `enable_llm` - Use AI analysis (true/false)
- `enable_trading` - Enable API calls (true/false)
- `execute_trades` - Actually execute trades (true/false)
- `interval_seconds` - Default screenshot frequency in seconds
- `interval_schedule` - Time-based intervals (e.g., "09:30-16:00=30,18:00-23:59=300")
- `begin_time`/`end_time` - Trading hours window
- `no_new_trades_windows` - Time ranges when no new trades allowed (e.g., "09:15-09:35,15:45-18:02")
- `force_close_time` - Force close all positions at this time
- `window_process_name` - Filter windows by process name (e.g., Bookmap.exe)
- `enable_supabase_logging` - Log to PostgreSQL database (true/false)
- `enable_bar_data` - Fetch TopstepX bar data for context (true/false)

## Data Storage
- `logs/YYYYMMDD.txt` - Daily execution logs
- `logs/YYMMDD_LLM.csv` - LLM interaction logs (prompts, responses, decisions)
- `trades/YYYY_MM.csv` - Monthly trade journal with P&L
- `trades/active_trade.json` - Current position tracking
- `context/YYMMDD.txt` - Original market data context (never overwritten)
- `context/YYMMDD_LLM.txt` - LLM's updated context (evolves throughout day)
- `market_data/` - Cached Yahoo Finance raw data (CSV files: daily, 5m intraday, VIX)
- `cache/bars/` - TopstepX 5m OHLCV bar data (JSON files)
- `screenshots/` - Captured images (timestamped)
- `supabase/` - Database migrations and schema
- **Supabase Database** (when enabled):
  - `accounts` - Trading account registry
  - `trades` - All trade events with full P&L tracking
  - `llm_interactions` - Complete LLM request/response history
  - `market_context` - Daily market analysis snapshots
  - `account_snapshots` - Balance history for equity curve
  - Analytics views: `daily_trade_stats`, `win_rate_analysis`, `monthly_performance`, `recent_trades`

## API Integrations
- **OpenAI**: GPT-4o vision (currently gpt-5.1-chat-latest) for screenshot analysis
- **TopstepX**: Trade execution, position queries, order management, 5m bar data
- **Yahoo Finance**: ES/VIX historical and intraday data (via yfinance)
- **Telegram**: Trade notifications
- **Supabase**: PostgreSQL database for centralized logging and analytics

## Common Tasks

### Start Trading System
```powershell
.\start_trading.ps1
```

### Fetch Market Data Manually
```powershell
.\fetch_market_data.ps1
```

### Run Market Data Module Standalone
```powershell
python market_data.py
```

### System Tray Menu Options
Right-click the tray icon for quick access to:
- **Start/Stop** - Control the scheduler
- **Reload Config** - Hot-reload config.ini without restarting
- **Refresh Market Context** - Fetch latest market data on demand
- **Set Position** - Manually override position tracking
- **Toggle LLM/Trading** - Enable/disable features
- **Take Screenshot Now** - Manual screenshot analysis
- **Test Positions/Orders** - Debug API connectivity
- **List All Contracts** - View available contracts

### Check Logs
- Latest execution: `logs\YYYYMMDD.txt` (today's date)
- Trade history: `trades\trades_YYYYMM.csv` (current month)

## Tech Stack
- Python 3.13, Windows 10
- Key packages: pillow, requests, schedule, pywin32, pystray, yfinance, pandas, numpy, **supabase, signalrcore**
- Virtual environment: `venv/`

## Recent Changes
- **Supabase integration**: Dual logging to PostgreSQL database with analytics views
- **TopstepX bar data**: 5m OHLCV bars fetched and cached for LLM context
- **Dynamic interval scheduling**: Time-based screenshot intervals (configurable per time period)
- **Updated prompts**: Focus on sweep/reclaim/retest/reversal setups with strict position management
- **LLM model upgrade**: Now using gpt-5.1-chat-latest
- **Enhanced intraday data**: 5-minute intervals (previously 15m)
- **Dual context storage**: Base context + LLM-updated context stored separately
- **Window process filtering**: Ensure correct Bookmap window is captured
- **Testing infrastructure**: SignalR testing, LLM prompt testing, comprehensive test utilities
- **Account update**: Now trading on account #14789500 with 3 contracts
- **Backfill utility**: Import historical CSV data to Supabase

## Important Notes
- System runs as Windows system tray application
- All credentials are in config.ini (already configured)
- Position management happens every 20 seconds when in a trade
- Screenshots taken based on dynamic interval schedule (not fixed 1-minute)
- API queries only run during trading hours (saves API calls)
- Trade IDs track positions across entry/adjustments/exit
- Can run in mock mode with safety flags disabled for testing
- After-hours trading automatically detected (RTH: 9:30 AM - 4:00 PM ET)
- Hot-reload config without restarting via tray menu
- Overnight trading sessions supported (e.g., 00:00-23:59)
- Stop/take profit orders disabled by default (LLM manages dynamically)
- **Supabase logging runs in parallel** - CSV files remain primary, database is supplementary
- Bar data cached daily to minimize API calls
- LLM interactions logged separately for analysis (`logs/*_LLM.csv`)
- Window process filtering prevents accidental wrong-window captures
- Testing directory contains SignalR and LLM testing utilities


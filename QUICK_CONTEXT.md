# ESTrader - Quick Context for AI Assistant

## What This Is
Automated ES futures trading system using GPT-4o vision to analyze Bookmap screenshots and execute trades via TopstepX API.

## Core Files
- **screenshot_uploader.py** (2544 lines) - Main trading bot with system tray, scheduler, API integration
- **market_data.py** (422 lines) - Fetches Yahoo Finance data, calculates VWAP/volume profile
- **config.ini** (136 lines) - All settings, prompts, credentials
- **start_trading.ps1** - Launcher script

## How It Works
1. Every minute: Capture Bookmap screenshot from thinkorswim window
2. Query TopstepX API for current position status
3. Send screenshot + market context to GPT-4o with appropriate prompt:
   - **No position**: Look for buy/sell/hold opportunities
   - **Has position**: Manage it (hold/adjust/scale/close)
4. Parse JSON response and execute trades
5. Log everything to daily logs and monthly CSV trade journal
6. Send Telegram notifications

## Market Context Provided to LLM
- ES price, daily range, 5-day trend
- VWAP (5-day) and intraday (15m) 
- VIX volatility level
- Volume Profile top 5 levels (daily + intraday)
- Key support/resistance levels
- Context updates dynamically based on LLM observations

## Trading Parameters
- **Account**: TopstepX #14664776
- **Contract**: ES Dec 2025 (CON.F.US.EP.Z25)
- **Size**: 2 contracts
- **Max Risk**: 8 points per contract
- **Max Target**: 30 points per contract
- **Strategy**: Swing trades, hold up to several hours, aim for 20+ points

## Key Configuration Flags
- `enable_llm` - Use AI analysis (true/false)
- `enable_trading` - Enable API calls (true/false)
- `execute_trades` - Actually execute trades (true/false)
- `interval_minutes` - Screenshot frequency (default: 1)
- `begin_time`/`end_time` - Trading hours window

## Data Storage
- `logs/YYYYMMDD.txt` - Daily execution logs
- `trades/trades_YYYYMM.csv` - Monthly trade journal with P&L
- `trades/active_trade.json` - Current position tracking
- `market_data/` - Cached Yahoo Finance data and context
- `screenshots/` - Captured images (timestamped)

## API Integrations
- **OpenAI**: GPT-4o vision for screenshot analysis
- **TopstepX**: Trade execution, position queries, order management
- **Yahoo Finance**: ES/VIX historical and intraday data (via yfinance)
- **Telegram**: Trade notifications

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

### Check Logs
- Latest execution: `logs\YYYYMMDD.txt` (today's date)
- Trade history: `trades\trades_YYYYMM.csv` (current month)

## Tech Stack
- Python 3.13, Windows 10
- Key packages: pillow, requests, schedule, pywin32, pystray, yfinance, pandas, numpy
- Virtual environment: `venv/`

## Recent Changes (Uncommitted)
- Added market data integration (market_data.py)
- Enhanced LLM prompts with market context
- Added intraday 15-minute volume profile analysis
- Updated config.ini with MarketData section
- Added PowerShell helper scripts

## Important Notes
- System runs as Windows system tray application
- All credentials are in config.ini (already configured)
- Position management happens every 15 seconds when in a trade
- Screenshots only taken during configured trading hours
- Trade IDs track positions across entry/adjustments/exit
- Can run in mock mode with safety flags disabled for testing


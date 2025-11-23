# ESTrader - AI-Powered ES Futures Trading System

## Project Overview
ESTrader is an automated trading system for E-mini S&P 500 (ES) futures that uses AI vision analysis of Bookmap screenshots combined with market data to make trading decisions. The system runs on Windows, captures screenshots from thinkorswim/Bookmap, analyzes order flow using GPT-4o vision, and executes trades via the TopstepX API.

## System Architecture

### Core Components

1. **screenshot_uploader.py** (2544 lines)
   - Main trading bot that orchestrates the entire system
   - Runs as a Windows system tray application with scheduler
   - Captures screenshots of Bookmap chart at configurable intervals
   - Sends screenshots to GPT-4o for analysis
   - Manages positions and executes trades via TopstepX API
   - Handles both entry signals and position management (adjust/scale/close)
   - Logs all trades to monthly CSV files with full details
   - Sends Telegram notifications for all trade events

2. **market_data.py** (422 lines)
   - Fetches ES futures and VIX data from Yahoo Finance
   - Calculates daily and intraday (15-minute) VWAP
   - Generates Volume Profile analysis (top 5 price levels)
   - Creates formatted market context for LLM prompts
   - Caches data to minimize API calls
   - Can be run standalone or integrated into main system

3. **config.ini** (136 lines)
   - Centralized configuration for all system components
   - Contains LLM prompts for different market scenarios
   - TopstepX API credentials and settings
   - Trading parameters (risk limits, contract size, etc.)
   - Market data settings (tickers, intervals, analysis parameters)

### PowerShell Scripts

- **start_trading.ps1** - Main launcher that activates venv and starts the trading system
- **fetch_market_data.ps1** - Standalone script to pre-fetch market data before trading hours

## Key Features

### 1. AI-Powered Trading Decisions
- Uses GPT-4o vision model to analyze Bookmap screenshots
- Analyzes: liquidity zones, order book imbalance, volume delta, momentum shifts, market structure
- Two prompt modes:
  - **No Position Mode**: Looks for high-probability entry opportunities (buy/sell/hold)
  - **Position Management Mode**: Manages open positions (hold/adjust/scale/close)
- Returns structured JSON with action, prices, confidence, and reasoning

### 2. Market Context Integration
- Automatically fetches daily market data before trading
- Provides LLM with comprehensive context including:
  - Current ES price, daily range, 5-day trend
  - VWAP (5-day) and current price relationship
  - VIX volatility level and change
  - Volume Profile top 5 levels (Point of Control)
  - Intraday 15-minute volume profile and VWAP
  - Key support/resistance levels
- Context updates dynamically throughout the day based on LLM observations

### 3. Robust Position Management
- Tracks active positions with unique trade IDs
- Monitors unrealized P&L in real-time
- Queries working orders (stop loss, take profit)
- Can modify bracket orders on the fly
- Supports partial closes (scaling)
- Logs all trade events with entry/exit prices and P&L

### 4. TopstepX API Integration
- Full integration with TopstepX funded trading accounts
- Authentication via API key
- Place market orders with OCO brackets (stop loss + take profit)
- Query positions and working orders
- Modify existing orders
- Cancel orders
- Flatten all positions
- Error handling with user notifications for critical issues

### 5. Risk Management
- Configurable max risk per contract (points/ticks)
- Configurable max profit target per contract
- Optional stop loss and take profit orders
- Confidence threshold for trades
- Trading hours restrictions (begin_time/end_time)
- Position size limits

### 6. Comprehensive Logging & Notifications
- Daily log files with full execution details
- Monthly CSV trade journals with:
  - Timestamp, Event Type (ENTRY/ADJUSTMENT/SCALE/CLOSE)
  - Symbol, Position Type, Size, Price
  - Stop Loss, Take Profit, Reasoning, Confidence
  - P&L (dollars and points), Account Balance
  - Market Context at time of trade
  - Trade ID for tracking
- Telegram notifications for all trade events
- Detailed error logging with stack traces

### 7. User Interface
- Windows system tray icon with menu
- Functions accessible via right-click:
  - Start/Stop scheduler
  - Take manual screenshot
  - Set position type
  - Toggle LLM/Trading
  - Test API connections
  - View contract info
  - Exit application

## Configuration Highlights

### General Settings
- `interval_minutes`: How often to take screenshots (default: 1)
- `trade_status_check_interval`: How often to check positions (default: 15s)
- `begin_time`/`end_time`: Trading hours window
- `window_title`: thinkorswim window to capture
- `enable_llm`: Enable/disable AI analysis
- `enable_trading`: Enable/disable actual trade execution
- `execute_trades`: Additional safety flag for live trading

### LLM Configuration
- `symbol`: Contract ID (e.g., CON.F.US.EP.Z25)
- `display_symbol`: Human-readable symbol (e.g., ES)
- `no_position_prompt`: Prompt for finding new entries
- `position_prompt`: Prompt for managing existing positions
- `model`: AI model to use (default: gpt-4o)

### TopstepX Settings
- Account credentials and endpoints
- Contract details (ES December 2025)
- Position sizing (default: 2 contracts)
- Risk parameters (8 points max risk, 30 points max profit)
- Tick size (0.25 for ES)

### Market Data Settings
- ES and VIX tickers
- Historical data lookback (30 days)
- Volume profile parameters (5 nodes from 5 days)
- Intraday analysis enabled with 15m intervals
- Auto-fetch on startup if context missing
- Caching to avoid repeated API calls

## Typical Workflow

### Morning (Before Market Open)
1. System starts via `start_trading.ps1`
2. Checks for today's market context in `market_data/context_YYYYMMDD.txt`
3. If missing, automatically fetches from Yahoo Finance:
   - 30 days ES daily data
   - 5 days ES 15-minute intraday data
   - 5 days VIX data
4. Calculates VWAP and Volume Profile
5. Generates and caches market context
6. Authenticates with TopstepX API

### During Trading Hours
1. Every minute (configurable):
   - Captures screenshot of Bookmap window
   - Queries current position status via API
   - If no position: Analyzes for entry opportunities
   - If position exists: Manages position (adjust stops, scale, or close)
2. Sends screenshot + market context + prompt to GPT-4o
3. Receives JSON response with action and reasoning
4. Executes trade if action is buy/sell/adjust/scale/close
5. Logs trade event to CSV and daily log
6. Sends Telegram notification
7. Updates market context if LLM provides new insights

### Position Management Cycle (Every 15s)
- Checks if position is still active
- Queries working orders (brackets)
- Provides LLM with current P&L and order status
- LLM can recommend: hold, adjust stops/targets, scale out, or close
- System executes recommended actions

### After Hours
- System stops taking screenshots (outside time range)
- All data preserved in folders:
  - `logs/` - Daily execution logs
  - `trades/` - Monthly CSV files
  - `screenshots/` - Captured images
  - `market_data/` - Historical price data and context cache

## Data Storage Structure

```
ESTrader/
├── screenshot_uploader.py       # Main trading bot (2544 lines)
├── market_data.py               # Market data fetcher (422 lines)
├── config.ini                   # All configuration (136 lines)
├── requirements.txt             # Python dependencies
├── start_trading.ps1            # Main launcher
├── fetch_market_data.ps1        # Pre-fetch market data
├── MARKET_DATA_GUIDE.md         # Market data documentation
├── EXAMPLE_INTRADAY_OUTPUT.txt  # Sample context output
├── logs/                        # Daily execution logs
│   ├── 20251118.txt
│   ├── 20251119.txt
│   └── ...
├── screenshots/                 # Captured Bookmap images (timestamped)
├── trades/                      # Trade logs and active trade tracking
│   ├── active_trade.json       # Current position info
│   └── trades_YYYYMM.csv       # Monthly trade journal
├── market_data/                 # Yahoo Finance data cache
│   ├── ES_F_YYYYMMDD.csv       # Daily ES data
│   ├── ES_F_15m_YYYYMMDD.csv   # Intraday 15m ES data
│   ├── VIX_YYYYMMDD.csv        # VIX data
│   └── context_YYYYMMDD.txt    # Generated market context
├── context/                     # Active context (legacy folder)
└── venv/                        # Python virtual environment
```

## Trade Logging Format

Each trade event is logged to `trades/trades_YYYYMM.csv` with columns:
- Timestamp, Event Type, Symbol, Position Type, Size, Price
- Stop Loss, Take Profit, Reasoning, Confidence
- Profit/Loss ($), Profit/Loss (pts), Balance, Market Context
- Trade ID, Entry Price

## Dependencies

Core Python packages (requirements.txt):
- pillow - Screenshot capture
- requests - API calls
- schedule - Job scheduling
- pywin32 - Windows integration
- pystray - System tray icon
- yfinance - Market data from Yahoo Finance
- pandas - Data analysis
- numpy - Numerical calculations

## Current Trading Strategy

The system uses a **swing trading approach** targeting:
- Hold duration: Up to several hours
- Profit targets: 20+ points when conditions allow
- Stop losses: 4-6 points (tight risk management)
- Entry method: Market orders at immediate opportunities
- Focus: High-probability setups based on:
  - Liquidity absorption/icebergs in heatmap
  - Order book imbalance
  - Volume delta and sweeps
  - Momentum shifts and exhaustion
  - Retests of key liquidity levels
  - Market structure (higher highs/lows)
  - Position relative to VWAP and volume profile nodes

## Safety Features

1. **Multiple kill switches**:
   - `enable_llm` - Disable AI analysis
   - `enable_trading` - Disable API calls
   - `execute_trades` - Final confirmation for live execution

2. **Time restrictions**: Only operates during configured hours

3. **Error handling**: Critical API errors show popup dialog

4. **Mock mode**: Can run with all safety switches off for testing

5. **Position tracking**: Maintains state between runs via JSON file

6. **Risk limits**: Configurable maximum risk per contract

## API Credentials

The system requires:
- OpenAI API key (for GPT-4o vision)
- TopstepX API credentials (username, API secret)
- TopstepX account ID
- Telegram bot token and chat ID (for notifications)

All stored in `config.ini` (already configured).

## Current Status

Based on git status:
- Modified: config.ini, requirements.txt, screenshot_uploader.py
- New files: Market data integration (market_data.py, MARKET_DATA_GUIDE.md, etc.)
- Trading account: TopstepX account #14664776
- Contract: ES December 2025 (CON.F.US.EP.Z25)
- Position size: 2 contracts
- Currently not tracking any active position (context/ is empty)

## Notes for Future Sessions

1. The system has been enhanced with comprehensive market data integration
2. LLM now receives rich market context (VWAP, volume profile, VIX, trend)
3. Both daily and intraday (15m) analysis is provided
4. Context updates dynamically as LLM observes intraday changes
5. All trades are logged to CSV with full details for analysis
6. System can run fully automated during configured trading hours
7. Telegram notifications keep you informed of all trade activity


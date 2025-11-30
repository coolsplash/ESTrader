# ESTrader - AI-Powered ES Futures Trading System

## Project Overview
ESTrader is an automated trading system for E-mini S&P 500 (ES) futures that uses AI vision analysis of Bookmap screenshots combined with market data to make trading decisions. The system runs on Windows, captures screenshots from thinkorswim/Bookmap, analyzes order flow using GPT-4o vision, and executes trades via the TopstepX API.

## System Architecture

### Core Components

1. **screenshot_uploader.py** (5550+ lines)
   - Main trading bot that orchestrates the entire system
   - Runs as a Windows system tray application with scheduler
   - Captures screenshots of Bookmap chart with dynamic interval scheduling
   - Sends screenshots to GPT-4o for analysis
   - Manages positions and executes trades via TopstepX API
   - Handles both entry signals and position management (adjust/scale/close)
   - Logs all trades to monthly CSV files with full details
   - **Supabase integration**: Dual logging to PostgreSQL database for analytics
   - Sends Telegram notifications for all trade events
   - Hot-reload configuration without restarting
   - After-hours trading detection (RTH vs ETH)
   - Overnight session support (handles time windows crossing midnight)
   - API query optimization (only during trading hours)
   - **TopstepX bar data**: Fetches and caches 5m OHLCV bars for context
   - Window process name filtering for accurate screenshot capture

2. **market_data.py** (433 lines)
   - Fetches ES futures and VIX data from Yahoo Finance
   - Calculates daily and intraday (5-minute) VWAP
   - Generates Volume Profile analysis (top 5 price levels)
   - Detects gap-ups and gap-downs (2+ point threshold)
   - Creates formatted market context for LLM prompts
   - Pure data generation (caching handled by screenshot_uploader.py)
   - Can be run standalone or integrated into main system

3. **market_holidays.py** (~500 lines)
   - Fetches market holiday schedules from EdgeClear
   - Extracts Equities futures trading hours using BeautifulSoup
   - Parses holiday data with LLM (CT to ET conversion)
   - Handles Trading Halt with Reopen (e.g., Thanksgiving 13:00 halt, 18:00 reopen)
   - Caches weekly data to avoid redundant fetches
   - Provides functions to check holidays, early closes, and specific times
   - Integrates with main bot to stop trading before early closes
   - Configurable buffer times (minutes before close, minutes after open)

4. **config.ini** (193 lines)
   - Centralized configuration for all system components
   - **Points to external prompt files** (no_position_prompt.txt, position_prompt.txt, runner_prompt.txt)
   - TopstepX API credentials and settings
   - Trading parameters (risk limits, contract size, etc.)
   - Market data settings (tickers, intervals, analysis parameters)
   - **Market holidays configuration**: EdgeClear integration, buffer times
   - Time window controls (no_new_trades_windows, force_close_time)
   - **Interval scheduling**: Time-based screenshot intervals (e.g., 30s during RTH, 5min pre-market)
   - **Supabase configuration**: Database connection and logging settings
   - **TopstepX bars configuration**: Bar data fetching and caching settings
   - **Runner strategy configuration**: runners_quantity and runner_prompt settings
   - Hot-reloadable without restarting the application

5. **Prompt Files** (External prompt management)
   - **no_position_prompt.txt** - LLM prompt for identifying new trade entries (sweep/reclaim/retest setups)
   - **position_prompt.txt** - LLM prompt for managing existing positions (risk management, scaling, exits)
   - **runner_prompt.txt** - LLM prompt for managing runner contracts after scaling out (specialized for letting winners run)
   - **position_variables.txt** - Documentation of all placeholder variables used in prompts:
     - Common: {Context}, {Symbol}, {display_symbol}
     - Position-specific: {position_type}, {size}, {average_price}, {current_stop_loss}, {current_take_profit}, {unrealized_pnl}, {Reason}
   - Easier to edit and version control than inline config.ini text
   - System automatically loads prompt content from files at startup and config reload

### PowerShell Scripts

- **start_trading.ps1** - Main launcher that activates venv and starts the trading system
- **fetch_market_data.ps1** - Standalone script to pre-fetch market data before trading hours

## Key Features

### 1. AI-Powered Trading Decisions
- Uses GPT-4o vision model to analyze Bookmap screenshots
- Analyzes: liquidity zones, order book imbalance, volume delta, momentum shifts, market structure
- Three prompt modes:
  - **No Position Mode**: Looks for high-probability entry opportunities (buy/sell/hold)
  - **Position Management Mode**: Manages open positions (hold/adjust/scale/close)
  - **Runner Management Mode**: Specialized management for remaining contracts after scaling
- Returns structured JSON with action, prices, confidence, and reasoning

### 2. Market Context Integration
- Automatically fetches daily market data before trading
- Detects and reports gap-ups/gap-downs (2+ points significant)
- Provides LLM with comprehensive context including:
  - Current ES price, daily range, 5-day trend
  - Gap detection (previous close comparison)
  - VWAP (5-day) and current price relationship
  - VIX volatility level and change
  - Volume Profile top 5 levels (Point of Control)
  - Intraday 15-minute volume profile and VWAP
  - Key support/resistance levels
  - After-hours trading notice (outside RTH: 9:30 AM - 4:00 PM ET)
- Context updates dynamically throughout the day based on LLM observations
- Unified storage in `context/YYMMDD.txt` (single source of truth)
- On-demand refresh via tray menu

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

### 6. Market Holiday Management
- **EdgeClear integration**: Fetches holiday schedules from https://edgeclear.com/exchange-holiday-hours/
- **Efficient parsing**: BeautifulSoup extracts only Equities row before LLM processing
- **Trading Halt with Reopen**: Correctly handles days like Thanksgiving (halt at 13:00, reopen at 18:00)
- **Time conversion**: Automatic CT to ET conversion (+1 hour)
- **Weekly caching**: Stores current week data in `market_data/market_holidays.json`
- **Configurable buffers**:
  - `minutes_before_close`: Stop trading X minutes before early close (default: 30)
  - `minutes_after_open`: Wait X minutes after open before trading (default: 5)
- **Trading logic**:
  - Full holidays: Skip all processing for the day
  - Early close: Stop trading at adjusted time (close_time - buffer)
  - Trading halt with reopen: Skip during halt period, resume after reopen
- **Example - Thanksgiving 2025**:
  - Before 12:30: Trading allowed
  - 12:30-17:59: Skip (halt period with 30min buffer)
  - 18:00+: Trading resumes (market reopened)
- **Black Friday handling**: Correctly identifies market already open from previous day (open_time: null)

### 7. Comprehensive Logging & Notifications
- Daily log files with full execution details
- Monthly CSV trade journals with:
  - Timestamp, Event Type (ENTRY/ADJUSTMENT/SCALE/CLOSE/HOLD)
  - Symbol, Position Type, Size, Price
  - Stop Loss, Take Profit, Reasoning, Confidence
  - P&L (dollars and points), Account Balance
  - Market Context at time of trade
  - Trade ID for tracking
- **Supabase database logging**: 
  - Real-time PostgreSQL storage
  - Analytics views (daily stats, win rates, monthly performance)
  - LLM interaction tracking with full prompts/responses
  - Market context snapshots
  - Account balance history
- Telegram notifications for all trade events
- Detailed error logging with stack traces
- LLM interaction logs in CSV format (`logs/*_LLM.csv`)

### 8. User Interface
- Windows system tray icon with menu
- Functions accessible via right-click:
  - Start/Stop scheduler
  - **Reload Config** - Hot-reload config.ini without restart
  - **Refresh Market Context** - Fetch latest market data on demand
  - Take manual screenshot
  - Set position type (None/Long/Short)
  - Toggle LLM/Trading
  - Select account
  - Test API connections (positions, orders)
  - List all available contracts
  - Exit application

## Configuration Highlights

### General Settings
- `interval_seconds`: Default screenshot interval in seconds (can be overridden by schedule)
- `interval_schedule`: Time-based intervals (e.g., "09:30-16:00=30,18:00-23:59=300")
- `trade_status_check_interval`: How often to check positions (default: 20s)
- `begin_time`/`end_time`: Trading hours window (supports overnight sessions)
- `no_new_trades_windows`: Time ranges to pause new entries (e.g., "09:15-09:35,15:45-18:02")
- `force_close_time`: Force close all positions at this time (only if within session)
- `window_title`: Bookmap window to capture
- `window_process_name`: Filter windows by process (e.g., Bookmap.exe)
- `enable_llm`: Enable/disable AI analysis
- `enable_trading`: Enable/disable actual trade execution
- `execute_trades`: Additional safety flag for live trading
- `enable_save_screenshots`: Save screenshots to disk

### LLM Configuration
- `symbol`: Contract ID (e.g., CON.F.US.EP.Z25)
- `display_symbol`: Human-readable symbol (e.g., ES)
- `no_position_prompt`: File path to no-position prompt (e.g., no_position_prompt.txt)
- `position_prompt`: File path to position management prompt (e.g., position_prompt.txt)
- `model`: AI model to use (current: gpt-5.1-chat-latest)
- **Note**: Prompts are now stored in external .txt files for easier editing and version control

### TopstepX Settings
- Account credentials and endpoints
- Contract details (ES December 2025: CON.F.US.EP.Z25)
- Position sizing (current: 3 contracts)
- Runner strategy (current: 1 runner contract)
- Risk parameters (8 points max risk, 30 points max profit)
- Tick size (0.25 for ES)
- Stop loss and take profit orders (currently disabled by default)

### TopstepX Bar Data Settings
- `enable_bar_data`: Fetch OHLCV bar data for context
- `bar_interval`: Bar interval (5m)
- `num_bars`: Number of bars to include in LLM context (36 bars = 3 hours)
- `market_open`/`market_close`: Hours for bar fetching
- Cached in `cache/bars/` directory

### Market Data Settings
- ES and VIX tickers (ES=F, ^VIX)
- Historical data lookback (10 days)
- Volume profile parameters (5 nodes from 5 days)
- Intraday analysis enabled with 5m intervals
- Auto-fetch on startup if context missing
- Caching to avoid repeated API calls

### Market Holidays Settings
- `enable_holiday_check`: Enable/disable holiday checking (default: true)
- `cme_url`: EdgeClear holiday calendar URL
- `data_file`: Weekly cache file path (market_data/market_holidays.json)
- `minutes_before_close`: Buffer before early close (default: 30)
- `minutes_after_open`: Buffer after open (default: 5)
- `force_refresh`: Force refresh even if cached data exists (default: false)
- Automatic weekly data refresh when current week data is missing

### Supabase Database Settings
- `supabase_url`: Project URL
- `supabase_anon_key`: Anonymous/public API key
- `enable_supabase_logging`: Enable dual logging to PostgreSQL database
- Automatic account registration
- Real-time analytics and aggregation views
- Historical data backfill support

## Typical Workflow

### Morning (Before Market Open)
1. System starts via `start_trading.ps1`
2. Checks for today's market context in `context/YYMMDD.txt`
3. If missing, automatically fetches from Yahoo Finance:
   - 30 days ES daily data
   - 5 days ES 15-minute intraday data
   - 5 days VIX data
4. Calculates VWAP, Volume Profile, and gap analysis
5. Generates and caches market context
6. **Checks for current week's holiday data**:
   - Fetches from EdgeClear if missing
   - Parses with LLM (CT to ET conversion)
   - Caches to `market_data/market_holidays.json`
7. Authenticates with TopstepX API
8. Detects if trading during after-hours (ETH) and adds notice

### During Trading Hours
1. Every interval (configurable, e.g., 30s):
   - **Checks holiday status**:
     - Skip if full holiday (market closed)
     - Check if early close day (calculate adjusted stop time with buffer)
     - Check if in Trading Halt period (skip until reopen)
   - Captures screenshot of Bookmap window
   - Queries current position status via API (only during trading hours)
   - Appends after-hours notice to context if outside RTH
   - If no position: Analyzes for entry opportunities
   - If position exists: Manages position (adjust stops, scale, or close)
2. Sends screenshot + market context + prompt to GPT-4o
3. Receives JSON response with action and reasoning
4. Executes trade if action is buy/sell/adjust/scale/close
5. Logs trade event to CSV, daily log, and Supabase
6. Sends Telegram notification
7. Updates market context if LLM provides new insights
8. No-new-trades window respected (stops entries between configured times)
9. Holiday buffer times respected (stops before early close, waits after open)

### Position Management Cycle (Every 15s)
- Checks if position is still active
- Queries working orders (brackets)
- Provides LLM with current P&L and order status
- LLM can recommend: hold, adjust stops/targets, scale out, or close
- System executes recommended actions

### After Hours / Outside Trading Window
- System stops taking screenshots (outside configured time range)
- API queries paused (no unnecessary position checks)
- All data preserved in folders:
  - `logs/` - Daily execution logs
  - `trades/` - Monthly CSV files
  - `screenshots/` - Captured images
  - `context/` - Daily market context
  - `market_data/` - Historical price data cache
- Config can be modified and hot-reloaded via tray menu
- Market context can be refreshed on demand for next session

## Data Storage Structure

```
ESTrader/
├── screenshot_uploader.py       # Main trading bot (5939 lines)
├── market_data.py               # Market data fetcher (433 lines)
├── market_holidays.py           # Holiday data fetcher (~500 lines)
├── config.ini                   # All configuration (193 lines)
├── no_position_prompt.txt       # LLM prompt for new entries
├── position_prompt.txt          # LLM prompt for position management
├── runner_prompt.txt            # LLM prompt for managing runners after scaling
├── position_variables.txt       # Documentation of prompt variables
├── backfill_supabase.py         # Import historical CSV data to Supabase
├── requirements.txt             # Python dependencies
├── start_trading.ps1            # Main launcher
├── fetch_market_data.ps1        # Pre-fetch market data
├── MARKET_DATA_GUIDE.md         # Market data documentation
├── PROMPT_FORMATTING_GUIDE.md   # Prompt formatting and escaping documentation
├── EDGECLEAR_INTEGRATION.md     # Holiday data integration documentation
├── EXAMPLE_INTRADAY_OUTPUT.txt  # Sample context output
├── PROJECT_SUMMARY.md           # This file
├── QUICK_CONTEXT.md             # Quick reference guide
├── logs/                        # Daily execution logs
│   ├── 20251127.txt            # Daily log files
│   ├── 251127_LLM.csv          # LLM interaction logs
│   └── ...
├── screenshots/                 # Captured Bookmap images (timestamped)
├── trades/                      # Trade logs and active trade tracking
│   ├── active_trade.json       # Current position info
│   └── 2025_11.csv             # Monthly trade journal
├── context/                     # Daily market context (dual storage)
│   ├── 251127.txt              # Base context (YYMMDD format)
│   ├── 251127_LLM.txt          # LLM-updated context
│   └── ...
├── market_data/                 # Yahoo Finance raw data cache
│   ├── ES_F_20251127.csv       # Daily ES data
│   ├── ES_F_5m_20251127.csv    # Intraday 5m ES data
│   ├── VIX_20251127.csv        # VIX data
│   └── market_holidays.json    # Weekly holiday schedule (EdgeClear)
├── cache/                       # TopstepX API caches
│   └── bars/                   # 5m OHLCV bar data
│       └── 20251127.json       # Daily bar cache
├── supabase/                    # Database schema and migrations
│   ├── migrations/             # SQL migration files
│   └── README.md               # Database documentation
├── testing/                     # Test scripts and utilities
│   ├── test_llm.py             # LLM prompt testing
│   ├── test_signalr_user_hub.py # SignalR real-time testing
│   ├── test_market_holidays.py # Holiday integration tests
│   ├── test_edgeclear_fetch.py # EdgeClear data fetching tests
│   ├── test_trading_halt_reopen.py # Trading halt/reopen logic tests
│   └── responses/              # Test response storage
└── venv/                        # Python virtual environment
```

## Trade Logging Format

### CSV Files
Each trade event is logged to `trades/YYYY_MM.csv` with columns:
- Timestamp, Event Type (ENTRY/ADJUSTMENT/SCALE/CLOSE/HOLD)
- Symbol, Position Type, Size, Price
- Stop Loss, Take Profit, Reasoning, Confidence
- Profit/Loss ($), Profit/Loss (pts), Balance, Market Context
- Trade ID, Entry Price, Order ID

### Supabase Database
When enabled, all trade events are also logged to PostgreSQL with:
- **trades table**: Complete trade event history with all fields
- **llm_interactions table**: Full LLM prompts, responses, and decisions
- **market_context table**: Daily market analysis snapshots
- **account_snapshots table**: Balance history for equity curve
- **Analytics views**: 
  - `daily_trade_stats`: Daily aggregated statistics
  - `win_rate_analysis`: Win rate and profitability metrics
  - `monthly_performance`: Monthly P&L and drawdown
  - `recent_trades`: Last 100 trades for quick reference

## Dependencies

Core Python packages (requirements.txt):
- pillow>=10.0.0 - Screenshot capture
- requests>=2.31.0 - API calls
- schedule>=1.2.0 - Job scheduling
- pystray>=0.19.4 - System tray icon
- yfinance>=0.2.28 - Market data from Yahoo Finance
- pandas>=2.0.0 - Data analysis
- numpy>=1.24.0 - Numerical calculations
- supabase>=2.0.0 - PostgreSQL database integration
- signalrcore>=0.9.5 - SignalR real-time connectivity (testing)

## Current Trading Strategy

The system uses a **precision entry and active management approach** targeting:
- Hold duration: Up to several hours
- Profit targets: 20-30+ points when structure allows
- Stop losses: 5-10 points (structure-based risk management)
- Entry method: Market orders at high-conviction setups
- **Primary Focus**: Sweep → Reclaim → Retest → Reversal setups
  - Sweep of key level with immediate rejection
  - Reclaim with aggressive taker initiative
  - Retest of flipped liquidity level
  - Reversal with clear delta flip and follow-through
- **Secondary Focus**: High-probability trend continuation
  - Clean directional structure (HH/HL or LH/LL)
  - Pullbacks defended with absorption
  - Delta and volume confirm direction
- **Microstructure Signals**:
  - Stop-run wicks into high liquidity
  - Absorption walls holding/shifting during sweeps
  - Liquidity thinning in continuation direction
  - Delta flipping after sweep or reclaim
  - Stacked bids/offers appearing after reclaim
- **Position Management**: Active risk reduction
  - Scale out at key levels (1R-2R)
  - Move stops to breakeven after 1R move
  - Trail stops behind structure
  - Never allow winners to turn into losers
  - Exit immediately if thesis invalidated

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

Based on recent changes:
- Core files: screenshot_uploader.py (5939 lines), market_data.py (433 lines), market_holidays.py (~500 lines), config.ini (193 lines)
- **Prompt management**: External .txt files (no_position_prompt.txt, position_prompt.txt, runner_prompt.txt, position_variables.txt)
- **Runner strategy**: Configurable runners_quantity with specialized runner_prompt for post-scale management
- **Market holidays**: EdgeClear integration with Trading Halt/Reopen support
- Market data integration: Fully operational with gap detection and 5m intraday data
- Context storage: Dual storage (`context/YYMMDD.txt` base + `context/YYMMDD_LLM.txt` updated)
- TopstepX bar data: 5m OHLCV bars cached in `cache/bars/` directory
- Trading account: TopstepX account #14789500
- Contract: ES December 2025 (CON.F.US.EP.Z25)
- Position size: 3 contracts
- LLM model: gpt-5.1-chat-latest
- Supabase: Integrated for database logging and analytics
- Features: 
  - Market holiday checking (EdgeClear integration)
  - Trading Halt with Reopen support (e.g., Thanksgiving)
  - Dynamic interval scheduling
  - Hot-reload configuration (including external prompt files)
  - After-hours detection
  - Overnight sessions
  - API optimization
  - Window process filtering
  - Database logging with analytics views
  - External prompt file management
- Menu: Enhanced tray icon with config reload and context refresh options

## Recent Enhancements (November 2025)

### Runner Strategy Implementation (Latest)
- **Configurable runners**: `runners_quantity` setting in config.ini (default: 1)
- **Specialized prompt**: `runner_prompt.txt` for managing runner contracts
- **Smart scaling logic**: When LLM chooses to scale, system closes `quantity - runners_quantity` contracts
- **Automatic prompt switching**: System detects when position size equals runners_quantity and switches to runner_prompt
- **Flexible configuration**: 
  - Set `runners_quantity > 0` to keep runners after scaling
  - Set `runners_quantity = 0` for traditional "scale closes entire position" behavior
- **Enhanced logging**: Clear indication when managing runners vs full position
- **Hot-reload support**: Runner configuration reloads with config.ini
- **Example workflow**:
  1. Enter with 3 contracts (uses position_prompt)
  2. LLM decides to scale → closes 2 contracts (3 - 1)
  3. Remaining 1 contract (uses runner_prompt for specialized management)

### Market Holiday Integration
- **EdgeClear data source**: Fetches Equities futures holiday schedules
- **Efficient extraction**: BeautifulSoup pre-processes HTML to extract only Equities row
- **LLM parsing**: GPT-4o processes holiday data with CT to ET conversion
- **Trading Halt with Reopen**: Handles complex schedules (e.g., Thanksgiving halt at 13:00, reopen at 18:00)
- **Intelligent trading logic**: 
  - Skips full holidays entirely
  - Stops trading before early closes (with configurable buffer)
  - Resumes trading after reopen times
  - Correctly handles days already open from previous day (open_time: null)
- **Weekly caching**: Stores data in `market_data/market_holidays.json`
- **Configurable buffers**: minutes_before_close (30) and minutes_after_open (5)
- **Testing**: Comprehensive test suite verifying all holiday scenarios
- **Token efficiency**: Reduced from ~7,000 tokens to ~1,500-2,000 tokens per LLM call

### External Prompt Management
- **Prompt files**: LLM prompts moved to separate .txt files for easier editing
- **no_position_prompt.txt**: Contains full prompt for identifying new trade entries
- **position_prompt.txt**: Contains full prompt for managing existing positions
- **position_variables.txt**: Comprehensive documentation of all placeholder variables
- **Safe formatting**: Automatic escaping of special characters (curly braces, quotes) in replacement values
- **Error handling**: Graceful handling of missing placeholders or format errors with detailed logging
- **Benefits**: Easier version control, simpler editing, better organization, robust handling of complex data
- **Automatic loading**: System loads prompt content from files at startup and reload
- **Backward compatible**: Still supports inline prompts in config.ini if needed
- **Documentation**: See PROMPT_FORMATTING_GUIDE.md for details on escaping and best practices

### Supabase Database Integration
- **Dual logging**: All trades and LLM interactions logged to PostgreSQL database
- **Analytics views**: Pre-built aggregations for daily stats, win rates, monthly performance
- **Account snapshots**: Balance tracking for equity curve analysis
- **Backfill support**: Import historical CSV data via `backfill_supabase.py`
- **Real-time storage**: Centralized data warehouse for advanced analysis

### TopstepX Bar Data
- **5-minute OHLCV bars**: Fetched from TopstepX API for enhanced context
- **Bar caching**: Cached in `cache/bars/` directory to minimize API calls
- **Configurable**: 36 bars (3 hours) included in LLM context by default
- **Market-aware**: Only fetches during configured market hours

### Dynamic Interval Scheduling
- **Time-based intervals**: Different screenshot frequencies for different times
- **Example**: 30s during RTH, 5min during pre-market, 5min after-hours
- **Configurable**: Format "HH:MM-HH:MM=seconds" with multiple ranges
- **Disabled periods**: Use -1 to disable screenshots during specific times (e.g., lunch)

### Context Management Improvements
- **Dual storage**: Base context in `YYMMDD.txt`, LLM updates in `YYMMDD_LLM.txt`
- **Gap detection**: Automatically identifies gap-ups/gap-downs (2+ point threshold)
- **After-hours notices**: Automatically appended when trading outside RTH (9:30 AM - 4:00 PM ET)
- **On-demand refresh**: Tray menu option to fetch latest market data anytime
- **Fallback logic**: Uses yesterday's context if current fetch fails
- **5m intraday data**: More granular intraday volume profile and VWAP

### Configuration & Control
- **Hot-reload**: Modify config.ini and reload via tray menu without restart
- **No-new-trades windows**: Multiple time ranges to pause entries (comma-separated)
- **Overnight sessions**: Properly handles trading windows that cross midnight
- **Force close logic**: Only applies if within the current trading session
- **Window filtering**: Process name filtering ensures correct window capture

### Performance Optimizations
- **Smart API queries**: Position/order checks only run during trading hours
- **Reduced overhead**: No unnecessary API calls outside configured windows
- **Trade monitoring**: Background thread respects trading hours
- **Bar caching**: Daily cache files minimize redundant API calls

### Enhanced Menu & UI
- New tray menu items for config reload and market context refresh
- All system controls accessible without restart
- Quick access to testing and diagnostic functions

### Testing Infrastructure
- **SignalR testing**: Exploration of real-time WebSocket connectivity
- **LLM testing**: Standalone prompt testing with response storage
- **Comprehensive logging**: Separate test results and logs

## Notes for Future Sessions

1. The system has been enhanced with comprehensive market data integration
2. **Market holidays now managed via EdgeClear integration** with Trading Halt/Reopen support
3. LLM now receives rich market context (VWAP, volume profile, VIX, trend, gaps, 5m bars)
4. Both daily and intraday (5m) analysis is provided
5. Context updates dynamically as LLM observes intraday changes (stored separately)
6. All trades are logged to CSV **and** Supabase database for advanced analytics
7. System can run fully automated during configured trading hours
8. **Trading automatically pauses on holidays and before early closes** (configurable buffers)
9. Telegram notifications keep you informed of all trade activity
10. Hot-reload capability allows config changes without downtime (including prompt files)
11. After-hours trading is automatically detected and communicated to LLM
12. Context management uses dual storage (base + LLM updates) for reliability
13. Dynamic interval scheduling allows optimal screenshot frequency per time period
14. TopstepX bar data provides additional price action context to LLM
15. Supabase integration enables real-time analytics, win rate tracking, and performance views
16. SignalR testing infrastructure in place for potential real-time event migration
17. Current model is gpt-5.1-chat-latest with updated prompts focused on sweep/reclaim setups
18. **LLM prompts now managed in external .txt files** for easier editing and version control (no_position_prompt.txt, position_prompt.txt, runner_prompt.txt, position_variables.txt)
19. **Holiday data cached weekly** - automatic refresh when current week data is missing
20. **Runner strategy implemented** - keep specified number of contracts as "runners" after scaling with specialized management prompt


# ES Market Data Integration Guide

## Overview
The trading system now integrates Yahoo Finance data to provide daily market context including:
- ES futures price data (OHLC)
- VIX volatility index
- VWAP (Volume Weighted Average Price)
- Volume Profile (top 5 price levels)
- Key support/resistance levels

## Installation (Already Done)
The required packages are installed in your venv:
- `yfinance` - Yahoo Finance data fetcher
- `pandas` - Data analysis
- `numpy` - Numerical computations

## Usage

### Option 1: Automatic (Recommended)
Simply run your trading system as usual:
```powershell
.\start_trading.ps1
```

The system will **automatically**:
1. Check if today's market context exists
2. If not, fetch data from Yahoo Finance
3. Generate context and save it
4. Use it throughout the trading day

### Option 2: Manual Pre-fetch
Run this before market open (8:00 AM suggested):
```powershell
.\fetch_market_data.ps1
```

This will:
- Fetch 30 days of ES and VIX data
- Calculate VWAP and Volume Profile
- Generate market context
- Store data in `market_data/` folder
- Cache context in `context/YYMMDD.txt`

## Configuration
All settings are in `config.ini` under the `[MarketData]` section:

```ini
[MarketData]
es_ticker = ES=F                    # ES futures continuous contract
vix_ticker = ^VIX                   # VIX volatility index
historical_days = 30                # Days of historical data to fetch
focus_days = 5                      # Days to focus on for volume profile
volume_nodes = 5                    # Number of key price levels to identify
data_folder = market_data           # Where to store CSV data
enable_auto_fetch = true            # Auto-fetch if context missing
fetch_time = 08:00                  # Suggested time to fetch data
enable_intraday = true              # Enable 15-min intraday analysis
intraday_interval = 15m             # Options: 5m, 15m, 30m, 1h
intraday_days = 5                   # Days of intraday data (max 60 for 15m)
intraday_volume_nodes = 5           # Top N intraday volume levels
```

### Intraday Configuration Options
- **enable_intraday**: Set to `false` to disable intraday analysis (daily only)
- **intraday_interval**: Choose granularity
  - `5m` - Most granular (max 60 days)
  - `15m` - Recommended for day trading (max 60 days)
  - `30m` - Good balance (max 60 days)
  - `1h` - Broader view (max 730 days)
- **intraday_days**: More days = more data, but slower fetching
- **intraday_volume_nodes**: How many key levels to identify (typically 5-10)

## Market Context Example
```
Market Context (Nov 23, 2025):
ES: Open 6025.00, Current 6032.50 (+7.50, +0.12%), Range 6018.25-6040.75
5-Day Trend: UPTREND (+1.45%)
VWAP (5-day): 6028.25 | Price is 4.25 pts BULLISH of VWAP
VIX: 14.23 (-2.1%) - Low volatility (complacent)

Volume Profile (Top 5 levels from past 5 days):
  1. 6030.00 pts (POC - Point of Control)
  2. 6027.50 pts
  3. 6035.25 pts
  4. 6022.75 pts
  5. 6018.50 pts

Intraday 15m Volume Profile (Past 5 days, 260 bars):
Intraday VWAP: 6028.75 | Price is 3.75 pts BULLISH
Top 5 High Volume Zones:
  1. 6031.25 pts (8.2% of volume) (Intraday POC)
  2. 6029.50 pts (6.5% of volume)
  3. 6026.75 pts (5.9% of volume)
  4. 6024.00 pts (5.3% of volume)
  5. 6022.25 pts (4.8% of volume)

Key Levels: Support 6018.25, Resistance 6040.75
```

### Intraday Volume Profile Benefits
- **More Granular**: 15-minute bars show precise intraday trading zones
- **Better Entry/Exit**: Identify exact price levels with most activity
- **Volume Percentage**: See concentration of trading at each level
- **Separate VWAP**: Intraday VWAP for short-term bias

This context is automatically injected into your LLM prompts via the `{Context}` placeholder.

## Troubleshooting

### Yahoo Finance Connection Failed
If you see connection errors:
1. **Check firewall** - Ensure Python can access `fc.yahoo.com` on port 443
2. **Check proxy** - If behind a corporate proxy, configure it
3. **Try later** - Yahoo Finance may have temporary outages

**Don't worry!** The system gracefully falls back:
- Uses previous day's cached context if available
- Shows a helpful message if no data available
- Your trading system continues to work

### Network/Firewall Configuration
If consistently blocked:
1. Check Windows Firewall settings for Python
2. Add exception for `fc.yahoo.com`
3. Verify network connectivity: `Test-NetConnection fc.yahoo.com -Port 443`

### Manual Context Entry
If automated fetch fails consistently, you can manually create context:
1. Create file: `context/YYMMDD.txt` (e.g., `context/251123.txt`)
2. Add your market analysis text
3. System will use this instead

## Files Structure
```
ESTrader/
├── market_data.py              # Core market data module
├── fetch_market_data.ps1       # Standalone data fetcher script
├── start_trading.ps1           # Main trading system launcher
├── screenshot_uploader.py      # Main trading bot (auto-fetches if needed)
├── config.ini                  # Configuration (includes [MarketData] section)
├── market_data/                # Stored CSV data files
│   ├── ES_F_YYYYMMDD.csv      # ES daily data
│   ├── VIX_YYYYMMDD.csv       # VIX daily data
│   └── context_YYYYMMDD.txt   # Generated context cache
└── context/                    # Active context files
    └── YYMMDD.txt             # Today's context (used by LLM)
```

## Daily Workflow

### Morning Routine (Before Market Open)
1. Run `.\fetch_market_data.ps1` (or it will auto-run when you start trading)
2. Review generated context
3. Start your trading system with `.\start_trading.ps1`

### During Trading Hours
- System uses cached context throughout the day
- Context is included in all LLM decision prompts
- LLM can update context based on live price action

### After Hours
- Data is preserved in `market_data/` folder
- Historical analysis available for backtesting
- Review logs in `logs/` folder

## Advanced Usage

### Programmatic Access
You can import and use the module directly:

```python
from market_data import MarketDataAnalyzer

analyzer = MarketDataAnalyzer()

# Get current context
context = analyzer.generate_market_context()

# Get latest ES price
price = analyzer.get_latest_price()

# Fetch custom data
data = analyzer.fetch_data('ES=F', days=90)
```

### Custom Calculations
Modify `market_data.py` to add:
- Additional technical indicators
- Different volume profile algorithms
- Custom price level detection
- Multi-timeframe analysis

## Support
For issues or enhancements:
1. Check logs for detailed error messages
2. Test network connectivity to Yahoo Finance
3. Verify venv is activated when running scripts
4. Review configuration in `config.ini`


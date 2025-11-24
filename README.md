# ESTrader

AI-powered ES futures trading bot that uses GPT-4o Vision to analyze Bookmap screenshots and execute trades via TopstepX API.

## Overview

ESTrader is an automated trading system that captures screenshots from Bookmap (running in thinkorswim), sends them to GPT-4o for order flow analysis, and executes trades based on AI recommendations. The system includes comprehensive market context (VWAP, volume profile, VIX), position management, and Telegram notifications.

## Features

- 🤖 **AI-Powered Analysis**: GPT-4o Vision analyzes Bookmap heatmaps, order flow, and volume
- 📊 **Market Context**: Real-time VWAP, volume profile, VIX, support/resistance levels
- 🔄 **Position Management**: Automatic stop-loss/take-profit adjustments and position scaling
- 📱 **Telegram Notifications**: Real-time trade alerts with P&L, reasoning, and confidence
- 🎯 **System Tray Interface**: Start/stop, reload config, manual screenshots, position override
- 📈 **Trade Logging**: Detailed CSV journal with entry/exit prices, P&L, and fees
- ⏰ **Time-Based Rules**: Configurable trading hours, force close times, no-new-trades windows
- 🌙 **Overnight Sessions**: Support for trading sessions that cross midnight

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Bookmap    │────▶│ Screenshot   │────▶│   GPT-4o    │
│ (thinkorswim)│     │   Capture    │     │   Vision    │
└─────────────┘     └──────────────┘     └─────────────┘
                                                  │
                                                  ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  TopstepX   │◀────│    Trade     │◀────│  Decision   │
│     API     │     │  Execution   │     │   Engine    │
└─────────────┘     └──────────────┘     └─────────────┘
        │
        ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Telegram  │     │   CSV Log    │     │  Market     │
│ Notifications│     │  Journal     │     │   Data      │
└─────────────┘     └──────────────┘     └─────────────┘
```

## Requirements

- Windows 10/11
- Python 3.13+
- thinkorswim with Bookmap
- TopstepX trading account
- OpenAI API key (GPT-4o access)
- Telegram bot (optional, for notifications)

## Installation

1. **Clone the repository**
```bash
git clone https://github.com/coolsplash/ESTrader.git
cd ESTrader
```

2. **Create virtual environment**
```bash
python -m venv venv
venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure settings**
```bash
# Copy the example config and edit with your credentials
copy config.ini.example config.ini
notepad config.ini
```

Update the following in `config.ini`:
- `[Topstep]` section: Your TopstepX API credentials and account ID
- `[OpenAI]` section: Your OpenAI API key
- `[Telegram]` section: Your Telegram bot token and chat ID

5. **Launch the system**
```bash
.\start_trading.ps1
```

## Configuration

### Trading Hours
```ini
begin_time = 00:00              # Start of trading session
end_time = 23:59                # End of trading session
no_new_trades_time = 15:45      # Stop opening new positions
no_new_trades_end_time = 18:00  # Resume trading after break
force_close_time = 15:50        # Force close all positions
```

### Safety Flags
```ini
enable_llm = true          # Use AI analysis
enable_trading = true      # Enable API calls to broker
execute_trades = false     # Actually execute trades (set true when ready)
```

### Trading Parameters
```ini
[Topstep]
quantity = 2                      # Number of contracts per trade
max_risk_per_contract = 8         # Maximum stop loss in points
max_profit_per_contract = 30      # Maximum take profit in points
enable_stop_loss = false          # Use bracket stop orders
enable_take_profit = false        # Use bracket profit orders
```

## Usage

### Starting the Bot

1. **Launch via PowerShell script:**
```powershell
.\start_trading.ps1
```

2. **Or run directly:**
```bash
venv\Scripts\activate
python screenshot_uploader.py
```

The bot will:
- Authenticate with TopstepX API
- Fetch initial market data
- Start capturing screenshots at configured intervals
- Run as a system tray application

### System Tray Menu

Right-click the tray icon for quick access:
- **Start/Stop** - Control the scheduler
- **Reload Config** - Hot-reload config.ini changes
- **Refresh Market Context** - Fetch latest market data
- **Set Position** - Manually override position tracking
- **Toggle LLM/Trading** - Enable/disable features
- **Take Screenshot Now** - Manual screenshot analysis
- **Test Positions/Orders** - Debug API connectivity
- **Exit** - Shutdown the bot

### Monitoring

**Logs:**
- `logs/YYYYMMDD.txt` - Daily execution logs
- `trades/YYYY_MM.csv` - Monthly trade journal with P&L

**Telegram Notifications:**
- New position opened with reasoning and confidence
- Position closed with actual P&L from API
- Stop-loss/take-profit adjustments

## Data Flow

### Entry Analysis (No Position)
1. Capture Bookmap screenshot
2. Query TopstepX API for current position status
3. Load daily market context (VWAP, volume profile, key levels)
4. Send screenshot + context to GPT-4o
5. Parse JSON response: `{action, entry_price, stop_loss, price_target, confidence, reasoning}`
6. If action is buy/sell: Place market order with brackets
7. Log trade event to CSV
8. Send Telegram notification

### Position Management (Active Trade)
1. Capture screenshot every 1 minute
2. Check position status every 15 seconds
3. Send screenshot to GPT-4o with position details
4. Parse response: `{action: hold/adjust/scale/close, stop_loss, price_target, reasoning}`
5. Execute recommended action via TopstepX API
6. Update CSV log with adjustments
7. Notify via Telegram

### Exit Detection
1. Detect position change from active → none
2. Query `/api/Trade/search` for actual fill data
3. Calculate net P&L (profit/loss minus fees)
4. Update CSV with final results
5. Send Telegram notification with emoji (✅ profit / ❌ loss)

## Market Context

The system provides GPT-4o with comprehensive market context:

- **ES Price Data**: Current price, daily range, 5-day trend
- **VWAP**: 5-day VWAP and intraday 15-minute VWAP
- **Volume Profile**: Top 5 volume nodes (daily + intraday)
- **VIX Level**: Current volatility reading
- **Gap Detection**: Gap up/down vs previous close
- **Support/Resistance**: Key levels from volume analysis
- **After-Hours Notice**: Alert when trading outside RTH (9:30 AM - 4:00 PM ET)

## Project Structure

```
ESTrader/
├── screenshot_uploader.py    # Main trading bot (3126 lines)
├── market_data.py            # Market data fetcher and analyzer
├── config.ini                # Configuration (DO NOT COMMIT)
├── config.ini.example        # Template for setup
├── requirements.txt          # Python dependencies
├── start_trading.ps1         # Launcher script
├── fetch_market_data.ps1     # Market data refresh script
├── logs/                     # Daily execution logs (gitignored)
├── trades/                   # Trade journal CSVs (gitignored)
├── context/                  # Daily market context cache (gitignored)
├── market_data/              # Yahoo Finance raw data (gitignored)
├── screenshots/              # Captured images (gitignored)
└── venv/                     # Python virtual environment (gitignored)
```

## API Integrations

- **TopstepX API**: Trade execution, position queries, order management
- **OpenAI GPT-4o Vision**: Screenshot analysis and trade recommendations
- **Yahoo Finance (yfinance)**: ES futures and VIX historical/intraday data
- **Telegram Bot API**: Real-time trade notifications

## Safety Features

- **Three-tier safety system**: `enable_llm`, `enable_trading`, `execute_trades`
- **Force close**: Automatically closes all positions at configured time
- **No-new-trades window**: Prevents new entries during break periods
- **Position detection**: Reconciles local state with broker API
- **Error dialogs**: Critical API errors show Windows notification
- **Comprehensive logging**: Every action logged with timestamp

## Trading Strategy

The LLM is prompted to:
- Focus on high-probability entries using Bookmap order flow
- Look for liquidity absorption, icebergs, and sweeps
- Identify momentum shifts and exhaustion
- Hold for several hours and aim for 20+ points
- Use tight stops (4-6 points) and maximize profits (20-30 points)
- Only trade when there's a clear, confident opportunity

## Development

### Running Tests
```bash
# Test position API
python screenshot_uploader.py --test-positions

# Test working orders API
python screenshot_uploader.py --test-orders

# Fetch market data manually
python market_data.py
```

### Debugging
- Set `enable_llm = false` to disable AI analysis
- Set `execute_trades = false` to prevent actual trading
- Check `logs/YYYYMMDD.txt` for detailed execution trace
- Use system tray menu to test individual features

## Contributing

This is a personal trading system. Fork and customize for your own use.

## Disclaimer

**⚠️ TRADING DISCLAIMER**

This software is for educational and personal use only. Trading futures involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results.

- The author is not responsible for any financial losses
- Use at your own risk
- Always test in paper trading/simulation first
- Never risk more than you can afford to lose
- This is not financial advice

## License

MIT License - See LICENSE file for details

## Support

For issues or questions, please open a GitHub issue.

---

**Built with ❤️ for algorithmic traders**


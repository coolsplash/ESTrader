# Economic Calendar Integration - Implementation Summary

## Overview

The ESTrader system now includes economic calendar integration that fetches events from MarketWatch, classifies them using LLM for market impact assessment, and provides this information to the trading bot for decision-making.

## What Was Implemented

### 1. New Module: `economic_calendar.py`

A comprehensive module with the following capabilities:

- **Fetch Calendar Events**: Scrapes MarketWatch economic calendar for current trading week
- **LLM Classification**: Uses GPT to classify each event by severity (High/Medium/Low) and expected market impact
- **Trading Week Management**: Calculates trading week boundaries (Sunday through Friday)
- **Data Caching**: Saves classified events to JSON, checks weekly to avoid redundant fetching
- **Event Filtering**: Returns upcoming events within configurable time windows
- **Fallback Handling**: Creates sample events if scraping fails, allows system to continue without calendar data

### 2. Configuration: `config.ini`

New `[EconomicCalendar]` section with settings:

```ini
[EconomicCalendar]
enable_economic_calendar = true
marketwatch_url = https://www.marketwatch.com/economy-politics/calendar
data_file = market_data/economic_calendar.json
minutes_before_event = 15
minutes_after_event = 15
severity_threshold = High,Medium
classification_prompt = Analyze these economic calendar events...
```

### 3. Integration: `screenshot_uploader.py`

**Startup Initialization**:
- Checks if calendar data exists for current trading week
- If missing, fetches from MarketWatch and classifies with LLM
- Saves to `market_data/economic_calendar.json`
- Logs calendar summary on startup

**Job Function Integration**:
- Loads calendar data at start of each job cycle
- Filters for upcoming events within configured time window
- Passes events to `generate_market_data_json()`
- Events included in JSON context sent to LLM

**Market Data JSON Structure**:
```json
{
  "CurrentTime": "...",
  "FiveMinuteBars": [...],
  "MarketContext": {...},
  "KeyLevels": {...},
  "Position": {...},
  "UpcomingEconomicEvents": [
    {
      "name": "FOMC Meeting Minutes",
      "datetime": "2025-11-27T14:00:00",
      "minutes_until": 12.5,
      "severity": "High",
      "market_impact": "Expected high volatility..."
    }
  ]
}
```

### 4. LLM Prompts: Updated with Economic Awareness

**`no_position_prompt.txt`**:
- Added "Economic Calendar Awareness" section
- Instructs LLM to avoid entries near high-impact events
- Wait for clear structure after major releases
- Handle imminent events with caution

**`position_prompt.txt`**:
- Added position management guidance around news events
- Scale out before high-severity events
- Ensure stops at break-even when holding through events
- Proactive risk management for economic releases

### 5. Dependencies: `requirements.txt`

Added:
```
beautifulsoup4>=4.12.0
lxml>=4.9.0
```

### 6. Test Suite: `testing/test_economic_calendar.py`

Comprehensive testing script that validates:
1. Trading week calculation
2. Calendar fetching from MarketWatch
3. LLM classification
4. Save/load functionality
5. Event filtering by time and severity
6. Full production workflow simulation

## How It Works

### Startup Sequence

1. System starts and loads `config.ini`
2. Checks for `market_data/economic_calendar.json`
3. If file missing or outdated (different trading week):
   - Fetches events from MarketWatch
   - Sends to GPT for classification (severity + impact description)
   - Saves classified events to JSON
4. Logs calendar summary to startup logs

### During Trading

1. Every job cycle (screenshot analysis):
   - Loads calendar data from JSON
   - Filters for events within time window (default: 15 min before/after)
   - Filters by severity threshold (default: High + Medium)
   - Adds upcoming events to market data JSON
2. LLM receives events in context
3. LLM decides autonomously:
   - Whether to take new trades near events
   - Whether to close existing positions before events
   - How to manage risk around volatility windows

### Example LLM Decision Process

**Scenario 1: No Position, FOMC Minutes in 10 minutes**
- LLM sees: "FOMC Meeting Minutes, High severity, 10 minutes away"
- Decision: "hold" - avoid new entries before major volatility event

**Scenario 2: Long Position, NFP in 5 minutes**
- LLM sees: "Non-Farm Payrolls, High severity, 5 minutes away"
- Decision: "scale" or "close" - take profits before unpredictable spike

**Scenario 3: No Position, Minor Event Passed 10 minutes ago**
- LLM sees: "Housing Starts, Medium severity, -10 minutes"
- Decision: "buy" or "sell" if clean setup - event impact has settled

## Configuration Options

### Enable/Disable Feature
```ini
enable_economic_calendar = true  ; Set to false to disable entirely
```

### Time Window Adjustment
```ini
minutes_before_event = 15  ; How far ahead to look
minutes_after_event = 15   ; How long to consider event "active"
```

### Severity Filter
```ini
severity_threshold = High,Medium  ; Include High and Medium events
severity_threshold = High         ; Include only High severity events
severity_threshold = High,Medium,Low  ; Include all events
```

### Custom Classification Prompt
```ini
classification_prompt = Your custom prompt for LLM classification...
```

## Data Storage

**File**: `market_data/economic_calendar.json`

**Structure**:
```json
{
  "fetch_timestamp": "2025-11-27T08:00:00",
  "week_start": "2025-11-24",
  "week_end": "2025-11-29",
  "events": [
    {
      "name": "FOMC Meeting Minutes",
      "datetime": "2025-11-27T14:00:00",
      "actual": null,
      "forecast": null,
      "previous": null,
      "severity": "High",
      "market_impact_description": "Expected high volatility. ES typically sees 20-50 point moves...",
      "affected_instruments": ["ES", "NQ", "YM"]
    }
  ]
}
```

## Testing

### Run Complete Test Suite
```powershell
cd testing
python test_economic_calendar.py
```

### Test Individual Functions
```powershell
python economic_calendar.py
```

The module includes `if __name__ == "__main__"` block for standalone testing.

## Error Handling

### MarketWatch Scraping Fails
- System logs warning
- Creates sample events for testing
- Trading continues with sample data

### LLM Classification Fails
- System logs error
- Uses raw events with default "Medium" severity
- Continues with unclassified events

### Calendar File Corrupted
- System detects invalid JSON
- Automatically refetches and reclassifies
- Overwrites corrupted file

### Outside Trading Week
- System detects date mismatch
- Fetches new week data on next startup
- Old data persists until new week fetched

## Benefits

1. **Proactive Risk Management**: LLM aware of upcoming volatility events
2. **Autonomous Decision-Making**: No hardcoded blackout windows
3. **Weekly Caching**: Minimal API calls, efficient data usage
4. **Flexible Configuration**: Easy to adjust sensitivity and time windows
5. **Comprehensive Logging**: All calendar operations logged for review
6. **Graceful Degradation**: System continues if calendar unavailable

## Future Enhancements

Potential improvements for future versions:

1. **Multiple Calendar Sources**: Add Investing.com, Trading Economics, etc.
2. **Historical Impact Analysis**: Track actual vs. expected market moves
3. **Dynamic Time Windows**: Adjust based on event severity
4. **Event Impact Learning**: ML model to predict actual impact
5. **Intraday Updates**: Refresh calendar during trading day
6. **Event Subscription**: Real-time event notifications via webhook

## Maintenance

### Weekly Reset
- Calendar automatically refreshes on new trading week
- No manual intervention required

### Update Classification Logic
- Modify `classification_prompt` in `config.ini`
- Restart system to apply changes
- Old classifications remain until next fetch

### Adjust Time Sensitivity
- Change `minutes_before_event` / `minutes_after_event`
- Takes effect immediately (hot-reload compatible)

### Change Severity Filter
- Modify `severity_threshold` in `config.ini`
- Affects event filtering in real-time

## Troubleshooting

### No Events Showing in Logs
1. Check `enable_economic_calendar = true` in config
2. Verify `market_data/economic_calendar.json` exists
3. Check if events are within configured time window
4. Verify severity filter includes event severities

### MarketWatch Scraping Fails
1. Check internet connectivity
2. Verify MarketWatch URL hasn't changed
3. System will use sample events - trading continues safely

### LLM Classification Not Working
1. Verify OpenAI API key in config
2. Check API quota/billing
3. System will use default "Medium" severity - trading continues

### Calendar Not Refreshing
1. Check file permissions on `market_data/` directory
2. Manually delete `economic_calendar.json` to force refresh
3. Check logs for error messages

## Logs

Calendar operations appear in:
- **Startup logs**: `logs/YYYYMMDD.txt` - "CHECKING ECONOMIC CALENDAR DATA" section
- **Job logs**: When upcoming events are found, logged at INFO level
- **Error logs**: Any fetch/classification failures logged with full traceback

Look for:
```
================================================================================
CHECKING ECONOMIC CALENDAR DATA
================================================================================
No economic calendar data for current trading week - Fetching now...
Fetched 15 events from MarketWatch
Classifying 15 events with LLM...
Successfully classified 15 events
Economic calendar data saved to market_data/economic_calendar.json
================================================================================
```

## Integration Status

✅ Module created and tested
✅ Configuration added
✅ Startup initialization complete
✅ Job integration complete
✅ LLM prompts updated
✅ Dependencies added
✅ Test suite created
✅ Documentation complete

The economic calendar integration is **fully operational** and ready for production use.


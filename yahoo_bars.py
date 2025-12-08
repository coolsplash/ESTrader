"""
Yahoo Finance Bar Data Module for ES Futures Trading
Fetches 5-minute bars from Yahoo Finance as a fallback when TopStep API is unavailable.
Provides caching and incremental updates similar to TopStep bar handling.
"""

import yfinance as yf
import pandas as pd
import json
import os
import logging
from datetime import datetime, timedelta, timezone
import configparser

# Cache folder for Yahoo bars (separate from TopStep cache)
CACHE_FOLDER = 'cache/yahoo_bars'

def get_config():
    """Load config from config.ini."""
    config = configparser.ConfigParser()
    config.read('config.ini')
    return config

def fetch_yahoo_bars(ticker='ES=F', days=2, interval='5m'):
    """Fetch 5-minute bars from Yahoo Finance.
    
    Args:
        ticker: Yahoo Finance ticker (default 'ES=F' for ES futures)
        days: Number of days to fetch (default 2 for 24+ hour coverage)
        interval: Bar interval (default '5m')
    
    Returns:
        list: List of bar dicts with format {t, o, h, l, c, v} or empty list on error
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        logging.info(f"Fetching Yahoo Finance {ticker} {interval} bars from {start_date.date()} to {end_date.date()}")
        
        # Download data from Yahoo Finance
        data = yf.download(
            ticker, 
            start=start_date, 
            end=end_date, 
            interval=interval, 
            progress=False, 
            timeout=15
        )
        
        if data is None or data.empty:
            logging.warning(f"No Yahoo Finance data returned for {ticker}")
            return []
        
        # Flatten multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        
        # Convert DataFrame to list of bar dicts matching TopStep format
        bars = []
        for idx, row in data.iterrows():
            # Convert pandas Timestamp to ISO format string
            # Yahoo Finance returns timezone-aware timestamps
            if idx.tzinfo is None:
                # If no timezone, assume UTC
                ts = idx.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC
                ts = idx.astimezone(timezone.utc)
            
            bar = {
                't': ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                'o': float(row['Open']),
                'h': float(row['High']),
                'l': float(row['Low']),
                'c': float(row['Close']),
                'v': int(row['Volume']) if pd.notna(row['Volume']) else 0
            }
            bars.append(bar)
        
        logging.info(f"Successfully fetched {len(bars)} {interval} bars from Yahoo Finance")
        return bars
        
    except Exception as e:
        logging.error(f"Error fetching Yahoo Finance bars: {e}")
        return []


def get_cached_yahoo_bars(date_str):
    """Read cached Yahoo bars from cache/yahoo_bars/YYYYMMDD.json.
    
    Args:
        date_str: Date string in YYYYMMDD format
    
    Returns:
        dict: Cache data with keys {date, ticker, interval, bars, last_fetched} or None
    """
    try:
        cache_file = os.path.join(CACHE_FOLDER, f"{date_str}.json")
        
        if not os.path.exists(cache_file):
            logging.debug(f"No Yahoo cache file found for {date_str}")
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        logging.info(f"Loaded {len(cache_data.get('bars', []))} cached Yahoo bars from {cache_file}")
        return cache_data
        
    except Exception as e:
        logging.error(f"Error reading cached Yahoo bars: {e}")
        return None


def save_yahoo_bars_to_cache(date_str, bars, ticker='ES=F', interval='5m'):
    """Save Yahoo bars to cache file cache/yahoo_bars/YYYYMMDD.json.
    Merges new bars with existing bars (avoiding duplicates by timestamp).
    
    Args:
        date_str: Date string in YYYYMMDD format
        bars: List of bar dicts to add/merge
        ticker: Ticker symbol
        interval: Bar interval
    """
    try:
        os.makedirs(CACHE_FOLDER, exist_ok=True)
        cache_file = os.path.join(CACHE_FOLDER, f"{date_str}.json")
        
        # Read existing cache if it exists
        existing_bars = []
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    existing_cache = json.load(f)
                    existing_bars = existing_cache.get('bars', [])
                    logging.debug(f"Loaded {len(existing_bars)} existing Yahoo bars from cache")
            except Exception as e:
                logging.warning(f"Could not read existing Yahoo cache file, will overwrite: {e}")
                existing_bars = []
        
        # Merge bars - avoid duplicates by timestamp
        existing_timestamps = {bar['t'] for bar in existing_bars}
        new_count = 0
        for bar in bars:
            if bar['t'] not in existing_timestamps:
                existing_bars.append(bar)
                existing_timestamps.add(bar['t'])
                new_count += 1
        
        # Sort by timestamp to maintain chronological order
        existing_bars.sort(key=lambda x: x['t'])
        
        # Prepare cache data
        cache_data = {
            'date': date_str,
            'ticker': ticker,
            'interval': interval,
            'bars': existing_bars,
            'last_fetched': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        logging.info(f"Saved Yahoo cache: {len(existing_bars)} total bars ({new_count} new) to {cache_file}")
        
    except Exception as e:
        logging.error(f"Error saving Yahoo bars to cache: {e}")


def get_yahoo_bars_for_llm(num_bars=36, ticker='ES=F'):
    """Main function to get Yahoo Finance bars for LLM with smart caching.
    
    This function:
    1. Checks cache for today's bars (and yesterday for 24hr coverage)
    2. Fetches fresh bars from Yahoo Finance (always fetches to get latest)
    3. Merges and saves to cache
    4. Returns both raw bars and formatted data matching TopStep format
    
    Args:
        num_bars: Number of bars to return for context (default 36 = 3 hours of 5min bars)
        ticker: Yahoo Finance ticker (default 'ES=F')
    
    Returns:
        dict: {'bars': list of raw bar dicts, 'formatted': formatted text for LLM}
              Returns {'bars': [], 'formatted': ''} on error
    """
    try:
        # Get config for ticker if available
        config = get_config()
        ticker = config.get('MarketData', 'es_ticker', fallback=ticker)
        
        # Get today's and yesterday's date strings
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime("%Y%m%d")
        yesterday_str = yesterday.strftime("%Y%m%d")
        
        logging.info("=" * 60)
        logging.info("FETCHING YAHOO FINANCE BARS (FALLBACK)")
        logging.info("=" * 60)
        
        # Load cached bars for today and yesterday
        today_cache = get_cached_yahoo_bars(today_str)
        yesterday_cache = get_cached_yahoo_bars(yesterday_str)
        
        # Collect all existing cached bars
        all_cached_bars = []
        if yesterday_cache:
            all_cached_bars.extend(yesterday_cache.get('bars', []))
        if today_cache:
            all_cached_bars.extend(today_cache.get('bars', []))
        
        # Always fetch fresh data to get the latest bars
        # Yahoo Finance 5m data goes back ~60 days, we fetch 2 days for 24hr coverage
        fresh_bars = fetch_yahoo_bars(ticker=ticker, days=2, interval='5m')
        
        if not fresh_bars and not all_cached_bars:
            logging.warning("No Yahoo Finance bars available (fetch failed, no cache)")
            return {'bars': [], 'formatted': "\n[Yahoo Finance bar data unavailable]"}
        
        if fresh_bars:
            # Merge fresh bars with cached bars
            existing_timestamps = {bar['t'] for bar in all_cached_bars}
            for bar in fresh_bars:
                if bar['t'] not in existing_timestamps:
                    all_cached_bars.append(bar)
                    existing_timestamps.add(bar['t'])
            
            # Sort by timestamp
            all_cached_bars.sort(key=lambda x: x['t'])
            
            # Save to cache - split by date
            # Today's bars
            today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_utc = today_start.strftime("%Y-%m-%dT00:00:00.000Z")
            today_bars = [bar for bar in all_cached_bars if bar['t'] >= today_start_utc]
            if today_bars:
                save_yahoo_bars_to_cache(today_str, today_bars, ticker)
            
            # Yesterday's bars
            yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start_utc = yesterday_start.strftime("%Y-%m-%dT00:00:00.000Z")
            yesterday_bars = [bar for bar in all_cached_bars 
                           if bar['t'] >= yesterday_start_utc and bar['t'] < today_start_utc]
            if yesterday_bars:
                save_yahoo_bars_to_cache(yesterday_str, yesterday_bars, ticker)
        else:
            # Use cached bars if fetch failed
            logging.warning("Yahoo Finance fetch failed - using cached bars")
        
        # Return the most recent num_bars
        recent_bars = all_cached_bars[-num_bars:] if len(all_cached_bars) > num_bars else all_cached_bars
        
        logging.info(f"Returning {len(recent_bars)} Yahoo bars for LLM context")
        
        # Format bars for context (import format function from screenshot_uploader)
        formatted = format_yahoo_bars_for_context(recent_bars, num_bars)
        
        return {'bars': recent_bars, 'formatted': formatted}
        
    except Exception as e:
        logging.error(f"Error in get_yahoo_bars_for_llm: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {'bars': [], 'formatted': "\n[Error retrieving Yahoo Finance bar data]"}


def utc_to_eastern(utc_dt):
    """Convert UTC datetime to Eastern Time (handles DST).
    
    Args:
        utc_dt: UTC datetime (timezone-aware or naive assumed UTC)
    
    Returns:
        datetime: Eastern Time datetime
    """
    try:
        # Determine if DST is in effect (approximate - US DST rules)
        # DST: Second Sunday in March to First Sunday in November
        year = utc_dt.year
        
        # March: Second Sunday
        march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
        days_until_sunday = (6 - march_first.weekday()) % 7
        dst_start = march_first + timedelta(days=days_until_sunday + 7, hours=7)  # 2 AM ET = 7 AM UTC
        
        # November: First Sunday
        nov_first = datetime(year, 11, 1, tzinfo=timezone.utc)
        days_until_sunday = (6 - nov_first.weekday()) % 7
        dst_end = nov_first + timedelta(days=days_until_sunday, hours=6)  # 2 AM ET = 6 AM UTC (still in DST)
        
        # Ensure utc_dt is timezone-aware
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        
        # Check if in DST
        if dst_start <= utc_dt < dst_end:
            offset = timedelta(hours=-4)  # EDT
        else:
            offset = timedelta(hours=-5)  # EST
        
        return utc_dt + offset
    except:
        # Fallback to EST if calculation fails
        return utc_dt + timedelta(hours=-5)


def format_yahoo_bars_for_context(bars, num_bars=36):
    """Format Yahoo bars into readable table and analysis for LLM context.
    Matches the format used by TopStep bars for consistency.
    
    Args:
        bars: List of bar dicts with {t, o, h, l, c, v}
        num_bars: Number of most recent bars to include
    
    Returns:
        str: Formatted bar data and analysis
    """
    try:
        if not bars:
            return "\n[No Yahoo Finance bar data available]"
        
        # Take last N bars
        recent_bars = bars[-num_bars:] if len(bars) > num_bars else bars
        
        # Calculate metrics
        if len(recent_bars) < 2:
            metrics = {
                'trend': 'insufficient data',
                'avg_volume': 0,
                'swing_high': recent_bars[0]['h'] if recent_bars else 0,
                'swing_low': recent_bars[0]['l'] if recent_bars else 0,
                'recent_close': recent_bars[-1]['c'] if recent_bars else 0
            }
        else:
            highs = [bar['h'] for bar in recent_bars]
            lows = [bar['l'] for bar in recent_bars]
            closes = [bar['c'] for bar in recent_bars]
            volumes = [bar['v'] for bar in recent_bars]
            
            # Trend analysis
            mid_point = len(closes) // 2
            earlier_avg = sum(closes[:mid_point]) / mid_point if mid_point > 0 else closes[0]
            recent_avg = sum(closes[mid_point:]) / (len(closes) - mid_point)
            
            if recent_avg > earlier_avg * 1.001:
                trend = 'uptrend'
            elif recent_avg < earlier_avg * 0.999:
                trend = 'downtrend'
            else:
                trend = 'sideways'
            
            metrics = {
                'trend': trend,
                'avg_volume': sum(volumes) / len(volumes) if volumes else 0,
                'swing_high': max(highs),
                'swing_low': min(lows),
                'recent_close': closes[-1]
            }
        
        # Get current time in ET for context
        current_utc = datetime.now(timezone.utc)
        current_et = utc_to_eastern(current_utc)
        current_time_str = current_et.strftime("%H:%M ET")
        
        # Get most recent bar time
        most_recent_bar_time_str = "Unknown"
        data_delay_minutes = 0
        if recent_bars:
            try:
                last_bar_time = datetime.fromisoformat(recent_bars[-1]['t'].replace('Z', '+00:00'))
                last_bar_et = utc_to_eastern(last_bar_time)
                most_recent_bar_time_str = last_bar_et.strftime("%H:%M ET")
                
                # Calculate delay
                data_delay = current_utc - last_bar_time
                data_delay_minutes = int(data_delay.total_seconds() / 60)
            except:
                pass
        
        # Format bars table with delay warning
        context = f"\n\n*** YAHOO FINANCE DATA (FALLBACK) - MAY BE DELAYED 15-20 MINUTES ***\n"
        context += f"Current Time: {current_time_str} | Most Recent Bar: {most_recent_bar_time_str}"
        if data_delay_minutes > 0:
            context += f" ({data_delay_minutes} min ago)"
        context += f"\n\nRecent 5-Minute Bars (Last {len(recent_bars)} bars / {len(recent_bars)*5/60:.1f} hours):\n"
        context += "Time (ET)  Open      High      Low       Close     Volume\n"
        context += "-" * 65 + "\n"
        
        # Show last 10 bars in table to keep context manageable
        display_bars = recent_bars[-10:]
        for bar in display_bars:
            try:
                # Parse timestamp and convert to ET for display
                bar_time = datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
                et_time = utc_to_eastern(bar_time)
                time_str = et_time.strftime("%H:%M")
            except:
                time_str = "??:??"
            
            context += f"{time_str}     {bar['o']:<9.2f} {bar['h']:<9.2f} {bar['l']:<9.2f} {bar['c']:<9.2f} {bar['v']:>8,}\n"
        
        # Add analysis
        context += f"\nBar Analysis ({len(recent_bars)} bars):\n"
        context += f"- Trend: {metrics['trend'].title()}\n"
        context += f"- Volume: Average {metrics['avg_volume']:,.0f}\n"
        context += f"- Key Levels: Swing High {metrics['swing_high']:.2f}, Swing Low {metrics['swing_low']:.2f}\n"
        context += f"- Current Close: {metrics['recent_close']:.2f}\n"
        context += f"- NOTE: This is Yahoo Finance fallback data - prices may not reflect current market\n"
        
        return context
        
    except Exception as e:
        logging.error(f"Error formatting Yahoo bars for context: {e}")
        return "\n[Error formatting Yahoo Finance bar data]"


def main():
    """Main function for standalone testing."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("Yahoo Finance Bar Data Module - Test")
    print("=" * 70)
    
    # Test fetching bars
    result = get_yahoo_bars_for_llm(num_bars=36)
    
    print(f"\nFetched {len(result['bars'])} bars")
    print("\nFormatted output:")
    print(result['formatted'])
    
    # Show first and last bar
    if result['bars']:
        print(f"\nFirst bar: {result['bars'][0]}")
        print(f"Last bar: {result['bars'][-1]}")


if __name__ == "__main__":
    main()


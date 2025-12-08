"""
Yahoo Finance 1-Minute Bar Fetcher
Fetches 1-minute bars from Yahoo Finance for ES futures for a specific date.
Standalone script for historical data retrieval.

Usage:
    python fetch_yahoo_1m_bars.py                    # Fetch for default date (12/5/2025)
    python fetch_yahoo_1m_bars.py 2025-12-06         # Fetch for specific date
    python fetch_yahoo_1m_bars.py 2025-12-06 NQ=F    # Fetch for specific date and ticker
"""

import yfinance as yf
import pandas as pd
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# Output folder for 1-minute bar data
OUTPUT_FOLDER = 'cache/yahoo_1m_bars'

# Default settings
DEFAULT_DATE = '2025-12-05'
DEFAULT_TICKER = 'ES=F'


def utc_to_eastern(utc_dt):
    """Convert UTC datetime to Eastern Time (handles DST).
    
    Args:
        utc_dt: UTC datetime (timezone-aware or naive assumed UTC)
    
    Returns:
        datetime: Eastern Time datetime
    """
    try:
        year = utc_dt.year
        
        # DST: Second Sunday in March to First Sunday in November
        march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
        days_until_sunday = (6 - march_first.weekday()) % 7
        dst_start = march_first + timedelta(days=days_until_sunday + 7, hours=7)
        
        nov_first = datetime(year, 11, 1, tzinfo=timezone.utc)
        days_until_sunday = (6 - nov_first.weekday()) % 7
        dst_end = nov_first + timedelta(days=days_until_sunday, hours=6)
        
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        
        if dst_start <= utc_dt < dst_end:
            offset = timedelta(hours=-4)  # EDT
        else:
            offset = timedelta(hours=-5)  # EST
        
        return utc_dt + offset
    except:
        return utc_dt + timedelta(hours=-5)


def fetch_1m_bars(target_date, ticker='ES=F'):
    """Fetch 1-minute bars from Yahoo Finance for a specific date.
    
    Note: Yahoo Finance only provides 1-minute data for the last 7 days.
    
    Args:
        target_date: Date string in YYYY-MM-DD format or datetime object
        ticker: Yahoo Finance ticker (default 'ES=F' for ES futures)
    
    Returns:
        list: List of bar dicts with format {t, o, h, l, c, v} or empty list on error
    """
    try:
        # Parse target date
        if isinstance(target_date, str):
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
        else:
            target_dt = target_date
        
        # Yahoo Finance 1m data only available for last 7 days
        days_ago = (datetime.now() - target_dt).days
        if days_ago > 7:
            print(f"WARNING: Yahoo Finance only provides 1-minute data for the last 7 days.")
            print(f"         Requested date ({target_date}) is {days_ago} days ago.")
            print(f"         Will attempt to fetch, but may return empty data.")
        
        # Fetch from day before to day after to ensure we get full coverage
        start_date = target_dt - timedelta(days=1)
        end_date = target_dt + timedelta(days=2)
        
        print(f"Fetching Yahoo Finance {ticker} 1-minute bars...")
        print(f"Target date: {target_dt.strftime('%Y-%m-%d')}")
        print(f"Fetch range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Download data from Yahoo Finance
        data = yf.download(
            ticker, 
            start=start_date, 
            end=end_date, 
            interval='1m', 
            progress=True, 
            timeout=30
        )
        
        if data is None or data.empty:
            print(f"No Yahoo Finance 1-minute data returned for {ticker}")
            return []
        
        # Flatten multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        
        print(f"Downloaded {len(data)} total 1-minute bars")
        
        # Filter to only the target date
        # Convert target_dt to date for comparison
        target_date_only = target_dt.date()
        
        # Convert DataFrame to list of bar dicts
        bars = []
        for idx, row in data.iterrows():
            # Convert pandas Timestamp to UTC
            if idx.tzinfo is None:
                ts = idx.replace(tzinfo=timezone.utc)
            else:
                ts = idx.astimezone(timezone.utc)
            
            # Convert to ET for date filtering (market hours are in ET)
            et_time = utc_to_eastern(ts)
            
            # Filter to target date based on ET time
            if et_time.date() != target_date_only:
                continue
            
            bar = {
                't': ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                't_et': et_time.strftime("%Y-%m-%d %H:%M:%S ET"),
                'o': float(row['Open']),
                'h': float(row['High']),
                'l': float(row['Low']),
                'c': float(row['Close']),
                'v': int(row['Volume']) if pd.notna(row['Volume']) else 0
            }
            bars.append(bar)
        
        # Sort by timestamp
        bars.sort(key=lambda x: x['t'])
        
        print(f"Filtered to {len(bars)} bars for {target_date}")
        return bars
        
    except Exception as e:
        print(f"Error fetching Yahoo Finance 1-minute bars: {e}")
        import traceback
        traceback.print_exc()
        return []


def save_bars_to_file(bars, target_date, ticker):
    """Save bars to JSON file.
    
    Args:
        bars: List of bar dicts
        target_date: Date string in YYYY-MM-DD format
        ticker: Ticker symbol
    """
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        
        # Create filename
        date_str = target_date.replace('-', '')
        ticker_clean = ticker.replace('=', '_')
        filename = f"{ticker_clean}_1m_{date_str}.json"
        filepath = os.path.join(OUTPUT_FOLDER, filename)
        
        # Prepare data
        data = {
            'date': target_date,
            'ticker': ticker,
            'interval': '1m',
            'bar_count': len(bars),
            'fetched_at': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            'bars': bars
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        print(f"\nSaved {len(bars)} bars to: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"Error saving bars to file: {e}")
        return None


def save_bars_to_csv(bars, target_date, ticker):
    """Save bars to CSV file for easy analysis.
    
    Args:
        bars: List of bar dicts
        target_date: Date string in YYYY-MM-DD format
        ticker: Ticker symbol
    """
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        
        # Create filename
        date_str = target_date.replace('-', '')
        ticker_clean = ticker.replace('=', '_')
        filename = f"{ticker_clean}_1m_{date_str}.csv"
        filepath = os.path.join(OUTPUT_FOLDER, filename)
        
        # Convert to DataFrame and save
        df = pd.DataFrame(bars)
        df.to_csv(filepath, index=False)
        
        print(f"Saved CSV to: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"Error saving bars to CSV: {e}")
        return None


def print_summary(bars, ticker):
    """Print summary statistics for the bars."""
    if not bars:
        print("\nNo bars to summarize.")
        return
    
    print("\n" + "=" * 70)
    print(f"SUMMARY: {ticker} 1-Minute Bars")
    print("=" * 70)
    
    # Time range
    first_bar = bars[0]
    last_bar = bars[-1]
    print(f"Time Range (ET): {first_bar['t_et']} to {last_bar['t_et']}")
    print(f"Total Bars: {len(bars)}")
    
    # Price stats
    highs = [bar['h'] for bar in bars]
    lows = [bar['l'] for bar in bars]
    opens = [bar['o'] for bar in bars]
    closes = [bar['c'] for bar in bars]
    volumes = [bar['v'] for bar in bars]
    
    print(f"\nPrice Statistics:")
    print(f"  Open:  {opens[0]:.2f} (first bar)")
    print(f"  High:  {max(highs):.2f}")
    print(f"  Low:   {min(lows):.2f}")
    print(f"  Close: {closes[-1]:.2f} (last bar)")
    print(f"  Range: {max(highs) - min(lows):.2f} points")
    
    print(f"\nVolume Statistics:")
    print(f"  Total Volume: {sum(volumes):,}")
    print(f"  Avg Volume/Bar: {sum(volumes) / len(volumes):,.0f}")
    print(f"  Max Volume Bar: {max(volumes):,}")
    
    # Show first and last 5 bars
    print("\n" + "-" * 70)
    print("First 5 Bars:")
    print(f"{'Time (ET)':<22} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12}")
    for bar in bars[:5]:
        print(f"{bar['t_et']:<22} {bar['o']:>10.2f} {bar['h']:>10.2f} {bar['l']:>10.2f} {bar['c']:>10.2f} {bar['v']:>12,}")
    
    print("\n" + "-" * 70)
    print("Last 5 Bars:")
    print(f"{'Time (ET)':<22} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12}")
    for bar in bars[-5:]:
        print(f"{bar['t_et']:<22} {bar['o']:>10.2f} {bar['h']:>10.2f} {bar['l']:>10.2f} {bar['c']:>10.2f} {bar['v']:>12,}")
    
    print("=" * 70)


def main():
    """Main function."""
    print("=" * 70)
    print("Yahoo Finance 1-Minute Bar Fetcher")
    print("=" * 70)
    
    # Parse command line arguments
    target_date = DEFAULT_DATE
    ticker = DEFAULT_TICKER
    
    if len(sys.argv) >= 2:
        target_date = sys.argv[1]
    if len(sys.argv) >= 3:
        ticker = sys.argv[2]
    
    print(f"\nConfiguration:")
    print(f"  Target Date: {target_date}")
    print(f"  Ticker: {ticker}")
    print()
    
    # Fetch bars
    bars = fetch_1m_bars(target_date, ticker)
    
    if bars:
        # Print summary
        print_summary(bars, ticker)
        
        # Save to files
        save_bars_to_file(bars, target_date, ticker)
        save_bars_to_csv(bars, target_date, ticker)
    else:
        print("\nNo bars fetched. This could be because:")
        print("  1. The date is more than 7 days ago (Yahoo Finance limitation)")
        print("  2. The market was closed on that date")
        print("  3. Network/API error occurred")


if __name__ == "__main__":
    main()


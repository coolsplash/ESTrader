"""
Test script to fetch and parse EdgeClear holiday data.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_holidays
import logging
import configparser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

print("=" * 80)
print("EDGECLEAR HOLIDAY DATA TEST")
print("=" * 80)
print()

# Load config
config = configparser.ConfigParser()
config.read('config.ini')

openai_config = {
    'api_key': config.get('OpenAI', 'api_key', fallback=''),
    'api_url': config.get('OpenAI', 'api_url', fallback='https://api.openai.com/v1/chat/completions')
}

cme_url = config.get('MarketHolidays', 'cme_url', fallback='https://edgeclear.com/exchange-holiday-hours/')
data_file = config.get('MarketHolidays', 'data_file', fallback='market_data/market_holidays.json')

print(f"Fetching from: {cme_url}")
print()

# Test 1: Fetch raw HTML
print("TEST 1: Fetching raw HTML...")
try:
    html_content = market_holidays.fetch_cme_trading_hours("2025-11-27", cme_url)
    print(f"Success! Fetched {len(html_content)} bytes")
    
    # Check if we can find the Equities row
    if "Equities" in html_content:
        print("[OK] Found 'Equities' in HTML content")
    else:
        print("[FAIL] 'Equities' not found in HTML content")
    
    if "Thanksgiving" in html_content:
        print("[OK] Found 'Thanksgiving' in HTML content")
    else:
        print("[FAIL] 'Thanksgiving' not found in HTML content")
        
except Exception as e:
    print(f"Failed: {e}")
    sys.exit(1)

print()

# Test 2: Parse with LLM
print("TEST 2: Parsing with LLM...")
print("(This will use your OpenAI API key and log the full interaction)")
print()

week_start, week_end = market_holidays.get_current_trading_week()
print(f"Current trading week: {week_start} to {week_end}")
print()

try:
    holidays = market_holidays.fetch_and_parse_week(cme_url, openai_config)
    
    if holidays:
        print(f"Success! Parsed {len(holidays)} days")
        print()
        print("Parsed Holiday Data:")
        print("-" * 80)
        
        import json
        for day in holidays:
            print(json.dumps(day, indent=2))
            print()
        
        # Save to file
        if market_holidays.save_holiday_data(holidays, data_file):
            print(f"[OK] Data saved to {data_file}")
        else:
            print(f"[FAIL] Failed to save data")
    else:
        print("No data returned")
        
except Exception as e:
    print(f"Failed: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("TEST COMPLETE")
print("=" * 80)


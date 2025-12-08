"""
Market Holidays Module for ESTrader

Fetches CME Group trading hours for ES futures, processes them via LLM
for structured parsing, and provides holiday/early-close checking for trading decisions.

Author: ESTrader System
"""

import requests
from bs4 import BeautifulSoup
import json
import logging
import datetime
import os
from typing import List, Dict, Tuple, Optional


def get_current_trading_week() -> Tuple[datetime.date, datetime.date]:
    """
    Calculate current trading week boundaries.
    
    Trading week: Sunday 18:00 ET through Friday 17:00 ET
    For simplicity, we consider the calendar dates: Sunday through Friday
    
    Returns:
        tuple: (week_start_date, week_end_date) as datetime.date objects
    """
    now = datetime.datetime.now()
    
    # Get current day of week (0=Monday, 6=Sunday)
    weekday = now.weekday()
    
    # Calculate days to previous Sunday (trading week start)
    # If today is Sunday (6), days_to_sunday = 0
    # If today is Monday (0), days_to_sunday = 1
    # If today is Saturday (5), days_to_sunday = 6
    if weekday == 6:  # Sunday
        days_to_sunday = 0
    else:
        days_to_sunday = weekday + 1
    
    week_start = now.date() - datetime.timedelta(days=days_to_sunday)
    
    # Trading week ends on Friday (5 days after Sunday)
    week_end = week_start + datetime.timedelta(days=5)
    
    return week_start, week_end


def fetch_cme_trading_hours(date_str: str, cme_url: str) -> str:
    """
    Fetch holiday hours page (EdgeClear or CME).
    
    Args:
        date_str: Date in YYYY-MM-DD format (not used for EdgeClear static page)
        cme_url: URL to fetch (e.g., https://edgeclear.com/exchange-holiday-hours/)
        
    Returns:
        str: HTML content of the page
    """
    try:
        # For EdgeClear, use the URL directly (it's a static yearly calendar)
        logging.info(f"Fetching holiday hours from: {cme_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(cme_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        logging.info(f"Successfully fetched holiday data ({len(response.content)} bytes)")
        return response.text
        
    except requests.RequestException as e:
        logging.error(f"Error fetching holiday hours: {e}")
        raise


def parse_equities_hours_from_html(html_content: str, date: datetime.date) -> Optional[Dict]:
    """
    Fallback parser to extract Equities trading hours from EdgeClear HTML using BeautifulSoup.
    
    Args:
        html_content: HTML content from EdgeClear website
        date: Date to parse hours for
        
    Returns:
        dict: Parsed holiday info or None if not found
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for tables containing trading hours
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                
                # Look for Equities row
                if cells and len(cells) > 0:
                    first_cell_text = cells[0].get_text(strip=True)
                    
                    if 'Equities' in first_cell_text:
                        row_text = ' '.join([cell.get_text(strip=True) for cell in cells])
                        logging.info(f"Found Equities row: {row_text[:200]}...")
                        
                        # Check for closed/holiday indicators
                        if 'closed' in row_text.lower():
                            return {
                                'date': date.isoformat(),
                                'type': 'closed',
                                'open_time': None,
                                'close_time': None,
                                'notes': 'Market closed (holiday)'
                            }
                        
                        # IMPORTANT: This fallback parser cannot reliably detect date-specific
                        # early closes from the entire Equities row text. The row contains ALL
                        # holidays for the year, so keywords like "halt" or "close @" may refer
                        # to different dates. Default to normal trading hours - the LLM parser
                        # should handle specific holiday detection properly.
                        
                        # Normal trading day (safe default)
                        return {
                            'date': date.isoformat(),
                            'type': 'normal',
                            'open_time': '18:00',
                            'close_time': '17:00',
                            'notes': 'Normal trading hours (fallback parser)'
                        }
        
        logging.warning(f"Could not find Equities row in HTML for {date}")
        return None
        
    except Exception as e:
        logging.error(f"Error parsing HTML for Equities hours: {e}")
        return None


def extract_equities_table(html_content: str) -> Optional[str]:
    """
    Extract just the Equities row from the holiday schedule table.
    
    Args:
        html_content: Full HTML content from EdgeClear
        
    Returns:
        str: Extracted table HTML or None if not found
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all tables (don't filter by class since class name might vary)
        tables = soup.find_all('table')
        logging.info(f"Found {len(tables)} tables in HTML")
        
        for table in tables:
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                
                # Look for row where first column contains "Equities"
                if cells and len(cells) > 0:
                    first_cell_text = cells[0].get_text(strip=True).lower()
                    
                    if 'equities' in first_cell_text:
                        logging.info(f"Found Equities row in table")
                        # Return just this row's HTML
                        return str(row)
        
        logging.warning("Could not find Equities row in any table")
        return None
        
    except Exception as e:
        logging.error(f"Error extracting Equities table: {e}")
        return None


def parse_holidays_with_llm(html_content: str, week_start: datetime.date, 
                           week_end: datetime.date, openai_config: Dict) -> List[Dict]:
    """
    Send extracted Equities table to GPT for parsing into structured JSON with graceful fallback.
    
    Args:
        html_content: HTML content from EdgeClear website
        week_start: Start of trading week
        week_end: End of trading week
        openai_config: Dictionary with 'api_key' and 'api_url'
        
    Returns:
        list: Parsed holiday data for the week
    """
    try:
        logging.info(f"Parsing holiday data with LLM for week {week_start} to {week_end}...")
        
        # Extract just the Equities table row using BeautifulSoup
        equities_row = extract_equities_table(html_content)
        
        if not equities_row:
            logging.warning("Could not extract Equities table, using simple HTML parser fallback")
            # Fall through to the except block to use fallback parser
            raise Exception("Equities table not found")
        
        # Use the extracted row instead of full HTML
        html_snippet = equities_row
        logging.info(f"Extracted Equities row: {len(html_snippet)} bytes (vs {len(html_content)} bytes full page)")
        logging.debug(f"Equities row text preview: {html_snippet[:500]}")
        
        prompt = f"""Extract Equities futures trading hours from this table row.

The HTML below is the **Equities** row from EdgeClear's holiday schedule table.
The second column contains the trading schedule text for the week {week_start} to {week_end}.

FUTURES TRADING CONCEPT:
- Futures trade nearly 24/7 (Sunday 18:00 ET to Friday 17:00 ET)
- When a day shows ONLY "Close @ XX:XX CT", market was already open from previous day
- "Trading Halt @ XX:XX CT" then "Open @ XX:XX CT" = temporary pause and reopen
- If no open time listed for a day, set open_time to null

TIME CONVERSION (CRITICAL):
- EdgeClear shows Central Time (CT)
- Convert ALL times to Eastern Time (ET) by adding 1 hour
- Examples: 12:00 CT = 13:00 ET, 17:00 CT = 18:00 ET

Parse the schedule text and extract:
- Each day mentioned (e.g., "Wednesday, November 26", "Thursday, November 27", "Friday, November 28")
- Open times (if explicitly stated)
- Close times
- Special conditions (Trading Halt, Closed, early close)

Return JSON array (ET times in 24-hour format):
[
  {{
    "date": "2025-11-23",
    "type": "normal",
    "open_time": "18:00",
    "close_time": "17:00",
    "notes": "Sunday - Normal week start"
  }},
  {{
    "date": "2025-11-27",
    "type": "early_close",
    "open_time": "18:00",
    "close_time": "13:00",
    "notes": "Thanksgiving - Trading Halt @ 12:00 CT, Reopen @ 17:00 CT (18:00 ET)"
  }},
  {{
    "date": "2025-11-28",
    "type": "early_close",
    "open_time": null,
    "close_time": "13:15",
    "notes": "Black Friday - Close @ 12:15 CT (13:15 ET), already open from Thu"
  }}
]

Equities Row HTML:
{html_snippet}
"""
        
        # DEBUG: Log the full prompt being sent to LLM
        logging.info("=" * 80)
        logging.info("LLM PROMPT (Market Holidays Parsing)")
        logging.info("=" * 80)
        logging.info(f"Model: gpt-4o")
        logging.info(f"Temperature: 0.3")
        logging.info(f"Max Tokens: 2000")
        logging.info("-" * 80)
        logging.info(prompt)
        logging.info("=" * 80)
        
        # Call OpenAI API
        headers = {
            'Authorization': f"Bearer {openai_config['api_key']}",
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': 'gpt-4o',
            'messages': [
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': 0.3,
            'max_tokens': 2000
        }
        
        response = requests.post(
            openai_config['api_url'],
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        
        response_data = response.json()
        llm_response = response_data['choices'][0]['message']['content']
        
        # DEBUG: Log the full LLM response
        logging.info("=" * 80)
        logging.info("LLM RESPONSE (Market Holidays Parsing)")
        logging.info("=" * 80)
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Model Used: {response_data.get('model', 'unknown')}")
        logging.info(f"Finish Reason: {response_data['choices'][0].get('finish_reason', 'unknown')}")
        logging.info(f"Total Tokens: {response_data.get('usage', {}).get('total_tokens', 'unknown')}")
        logging.info("-" * 80)
        logging.info("Raw Response Content:")
        logging.info(llm_response)
        logging.info("=" * 80)
        
        # Parse JSON response
        # Extract JSON from response (handle markdown code blocks)
        if '```json' in llm_response:
            llm_response = llm_response.split('```json')[1].split('```')[0]
        elif '```' in llm_response:
            llm_response = llm_response.split('```')[1].split('```')[0]
        
        parsed_holidays = json.loads(llm_response.strip())
        
        logging.info(f"Successfully parsed {len(parsed_holidays)} days with LLM")
        return parsed_holidays
        
    except Exception as e:
        logging.error(f"Error parsing with LLM: {e}")
        logging.exception("Full traceback:")
        logging.warning("Falling back to simple HTML parsing...")
        
        # Graceful fallback: Parse each day using simple HTML parser
        fallback_data = []
        current_date = week_start
        
        while current_date <= week_end:
            parsed = parse_equities_hours_from_html(html_content, current_date)
            
            if parsed:
                fallback_data.append(parsed)
            else:
                # Default to normal if we can't determine
                fallback_data.append({
                    'date': current_date.isoformat(),
                    'type': 'normal',
                    'open_time': '18:00',
                    'close_time': '17:00',
                    'notes': 'Assumed normal (parsing failed)'
                })
            
            current_date += datetime.timedelta(days=1)
        
        logging.info(f"Fallback parser returned {len(fallback_data)} days")
        return fallback_data


def fetch_and_parse_week(cme_url: str, openai_config: Dict) -> List[Dict]:
    """
    Fetch and parse trading hours for the current week.
    
    Args:
        cme_url: CME trading hours URL
        openai_config: OpenAI API configuration
        
    Returns:
        list: Parsed holiday data for current trading week
    """
    week_start, week_end = get_current_trading_week()
    
    # Use middle of week (Wednesday) for fetching
    # CME website should show the full week's data
    fetch_date = week_start + datetime.timedelta(days=3)
    date_str = fetch_date.isoformat()
    
    try:
        # Fetch HTML
        html_content = fetch_cme_trading_hours(date_str, cme_url)
        
        # Parse with LLM (with fallback)
        holidays = parse_holidays_with_llm(html_content, week_start, week_end, openai_config)
        
        return holidays
        
    except Exception as e:
        logging.error(f"Error fetching/parsing week data: {e}")
        logging.exception("Full traceback:")
        
        # Return empty list on failure
        return []


def save_holiday_data(holidays: List[Dict], data_file: str) -> bool:
    """
    Save holiday data to JSON file.
    
    Args:
        holidays: List of holiday dictionaries
        data_file: Path to save JSON file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        week_start, week_end = get_current_trading_week()
        
        data = {
            'fetch_timestamp': datetime.datetime.now().isoformat(),
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'holidays': holidays
        }
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        
        with open(data_file, 'w') as f:
            json.dump(data, indent=2, fp=f)
        
        logging.info(f"Saved {len(holidays)} holiday entries to {data_file}")
        return True
        
    except Exception as e:
        logging.error(f"Error saving holiday data: {e}")
        logging.exception("Full traceback:")
        return False


def load_holiday_data(data_file: str) -> Dict:
    """
    Load cached holiday data from JSON file.
    
    Args:
        data_file: Path to JSON file
        
    Returns:
        dict: Holiday data with 'holidays', 'week_start', 'week_end', 'fetch_timestamp'
              Empty dict if file doesn't exist or is invalid
    """
    if not os.path.exists(data_file):
        logging.info(f"Holiday file not found: {data_file}")
        return {}
    
    try:
        with open(data_file, 'r') as f:
            data = json.load(f)
        
        logging.info(f"Loaded holiday data: {len(data.get('holidays', []))} entries")
        return data
        
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in holiday file: {e}")
        return {}
    except Exception as e:
        logging.error(f"Error loading holiday data: {e}")
        return {}


def has_current_week_data(data_file: str) -> bool:
    """
    Check if we have valid data for current trading week.
    
    Args:
        data_file: Path to JSON file
        
    Returns:
        bool: True if data exists and covers current week, False otherwise
    """
    data = load_holiday_data(data_file)
    
    if not data or 'holidays' not in data:
        return False
    
    try:
        # Get current trading week
        current_week_start, current_week_end = get_current_trading_week()
        
        # Get cached week boundaries
        cached_week_start = datetime.date.fromisoformat(data['week_start'])
        cached_week_end = datetime.date.fromisoformat(data['week_end'])
        
        # Check if cached data covers current week
        if cached_week_start == current_week_start and cached_week_end == current_week_end:
            logging.info(f"Holiday data valid for current week: {current_week_start} to {current_week_end}")
            return True
        else:
            logging.info(f"Holiday data outdated. Cached: {cached_week_start} to {cached_week_end}, Current: {current_week_start} to {current_week_end}")
            return False
            
    except Exception as e:
        logging.error(f"Error checking holiday data validity: {e}")
        return False


def is_market_holiday(dt: datetime.datetime, data_file: str) -> bool:
    """
    Check if given datetime falls on a market holiday (closed all day).
    
    Args:
        dt: Datetime to check
        data_file: Path to holiday data JSON file
        
    Returns:
        bool: True if market is closed (holiday), False otherwise
    """
    data = load_holiday_data(data_file)
    
    if not data or 'holidays' not in data:
        logging.warning("No holiday data available - assuming market is open")
        return False
    
    date_str = dt.date().isoformat()
    
    for holiday in data['holidays']:
        if holiday['date'] == date_str and holiday['type'] == 'closed':
            logging.info(f"Market holiday detected: {holiday.get('notes', 'Holiday')}")
            return True
    
    return False


def is_early_close_day(dt: datetime.date, data_file: str) -> bool:
    """
    Check if given date is an early close day.
    
    Args:
        dt: Date to check
        data_file: Path to holiday data JSON file
        
    Returns:
        bool: True if early close day, False otherwise
    """
    data = load_holiday_data(data_file)
    
    if not data or 'holidays' not in data:
        return False
    
    date_str = dt.isoformat()
    
    for holiday in data['holidays']:
        if holiday['date'] == date_str and holiday['type'] == 'early_close':
            return True
    
    return False


def get_close_time(dt: datetime.date, data_file: str) -> Optional[datetime.time]:
    """
    Get the close time for a specific date.
    
    Args:
        dt: Date to check
        data_file: Path to holiday data JSON file
        
    Returns:
        datetime.time: Close time, or None if not found or market closed
    """
    data = load_holiday_data(data_file)
    
    if not data or 'holidays' not in data:
        # Default to normal close time
        return datetime.time(17, 0)
    
    date_str = dt.isoformat()
    
    for holiday in data['holidays']:
        if holiday['date'] == date_str:
            if holiday['type'] == 'closed':
                return None  # Market closed all day
            
            close_time_str = holiday.get('close_time')
            if close_time_str:
                try:
                    # Parse time string (e.g., "17:00" or "13:00")
                    hour, minute = map(int, close_time_str.split(':'))
                    return datetime.time(hour, minute)
                except:
                    logging.error(f"Error parsing close_time: {close_time_str}")
    
    # Default to normal close if not found
    return datetime.time(17, 0)


def get_open_time(dt: datetime.date, data_file: str) -> Optional[datetime.time]:
    """
    Get the open time for a specific date.
    
    Args:
        dt: Date to check
        data_file: Path to holiday data JSON file
        
    Returns:
        datetime.time: Open time, or None if not found or market closed
    """
    data = load_holiday_data(data_file)
    
    if not data or 'holidays' not in data:
        # Default to normal open time (Sunday 18:00)
        return datetime.time(18, 0)
    
    date_str = dt.isoformat()
    
    for holiday in data['holidays']:
        if holiday['date'] == date_str:
            if holiday['type'] == 'closed':
                return None  # Market closed all day
            
            open_time_str = holiday.get('open_time')
            if open_time_str:
                try:
                    # Parse time string (e.g., "18:00")
                    hour, minute = map(int, open_time_str.split(':'))
                    return datetime.time(hour, minute)
                except:
                    logging.error(f"Error parsing open_time: {open_time_str}")
    
    # Default to normal open if not found
    return datetime.time(18, 0)


def refresh_holiday_data(cme_url: str, data_file: str, openai_config: Dict) -> bool:
    """
    Force refresh of holiday data.
    
    Args:
        cme_url: CME trading hours URL
        data_file: Path to save JSON file
        openai_config: OpenAI API configuration
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logging.info("Force refreshing market holiday data...")
        
        # Fetch and parse
        holidays = fetch_and_parse_week(cme_url, openai_config)
        
        if not holidays:
            logging.warning("No holiday data fetched, refresh aborted")
            return False
        
        # Save to file
        success = save_holiday_data(holidays, data_file)
        
        if success:
            logging.info("Holiday data refresh completed successfully")
        else:
            logging.error("Holiday data refresh failed during save")
        
        return success
        
    except Exception as e:
        logging.error(f"Error refreshing holiday data: {e}")
        logging.exception("Full traceback:")
        return False


if __name__ == "__main__":
    # Configure logging for standalone testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=== Market Holidays Module Test ===\n")
    
    # Test 1: Get current trading week
    week_start, week_end = get_current_trading_week()
    print(f"Current trading week: {week_start} to {week_end}\n")
    
    # Test 2: Create sample data for testing
    test_file = "market_data/market_holidays.json"
    print(f"Creating sample holiday data in {test_file}...")
    
    # Create sample holidays (Thanksgiving week 2025)
    sample_holidays = [
        {
            "date": "2025-11-23",
            "type": "normal",
            "open_time": "18:00",
            "close_time": "17:00",
            "notes": "Normal trading hours"
        },
        {
            "date": "2025-11-24",
            "type": "normal",
            "open_time": "18:00",
            "close_time": "17:00",
            "notes": "Normal trading hours"
        },
        {
            "date": "2025-11-25",
            "type": "normal",
            "open_time": "18:00",
            "close_time": "17:00",
            "notes": "Normal trading hours"
        },
        {
            "date": "2025-11-26",
            "type": "normal",
            "open_time": "18:00",
            "close_time": "17:00",
            "notes": "Normal trading hours"
        },
        {
            "date": "2025-11-27",
            "type": "closed",
            "open_time": None,
            "close_time": None,
            "notes": "Thanksgiving - Market Closed"
        },
        {
            "date": "2025-11-28",
            "type": "early_close",
            "open_time": "18:00",
            "close_time": "13:00",
            "notes": "Early close (1:00 PM ET)"
        }
    ]
    
    save_holiday_data(sample_holidays, test_file)
    
    # Test 3: Load and verify
    print("\nLoading holiday data...")
    loaded_data = load_holiday_data(test_file)
    print(f"Loaded {len(loaded_data.get('holidays', []))} entries\n")
    
    # Test 4: Check specific dates
    print("Testing holiday checks:")
    
    # Thanksgiving (closed)
    thanksgiving = datetime.datetime(2025, 11, 27, 10, 0)
    is_holiday = is_market_holiday(thanksgiving, test_file)
    print(f"  Nov 27, 2025 (Thanksgiving): Holiday = {is_holiday}")
    
    # Day after Thanksgiving (early close)
    day_after = datetime.date(2025, 11, 28)
    is_early = is_early_close_day(day_after, test_file)
    close_time = get_close_time(day_after, test_file)
    print(f"  Nov 28, 2025 (Black Friday): Early close = {is_early}, Close time = {close_time}")
    
    # Normal day
    normal_day = datetime.date(2025, 11, 24)
    is_early = is_early_close_day(normal_day, test_file)
    close_time = get_close_time(normal_day, test_file)
    print(f"  Nov 24, 2025 (Monday): Early close = {is_early}, Close time = {close_time}")
    
    print("\n=== Test Complete ===")


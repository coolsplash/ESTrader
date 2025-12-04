import time
import base64
import requests
from io import BytesIO
from PIL import ImageGrab  # For screenshots (part of Pillow)
import schedule  # For scheduling
import win32gui  # For finding window rectangles
import configparser
import datetime
import os
import threading
import pystray
from pystray import MenuItem as item
from PIL import Image
import json # Added for JSON parsing
import logging
import base64  # For Basic Auth
import win32ui
import win32con
import win32process
from ctypes import windll
import tkinter as tk
from tkinter import messagebox
import sys
import ctypes
import urllib.parse  # For Telegram URL encoding
import csv
from market_data import MarketDataAnalyzer
import economic_calendar
import market_holidays

# Supabase integration
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("Supabase package not installed - database logging disabled")

# psutil for process filtering
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

def get_eastern_utc_offset():
    """Get the current UTC offset for Eastern Time (handles EST/EDT).
    
    Returns:
        int: Hours to subtract from UTC to get Eastern Time (4 for EDT, 5 for EST)
    """
    # Check if we're in daylight saving time
    # DST in US: Second Sunday in March to First Sunday in November
    now = datetime.datetime.now()
    
    # Simple DST check for Eastern Time
    # March: Find second Sunday
    march_second_sunday = None
    for day in range(8, 15):  # Second Sunday is between 8th-14th
        if datetime.datetime(now.year, 3, day).weekday() == 6:  # Sunday
            march_second_sunday = datetime.datetime(now.year, 3, day, 2, 0)  # 2 AM
            break
    
    # November: Find first Sunday
    november_first_sunday = None
    for day in range(1, 8):  # First Sunday is between 1st-7th
        if datetime.datetime(now.year, 11, day).weekday() == 6:  # Sunday
            november_first_sunday = datetime.datetime(now.year, 11, day, 2, 0)  # 2 AM
            break
    
    # Check if current time is in DST period
    if march_second_sunday and november_first_sunday:
        is_dst = march_second_sunday <= now < november_first_sunday
    else:
        # Fallback: Rough estimation
        is_dst = 3 <= now.month <= 10
    
    return 4 if is_dst else 5  # EDT is UTC-4, EST is UTC-5

def utc_to_eastern(utc_dt):
    """Convert UTC datetime to Eastern Time.
    
    Args:
        utc_dt: datetime object in UTC
    
    Returns:
        datetime: Eastern Time datetime
    """
    offset_hours = get_eastern_utc_offset()
    return utc_dt - datetime.timedelta(hours=offset_hours)

def eastern_to_utc(et_dt):
    """Convert Eastern Time datetime to UTC.
    
    Args:
        et_dt: datetime object in Eastern Time
    
    Returns:
        datetime: UTC datetime
    """
    offset_hours = get_eastern_utc_offset()
    return et_dt + datetime.timedelta(hours=offset_hours)

def is_market_closed_weekly(market_closed_config):
    """Check if current time falls within weekly market closed periods.
    
    Args:
        market_closed_config: String format "DAY:HH:MM-HH:MM,DAY:HH:MM-HH:MM"
                             Day numbers: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 
                                         4=Friday, 5=Saturday, 6=Sunday
    
    Returns:
        tuple: (is_closed, reason) where is_closed is bool and reason is string
    """
    if not market_closed_config:
        return False, None
    
    now = datetime.datetime.now()
    current_day = now.weekday()  # 0=Monday, 6=Sunday
    current_time = now.time()
    
    try:
        # Parse the market_closed config
        # Format: DAY:HH:MM-HH:MM,DAY:HH:MM-HH:MM
        periods = market_closed_config.split(',')
        
        for period in periods:
            period = period.strip()
            if not period:
                continue
            
            # Split day from time range
            parts = period.split(':')
            if len(parts) < 3:
                logging.warning(f"Invalid market_closed format: {period}")
                continue
            
            day_num = int(parts[0])
            time_range = ':'.join(parts[1:])  # Rejoin in case of HH:MM:SS format
            
            # Check if current day matches
            if current_day == day_num:
                # Parse time range
                time_parts = time_range.split('-')
                if len(time_parts) != 2:
                    logging.warning(f"Invalid time range format: {time_range}")
                    continue
                
                start_time_str = time_parts[0].strip()
                end_time_str = time_parts[1].strip()
                
                # Parse times
                start_time = datetime.datetime.strptime(start_time_str, '%H:%M').time()
                end_time = datetime.datetime.strptime(end_time_str, '%H:%M').time()
                
                # Check if current time is within closed period
                if start_time <= current_time <= end_time:
                    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    reason = f"Market closed: {day_names[current_day]} {start_time_str}-{end_time_str}"
                    return True, reason
        
        return False, None
        
    except Exception as e:
        logging.error(f"Error checking weekly market closed periods: {e}")
        return False, None

def format_key_levels_for_prompt(key_levels):
    """Format key levels list into readable text for LLM prompt.
    
    Args:
        key_levels: List of dicts with keys 'price', 'type', 'reason', or JSON string
    
    Returns:
        str: Formatted text describing key levels
    """
    if not key_levels:
        return "No key levels currently tracked"
    
    try:
        # Parse if string
        if isinstance(key_levels, str):
            key_levels = json.loads(key_levels)
        
        if not key_levels or not isinstance(key_levels, list):
            return "No key levels currently tracked"
        
        # Format as bullet list
        formatted_lines = ["KEY LEVELS BEING TRACKED:"]
        for level in key_levels:
            if isinstance(level, dict):
                price = level.get('price', 'N/A')
                level_type = level.get('type', 'N/A')
                reason = level.get('reason', '')
                
                if reason:
                    formatted_lines.append(f"- {price} ({level_type}): {reason}")
                else:
                    formatted_lines.append(f"- {price} ({level_type})")
        
        return "\n".join(formatted_lines)
        
    except Exception as e:
        logging.error(f"Error formatting key levels: {e}")
        return "No key levels currently tracked"

def get_session_start_time():
    """Determine the 18:00 reference time for current trading session.
    
    ES futures sessions run 18:00 to 18:00 ET.
    - If current time < midnight: session started today at 18:00
    - If current time >= midnight: session started yesterday at 18:00
    
    Returns:
        datetime: Session start time (18:00 ET)
    """
    now = datetime.datetime.now()
    
    # If we're before midnight (00:00), session started today at 18:00
    if now.hour >= 18:
        session_start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        # After midnight but before 18:00 - session started yesterday at 18:00
        yesterday = now - datetime.timedelta(days=1)
        session_start = yesterday.replace(hour=18, minute=0, second=0, microsecond=0)
    
    return session_start

def get_session_start_balance(account_id):
    """Query Supabase for session start balance (first snapshot >= 18:00).
    
    Args:
        account_id: Account ID to query
    
    Returns:
        float: Session start balance, or None if not found
    """
    if not SUPABASE_CLIENT:
        logging.debug("Supabase not available - cannot query session start balance")
        return None
    
    try:
        session_start = get_session_start_time()
        logging.info(f"Querying session start balance for session beginning at {session_start}")
        
        # Query for first balance snapshot >= session start time
        response = SUPABASE_CLIENT.table('account_snapshots')\
            .select('balance')\
            .eq('account_id', str(account_id))\
            .gte('timestamp', session_start.isoformat())\
            .order('timestamp')\
            .limit(1)\
            .execute()
        
        if response.data and len(response.data) > 0:
            balance = float(response.data[0]['balance'])
            logging.info(f"Found session start balance: ${balance:,.2f}")
            return balance
        else:
            logging.info("No session start balance found in database")
            return None
            
    except Exception as e:
        logging.error(f"Error querying session start balance: {e}")
        return None

def save_balance_snapshot(account_id, balance, rpl=None):
    """Save account balance snapshot to Supabase.
    
    Args:
        account_id: Account ID
        balance: Current account balance
        rpl: Optional realized P&L for the session
    """
    if not SUPABASE_CLIENT:
        logging.debug("Supabase not available - skipping balance snapshot")
        return
    
    try:
        snapshot_data = {
            'account_id': str(account_id),
            'timestamp': datetime.datetime.now().isoformat(),
            'balance': float(balance),
            'daily_pnl': float(rpl) if rpl is not None else None
        }
        
        SUPABASE_CLIENT.table('account_snapshots').insert(snapshot_data).execute()
        logging.debug(f"Saved balance snapshot: ${balance:,.2f}, RPL: ${rpl:,.2f if rpl else 0:.2f}")
        
    except Exception as e:
        logging.error(f"Error saving balance snapshot (non-critical): {e}")

def calculate_session_rpl(current_balance, session_start_balance):
    """Calculate session realized profit/loss.
    
    Args:
        current_balance: Current account balance
        session_start_balance: Balance at session start (18:00)
    
    Returns:
        float: RPL (current - start)
    """
    if current_balance is None or session_start_balance is None:
        return 0.0
    
    return float(current_balance) - float(session_start_balance)

def get_active_trade_info():
    """Get the current active trade info from file.
    
    Returns:
        dict: {'order_id': int, 'entry_price': float, 'position_type': str, 'entry_timestamp': str} or None
    """
    try:
        trade_info_file = os.path.join('trades', 'active_trade.json')
        if os.path.exists(trade_info_file):
            with open(trade_info_file, 'r') as f:
                return json.load(f)
        return None
    except Exception as e:
        logging.error(f"Error reading active trade info: {e}")
        return None

def get_active_order_id():
    """Get the current active order ID from file."""
    info = get_active_trade_info()
    return info['order_id'] if info else None

def save_active_trade_info(order_id, entry_price, position_type, entry_timestamp=None, stop_loss=None, price_target=None, reasoning=None, size=None, stop_loss_order_id=None, take_profit_order_id=None):
    """Save the active trade info to file.
    
    Args:
        order_id: TopstepX order ID
        entry_price: Entry price
        position_type: 'long' or 'short'
        entry_timestamp: ISO timestamp of entry (defaults to now)
        stop_loss: Stop loss price (optional)
        price_target: Take profit price (optional)
        reasoning: Reasoning for entering the trade (optional)
        size: Number of contracts (optional)
        stop_loss_order_id: Order ID for the stop loss order (optional)
        take_profit_order_id: Order ID for the take profit order (optional)
    """
    try:
        trades_folder = 'trades'
        os.makedirs(trades_folder, exist_ok=True)
        trade_info_file = os.path.join(trades_folder, 'active_trade.json')
        trade_info = {
            'order_id': order_id,
            'entry_price': float(entry_price),
            'position_type': position_type,
            'entry_timestamp': entry_timestamp or datetime.datetime.now().isoformat()
        }
        
        # Add optional fields if provided
        if stop_loss is not None:
            trade_info['stop_loss'] = float(stop_loss)
        if price_target is not None:
            trade_info['price_target'] = float(price_target)
        if reasoning is not None:
            trade_info['reasoning'] = reasoning
        if size is not None:
            trade_info['size'] = int(size)
        if stop_loss_order_id is not None:
            trade_info['stop_loss_order_id'] = int(stop_loss_order_id)
        if take_profit_order_id is not None:
            trade_info['take_profit_order_id'] = int(take_profit_order_id)
        
        with open(trade_info_file, 'w') as f:
            json.dump(trade_info, f, indent=2)
        logging.info(f"Saved active trade info: {trade_info}")
    except Exception as e:
        logging.error(f"Error saving active trade info: {e}")

def clear_active_trade_info():
    """Clear the active trade info file."""
    try:
        trade_info_file = os.path.join('trades', 'active_trade.json')
        if os.path.exists(trade_info_file):
            os.remove(trade_info_file)
            logging.info("Cleared active trade info")
    except Exception as e:
        logging.error(f"Error clearing active trade info: {e}")

def determine_exit_type(exit_trade_order_id, stop_loss_order_id, take_profit_order_id):
    """Determine how a position was closed by matching the exit trade's order ID.
    
    Args:
        exit_trade_order_id: The orderId from the closing trade in trade history
        stop_loss_order_id: The stored stop loss order ID
        take_profit_order_id: The stored take profit order ID
        
    Returns:
        str: "STOP LOSS HIT", "TAKE PROFIT HIT", or "CLOSED" (for LLM/manual closes)
    """
    if exit_trade_order_id is None:
        return "CLOSED"
    
    # Convert to int for comparison (API may return strings)
    try:
        exit_id = int(exit_trade_order_id)
    except (ValueError, TypeError):
        exit_id = exit_trade_order_id
    
    if stop_loss_order_id is not None:
        try:
            sl_id = int(stop_loss_order_id)
            if exit_id == sl_id:
                return "STOP LOSS HIT"
        except (ValueError, TypeError):
            if exit_trade_order_id == stop_loss_order_id:
                return "STOP LOSS HIT"
    
    if take_profit_order_id is not None:
        try:
            tp_id = int(take_profit_order_id)
            if exit_id == tp_id:
                return "TAKE PROFIT HIT"
        except (ValueError, TypeError):
            if exit_trade_order_id == take_profit_order_id:
                return "TAKE PROFIT HIT"
    
    return "CLOSED"

def log_llm_interaction(request_prompt, response_text, action=None, entry_price=None, 
                        price_target=None, stop_loss=None, confidence=None, reasoning=None, context=None, waiting_for=None, key_levels=None, suggestion=None):
    """Log LLM request and response to daily CSV file.
    
    Args:
        request_prompt: The full prompt sent to the LLM
        response_text: The raw response from the LLM
        action: Parsed action from response (e.g., 'buy', 'sell', 'hold')
        entry_price: Parsed entry price
        price_target: Parsed price target
        stop_loss: Parsed stop loss
        confidence: Parsed confidence level
        reasoning: Parsed reasoning
        context: Market context used in the request
        waiting_for: Condition the LLM is waiting for before taking action
        key_levels: Key price levels being tracked (list of dicts or JSON string)
    """
    global LATEST_LLM_DATA
    
    try:
        log_folder = 'logs'
        os.makedirs(log_folder, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.datetime.now().strftime("%y%m%d")
        csv_file = os.path.join(log_folder, f"{today}_LLM.csv")
        
        # Store in global variable for immediate dashboard access
        # Convert key_levels to JSON string for storage
        key_levels_str = ''
        if key_levels:
            if isinstance(key_levels, str):
                key_levels_str = key_levels[:1000]
            else:
                key_levels_str = json.dumps(key_levels)[:1000]
        
        LATEST_LLM_DATA = {
            'date_time': timestamp,
            'request': request_prompt[:1000] if request_prompt else '',
            'response': response_text[:1000] if response_text else '',
            'action': action or '',
            'entry_price': entry_price or '',
            'price_target': price_target or '',
            'stop_loss': stop_loss or '',
            'confidence': confidence or '',
            'reasoning': reasoning[:500] if reasoning else '',
            'context': context[:500] if context else '',
            'waiting_for': waiting_for[:500] if waiting_for else '',
            'key_levels': key_levels_str,
            'suggestion': suggestion[:500] if suggestion else ''
        }
        
        # Check if file exists to determine if we need to write header
        file_exists = os.path.exists(csv_file)
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header if new file
            if not file_exists:
                writer.writerow([
                    'date_time', 'request', 'response', 'action', 'entry_price', 
                    'price_target', 'stop_loss', 'confidence', 'reasoning', 'context', 'waiting_for', 'key_levels'
                ])
            
            # Write the log entry
            writer.writerow([
                timestamp,
                LATEST_LLM_DATA['request'],
                LATEST_LLM_DATA['response'],
                LATEST_LLM_DATA['action'],
                LATEST_LLM_DATA['entry_price'],
                LATEST_LLM_DATA['price_target'],
                LATEST_LLM_DATA['stop_loss'],
                LATEST_LLM_DATA['confidence'],
                LATEST_LLM_DATA['reasoning'],
                LATEST_LLM_DATA['context'],
                LATEST_LLM_DATA['waiting_for'],
                LATEST_LLM_DATA['key_levels']
            ])
        
        logging.info(f"LLM interaction logged to {csv_file}")
        
        # Also log to Supabase if enabled (with FULL, untruncated data)
        if SUPABASE_CLIENT:
            try:
                # Convert key_levels to proper JSON for JSONB column
                key_levels_json = None
                if key_levels:
                    if isinstance(key_levels, str):
                        try:
                            key_levels_json = json.loads(key_levels)
                        except:
                            key_levels_json = key_levels  # Store as-is if not valid JSON
                    else:
                        key_levels_json = key_levels
                
                supabase_data = {
                    'account_id': TOPSTEP_CONFIG.get('account_id', ''),
                    'order_id': None,  # Will be set if available
                    'timestamp': datetime.datetime.now().isoformat(),
                    'request': request_prompt if request_prompt else '',  # Full prompt, not truncated
                    'response': response_text if response_text else '',  # Full response, not truncated
                    'action': action or '',
                    'entry_price': float(entry_price) if entry_price else None,
                    'price_target': float(price_target) if price_target else None,
                    'stop_loss': float(stop_loss) if stop_loss else None,
                    'confidence': int(confidence) if confidence else None,
                    'reasoning': reasoning if reasoning else '',  # Full reasoning, not truncated
                    'context': context if context else '',  # Full context, not truncated
                    'waiting_for': waiting_for if waiting_for else None,
                    'key_levels': key_levels_json  # JSONB column
                }
                SUPABASE_CLIENT.table('llm_interactions').insert(supabase_data).execute()
                logging.debug("LLM interaction logged to Supabase (full message, not truncated)")
            except Exception as supabase_error:
                logging.error(f"Error logging to Supabase (non-critical): {supabase_error}")
        
    except Exception as e:
        logging.error(f"Error logging LLM interaction: {e}")
        logging.exception("Full traceback:")

def log_trade_event(event_type, symbol, position_type, size, price, stop_loss=None, take_profit=None, 
                    reasoning=None, confidence=None, profit_loss=None, profit_loss_points=None, 
                    balance=None, market_context=None, order_id=None, entry_price=None):
    """Log a trade event to the monthly CSV file.
    
    Args:
        event_type: "ENTRY", "ADJUSTMENT", "HOLD", "SCALE", "CLOSE"
        symbol: Trading symbol (e.g., "ES")
        position_type: "long" or "short"
        size: Number of contracts
        price: Current price for this event
        stop_loss: Stop loss price
        take_profit: Take profit price
        reasoning: LLM reasoning
        confidence: LLM confidence (0-100)
        profit_loss: P&L in dollars
        profit_loss_points: P&L in points
        balance: Account balance after event
        market_context: Market context at time of event
        order_id: TopstepX order ID (required for ENTRY, retrieved from file for other events)
        entry_price: Original entry price (for calculating P&L on exit)
    
    Returns:
        int: The order_id used
    """
    try:
        # Get or use order ID
        if event_type == "ENTRY":
            if order_id is None:
                logging.error("No order ID provided for ENTRY event")
                order_id = "UNKNOWN"
        else:
            if order_id is None:
                order_id = get_active_order_id()
                if order_id is None:
                    logging.error("No active order ID found for non-ENTRY event")
                    order_id = "UNKNOWN"
        
        # Prepare timestamp info
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        date = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        # Create monthly CSV filename
        trades_folder = 'trades'
        os.makedirs(trades_folder, exist_ok=True)
        year_month = now.strftime("%Y_%m")
        csv_file = os.path.join(trades_folder, f"{year_month}.csv")
        
        # Check if file exists to determine if we need to write headers
        file_exists = os.path.exists(csv_file)
        
        # Prepare row data
        row = {
            'order_id': order_id,
            'timestamp': timestamp,
            'date': date,
            'time': time_str,
            'event_type': event_type,
            'symbol': symbol,
            'position_type': position_type,
            'size': size,
            'price': price,
            'entry_price': entry_price if entry_price else (price if event_type == "ENTRY" else ''),
            'stop_loss': stop_loss if stop_loss else '',
            'take_profit': take_profit if take_profit else '',
            'reasoning': reasoning if reasoning else '',
            'confidence': confidence if confidence else '',
            'profit_loss': profit_loss if profit_loss else '',
            'profit_loss_points': profit_loss_points if profit_loss_points else '',
            'balance': balance if balance else '',
            'success': 'TRUE' if profit_loss and float(profit_loss) > 0 else ('FALSE' if profit_loss else ''),
            'market_context': market_context if market_context else ''
        }
        
        # Write to CSV
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['order_id', 'timestamp', 'date', 'time', 'event_type', 'symbol', 'position_type', 
                         'size', 'price', 'entry_price', 'stop_loss', 'take_profit', 'reasoning', 'confidence',
                         'profit_loss', 'profit_loss_points', 'balance', 'success', 'market_context']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # Write header if new file
            if not file_exists:
                writer.writeheader()
            
            writer.writerow(row)
        
        logging.info(f"Logged {event_type} event to {csv_file}: order_id={order_id}, price={price}")
        
        # Also log to Supabase if enabled
        if SUPABASE_CLIENT:
            try:
                supabase_data = {
                    'account_id': TOPSTEP_CONFIG.get('account_id', ''),
                    'order_id': str(order_id),
                    'timestamp': timestamp,
                    'event_type': event_type,
                    'symbol': symbol,
                    'position_type': position_type,
                    'size': int(size),
                    'price': float(price) if price else None,
                    'entry_price': float(entry_price) if entry_price else None,
                    'stop_loss': float(stop_loss) if stop_loss else None,
                    'take_profit': float(take_profit) if take_profit else None,
                    'reasoning': reasoning if reasoning else None,
                    'confidence': int(confidence) if confidence else None,
                    'profit_loss': float(profit_loss) if profit_loss else None,
                    'profit_loss_points': float(profit_loss_points) if profit_loss_points else None,
                    'balance': float(balance) if balance else None,
                    'market_context': market_context[:1000] if market_context else None  # Truncate for database
                }
                SUPABASE_CLIENT.table('trades').insert(supabase_data).execute()
                logging.debug(f"Trade event also logged to Supabase: {event_type}")
            except Exception as supabase_error:
                logging.error(f"Error logging trade to Supabase (non-critical): {supabase_error}")
        
        # Clear trade info if position fully closed
        if event_type == "CLOSE":
            clear_active_trade_info()
            # Disable monitoring since position is closed
            disable_trade_monitoring("Position closed via log_trade_event")
        
        return order_id
        
    except Exception as e:
        logging.error(f"Error logging trade event: {e}")
        logging.exception("Full traceback:")
        return trade_id

def is_after_hours():
    """Check if current time is outside regular trading hours (RTH).
    
    Regular Trading Hours (RTH) for ES futures: 8:30 AM - 3:00 PM CT (9:30 AM - 4:00 PM ET)
    Any time outside this window is considered after-hours/electronic trading hours (ETH).
    
    Returns:
        bool: True if after hours, False if during RTH
    """
    current_time = datetime.datetime.now().time()
    
    # Regular Trading Hours (RTH): 8:30 AM - 3:00 PM CT
    rth_start = datetime.datetime.strptime("09:30", "%H:%M").time()
    rth_end = datetime.datetime.strptime("16:00", "%H:%M").time()
    
    # Check if we're outside RTH
    is_eth = current_time < rth_start or current_time >= rth_end
    
    return is_eth

def get_daily_context():
    """Read today's base market context from context/YYMMDD.txt file.
    
    This returns ONLY the original market data context from Yahoo Finance.
    LLM observations are retrieved separately via get_llm_observations() and
    passed as a separate parameter when formatting prompts.
    
    File structure:
    - context/YYMMDD.txt - Original market data (returned by this function)
    - context/YYMMDD_LLM.txt - LLM's observations (retrieved via get_llm_observations())
    
    Appends after-hours notice if trading outside RTH.
    
    Returns:
        str: The base context text, or empty string if file doesn't exist
    """
    try:
        context_folder = 'context'
        os.makedirs(context_folder, exist_ok=True)
        today = datetime.datetime.now().strftime("%y%m%d")
        
        # File paths
        llm_context_file = os.path.join(context_folder, f"{today}_LLM.txt")
        base_context_file = os.path.join(context_folder, f"{today}.txt")
        
        context = ""
        
        # Always try to load base context first (original market data)
        if os.path.exists(base_context_file):
            with open(base_context_file, 'r', encoding='utf-8') as f:
                context = f.read().strip()
                logging.info(f"Loaded base context from {base_context_file}")
        
        # If base context doesn't exist, generate it
        else:
            logging.info(f"No context file found for today")
            # Try to generate market context from Yahoo Finance data
            try:
                logging.info("Attempting to generate market context from Yahoo Finance data...")
                analyzer = MarketDataAnalyzer()
                context = analyzer.generate_market_context(force_refresh=True)
                
                # Check if data fetch failed
                if "Market data unavailable" in context:
                    # Data fetch failed - do NOT save error message to file
                    logging.error("Market data fetch failed - context file will not be created/updated")
                    # Try to use yesterday's context as fallback (read-only, don't save)
                    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%y%m%d")
                    yesterday_file = os.path.join(context_folder, f"{yesterday}.txt")
                    if os.path.exists(yesterday_file):
                        logging.warning(f"Using yesterday's context from {yesterday_file} as fallback")
                        with open(yesterday_file, 'r', encoding='utf-8') as f:
                            context = f.read()
                    else:
                        logging.error("No yesterday context available either - returning empty context")
                        return ""
                else:
                    # Data fetch successful - save the generated context
                    with open(base_context_file, 'w', encoding='utf-8') as f:
                        f.write(context)
                    logging.info(f"Generated and saved base market context to {base_context_file}")
            except Exception as e:
                logging.error(f"Could not generate market context: {e}")
                # Try yesterday's context as final fallback (read-only, don't save)
                yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%y%m%d")
                yesterday_file = os.path.join(context_folder, f"{yesterday}.txt")
                if os.path.exists(yesterday_file):
                    logging.warning(f"Exception occurred, using yesterday's context from {yesterday_file} as fallback")
                    with open(yesterday_file, 'r', encoding='utf-8') as f:
                        context = f.read()
                else:
                    logging.error("No yesterday context available - returning empty context")
                    return ""
        
        # Note: LLM observations are NOT merged here - they are passed separately 
        # to prompt formatting to avoid nested placeholder issues
        
        # Append after-hours notice if outside RTH
        if is_after_hours():
            context += "\n\n⚠️ PLEASE NOTE: THIS IS AFTER HOURS TRADING (Outside Regular Trading Hours 8:30 AM - 3:00 PM CT)"
            logging.info("After-hours notice appended to context")
        
        return context
        
    except Exception as e:
        logging.error(f"Error reading daily context: {e}")
        return ""

def get_llm_observations():
    """Get LLM's previous observations from context/YYMMDD_LLM.txt file.
    
    Returns:
        str: LLM observations or default message if file doesn't exist
    """
    try:
        context_folder = 'context'
        today = datetime.datetime.now().strftime("%y%m%d")
        llm_context_file = os.path.join(context_folder, f"{today}_LLM.txt")
        
        if os.path.exists(llm_context_file):
            with open(llm_context_file, 'r', encoding='utf-8') as f:
                observations = f.read().strip()
                logging.debug(f"Loaded LLM observations from {llm_context_file}")
                return observations
        else:
            logging.debug("No LLM context file found - using default message")
            return "No previous observations yet - first analysis of the day."
    except Exception as e:
        logging.error(f"Error reading LLM observations: {e}")
        return "Error loading previous observations."

def save_daily_context(new_context, old_context):
    """Save LLM's updated market context to context/YYMMDD_LLM.txt file.
    
    This preserves the original market data context in YYMMDD.txt and stores
    the LLM's evolving understanding separately in YYMMDD_LLM.txt.
    
    Only saves if the context has changed.
    
    Args:
        new_context: The new context from LLM response
        old_context: The context that was sent to LLM
    """
    try:
        # Only update if context changed
        if new_context == old_context:
            logging.debug("LLM context unchanged, not updating file")
            return
        
        context_folder = 'context'
        today = datetime.datetime.now().strftime("%y%m%d")
        llm_context_file = os.path.join(context_folder, f"{today}_LLM.txt")
        
        # Create folder if it doesn't exist
        os.makedirs(context_folder, exist_ok=True)
        
        # Write the LLM's updated context
        with open(llm_context_file, 'w', encoding='utf-8') as f:
            f.write(new_context)
        
        logging.info(f"Updated LLM context in {llm_context_file}")
        logging.debug(f"LLM context preview: {new_context[:100]}..." if len(new_context) > 100 else f"LLM context: {new_context}")
        
    except Exception as e:
        logging.error(f"Error saving LLM context: {e}")
        logging.exception("Full traceback:")

def reconcile_supabase_open_trades(topstep_config, enable_trading, auth_token):
    """Check Supabase for ENTRY events without matching CLOSE events and reconcile them.
    
    This function queries Supabase for open trades (ENTRY without CLOSE) and checks if they
    are still open in the API. If not, fetches trade history to log the closure.
    """
    if not SUPABASE_CLIENT or not enable_trading or not auth_token:
        return
    
    try:
        account_id = topstep_config.get('account_id', '')
        if not account_id:
            return
        
        # Query Supabase for ENTRY events without matching CLOSE events
        # Get the most recent ENTRY event that doesn't have a CLOSE with the same order_id
        response = SUPABASE_CLIENT.table('trades').select('*').eq('account_id', account_id).eq('event_type', 'ENTRY').order('timestamp', desc=True).limit(1).execute()
        
        if not response.data:
            logging.debug("No ENTRY events found in Supabase")
            return
        
        most_recent_entry = response.data[0]
        order_id = most_recent_entry.get('order_id')
        entry_timestamp = most_recent_entry.get('timestamp')
        
        # Check if there's a matching CLOSE event
        close_response = SUPABASE_CLIENT.table('trades').select('*').eq('order_id', order_id).eq('event_type', 'CLOSE').execute()
        
        if close_response.data and len(close_response.data) > 0:
            logging.debug(f"Order {order_id} already has CLOSE event - no reconciliation needed")
            return
        
        # No CLOSE event found - check if position still exists in API
        current_position_type = get_current_position(SYMBOL, topstep_config, enable_trading, auth_token)
        
        tracked_position = most_recent_entry.get('position_type')
        if tracked_position in ['long', 'short'] and current_position_type == 'none':
            logging.info(f"🔄 SUPABASE RECONCILIATION: Found unclosed {tracked_position} trade (order {order_id}) - fetching trade history")
            
            # Fetch trade history from entry time to now
            start_time = entry_timestamp if entry_timestamp else datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            
            trades = fetch_trade_results(account_id, topstep_config, enable_trading, auth_token, start_time, end_time)
            
            if trades and len(trades) > 0:
                # Find the closing trade
                entry_price = most_recent_entry.get('entry_price') or most_recent_entry.get('price')
                exit_trade = None
                
                for trade in reversed(trades):
                    trade_side = trade.get('side', 0)
                    if tracked_position == 'long' and trade_side == 1:
                        exit_trade = trade
                        break
                    elif tracked_position == 'short' and trade_side == 0:
                        exit_trade = trade
                        break
                
                if exit_trade:
                    exit_price = exit_trade.get('price')
                    exit_quantity = exit_trade.get('quantity', 1)
                    
                    # Calculate P&L
                    if tracked_position == 'long':
                        pnl_points = (exit_price - entry_price) if exit_price and entry_price else 0
                    else:
                        pnl_points = (entry_price - exit_price) if exit_price and entry_price else 0
                    
                    pnl_dollars = pnl_points * 50 * exit_quantity
                    
                    balance = get_account_balance(account_id, topstep_config, enable_trading, auth_token)
                    
                    logging.info(f"🔄 SUPABASE RECONCILED: {tracked_position} @ {exit_price}, P&L: ${pnl_dollars:+,.2f}")
                    
                    # Log CLOSE event
                    log_trade_event(
                        event_type='CLOSE',
                        symbol=SYMBOL,
                        position_type=tracked_position,
                        size=exit_quantity,
                        price=exit_price,
                        stop_loss=None,
                        take_profit=None,
                        reasoning="Position closed (detected via Supabase reconciliation - stop loss or take profit filled)",
                        confidence=None,
                        profit_loss=pnl_dollars,
                        profit_loss_points=pnl_points,
                        balance=balance,
                        market_context=None,
                        order_id=order_id,
                        entry_price=entry_price
                    )
                    
                    logging.info("✅ Supabase trade closure reconciled and logged")
                    
    except Exception as e:
        logging.error(f"Error in Supabase reconciliation: {e}")
        logging.exception("Full traceback:")

def reconcile_closed_trades(topstep_config, enable_trading, auth_token):
    """Reconcile trades that were closed via stop loss or take profit but not logged.
    
    Checks if we have an active trade in our tracking, verifies it still exists in API,
    and if closed, fetches trade history to log the closure details.
    
    Also queries Supabase for any ENTRY events without matching CLOSE events and reconciles them.
    """
    if not enable_trading or not auth_token:
        return
    
    # Get active trade from our local tracking
    trade_info = get_active_trade_info()
    if not trade_info:
        logging.debug("No active trade in local tracking to reconcile")
        return
    
    try:
        # Check if position still exists in API
        current_position_type = get_current_position(SYMBOL, topstep_config, enable_trading, auth_token)
        
        # If we think we have a position but API shows none, it was closed
        tracked_position = trade_info.get('position_type', 'none')
        if tracked_position in ['long', 'short'] and current_position_type == 'none':
            logging.info("🔄 RECONCILIATION: Position closed but not logged - fetching trade history")
            
            # Fetch trade history to find the close
            entry_timestamp = trade_info.get('entry_timestamp')
            if entry_timestamp:
                # Parse entry timestamp and fetch trades from then until now
                start_time = entry_timestamp  # Already in ISO format
                end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                # Fallback: fetch today's trades
                start_time = datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            
            trades = fetch_trade_results(
                topstep_config['account_id'],
                topstep_config,
                enable_trading,
                auth_token,
                start_time,
                end_time
            )
            
            if trades and len(trades) > 0:
                logging.info(f"Found {len(trades)} trades in history")
                
                # Look for exit trades (opposite side from our entry)
                order_id = trade_info.get('order_id')
                entry_price = trade_info.get('entry_price')
                
                # Find the most recent closing trade (opposite side)
                exit_trade = None
                for trade in reversed(trades):  # Start from most recent
                    # Check if this is an exit trade (opposite side)
                    trade_side = trade.get('side', 0)  # 0=buy, 1=sell
                    
                    # If we were long (buy entry), look for sell exit
                    # If we were short (sell entry), look for buy exit
                    if tracked_position == 'long' and trade_side == 1:  # Sell closes long
                        exit_trade = trade
                        break
                    elif tracked_position == 'short' and trade_side == 0:  # Buy closes short
                        exit_trade = trade
                        break
                
                if exit_trade:
                    # Extract exit details
                    exit_price = exit_trade.get('price')
                    exit_quantity = exit_trade.get('quantity', 1)
                    exit_time = exit_trade.get('timestamp', datetime.datetime.now().isoformat())
                    
                    # Calculate P&L
                    if tracked_position == 'long':
                        pnl_points = (exit_price - entry_price) if exit_price and entry_price else 0
                    else:  # short
                        pnl_points = (entry_price - exit_price) if exit_price and entry_price else 0
                    
                    pnl_dollars = pnl_points * 50 * exit_quantity  # ES: $50 per point
                    
                    # Get current balance
                    balance = get_account_balance(topstep_config['account_id'], topstep_config, enable_trading, auth_token)
                    
                    logging.info(f"🔄 RECONCILED CLOSE: {tracked_position} @ {exit_price}, P&L: ${pnl_dollars:+,.2f} ({pnl_points:+.2f} pts)")
                    
                    # Log the CLOSE event (updates both CSV and Supabase)
                    log_trade_event(
                        event_type='CLOSE',
                        symbol=SYMBOL,
                        position_type=tracked_position,
                        size=exit_quantity,
                        price=exit_price,
                        stop_loss=None,
                        take_profit=None,
                        reasoning="Position closed (detected via reconciliation - likely stop loss or take profit filled)",
                        confidence=None,
                        profit_loss=pnl_dollars,
                        profit_loss_points=pnl_points,
                        balance=balance,
                        market_context=None,
                        order_id=order_id,
                        entry_price=entry_price
                    )
                    
                    logging.info("✅ Trade closure reconciled and logged to CSV and Supabase")
                else:
                    logging.warning("Position closed but no exit trade found in history - clearing tracking")
                    clear_active_trade_info()
                    disable_trade_monitoring("Position closed but no exit found in API history")
            else:
                logging.warning("No trade history available for reconciliation - clearing tracking")
                clear_active_trade_info()
                disable_trade_monitoring("Position closed, no trade history")
                
    except Exception as e:
        logging.error(f"Error reconciling trades: {e}")
        logging.exception("Full traceback:")

def check_position_discrepancy(api_position_type, api_position_details):
    """Compare local tracking (active_trade.json) against actual API results.
    
    Args:
        api_position_type: Position type from API ('long', 'short', or 'none')
        api_position_details: Full position details dict from API (or None if no position)
    
    Returns:
        dict or None: Discrepancy details if mismatch found, None if everything matches
        {
            'type': 'full_close' | 'partial_close' | 'position_mismatch' | 'untracked_position',
            'local_position_type': str,
            'api_position_type': str,
            'local_quantity': int,
            'api_quantity': int,
            'local_entry_price': float,
            'api_entry_price': float
        }
    """
    try:
        # Get local tracking info
        trade_info = get_active_trade_info()
        
        # If no local tracking and no API position, everything matches
        if not trade_info and api_position_type == 'none':
            return None
        
        # SCENARIO: API shows position but we have no local tracking
        # This happens when: system restart, manual entry, or tracking lost
        if not trade_info and api_position_type in ['long', 'short']:
            logging.warning(f"🔄 DISCREPANCY: Untracked position detected!")
            logging.warning(f"   Local tracking: NO POSITION")
            logging.warning(f"   API shows: {api_position_type.upper()} position")
            
            # Extract API position details
            api_quantity = 0
            api_entry_price = 0
            if api_position_details:
                api_quantity = (
                    api_position_details.get('quantity', 0) or 
                    api_position_details.get('size', 0) or 
                    api_position_details.get('netQuantity', 0)
                )
                api_entry_price = (
                    api_position_details.get('entryPrice', 0) or 
                    api_position_details.get('averagePrice', 0) or 
                    api_position_details.get('avgPrice', 0) or
                    0
                )
            
            return {
                'type': 'untracked_position',
                'local_position_type': 'none',
                'api_position_type': api_position_type,
                'local_quantity': 0,
                'api_quantity': api_quantity,
                'local_entry_price': 0,
                'api_entry_price': api_entry_price
            }
        
        # Extract local tracking details
        local_position_type = trade_info.get('position_type', 'none') if trade_info else 'none'
        local_entry_price = trade_info.get('entry_price', 0) if trade_info else 0
        
        # For API position details
        api_quantity = 0
        api_entry_price = 0
        if api_position_details:
            # Extract quantity from various possible fields
            api_quantity = (
                api_position_details.get('quantity', 0) or 
                api_position_details.get('size', 0) or 
                api_position_details.get('netQuantity', 0)
            )
            # Extract entry price
            api_entry_price = (
                api_position_details.get('entryPrice', 0) or 
                api_position_details.get('averagePrice', 0) or 
                api_position_details.get('avgPrice', 0) or
                0
            )
        
        # SCENARIO 1: Full close - we think we have position but API shows none
        if local_position_type in ['long', 'short'] and api_position_type == 'none':
            logging.info(f"🔄 DISCREPANCY: Full position close detected")
            logging.info(f"   Local tracking: {local_position_type.upper()} position")
            logging.info(f"   API shows: NO POSITION")
            return {
                'type': 'full_close',
                'local_position_type': local_position_type,
                'api_position_type': api_position_type,
                'local_quantity': 0,  # We don't track quantity in active_trade.json
                'api_quantity': 0,
                'local_entry_price': local_entry_price,
                'api_entry_price': 0
            }
        
        # SCENARIO 2: Partial close - both have positions but quantities differ
        # Note: We don't currently track quantity in active_trade.json, so we can't detect this
        # This would require enhancing active_trade.json to include quantity
        
        # SCENARIO 3: Position type mismatch - different position types
        if local_position_type != api_position_type:
            # This shouldn't happen normally, but handle it
            logging.warning(f"🔄 DISCREPANCY: Position type mismatch")
            logging.warning(f"   Local tracking: {local_position_type}")
            logging.warning(f"   API shows: {api_position_type}")
            return {
                'type': 'position_mismatch',
                'local_position_type': local_position_type,
                'api_position_type': api_position_type,
                'local_quantity': 0,
                'api_quantity': api_quantity,
                'local_entry_price': local_entry_price,
                'api_entry_price': api_entry_price
            }
        
        # Everything matches
        return None
        
    except Exception as e:
        logging.error(f"Error checking position discrepancy: {e}")
        logging.exception("Full traceback:")
        return None

def correct_position_state(discrepancy, api_position_type, api_position_details, working_orders, 
                           topstep_config, enable_trading, auth_token):
    """Update all system state to match TRUE position from API.
    
    This function corrects the system's internal state when a discrepancy is detected between
    what we think we have (active_trade.json) and what the API actually shows.
    
    Args:
        discrepancy: Dict with discrepancy details from check_position_discrepancy()
        api_position_type: Current position type from API ('long', 'short', 'none')
        api_position_details: Full position details from API
        working_orders: Current working orders from API
        topstep_config: TopstepX configuration dict
        enable_trading: Whether trading is enabled
        auth_token: Authentication token for API calls
    
    Returns:
        bool: True if state was successfully corrected, False otherwise
    """
    global ACCOUNT_BALANCE, LAST_RECONCILIATION_TIME
    
    try:
        discrepancy_type = discrepancy.get('type')
        local_position_type = discrepancy.get('local_position_type')
        
        # Log the discrepancy clearly
        logging.info("="*80)
        logging.info("🔄 POSITION DISCREPANCY DETECTED - CORRECTING STATE")
        logging.info(f"Discrepancy Type: {discrepancy_type}")
        logging.info(f"Local tracking showed: {local_position_type}")
        logging.info(f"API actually shows: {api_position_type}")
        logging.info("="*80)
        
        # Handle different discrepancy types
        if discrepancy_type == 'full_close':
            # Position was closed - run existing reconciliation to log the closure
            logging.info("Running reconcile_closed_trades() to fetch and log exit details...")
            reconcile_closed_trades(topstep_config, enable_trading, auth_token)
            
            # Clear local tracking (reconcile_closed_trades should do this, but double-check)
            trade_info = get_active_trade_info()
            if trade_info:
                logging.info("Clearing active_trade.json after reconciliation")
                clear_active_trade_info()
        
        elif discrepancy_type == 'partial_close':
            # Partial close detected - update quantity in active_trade.json
            # Note: Current implementation doesn't track quantity in active_trade.json
            # For now, just log it
            logging.info("Partial close detected - not currently handled in active_trade.json")
            logging.info("System will continue with existing position tracking")
        
        elif discrepancy_type == 'untracked_position':
            # Position opened manually from broker - create tracking for it
            logging.info("📊 Untracked position detected - creating tracking for manually-opened position")
            
            if api_position_details:
                # Extract position details from API
                api_entry_price = api_position_details.get('average_price') or api_position_details.get('averagePrice') or api_position_details.get('entryPrice') or 0
                api_symbol = api_position_details.get('symbol', 'UNKNOWN')
                api_quantity = abs(api_position_details.get('quantity', 0) or api_position_details.get('size', 0))
                
                # Parse working orders to get stop loss and take profit
                contract_id = topstep_config.get('contract_id', '')
                order_info = parse_working_orders(working_orders, contract_id)
                current_stop_loss = order_info.get('stop_loss_price')
                current_take_profit = order_info.get('take_profit_price')
                current_stop_loss_order_id = order_info.get('stop_loss_order_id')
                current_take_profit_order_id = order_info.get('take_profit_order_id')
                
                # Try to get a real ID from the position data
                raw_position = api_position_details.get('rawPosition', {})
                order_id = (
                    raw_position.get('id') or 
                    raw_position.get('positionId') or 
                    raw_position.get('entryOrderId') or
                    api_position_details.get('id') or
                    api_position_details.get('positionId')
                )
                
                # Fall back to generated ID only if no real ID is available
                if not order_id:
                    order_id = f"DETECTED_{api_position_type.upper()}_{int(datetime.datetime.now().timestamp())}"
                    logging.info(f"No position ID found in API response, using generated ID: {order_id}")
                else:
                    logging.info(f"Using position ID from API: {order_id}")
                
                # Save active trade info
                entry_timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                save_active_trade_info(
                    order_id=order_id,
                    entry_price=api_entry_price,
                    position_type=api_position_type,
                    entry_timestamp=entry_timestamp,
                    stop_loss=current_stop_loss,
                    price_target=current_take_profit,
                    reasoning="Position opened manually from broker - detected by system",
                    size=api_quantity,
                    stop_loss_order_id=current_stop_loss_order_id,
                    take_profit_order_id=current_take_profit_order_id
                )
                
                logging.info(f"✅ Created tracking for {api_position_type.upper()} position @ {api_entry_price}")
                logging.info(f"   Stop Loss: {current_stop_loss}, Take Profit: {current_take_profit}")
                
                # Log ENTRY event to trade log and Supabase
                balance = get_account_balance(topstep_config['account_id'], topstep_config, enable_trading, auth_token)
                log_trade_event(
                    event_type='ENTRY',
                    symbol=api_symbol,
                    position_type=api_position_type,
                    size=api_quantity,
                    price=api_entry_price,
                    stop_loss=current_stop_loss,
                    take_profit=current_take_profit,
                    reasoning="Position opened manually from broker - detected by system",
                    confidence=None,
                    profit_loss=None,
                    profit_loss_points=None,
                    balance=balance,
                    market_context=None,
                    order_id=order_id,
                    entry_price=api_entry_price
                )
                
                # Update global position tracking
                global PREVIOUS_POSITION_TYPE
                PREVIOUS_POSITION_TYPE = api_position_type
                
                logging.info("✅ ENTRY event logged for manually-opened position")
            else:
                logging.warning("No API position details available - cannot create tracking")
        
        elif discrepancy_type == 'position_mismatch':
            # Unexpected position mismatch - update to match API
            logging.warning("Position mismatch - updating local tracking to match API")
            if api_position_type == 'none':
                clear_active_trade_info()
            else:
                # API shows a position we don't have tracked - this is unusual
                # Just log it for now, don't try to create tracking
                logging.warning("API shows position but we have no/different local tracking")
                logging.warning("This may indicate manual trading or system restart")
        
        # Query and update account balance
        logging.info("Querying account balance...")
        balance = get_account_balance(topstep_config['account_id'], topstep_config, enable_trading, auth_token)
        if balance is not None:
            ACCOUNT_BALANCE = balance
            logging.info(f"Account balance updated: ${balance:,.2f}")
        else:
            logging.warning("Could not retrieve account balance")
        
        # Update dashboard if visible
        try:
            update_dashboard_data()
            logging.info("Dashboard updated with corrected position state")
        except Exception as e:
            logging.debug(f"Dashboard update skipped: {e}")
        
        # Update reconciliation timestamp
        LAST_RECONCILIATION_TIME = datetime.datetime.now()
        
        logging.info("="*80)
        logging.info("✅ POSITION STATE CORRECTED - System now matches API reality")
        logging.info("="*80)
        
        return True
        
    except Exception as e:
        logging.error(f"Error correcting position state: {e}")
        logging.exception("Full traceback:")
        return False

def send_telegram_message(message, telegram_config):
    """Send a message to Telegram chat."""
    try:
        if not telegram_config or not telegram_config.get('api_key') or not telegram_config.get('chat_id'):
            logging.debug("Telegram config not available - skipping notification")
            return False
        
        api_key = telegram_config['api_key']
        chat_id = telegram_config['chat_id']
        
        url = f"https://api.telegram.org/bot{api_key}/sendMessage"
        
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'  # Enable HTML formatting
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        logging.info(f"Telegram notification sent successfully")
        return True
        
    except requests.exceptions.Timeout:
        logging.error("Telegram notification timed out")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram notification: {e}")
        return False
    except Exception as e:
        logging.error(f"Error sending Telegram notification: {e}")
        return False

def get_window_by_partial_title(partial_title, process_name=None):
    """Find a window handle by partial, case-insensitive title match, optionally filtered by process name.
    
    Uses smart prioritization to select the main application window over child windows/panels.
    
    Args:
        partial_title: Substring to search for in window title (case-insensitive)
        process_name: Optional process name to filter by (e.g., 'Bookmap.exe')
    
    Returns:
        Window handle (hwnd) or None if not found
    """
    def callback(hwnd, results):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if partial_title.lower() in title.lower():
                # Get process name if filtering is requested
                proc_name = None
                if process_name and PSUTIL_AVAILABLE:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        proc = psutil.Process(pid)
                        proc_name = proc.name()
                    except:
                        proc_name = "Unknown"
                
                # Get window properties for prioritization
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]
                    area = width * height
                    
                    # Check if this is a child window
                    parent = win32gui.GetParent(hwnd)
                    is_child = (parent != 0)
                    
                    # Get window style
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    # Check for main window characteristics
                    has_caption = bool(style & win32con.WS_CAPTION)
                    has_sysmenu = bool(style & win32con.WS_SYSMENU)
                    
                except:
                    area = 0
                    is_child = False
                    has_caption = False
                    has_sysmenu = False
                
                results.append({
                    'hwnd': hwnd,
                    'title': title,
                    'proc_name': proc_name,
                    'area': area,
                    'is_child': is_child,
                    'has_caption': has_caption,
                    'has_sysmenu': has_sysmenu,
                    'title_length': len(title)
                })
    
    results = []
    win32gui.EnumWindows(callback, results)
    
    if not results:
        logging.error(f"No window found matching title: '{partial_title}'")
        return None
    
    # Filter by process name if specified
    if process_name:
        if not PSUTIL_AVAILABLE:
            logging.warning("psutil not available - cannot filter by process name, using title match only")
        else:
            original_count = len(results)
            results = [r for r in results if r['proc_name'] and r['proc_name'].lower() == process_name.lower()]
            if len(results) < original_count:
                logging.info(f"Filtered {original_count} window(s) by process name '{process_name}' -> {len(results)} match(es)")
    
    if not results:
        logging.error(f"No window found matching title '{partial_title}' and process '{process_name}'")
        return None
    
    # Log all matches for debugging
    if len(results) > 1:
        logging.warning(f"Found {len(results)} matching windows:")
        for r in results:
            logging.warning(f"  - HWND={r['hwnd']}: '{r['title']}' "
                          f"(Size={r['area']}, Child={r['is_child']}, Caption={r['has_caption']}, SysMenu={r['has_sysmenu']})")
    
    # Sort by priority to select main window:
    # 1. Non-child windows first (parent=0)
    # 2. Windows with caption and system menu (main window characteristics)
    # 3. Larger windows (main windows are typically larger than panels)
    # 4. Shorter titles (child windows often have longer descriptive titles)
    results.sort(key=lambda r: (
        r['is_child'],              # False < True, so non-child windows first
        not r['has_caption'],       # Main windows have captions
        not r['has_sysmenu'],       # Main windows have system menu
        -r['area'],                 # Larger windows preferred (negative for descending)
        r['title_length']           # Shorter titles preferred
    ))
    
    selected = results[0]
    logging.info(f"Selected window: '{selected['title']}' (Process: {selected['proc_name'] or 'N/A'}, "
                f"HWND={selected['hwnd']}, Size={selected['area']}, Child={selected['is_child']})")
    
    return selected['hwnd']

def capture_screenshot(window_title=None, window_process_name=None, top_offset=0, bottom_offset=0, left_offset=0, right_offset=0, save_folder=None, enable_save_screenshots=False):
    """Capture the full screen or a specific window (by partial title) using Win32 PrintWindow without activating, apply offsets by cropping, save to folder if enabled, and return as base64-encoded string."""
    logging.info("Capturing screenshot.")
    if window_title:
        hwnd = get_window_by_partial_title(window_title, window_process_name)
        if not hwnd:
            logging.error(f"No window found matching partial title '{window_title}'{' and process ' + window_process_name if window_process_name else ''}.")
            raise ValueError(f"No window found matching partial title '{window_title}'{' and process ' + window_process_name if window_process_name else ''}.")
        logging.info(f"Window found: HWND={hwnd}, Title={win32gui.GetWindowText(hwnd)}")

        # Check if window is minimized and restore it without activating
        was_minimized = win32gui.IsIconic(hwnd)
        if was_minimized:
            logging.info("Window is minimized; restoring without activation.")
            # SW_SHOWNOACTIVATE (4) - Displays window without activating it
            win32gui.ShowWindow(hwnd, 4)
            time.sleep(0.5)  # Brief pause to allow window to restore

        # Get window dimensions after ensuring it's restored
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top

        logging.info(f"Window dimensions: {width}x{height}")

        # Check if offsets would result in invalid dimensions
        effective_width = width - left_offset - right_offset
        effective_height = height - top_offset - bottom_offset
        if effective_height <= 0:
            logging.error(f"Offsets result in invalid effective height: {effective_height} (original height: {height}, top_offset: {top_offset}, bottom_offset: {bottom_offset})")
            raise ValueError("Offsets result in invalid effective height.")
        if effective_width <= 0:
            logging.error(f"Offsets result in invalid effective width: {effective_width} (original width: {width}, left_offset: {left_offset}, right_offset: {right_offset})")
            raise ValueError("Offsets result in invalid effective width.")

        # Capture using Win32 PrintWindow (works without bringing to foreground)
        try:
            # Create device contexts
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            # Create bitmap
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)

            # Use PrintWindow to capture window content
            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)  # 3 = PW_RENDERFULLCONTENT
            
            if result == 0:
                logging.warning("PrintWindow returned 0, attempting fallback to BitBlt")
                # Fallback to BitBlt if PrintWindow fails
                saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)

            # Convert to PIL Image
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            screenshot = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )

            # Clean up
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)

            logging.info("Screenshot captured using PrintWindow")

            # Restore minimized state if it was originally minimized
            if was_minimized:
                logging.info("Re-minimizing window.")
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

        except Exception as e:
            # Make sure to restore minimized state even on error
            if was_minimized:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            logging.error(f"Error capturing window with PrintWindow: {e}")
            raise ValueError(f"Failed to capture window: {e}")

        # Apply crop for offsets
        if top_offset > 0 or bottom_offset > 0 or left_offset > 0 or right_offset > 0:
            screenshot = screenshot.crop((left_offset, top_offset, width - right_offset, height - bottom_offset))
            logging.info(f"Applied offsets: top={top_offset}, bottom={bottom_offset}, left={left_offset}, right={right_offset}")
    else:
        logging.info("Capturing full screen.")
        screenshot = ImageGrab.grab()  # Full screen; offsets not applied

    buffered = BytesIO()
    screenshot.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    # Save to file if folder specified and enabled
    if save_folder and enable_save_screenshots:
        os.makedirs(save_folder, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  # To avoid overwriting
        file_path = os.path.join(save_folder, f"screenshot_{timestamp}.png")
        screenshot.save(file_path)
        logging.info(f"Screenshot saved to {file_path}")

    return image_base64

def upload_to_llm(image_base64, prompt, model, enable_llm, api_url, api_key):
    """Upload the screenshot to OpenAI API with custom prompt and model, and get a response (or mock if disabled)."""
    try:
        # Safely log prompt (truncate if too long, handle Unicode errors)
        prompt_preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
        logging.info(f"Uploading screenshot with prompt: {prompt_preview}")
    except UnicodeEncodeError:
        logging.info("Uploading screenshot with prompt (contains special characters)")
    if not enable_llm:
        mock_response = '{"action": "mock_action", "price_target": 0, "stop_loss": 0, "reasoning": "Mock response for testing"}'
        logging.info(f"LLM upload disabled - Mock Response: {mock_response}")
        return mock_response

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
                ]
            }
        ]#,
        #"max_tokens": 300  # Adjust as needed
    }
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        logging.info(f"LLM Response: {content}")
        return content  # Return the response for parsing
    except Exception as e:
        logging.error(f"Error uploading to LLM: {e}")
        return None

def is_within_time_range(begin_time, end_time):
    """Check if current time is within the specified range."""
    now = datetime.datetime.now().time()
    begin = datetime.datetime.strptime(begin_time, "%H:%M").time()
    end = datetime.datetime.strptime(end_time, "%H:%M").time()
    return begin <= now <= end

def is_in_no_new_trades_window(no_new_trades_windows_str):
    """Check if current time is within any of the no-new-trades windows.
    
    Args:
        no_new_trades_windows_str: Comma-separated time ranges (e.g., "09:30-09:35,15:45-18:00")
        
    Returns:
        tuple: (is_blocked, window_str) - Whether trading is blocked and which window
    """
    if not no_new_trades_windows_str or no_new_trades_windows_str.strip() == '':
        return (False, None)
    
    current_time = datetime.datetime.now().time()
    
    # Parse comma-separated windows
    windows = [w.strip() for w in no_new_trades_windows_str.split(',') if w.strip()]
    
    for window in windows:
        try:
            # Parse start-end times
            if '-' not in window:
                logging.warning(f"Invalid no_new_trades_window format: '{window}' (expected HH:MM-HH:MM)")
                continue
            
            start_str, end_str = window.split('-', 1)
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            
            # Check if we're in this window (handle overnight windows)
            in_window = False
            if start_time < end_time:
                # Same-day window (e.g., 09:30 to 18:00)
                in_window = start_time <= current_time < end_time
            else:
                # Overnight window (e.g., 23:00 to 02:00)
                in_window = current_time >= start_time or current_time < end_time
            
            if in_window:
                return (True, window)
                
        except Exception as e:
            logging.error(f"Error parsing no_new_trades_window '{window}': {e}")
            continue
    
    return (False, None)

def get_next_active_interval(interval_schedule_str):
    """Get the next active time from interval_schedule.
    
    Args:
        interval_schedule_str: Comma-separated time ranges with intervals (e.g., "00:00-09:20=-1,09:32-15:45=45")
        
    Returns:
        datetime.time or None: The next active time, or None if no active period found
    """
    if not interval_schedule_str or interval_schedule_str.strip() == '':
        return None
    
    current_time = datetime.datetime.now().time()
    
    # Parse schedule
    schedule_parts = [s.strip() for s in interval_schedule_str.split(',') if s.strip()]
    
    active_periods = []
    for part in schedule_parts:
        try:
            if '=' not in part:
                continue
            
            time_range, interval = part.split('=', 1)
            interval_seconds = int(interval)
            
            # Skip disabled intervals
            if interval_seconds < 0:
                continue
            
            # Parse time range
            if '-' not in time_range:
                continue
            
            start_str, end_str = time_range.split('-', 1)
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            
            active_periods.append((start_time, end_time))
        except (ValueError, AttributeError) as e:
            logging.debug(f"Error parsing interval schedule part '{part}': {e}")
            continue
    
    if not active_periods:
        return None
    
    # Find next active period
    for start_time, end_time in sorted(active_periods):
        # If current time is before this period starts, return the start time
        if current_time < start_time:
            return start_time
        # If we're in this period, it's already active (shouldn't happen if called correctly)
        elif start_time <= current_time <= end_time:
            return None  # Already in active period
    
    # If we're past all periods today, return first period of tomorrow
    if active_periods:
        first_start = sorted(active_periods)[0][0]
        # Return tomorrow's time (will be displayed as HH:MM)
        return first_start
    
    return None

def is_in_disabled_interval(interval_schedule_str):
    """Check if current time is in a disabled interval (interval=-1).
    
    Args:
        interval_schedule_str: Comma-separated time ranges with intervals
        
    Returns:
        tuple: (is_disabled, next_active_time) - Whether in disabled interval and next active time
    """
    if not interval_schedule_str or interval_schedule_str.strip() == '':
        return (False, None)
    
    current_time = datetime.datetime.now().time()
    
    # Parse schedule
    schedule_parts = [s.strip() for s in interval_schedule_str.split(',') if s.strip()]
    
    in_disabled = False
    for part in schedule_parts:
        try:
            if '=' not in part:
                continue
            
            time_range, interval = part.split('=', 1)
            interval_seconds = int(interval)
            
            # Parse time range
            if '-' not in time_range:
                continue
            
            start_str, end_str = time_range.split('-', 1)
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            
            # Check if current time is in this range
            if start_time <= current_time <= end_time:
                if interval_seconds < 0:
                    # We're in a disabled interval
                    in_disabled = True
                    break
                else:
                    # We're in an active interval
                    return (False, None)
        except (ValueError, AttributeError) as e:
            logging.debug(f"Error parsing interval schedule part '{part}': {e}")
            continue
    
    if in_disabled:
        next_time = get_next_active_interval(interval_schedule_str)
        return (True, next_time)
    
    return (False, None)

def show_error_dialog(error_message, error_code):
    """Show Windows native error dialog with Continue/Exit options."""
    logging.critical("="*80)
    logging.critical(f"CRITICAL ERROR (Code {error_code}): {error_message}")
    logging.critical("Displaying Windows native error dialog to user...")
    logging.critical("="*80)
    
    # Play system error sound
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND)
    except:
        pass
    
    try:
        # Windows MessageBox constants
        # MB_YESNO = 4, MB_ICONERROR = 16, MB_SYSTEMMODAL = 0x1000, MB_TOPMOST = 0x40000
        # IDYES = 6, IDNO = 7
        
        message = (
            f"Trading Error (Code {error_code})\n\n"
            f"{error_message}\n\n"
            f"Do you want to continue running the program?\n\n"
            f"YES = Continue running\n"
            f"NO = Exit program"
        )
        
        logging.critical("Calling Windows MessageBoxW...")
        
        # Use MessageBoxW for proper Unicode support
        # 4 = MB_YESNO (Yes/No buttons)
        # 16 = MB_ICONERROR (Error icon)
        # 0x1000 = MB_SYSTEMMODAL (System modal - stays on top)
        result = ctypes.windll.user32.MessageBoxW(
            0,  # No parent window
            message, 
            "ESTrader - Trading Error", 
            4 | 16 | 0x1000  # MB_YESNO | MB_ICONERROR | MB_SYSTEMMODAL
        )
        
        logging.critical(f"MessageBox returned: {result}")
        
        if result == 6:  # IDYES - Continue
            logging.warning("User chose to CONTINUE after error code 2")
            logging.warning("Program continuing despite error code 2 - user override")
        else:  # IDNO (7) or dialog closed - Exit
            logging.critical("User chose to EXIT after error code 2")
            logging.critical("Program terminated due to trading error")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Error showing Windows MessageBox: {e}")
        logging.exception("Full traceback:")
        logging.critical("MessageBox failed - exiting program for safety")
        sys.exit(1)

def close_position(position_details, topstep_config, enable_trading, auth_token=None, execute_trades=False, telegram_config=None, reasoning=None, market_context=None):
    """Close the entire position by placing an opposite market order."""
    try:
        if not enable_trading:
            logging.info("Trading disabled - Would close position (mock)")
            return
        
        if not execute_trades:
            logging.info("Execute trades disabled - Would close position (mock)")
            return
        
        # Extract position information
        position_type = position_details.get('position_type')
        size = position_details.get('size', 0)
        symbol = position_details.get('symbol')
        avg_price = position_details.get('average_price')
        
        logging.info(f"=" * 80)
        logging.info(f"CLOSING POSITION")
        logging.info(f"Position Type: {position_type.upper()}")
        logging.info(f"Size: {size} contracts")
        logging.info(f"Symbol: {symbol}")
        logging.info(f"Entry Price: {avg_price}")
        logging.info(f"=" * 80)
        
        # Determine the side for closing: opposite of current position
        # If long, sell to close. If short, buy to close.
        if position_type == 'long':
            side = 1  # Ask (sell to close long)
            action_text = "SELL to close LONG"
        elif position_type == 'short':
            side = 0  # Bid (buy to close short)
            action_text = "BUY to close SHORT"
        else:
            logging.error(f"Invalid position type for closing: {position_type}")
            return
        
        # Build the close order payload
        account_id = topstep_config['account_id']
        contract_id = topstep_config['contract_id']
        
        payload = {
            "accountId": int(account_id),
            "contractId": contract_id,
            "type": 2,  # Market order for immediate execution
            "side": side,
            "size": int(size)  # Close the entire position
        }
        
        logging.info(f"Placing CLOSE order: {action_text}")
        logging.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        # Place the order
        base_url = topstep_config['base_url']
        endpoint = topstep_config['buy_endpoint']  # Same endpoint for buy/sell
        url = base_url + endpoint
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {auth_token}'
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response_data = response.json()
        
        logging.info(f"Close Order Response (Status {response.status_code}):")
        logging.info(json.dumps(response_data, indent=2))
        
        # Check for errors
        if not response_data.get('success', True):
            error_code = response_data.get('errorCode', 0)
            error_message = response_data.get('errorMessage', 'Unknown error')
            logging.error(f"Failed to close position: {error_message} (Code: {error_code})")
            
            # Handle critical error code 2
            if error_code == 2:
                show_error_dialog(error_message, error_code)
        else:
            logging.info(f"Position CLOSED successfully!")
            
            # Get updated account balance
            balance = get_account_balance(account_id, topstep_config, True, auth_token)
            
            # Get trade info to fetch actual P&L from API
            trade_info = get_active_trade_info()
            
            # Fetch actual trade results from API
            net_pnl = None
            total_fees = None
            pnl_points = None
            entry_price = None
            
            if trade_info:
                entry_price = trade_info.get('entry_price')
                entry_timestamp = trade_info.get('entry_timestamp')
                
                # Fetch trade results from API
                if entry_timestamp:
                    start_time = entry_timestamp
                else:
                    # Fallback to today's start if no timestamp
                    start_time = datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                
                end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                
                trades = fetch_trade_results(
                    account_id,
                    topstep_config,
                    True,
                    auth_token,
                    start_time,
                    end_time
                )
                
                if trades:
                    # Calculate net P&L from all fills
                    total_pnl = sum(trade.get('profitAndLoss', 0) for trade in trades)
                    total_fees = sum(trade.get('fees', 0) for trade in trades)
                    net_pnl = total_pnl - total_fees
                    
                    # Calculate P&L in points (assuming ES multiplier of $50 per point)
                    pnl_points = net_pnl / 50 if net_pnl else 0
                    
                    logging.info(f"Fetched actual trade results: Net P&L=${net_pnl:.2f}, Fees=${total_fees:.2f}, Points={pnl_points:+.2f}")
            
            # Log CLOSE event to CSV with actual P&L
            log_trade_event(
                event_type="CLOSE",
                symbol=symbol,
                position_type=position_type,
                size=size,
                price=0,  # Exit price not available from close order
                reasoning=reasoning,
                profit_loss=net_pnl,
                profit_loss_points=pnl_points,
                balance=balance,
                market_context=market_context,
                order_id=trade_info.get('order_id') if trade_info else None,
                entry_price=entry_price
            )
            
            # Build Telegram notification with P&L
            is_success = net_pnl > 0 if net_pnl is not None else None
            emoji = "✅" if is_success else "❌" if is_success is False else "🔴"
            result_text = "PROFIT" if is_success else "LOSS" if is_success is False else "CLOSED"
            
            telegram_msg = (
                f"{emoji} <b>POSITION {result_text}</b>\n"
                f"Type: {position_type.upper()}\n"
                f"Size: {size} contract(s)\n"
                f"Symbol: {symbol}\n"
            )
            
            if entry_price:
                telegram_msg += f"Entry Price: {entry_price}\n"
            
            if net_pnl is not None:
                telegram_msg += f"P&L: ${net_pnl:+,.2f} ({pnl_points:+.2f} pts)\n"
            
            if total_fees is not None:
                telegram_msg += f"Fees: ${total_fees:.2f}\n"
            
            if balance is not None:
                telegram_msg += f"💰 Balance: ${balance:,.2f}\n"
            
            if reasoning:
                telegram_msg += f"📝 Reason: {reasoning}\n"
            
            telegram_msg += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            send_telegram_message(telegram_msg, telegram_config)
            logging.info(f"Telegram notification sent for position CLOSE with P&L results")
            
    except Exception as e:
        logging.error(f"Error closing position: {e}")
        logging.exception("Full traceback:")

def parse_working_orders(working_orders, contract_id):
    """Parse working orders to extract stop loss and take profit order IDs and prices.
    
    Returns:
        dict: {
            'stop_loss_order_id': int or None,
            'stop_loss_price': float or None,
            'take_profit_order_id': int or None,
            'take_profit_price': float or None
        }
    """
    result = {
        'stop_loss_order_id': None,
        'stop_loss_price': None,
        'take_profit_order_id': None,
        'take_profit_price': None
    }
    
    if not working_orders:
        return result
    
    # Extract orders list from response
    orders_list = []
    if isinstance(working_orders, list):
        orders_list = working_orders
    elif isinstance(working_orders, dict) and 'orders' in working_orders:
        orders_list = working_orders.get('orders', [])
    
    # Find stop loss and take profit orders for this contract
    for order in orders_list:
        if not isinstance(order, dict):
            continue
        
        order_contract_id = order.get('contractId')
        order_type = order.get('type')
        order_id = order.get('id')
        
        # Match contract and identify order type
        if order_contract_id == contract_id:
            if order_type == 4:  # Stop loss
                result['stop_loss_order_id'] = order_id
                result['stop_loss_price'] = order.get('stopPrice')
                logging.info(f"Found stop loss order ID: {order_id}, Price: {result['stop_loss_price']}")
            elif order_type == 1:  # Take profit (limit order)
                result['take_profit_order_id'] = order_id
                result['take_profit_price'] = order.get('limitPrice')
                logging.info(f"Found take profit order ID: {order_id}, Price: {result['take_profit_price']}")
    
    return result

def modify_stops_and_targets(position_details, new_price_target, new_stop_loss, topstep_config, enable_trading, auth_token=None, execute_trades=False, position_type='none', working_orders=None, reasoning=None, market_context=None):
    """Modify existing stop loss and take profit orders using /api/Order/modify endpoint."""
    try:
        if not enable_trading:
            logging.info("Trading disabled - Would modify stops/targets (mock)")
            return
        
        if not execute_trades:
            logging.info("Execute trades disabled - Would modify stops/targets (mock)")
            return
        
        if not auth_token:
            logging.error("No auth token available for modifying orders")
            return
        
        # Extract position information
        size = position_details.get('size', 0)
        symbol = position_details.get('symbol')
        avg_price = position_details.get('average_price')
        
        logging.info(f"=" * 80)
        logging.info(f"MODIFYING STOPS & TARGETS")
        logging.info(f"Position Type: {position_type.upper()}")
        logging.info(f"Size: {size} contracts")
        logging.info(f"Symbol: {symbol}")
        logging.info(f"Entry Price: {avg_price}")
        logging.info(f"New Price Target: {new_price_target}")
        logging.info(f"New Stop Loss: {new_stop_loss}")
        logging.info(f"=" * 80)
        
        # Get configuration
        account_id = topstep_config['account_id']
        contract_id = topstep_config['contract_id']
        base_url = topstep_config['base_url']
        modify_order_endpoint = topstep_config.get('modify_order_endpoint', '/api/Order/modify')
        
        # Validate price data
        if not new_price_target or not new_stop_loss:
            logging.warning("Missing price data for modifying stops/targets")
            return
        
        # Parse working orders to get order IDs
        if not working_orders:
            logging.warning("No working orders provided - cannot modify stops/targets")
            return
        
        order_ids = parse_working_orders(working_orders, contract_id)
        stop_loss_order_id = order_ids.get('stop_loss_order_id')
        take_profit_order_id = order_ids.get('take_profit_order_id')
        current_stop_loss = order_ids.get('stop_loss_price')
        current_take_profit = order_ids.get('take_profit_price')
        
        # Check if values actually changed (tolerance for floating point comparison)
        tolerance = 0.01
        stop_changed = False
        target_changed = False
        
        if current_stop_loss and new_stop_loss:
            stop_changed = abs(float(current_stop_loss) - float(new_stop_loss)) > tolerance
        
        if current_take_profit and new_price_target:
            target_changed = abs(float(current_take_profit) - float(new_price_target)) > tolerance
        
        values_changed = stop_changed or target_changed
        
        logging.info(f"Current values - Stop: {current_stop_loss}, Target: {current_take_profit}")
        logging.info(f"New values - Stop: {new_stop_loss}, Target: {new_price_target}")
        logging.info(f"Values changed: Stop={stop_changed}, Target={target_changed}, Overall={values_changed}")
        
        # Set up headers for modify requests
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json'
        }
        
        modify_url = base_url + modify_order_endpoint
        
        # Only modify orders if values actually changed
        if not values_changed:
            logging.info("Stop loss and price target unchanged - skipping broker modifications")
        else:
            logging.info("Values changed - proceeding with broker modifications")
        
        # Modify stop loss order if order ID found AND value changed
        if stop_loss_order_id and new_stop_loss and stop_changed:
            stop_loss_payload = {
                "accountId": int(account_id),
                "orderId": int(stop_loss_order_id),
                "stopPrice": float(new_stop_loss)
            }
            
            logging.info(f"Modifying stop loss order ID {stop_loss_order_id} to price {new_stop_loss}")
            logging.info(f"Modify URL: {modify_url}")
            logging.info(f"Stop Loss Payload: {json.dumps(stop_loss_payload, indent=2)}")
            
            try:
                sl_response = requests.post(modify_url, headers=headers, json=stop_loss_payload, timeout=10)
                sl_response_data = sl_response.json()
                
                logging.info(f"Stop loss modify response: {json.dumps(sl_response_data, indent=2)}")
                
                if sl_response_data.get('success', True):
                    logging.info(f"Successfully modified stop loss to {new_stop_loss}")
                else:
                    error_msg = sl_response_data.get('errorMessage', 'Unknown error')
                    error_code = sl_response_data.get('errorCode', 0)
                    logging.error(f"Failed to modify stop loss: {error_msg}")
                    if error_code == 2:
                        show_error_dialog(error_msg, error_code)
                        
            except Exception as e:
                logging.error(f"Error modifying stop loss order: {e}")
                logging.exception("Full traceback:")
        else:
            if not stop_loss_order_id:
                logging.warning("No stop loss order ID found - cannot modify")
        
        # Modify take profit order if order ID found AND value changed
        if take_profit_order_id and new_price_target and target_changed:
            take_profit_payload = {
                "accountId": int(account_id),
                "orderId": int(take_profit_order_id),
                "limitPrice": float(new_price_target)
            }
            
            logging.info(f"Modifying take profit order ID {take_profit_order_id} to price {new_price_target}")
            logging.info(f"Modify URL: {modify_url}")
            logging.info(f"Take Profit Payload: {json.dumps(take_profit_payload, indent=2)}")
            
            try:
                tp_response = requests.post(modify_url, headers=headers, json=take_profit_payload, timeout=10)
                tp_response_data = tp_response.json()
                
                logging.info(f"Take profit modify response: {json.dumps(tp_response_data, indent=2)}")
                
                if tp_response_data.get('success', True):
                    logging.info(f"Successfully modified take profit to {new_price_target}")
                else:
                    error_msg = tp_response_data.get('errorMessage', 'Unknown error')
                    error_code = tp_response_data.get('errorCode', 0)
                    logging.error(f"Failed to modify take profit: {error_msg}")
                    if error_code == 2:
                        show_error_dialog(error_msg, error_code)
                        
            except Exception as e:
                logging.error(f"Error modifying take profit order: {e}")
                logging.exception("Full traceback:")
        else:
            if not take_profit_order_id:
                logging.warning("No take profit order ID found - cannot modify")
        
        # Log event to CSV - ADJUSTMENT if values changed, HOLD if they stayed the same
        # Get order_id from active trade info
        trade_info = get_active_trade_info()
        event_type = "ADJUSTMENT" if values_changed else "HOLD"
        
        logging.info(f"Logging {event_type} event (values_changed={values_changed})")
        
        log_trade_event(
            event_type=event_type,
            symbol=symbol,
            position_type=position_type,
            size=size,
            price=avg_price,  # Current price (use entry as reference)
            stop_loss=new_stop_loss,
            take_profit=new_price_target,
            reasoning=reasoning,
            market_context=market_context,
            order_id=trade_info.get('order_id') if trade_info else None
        )
        
        # Update active_trade.json with new stop loss and price target
        if trade_info:
            save_active_trade_info(
                order_id=trade_info.get('order_id'),
                entry_price=trade_info.get('entry_price'),
                position_type=position_type,
                entry_timestamp=trade_info.get('entry_timestamp'),
                stop_loss=new_stop_loss,
                price_target=new_price_target,
                reasoning=trade_info.get('reasoning'),  # Keep original entry reasoning
                size=trade_info.get('size'),  # Preserve size
                stop_loss_order_id=stop_loss_order_id,
                take_profit_order_id=take_profit_order_id
            )
            logging.info(f"Updated active_trade.json with new values: Stop={new_stop_loss}, Target={new_price_target}, SL Order ID={stop_loss_order_id}, TP Order ID={take_profit_order_id}")
        
        logging.info("=" * 80)
        if values_changed:
            logging.info("STOP LOSS AND TAKE PROFIT MODIFICATION COMPLETE")
        else:
            logging.info("POSITION MANAGEMENT - HOLD (NO CHANGES NEEDED)")
        logging.info("=" * 80)
            
    except Exception as e:
        logging.error(f"Error modifying stops and targets: {e}")
        logging.exception("Full traceback:")

def get_latest_llm_data():
    """Get the most recent LLM interaction from today's log.
    
    Returns:
        dict: Latest LLM data or None
    """
    global LATEST_LLM_DATA
    
    # Return the global variable if available (most recent)
    if LATEST_LLM_DATA:
        return LATEST_LLM_DATA
    
    # Fallback to reading from CSV if global variable not set
    try:
        log_folder = 'logs'
        today = datetime.datetime.now().strftime("%y%m%d")
        csv_file = os.path.join(log_folder, f"{today}_LLM.csv")
        
        if not os.path.exists(csv_file):
            return None
        
        # Read the CSV and get the last row
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                return rows[-1]  # Return the most recent entry
        return None
    except Exception as e:
        logging.error(f"Error reading latest LLM data: {e}")
        return None

def show_dashboard(root=None):
    """Show a GUI dashboard with current trading status and latest LLM analysis."""
    global DASHBOARD_WINDOW, ACCOUNT_BALANCE, DASHBOARD_WIDGETS
    
    try:
        # Determine if this is initial build or refresh
        is_initial_build = not DASHBOARD_WIDGETS
        
        # Create new window (or use root if provided)
        if root is None:
            # Being called from tray menu - create a new window
            dashboard = tk.Tk()
            DASHBOARD_WINDOW = dashboard
            is_initial_build = True  # Force rebuild for new window
        else:
            # Being called at startup or refresh with existing root
            dashboard = root
            DASHBOARD_WINDOW = dashboard
            # Only deiconify if the window is actually withdrawn (hidden)
            # Don't call it on every update to prevent taskbar flashing
            if dashboard.state() == 'withdrawn':
                dashboard.deiconify()
        
        dashboard.title("ES Trader Dashboard")
        if is_initial_build:
            dashboard.geometry("650x850")
        dashboard.configure(bg='#1e1e1e')
        
        # Get current data - verify position from API if trading is enabled
        trade_info = get_active_trade_info()
        
        # Note: Position verification is now handled by reconciliation in job() and run_trade_monitor()
        # Dashboard simply displays what's in active_trade.json without modifying it
        # This prevents race conditions and duplicate reconciliation
        
        llm_data = get_latest_llm_data()
        
        # Use cached balance or display N/A
        balance = "N/A"
        if ACCOUNT_BALANCE is not None:
            balance = f"${ACCOUNT_BALANCE:,.2f}"
        
        # If this is just a data refresh, update existing widgets
        if not is_initial_build and DASHBOARD_WIDGETS:
            # Update balance
            if 'balance_label' in DASHBOARD_WIDGETS:
                DASHBOARD_WIDGETS['balance_label'].config(text=f"Balance: {balance}")
            
            # Update session RPL (always update, even if 0 or None)
            if SESSION_START_BALANCE is not None:
                rpl_color = '#00ff00' if CURRENT_RPL >= 0 else '#ff4444'
                rpl_text = f"${CURRENT_RPL:+,.2f}"
                session_start_text = f"${SESSION_START_BALANCE:,.2f}"
            else:
                rpl_color = '#aaaaaa'
                rpl_text = "$0.00"
                session_start_text = "N/A"
            
            if 'session_rpl_label' in DASHBOARD_WIDGETS:
                DASHBOARD_WIDGETS['session_rpl_label'].config(text=rpl_text, fg=rpl_color)
            # Session start label hidden for cleaner UI
            # if 'session_start_label' in DASHBOARD_WIDGETS:
            #     DASHBOARD_WIDGETS['session_start_label'].config(text=f"Session Start (18:00): {session_start_text}")
            
            # Update position info
            if trade_info:
                position_type = trade_info.get('position_type', 'None').upper()
                entry_price = trade_info.get('entry_price', 'N/A')
                stop_loss = trade_info.get('stop_loss', 'N/A')
                price_target = trade_info.get('price_target', 'N/A')
                order_id = trade_info.get('order_id', 'N/A')
                size = trade_info.get('size', '')
                pos_color = '#00ff00' if position_type == 'LONG' else '#ff4444'
                
                # Show position type with size in parentheses
                position_text = f"Position: {position_type}"
                if size:
                    position_text += f" ({size})"
                
                if 'position_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['position_label'].config(text=position_text, fg=pos_color)
                if 'entry_price_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['entry_price_label'].config(text=f"Entry Price: {entry_price}")
                if 'stop_loss_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['stop_loss_label'].config(text=f"Stop Loss: {stop_loss}")
                if 'price_target_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['price_target_label'].config(text=f"Take Profit: {price_target}")
                if 'order_id_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['order_id_label'].config(text=f"Order ID: {order_id}")
                
                # Show position labels, hide no-position label
                for key in ['position_label', 'entry_price_label', 'stop_loss_label', 'price_target_label', 'order_id_label']:
                    if key in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS[key].pack(anchor="w")
                if 'no_position_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['no_position_label'].pack_forget()
            else:
                # Hide position labels, show no-position label
                for key in ['position_label', 'entry_price_label', 'stop_loss_label', 'price_target_label', 'order_id_label']:
                    if key in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS[key].pack_forget()
                if 'no_position_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['no_position_label'].pack(anchor="w")
            
            # Update LLM data
            if llm_data:
                action = llm_data.get('action', 'N/A').upper()
                action_colors = {
                    'BUY': '#00ff00', 'SELL': '#ff4444', 'HOLD': '#ffaa00',
                    'CLOSE': '#ff4444', 'ADJUST': '#00aaff', 'SCALE': '#ffaa00'
                }
                action_color = action_colors.get(action, '#ffffff')
                
                if 'action_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['action_label'].config(text=f"Action: {action}", fg=action_color)
                if 'timestamp_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['timestamp_label'].config(text=f"Time: {llm_data.get('date_time', 'N/A')}")
                
                # Update prices
                price_info = []
                if llm_data.get('entry_price'):
                    price_info.append(f"Entry: {llm_data['entry_price']}")
                
                actual_stop = None
                actual_target = None
                if trade_info:
                    actual_stop = trade_info.get('stop_loss')
                    actual_target = trade_info.get('price_target')
                
                # Debug logging
                logging.debug(f"Dashboard price display - LLM: Target={llm_data.get('price_target')}, Stop={llm_data.get('stop_loss')}")
                logging.debug(f"Dashboard price display - Actual: Target={actual_target}, Stop={actual_stop}")
                
                target_value = actual_target if actual_target else llm_data.get('price_target')
                if target_value:
                    target_label = f"Target: {target_value}"
                    if actual_target:
                        target_label += " ✓"
                    price_info.append(target_label)
                
                stop_value = actual_stop if actual_stop else llm_data.get('stop_loss')
                if stop_value:
                    stop_label = f"Stop: {stop_value}"
                    if actual_stop:
                        stop_label += " ✓"
                    price_info.append(stop_label)
                
                if 'prices_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['prices_label'].config(text=" | ".join(price_info) if price_info else "")
                
                if 'confidence_label' in DASHBOARD_WIDGETS:
                    conf_text = f"Confidence: {llm_data['confidence']}" if llm_data.get('confidence') else ""
                    DASHBOARD_WIDGETS['confidence_label'].config(text=conf_text)
                
                if 'reasoning_text' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['reasoning_text'].config(state=tk.NORMAL)
                    DASHBOARD_WIDGETS['reasoning_text'].delete(1.0, tk.END)
                    DASHBOARD_WIDGETS['reasoning_text'].insert(1.0, llm_data.get('reasoning', 'N/A'))
                    DASHBOARD_WIDGETS['reasoning_text'].config(state=tk.DISABLED)
                
                # Update waiting_for text if available
                waiting_for_value = llm_data.get('waiting_for', '')
                if waiting_for_value and waiting_for_value.strip():
                    if 'waiting_for_title' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['waiting_for_title'].pack(anchor="w", pady=(10, 5))
                    if 'waiting_for_text' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['waiting_for_text'].config(state=tk.NORMAL)
                        DASHBOARD_WIDGETS['waiting_for_text'].delete(1.0, tk.END)
                        DASHBOARD_WIDGETS['waiting_for_text'].insert(1.0, waiting_for_value)
                        DASHBOARD_WIDGETS['waiting_for_text'].config(state=tk.DISABLED)
                        DASHBOARD_WIDGETS['waiting_for_text'].pack(fill="x", pady=5)
                else:
                    # Hide waiting_for widgets if no data
                    if 'waiting_for_title' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['waiting_for_title'].pack_forget()
                    if 'waiting_for_text' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['waiting_for_text'].pack_forget()
                
                # Update key_levels text if available
                key_levels_value = llm_data.get('key_levels', '')
                if key_levels_value and key_levels_value.strip():
                    # Format key levels for display
                    try:
                        if isinstance(key_levels_value, str):
                            key_levels_json = json.loads(key_levels_value)
                        else:
                            key_levels_json = key_levels_value
                        
                        if key_levels_json and isinstance(key_levels_json, list):
                            formatted_levels = []
                            for level in key_levels_json:
                                if isinstance(level, dict):
                                    price = level.get('price', 'N/A')
                                    level_type = level.get('type', 'N/A')
                                    reason = level.get('reason', '')
                                    if reason:
                                        formatted_levels.append(f"{price} ({level_type}): {reason}")
                                    else:
                                        formatted_levels.append(f"{price} ({level_type})")
                            
                            if formatted_levels:
                                if 'key_levels_title' in DASHBOARD_WIDGETS:
                                    DASHBOARD_WIDGETS['key_levels_title'].pack(anchor="w", pady=(10, 5))
                                if 'key_levels_text' in DASHBOARD_WIDGETS:
                                    DASHBOARD_WIDGETS['key_levels_text'].config(state=tk.NORMAL)
                                    DASHBOARD_WIDGETS['key_levels_text'].delete(1.0, tk.END)
                                    DASHBOARD_WIDGETS['key_levels_text'].insert(1.0, "\n".join(formatted_levels))
                                    DASHBOARD_WIDGETS['key_levels_text'].config(state=tk.DISABLED)
                                    DASHBOARD_WIDGETS['key_levels_text'].pack(fill="x", pady=5)
                    except:
                        pass  # Skip if parsing fails
                else:
                    # Hide key_levels widgets if no data
                    if 'key_levels_title' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['key_levels_title'].pack_forget()
                    if 'key_levels_text' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['key_levels_text'].pack_forget()
                
                # Update suggestion text if available (only show if not null/empty)
                suggestion_value = llm_data.get('suggestion', '')
                if suggestion_value and suggestion_value.strip() and suggestion_value.lower() != 'null':
                    if 'suggestion_title' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['suggestion_title'].pack(anchor="w", pady=(10, 5))
                    if 'suggestion_text' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['suggestion_text'].config(state=tk.NORMAL)
                        DASHBOARD_WIDGETS['suggestion_text'].delete(1.0, tk.END)
                        DASHBOARD_WIDGETS['suggestion_text'].insert(1.0, suggestion_value)
                        DASHBOARD_WIDGETS['suggestion_text'].config(state=tk.DISABLED)
                        DASHBOARD_WIDGETS['suggestion_text'].pack(fill="x", pady=5)
                else:
                    # Hide suggestion widgets if no data
                    if 'suggestion_title' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['suggestion_title'].pack_forget()
                    if 'suggestion_text' in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS['suggestion_text'].pack_forget()
                
                # Market Context temporarily hidden
                # if 'context_text' in DASHBOARD_WIDGETS:
                #     DASHBOARD_WIDGETS['context_text'].config(state=tk.NORMAL)
                #     DASHBOARD_WIDGETS['context_text'].delete(1.0, tk.END)
                #     DASHBOARD_WIDGETS['context_text'].insert(1.0, llm_data.get('context', 'N/A'))
                #     DASHBOARD_WIDGETS['context_text'].config(state=tk.DISABLED)
                
                # Hide no-data label when LLM data exists
                if 'no_llm_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['no_llm_label'].pack_forget()
            else:
                # Hide LLM widgets, show no-data label (context temporarily hidden)
                for key in ['action_label', 'time_frame', 'prices_label', 'confidence_label', 
                           'reasoning_title', 'reasoning_text', 'waiting_for_title', 'waiting_for_text',
                           'key_levels_title', 'key_levels_text', 'suggestion_title', 'suggestion_text']:
                    if key in DASHBOARD_WIDGETS:
                        DASHBOARD_WIDGETS[key].pack_forget()
                if 'no_llm_label' in DASHBOARD_WIDGETS:
                    DASHBOARD_WIDGETS['no_llm_label'].pack(pady=20)
            
            # Update clock
            if 'clock_label' in DASHBOARD_WIDGETS:
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                DASHBOARD_WIDGETS['clock_label'].config(text=current_time)
            
            return  # Exit after updating existing widgets
        
        # INITIAL BUILD - Create all widgets from scratch
        # Clear any existing widgets
        for widget in dashboard.winfo_children():
            widget.destroy()
        DASHBOARD_WIDGETS.clear()
        
        # Title bar with clock
        title_frame = tk.Frame(dashboard, bg='#1e1e1e')
        title_frame.pack(fill="x", pady=10)
        
        # Title (centered)
        title = tk.Label(title_frame, text="ES TRADER DASHBOARD", font=("Arial", 20, "bold"), 
                        bg='#1e1e1e', fg='#00ff00')
        title.pack(side="left", expand=True)
        
        # Clock (top right)
        clock_label = tk.Label(title_frame, text="", font=("Arial", 14), 
                              bg='#1e1e1e', fg='#00aaff', padx=20)
        clock_label.pack(side="right")
        DASHBOARD_WIDGETS['clock_label'] = clock_label
        
        # Account Section
        account_frame = tk.LabelFrame(dashboard, text="Account Status", font=("Arial", 12, "bold"),
                                     bg='#2d2d2d', fg='#ffffff', padx=10, pady=10)
        account_frame.pack(fill="x", padx=20, pady=10)
        
        # Balance and RPL on same line
        balance_rpl_frame = tk.Frame(account_frame, bg='#2d2d2d')
        balance_rpl_frame.pack(anchor="w")
        
        balance_label = tk.Label(balance_rpl_frame, text=f"Balance: {balance}", 
                                font=("Arial", 14), bg='#2d2d2d', fg='#00ff00')
        balance_label.pack(side="left")
        DASHBOARD_WIDGETS['balance_label'] = balance_label
        
        # Session RPL (displayed next to balance with 50px spacing)
        if SESSION_START_BALANCE is not None:
            rpl_color = '#00ff00' if CURRENT_RPL >= 0 else '#ff4444'
            rpl_text = f"${CURRENT_RPL:+,.2f}"
            session_start_text = f"${SESSION_START_BALANCE:,.2f}"
        else:
            # Initial state before first balance query
            rpl_color = '#aaaaaa'
            rpl_text = "$0.00"
            session_start_text = "N/A"
        
        session_rpl_label = tk.Label(balance_rpl_frame, text=rpl_text,
                                    font=("Arial", 14, "bold"), bg='#2d2d2d', fg=rpl_color)
        session_rpl_label.pack(side="left", padx=(20, 0))
        DASHBOARD_WIDGETS['session_rpl_label'] = session_rpl_label
        
        # Session start label hidden for cleaner UI
        # session_start_label = tk.Label(account_frame, text=f"Session Start (18:00): {session_start_text}",
        #                               font=("Arial", 11), bg='#2d2d2d', fg='#aaaaaa')
        # session_start_label.pack(anchor="w", pady=(5, 0))
        # DASHBOARD_WIDGETS['session_start_label'] = session_start_label
        
        # Position Section
        position_frame = tk.LabelFrame(dashboard, text="Current Position", font=("Arial", 12, "bold"),
                                      bg='#2d2d2d', fg='#ffffff', padx=10, pady=10)
        position_frame.pack(fill="x", padx=20, pady=10)
        
        # Create position labels (shown/hidden based on state)
        position_label = tk.Label(position_frame, text="", font=("Arial", 14, "bold"), bg='#2d2d2d')
        entry_price_label = tk.Label(position_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#ffffff')
        stop_loss_label = tk.Label(position_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#ff6666')
        price_target_label = tk.Label(position_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#66ff66')
        order_id_label = tk.Label(position_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#aaaaaa')
        no_position_label = tk.Label(position_frame, text="No Active Position", 
                                     font=("Arial", 14), bg='#2d2d2d', fg='#888888')
        
        DASHBOARD_WIDGETS['position_label'] = position_label
        DASHBOARD_WIDGETS['entry_price_label'] = entry_price_label
        DASHBOARD_WIDGETS['stop_loss_label'] = stop_loss_label
        DASHBOARD_WIDGETS['price_target_label'] = price_target_label
        DASHBOARD_WIDGETS['order_id_label'] = order_id_label
        DASHBOARD_WIDGETS['no_position_label'] = no_position_label
        
        if trade_info:
            position_type = trade_info.get('position_type', 'None').upper()
            entry_price = trade_info.get('entry_price', 'N/A')
            stop_loss = trade_info.get('stop_loss', 'N/A')
            price_target = trade_info.get('price_target', 'N/A')
            order_id = trade_info.get('order_id', 'N/A')
            size = trade_info.get('size', '')
            pos_color = '#00ff00' if position_type == 'LONG' else '#ff4444'
            
            # Show position type with size in parentheses
            position_text = f"Position: {position_type}"
            if size:
                position_text += f" ({size})"
            
            position_label.config(text=position_text, fg=pos_color)
            entry_price_label.config(text=f"Entry Price: {entry_price}")
            stop_loss_label.config(text=f"Stop Loss: {stop_loss}")
            price_target_label.config(text=f"Take Profit: {price_target}")
            order_id_label.config(text=f"Order ID: {order_id}")
            
            position_label.pack(anchor="w")
            entry_price_label.pack(anchor="w")
            stop_loss_label.pack(anchor="w")
            price_target_label.pack(anchor="w")
            order_id_label.pack(anchor="w")
        else:
            no_position_label.pack(anchor="w")
        
        # LLM Analysis Section
        llm_frame = tk.LabelFrame(dashboard, text="Latest LLM Analysis", font=("Arial", 12, "bold"),
                                 bg='#2d2d2d', fg='#ffffff', padx=10, pady=10)
        llm_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Create LLM widgets (shown/hidden based on data availability)
        action_label = tk.Label(llm_frame, text="", font=("Arial", 14, "bold"), bg='#2d2d2d')
        
        # Timestamp and countdown on same line
        time_frame = tk.Frame(llm_frame, bg='#2d2d2d')
        timestamp_label = tk.Label(time_frame, text="", font=("Arial", 10), bg='#2d2d2d', fg='#aaaaaa')
        countdown_label = tk.Label(time_frame, text="", font=("Arial", 10), bg='#2d2d2d', fg='#00ff00')
        
        prices_label = tk.Label(llm_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#00aaff')
        confidence_label = tk.Label(llm_frame, text="", font=("Arial", 11), bg='#2d2d2d', fg='#ffaa00')
        reasoning_title = tk.Label(llm_frame, text="Reasoning:", font=("Arial", 11, "bold"), bg='#2d2d2d', fg='#ffffff')
        reasoning_text = tk.Text(llm_frame, height=6, wrap=tk.WORD, font=("Arial", 10),
                                bg='#2d2d2d', fg='#ffffff', relief=tk.FLAT)
        waiting_for_title = tk.Label(llm_frame, text="Waiting For:", font=("Arial", 11, "bold"), bg='#2d2d2d', fg='#ffffff')
        waiting_for_text = tk.Text(llm_frame, height=2, wrap=tk.WORD, font=("Arial", 10),
                                   bg='#2d2d2d', fg='#ffaa00', relief=tk.FLAT)
        key_levels_title = tk.Label(llm_frame, text="Key Levels:", font=("Arial", 11, "bold"), bg='#2d2d2d', fg='#ffffff')
        key_levels_text = tk.Text(llm_frame, height=4, wrap=tk.WORD, font=("Arial", 10),
                                  bg='#2d2d2d', fg='#00aaff', relief=tk.FLAT)
        suggestion_title = tk.Label(llm_frame, text="💡 Suggestion:", font=("Arial", 11, "bold"), bg='#2d2d2d', fg='#ffffff')
        suggestion_text = tk.Text(llm_frame, height=2, wrap=tk.WORD, font=("Arial", 10),
                                  bg='#2d2d2d', fg='#ff66ff', relief=tk.FLAT)
        context_title = tk.Label(llm_frame, text="Market Context:", font=("Arial", 11, "bold"), bg='#2d2d2d', fg='#ffffff')
        context_text = tk.Text(llm_frame, height=4, wrap=tk.WORD, font=("Arial", 10),
                              bg='#1e1e1e', fg='#aaaaaa', relief=tk.FLAT)
        no_llm_label = tk.Label(llm_frame, text="No LLM data available yet", 
                               font=("Arial", 12), bg='#2d2d2d', fg='#888888')
        
        DASHBOARD_WIDGETS['action_label'] = action_label
        DASHBOARD_WIDGETS['time_frame'] = time_frame
        DASHBOARD_WIDGETS['timestamp_label'] = timestamp_label
        DASHBOARD_WIDGETS['countdown_label'] = countdown_label
        DASHBOARD_WIDGETS['prices_label'] = prices_label
        DASHBOARD_WIDGETS['confidence_label'] = confidence_label
        DASHBOARD_WIDGETS['reasoning_title'] = reasoning_title
        DASHBOARD_WIDGETS['reasoning_text'] = reasoning_text
        DASHBOARD_WIDGETS['waiting_for_title'] = waiting_for_title
        DASHBOARD_WIDGETS['waiting_for_text'] = waiting_for_text
        DASHBOARD_WIDGETS['key_levels_title'] = key_levels_title
        DASHBOARD_WIDGETS['key_levels_text'] = key_levels_text
        DASHBOARD_WIDGETS['suggestion_title'] = suggestion_title
        DASHBOARD_WIDGETS['suggestion_text'] = suggestion_text
        DASHBOARD_WIDGETS['context_title'] = context_title
        DASHBOARD_WIDGETS['context_text'] = context_text
        DASHBOARD_WIDGETS['no_llm_label'] = no_llm_label
        
        if llm_data:
            action = llm_data.get('action', 'N/A').upper()
            action_colors = {
                'BUY': '#00ff00', 'SELL': '#ff4444', 'HOLD': '#ffaa00',
                'CLOSE': '#ff4444', 'ADJUST': '#00aaff', 'SCALE': '#ffaa00'
            }
            action_color = action_colors.get(action, '#ffffff')
            
            action_label.config(text=f"Action: {action}", fg=action_color)
            action_label.pack(anchor="w", pady=5)
            
            timestamp_label.config(text=f"Time: {llm_data.get('date_time', 'N/A')}")
            timestamp_label.pack(side="left")
            
            # Countdown will be updated by update_countdown()
            countdown_label.pack(side="left", padx=10)
            time_frame.pack(anchor="w")
            
            # Prices
            price_info = []
            if llm_data.get('entry_price'):
                price_info.append(f"Entry: {llm_data['entry_price']}")
            
            actual_stop = None
            actual_target = None
            if trade_info:
                actual_stop = trade_info.get('stop_loss')
                actual_target = trade_info.get('price_target')
            
            # Debug logging
            logging.debug(f"Dashboard price display (initial) - LLM: Target={llm_data.get('price_target')}, Stop={llm_data.get('stop_loss')}")
            logging.debug(f"Dashboard price display (initial) - Actual: Target={actual_target}, Stop={actual_stop}")
            
            target_value = actual_target if actual_target else llm_data.get('price_target')
            if target_value:
                target_label = f"Target: {target_value}"
                if actual_target:
                    target_label += " ✓"
                price_info.append(target_label)
            
            stop_value = actual_stop if actual_stop else llm_data.get('stop_loss')
            if stop_value:
                stop_label = f"Stop: {stop_value}"
                if actual_stop:
                    stop_label += " ✓"
                price_info.append(stop_label)
            
            if price_info:
                prices_label.config(text=" | ".join(price_info))
                prices_label.pack(anchor="w", pady=5)
            
            if llm_data.get('confidence'):
                confidence_label.config(text=f"Confidence: {llm_data['confidence']}")
                confidence_label.pack(anchor="w")
            
            reasoning_title.pack(anchor="w", pady=(10, 5))
            reasoning_text.insert(1.0, llm_data.get('reasoning', 'N/A'))
            reasoning_text.config(state=tk.DISABLED)
            reasoning_text.pack(fill="x", pady=5)
            
            # Waiting For section (if available)
            waiting_for_value = llm_data.get('waiting_for', '')
            if waiting_for_value and waiting_for_value.strip():
                waiting_for_title.pack(anchor="w", pady=(10, 5))
                waiting_for_text.insert(1.0, waiting_for_value)
                waiting_for_text.config(state=tk.DISABLED)
                waiting_for_text.pack(fill="x", pady=5)
            
            # Key Levels section (if available)
            key_levels_value = llm_data.get('key_levels', '')
            if key_levels_value and key_levels_value.strip():
                # Format key levels for display
                try:
                    if isinstance(key_levels_value, str):
                        key_levels_json = json.loads(key_levels_value)
                    else:
                        key_levels_json = key_levels_value
                    
                    if key_levels_json and isinstance(key_levels_json, list):
                        formatted_levels = []
                        for level in key_levels_json:
                            if isinstance(level, dict):
                                price = level.get('price', 'N/A')
                                level_type = level.get('type', 'N/A')
                                reason = level.get('reason', '')
                                if reason:
                                    formatted_levels.append(f"{price} ({level_type}): {reason}")
                                else:
                                    formatted_levels.append(f"{price} ({level_type})")
                        
                        if formatted_levels:
                            key_levels_title.pack(anchor="w", pady=(10, 5))
                            key_levels_text.insert(1.0, "\n".join(formatted_levels))
                            key_levels_text.config(state=tk.DISABLED)
                            key_levels_text.pack(fill="x", pady=5)
                except:
                    pass  # Skip if parsing fails
            
            # Display suggestion if present (only show if not null/empty)
            suggestion_value = llm_data.get('suggestion', '')
            if suggestion_value and suggestion_value.strip() and suggestion_value.lower() != 'null':
                suggestion_title.pack(anchor="w", pady=(10, 5))
                suggestion_text.insert(1.0, suggestion_value)
                suggestion_text.config(state=tk.DISABLED)
                suggestion_text.pack(fill="x", pady=5)
            
            # Market Context temporarily hidden
            # context_title.pack(anchor="w", pady=(10, 5))
            # context_text.insert(1.0, llm_data.get('context', 'N/A'))
            # context_text.config(state=tk.DISABLED)
            # context_text.pack(fill="x", pady=5)
        else:
            no_llm_label.pack(pady=20)
        
        # Close/Refresh buttons
        btn_frame = tk.Frame(dashboard, bg='#1e1e1e')
        btn_frame.pack(pady=10)
        
        # Centered refresh button that triggers full screenshot workflow
        refresh_btn = tk.Button(btn_frame, text="Refresh", 
                               command=manual_job,
                               font=("Arial", 11), bg='#006600', fg='#ffffff',
                               activebackground='#008800', relief=tk.FLAT, padx=20, pady=5)
        refresh_btn.pack()
        
        # Center the window only on initial build
        if is_initial_build:
            dashboard.update_idletasks()
            width = dashboard.winfo_width()
            height = dashboard.winfo_height()
            x = (dashboard.winfo_screenwidth() // 2) - (width // 2)
            y = (dashboard.winfo_screenheight() // 2) - (height // 2)
            dashboard.geometry(f'{width}x{height}+{x}+{y}')
            
            # Start the clock and countdown updates (only on initial build to avoid multiple timers)
            update_clock()
            update_countdown()
        
    except Exception as e:
        logging.error(f"Error showing dashboard: {e}")
        logging.exception("Full traceback:")

def update_dashboard_data():
    """Update the dashboard with latest data if it exists.
    
    This function is thread-safe and can be called from any thread.
    It schedules the update on the Tkinter main thread.
    """
    global DASHBOARD_WINDOW
    if DASHBOARD_WINDOW and DASHBOARD_WINDOW.winfo_exists():
        try:
            # Schedule the update on the main Tkinter thread (thread-safe)
            # Using after(0) ensures it runs on the next event loop iteration
            logging.debug("Scheduling dashboard update on main thread")
            DASHBOARD_WINDOW.after(0, lambda: _update_dashboard_widgets())
        except Exception as e:
            logging.error(f"Error scheduling dashboard update: {e}")
    else:
        logging.debug("Dashboard window not available for update")

def _update_dashboard_widgets():
    """Internal function to update dashboard widgets (must be called from main thread)."""
    global DASHBOARD_WINDOW
    try:
        logging.debug("Updating dashboard widgets")
        # Refresh the dashboard
        show_dashboard(DASHBOARD_WINDOW)
        # Force immediate GUI update
        DASHBOARD_WINDOW.update_idletasks()
        logging.debug("Dashboard widgets updated successfully")
    except Exception as e:
        logging.error(f"Error updating dashboard widgets: {e}")

def update_clock():
    """Update the clock label with current time (HH:MM:SS)."""
    global DASHBOARD_WINDOW, DASHBOARD_WIDGETS
    if DASHBOARD_WINDOW and DASHBOARD_WINDOW.winfo_exists() and 'clock_label' in DASHBOARD_WIDGETS:
        try:
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            DASHBOARD_WIDGETS['clock_label'].config(text=current_time)
            # Schedule next update in 1 second
            DASHBOARD_WINDOW.after(1000, update_clock)
        except Exception as e:
            logging.debug(f"Error updating clock: {e}")
    else:
        logging.debug("Dashboard window or clock widget not available")

def update_countdown():
    """Update the countdown label showing seconds until next screenshot."""
    global DASHBOARD_WINDOW, DASHBOARD_WIDGETS, LAST_JOB_TIME, INTERVAL_SCHEDULE
    if DASHBOARD_WINDOW and DASHBOARD_WINDOW.winfo_exists() and 'countdown_label' in DASHBOARD_WIDGETS:
        try:
            if LAST_JOB_TIME is not None:
                current_interval = get_current_interval()
                
                # Check if in disabled interval and show next active time
                if current_interval == -1:
                    in_disabled, next_active_time = is_in_disabled_interval(INTERVAL_SCHEDULE)
                    if in_disabled and next_active_time:
                        DASHBOARD_WIDGETS['countdown_label'].config(
                            text=f"[Waiting until {next_active_time.strftime('%H:%M')}]", 
                            fg='#888888'
                        )
                    else:
                        DASHBOARD_WIDGETS['countdown_label'].config(text="[Screenshots disabled]", fg='#888888')
                else:
                    # Calculate seconds since last job
                    elapsed = (datetime.datetime.now() - LAST_JOB_TIME).total_seconds()
                    remaining = max(0, int(current_interval - elapsed))
                    
                    # Color based on urgency
                    if remaining <= 5:
                        color = '#ff4444'  # Red - imminent
                    elif remaining <= 15:
                        color = '#ffaa00'  # Orange - soon
                    else:
                        color = '#00ff00'  # Green - plenty of time
                    
                    DASHBOARD_WIDGETS['countdown_label'].config(
                        text=f"{remaining}s", 
                        fg=color
                    )
            else:
                # Check if waiting for next active interval
                in_disabled, next_active_time = is_in_disabled_interval(INTERVAL_SCHEDULE)
                if in_disabled and next_active_time:
                    DASHBOARD_WIDGETS['countdown_label'].config(
                        text=f"[Waiting until {next_active_time.strftime('%H:%M')}]", 
                        fg='#aaaaaa'
                    )
                else:
                    DASHBOARD_WIDGETS['countdown_label'].config(text="[Waiting...]", fg='#aaaaaa')
            
            # Schedule next update in 1 second
            DASHBOARD_WINDOW.after(1000, update_countdown)
        except Exception as e:
            logging.debug(f"Error updating countdown: {e}")
    else:
        logging.debug("Dashboard window or countdown widget not available")

def job(window_title, window_process_name, top_offset, bottom_offset, left_offset, right_offset, save_folder, begin_time, end_time, symbol, position_type, no_position_prompt, long_position_prompt, short_position_prompt, runner_prompt, model, topstep_config, enable_llm, enable_trading, openai_api_url, openai_api_key, enable_save_screenshots, auth_token=None, execute_trades=False, telegram_config=None, no_new_trades_windows='', force_close_time='23:59'):
    """The main job to run periodically."""
    global PREVIOUS_POSITION_TYPE, LAST_WAITING_FOR, LAST_KEY_LEVELS
    
    if not is_within_time_range(begin_time, end_time):
        logging.info(f"Current time {datetime.datetime.now().time()} is outside the range {begin_time}-{end_time}. Skipping.")
        return
    
    # Check weekly market closed periods (Saturday/Sunday closure)
    if HOLIDAY_CONFIG.get('market_closed'):
        is_closed, reason = is_market_closed_weekly(HOLIDAY_CONFIG['market_closed'])
        if is_closed:
            logging.info(f"📅 {reason} - Skipping all operations")
            return
    
    # Check if we're in any no-new-trades window BEFORE doing anything
    in_no_trades_window, current_window = is_in_no_new_trades_window(no_new_trades_windows)
    
    # Check if today is a market holiday (full close)
    if HOLIDAY_CONFIG['enabled']:
        now = datetime.datetime.now()
        holiday_file = HOLIDAY_CONFIG['data_file']
        
        if market_holidays.is_market_holiday(now, holiday_file):
            logging.info("🚫 Market is CLOSED today (holiday) - Skipping all trading operations")
            return
        
        # Check for early close day with Trading Halt and Reopen (like Thanksgiving)
        if market_holidays.is_early_close_day(now.date(), holiday_file):
            # Load holiday data to check for reopen times
            holiday_data = market_holidays.load_holiday_data(holiday_file)
            if holiday_data and 'holidays' in holiday_data:
                date_str = now.date().isoformat()
                for holiday in holiday_data['holidays']:
                    if holiday['date'] == date_str and holiday['type'] == 'early_close':
                        close_time = market_holidays.get_close_time(now.date(), holiday_file)
                        notes = holiday.get('notes', '')
                        
                        # Check if there's a reopen time mentioned in notes (e.g., "Reopen @ 17:00 CT (18:00 ET)")
                        reopen_time = None
                        if 'reopen' in notes.lower():
                            # Try to extract reopen time from notes (format: "18:00 ET" or "17:00 CT (18:00 ET)")
                            import re
                            # Look for time in format HH:MM after "Reopen" or "Open @"
                            match = re.search(r'(?:Reopen|Open)\s+@\s+(\d{1,2}):(\d{2})\s+(?:CT|ET)', notes, re.IGNORECASE)
                            if match:
                                hour = int(match.group(1))
                                minute = int(match.group(2))
                                # If it says CT, convert to ET
                                if 'CT' in match.group(0):
                                    hour += 1  # CT to ET conversion
                                reopen_time = datetime.time(hour, minute)
                                logging.info(f"ℹ️  Detected Trading Halt with reopen at {reopen_time.strftime('%H:%M')} ET")
                        
                        if close_time:
                            # Calculate adjusted close time with buffer
                            minutes_before = HOLIDAY_CONFIG['minutes_before_close']
                            close_datetime = datetime.datetime.combine(now.date(), close_time)
                            adjusted_close = close_datetime - datetime.timedelta(minutes=minutes_before)
                            
                            # If there's a reopen time, check if we're in the halt period
                            if reopen_time:
                                # We're in halt period if: current time >= adjusted_close AND current time < reopen_time
                                if adjusted_close.time() <= now.time() < reopen_time:
                                    logging.info(f"⚠️  Trading Halt period (halt at {close_time.strftime('%H:%M')}, reopen at {reopen_time.strftime('%H:%M')})")
                                    logging.info(f"⚠️  Stop time reached: {adjusted_close.strftime('%H:%M')} - Skipping trading operations")
                                    return
                                elif now.time() >= reopen_time:
                                    logging.info(f"✅ Market reopened at {reopen_time.strftime('%H:%M')} ET - Trading allowed")
                                    # Continue with normal trading
                                    break
                            else:
                                # No reopen time, just check if we're past adjusted close
                                if now >= adjusted_close:
                                    logging.info(f"⚠️  Approaching early market close (normal: {close_time.strftime('%H:%M')}, buffer: {minutes_before}min)")
                                    logging.info(f"⚠️  Stop time reached: {adjusted_close.strftime('%H:%M')} - Skipping trading operations")
                                    return
                                elif now.time() >= datetime.time(close_time.hour - 1, 0):  # Within 1 hour of close
                                    logging.info(f"ℹ️  Early close today at {close_time.strftime('%H:%M')} - Will stop trading at {adjusted_close.strftime('%H:%M')}")
                        break

    # Check if we're in no-new-trades window BEFORE taking any screenshots or querying positions
    # (except if we have an active position that needs force closing)
    if in_no_trades_window:
        # Check if we have an active position that needs to be force-closed
        trade_info = get_active_trade_info()
        has_active_trade = trade_info and trade_info.get('position_type') in ['long', 'short']
        
        # Parse force close time
        force_close = datetime.datetime.strptime(force_close_time, "%H:%M").time()
        current_time = datetime.datetime.now().time()
        
        # Only proceed if we have an active trade AND it's past force close time
        if has_active_trade and current_time >= force_close:
            logging.info(f"In no-new-trades window '{current_window}' but active trade needs force closing - continuing")
        else:
            # Skip everything - no screenshots, no analysis
            logging.info(f"In no-new-trades window '{current_window}' - Skipping all operations (screenshots, analysis, new entries)")
            return

    logging.info(f"Starting job at {time.ctime()}")
    
    # First, verify Bookmap is available before doing anything else
    if window_title:
        try:
            hwnd = get_window_by_partial_title(window_title, window_process_name)
            if not hwnd:
                logging.warning(f"Bookmap window not found ('{window_title}'{' / process ' + window_process_name if window_process_name else ''}) - skipping all processing for this cycle")
                return  # Exit early, scheduler will retry on next interval
            logging.info(f"Bookmap window verified: HWND={hwnd}")
        except Exception as e:
            logging.error(f"Error checking for Bookmap window: {e}")
            logging.warning("Bookmap not available - skipping all processing for this cycle")
            return  # Exit early, scheduler will retry on next interval
    
    current_time = datetime.datetime.now().time()
    begin = datetime.datetime.strptime(begin_time, "%H:%M").time()
    end = datetime.datetime.strptime(end_time, "%H:%M").time()
    force_close = datetime.datetime.strptime(force_close_time, "%H:%M").time()
    
    # Determine if this is an overnight session (begin_time > end_time, e.g., 18:00 - 05:00)
    is_overnight_session = begin > end
    
    # Load daily market context
    daily_context = get_daily_context()
    
    # Load economic calendar and get upcoming events (if enabled)
    upcoming_events = []
    try:
        if CONFIG.has_section('EconomicCalendar') and CONFIG.getboolean('EconomicCalendar', 'enable_economic_calendar', fallback=False):
            calendar_file = CONFIG.get('EconomicCalendar', 'data_file', fallback='market_data/economic_calendar.json')
            minutes_before = CONFIG.getint('EconomicCalendar', 'minutes_before_event', fallback=15)
            minutes_after = CONFIG.getint('EconomicCalendar', 'minutes_after_event', fallback=15)
            severity_threshold_str = CONFIG.get('EconomicCalendar', 'severity_threshold', fallback='High,Medium')
            severity_filter = [s.strip() for s in severity_threshold_str.split(',')]
            
            upcoming_events = economic_calendar.get_upcoming_events(
                calendar_file,
                minutes_before,
                minutes_after,
                severity_filter
            )
            
            if upcoming_events:
                logging.info(f"Found {len(upcoming_events)} upcoming economic events:")
                for event in upcoming_events:
                    logging.info(f"  - {event['name']} ({event['severity']}) in {event['minutes_until']:.1f} minutes")
    except Exception as e:
        logging.error(f"Error loading economic calendar: {e}")
        logging.exception("Full traceback:")
        upcoming_events = []
    
    try:
        # Get current position status and details (only query API during trading hours)
        if is_within_time_range(begin_time, end_time):
            current_position_type, position_details, working_orders = get_current_position(
                symbol, topstep_config, enable_trading, auth_token, return_details=True
            )
            logging.info(f"Determined current position_type: {current_position_type}")
            
            # Query account balance for session RPL tracking and snapshots
            balance = get_account_balance(topstep_config['account_id'], topstep_config, enable_trading, auth_token)
            if balance is not None:
                global ACCOUNT_BALANCE
                ACCOUNT_BALANCE = balance
            
            # Check for position discrepancies (e.g., positions opened manually from broker)
            discrepancy = check_position_discrepancy(current_position_type, position_details)
            if discrepancy:
                logging.info("⚠️ DISCREPANCY DETECTED in main job - correcting state")
                
                # Handle untracked position (opened manually from broker)
                if discrepancy.get('type') == 'untracked_position':
                    logging.info("📊 Detected untracked position opened from broker - updating system state")
                    
                    # Correct the system state to match API reality
                    success = correct_position_state(
                        discrepancy,
                        current_position_type,
                        position_details,
                        working_orders,
                        topstep_config,
                        enable_trading,
                        auth_token
                    )
                    
                    if success:
                        logging.info("✅ System state corrected for manually-opened position")
                    else:
                        logging.warning("⚠️ Failed to correct system state")
                else:
                    # Other discrepancy types (full_close, position_mismatch, etc.)
                    correct_position_state(
                        discrepancy,
                        current_position_type,
                        position_details,
                        working_orders,
                        topstep_config,
                        enable_trading,
                        auth_token
                    )
            
            # Reconcile trades (check for positions closed by stop/target)
            # This checks both local tracking and Supabase for unclosed trades
            # Skip if reconciliation was just done by trade monitor (within last 5 seconds)
            global LAST_RECONCILIATION_TIME
            should_reconcile = True
            if LAST_RECONCILIATION_TIME:
                time_since_reconciliation = (datetime.datetime.now() - LAST_RECONCILIATION_TIME).total_seconds()
                if time_since_reconciliation < 5:
                    should_reconcile = False
                    logging.debug(f"Skipping reconciliation - just handled by trade monitor {time_since_reconciliation:.1f}s ago")
            
            if should_reconcile:
                reconcile_closed_trades(topstep_config, enable_trading, auth_token)
                reconcile_supabase_open_trades(topstep_config, enable_trading, auth_token)
            else:
                logging.debug("Using position state from recent reconciliation")
            
            # Update dashboard with latest position data and balance
            update_dashboard_data()
            
            # Detect if position changed from active to closed
            if PREVIOUS_POSITION_TYPE in ['long', 'short'] and current_position_type == 'none':
                logging.info(f"Position changed from {PREVIOUS_POSITION_TYPE} to none - Fetching trade results")
                trade_info = get_active_trade_info()
                if trade_info:
                    # Fetch trade results from API
                    entry_timestamp = trade_info.get('entry_timestamp')
                    if entry_timestamp:
                        start_time = entry_timestamp
                    else:
                        # Fallback to today's start if no timestamp
                        start_time = datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                    
                    end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                    
                    trades = fetch_trade_results(
                        topstep_config['account_id'],
                        topstep_config,
                        enable_trading,
                        auth_token,
                        start_time,
                        end_time
                    )
                    
                    if trades:
                        # Calculate net P&L from all fills
                        total_pnl = sum(trade.get('profitAndLoss', 0) for trade in trades)
                        total_fees = sum(trade.get('fees', 0) for trade in trades)
                        net_pnl = total_pnl - total_fees
                        
                        # Get entry price and position details
                        entry_price = trade_info.get('entry_price', 0)
                        trade_position_type = trade_info.get('position_type', PREVIOUS_POSITION_TYPE)
                        
                        # Calculate P&L in points (assuming ES multiplier of $50 per point)
                        pnl_points = net_pnl / 50 if net_pnl else 0
                        
                        # Determine success/failure
                        is_success = net_pnl > 0
                        emoji = "✅" if is_success else "❌"
                        result_text = "PROFIT" if is_success else "LOSS"
                        
                        logging.info(f"="*80)
                        logging.info(f"TRADE CLOSED - {result_text}")
                        logging.info(f"Position: {trade_position_type.upper()}")
                        logging.info(f"Entry Price: {entry_price}")
                        logging.info(f"Net P&L: ${net_pnl:.2f} ({pnl_points:+.2f} pts)")
                        logging.info(f"Fees: ${total_fees:.2f}")
                        logging.info(f"Total Fills: {len(trades)}")
                        logging.info(f"="*80)
                        
                        # Get updated balance
                        balance = get_account_balance(topstep_config['account_id'], topstep_config, enable_trading, auth_token)
                        
                        # Log CLOSE event with actual P&L
                        log_trade_event(
                            event_type="CLOSE",
                            symbol=symbol,
                            position_type=trade_position_type,
                            size=topstep_config.get('quantity', 0),
                            price=0,  # Exit price not available from trade results
                            reasoning="Position closed - fetched actual results from API",
                            profit_loss=net_pnl,
                            profit_loss_points=pnl_points,
                            balance=balance,
                            market_context=daily_context,
                            order_id=trade_info.get('order_id'),
                            entry_price=entry_price
                        )
                        
                        # Send Telegram notification
                        telegram_msg = (
                            f"{emoji} <b>TRADE CLOSED - {result_text}</b>\n"
                            f"Position: {trade_position_type.upper()}\n"
                            f"Entry Price: {entry_price}\n"
                            f"P&L: ${net_pnl:+,.2f} ({pnl_points:+.2f} pts)\n"
                            f"Fees: ${total_fees:.2f}\n"
                        )
                        
                        if balance is not None:
                            telegram_msg += f"💰 Balance: ${balance:,.2f}\n"
                        
                        telegram_msg += f"📝 Reason: Position closed - fetched actual results from API\n"
                        telegram_msg += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        send_telegram_message(telegram_msg, telegram_config)
                        logging.info("Telegram notification sent for closed position")
                        
                        # Clear active trade info
                        clear_active_trade_info()
                        
                        # Update dashboard
                        update_dashboard_data()
                        logging.info("Dashboard updated with closed position results")
                    else:
                        logging.warning("Could not fetch trade results from API")
                else:
                    logging.warning("No active trade info found for closed position")
            
            # Update previous position type
            PREVIOUS_POSITION_TYPE = current_position_type
        else:
            # Outside trading hours - assume no position and skip API queries
            logging.info(f"Outside trading hours ({begin_time}-{end_time}) - Skipping position queries")
            current_position_type = 'none'
            position_details = None
            working_orders = None
        
        # Note: in_no_trades_window and current_window were already checked at the start of job()
        # If we made it this far, we're either not in a no-trade window, or we have an active position needing force close
        
        # Check if it's time to force close all positions
        # Force close should only apply if we're in a no-new-trades window AND past the force_close_time
        should_force_close = False
        
        if in_no_trades_window and current_time >= force_close:
            should_force_close = True
            logging.debug(f"In no-new-trades window '{current_window}' and past force close time - should_force_close={should_force_close}")
        
        if should_force_close:
            if current_position_type in ['long', 'short'] and position_details:
                logging.info(f"FORCE CLOSE TIME REACHED ({force_close_time}) - Closing all positions immediately")
                close_position(position_details, topstep_config, enable_trading, auth_token, execute_trades, telegram_config, 
                             f"Force close at {force_close_time} end-of-day rule", daily_context)
                return  # Exit after force close
            else:
                logging.info(f"Force close time reached ({force_close_time}) but no active positions to close")
                # Continue to check if we're past no_new_trades_end_time to resume trading
        
        # Log working orders info
        if working_orders:
            if isinstance(working_orders, list):
                logging.info(f"Found {len(working_orders)} working order(s)")
            elif isinstance(working_orders, dict) and 'orders' in working_orders:
                orders_list = working_orders.get('orders', [])
                logging.info(f"Found {len(orders_list)} working order(s)")
            else:
                logging.info("Working orders retrieved but format unclear")
        else:
            logging.info("No working orders returned (may be none or query failed)")
        
        # If we have an active position, manage it instead of looking for new entries
        if current_position_type in ['long', 'short'] and position_details:
            logging.info(f"Managing active {current_position_type} position...")
            logging.info(f"Position details: Size={position_details.get('size')}, "
                        f"Avg Price={position_details.get('average_price')}, "
                        f"Unrealized P&L={position_details.get('unrealized_pnl')}")
            
            # Take screenshot for position management
            try:
                image_base64 = capture_screenshot(window_title, window_process_name, top_offset, bottom_offset, left_offset, right_offset, save_folder, enable_save_screenshots)
            except (ValueError, Exception) as e:
                logging.error(f"Failed to capture Bookmap screenshot: {e}")
                logging.warning("Bookmap screenshot not available - skipping all LLM and trading processing for this cycle")
                return  # Exit early, scheduler will retry on next interval
            
            # Fetch bar data and generate market data JSON
            try:
                contract_id = topstep_config.get('contract_id', '')
                bars_result = get_bars_for_llm(contract_id, topstep_config, auth_token)
                raw_bars = bars_result.get('bars', [])
                
                # Generate structured JSON market data
                market_data_json = generate_market_data_json(
                    raw_bars,
                    daily_context,
                    current_position_type,
                    position_details,
                    working_orders,
                    contract_id,
                    upcoming_events=upcoming_events
                )
                
                # TEMPORARY: Send only JSON format (disabled text blob market context)
                json_section = f"\n\nMarket Data JSON:\n{market_data_json}\n"
                daily_context_with_bars = json_section  # Temporarily disabled: daily_context + json_section
            except Exception as e:
                logging.warning(f"Error fetching bar data (non-critical): {e}")
                daily_context_with_bars = daily_context
            
            # Format prompt with position details
            # Use the pre-loaded global variable (which has the file content, not the path)
            
            # Check if we're managing runners (position size equals runners_quantity)
            runners_qty = topstep_config.get('runners_quantity', 0)
            current_position_size = position_details.get('size', 0) if position_details else 0
            is_managing_runners = (runners_qty > 0 and current_position_size == runners_qty)
            
            if is_managing_runners:
                # Use runner prompt for managing runner contracts
                position_prompt_template = runner_prompt
                logging.info(f"Managing RUNNERS position ({current_position_size} contract(s))")
            else:
                # Use regular position prompt (long/short)
                position_prompt_template = long_position_prompt if current_position_type == 'long' else short_position_prompt
                logging.info(f"Managing position ({current_position_size} contract(s))")
            
            # Parse working orders to get current stop loss and take profit
            contract_id = topstep_config.get('contract_id', '')
            order_info = parse_working_orders(working_orders, contract_id)
            current_stop_loss = order_info.get('stop_loss_price', 'Not set')
            current_take_profit = order_info.get('take_profit_price', 'Not set')
            
            # Get entry reasoning from active_trade.json
            trade_info = get_active_trade_info()
            entry_reasoning = "Not available"
            if trade_info:
                entry_reasoning = trade_info.get('reasoning', 'Not available')
            
            # Add position data to prompt
            # Format key_levels text for prompt
            key_levels_text = format_key_levels_for_prompt(LAST_KEY_LEVELS)
            
            # Format the position prompt with available template variables (using safe formatting)
            position_prompt = safe_format_prompt(
                position_prompt_template,
                symbol=DISPLAY_SYMBOL,
                size=position_details.get('size', 0),
                average_price=position_details.get('average_price', 0),
                position_type=position_details.get('position_type', 'unknown'),
                quantity=position_details.get('quantity', 0),
                unrealized_pnl=position_details.get('unrealized_pnl', 0),
                current_stop_loss=current_stop_loss,
                current_take_profit=current_take_profit,
                Context=daily_context_with_bars,
                LLM_Context=get_llm_observations(),
                Reason=entry_reasoning,
                key_levels=key_levels_text
            )
            
            logging.info(f"Using position management prompt")
            logging.info(f"Current Stop Loss: {current_stop_loss}, Current Take Profit: {current_take_profit}")
            logging.info(f"Using context: {daily_context[:50]}..." if len(daily_context) > 50 else f"Using context: {daily_context}")
            
            # Get LLM advice on position management
            llm_response = upload_to_llm(image_base64, position_prompt, model, enable_llm, openai_api_url, openai_api_key)
            if llm_response:
                # Strip markdown if present
                llm_response = llm_response.strip()
                if llm_response.startswith('```json') and llm_response.endswith('```'):
                    llm_response = llm_response[7:-3].strip()
                elif llm_response.startswith('```') and llm_response.endswith('```'):
                    llm_response = llm_response[3:-3].strip()
                logging.info(f"Position Management LLM Response: {llm_response}")
                
                # Parse and execute position management action
                try:
                    advice = json.loads(llm_response)
                    action = advice.get('action', '').lower()
                    price_target = advice.get('price_target')
                    stop_loss = advice.get('stop_loss')
                    reasoning = advice.get('reasoning')
                    new_context = advice.get('context', '')
                    key_levels = advice.get('key_levels')
                    suggestion = advice.get('suggestion')
                    logging.info(f"Position Management Advice: Action={action}, Target={price_target}, Stop={stop_loss}, Reasoning={reasoning}, KeyLevels={len(key_levels) if key_levels else 0} levels")
                    
                    # Log LLM interaction to CSV
                    llm_response_time = datetime.datetime.now()
                    log_llm_interaction(
                        request_prompt=position_prompt,
                        response_text=llm_response,
                        action=action,
                        entry_price=None,  # Not applicable for position management
                        price_target=price_target,
                        stop_loss=stop_loss,
                        confidence=None,  # Not provided in position management
                        reasoning=reasoning,
                        context=daily_context,
                        key_levels=key_levels,
                        suggestion=suggestion
                    )
                    logging.info(f"LLM response logged and cached at {llm_response_time.strftime('%H:%M:%S')}")
                    
                    # Store key_levels for next iteration (persists across trades)
                    LAST_KEY_LEVELS = key_levels if key_levels else None
                    logging.info(f"Updated LAST_KEY_LEVELS to: {len(LAST_KEY_LEVELS) if LAST_KEY_LEVELS else 0} levels")
                    
                    # Update dashboard with latest LLM response
                    update_dashboard_data()
                    logging.info(f"Dashboard update scheduled immediately after LLM response")
                    
                    # Save updated context if it changed
                    if new_context:
                        save_daily_context(new_context, daily_context)
                    
                    # Handle position management actions
                    if action == 'close':
                        logging.info(f"LLM advises to CLOSE position. Reasoning: {reasoning}")
                        # Close the entire position by placing opposite market order
                        close_position(position_details, topstep_config, enable_trading, auth_token, execute_trades, telegram_config, reasoning, daily_context)
                    
                    elif action == 'scale':
                        logging.info(f"LLM advises to SCALE position. Reasoning: {reasoning}")
                        # Partially close the position (scale out)
                        execute_topstep_trade(action, None, price_target, stop_loss, topstep_config, enable_trading, current_position_type, auth_token, execute_trades, position_details, telegram_config, reasoning, None, daily_context)
                    
                    elif action == 'adjust' or (action == 'hold' and price_target and stop_loss):
                        logging.info(f"LLM advises to ADJUST stops/targets. New Target={price_target}, New Stop={stop_loss}. Reasoning: {reasoning}")
                        # Modify existing stop loss and take profit orders
                        modify_stops_and_targets(position_details, price_target, stop_loss, topstep_config, enable_trading, auth_token, execute_trades, current_position_type, working_orders, reasoning, daily_context)
                    
                    elif action == 'hold':
                        logging.info(f"LLM advises to HOLD position. Reasoning: {reasoning}")
                        # Do nothing, keep current position
                    
                    else:
                        logging.warning(f"Unknown position management action: {action}")
                except json.JSONDecodeError as e:
                    logging.error(f"Error parsing position management LLM response as JSON: {e}")
            
            return  # Done managing position, exit job
        
        # No position - check if we can still enter new trades (reuse in_no_trades_window from above)
        if in_no_trades_window:
            logging.info(f"In no-new-trades window '{current_window}' - Skipping entry analysis")
            return
        
        # No position - look for new entry opportunities
        logging.info("No active position - analyzing for new entry opportunities")
        logging.info(f"Using context: {daily_context[:50]}..." if len(daily_context) > 50 else f"Using context: {daily_context}")

        try:
            image_base64 = capture_screenshot(window_title, window_process_name, top_offset, bottom_offset, left_offset, right_offset, save_folder, enable_save_screenshots)
        except (ValueError, Exception) as e:
            logging.error(f"Failed to capture Bookmap screenshot: {e}")
            logging.warning("Bookmap screenshot not available - skipping all LLM and trading processing for this cycle")
            return  # Exit early, scheduler will retry on next interval
        
        # Fetch bar data and generate market data JSON
        try:
            contract_id = topstep_config.get('contract_id', '')
            bars_result = get_bars_for_llm(contract_id, topstep_config, auth_token)
            raw_bars = bars_result.get('bars', [])
            
            # Generate structured JSON market data
            market_data_json = generate_market_data_json(
                raw_bars,
                daily_context,
                current_position_type,
                position_details,
                working_orders,
                contract_id,
                upcoming_events=upcoming_events
            )
            
            # TEMPORARY: Send only JSON format (disabled text blob market context)
            json_section = f"\n\nMarket Data JSON:\n{market_data_json}\n"
            daily_context_with_bars = json_section  # Temporarily disabled: daily_context + json_section
        except Exception as e:
            logging.warning(f"Error fetching bar data (non-critical): {e}")
            daily_context_with_bars = daily_context
        
        # Select and format prompt based on current_position_type (using safe formatting)
        llm_observations = get_llm_observations()
        if current_position_type == 'none':
            # Format waiting_for text for prompt
            if LAST_WAITING_FOR:
                waiting_for_text = f"Previously waiting for: {LAST_WAITING_FOR}"
            else:
                waiting_for_text = "No previous conditions being tracked"
            
            # Format key_levels text for prompt
            key_levels_text = format_key_levels_for_prompt(LAST_KEY_LEVELS)
            
            prompt = safe_format_prompt(
                no_position_prompt, 
                symbol=DISPLAY_SYMBOL, 
                Context=daily_context_with_bars, 
                LLM_Context=llm_observations,
                waiting_for=waiting_for_text,
                key_levels=key_levels_text
            )
        elif current_position_type == 'long':
            prompt = safe_format_prompt(long_position_prompt, symbol=DISPLAY_SYMBOL, Context=daily_context_with_bars, LLM_Context=llm_observations)
        elif current_position_type == 'short':
            prompt = safe_format_prompt(short_position_prompt, symbol=DISPLAY_SYMBOL, Context=daily_context_with_bars, LLM_Context=llm_observations)
        else:
            logging.error(f"Invalid position_type: {current_position_type}")
            raise ValueError(f"Invalid position_type: {current_position_type}")

        llm_response = upload_to_llm(image_base64, prompt, model, enable_llm, openai_api_url, openai_api_key)
        if llm_response:
            # Strip markdown if present (e.g., ```json ... ```)
            llm_response = llm_response.strip()
            if llm_response.startswith('```json') and llm_response.endswith('```'):
                llm_response = llm_response[7:-3].strip()  # Remove ```json and trailing ```
            elif llm_response.startswith('```') and llm_response.endswith('```'):
                llm_response = llm_response[3:-3].strip()  # Remove generic ```
            logging.info(f"Cleaned LLM Response for parsing: {llm_response}")

            # Parse JSON response
            try:
                advice = json.loads(llm_response)
                action = advice.get('action')
                entry_price = advice.get('entry_price')
                price_target = advice.get('price_target')
                stop_loss = advice.get('stop_loss')
                reasoning = advice.get('reasoning')
                confidence = advice.get('confidence')
                new_context = advice.get('context', '')
                waiting_for = advice.get('waiting_for')
                key_levels = advice.get('key_levels')
                next_snapshot = advice.get('next_snapshot')
                suggestion = advice.get('suggestion')
                logging.info(f"Parsed Advice: Action={action}, Entry={entry_price}, Target={price_target}, Stop={stop_loss}, Confidence={confidence}, Reasoning={reasoning}, WaitingFor={waiting_for}, KeyLevels={len(key_levels) if key_levels else 0} levels, NextSnapshot={next_snapshot}s")

                # Log LLM interaction to CSV
                llm_response_time = datetime.datetime.now()
                log_llm_interaction(
                    request_prompt=prompt,
                    response_text=llm_response,
                    action=action,
                    entry_price=entry_price,
                    price_target=price_target,
                    stop_loss=stop_loss,
                    confidence=confidence,
                    reasoning=reasoning,
                    context=daily_context,
                    waiting_for=waiting_for,
                    key_levels=key_levels,
                    suggestion=suggestion
                )
                logging.info(f"LLM response logged and cached at {llm_response_time.strftime('%H:%M:%S')}")
                
                # Store waiting_for condition for next iteration
                LAST_WAITING_FOR = waiting_for if waiting_for else None
                logging.info(f"Updated LAST_WAITING_FOR to: {LAST_WAITING_FOR}")
                
                # Store key_levels for next iteration (persists across trades)
                LAST_KEY_LEVELS = key_levels if key_levels else None
                logging.info(f"Updated LAST_KEY_LEVELS to: {len(LAST_KEY_LEVELS) if LAST_KEY_LEVELS else 0} levels")
                
                # Store next_snapshot timing override (LLM-controlled dynamic interval)
                global NEXT_SNAPSHOT_OVERRIDE
                if next_snapshot and isinstance(next_snapshot, (int, float)) and next_snapshot > 0:
                    NEXT_SNAPSHOT_OVERRIDE = int(next_snapshot)
                    logging.info(f"🕐 LLM requested next snapshot in {NEXT_SNAPSHOT_OVERRIDE}s (overriding schedule)")
                else:
                    NEXT_SNAPSHOT_OVERRIDE = None
                    logging.debug("No next_snapshot override from LLM - using schedule")
                
                # Update dashboard with latest LLM response
                update_dashboard_data()
                logging.info(f"Dashboard update scheduled immediately after LLM response")

                # Save updated context if it changed
                if new_context:
                    save_daily_context(new_context, daily_context)

                # Execute trade based on action
                if action in ['buy', 'sell', 'scale', 'close', 'flatten']:
                    logging.info(f"Executing trade: {action}")
                    order_id, trade_position_type = execute_topstep_trade(action, entry_price, price_target, stop_loss, topstep_config, enable_trading, current_position_type, auth_token, execute_trades, None, telegram_config, reasoning, confidence, daily_context)
                    
                    # Clear waiting_for when entering a new position (buy/sell)
                    if action in ['buy', 'sell'] and order_id:
                        LAST_WAITING_FOR = None
                        logging.info("Cleared LAST_WAITING_FOR after entering new position")
                    
                    # For new entry trades (buy/sell), fetch actual stop/target from working orders
                    if action in ['buy', 'sell'] and order_id and enable_trading:
                        logging.info("Fetching working orders to get actual stop loss and take profit values...")
                        time.sleep(2)  # Wait for orders to be processed
                        
                        working_orders = get_working_orders(topstep_config, enable_trading, auth_token)
                        if working_orders and isinstance(working_orders, dict):
                            orders = working_orders.get('orders', [])
                            actual_stop_loss = None
                            actual_price_target = None
                            stop_loss_order_id = None
                            take_profit_order_id = None
                            
                            for order in orders:
                                order_type = order.get('type', 0)
                                stop_price = order.get('stopPrice')
                                limit_price = order.get('limitPrice')
                                order_order_id = order.get('id')
                                
                                # Type 4 = Stop order (stop loss)
                                if order_type == 4 and stop_price:
                                    actual_stop_loss = stop_price
                                    stop_loss_order_id = order_order_id
                                    logging.info(f"Found actual stop loss: {actual_stop_loss} (Order ID: {stop_loss_order_id})")
                                
                                # Type 1 = Limit order (take profit)
                                if order_type == 1 and limit_price:
                                    actual_price_target = limit_price
                                    take_profit_order_id = order_order_id
                                    logging.info(f"Found actual price target: {actual_price_target} (Order ID: {take_profit_order_id})")
                            
                            # Check if actual values differ from LLM suggestions
                            needs_modification = False
                            tolerance = 0.01  # Allow 0.01 point difference for rounding
                            
                            if stop_loss and actual_stop_loss:
                                diff = abs(float(stop_loss) - float(actual_stop_loss))
                                if diff > tolerance:
                                    logging.info(f"Stop loss differs: LLM suggested {stop_loss}, actual {actual_stop_loss} (diff: {diff:.2f})")
                                    needs_modification = True
                            
                            if price_target and actual_price_target:
                                diff = abs(float(price_target) - float(actual_price_target))
                                if diff > tolerance:
                                    logging.info(f"Price target differs: LLM suggested {price_target}, actual {actual_price_target} (diff: {diff:.2f})")
                                    needs_modification = True
                            
                            # If values differ, modify the orders to match LLM suggestions
                            if needs_modification and execute_trades:
                                logging.info("="*80)
                                logging.info("MODIFYING ORDERS TO MATCH LLM SUGGESTIONS")
                                logging.info(f"LLM suggested - Stop: {stop_loss}, Target: {price_target}")
                                logging.info(f"Actual placed - Stop: {actual_stop_loss}, Target: {actual_price_target}")
                                logging.info("="*80)
                                
                                # Get position details
                                position_details = {
                                    'size': topstep_config.get('quantity', 1),
                                    'symbol': symbol,
                                    'average_price': entry_price,
                                    'position_type': trade_position_type
                                }
                                
                                # Modify the orders
                                base_url = topstep_config['base_url']
                                modify_order_endpoint = topstep_config.get('modify_order_endpoint', '/api/Order/modify')
                                headers = {
                                    'Authorization': f'Bearer {auth_token}',
                                    'Content-Type': 'application/json'
                                }
                                modify_url = base_url + modify_order_endpoint
                                account_id = topstep_config['account_id']
                                
                                # Modify stop loss if needed
                                if stop_loss and stop_loss_order_id and abs(float(stop_loss) - float(actual_stop_loss)) > tolerance:
                                    stop_loss_payload = {
                                        "accountId": int(account_id),
                                        "orderId": int(stop_loss_order_id),
                                        "stopPrice": float(stop_loss)
                                    }
                                    
                                    try:
                                        logging.info(f"Modifying stop loss order {stop_loss_order_id} from {actual_stop_loss} to {stop_loss}")
                                        sl_response = requests.post(modify_url, headers=headers, json=stop_loss_payload, timeout=10)
                                        sl_response_data = sl_response.json()
                                        
                                        if sl_response_data.get('success', True):
                                            logging.info(f"✅ Successfully modified stop loss to {stop_loss}")
                                            actual_stop_loss = stop_loss  # Update to modified value
                                        else:
                                            logging.error(f"❌ Failed to modify stop loss: {sl_response_data.get('errorMessage')}")
                                    except Exception as e:
                                        logging.error(f"Error modifying stop loss: {e}")
                                
                                # Modify take profit if needed
                                if price_target and take_profit_order_id and abs(float(price_target) - float(actual_price_target)) > tolerance:
                                    take_profit_payload = {
                                        "accountId": int(account_id),
                                        "orderId": int(take_profit_order_id),
                                        "limitPrice": float(price_target)
                                    }
                                    
                                    try:
                                        logging.info(f"Modifying take profit order {take_profit_order_id} from {actual_price_target} to {price_target}")
                                        tp_response = requests.post(modify_url, headers=headers, json=take_profit_payload, timeout=10)
                                        tp_response_data = tp_response.json()
                                        
                                        if tp_response_data.get('success', True):
                                            logging.info(f"✅ Successfully modified take profit to {price_target}")
                                            actual_price_target = price_target  # Update to modified value
                                        else:
                                            logging.error(f"❌ Failed to modify take profit: {tp_response_data.get('errorMessage')}")
                                    except Exception as e:
                                        logging.error(f"Error modifying take profit: {e}")
                                
                                logging.info("="*80)
                            
                            # Update LATEST_LLM_DATA with final values (either actual or modified)
                            if actual_stop_loss or actual_price_target:
                                global LATEST_LLM_DATA
                                if LATEST_LLM_DATA:
                                    logging.info(f"BEFORE UPDATE - LATEST_LLM_DATA: Target={LATEST_LLM_DATA.get('price_target')}, Stop={LATEST_LLM_DATA.get('stop_loss')}")
                                    if actual_stop_loss:
                                        LATEST_LLM_DATA['stop_loss'] = actual_stop_loss
                                    if actual_price_target:
                                        LATEST_LLM_DATA['price_target'] = actual_price_target
                                    logging.info(f"AFTER UPDATE - LATEST_LLM_DATA: Target={LATEST_LLM_DATA.get('price_target')}, Stop={LATEST_LLM_DATA.get('stop_loss')}")
                                    logging.info(f"Updated LLM data with final values - Stop: {actual_stop_loss}, Target: {actual_price_target}")
                                    
                                    # Also update active_trade.json with final values
                                    save_active_trade_info(
                                        order_id=order_id,
                                        entry_price=entry_price if entry_price else 0,
                                        position_type=trade_position_type,
                                        entry_timestamp=datetime.datetime.now().isoformat(),
                                        stop_loss=actual_stop_loss,
                                        price_target=actual_price_target,
                                        reasoning=reasoning,
                                        stop_loss_order_id=stop_loss_order_id,
                                        take_profit_order_id=take_profit_order_id
                                    )
                                    
                                    # Update dashboard with corrected values
                                    update_dashboard_data()
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing LLM response as JSON: {e}")
    except ValueError as e:
        logging.error(f"Error: {e}")

def get_working_orders(topstep_config, enable_trading, auth_token=None):
    """Query Topstep API for all working orders."""
    if not enable_trading:
        logging.debug("Trading disabled - Skipping working orders query")
        return None
    
    if not auth_token:
        logging.error("No auth token available for working orders query")
        return None
    
    base_url = topstep_config['base_url']
    working_orders_endpoint = topstep_config.get('working_orders_endpoint', '/api/Order/searchOpen')
    account_id = topstep_config.get('account_id', '')
    
    if not account_id:
        logging.error("No account_id configured for working orders query")
        return None
    
    url = base_url + working_orders_endpoint
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "accountId": int(account_id)
    }
    
    logging.info("=== FETCHING WORKING ORDERS ===")
    logging.info(f"Account ID: {account_id}")
    logging.info(f"Working Orders URL: {url}")
    logging.info(f"Payload: {json.dumps(payload)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        orders = response.json()
        
        # Log the full JSON response
        logging.info("="*80)
        logging.info("WORKING ORDERS API RESPONSE:")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Response Type: {type(orders)}")
        logging.info("Full JSON Response:")
        logging.info(json.dumps(orders, indent=2) if isinstance(orders, (dict, list)) else str(orders))
        logging.info("="*80)
        
        return orders
        
    except requests.exceptions.Timeout:
        logging.error("Working orders query timed out")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error querying working orders: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error querying working orders: {e}")
        logging.exception("Full traceback:")
        return None

def get_current_position(symbol, topstep_config, enable_trading, auth_token=None, return_details=False):
    """Query Topstep API for current position of the symbol and determine type (or mock if disabled).
    
    Args:
        return_details: If True, returns (position_type, position_details, working_orders) tuple instead of just position_type
    
    Note:
        Working orders are only fetched if an active position exists (optimization to reduce API calls)
    """
    if not enable_trading:
        logging.info("Trading disabled - Mock positions query: Returning 'none'")
        return ('none', None, None) if return_details else 'none'

    if not auth_token:
        logging.error("No auth token available for positions query")
        return ('none', None, None) if return_details else 'none'

    base_url = topstep_config['base_url']
    positions_endpoint = topstep_config.get('positions_endpoint', '/positions')
    account_id = topstep_config.get('account_id', '')
    contract_id = topstep_config.get('contract_id', '')
    
    if not account_id:
        logging.error("No account_id configured for positions query")
        return ('none', None, None) if return_details else 'none'

    url = base_url + positions_endpoint

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "accountId": int(account_id)
    }

    # Debug logging
    logging.info("=== FETCHING POSITIONS ===")
    logging.info(f"Positions URL: {url}")
    logging.info(f"Auth Token: {auth_token[:20]}..." if auth_token else "None")
    logging.info(f"Headers: {headers}")
    logging.info(f"Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        positions = response.json()
        
        # Log the full JSON response for debugging
        logging.info("="*80)
        logging.info("POSITIONS API RESPONSE:")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Response Type: {type(positions)}")
        logging.info("Full JSON Response:")
        logging.info(json.dumps(positions, indent=2) if isinstance(positions, (dict, list)) else str(positions))
        logging.info("="*80)
        
        # Handle different response formats
        if isinstance(positions, str):
            logging.error(f"Unexpected string response from positions API: {positions}")
            return ('none', None, None) if return_details else 'none'
        
        # If response is a list of positions
        if isinstance(positions, list):
            if len(positions) == 0:
                logging.info("No positions found (empty list)")
                return ('none', None, None) if return_details else 'none'
            
            for pos in positions:
                if not isinstance(pos, dict):
                    logging.error(f"Position item is not a dictionary: {type(pos)} - {pos}")
                    continue
                    
                pos_symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract')
                quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                
                if pos_symbol == symbol or pos_symbol == contract_id:
                    logging.info(f"Found matching position: symbol={pos_symbol}, quantity={quantity}")
                    if quantity > 0:
                        return ('long', None) if return_details else 'long'
                    elif quantity < 0:
                        return ('short', None, None) if return_details else 'short'
                    else:
                        return ('none', None, None) if return_details else 'none'
            
            logging.info(f"No matching position found for symbol {symbol}")
            return ('none', None, None) if return_details else 'none'
        
        # If response is a single dict (not a list)
        elif isinstance(positions, dict):
            # Check if it's a wrapper with a 'positions' key (TopstepX format)
            if 'positions' in positions and isinstance(positions['positions'], list):
                positions_list = positions['positions']
                logging.info(f"DEBUG: Found {len(positions_list)} position(s) in response")
                
                if len(positions_list) == 0:
                    logging.info("No positions found (empty positions list)")
                    return ('none', None, None) if return_details else 'none'
                
                # Log all positions for debugging
                logging.info("DEBUG: All positions in response:")
                for idx, pos in enumerate(positions_list):
                    if isinstance(pos, dict):
                        pos_symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract')
                        quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                        logging.info(f"  Position {idx+1}: symbol={pos_symbol}, quantity={quantity}, full={pos}")
                    else:
                        logging.info(f"  Position {idx+1}: Not a dict - {type(pos)} - {pos}")
                
                logging.info(f"DEBUG: Looking for symbol='{symbol}' or contract_id='{contract_id}'")
                
                for pos in positions_list:
                    if not isinstance(pos, dict):
                        continue
                    pos_symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract')
                    quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                    
                    logging.info(f"DEBUG: Comparing '{pos_symbol}' with '{symbol}' or '{contract_id}'")
                    
                    if pos_symbol == symbol or pos_symbol == contract_id:
                        # Get position type: 1 = Long, 2 = Short
                        position_type_code = pos.get('type') or pos.get('positionType')
                        
                        logging.info(f"MATCH FOUND: symbol={pos_symbol}, quantity={quantity}, type={position_type_code}")
                        
                        # Determine if long or short based on type field
                        if position_type_code == 1:
                            position_type_str = 'long'
                        elif position_type_code == 2:
                            position_type_str = 'short'
                        else:
                            # Fallback to quantity-based detection if type field not present
                            if quantity > 0:
                                position_type_str = 'long'
                            elif quantity < 0:
                                position_type_str = 'short'
                            else:
                                position_type_str = 'none'
                        
                        # Extract position details
                        position_details = {
                            'symbol': pos_symbol,
                            'size': abs(quantity),  # Always positive
                            'quantity': quantity,
                            'position_type': position_type_str,
                            'average_price': pos.get('averagePrice') or pos.get('avgPrice') or pos.get('entryPrice') or 0,
                            'unrealized_pnl': pos.get('unrealizedPnl') or pos.get('unrealizedPL') or pos.get('pnl') or 0,
                            'type_code': position_type_code,
                            'rawPosition': pos  # Full position object for reference
                        }
                        
                        logging.info(f"Returning '{position_type_str}' (type={position_type_code}, size={abs(quantity)})")
                        
                        # Fetch working orders only if position exists and details requested
                        working_orders = None
                        if return_details and enable_trading and auth_token:
                            logging.info("Active position detected - fetching working orders")
                            working_orders = get_working_orders(topstep_config, enable_trading, auth_token)
                        
                        return (position_type_str, position_details, working_orders) if return_details else position_type_str
                
                logging.info(f"No matching position found for symbol {symbol} in positions list")
                return ('none', None, None) if return_details else 'none'
            
            # Check if it's a wrapper with a 'data' key
            elif 'data' in positions and isinstance(positions['data'], list):
                positions_list = positions['data']
                if len(positions_list) == 0:
                    logging.info("No positions found (empty data list)")
                    return ('none', None, None) if return_details else 'none'
                
                for pos in positions_list:
                    if not isinstance(pos, dict):
                        continue
                    pos_symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract')
                    quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                    
                    if pos_symbol == symbol or pos_symbol == contract_id:
                        # Get position type: 1 = Long, 2 = Short
                        position_type_code = pos.get('type') or pos.get('positionType')
                        
                        logging.info(f"Found matching position: symbol={pos_symbol}, quantity={quantity}, type={position_type_code}")
                        
                        # Determine if long or short based on type field
                        if position_type_code == 1:
                            position_type_str = 'long'
                        elif position_type_code == 2:
                            position_type_str = 'short'
                        else:
                            # Fallback to quantity-based detection
                            if quantity > 0:
                                position_type_str = 'long'
                            elif quantity < 0:
                                position_type_str = 'short'
                            else:
                                position_type_str = 'none'
                        
                        position_details = {
                            'symbol': pos_symbol,
                            'size': abs(quantity),
                            'quantity': quantity,
                            'position_type': position_type_str,
                            'average_price': pos.get('averagePrice') or pos.get('avgPrice') or pos.get('entryPrice') or 0,
                            'unrealized_pnl': pos.get('unrealizedPnl') or pos.get('unrealizedPL') or pos.get('pnl') or 0,
                            'type_code': position_type_code,
                            'rawPosition': pos
                        }
                        
                        # Fetch working orders only if position exists and details requested
                        working_orders = None
                        if return_details and enable_trading and auth_token:
                            logging.info("Active position detected - fetching working orders")
                            working_orders = get_working_orders(topstep_config, enable_trading, auth_token)
                        
                        return (position_type_str, position_details, working_orders) if return_details else position_type_str
                
                logging.info(f"No matching position found for symbol {symbol} in data list")
                return ('none', None, None) if return_details else 'none'
            
            # Check if it's a single position object
            else:
                pos_symbol = positions.get('symbol') or positions.get('contractId') or positions.get('contract')
                quantity = positions.get('quantity', 0) or positions.get('size', 0) or positions.get('netQuantity', 0)
                
                if pos_symbol and (pos_symbol == symbol or pos_symbol == contract_id):
                    # Get position type: 1 = Long, 2 = Short
                    position_type_code = positions.get('type') or positions.get('positionType')
                    
                    logging.info(f"Found matching position: symbol={pos_symbol}, quantity={quantity}, type={position_type_code}")
                    
                    # Determine if long or short based on type field
                    if position_type_code == 1:
                        position_type_str = 'long'
                    elif position_type_code == 2:
                        position_type_str = 'short'
                    else:
                        # Fallback to quantity-based detection
                        if quantity > 0:
                            position_type_str = 'long'
                        elif quantity < 0:
                            position_type_str = 'short'
                        else:
                            position_type_str = 'none'
                    
                    position_details = {
                        'symbol': pos_symbol,
                        'size': abs(quantity),
                        'quantity': quantity,
                        'position_type': position_type_str,
                        'average_price': positions.get('averagePrice') or positions.get('avgPrice') or positions.get('entryPrice') or 0,
                        'unrealized_pnl': positions.get('unrealizedPnl') or positions.get('unrealizedPL') or positions.get('pnl') or 0,
                        'type_code': position_type_code,
                        'rawPosition': positions
                    }
                    
                    # Fetch working orders only if position exists and details requested
                    working_orders = None
                    if return_details and enable_trading and auth_token:
                        logging.info("Active position detected - fetching working orders")
                        working_orders = get_working_orders(topstep_config, enable_trading, auth_token)
                    
                    return (position_type_str, position_details, working_orders) if return_details else position_type_str
                else:
                    logging.info(f"No positions found - response indicates no open positions")
                    return ('none', None, None) if return_details else 'none'
        
        else:
            logging.error(f"Unexpected positions response type: {type(positions)}")
            return ('none', None, None) if return_details else 'none'
            
    except requests.exceptions.Timeout:
        logging.error("Positions query timed out")
        return ('none', None, None) if return_details else 'none'
    except requests.exceptions.RequestException as e:
        logging.error(f"Error querying positions: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
        return ('none', None, None) if return_details else 'none'
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse positions response as JSON: {e}")
        logging.error(f"Raw response: {response.text}")
        return ('none', None, None) if return_details else 'none'
    except Exception as e:
        logging.error(f"Unexpected error querying positions: {e}")
        logging.exception("Full traceback:")
        return ('none', None, None) if return_details else 'none'

def check_active_trades(topstep_config, enable_trading, auth_token=None):
    """Check if there are any active open positions - returns True if positions are active."""
    if not enable_trading:
        logging.debug("Trading disabled - No active trades check needed")
        return False

    if not auth_token:
        logging.error("No auth token available for active trades check")
        return False

    base_url = topstep_config['base_url']
    account_id = topstep_config.get('account_id', '')
    
    if not account_id:
        logging.error("No account_id configured for active trades check")
        return False
    
    logging.debug(f"DEBUG: Checking active trades for account {account_id}")

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "accountId": int(account_id)
    }

    try:
        # Check for active positions FIRST
        positions_endpoint = topstep_config.get('positions_endpoint', '/positions')
        positions_url = base_url + positions_endpoint
        
        logging.debug(f"DEBUG: Querying {positions_url} with payload {payload}")
        
        response = requests.post(positions_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        positions = response.json()
        
        # Log the full JSON response for debugging
        logging.info("="*80)
        logging.info("CHECK ACTIVE TRADES - API RESPONSE:")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Response Type: {type(positions)}")
        logging.info("Full JSON Response:")
        logging.info(json.dumps(positions, indent=2) if isinstance(positions, (dict, list)) else str(positions))
        logging.info("="*80)
        
        # Handle different response formats
        if isinstance(positions, str):
            logging.error(f"Unexpected string response from positions API: {positions}")
            return False
        
        # Track if we found any active positions
        has_active_position = False
        
        # If positions is a list and has any items with non-zero quantity, we have active trades
        if isinstance(positions, list) and len(positions) > 0:
            for pos in positions:
                if not isinstance(pos, dict):
                    logging.error(f"Position item is not a dictionary: {type(pos)} - {pos}")
                    continue
                
                quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                if quantity != 0:
                    symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract', 'Unknown')
                    logging.info(f"Active position found: {symbol} with quantity {quantity}")
                    has_active_position = True
                    break
        
        # If response is a single dict with positions data
        elif isinstance(positions, dict):
            # Check for 'positions' key (TopstepX format)
            if 'positions' in positions and isinstance(positions['positions'], list):
                positions_list = positions['positions']
                logging.debug(f"DEBUG (check_active_trades): Found {len(positions_list)} position(s)")
                
                for idx, pos in enumerate(positions_list):
                    if not isinstance(pos, dict):
                        continue
                    quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                    symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract', 'Unknown')
                    logging.debug(f"  Position {idx+1}: symbol={symbol}, quantity={quantity}")
                    
                    if quantity != 0:
                        logging.info(f"Active position found: {symbol} with quantity {quantity}")
                        has_active_position = True
                        break
            # Check for 'data' key
            elif 'data' in positions and isinstance(positions['data'], list):
                for pos in positions['data']:
                    if not isinstance(pos, dict):
                        continue
                    quantity = pos.get('quantity', 0) or pos.get('size', 0) or pos.get('netQuantity', 0)
                    if quantity != 0:
                        symbol = pos.get('symbol') or pos.get('contractId') or pos.get('contract', 'Unknown')
                        logging.info(f"Active position found: {symbol} with quantity {quantity}")
                        has_active_position = True
                        break
        
        # Only fetch working orders if we have an active position
        if has_active_position:
            logging.info("Active position detected - Fetching working orders")
            working_orders = get_working_orders(topstep_config, enable_trading, auth_token)
            return True
        
        # DISABLED: Check for working orders (uncomment to re-enable)
        # orders_endpoint = topstep_config.get('working_orders_endpoint', '/api/Order/searchWorking')
        # orders_url = base_url + orders_endpoint
        # 
        # response = requests.post(orders_url, headers=headers, json=payload, timeout=10)
        # response.raise_for_status()
        # orders = response.json()
        # 
        # # If orders is a list and has any items, we have active orders
        # if isinstance(orders, list) and len(orders) > 0:
        #     logging.info(f"Found {len(orders)} working order(s)")
        #     return True
        
        logging.debug("No active positions found")
        logging.info("No active trades - OK to analyze new screenshots")
        return False
        
    except requests.exceptions.Timeout:
        logging.error("Active trades check timed out")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error checking active trades: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error checking active trades: {e}")
        return False

def execute_topstep_trade(action, entry_price, price_target, stop_loss, topstep_config, enable_trading, position_type='none', auth_token=None, execute_trades=False, position_details=None, telegram_config=None, reasoning=None, confidence=None, market_context=None):
    """Execute trade via Topstep API based on action with stop loss and take profit (or mock/log details if disabled).
    
    Returns:
        tuple: (order_id, position_type) for buy/sell actions, (None, None) otherwise
    """
    logging.info(f"Preparing to execute trade: {action} with entry {entry_price}, target {price_target} and stop {stop_loss}")
    
    # Get configuration values
    account_id = topstep_config.get('account_id', '')
    if not account_id:
        logging.error("No account_id configured - cannot place order")
        return (None, None)
    
    # Get contract ID from config or from the available contracts
    contract_id = topstep_config.get('contract_id', '')
    
    # If not in config, try to get it from available contracts
    if not contract_id:
        contracts = topstep_config.get('available_contracts', [])
        if contracts and isinstance(contracts, list) and len(contracts) > 0:
            contract_id = contracts[0].get('symbol', '') if isinstance(contracts[0], dict) else ''
    
    if not contract_id:
        logging.error("No contract ID available - cannot place order")
        logging.error("Please set contract_id in config.ini or ensure contract search was successful on startup")
        return (None, None)
    
    # Get order size
    if action == 'scale':
        # For scaling, calculate how many to close: quantity - runners_quantity
        runners_qty = int(topstep_config.get('runners_quantity', 0))
        total_qty = int(topstep_config.get('quantity', 1))
        
        # Validate runner configuration
        if runners_qty >= total_qty:
            logging.warning(f"Invalid runners config: runners_quantity ({runners_qty}) >= quantity ({total_qty}). Treating as no runners (closing all).")
            runners_qty = 0
        
        # For scaling, use actual position size if available, otherwise fall back to config
        if position_details and position_details.get('size'):
            actual_size = int(position_details.get('size'))
            if runners_qty == 0:
                # No runners mode - scale closes entire position
                size = actual_size
                logging.info(f"Scaling (no runners): Closing all {size} contracts")
            else:
                # Calculate close quantity: quantity - runners_quantity
                size = actual_size - runners_qty
                if size <= 0:
                    logging.error(f"Scale calculation error: actual_size ({actual_size}) - runners_qty ({runners_qty}) = {size} (must be > 0)")
                    return (None, None)
                logging.info(f"Scaling: Closing {size} of {actual_size} contracts (leaving {runners_qty} runners)")
        else:
            if runners_qty == 0:
                # No runners mode - use config quantity
                size = total_qty
                logging.warning(f"Scaling (no runners): No position details, using config quantity = {size}")
            else:
                size = total_qty - runners_qty
                if size <= 0:
                    logging.error(f"Scale calculation error: total_qty ({total_qty}) - runners_qty ({runners_qty}) = {size} (must be > 0)")
                    return (None, None)
                logging.warning(f"Scaling: No position details available, using config quantity - runners = {size}")
    else:
        size = int(topstep_config['quantity'])
    
    # Determine order side based on action
    # side: 0 = bid (buy), 1 = ask (sell)
    if action == 'buy':
        side = 0  # Bid (buy)
    elif action == 'sell':
        side = 1  # Ask (sell)
    elif action == 'close':
        # Close position: if long, sell; if short, buy
        if position_type == 'long':
            side = 1  # Ask (sell to close long)
        elif position_type == 'short':
            side = 0  # Bid (buy to close short)
        else:
            logging.error("Close action requires long or short position_type")
            return (None, None)
        # For close action, use actual position size if available
        if position_details and position_details.get('size'):
            size = int(position_details.get('size'))
            logging.info(f"Closing: Using actual position size of {size} contracts")
    elif action == 'scale':
        # Scale position: if long, sell; if short, buy
        if position_type == 'long':
            side = 1  # Ask (sell to scale out long)
        elif position_type == 'short':
            side = 0  # Bid (buy to scale out short)
        else:
            logging.error("Scale action requires long or short position_type")
            return (None, None)
    elif action == 'flatten':
        logging.error("Flatten action not implemented - use close instead")
        return (None, None)
    else:
        logging.error(f"Unknown action: {action}")
        return (None, None)
    
    # Build the correct TopstepX API payload
    # Use market order for immediate execution
    order_type = 2  # Market order
    payload = {
        "accountId": int(account_id),
        "contractId": contract_id,
        "type": order_type,  # Market order
        "side": side,  # 0 = bid (buy), 1 = ask (sell)
        "size": size
    }
    logging.info(f"Using MARKET order for {action}")
    
    # Add stop loss and take profit brackets if enabled and provided
    # Only add these for entry orders (buy/sell), not for close/scale actions
    enable_sl = topstep_config.get('enable_stop_loss', True)
    enable_tp = topstep_config.get('enable_take_profit', True)
    
    if action in ['buy', 'sell']:
        # Calculate or use provided stop loss and take profit
        max_risk = topstep_config.get('max_risk_per_contract', '')
        max_profit = topstep_config.get('max_profit_per_contract', '')
        tick_size = topstep_config.get('tick_size', 0.25)
        
        # Calculate profit and risk distances from LLM if we have entry_price
        llm_profit_distance = None
        llm_risk_distance = None
        use_llm_profit = False
        use_llm_risk = False
        
        if entry_price and price_target and stop_loss:
            # Calculate distances in points from entry price
            llm_profit_distance = abs(float(price_target) - float(entry_price))
            llm_risk_distance = abs(float(stop_loss) - float(entry_price))
            
            logging.info(f"LLM suggests: Profit distance={llm_profit_distance:.2f} points, Risk distance={llm_risk_distance:.2f} points")
            
            # Compare with configured limits
            if max_profit and max_profit.strip():
                max_profit_points = float(max_profit)
                if llm_profit_distance > max_profit_points:
                    use_llm_profit = True
                    logging.info(f"LLM profit target ({llm_profit_distance:.2f} pts) is BETTER than config ({max_profit_points} pts) - Using LLM")
                else:
                    logging.info(f"Config profit target ({max_profit_points} pts) is better than LLM ({llm_profit_distance:.2f} pts) - Using config")
            else:
                use_llm_profit = True
                logging.info(f"No config profit limit - Using LLM profit target")
            
            if max_risk and max_risk.strip():
                max_risk_points = float(max_risk)
                if llm_risk_distance < max_risk_points:
                    use_llm_risk = True
                    logging.info(f"LLM stop loss ({llm_risk_distance:.2f} pts) is TIGHTER than config ({max_risk_points} pts) - Using LLM")
                else:
                    logging.info(f"Config stop loss ({max_risk_points} pts) is tighter than LLM ({llm_risk_distance:.2f} pts) - Using config")
            else:
                use_llm_risk = True
                logging.info(f"No config risk limit - Using LLM stop loss")
        
        # Build stopLossBracket object
        if enable_sl and (stop_loss or (max_risk and max_risk.strip())):
            stop_loss_bracket = {
                "type": 4  # 4 = Stop order
            }
            
            # Use LLM stop loss if it's tighter (better)
            if use_llm_risk and entry_price and stop_loss:
                # Calculate ticks from LLM distance
                stop_loss_ticks = int(llm_risk_distance / tick_size)
                
                # For long positions (side=0/buy), stop loss ticks should be negative (below entry)
                if side == 0:
                    stop_loss_ticks = -stop_loss_ticks
                
                stop_loss_bracket['ticks'] = stop_loss_ticks
                logging.info(f"Stop Loss Bracket set to: {stop_loss_ticks} ticks ({llm_risk_distance:.2f} points) from LLM")
            elif max_risk and max_risk.strip():
                # Use configured max risk in points
                max_risk_points = float(max_risk)
                # Calculate ticks from points
                stop_loss_ticks = int(max_risk_points / tick_size)
                
                # For long positions (side=0/buy), stop loss ticks should be negative (below entry)
                if side == 0:
                    stop_loss_ticks = -stop_loss_ticks
                
                stop_loss_bracket['ticks'] = stop_loss_ticks
                logging.info(f"Stop Loss Bracket set to: {stop_loss_ticks} ticks ({max_risk_points} points) from config")
            elif stop_loss:
                # Fallback: Use LLM suggestion as price
                stop_loss_bracket['price'] = float(stop_loss)
                logging.info(f"Stop Loss Bracket set to price: {stop_loss} (from LLM, no entry price available)")
            
            if stop_loss_bracket:
                payload['stopLossBracket'] = stop_loss_bracket
        
        # Build takeProfitBracket object
        if enable_tp and (price_target or (max_profit and max_profit.strip())):
            take_profit_bracket = {
                "type": 1  # 1 = Limit order
            }
            
            # Use LLM profit target if it's larger (better)
            if use_llm_profit and entry_price and price_target:
                # Calculate ticks from LLM distance
                take_profit_ticks = int(llm_profit_distance / tick_size)
                
                # For short positions (side=1/sell), take profit ticks should be negative
                if side == 1:
                    take_profit_ticks = -take_profit_ticks
                
                take_profit_bracket['ticks'] = take_profit_ticks
                logging.info(f"Take Profit Bracket set to: {take_profit_ticks} ticks ({llm_profit_distance:.2f} points) from LLM")
            elif max_profit and max_profit.strip():
                # Use configured max profit in points
                max_profit_points = float(max_profit)
                # Calculate ticks from points
                take_profit_ticks = int(max_profit_points / tick_size)
                
                # For short positions (side=1/sell), take profit ticks should be negative
                if side == 1:
                    take_profit_ticks = -take_profit_ticks
                
                take_profit_bracket['ticks'] = take_profit_ticks
                logging.info(f"Take Profit Bracket set to: {take_profit_ticks} ticks ({max_profit_points} points) from config")
            elif price_target:
                # Fallback: Use LLM suggestion as price
                take_profit_bracket['price'] = float(price_target)
                logging.info(f"Take Profit Bracket set to price: {price_target} (from LLM, no entry price available)")
            
            if take_profit_bracket:
                payload['takeProfitBracket'] = take_profit_bracket

    if not enable_trading:
        # Log full request details for testing
        base_url = topstep_config['base_url']
        url = base_url + topstep_config['buy_endpoint']  # All orders go to /api/Order/place endpoint
        headers = {"Authorization": f"Bearer {auth_token or '[AUTH_TOKEN]'}", "Content-Type": "application/json"}
        logging.info(f"Trading disabled - Mock request: URL={url}, Headers={headers}, Payload={json.dumps(payload, indent=2)}")
        return

    if not auth_token:
        logging.error("No auth token available for trade execution")
        return

    # Real execution code
    base_url = topstep_config['base_url']
    url = base_url + topstep_config['buy_endpoint']  # All orders go to /api/Order/place endpoint

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }

    # Debug logging
    logging.info("=== EXECUTING TRADE ===")
    logging.info(f"Trade URL: {url}")
    logging.info(f"Auth Token: {auth_token[:20]}..." if auth_token else "None")
    logging.info(f"Headers: {headers}")
    logging.info(f"Payload: {json.dumps(payload, indent=2)}")

    # Check if we should actually execute the trade or just log it
    if not execute_trades:
        logging.info("=== DRY RUN MODE - TRADE NOT EXECUTED ===")
        logging.info(f"Would execute {action} trade: {json.dumps(payload, indent=2)}")
        logging.info("Set execute_trades=true in config.ini to enable actual trade execution")
        return

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logging.info(f"Trade Response Status: {response.status_code}")
        logging.info(f"Trade Response Headers: {dict(response.headers)}")

        response.raise_for_status()
        trade_response = response.json()
        logging.info(f"Trade Response Body: {json.dumps(trade_response, indent=2)}")
        
        # Check for API error response (success: false, errorCode: 2)
        if isinstance(trade_response, dict):
            success = trade_response.get('success', True)
            error_code = trade_response.get('errorCode', 0)
            error_message = trade_response.get('errorMessage', 'Unknown error')
            
            # If error code is 2, show dialog with Continue/Exit options
            if not success and error_code == 2:
                logging.error("="*80)
                logging.error(f"DETECTED ERROR CODE 2: {error_message}")
                logging.error("Calling show_error_dialog()...")
                logging.error("="*80)
                show_error_dialog(error_message, error_code)
                logging.error("Returned from show_error_dialog()")
                return (None, None)  # Return after dialog (will exit if user chose Exit, continue if user chose Continue)
            
            # If other error, log it but continue
            if not success:
                logging.error(f"API returned error (code {error_code}): {error_message}")
                return (None, None)
        
        logging.info(f"Trade executed successfully: {action}")
        
        # Extract orderId from response if available
        order_id = None
        if isinstance(trade_response, dict):
            order_id = trade_response.get('orderId') or trade_response.get('id')
            if order_id:
                logging.info(f"Order ID from response: {order_id}")
        
        # Get updated account balance
        balance = get_account_balance(account_id, topstep_config, enable_trading, auth_token)
        
        # Log trade event to CSV
        if action in ['buy', 'sell']:
            # Entry event
            event_type = "ENTRY"
            trade_position_type = 'long' if action == 'buy' else 'short'
            
            # Log the entry with order_id
            log_trade_event(
                event_type=event_type,
                symbol=contract_id,
                position_type=trade_position_type,
                size=size,
                price=entry_price if entry_price else 0,  # Use entry price if available
                stop_loss=stop_loss,
                take_profit=price_target,
                reasoning=reasoning,
                confidence=confidence,
                balance=balance,
                market_context=market_context,
                order_id=order_id
            )
            
            # Save order ID and timestamp for later retrieval
            save_active_trade_info(
                order_id=order_id,
                entry_price=entry_price if entry_price else 0,
                position_type=trade_position_type,
                entry_timestamp=datetime.datetime.now().isoformat(),
                reasoning=reasoning
            )
            
            # Enable trade monitoring now that we have an active position
            enable_trade_monitoring(f"Position opened: {trade_position_type.upper()}")
            
            # Send Telegram notification for entry
            action_emoji = "🟢" if action == 'buy' else "🔴"
            telegram_msg = f"{action_emoji} <b>ORDER PLACED: {action.upper()}</b>\n"
            telegram_msg += f"Size: {size} contract(s)\n"
            telegram_msg += f"Symbol: {contract_id}\n"
            
            if entry_price:
                telegram_msg += f"Entry: {entry_price}\n"
            
            # Log stop loss and take profit bracket details if present
            if 'stopLossBracket' in payload:
                sl_bracket = payload['stopLossBracket']
                if 'ticks' in sl_bracket:
                    telegram_msg += f"Stop Loss: {sl_bracket['ticks']} ticks\n"
                elif 'price' in sl_bracket:
                    telegram_msg += f"Stop Loss: {sl_bracket['price']}\n"
            
            if 'takeProfitBracket' in payload:
                tp_bracket = payload['takeProfitBracket']
                if 'ticks' in tp_bracket:
                    telegram_msg += f"Take Profit: {tp_bracket['ticks']} ticks\n"
                elif 'price' in tp_bracket:
                    telegram_msg += f"Take Profit: {tp_bracket['price']}\n"
            
            if price_target:
                telegram_msg += f"Target: {price_target}\n"
            if stop_loss:
                telegram_msg += f"Stop: {stop_loss}\n"
            
            if balance is not None:
                telegram_msg += f"💰 Balance: ${balance:,.2f}\n"
            
            if reasoning:
                telegram_msg += f"📝 Reason: {reasoning}\n"
            
            if confidence is not None:
                telegram_msg += f"🎯 Confidence: {confidence}%\n"
            
            telegram_msg += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Send Telegram notification
            send_telegram_message(telegram_msg, telegram_config)
            logging.info(f"Telegram notification sent for {action.upper()} action")
            
            # Return order_id and position_type for buy/sell actions
            return (order_id, trade_position_type)
        elif action == 'scale':
            # Scale event (partial exit)
            trade_info = get_active_trade_info()
            if trade_info:
                scale_entry_price = trade_info.get('entry_price')
                scale_position_type = trade_info.get('position_type')
                # Calculate P&L for scaled portion
                if scale_entry_price:
                    price_diff = (float(entry_price) - float(scale_entry_price)) if scale_position_type == 'long' else (float(scale_entry_price) - float(entry_price))
                    profit_loss_points = price_diff
                    # Assuming ES multiplier of $50 per point
                    profit_loss = profit_loss_points * 50 * size
                else:
                    profit_loss_points = None
                    profit_loss = None
                
                log_trade_event(
                    event_type="SCALE",
                    symbol=contract_id,
                    position_type=scale_position_type,
                    size=size,
                    price=entry_price if entry_price else 0,
                    reasoning=reasoning,
                    profit_loss=profit_loss,
                    profit_loss_points=profit_loss_points,
                    balance=balance,
                    market_context=market_context,
                    order_id=trade_info.get('order_id'),
                    entry_price=scale_entry_price
                )
        
        # Build Telegram notification message for close/scale actions
        if action == 'close':
            action_emoji = "🔵"
            telegram_msg = f"{action_emoji} <b>POSITION CLOSED</b>\n"
        elif action == 'scale':
            action_emoji = "🟡"
            telegram_msg = f"{action_emoji} <b>POSITION SCALED OUT</b>\n"
        else:
            action_emoji = "🟢" if action in ['buy', 'long'] else "🔴" if action in ['sell', 'short'] else "⚪"
            action_text = action.upper()
            telegram_msg = f"{action_emoji} <b>ORDER PLACED: {action_text}</b>\n"
        telegram_msg += f"Size: {size} contract(s)\n"
        telegram_msg += f"Symbol: {contract_id}\n"
        
        if entry_price:
            telegram_msg += f"Entry: {entry_price}\n"
        
        # Log stop loss and take profit bracket details if present
        if 'stopLossBracket' in payload:
            sl_bracket = payload['stopLossBracket']
            if 'ticks' in sl_bracket:
                logging.info(f"Stop Loss bracket placed: {sl_bracket['ticks']} ticks")
                telegram_msg += f"Stop Loss: {sl_bracket['ticks']} ticks\n"
            elif 'price' in sl_bracket:
                logging.info(f"Stop Loss bracket placed at price: {sl_bracket['price']}")
                telegram_msg += f"Stop Loss: {sl_bracket['price']}\n"
        
        if 'takeProfitBracket' in payload:
            tp_bracket = payload['takeProfitBracket']
            if 'ticks' in tp_bracket:
                logging.info(f"Take Profit bracket placed: {tp_bracket['ticks']} ticks")
                telegram_msg += f"Take Profit: {tp_bracket['ticks']} ticks\n"
            elif 'price' in tp_bracket:
                logging.info(f"Take Profit bracket placed at price: {tp_bracket['price']}")
                telegram_msg += f"Take Profit: {tp_bracket['price']}\n"
        
        if price_target:
            telegram_msg += f"Target: {price_target}\n"
        if stop_loss:
            telegram_msg += f"Stop: {stop_loss}\n"
        
        if balance is not None:
            telegram_msg += f"💰 Balance: ${balance:,.2f}\n"
        
        if reasoning:
            telegram_msg += f"📝 Reason: {reasoning}\n"
        
        if confidence is not None:
            telegram_msg += f"🎯 Confidence: {confidence}%\n"
        
        telegram_msg += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Send Telegram notification
        send_telegram_message(telegram_msg, telegram_config)
        logging.info(f"Telegram notification sent for {action.upper()} action")
        
        # Return None for close/scale actions
        return (None, None)
            
    except requests.exceptions.Timeout:
        logging.error("Trade request timed out")
    except requests.exceptions.RequestException as e:
        logging.error(f"Trade request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
            # Try to parse error response for error code 2
            try:
                error_json = e.response.json()
                if isinstance(error_json, dict):
                    error_code = error_json.get('errorCode', 0)
                    error_message = error_json.get('errorMessage', str(e))
                    if error_code == 2:
                        logging.error("="*80)
                        logging.error(f"DETECTED ERROR CODE 2 in exception: {error_message}")
                        logging.error("Calling show_error_dialog()...")
                        logging.error("="*80)
                        show_error_dialog(error_message, error_code)
                        logging.error("Returned from show_error_dialog()")
            except:
                pass
    except Exception as e:
        logging.error(f"Error executing trade: {e}")

def login_topstep(topstep_config):
    """Authenticate with TopstepX API and retrieve access token."""
    base_url = topstep_config['base_url']
    user_name = topstep_config.get('user_name', topstep_config['api_key'])
    api_secret = topstep_config.get('api_secret', '')
    login_endpoint = topstep_config.get('login_endpoint', '/api/Auth/loginKey')

    url = base_url + login_endpoint
    headers = {
        "Content-Type": "application/json",
        "accept": "text/plain"
    }
    payload = {
        "userName": user_name,
        "apiKey": api_secret
    }

    # Debug logging
    logging.info("=== TOPSTEP LOGIN ATTEMPT ===")
    logging.info(f"Login URL: {url}")
    logging.info(f"Username: {user_name}")
    logging.info(f"API Secret (used as apikey): {api_secret[:10]}..." if api_secret else "None")
    logging.info(f"Login Headers: {headers}")
    logging.info(f"Login Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logging.info(f"Login Response Status: {response.status_code}")
        logging.info(f"Login Response Headers: {dict(response.headers)}")

        if response.status_code == 200:
            try:
                response_data = response.json()
                logging.info(f"Login Response Body: {json.dumps(response_data, indent=2)}")

                # Extract token from response - adjust based on actual API response structure
                token = response_data.get('token') or response_data.get('access_token') or response_data.get('auth_token')
                if token:
                    logging.info("Login successful - Token retrieved")
                    return token
                else:
                    logging.error("Login response does not contain token field")
                    logging.error(f"Available fields: {list(response_data.keys())}")
                    return None
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse login response as JSON: {e}")
                logging.error(f"Raw response: {response.text}")
                return None
        else:
            logging.error(f"Login failed with status {response.status_code}: {response.text}")
            return None

    except requests.exceptions.Timeout:
        logging.error("Login request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Login request failed: {e}")
        return None

def fetch_topstepx_bars(contract_id, start_time, end_time, topstep_config, auth_token, interval='5m'):
    """Fetch bar data from TopstepX /api/History/retrieveBars endpoint.
    
    Args:
        contract_id: Contract symbol (e.g., "CON.F.US.EP.Z25")
        start_time: Start timestamp as datetime object or ISO string
        end_time: End timestamp as datetime object or ISO string
        topstep_config: Topstep configuration dict
        auth_token: Auth token for API
        interval: Bar interval (default '5m')
    
    Returns:
        list: List of bar dicts with keys {t, o, h, l, c, v} or None on error
    """
    try:
        base_url = topstep_config['base_url']
        endpoint = '/api/History/retrieveBars'
        url = base_url + endpoint
        
        # Convert datetime to UTC ISO format (handle both datetime and string inputs)
        if isinstance(start_time, str):
            start_time_str = start_time
        else:
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        if isinstance(end_time, str):
            end_time_str = end_time
        else:
            end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        # Build request payload
        payload = {
            "contractId": contract_id,
            "live": False,
            "startTime": start_time_str,
            "endTime": end_time_str,
            "unit": 2,  # Minutes
            "unitNumber": 5,  # 5 minutes
            "limit": 200,  # Max bars to fetch
            "includePartialBar": True  # Only complete bars
        }
        
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
        
        logging.info("=" * 80)
        logging.info("FETCHING BARS FROM TOPSTEPX API")
        logging.info("=" * 80)
        logging.info(f"Bar fetch URL: {url}")
        logging.info(f"Time range: {start_time_str} to {end_time_str}")
        logging.info(f"Auth token: {auth_token[:20]}..." if auth_token else "None")
        logging.info("Request payload:")
        logging.info(json.dumps(payload, indent=2))
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        logging.info("=" * 80)
        logging.info("BAR FETCH API RESPONSE")
        logging.info("=" * 80)
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Response Headers: {dict(response.headers)}")
        
        response.raise_for_status()
        result = response.json()
        
        logging.info("Response Body:")
        logging.info(json.dumps(result, indent=2))
        logging.info("=" * 80)
        
        # Check for API errors
        if not result.get('success', True):
            error_code = result.get('errorCode', 0)
            error_message = result.get('errorMessage', 'Unknown error')
            logging.error(f"Bar fetch failed: {error_message} (code: {error_code})")
            return None
        
        bars = result.get('bars', [])
        logging.info(f"Successfully fetched {len(bars)} bars")
        if bars:
            logging.info(f"First bar timestamp: {bars[0].get('t')}")
            logging.info(f"Last bar timestamp: {bars[-1].get('t')}")
        return bars
        
    except Exception as e:
        logging.error(f"Error fetching bars from TopstepX: {e}")
        logging.exception("Full traceback:")
        return None

def get_cached_bars(date_str):
    """Read cached bars from /cache/bars/YYYYMMDD.json.
    
    Args:
        date_str: Date string in YYYYMMDD format
    
    Returns:
        dict: Cache data with keys {date, contract_id, interval, bars, last_fetched} or None
    """
    try:
        cache_folder = 'cache/bars'
        cache_file = os.path.join(cache_folder, f"{date_str}.json")
        
        if not os.path.exists(cache_file):
            logging.debug(f"No cache file found for {date_str}")
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        logging.info(f"Loaded {len(cache_data.get('bars', []))} cached bars from {cache_file}")
        return cache_data
        
    except Exception as e:
        logging.error(f"Error reading cached bars: {e}")
        return None

def save_bars_to_cache(date_str, contract_id, bars, interval='5m'):
    """Save bars to cache file /cache/bars/YYYYMMDD.json.
    Merges new bars with existing bars (avoiding duplicates by timestamp).
    
    Args:
        date_str: Date string in YYYYMMDD format
        contract_id: Contract symbol
        bars: List of bar dicts to add/merge
        interval: Bar interval (default '5m')
    """
    try:
        cache_folder = 'cache/bars'
        os.makedirs(cache_folder, exist_ok=True)
        cache_file = os.path.join(cache_folder, f"{date_str}.json")
        
        # Read existing cache if it exists
        existing_bars = []
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    existing_cache = json.load(f)
                    existing_bars = existing_cache.get('bars', [])
                    logging.debug(f"Loaded {len(existing_bars)} existing bars from cache")
            except Exception as e:
                logging.warning(f"Could not read existing cache file, will overwrite: {e}")
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
        
        # Prepare cache data with merged bars
        cache_data = {
            'date': date_str,
            'contract_id': contract_id,
            'interval': interval,
            'bars': existing_bars,
            'last_fetched': datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        logging.info(f"Saved cache: {len(existing_bars)} total bars ({new_count} new, {len(existing_bars)-new_count} existing) to {cache_file}")
        
    except Exception as e:
        logging.error(f"Error saving bars to cache: {e}")
        logging.exception("Full traceback:")

def calculate_bar_metrics(bars):
    """Calculate trend, volume, and key level metrics from bars.
    
    Args:
        bars: List of bar dicts with keys {t, o, h, l, c, v}
    
    Returns:
        dict: Metrics including trend, volume stats, and key levels
    """
    try:
        if not bars or len(bars) < 2:
            return {
                'trend': 'insufficient data',
                'avg_volume': 0,
                'swing_high': 0,
                'swing_low': 0
            }
        
        # Extract highs, lows, closes, volumes
        highs = [bar['h'] for bar in bars]
        lows = [bar['l'] for bar in bars]
        closes = [bar['c'] for bar in bars]
        volumes = [bar['v'] for bar in bars]
        
        # Trend analysis - compare recent half to earlier half
        mid_point = len(closes) // 2
        earlier_avg = sum(closes[:mid_point]) / mid_point if mid_point > 0 else closes[0]
        recent_avg = sum(closes[mid_point:]) / (len(closes) - mid_point)
        
        # Determine trend
        if recent_avg > earlier_avg * 1.001:  # 0.1% threshold
            trend = 'uptrend'
        elif recent_avg < earlier_avg * 0.999:
            trend = 'downtrend'
        else:
            trend = 'sideways'
        
        # Volume analysis
        avg_volume = sum(volumes) / len(volumes)
        
        # Key levels
        swing_high = max(highs)
        swing_low = min(lows)
        
        return {
            'trend': trend,
            'avg_volume': avg_volume,
            'swing_high': swing_high,
            'swing_low': swing_low,
            'recent_close': closes[-1]
        }
        
    except Exception as e:
        logging.error(f"Error calculating bar metrics: {e}")
        return {
            'trend': 'error',
            'avg_volume': 0,
            'swing_high': 0,
            'swing_low': 0
        }

def format_bars_for_context(bars, num_bars=36):
    """Format bars into readable table and analysis for LLM context.
    
    Args:
        bars: List of bar dicts
        num_bars: Number of most recent bars to include (default 36 = 3 hours)
    
    Returns:
        str: Formatted bar data and analysis
    """
    try:
        if not bars:
            return "\n[No bar data available]"
        
        # Take last N bars
        recent_bars = bars[-num_bars:] if len(bars) > num_bars else bars
        
        # Calculate metrics
        metrics = calculate_bar_metrics(recent_bars)
        
        # Format bars table
        context = f"\n\nRecent 5-Minute Bars (Last {len(recent_bars)} bars / {len(recent_bars)*5/60:.1f} hours):\n"
        context += "Time (CT)  Open      High      Low       Close     Volume\n"
        context += "-" * 65 + "\n"
        
        # Show last 10 bars in table to keep context manageable
        display_bars = recent_bars[-10:]
        for bar in display_bars:
            # Convert UTC timestamp to ET
            try:
                bar_time = datetime.datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
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
        
        return context
        
    except Exception as e:
        logging.error(f"Error formatting bars for context: {e}")
        logging.exception("Full traceback:")
        return "\n[Error formatting bar data]"

def parse_yahoo_context(context_text):
    """Parse Yahoo Finance text context to extract structured metrics.
    
    Args:
        context_text: Yahoo Finance context string from market_data.py
    
    Returns:
        dict: Extracted metrics {prev_close, open, gap_direction, gap_size, pdh, pdl, day_trend, vwap, poc}
    """
    try:
        import re
        
        metrics = {
            'prev_close': None,
            'open': None,
            'gap_direction': '',
            'gap_size': 0,
            'pdh': None,
            'pdl': None,
            'day_trend': '',
            'vwap': None,
            'poc': None
        }
        
        # Extract current open/close from "ES: Open X, Current Y"
        open_match = re.search(r'Open\s+([\d.]+)', context_text)
        if open_match:
            metrics['open'] = float(open_match.group(1))
        
        # Extract range for PDH/PDL from "Range X-Y"
        range_match = re.search(r'Range\s+([\d.]+)-([\d.]+)', context_text)
        if range_match:
            metrics['pdl'] = float(range_match.group(1))
            metrics['pdh'] = float(range_match.group(2))
        
        # Extract gap info from "GAP UP:" or "GAP DOWN:" or "Minor gap"
        if 'GAP UP' in context_text:
            metrics['gap_direction'] = 'up'
            gap_match = re.search(r'GAP UP:\s+([\d.]+)\s+pts', context_text)
            if gap_match:
                metrics['gap_size'] = float(gap_match.group(1))
        elif 'GAP DOWN' in context_text:
            metrics['gap_direction'] = 'down'
            gap_match = re.search(r'GAP DOWN:\s+([\d.]+)\s+pts', context_text)
            if gap_match:
                metrics['gap_size'] = float(gap_match.group(1))
        elif 'Minor gap up' in context_text:
            metrics['gap_direction'] = 'up'
            gap_match = re.search(r'Minor gap up:\s+([\d.]+)\s+pts', context_text)
            if gap_match:
                metrics['gap_size'] = float(gap_match.group(1))
        elif 'Minor gap down' in context_text:
            metrics['gap_direction'] = 'down'
            gap_match = re.search(r'Minor gap down:\s+([\d.]+)\s+pts', context_text)
            if gap_match:
                metrics['gap_size'] = float(gap_match.group(1))
        
        # Extract previous close from gap info "from previous close X"
        prev_close_match = re.search(r'from previous close\s+([\d.]+)', context_text)
        if prev_close_match:
            metrics['prev_close'] = float(prev_close_match.group(1))
        
        # Extract 5-day trend from "5-Day Trend: UPTREND" or "DOWNTREND"
        if '5-Day Trend: UPTREND' in context_text:
            metrics['day_trend'] = 'uptrend'
        elif '5-Day Trend: DOWNTREND' in context_text:
            metrics['day_trend'] = 'downtrend'
        elif '5-Day Trend: NEUTRAL' in context_text:
            metrics['day_trend'] = 'neutral'
        
        # Extract VWAP from "VWAP (X-day): Y.YY"
        vwap_match = re.search(r'VWAP\s+\([^)]+\):\s+([\d.]+)', context_text)
        if vwap_match:
            metrics['vwap'] = float(vwap_match.group(1))
        
        # Extract POC from "1. X.XX pts (POC - Point of Control)"
        poc_match = re.search(r'1\.\s+([\d.]+)\s+pts.*\(POC', context_text)
        if poc_match:
            metrics['poc'] = float(poc_match.group(1))
        
        return metrics
        
    except Exception as e:
        logging.error(f"Error parsing Yahoo context: {e}")
        logging.exception("Full traceback:")
        return {
            'prev_close': None,
            'open': None,
            'gap_direction': '',
            'gap_size': 0,
            'pdh': None,
            'pdl': None,
            'day_trend': '',
            'vwap': None,
            'poc': None
        }

def calculate_overnight_metrics(bars):
    """Calculate overnight session metrics (ONH, ONL, Globex VWAP).
    
    Overnight session: 16:00 ET previous day to 09:30 ET current day
    
    Args:
        bars: List of bar dicts with keys {t, o, h, l, c, v}
    
    Returns:
        dict: {onh, onl, globex_vwap}
    """
    try:
        if not bars:
            return {'onh': None, 'onl': None, 'globex_vwap': None}
        
        # Filter bars for overnight session
        # Overnight is 16:00 ET to 09:30 ET
        overnight_bars = []
        
        for bar in bars:
            try:
                # Parse bar timestamp
                bar_time_utc = datetime.datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
                bar_time_et = utc_to_eastern(bar_time_utc)
                bar_hour = bar_time_et.hour
                bar_minute = bar_time_et.minute
                
                # Check if in overnight session (16:00-23:59 or 00:00-09:30)
                is_overnight = (bar_hour >= 16) or (bar_hour < 9) or (bar_hour == 9 and bar_minute < 30)
                
                if is_overnight:
                    overnight_bars.append(bar)
            except:
                continue
        
        if not overnight_bars:
            logging.warning("No overnight bars found for ONH/ONL/Globex VWAP calculation")
            return {'onh': None, 'onl': None, 'globex_vwap': None}
        
        # Calculate ONH (overnight high)
        onh = max(bar['h'] for bar in overnight_bars)
        
        # Calculate ONL (overnight low)
        onl = min(bar['l'] for bar in overnight_bars)
        
        # Calculate Globex VWAP
        total_volume = sum(bar['v'] for bar in overnight_bars)
        if total_volume > 0:
            typical_prices = [(bar['h'] + bar['l'] + bar['c']) / 3 * bar['v'] for bar in overnight_bars]
            globex_vwap = sum(typical_prices) / total_volume
        else:
            globex_vwap = None
        
        logging.info(f"Overnight metrics: ONH={onh}, ONL={onl}, Globex VWAP={globex_vwap}")
        return {
            'onh': round(onh, 2) if onh else None,
            'onl': round(onl, 2) if onl else None,
            'globex_vwap': round(globex_vwap, 2) if globex_vwap else None
        }
        
    except Exception as e:
        logging.error(f"Error calculating overnight metrics: {e}")
        logging.exception("Full traceback:")
        return {'onh': None, 'onl': None, 'globex_vwap': None}

def generate_market_data_json(bars, yahoo_context_text, position_type, position_details=None, working_orders=None, contract_id='', num_bars=36, upcoming_events=None):
    """Generate structured JSON market data combining Yahoo Finance and TopstepX bars.
    
    Args:
        bars: List of bar dicts from TopstepX
        yahoo_context_text: Yahoo Finance context string
        position_type: Current position type ('none', 'long', 'short')
        position_details: Position details dict
        working_orders: Working orders dict
        contract_id: Contract ID for parsing working orders
        num_bars: Number of bars to include (default 36)
        upcoming_events: List of upcoming economic events (default None)
    
    Returns:
        str: JSON string with structured market data
    """
    try:
        # Parse Yahoo Finance context
        yahoo_metrics = parse_yahoo_context(yahoo_context_text)
        
        # Calculate overnight metrics from bars
        overnight_metrics = calculate_overnight_metrics(bars) if bars else {'onh': None, 'onl': None, 'globex_vwap': None}
        
        # Format 5-minute bars (last num_bars)
        recent_bars = bars[-num_bars:] if bars and len(bars) > num_bars else (bars if bars else [])
        five_min_bars = []
        for bar in recent_bars:
            try:
                # Convert UTC to ET
                bar_time_utc = datetime.datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
                bar_time_et = utc_to_eastern(bar_time_utc)
                time_str = bar_time_et.strftime("%H:%M")
                
                five_min_bars.append({
                    "time": time_str,
                    "open": round(bar['o'], 2),
                    "high": round(bar['h'], 2),
                    "low": round(bar['l'], 2),
                    "close": round(bar['c'], 2),
                    "volume": int(bar['v'])
                })
            except:
                continue
        
        # Build MarketContext
        market_context = {
            "PrevClose": yahoo_metrics['prev_close'],
            "Open": yahoo_metrics['open'],
            "GapDirection": yahoo_metrics['gap_direction'],
            "GapSizePts": yahoo_metrics['gap_size'],
            "ONH": overnight_metrics['onh'],
            "ONL": overnight_metrics['onl'],
            "DayTrend5D": yahoo_metrics['day_trend']
        }
        
        # Build KeyLevels (removed ONH/ONL as they're already in MarketContext)
        key_levels = {
            "PDH": yahoo_metrics['pdh'],
            "PDL": yahoo_metrics['pdl'],
            "RTH_VWAP": yahoo_metrics['vwap'],
            "Globex_VWAP": overnight_metrics['globex_vwap'],
            "5DayPOC": yahoo_metrics['poc']
        }
        
        # Build Position (only include if actively in a trade)
        position_status = "flat"
        if position_type == 'long':
            position_status = "long"
        elif position_type == 'short':
            position_status = "short"
        
        # Get current time in Eastern Time
        current_utc = datetime.datetime.utcnow()
        current_et = utc_to_eastern(current_utc)
        current_time_str = current_et.strftime("%Y-%m-%d %H:%M:%S ET")
        
        # Build complete structure
        market_data = {
            "CurrentTime": current_time_str,
            "FiveMinuteBars": five_min_bars,
            "MarketContext": market_context,
            "KeyLevels": key_levels
        }
        
        # Only include Position if in an active trade
        if position_status in ['long', 'short']:
            entry_price = None
            stop = None
            target = None
            
            # Get entry price from position_details
            if position_details:
                entry_price = position_details.get('average_price')
            
            # Get stop/target from working orders
            if working_orders and contract_id:
                order_info = parse_working_orders(working_orders, contract_id)
                stop = order_info.get('stop_loss_price')
                target = order_info.get('take_profit_price')
            
            market_data["Position"] = {
                "status": position_status,
                "entry_price": round(entry_price, 2) if entry_price else None,
                "stop": round(stop, 2) if stop else None,
                "target": round(target, 2) if target else None
            }
        
        # Include upcoming economic events if provided
        if upcoming_events:
            market_data["UpcomingEconomicEvents"] = []
            for event in upcoming_events:
                event_data = {
                    "name": event.get('name', ''),
                    "datetime": event.get('datetime', ''),
                    "minutes_until": event.get('minutes_until', 0),
                    "severity": event.get('severity', 'Medium'),
                    "market_impact": event.get('market_impact_description', '')
                }
                market_data["UpcomingEconomicEvents"].append(event_data)
        
        # Convert to formatted JSON string
        json_string = json.dumps(market_data, indent=2)
        
        return json_string
        
    except Exception as e:
        logging.error(f"Error generating market data JSON: {e}")
        logging.exception("Full traceback:")
        return "{}"

def get_bars_for_llm(contract_id, topstep_config, auth_token, num_bars=36):
    """Main function to get bars for LLM with smart daily caching.
    
    This function:
    1. Checks cache for today's bars
    2. Fetches missing bars from API (all day on first run, incremental after)
    3. Appends new bars to cache
    4. Returns both raw bars and formatted bar data for LLM context
    
    Args:
        contract_id: Contract symbol
        topstep_config: Topstep configuration dict
        auth_token: Auth token for API
        num_bars: Number of bars to return for context (default 36)
    
    Returns:
        dict: {'bars': list of raw bar dicts, 'formatted': formatted text for LLM}
              Returns {'bars': [], 'formatted': ''} if disabled or error
    """
    try:
        # Check if bar data is enabled
        enable_bar_data = config.getboolean('TopstepXBars', 'enable_bar_data', fallback=True)
        if not enable_bar_data:
            logging.debug("Bar data disabled in config")
            return {'bars': [], 'formatted': ''}
        
        if not auth_token:
            logging.warning("No auth token - skipping bar data fetch")
            return {'bars': [], 'formatted': ''}
        
        # Get today's date
        today = datetime.datetime.now()
        date_str = today.strftime("%Y%m%d")
        
        # Try to load cached bars for today
        cache_data = get_cached_bars(date_str)
        
        # Check if we might need bars from previous day (early morning hours)
        current_utc = datetime.datetime.utcnow()
        minutes_needed = num_bars * 5  # 5-minute bars
        calculated_start = current_utc - datetime.timedelta(minutes=minutes_needed)
        midnight_utc = current_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # If we need bars from yesterday, try to load yesterday's cache too
        yesterday_bars = []
        if calculated_start < midnight_utc:
            yesterday = today - datetime.timedelta(days=1)
            yesterday_str = yesterday.strftime("%Y%m%d")
            yesterday_cache = get_cached_bars(yesterday_str)
            if yesterday_cache:
                yesterday_bars = yesterday_cache.get('bars', [])
                logging.info(f"Loaded {len(yesterday_bars)} bars from yesterday's cache ({yesterday_str})")
                
                # Filter yesterday's bars to only include those after calculated_start
                calculated_start_str = calculated_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                yesterday_bars = [bar for bar in yesterday_bars if bar['t'] >= calculated_start_str]
                logging.info(f"Filtered to {len(yesterday_bars)} bars from yesterday after {calculated_start_str}")
        
        # Determine what time range to fetch
        market_open = config.get('TopstepXBars', 'market_open', fallback='09:30')
        open_hour, open_min = map(int, market_open.split(':'))
        
        # Create market open datetime (ET - convert to UTC)
        market_open_et = today.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)
        market_open_utc = eastern_to_utc(market_open_et)
        
        if cache_data is None:
            # First fetch of the day - get all bars from market open
            logging.info("First bar fetch of the day - fetching all bars from market open")
            
            # If we're in early morning hours and need bars from previous day
            if calculated_start < midnight_utc:
                logging.info(f"Early morning fetch - need bars from previous day")
                logging.info(f"Calculated start: {calculated_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                logging.info(f"Using calculated start instead of market open")
                start_time = calculated_start
            else:
                # Normal case - use market open or calculated start, whichever is later
                start_time = max(market_open_utc, calculated_start)
            
            end_time = current_utc
            existing_bars = []
        else:
            # Incremental fetch - only get new bars since last fetch
            try:
                last_fetched_str = cache_data.get('last_fetched')
                last_fetched = datetime.datetime.fromisoformat(last_fetched_str.replace('Z', '+00:00'))
                
                # Only fetch if more than 5 minutes have passed
                time_diff = (current_utc - last_fetched.replace(tzinfo=None)).total_seconds()
                if time_diff < 300:  # Less than 5 minutes
                    logging.debug(f"Using cached bars - only {time_diff:.0f}s since last fetch")
                    # Merge yesterday's bars with cached bars if in early morning
                    all_cached_bars = yesterday_bars.copy() if yesterday_bars else []
                    all_cached_bars.extend(cache_data.get('bars', []))
                    
                    # Check if we have enough bars before returning
                    if len(all_cached_bars) < num_bars:
                        logging.warning(f"Cached bars ({len(all_cached_bars)}) < required ({num_bars}) - fetching historical data")
                        # Fetch enough historical bars to fill the gap
                        minutes_back = num_bars * 5 + 60  # Extra buffer
                        hist_start = current_utc - datetime.timedelta(minutes=minutes_back)
                        hist_bars = fetch_topstepx_bars(
                            contract_id,
                            hist_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            current_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            topstep_config,
                            auth_token
                        )
                        if hist_bars:
                            # Merge and deduplicate
                            existing_ts = {bar['t'] for bar in all_cached_bars}
                            for bar in hist_bars:
                                if bar['t'] not in existing_ts:
                                    all_cached_bars.append(bar)
                            all_cached_bars.sort(key=lambda x: x['t'])
                            logging.info(f"After historical backfill: {len(all_cached_bars)} total bars")
                    
                    return {'bars': all_cached_bars, 'formatted': format_bars_for_context(all_cached_bars, num_bars)}
                
                logging.info(f"Incremental fetch - getting bars since {last_fetched_str}")
                start_time = last_fetched.replace(tzinfo=None)
                end_time = current_utc
                existing_bars = cache_data.get('bars', [])
            except:
                logging.warning("Error parsing cache timestamp - fetching all bars")
                start_time = market_open_utc
                end_time = current_utc
                existing_bars = []
        
        # Fetch new bars from API
        new_bars = fetch_topstepx_bars(contract_id, start_time, end_time, topstep_config, auth_token)
        
        if new_bars is None:
            # API fetch failed - use cached bars if available
            logging.warning("Bar fetch failed - using cached bars if available")
            if cache_data or yesterday_bars:
                # Merge yesterday's bars with cached bars if in early morning
                all_cached_bars = yesterday_bars.copy() if yesterday_bars else []
                if cache_data:
                    all_cached_bars.extend(cache_data.get('bars', []))
                
                # Check if we have enough bars - try one more historical fetch if not
                if len(all_cached_bars) < num_bars:
                    logging.warning(f"Cached bars ({len(all_cached_bars)}) < required ({num_bars}) - attempting historical backfill")
                    minutes_back = num_bars * 5 + 60
                    hist_start = current_utc - datetime.timedelta(minutes=minutes_back)
                    hist_bars = fetch_topstepx_bars(
                        contract_id,
                        hist_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        current_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        topstep_config,
                        auth_token
                    )
                    if hist_bars:
                        existing_ts = {bar['t'] for bar in all_cached_bars}
                        for bar in hist_bars:
                            if bar['t'] not in existing_ts:
                                all_cached_bars.append(bar)
                        all_cached_bars.sort(key=lambda x: x['t'])
                        logging.info(f"After historical backfill: {len(all_cached_bars)} total bars")
                
                return {'bars': all_cached_bars, 'formatted': format_bars_for_context(all_cached_bars, num_bars)}
            else:
                return {'bars': [], 'formatted': "\n[Bar data unavailable - API fetch failed]"}
        
        # Merge yesterday's bars, existing bars, and new bars (remove duplicates by timestamp)
        all_bars = yesterday_bars.copy() if yesterday_bars else []
        all_bars.extend(existing_bars)
        existing_timestamps = {bar['t'] for bar in all_bars}
        
        for bar in new_bars:
            if bar['t'] not in existing_timestamps:
                all_bars.append(bar)
        
        # Sort by timestamp
        all_bars.sort(key=lambda x: x['t'])
        
        # Check if we have enough bars - if not, fetch more historical data
        if len(all_bars) < num_bars:
            logging.warning(f"Only have {len(all_bars)} bars, need {num_bars} - fetching more historical data")
            
            # Calculate how far back we need to go to get num_bars
            minutes_needed = num_bars * 5 + 60  # Extra 60 min buffer
            historical_start = current_utc - datetime.timedelta(minutes=minutes_needed)
            
            # If all_bars has some data, start from before the earliest bar we have
            if all_bars:
                earliest_bar_time = datetime.datetime.fromisoformat(all_bars[0]['t'].replace('Z', '+00:00')).replace(tzinfo=None)
                historical_start = min(historical_start, earliest_bar_time - datetime.timedelta(minutes=30))
            
            logging.info(f"Fetching historical bars from {historical_start.strftime('%Y-%m-%d %H:%M:%S UTC')} to fill gap")
            
            # Fetch historical bars
            historical_bars = fetch_topstepx_bars(
                contract_id,
                historical_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                current_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                topstep_config,
                auth_token
            )
            
            if historical_bars:
                logging.info(f"Fetched {len(historical_bars)} historical bars")
                
                # Merge with existing bars (avoid duplicates)
                existing_timestamps = {bar['t'] for bar in all_bars}
                for bar in historical_bars:
                    if bar['t'] not in existing_timestamps:
                        all_bars.append(bar)
                
                # Re-sort
                all_bars.sort(key=lambda x: x['t'])
                logging.info(f"After historical fetch: total {len(all_bars)} bars")
        
        # Save updated cache for today (not including yesterday's bars)
        today_bars = [bar for bar in all_bars if bar['t'] >= midnight_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")]
        save_bars_to_cache(date_str, contract_id, today_bars)
        
        # Format and return (including yesterday's bars if present)
        return {'bars': all_bars, 'formatted': format_bars_for_context(all_bars, num_bars)}
        
    except Exception as e:
        logging.error(f"Error in get_bars_for_llm: {e}")
        logging.exception("Full traceback:")
        return {'bars': [], 'formatted': "\n[Error retrieving bar data]"}

def get_available_contracts(topstep_config, auth_token=None, symbol=None):
    """Query API for contract search by symbol (or available contracts if no symbol specified)."""
    if not auth_token:
        logging.error("No auth token available for contracts query")
        return None

    base_url = topstep_config['base_url']

    if symbol:
        # Use contract search for specific symbol
        contracts_endpoint = topstep_config.get('contracts_endpoint', '/api/Contract/search')
        url = base_url + contracts_endpoint

        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "accept": "text/plain"
        }

        payload = {
            "searchText": symbol,
            "live": False
        }

        # Debug logging
        logging.info("=== SEARCHING CONTRACT BY SYMBOL ===")
        logging.info(f"Contract Search URL: {url}")
        logging.info(f"Search Payload: {json.dumps(payload)}")
        logging.info(f"Auth Token: {auth_token[:20]}..." if auth_token else "None")
        logging.info(f"Headers: {headers}")

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            logging.info(f"Contract Search Response Status: {response.status_code}")
            logging.info(f"Contract Search Response Headers: {dict(response.headers)}")

            response.raise_for_status()
            contracts = response.json()
            logging.info(f"Contract Search Response Body: {json.dumps(contracts, indent=2)}")

            if isinstance(contracts, list) and contracts:
                contract = contracts[0]  # Take the first matching contract
                contract_symbol = contract.get('symbol', 'Unknown')
                contract_name = contract.get('name', 'Unknown')
                logging.info(f"Found contract for {symbol}: {contract_symbol} - {contract_name}")
                return contracts
            else:
                logging.warning(f"No contracts found for symbol {symbol}")
                return None

        except requests.exceptions.Timeout:
            logging.error("Contract search request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Contract search request failed: {e}")
            return None
        except Exception as e:
            logging.error(f"Error searching contracts: {e}")
            return None
    else:
        # Fallback to available contracts endpoint
        contracts_endpoint = topstep_config.get('contracts_available_endpoint', '/api/Contract/available')
        url = base_url + contracts_endpoint
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "accept": "text/plain"
        }

        payload = {
            "live": False
        }

        # Debug logging
        logging.info("=== FETCHING AVAILABLE CONTRACTS ===")
        logging.info(f"Contracts URL: {url}")
        logging.info(f"Request Payload: {json.dumps(payload)}")
        logging.info(f"Auth Token: {auth_token[:20]}..." if auth_token else "None")
        logging.info(f"Headers: {headers}")

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            logging.info(f"Contracts Response Status: {response.status_code}")
            logging.info(f"Contracts Response Headers: {dict(response.headers)}")

            response.raise_for_status()
            contracts = response.json()
            logging.info(f"Contracts Response Body: {json.dumps(contracts, indent=2)}")
            logging.info(f"Found {len(contracts) if isinstance(contracts, list) else 'N/A'} available contracts")
            return contracts
        except requests.exceptions.Timeout:
            logging.error("Contracts request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Contracts request failed: {e}")
            return None
        except Exception as e:
            logging.error(f"Error fetching contracts: {e}")
            return None

def fetch_trade_results(account_id, topstep_config, enable_trading, auth_token=None, start_timestamp=None, end_timestamp=None):
    """Fetch trade results from TopstepX Trade/search API.
    
    Args:
        account_id: Account ID
        topstep_config: Topstep configuration dict
        enable_trading: Whether trading is enabled
        auth_token: Auth token
        start_timestamp: Start time in ISO format (default: today 00:00)
        end_timestamp: End time in ISO format (default: now)
        
    Returns:
        list: List of trade objects or None on error
    """
    if not enable_trading:
        logging.debug("Trading disabled - Skipping trade results query")
        return None
    
    if not auth_token:
        logging.error("No auth token available for trade results query")
        return None
    
    if not account_id:
        logging.error("No account_id provided for trade results query")
        return None
    
    try:
        # Default timestamps: today 00:00 to now
        if not start_timestamp:
            start_timestamp = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not end_timestamp:
            end_timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        
        base_url = topstep_config['base_url']
        trade_search_endpoint = topstep_config.get('trade_search_endpoint', '/api/Trade/search')
        url = base_url + trade_search_endpoint
        
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "accountId": int(account_id),
            "startTimestamp": start_timestamp,
            "endTimestamp": end_timestamp
        }
        
        logging.info("=== FETCHING TRADE RESULTS ===")
        logging.info(f"Trade Search URL: {url}")
        logging.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        logging.info("="*80)
        logging.info("TRADE RESULTS API RESPONSE:")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(json.dumps(result, indent=2))
        logging.info("="*80)
        
        if result.get('success', True) and 'trades' in result:
            return result['trades']
        else:
            logging.warning(f"Trade search returned no trades or error: {result.get('errorMessage')}")
            return []
        
    except Exception as e:
        logging.error(f"Error fetching trade results: {e}")
        logging.exception("Full traceback:")
        return None

def get_account_balance(account_id, topstep_config, enable_trading, auth_token=None):
    """Query API for account balance for a specific account ID."""
    global SESSION_START_BALANCE, SESSION_START_TIME, CURRENT_RPL
    
    if not enable_trading:
        logging.debug("Trading disabled - Skipping account balance query")
        return None
    
    if not auth_token:
        logging.error("No auth token available for account balance query")
        return None
    
    if not account_id:
        logging.error("No account_id provided for balance query")
        return None
    
    try:
        # Get all accounts
        accounts_response = get_accounts(topstep_config, enable_trading, auth_token)
        
        if not accounts_response:
            logging.warning("No accounts data returned")
            return None
        
        # Extract accounts list from response
        if not isinstance(accounts_response, dict) or 'accounts' not in accounts_response:
            logging.error("Unexpected accounts response format")
            return None
        
        accounts_list = accounts_response['accounts']
        
        # Find the matching account by id
        target_account_id = int(account_id)
        for account in accounts_list:
            if account.get('id') == target_account_id:
                balance = account.get('balance')
                if balance is not None:
                    balance = float(balance)
                    logging.info(f"Retrieved balance for account {account_id}: ${balance:,.2f}")
                    
                    # Session RPL tracking
                    # Initialize session start balance if not set
                    if SESSION_START_BALANCE is None:
                        # Try to get from database first
                        db_start_balance = get_session_start_balance(account_id)
                        if db_start_balance is not None:
                            SESSION_START_BALANCE = db_start_balance
                        else:
                            # Use current balance as baseline
                            SESSION_START_BALANCE = balance
                            logging.info(f"No session start balance found - using current balance as baseline: ${balance:,.2f}")
                        
                        SESSION_START_TIME = get_session_start_time()
                        logging.info(f"Session started at {SESSION_START_TIME}, start balance: ${SESSION_START_BALANCE:,.2f}")
                    
                    # Calculate current RPL
                    CURRENT_RPL = calculate_session_rpl(balance, SESSION_START_BALANCE)
                    
                    # Save snapshot to Supabase
                    save_balance_snapshot(account_id, balance, CURRENT_RPL)
                    
                    logging.info(f"Session RPL: ${CURRENT_RPL:+,.2f}")
                    
                    return balance
                else:
                    logging.warning(f"Found account {account_id} but no balance field")
                    return None
        
        logging.warning(f"Account {account_id} not found in accounts list")
        return None
        
    except Exception as e:
        logging.error(f"Error retrieving account balance: {e}")
        logging.exception("Full traceback:")
        return None

def get_accounts(topstep_config, enable_trading, auth_token=None):
    """Query API for list of accounts (or skip if trading disabled)."""
    if not enable_trading:
        logging.info("Trading disabled - Skipping accounts query on startup.")
        return None

    if not auth_token:
        logging.error("No auth token available for accounts query")
        return None

    base_url = topstep_config['base_url']
    accounts_endpoint = topstep_config.get('accounts_endpoint', '/api/Account/search')

    url = base_url + accounts_endpoint
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "accept": "text/plain"
    }
    payload = {
        "onlyActiveAccounts": True
    }

    # Debug logging
    logging.info("=== FETCHING ACCOUNTS ===")
    logging.info(f"Accounts URL: {url}")
    logging.info(f"Auth Token: {auth_token[:20]}..." if auth_token else "None")
    logging.info(f"Headers: {headers}")
    logging.info(f"Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logging.info(f"Accounts Response Status: {response.status_code}")
        logging.info(f"Accounts Response Headers: {dict(response.headers)}")

        response.raise_for_status()
        accounts = response.json()
        logging.info(f"Accounts Response Body: {json.dumps(accounts, indent=2)}")
        return accounts
    except requests.exceptions.Timeout:
        logging.error("Accounts request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Accounts request failed: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching accounts: {e}")
        return None

# Global dashboard reference
DASHBOARD_WINDOW = None
ACCOUNT_BALANCE = None
LATEST_LLM_DATA = None  # Store the most recent LLM response for immediate dashboard updates
DASHBOARD_WIDGETS = {}  # Store references to dashboard widgets for updates without rebuild
LAST_JOB_TIME = None  # Track when last screenshot/job was taken for countdown
LAST_WAITING_FOR = None  # Store the most recent "waiting_for" condition from LLM response
LAST_KEY_LEVELS = None  # Store the most recent key price levels from LLM response

# Session RPL tracking
SESSION_START_BALANCE = None  # Balance at 18:00 session start
SESSION_START_TIME = None  # When the trading session started
CURRENT_RPL = 0.0  # Current session realized profit/loss

# Position reconciliation tracking
FORCE_IMMEDIATE_ANALYSIS = False  # Flag to trigger immediate screenshot and LLM analysis when discrepancy detected
LAST_RECONCILIATION_TIME = None  # Timestamp of last reconciliation to prevent duplicates

# Dynamic snapshot timing (LLM-controlled)
NEXT_SNAPSHOT_OVERRIDE = None  # LLM-requested interval for next snapshot (in seconds), overrides schedule

# Global Supabase client
SUPABASE_CLIENT = None

# Load configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

# Make config globally accessible
CONFIG = config

# Logging setup with UTF-8 encoding
LOG_FOLDER = config.get('General', 'log_folder', fallback='logs')
os.makedirs(LOG_FOLDER, exist_ok=True)
today = datetime.datetime.now().strftime("%Y%m%d")
log_file = os.path.join(LOG_FOLDER, f"{today}.txt")

# File handler with UTF-8 encoding
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# Console handler with UTF-8 encoding and error handling
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
# Ensure console can handle UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])

logging.info("Application started.")

INTERVAL_MINUTES = int(config.get('General', 'interval_minutes', fallback='5'))
INTERVAL_SECONDS = int(config.get('General', 'interval_seconds', fallback=str(INTERVAL_MINUTES * 60)))
INTERVAL_SCHEDULE = config.get('General', 'interval_schedule', fallback='')
TRADE_STATUS_CHECK_INTERVAL = int(config.get('General', 'trade_status_check_interval', fallback='10'))
BEGIN_TIME = config.get('General', 'begin_time', fallback='00:00')
END_TIME = config.get('General', 'end_time', fallback='23:59')
NO_NEW_TRADES_WINDOWS = config.get('General', 'no_new_trades_windows', fallback='')
FORCE_CLOSE_TIME = config.get('General', 'force_close_time', fallback='23:59')
WINDOW_TITLE = config.get('General', 'window_title', fallback=None)
WINDOW_PROCESS_NAME = config.get('General', 'window_process_name', fallback=None)
TOP_OFFSET = int(config.get('General', 'top_offset', fallback='0'))
BOTTOM_OFFSET = int(config.get('General', 'bottom_offset', fallback='0'))
LEFT_OFFSET = int(config.get('General', 'left_offset', fallback='0'))
RIGHT_OFFSET = int(config.get('General', 'right_offset', fallback='0'))
SAVE_FOLDER = config.get('General', 'save_folder', fallback=None)
ENABLE_LLM = config.getboolean('General', 'enable_llm', fallback=True)
ENABLE_TRADING = config.getboolean('General', 'enable_trading', fallback=False)
EXECUTE_TRADES = config.getboolean('General', 'execute_trades', fallback=False)
ENABLE_SAVE_SCREENSHOTS = config.getboolean('General', 'enable_save_screenshots', fallback=False)

logging.info(f"Loaded config: INTERVAL_MINUTES={INTERVAL_MINUTES}, INTERVAL_SECONDS={INTERVAL_SECONDS}, INTERVAL_SCHEDULE={INTERVAL_SCHEDULE or 'Not set (using interval_seconds)'}, TRADE_STATUS_CHECK_INTERVAL={TRADE_STATUS_CHECK_INTERVAL}s, BEGIN_TIME={BEGIN_TIME}, END_TIME={END_TIME}, NO_NEW_TRADES_WINDOWS={NO_NEW_TRADES_WINDOWS}, FORCE_CLOSE_TIME={FORCE_CLOSE_TIME}, WINDOW_TITLE={WINDOW_TITLE}, WINDOW_PROCESS_NAME={WINDOW_PROCESS_NAME or 'Not set'}, TOP_OFFSET={TOP_OFFSET}, BOTTOM_OFFSET={BOTTOM_OFFSET}, LEFT_OFFSET={LEFT_OFFSET}, RIGHT_OFFSET={RIGHT_OFFSET}, SAVE_FOLDER={SAVE_FOLDER}, ENABLE_LLM={ENABLE_LLM}, ENABLE_TRADING={ENABLE_TRADING}, EXECUTE_TRADES={EXECUTE_TRADES}, ENABLE_SAVE_SCREENSHOTS={ENABLE_SAVE_SCREENSHOTS}")

def load_prompt_from_config(config_value, fallback_text=''):
    """
    Load prompt text from config value.
    If the config value ends with .txt, treat it as a file path and load the content.
    Otherwise, return the config value as-is (for backward compatibility).
    """
    if not config_value:
        return fallback_text
    
    # Check if it's a file path
    if config_value.endswith('.txt'):
        try:
            with open(config_value, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logging.error(f"Prompt file not found: {config_value}, using fallback")
            return fallback_text
        except Exception as e:
            logging.error(f"Error reading prompt file {config_value}: {e}, using fallback")
            return fallback_text
    else:
        # Return as-is for backward compatibility with inline prompts
        return config_value

def escape_format_string(text):
    """
    Escape curly braces in text to prevent issues with Python's .format() method.
    Converts { to {{ and } to }} so they are treated as literals after formatting.
    """
    if text is None:
        return ""
    return str(text).replace('{', '{{').replace('}', '}}')

def safe_format_prompt(prompt_template, **kwargs):
    """
    Safely format a prompt template by escaping special characters in replacement values.
    This prevents issues when replacement text contains curly braces or quotes.
    
    Args:
        prompt_template: The template string with placeholders like {Context}, {Symbol}, etc.
        **kwargs: Keyword arguments for replacement values
    
    Returns:
        Formatted prompt string with all placeholders replaced
    """
    try:
        # Escape curly braces in all replacement values to prevent format string issues
        escaped_kwargs = {key: escape_format_string(value) for key, value in kwargs.items()}
        
        # Format the prompt with escaped values
        return prompt_template.format(**escaped_kwargs)
    
    except KeyError as e:
        logging.error(f"Missing placeholder in prompt template: {e}")
        logging.error(f"Available keys: {list(kwargs.keys())}")
        raise
    except Exception as e:
        logging.error(f"Error formatting prompt: {e}")
        logging.error(f"Template length: {len(prompt_template)}, Keys: {list(kwargs.keys())}")
        raise

SYMBOL = config.get('LLM', 'symbol', fallback='ES')
DISPLAY_SYMBOL = config.get('LLM', 'display_symbol', fallback='ES')  # Symbol for LLM communications and human readable formats
POSITION_TYPE = config.get('LLM', 'position_type', fallback='none')

# Load prompts (supports both file paths and inline text for backward compatibility)
no_position_prompt_config = config.get('LLM', 'no_position_prompt', fallback='Analyze this Bookmap screenshot for {symbol} futures and advise: buy, hold, or sell. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "buy/hold/sell", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
NO_POSITION_PROMPT = load_prompt_from_config(no_position_prompt_config, no_position_prompt_config)

# For position prompts, check if separate long/short prompts exist, otherwise use unified position_prompt
long_prompt_config = config.get('LLM', 'long_position_prompt', fallback=None)
short_prompt_config = config.get('LLM', 'short_position_prompt', fallback=None)
position_prompt_config = config.get('LLM', 'position_prompt', fallback='Analyze this Bookmap screenshot for a {position_type} position in {symbol} futures and advise: hold, scale, or close. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "hold/scale/close", "price_target": number, "stop_loss": number, "reasoning": "text"}}')

# If separate long/short prompts are defined, use those; otherwise use unified position_prompt for both
if long_prompt_config:
    LONG_POSITION_PROMPT = load_prompt_from_config(long_prompt_config, position_prompt_config)
else:
    LONG_POSITION_PROMPT = load_prompt_from_config(position_prompt_config, position_prompt_config)

if short_prompt_config:
    SHORT_POSITION_PROMPT = load_prompt_from_config(short_prompt_config, position_prompt_config)
else:
    SHORT_POSITION_PROMPT = load_prompt_from_config(position_prompt_config, position_prompt_config)

# Load runner prompt for managing runner contracts after scaling out
runner_prompt_config = config.get('LLM', 'runner_prompt', fallback='runner_prompt.txt')
RUNNER_PROMPT = load_prompt_from_config(runner_prompt_config, runner_prompt_config)

MODEL = config.get('LLM', 'model', fallback='gpt-4o')

logging.info(f"Loaded LLM config: SYMBOL={SYMBOL}, DISPLAY_SYMBOL={DISPLAY_SYMBOL}, POSITION_TYPE={POSITION_TYPE}, MODEL={MODEL}")

TOPSTEP_CONFIG = {
    'user_name': config.get('Topstep', 'user_name', fallback=''),
    'api_key': config.get('Topstep', 'api_key', fallback='your-topstep-api-key'),
    'api_secret': config.get('Topstep', 'api_secret', fallback='your-topstep-api-secret'),
    'base_url': config.get('Topstep', 'base_url', fallback='https://api.topstep.com/v1'),
    'login_endpoint': config.get('Topstep', 'login_endpoint', fallback='/api/Auth/loginKey'),
    'buy_endpoint': config.get('Topstep', 'buy_endpoint', fallback='/orders'),
    'sell_endpoint': config.get('Topstep', 'sell_endpoint', fallback='/orders'),
    'flatten_endpoint': config.get('Topstep', 'flatten_endpoint', fallback='/positions/flatten'),
    'positions_endpoint': config.get('Topstep', 'positions_endpoint', fallback='/positions'),
    'working_orders_endpoint': config.get('Topstep', 'working_orders_endpoint', fallback='/api/Order/searchOpen'),
    'cancel_order_endpoint': config.get('Topstep', 'cancel_order_endpoint', fallback='/api/Order/cancel'),
    'modify_order_endpoint': config.get('Topstep', 'modify_order_endpoint', fallback='/api/Order/modify'),
    'accounts_endpoint': config.get('Topstep', 'accounts_endpoint', fallback='/api/Account/search'),
    'contracts_endpoint': config.get('Topstep', 'contracts_endpoint', fallback='/api/Contract/search'),
    'contracts_available_endpoint': config.get('Topstep', 'contracts_available_endpoint', fallback='/api/Contract/available'),
    'trade_search_endpoint': config.get('Topstep', 'trade_search_endpoint', fallback='/api/Trade/search'),
    'account_id': config.get('Topstep', 'account_id', fallback=''),
    'contract_id': config.get('Topstep', 'contract_id', fallback=''),
    'quantity': config.get('Topstep', 'quantity', fallback='1'),
    'runners_quantity': config.getint('Topstep', 'runners_quantity', fallback=0),
    'contract_to_search': config.get('Topstep', 'contract_to_search', fallback='ES'),
    'max_risk_per_contract': config.get('Topstep', 'max_risk_per_contract', fallback=''),
    'max_profit_per_contract': config.get('Topstep', 'max_profit_per_contract', fallback=''),
    'enable_stop_loss': config.getboolean('Topstep', 'enable_stop_loss', fallback=True),
    'enable_take_profit': config.getboolean('Topstep', 'enable_take_profit', fallback=True),
    'tick_size': config.getfloat('Topstep', 'tick_size', fallback=0.25)
}

logging.info(f"Loaded Topstep config: BASE_URL={TOPSTEP_CONFIG['base_url']}, ACCOUNT_ID={TOPSTEP_CONFIG['account_id'] or 'None'}, CONTRACT_ID={TOPSTEP_CONFIG['contract_id'] or 'None (will use search results)'}, QUANTITY={TOPSTEP_CONFIG['quantity']}, CONTRACT_TO_SEARCH={TOPSTEP_CONFIG['contract_to_search']}")
logging.info(f"Risk Management: ENABLE_STOP_LOSS={TOPSTEP_CONFIG['enable_stop_loss']}, ENABLE_TAKE_PROFIT={TOPSTEP_CONFIG['enable_take_profit']}, MAX_RISK={TOPSTEP_CONFIG['max_risk_per_contract'] or 'LLM suggestion'}, MAX_PROFIT={TOPSTEP_CONFIG['max_profit_per_contract'] or 'LLM suggestion'}, TICK_SIZE={TOPSTEP_CONFIG['tick_size']}")

OPENAI_API_KEY = config.get('OpenAI', 'api_key', fallback='your-openai-api-key-here')
OPENAI_API_URL = config.get('OpenAI', 'api_url', fallback='https://api.openai.com/v1/chat/completions')

logging.info(f"Loaded OpenAI config: API_URL={OPENAI_API_URL}")

TELEGRAM_CONFIG = {
    'api_key': config.get('Telegram', 'telegram_api_key', fallback=''),
    'chat_id': config.get('Telegram', 'telegram_chat_id', fallback='')
}

if TELEGRAM_CONFIG['api_key'] and TELEGRAM_CONFIG['chat_id']:
    logging.info(f"Loaded Telegram config: Notifications enabled for chat ID {TELEGRAM_CONFIG['chat_id']}")
else:
    logging.info("Telegram config not found or incomplete - notifications disabled")

# Load Market Holidays configuration
HOLIDAY_CONFIG = {
    'enabled': config.getboolean('MarketHolidays', 'enable_holiday_check', fallback=True),
    'cme_url': config.get('MarketHolidays', 'cme_url', fallback='https://www.cmegroup.com/trading-hours.html'),
    'data_file': config.get('MarketHolidays', 'data_file', fallback='market_data/market_holidays.json'),
    'minutes_before_close': int(config.get('MarketHolidays', 'minutes_before_close', fallback='30')),
    'minutes_after_open': int(config.get('MarketHolidays', 'minutes_after_open', fallback='5')),
    'force_refresh': config.getboolean('MarketHolidays', 'force_refresh', fallback=False),
    'market_closed': config.get('MarketHolidays', 'market_closed', fallback='')
}

if HOLIDAY_CONFIG['enabled']:
    logging.info(f"Market holidays checking enabled - Data file: {HOLIDAY_CONFIG['data_file']}")
    logging.info(f"  Buffer times: {HOLIDAY_CONFIG['minutes_before_close']}min before close, {HOLIDAY_CONFIG['minutes_after_open']}min after open")
    if HOLIDAY_CONFIG['market_closed']:
        logging.info(f"  Weekly closed periods: {HOLIDAY_CONFIG['market_closed']}")
else:
    logging.info("Market holidays checking disabled")

# Initialize Supabase client
SUPABASE_CONFIG = {
    'url': config.get('Supabase', 'supabase_url', fallback=''),
    'key': config.get('Supabase', 'supabase_anon_key', fallback=''),
    'enabled': config.getboolean('Supabase', 'enable_supabase_logging', fallback=True)
}

if SUPABASE_AVAILABLE and SUPABASE_CONFIG['enabled'] and SUPABASE_CONFIG['url'] and SUPABASE_CONFIG['key']:
    try:
        SUPABASE_CLIENT = create_client(SUPABASE_CONFIG['url'], SUPABASE_CONFIG['key'])
        logging.info("Supabase client initialized successfully")
        
        # Register account if it doesn't exist
        try:
            account_id = TOPSTEP_CONFIG.get('account_id', '')
            if account_id:
                response = SUPABASE_CLIENT.table('accounts').select('*').eq('account_id', account_id).execute()
                if not response.data:
                    account_data = {
                        'account_id': account_id,
                        'account_name': f'TopstepX Account {account_id}',
                        'broker': 'TopstepX'
                    }
                    SUPABASE_CLIENT.table('accounts').insert(account_data).execute()
                    logging.info(f"Registered account {account_id} in Supabase")
        except Exception as e:
            logging.error(f"Error registering account in Supabase: {e}")
    except Exception as e:
        logging.error(f"Failed to initialize Supabase client: {e}")
        SUPABASE_CLIENT = None
elif not SUPABASE_AVAILABLE:
    logging.info("Supabase logging disabled - package not installed")
elif not SUPABASE_CONFIG['enabled']:
    logging.info("Supabase logging disabled in config")
else:
    logging.info("Supabase configuration incomplete - database logging disabled")

# Global auth token for Topstep API
AUTH_TOKEN = None

# Track previous position state to detect changes
PREVIOUS_POSITION_TYPE = 'none'

# Login to TopstepX and get auth token
if ENABLE_TRADING:
    logging.info("Trading enabled - Attempting to login to TopstepX API")
    AUTH_TOKEN = login_topstep(TOPSTEP_CONFIG)
    if AUTH_TOKEN:
        logging.info("Login successful - Auth token obtained")
        TOPSTEP_CONFIG['auth_token'] = AUTH_TOKEN  # Store in config for convenience
        
        # Fetch accounts and extract balance
        try:
            accounts_data = get_accounts(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
            if accounts_data:
                logging.info("Successfully fetched accounts")
                # Try to extract balance for the configured account
                if isinstance(accounts_data, dict) and 'accounts' in accounts_data:
                    account_id = TOPSTEP_CONFIG.get('account_id', '')
                    if account_id:
                        for account in accounts_data.get('accounts', []):
                            if str(account.get('id')) == str(account_id):
                                ACCOUNT_BALANCE = account.get('balance')
                                logging.info(f"Found balance for account {account_id}: ${ACCOUNT_BALANCE:,.2f}")
                                break
        except Exception as e:
            logging.error(f"Error fetching accounts: {e}")

        # NOTE: Automatic contract listing disabled - use tray menu "List All Contracts" to fetch manually
        # # Fetch all available contracts after successful login
        # logging.info("Fetching all available contracts...")
        # all_contracts = get_available_contracts(TOPSTEP_CONFIG, AUTH_TOKEN)  # No symbol parameter = fetch all
        # if all_contracts:
        #     logging.info(f"Successfully fetched {len(all_contracts) if isinstance(all_contracts, list) else 'N/A'} available contracts")
        #     # Log some contract details for better readability
        #     if isinstance(all_contracts, list) and len(all_contracts) > 0:
        #         logging.info("Sample contracts:")
        #         for contract in all_contracts[:5]:  # Show first 5 contracts
        #             if isinstance(contract, dict):
        #                 symbol = contract.get('symbol', 'Unknown')
        #                 name = contract.get('name', 'Unknown')
        #                 logging.info(f"  - {symbol}: {name}")
        #         if len(all_contracts) > 5:
        #             logging.info(f"  ... and {len(all_contracts) - 5} more contracts")
        #     TOPSTEP_CONFIG['all_available_contracts'] = all_contracts  # Store for later use
        # else:
        #     logging.warning("Failed to fetch all available contracts")
    else:
        logging.error("Login failed - Trading functionality may not work")
else:
    logging.info("Trading disabled - Skipping TopstepX login")

# Fetch and log accounts if trading enabled
accounts = get_accounts(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
if accounts:
    logging.info(f"Accounts response: {json.dumps(accounts, indent=2)}")
    
    # Try to extract balance for the configured account
    if isinstance(accounts, dict) and 'accounts' in accounts:
        account_id = TOPSTEP_CONFIG.get('account_id', '')
        if account_id:
            for account in accounts.get('accounts', []):
                if str(account.get('id')) == str(account_id):
                    ACCOUNT_BALANCE = account.get('balance')
                    logging.info(f"Found balance for account {account_id}: ${ACCOUNT_BALANCE:,.2f}")
                    break

    # Fetch contract for the configured symbol after successful accounts fetch
    contract_to_search = TOPSTEP_CONFIG.get('contract_to_search', DISPLAY_SYMBOL)
    logging.info(f"Searching for contract for symbol: {contract_to_search}")
    contracts = get_available_contracts(TOPSTEP_CONFIG, AUTH_TOKEN, contract_to_search)
    if contracts:
        logging.info(f"Successfully found contract(s) for {contract_to_search}")
        # Log contract details for better readability
        if isinstance(contracts, list) and contracts:
            contract = contracts[0]  # Log the first/primary contract
            if isinstance(contract, dict):
                contract_symbol = contract.get('symbol', 'Unknown')
                contract_name = contract.get('name', 'Unknown')
                logging.info(f"Contract found: {contract_symbol} - {contract_name}")
            else:
                logging.info(f"Contract found: {contract}")
        TOPSTEP_CONFIG['available_contracts'] = contracts  # Store for later use
    else:
        logging.warning(f"Failed to find contract for symbol {contract_to_search}")
else:
    logging.info("No accounts fetched (check API key/endpoint or enable_trading).")

# Ensure we have market context for today before beginning trading
logging.info("=" * 80)
logging.info("CHECKING MARKET CONTEXT FOR TODAY")
logging.info("=" * 80)
try:
    context_folder = 'context'
    today = datetime.datetime.now().strftime("%y%m%d")
    context_file = os.path.join(context_folder, f"{today}.txt")
    
    if not os.path.exists(context_file):
        logging.info(f"No market context found for today ({today}) - Generating now...")
        analyzer = MarketDataAnalyzer()
        market_context = analyzer.generate_market_context(force_refresh=True)
        
        # Check if data fetch failed
        if "Market data unavailable" in market_context:
            logging.error("=" * 80)
            logging.error("STARTUP MARKET DATA FETCH FAILED")
            logging.error("Yahoo Finance data is unavailable")
            logging.error("Context file will not be created")
            logging.error("System will attempt to use yesterday's context if available")
            logging.error("=" * 80)
        else:
            # Save the generated context only if successful
            os.makedirs(context_folder, exist_ok=True)
            with open(context_file, 'w', encoding='utf-8') as f:
                f.write(market_context)
            
            logging.info("=" * 80)
            logging.info("MARKET CONTEXT GENERATED:")
            logging.info("=" * 80)
            logging.info(market_context)
            logging.info("=" * 80)
    else:
        logging.info(f"Market context already exists for today ({today})")
        with open(context_file, 'r', encoding='utf-8') as f:
            existing_context = f.read()
        logging.info("=" * 80)
        logging.info("EXISTING MARKET CONTEXT:")
        logging.info("=" * 80)
        logging.info(existing_context)
        logging.info("=" * 80)
except Exception as e:
    logging.error(f"Error checking/generating startup market context: {e}")
    logging.exception("Full traceback:")

# Check/fetch economic calendar data if enabled
logging.info("=" * 80)
logging.info("CHECKING ECONOMIC CALENDAR DATA")
logging.info("=" * 80)
try:
    if config.has_section('EconomicCalendar') and config.getboolean('EconomicCalendar', 'enable_economic_calendar', fallback=False):
        calendar_file = config.get('EconomicCalendar', 'data_file', fallback='market_data/economic_calendar.json')
        classification_prompt = config.get('EconomicCalendar', 'classification_prompt', fallback='Analyze these economic calendar events and classify each by market impact severity (High/Medium/Low) for ES futures trading. For each event, provide expected market reaction and affected instruments. Return JSON format.')
        
        if not economic_calendar.has_current_week_data(calendar_file):
            logging.info("No economic calendar data for current trading week - Fetching now...")
            
            # Fetch events from MarketWatch
            raw_events = economic_calendar.fetch_marketwatch_calendar()
            
            if raw_events:
                logging.info(f"Fetched {len(raw_events)} events from MarketWatch")
                
                # Classify events with LLM
                openai_config = {
                    'api_key': OPENAI_API_KEY,
                    'api_url': OPENAI_API_URL
                }
                classified_events = economic_calendar.classify_events_with_llm(raw_events, openai_config, classification_prompt)
                
                # Save to file
                if economic_calendar.save_calendar_data(classified_events, calendar_file):
                    logging.info(f"Economic calendar data saved to {calendar_file}")
                    logging.info("=" * 80)
                    logging.info("ECONOMIC EVENTS FOR THIS WEEK:")
                    logging.info("=" * 80)
                    for event in classified_events[:10]:  # Show first 10 events
                        logging.info(f"{event.get('datetime', 'Unknown time')}: {event.get('name', 'Unknown')} ({event.get('severity', 'Unknown')})")
                    if len(classified_events) > 10:
                        logging.info(f"... and {len(classified_events) - 10} more events")
                    logging.info("=" * 80)
                else:
                    logging.error("Failed to save economic calendar data")
            else:
                logging.warning("No events fetched from MarketWatch")
        else:
            logging.info("Economic calendar data already exists for current trading week")
            # Load and display summary
            calendar_data = economic_calendar.load_calendar_data(calendar_file)
            if calendar_data and 'events' in calendar_data:
                events = calendar_data['events']
                logging.info(f"Loaded {len(events)} events for week {calendar_data.get('week_start')} to {calendar_data.get('week_end')}")
    else:
        logging.info("Economic calendar integration disabled in config")
except Exception as e:
    logging.error(f"Error checking/fetching economic calendar: {e}")
    logging.exception("Full traceback:")
    logging.info("System will continue without economic calendar data")

# Check/fetch market holiday data if enabled
logging.info("=" * 80)
logging.info("CHECKING MARKET HOLIDAY DATA")
logging.info("=" * 80)
try:
    if HOLIDAY_CONFIG['enabled']:
        holiday_file = HOLIDAY_CONFIG['data_file']
        
        # Check if we need to refresh
        need_refresh = HOLIDAY_CONFIG['force_refresh'] or not market_holidays.has_current_week_data(holiday_file)
        
        if need_refresh:
            logging.info("Fetching market holiday data for current trading week...")
            
            openai_config = {
                'api_key': OPENAI_API_KEY,
                'api_url': OPENAI_API_URL
            }
            
            # Fetch and parse week data
            holidays = market_holidays.fetch_and_parse_week(HOLIDAY_CONFIG['cme_url'], openai_config)
            
            if holidays:
                logging.info(f"Fetched {len(holidays)} days of holiday data")
                
                # Save to file
                if market_holidays.save_holiday_data(holidays, holiday_file):
                    logging.info(f"Market holiday data saved to {holiday_file}")
                    logging.info("=" * 80)
                    logging.info("MARKET HOLIDAYS FOR THIS WEEK:")
                    logging.info("=" * 80)
                    for day in holidays:
                        date_str = day.get('date', 'Unknown')
                        day_type = day.get('type', 'unknown')
                        notes = day.get('notes', '')
                        if day_type == 'closed':
                            logging.info(f"  🚫 {date_str}: CLOSED - {notes}")
                        elif day_type == 'early_close':
                            close_time = day.get('close_time', 'Unknown')
                            logging.info(f"  ⚠️  {date_str}: EARLY CLOSE at {close_time} - {notes}")
                        else:
                            logging.info(f"  ✅ {date_str}: Normal trading - {notes}")
                    logging.info("=" * 80)
                else:
                    logging.error("Failed to save market holiday data")
            else:
                logging.warning("No holiday data fetched")
        else:
            logging.info("Market holiday data already exists for current trading week")
            # Load and display summary
            holiday_data = market_holidays.load_holiday_data(holiday_file)
            if holiday_data and 'holidays' in holiday_data:
                holidays = holiday_data['holidays']
                logging.info(f"Loaded {len(holidays)} days for week {holiday_data.get('week_start')} to {holiday_data.get('week_end')}")
                
                # Check for upcoming holidays/early closes
                today = datetime.datetime.now().date()
                for day in holidays:
                    day_date = datetime.date.fromisoformat(day['date'])
                    if day_date >= today:
                        if day['type'] == 'closed':
                            logging.info(f"  ⚠️  {day['date']}: Market CLOSED - {day.get('notes', '')}")
                        elif day['type'] == 'early_close':
                            logging.info(f"  ⚠️  {day['date']}: Early close at {day.get('close_time', 'Unknown')} - {day.get('notes', '')}")
    else:
        logging.info("Market holiday checking disabled in config")
except Exception as e:
    logging.error(f"Error checking/fetching market holidays: {e}")
    logging.exception("Full traceback:")
    logging.info("System will continue without market holiday data")

logging.info("=" * 80)

# Log exact Topstep URLs and example POST requests for debug
logging.info("Topstep Debug URLs (all POST requests):")
logging.info(f"Login URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['login_endpoint']}")
logging.info(f"Accounts URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['accounts_endpoint']}")
logging.info(f"Contract Search URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['contracts_endpoint']}")
logging.info(f"Order Place URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['buy_endpoint']}")
logging.info(f"Positions URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['positions_endpoint']}")
logging.info(f"Working Orders URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['working_orders_endpoint']}")
logging.info(f"Trade Search URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['trade_search_endpoint']}")

# Example payloads for different endpoints
logging.info("Example POST Payloads:")
if TOPSTEP_CONFIG['account_id']:
    account_payload = {"accountId": int(TOPSTEP_CONFIG['account_id'])}
    logging.info(f"  Positions/Orders payload: {json.dumps(account_payload)}")
    
    order_payload = {
        "accountId": int(TOPSTEP_CONFIG['account_id']),
        "contractId": TOPSTEP_CONFIG.get('contract_id', 'CON.F.US.EP.Z25'),
        "type": 2,  # Market order
        "side": 0,
        "size": int(TOPSTEP_CONFIG['quantity']),
        "stopLossBracket": {"type": 4, "ticks": -16},
        "takeProfitBracket": {"type": 1, "ticks": 64}
    }
    logging.info(f"  Order payload example: {json.dumps(order_payload, indent=2)}")
logging.info(f"Headers Template: {{'Authorization': 'Bearer [auth_token]', 'Content-Type': 'application/json'}}")

# Helper function for scheduled context refresh
def refresh_base_context():
    """Refresh BASE market context from Yahoo Finance and save to YYMMDD.txt.
    
    This is called on a schedule (every 30 minutes) to keep market data current.
    It does NOT affect the LLM's observations (YYMMDD_LLM.txt).
    """
    try:
        logging.info("Scheduled context refresh - Fetching latest market data from Yahoo Finance")
        
        analyzer = MarketDataAnalyzer()
        market_context = analyzer.generate_market_context(force_refresh=True)
        
        # Check if data fetch failed
        if "Market data unavailable" in market_context:
            logging.error("Scheduled context refresh failed - Yahoo Finance data unavailable")
            logging.error("Existing context file will not be overwritten")
            return
        
        # Save to base context file (YYMMDD.txt) only if fetch was successful
        context_folder = 'context'
        os.makedirs(context_folder, exist_ok=True)
        today = datetime.datetime.now().strftime("%y%m%d")
        context_file = os.path.join(context_folder, f"{today}.txt")
        
        with open(context_file, 'w', encoding='utf-8') as f:
            f.write(market_context)
        
        logging.info(f"Base market context updated successfully in {context_file}")
        
    except Exception as e:
        logging.error(f"Error during scheduled context refresh: {e}")
        logging.exception("Full traceback:")
        logging.error("Existing context file will not be overwritten")

# NOTE: Job scheduling is now handled dynamically in run_scheduler() based on interval_seconds/interval_schedule
# The old schedule.every(INTERVAL_MINUTES).minutes.do(job) approach has been replaced with dynamic interval checking
# This allows for time-slot-based scheduling (e.g., different intervals for RTH vs after-hours)

# Schedule base context refresh every 30 minutes to keep market data current
schedule.every(30).minutes.do(refresh_base_context)
logging.info("Scheduled base context refresh every 30 minutes")
logging.info("Job scheduling uses dynamic intervals - see interval_seconds and interval_schedule in config.ini")

# Global flag to control trade monitoring (smart monitoring - only when needed)
# NOTE: These must be defined BEFORE the startup job() call below
monitoring_enabled = True  # Start as True for initial startup check
monitoring_lock = threading.Lock()  # Thread-safe flag access

def enable_trade_monitoring(reason=""):
    """Enable trade monitoring (start checking for position changes)."""
    global monitoring_enabled
    with monitoring_lock:
        if not monitoring_enabled:
            monitoring_enabled = True
            logging.info(f"✅ Trade monitoring ENABLED{': ' + reason if reason else ''}")

def disable_trade_monitoring(reason=""):
    """Disable trade monitoring (stop checking for position changes)."""
    global monitoring_enabled
    with monitoring_lock:
        if monitoring_enabled:
            monitoring_enabled = False
            logging.info(f"⛔ Trade monitoring DISABLED{': ' + reason if reason else ''}")

# Run the first job immediately on startup (before entering the scheduler loop)
# But first check if we're in a no-trade window or disabled interval to avoid unnecessary screenshots
logging.info("Checking if startup screenshot should be taken...")
startup_in_no_trades_window, startup_window = is_in_no_new_trades_window(NO_NEW_TRADES_WINDOWS)
startup_in_disabled_interval, next_active_time = is_in_disabled_interval(INTERVAL_SCHEDULE)

if startup_in_no_trades_window:
    logging.info(f"⏸️  STARTUP: In no-new-trades window '{startup_window}' - Skipping initial screenshot")
    logging.info("System will wait for next scheduled interval to begin operations")
elif startup_in_disabled_interval:
    if next_active_time:
        logging.info(f"⏸️  STARTUP: In disabled interval (interval=-1) - Skipping initial screenshot")
        logging.info(f"System will resume analysis at {next_active_time.strftime('%H:%M')}")
    else:
        logging.info(f"⏸️  STARTUP: In disabled interval (interval=-1) - Skipping initial screenshot")
        logging.info("No active intervals configured for today")
else:
    logging.info("Running initial screenshot job immediately on startup...")
    job(
        window_title=WINDOW_TITLE, 
        window_process_name=WINDOW_PROCESS_NAME, 
        top_offset=TOP_OFFSET, 
        bottom_offset=BOTTOM_OFFSET, 
        left_offset=LEFT_OFFSET, 
        right_offset=RIGHT_OFFSET, 
        save_folder=SAVE_FOLDER, 
        begin_time=BEGIN_TIME, 
        end_time=END_TIME, 
        symbol=SYMBOL, 
        position_type=POSITION_TYPE, 
        no_position_prompt=NO_POSITION_PROMPT, 
        long_position_prompt=LONG_POSITION_PROMPT,
        short_position_prompt=SHORT_POSITION_PROMPT,
        runner_prompt=RUNNER_PROMPT,
        model=MODEL,
        topstep_config=TOPSTEP_CONFIG,
        enable_llm=ENABLE_LLM,
        enable_trading=ENABLE_TRADING,
        openai_api_url=OPENAI_API_URL,
        openai_api_key=OPENAI_API_KEY,
        enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
        auth_token=AUTH_TOKEN,
        execute_trades=EXECUTE_TRADES,
        telegram_config=TELEGRAM_CONFIG,
        no_new_trades_windows=NO_NEW_TRADES_WINDOWS,
        force_close_time=FORCE_CLOSE_TIME
    )

# Global flag to control the scheduler
running = False
scheduler_thread = None
trade_monitor_thread = None

def get_current_interval():
    """Get the interval_seconds for the current time based on interval_schedule.
    
    LLM can override the schedule by setting next_snapshot in its response.
    This allows dynamic timing based on market conditions.
    
    Returns:
        int: interval_seconds for current time, or -1 if screenshots disabled
    """
    global INTERVAL_SCHEDULE, INTERVAL_SECONDS, NEXT_SNAPSHOT_OVERRIDE
    
    # Priority 1: LLM-requested override (dynamic timing based on market conditions)
    if NEXT_SNAPSHOT_OVERRIDE is not None:
        logging.debug(f"Using LLM-requested override: {NEXT_SNAPSHOT_OVERRIDE}s")
        return NEXT_SNAPSHOT_OVERRIDE
    
    # Priority 2: Time-based schedule
    if not INTERVAL_SCHEDULE or INTERVAL_SCHEDULE.strip() == '':
        # Fallback to interval_seconds if no schedule defined
        return INTERVAL_SECONDS
    
    current_time = datetime.datetime.now().time()
    
    # Parse schedule: "00:00-08:30=1800,08:30-09:30=300,..." (times in seconds)
    slots = [s.strip() for s in INTERVAL_SCHEDULE.split(',') if s.strip()]
    
    for slot in slots:
        try:
            # Parse: "HH:MM-HH:MM=seconds"
            time_range, interval = slot.split('=')
            start_str, end_str = time_range.split('-')
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            interval_seconds = int(interval)
            
            # Check if current time is in this slot (handle overnight)
            in_slot = False
            if start_time < end_time:
                # Same-day slot (e.g., 09:30 to 16:00)
                in_slot = start_time <= current_time < end_time
            else:
                # Overnight slot (e.g., 23:00 to 02:00)
                in_slot = current_time >= start_time or current_time < end_time
            
            if in_slot:
                logging.debug(f"Current time {current_time.strftime('%H:%M')} is in slot {slot} - interval={interval_seconds}s")
                return interval_seconds
                
        except Exception as e:
            logging.error(f"Error parsing interval_schedule slot '{slot}': {e}")
            continue
    
    # Not in any defined slot - use fallback
    logging.debug(f"Current time not in any interval_schedule slot - using fallback: {INTERVAL_SECONDS}s")
    return INTERVAL_SECONDS

def run_scheduler():
    """Scheduler with dynamic interval checking based on time slots."""
    global running, WINDOW_TITLE, TOP_OFFSET, BOTTOM_OFFSET, LEFT_OFFSET, RIGHT_OFFSET, SAVE_FOLDER
    global BEGIN_TIME, END_TIME, SYMBOL, POSITION_TYPE, NO_POSITION_PROMPT, LONG_POSITION_PROMPT
    global SHORT_POSITION_PROMPT, MODEL, TOPSTEP_CONFIG, ENABLE_LLM, ENABLE_TRADING
    global OPENAI_API_URL, OPENAI_API_KEY, ENABLE_SAVE_SCREENSHOTS, AUTH_TOKEN
    global EXECUTE_TRADES, TELEGRAM_CONFIG, NO_NEW_TRADES_WINDOWS, FORCE_CLOSE_TIME
    global LAST_JOB_TIME, FORCE_IMMEDIATE_ANALYSIS, RUNNER_PROMPT, NEXT_SNAPSHOT_OVERRIDE
    
    last_run_time = None
    last_interval_log = None
    
    while running:
        # Check if immediate analysis is requested (due to position discrepancy)
        if FORCE_IMMEDIATE_ANALYSIS:
            FORCE_IMMEDIATE_ANALYSIS = False  # Reset the flag
            
            # Clear any LLM snapshot override since we're taking an immediate screenshot
            NEXT_SNAPSHOT_OVERRIDE = None
            
            logging.info("="*80)
            logging.info("🚨 FORCE_IMMEDIATE_ANALYSIS triggered - Running immediate screenshot and LLM analysis")
            logging.info("="*80)
            try:
                # Run job immediately with corrected state
                job(
                    window_title=WINDOW_TITLE,
                    window_process_name=WINDOW_PROCESS_NAME,
                    top_offset=TOP_OFFSET,
                    bottom_offset=BOTTOM_OFFSET,
                    left_offset=LEFT_OFFSET,
                    right_offset=RIGHT_OFFSET,
                    save_folder=SAVE_FOLDER,
                    begin_time=BEGIN_TIME,
                    end_time=END_TIME,
                    symbol=SYMBOL,
                    position_type=POSITION_TYPE,
                    no_position_prompt=NO_POSITION_PROMPT,
                    long_position_prompt=LONG_POSITION_PROMPT,
                    short_position_prompt=SHORT_POSITION_PROMPT,
                    runner_prompt=RUNNER_PROMPT,
                    model=MODEL,
                    topstep_config=TOPSTEP_CONFIG,
                    enable_llm=ENABLE_LLM,
                    enable_trading=ENABLE_TRADING,
                    openai_api_url=OPENAI_API_URL,
                    openai_api_key=OPENAI_API_KEY,
                    enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
                    auth_token=AUTH_TOKEN,
                    execute_trades=EXECUTE_TRADES,
                    telegram_config=TELEGRAM_CONFIG,
                    no_new_trades_windows=NO_NEW_TRADES_WINDOWS,
                    force_close_time=FORCE_CLOSE_TIME
                )
                last_run_time = datetime.datetime.now()
                LAST_JOB_TIME = last_run_time
                logging.info("✅ Immediate analysis completed - Position state now correct for LLM")
            except Exception as e:
                logging.error(f"Error running immediate analysis job: {e}")
                logging.exception("Full traceback:")
        
        current_interval = get_current_interval()
        
        # Log interval changes (but not on every iteration)
        current_minute = datetime.datetime.now().strftime("%H:%M")
        if current_minute != last_interval_log:
            logging.info(f"Current interval: {current_interval}s ({current_interval/60:.1f} minutes)")
            last_interval_log = current_minute
        
        # Skip if disabled (-1)
        if current_interval == -1:
            logging.debug("Screenshots disabled for current time slot")
            time.sleep(60)  # Check again in 1 minute
            continue
        
        # Check if enough time has passed
        current_time = datetime.datetime.now()
        if last_run_time is None or (current_time - last_run_time).total_seconds() >= current_interval:
            logging.info(f"Running scheduled job (interval: {current_interval}s)")
            
            # Clear the LLM override after using it (it only applies to the NEXT screenshot)
            if NEXT_SNAPSHOT_OVERRIDE is not None:
                logging.debug(f"Clearing NEXT_SNAPSHOT_OVERRIDE ({NEXT_SNAPSHOT_OVERRIDE}s) - was used for this screenshot")
                NEXT_SNAPSHOT_OVERRIDE = None
            
            try:
                # Call job directly instead of using schedule.run_pending()
                job(
                    window_title=WINDOW_TITLE,
                    window_process_name=WINDOW_PROCESS_NAME,
                    top_offset=TOP_OFFSET,
                    bottom_offset=BOTTOM_OFFSET,
                    left_offset=LEFT_OFFSET,
                    right_offset=RIGHT_OFFSET,
                    save_folder=SAVE_FOLDER,
                    begin_time=BEGIN_TIME,
                    end_time=END_TIME,
                    symbol=SYMBOL,
                    position_type=POSITION_TYPE,
                    no_position_prompt=NO_POSITION_PROMPT,
                    long_position_prompt=LONG_POSITION_PROMPT,
                    short_position_prompt=SHORT_POSITION_PROMPT,
                    runner_prompt=RUNNER_PROMPT,
                    model=MODEL,
                    topstep_config=TOPSTEP_CONFIG,
                    enable_llm=ENABLE_LLM,
                    enable_trading=ENABLE_TRADING,
                    openai_api_url=OPENAI_API_URL,
                    openai_api_key=OPENAI_API_KEY,
                    enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
                    auth_token=AUTH_TOKEN,
                    execute_trades=EXECUTE_TRADES,
                    telegram_config=TELEGRAM_CONFIG,
                    no_new_trades_windows=NO_NEW_TRADES_WINDOWS,
                    force_close_time=FORCE_CLOSE_TIME
                )
            except Exception as e:
                logging.error(f"Error running scheduled job: {e}")
                logging.exception("Full traceback:")
            
            last_run_time = current_time
            LAST_JOB_TIME = current_time  # Update global for dashboard countdown
        
        time.sleep(1)

def run_trade_monitor():
    """Background thread to continuously monitor trade status (smart monitoring - only when needed)."""
    global running, ACCOUNT_BALANCE, monitoring_enabled, FORCE_IMMEDIATE_ANALYSIS
    last_active_state = None
    last_position_type = 'none'  # Track last known position
    initial_check_done = False  # Track if we've done the initial startup check
    
    while running:
        try:
            # Check if monitoring is enabled
            with monitoring_lock:
                is_monitoring = monitoring_enabled
            
            if not is_monitoring:
                # Monitoring disabled - sleep longer and skip checks
                if not initial_check_done:
                    logging.debug("Trade monitoring disabled - waiting for trade execution or manual enable")
                    initial_check_done = True  # Prevent repeated logs
                time.sleep(60)  # Sleep 1 minute when disabled
                continue
            
            # Only check trades during trading hours
            if is_within_time_range(BEGIN_TIME, END_TIME):
                # Get current position with details
                current_position_type, position_details, working_orders = get_current_position(
                    SYMBOL, TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN, return_details=True
                )
                is_active = current_position_type in ['long', 'short']
                
                # Check for position discrepancies between local tracking and API
                discrepancy = check_position_discrepancy(current_position_type, position_details)
                if discrepancy:
                    logging.info("⚠️ DISCREPANCY DETECTED in trade monitor - correcting state")
                    
                    # Correct the system state to match API reality
                    success = correct_position_state(
                        discrepancy,
                        current_position_type,
                        position_details,
                        working_orders,
                        TOPSTEP_CONFIG,
                        ENABLE_TRADING,
                        AUTH_TOKEN
                    )
                    
                    if success:
                        # Set flag to trigger immediate screenshot and LLM analysis
                        FORCE_IMMEDIATE_ANALYSIS = True
                        logging.info("🔄 FORCE_IMMEDIATE_ANALYSIS flag set - will trigger screenshot on next scheduler tick")
                
                # Initial startup check - disable monitoring if no position found
                if not initial_check_done:
                    initial_check_done = True
                    if not is_active:
                        disable_trade_monitoring("No positions found on startup")
                        continue  # Skip to next iteration (will sleep 60s)
                
                # Detect position closure (was active, now none)
                if last_position_type in ['long', 'short'] and current_position_type == 'none':
                    logging.info(f"="*80)
                    logging.info(f"TRADE MONITOR: Position closed detected!")
                    logging.info(f"Previous position: {last_position_type.upper()}")
                    logging.info(f"Fetching trade results from API...")
                    logging.info(f"="*80)
                    
                    # Get trade info
                    trade_info = get_active_trade_info()
                    if trade_info:
                        # Fetch trade results from API
                        entry_timestamp = trade_info.get('entry_timestamp')
                        if entry_timestamp:
                            start_time = entry_timestamp
                        else:
                            # Fallback to today's start if no timestamp
                            start_time = datetime.datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                        
                        end_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                        
                        trades = fetch_trade_results(
                            TOPSTEP_CONFIG['account_id'],
                            TOPSTEP_CONFIG,
                            ENABLE_TRADING,
                            AUTH_TOKEN,
                            start_time,
                            end_time
                        )
                        
                        if trades:
                            # Calculate net P&L from all fills
                            total_pnl = sum(trade.get('profitAndLoss', 0) for trade in trades)
                            total_fees = sum(trade.get('fees', 0) for trade in trades)
                            net_pnl = total_pnl - total_fees
                            
                            # Get entry price and position details
                            entry_price = trade_info.get('entry_price', 0)
                            trade_position_type = trade_info.get('position_type', last_position_type)
                            size = TOPSTEP_CONFIG.get('quantity', 1)
                            
                            # Calculate P&L in points (assuming ES multiplier of $50 per point)
                            pnl_points = net_pnl / 50 if net_pnl else 0
                            
                            # Get stored SL/TP order IDs for exit type determination
                            stop_loss_order_id = trade_info.get('stop_loss_order_id')
                            take_profit_order_id = trade_info.get('take_profit_order_id')
                            
                            # Find the closing trade's order ID (look for the exit trade)
                            exit_trade_order_id = None
                            exit_price = None
                            for trade in reversed(trades):
                                trade_side = trade.get('side', 0)
                                # Exit trade: sell closes long, buy closes short
                                if (trade_position_type == 'long' and trade_side == 1) or \
                                   (trade_position_type == 'short' and trade_side == 0):
                                    exit_trade_order_id = trade.get('orderId')
                                    exit_price = trade.get('price')
                                    break
                            
                            # Determine exit type by matching order IDs
                            exit_type = determine_exit_type(exit_trade_order_id, stop_loss_order_id, take_profit_order_id)
                            
                            # Determine success/failure
                            is_success = net_pnl > 0
                            emoji = "✅" if is_success else "❌"
                            result_text = "PROFIT" if is_success else "LOSS"
                            
                            # Set appropriate emoji based on exit type
                            if exit_type == "STOP LOSS HIT":
                                exit_emoji = "🛑"
                            elif exit_type == "TAKE PROFIT HIT":
                                exit_emoji = "🎯"
                            else:
                                exit_emoji = "📤"
                            
                            logging.info(f"="*80)
                            logging.info(f"TRADE CLOSED - {exit_type} - {result_text}")
                            logging.info(f"Position: {trade_position_type.upper()}")
                            logging.info(f"Entry Price: {entry_price}")
                            logging.info(f"Exit Price: {exit_price}")
                            logging.info(f"Exit Order ID: {exit_trade_order_id}")
                            logging.info(f"Stored SL Order ID: {stop_loss_order_id}")
                            logging.info(f"Stored TP Order ID: {take_profit_order_id}")
                            logging.info(f"Net P&L: ${net_pnl:.2f} ({pnl_points:+.2f} pts)")
                            logging.info(f"Fees: ${total_fees:.2f}")
                            logging.info(f"Total Fills: {len(trades)}")
                            logging.info(f"="*80)
                            
                            # Get updated balance
                            balance = get_account_balance(TOPSTEP_CONFIG['account_id'], TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
                            if balance is not None:
                                ACCOUNT_BALANCE = balance
                            
                            # Get current market context
                            daily_context = get_daily_context()
                            
                            # Log CLOSE event with actual P&L and exit type
                            log_trade_event(
                                event_type="CLOSE",
                                symbol=SYMBOL,
                                position_type=trade_position_type,
                                size=size,
                                price=exit_price if exit_price else 0,
                                reasoning=f"Position closed: {exit_type}",
                                profit_loss=net_pnl,
                                profit_loss_points=pnl_points,
                                balance=balance,
                                market_context=daily_context,
                                order_id=trade_info.get('order_id'),
                                entry_price=entry_price
                            )
                            
                            # Send Telegram notification with specific exit type
                            telegram_msg = (
                                f"{exit_emoji} <b>{exit_type}</b>\n"
                                f"{emoji} Result: {result_text}\n"
                                f"Position: {trade_position_type.upper()}\n"
                                f"Size: {size} contract(s)\n"
                                f"Entry Price: {entry_price}\n"
                            )
                            
                            if exit_price:
                                telegram_msg += f"Exit Price: {exit_price}\n"
                            
                            telegram_msg += (
                                f"P&L: ${net_pnl:+,.2f} ({pnl_points:+.2f} pts)\n"
                                f"Fees: ${total_fees:.2f}\n"
                            )
                            
                            if balance is not None:
                                telegram_msg += f"💰 Balance: ${balance:,.2f}\n"
                            
                            telegram_msg += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            send_telegram_message(telegram_msg, TELEGRAM_CONFIG)
                            logging.info(f"Telegram notification sent for {exit_type}")
                            
                            # Clear active trade info
                            clear_active_trade_info()
                            
                            # Update dashboard
                            update_dashboard_data()
                            logging.info("Dashboard updated with closed position results")
                            
                            # Trigger immediate screenshot for post-trade analysis
                            FORCE_IMMEDIATE_ANALYSIS = True
                            logging.info("🚨 FORCE_IMMEDIATE_ANALYSIS set - screenshot will be taken for post-trade analysis")
                            
                            # Disable monitoring now that position is closed
                            disable_trade_monitoring("Position closed")
                        else:
                            logging.warning("Could not fetch trade results from API")
                            # Still trigger screenshot and disable monitoring
                            FORCE_IMMEDIATE_ANALYSIS = True
                            logging.info("🚨 FORCE_IMMEDIATE_ANALYSIS set - screenshot will be taken despite missing trade results")
                            disable_trade_monitoring("Position closed (results fetch failed)")
                    else:
                        logging.warning("No active trade info found for closed position")
                        # Still trigger screenshot and disable monitoring
                        FORCE_IMMEDIATE_ANALYSIS = True
                        logging.info("🚨 FORCE_IMMEDIATE_ANALYSIS set - screenshot will be taken despite missing trade info")
                        disable_trade_monitoring("Position closed (no trade info found)")
                
                # Update last known position
                last_position_type = current_position_type
                
                # Log state changes
                if is_active != last_active_state:
                    if is_active:
                        logging.info("Trade monitoring: Active position detected - LLM analysis paused")
                    else:
                        logging.info("Trade monitoring: No active positions - LLM analysis will resume on next cycle")
                    last_active_state = is_active
            else:
                # Outside trading hours, reset state
                if last_active_state is not None:
                    logging.debug("Trade monitoring paused - outside trading hours")
                    last_active_state = None
                    last_position_type = 'none'
            
            time.sleep(TRADE_STATUS_CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Error in trade monitor thread: {e}")
            logging.exception("Full traceback:")
            time.sleep(TRADE_STATUS_CHECK_INTERVAL)

def start_scheduler(icon):
    global running, scheduler_thread, trade_monitor_thread
    if not running:
        running = True
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # Start trade monitor thread if trading is enabled
        if ENABLE_TRADING:
            trade_monitor_thread = threading.Thread(target=run_trade_monitor, daemon=True)
            trade_monitor_thread.start()
            logging.info(f"Trade monitor started (checking every {TRADE_STATUS_CHECK_INTERVAL}s)")
        
        icon.notify("Scheduler started.")
        logging.info("Scheduler started.")
        icon.icon = icon.green_image  # Set to green when running

def stop_scheduler(icon):
    global running, scheduler_thread, trade_monitor_thread
    if running:
        running = False
        if scheduler_thread:
            scheduler_thread.join(timeout=2)
        if trade_monitor_thread:
            trade_monitor_thread.join(timeout=2)
        icon.notify("Scheduler stopped.")
        logging.info("Scheduler stopped.")
        icon.icon = icon.red_image  # Set to red when stopped

def quit_app(icon):
    stop_scheduler(icon)
    icon.stop()
    logging.info("Application quit.")
    # Exit the application completely
    import sys
    sys.exit(0)

# Create tray icon
def create_tray_icon():
    # Use simple icons (green for running, red for stopped)
    green_image = Image.new('RGB', (64, 64), color=(0, 255, 0))
    red_image = Image.new('RGB', (64, 64), color=(255, 0, 0))
    menu = (
        item('Show Dashboard', lambda icon, item: show_dashboard()),
        item('Start', start_scheduler),
        item('Stop', stop_scheduler),
        item('Reload Config', lambda icon, item: reload_config()),
        item('Refresh Market Context', lambda icon, item: refresh_market_context()),
        item('Clear Active Trade', lambda icon, item: clear_trade_and_disable_monitoring()),
        item('Reconcile Closed Trades', lambda icon, item: manual_reconcile_trades()),
        item('Reset Session RPL', lambda icon, item: reset_session_rpl()),
        item('Enable Trade Monitoring', lambda icon, item: enable_trade_monitoring("Manual enable via tray menu")),
        item('Set Position', pystray.Menu(
            item('None', lambda icon, item: set_position('none')),
            item('Long', lambda icon, item: set_position('long')),
            item('Short', lambda icon, item: set_position('short'))
        )),
        item('Toggle LLM', lambda icon, item: toggle_flag('enable_llm')),
        item('Toggle Trading', lambda icon, item: toggle_flag('enable_trading')),
        item('Select Account', pystray.Menu(
            item('Default (None)', lambda icon, item: set_account('')),
            item('Account1', lambda icon, item: set_account('account1')),
            item('Account2', lambda icon, item: set_account('account2'))
            # Add more as needed or make dynamic
        )),
        item('Test Positions Endpoint', lambda icon, item: test_positions()),
        item('Test Active Positions Check', lambda icon, item: test_active_trades()),
        item('List All Contracts', lambda icon, item: list_all_contracts()),
        item('Take Screenshot Now', lambda icon, item: manual_job()),
        item('Exit', quit_app)
    )
    icon = pystray.Icon("screenshot_uploader", green_image, "Screenshot Uploader", menu)
    icon.green_image = green_image
    red_image = red_image
    return icon

def set_position(new_position):
    global POSITION_TYPE
    POSITION_TYPE = new_position
    # Update config file to persist
    config['LLM']['position_type'] = new_position
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Position set to: {new_position}")

def toggle_flag(flag_name):
    current = config.getboolean('General', flag_name) if flag_name in ['enable_llm', 'enable_trading'] else False
    new_value = not current
    config['General'][flag_name] = str(new_value).lower()
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Toggled {flag_name} to {new_value}")

def set_account(new_account_id):
    config['Topstep']['account_id'] = new_account_id
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Account set to: {new_account_id or 'Default (None)'}")

def test_positions():
    logging.info("Testing positions endpoint.")
    position_type = get_current_position(SYMBOL, TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
    logging.info(f"Test result: Position type = {position_type}")

def test_active_trades():
    logging.info("Testing active positions check.")
    has_active_trades = check_active_trades(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
    logging.info(f"Test result: Active positions = {has_active_trades}")

def clear_trade_and_disable_monitoring():
    """Helper function to clear active trade and disable monitoring (for tray menu)."""
    clear_active_trade_info()
    disable_trade_monitoring("Manual clear via tray menu")
    update_dashboard_data()

def reset_session_rpl():
    """Reset session RPL tracking (manual reset)."""
    global SESSION_START_BALANCE, SESSION_START_TIME, CURRENT_RPL
    
    # Get current balance
    if ACCOUNT_BALANCE is not None:
        SESSION_START_BALANCE = ACCOUNT_BALANCE
        SESSION_START_TIME = datetime.datetime.now()
        CURRENT_RPL = 0.0
        logging.info(f"Session RPL manually reset - New session start balance: ${SESSION_START_BALANCE:,.2f}")
        
        # Update dashboard
        update_dashboard_data()
    else:
        logging.warning("Cannot reset session RPL - no current balance available")

def manual_reconcile_trades():
    """Manually trigger trade reconciliation (for tray menu)."""
    logging.info("=== MANUAL TRADE RECONCILIATION TRIGGERED ===")
    try:
        reconcile_closed_trades(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
        reconcile_supabase_open_trades(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
        logging.info("=== MANUAL RECONCILIATION COMPLETE ===")
    except Exception as e:
        logging.error(f"Error during manual reconciliation: {e}")
        logging.exception("Full traceback:")

def create_tray_icon():
    # Use simple icons (green for running, red for stopped)
    green_image = Image.new('RGB', (64, 64), color=(0, 255, 0))
    red_image = Image.new('RGB', (64, 64), color=(255, 0, 0))
    menu = (
        item('Show Dashboard', lambda icon, item: show_dashboard()),
        item('Start', start_scheduler),
        item('Stop', stop_scheduler),
        item('Reload Config', lambda icon, item: reload_config()),
        item('Refresh Market Context', lambda icon, item: refresh_market_context()),
        item('Clear Active Trade', lambda icon, item: clear_trade_and_disable_monitoring()),
        item('Reconcile Closed Trades', lambda icon, item: manual_reconcile_trades()),
        item('Reset Session RPL', lambda icon, item: reset_session_rpl()),
        item('Enable Trade Monitoring', lambda icon, item: enable_trade_monitoring("Manual enable via tray menu")),
        item('Set Position', pystray.Menu(
            item('None', lambda icon, item: set_position('none')),
            item('Long', lambda icon, item: set_position('long')),
            item('Short', lambda icon, item: set_position('short'))
        )),
        item('Toggle LLM', lambda icon, item: toggle_flag('enable_llm')),
        item('Toggle Trading', lambda icon, item: toggle_flag('enable_trading')),
        item('Select Account', pystray.Menu(
            item('Default (None)', lambda icon, item: set_account('')),
            item('Account1', lambda icon, item: set_account('account1')),
            item('Account2', lambda icon, item: set_account('account2'))
            # Add more as needed or make dynamic
        )),
        item('Test Positions Endpoint', lambda icon, item: test_positions()),
        item('Test Active Positions Check', lambda icon, item: test_active_trades()),
        item('List All Contracts', lambda icon, item: list_all_contracts()),
        item('Take Screenshot Now', lambda icon, item: manual_job()),
        item('Exit', quit_app)
    )
    icon = pystray.Icon("screenshot_uploader", green_image, "Screenshot Uploader", menu)
    icon.green_image = green_image
    icon.red_image = red_image
    return icon

def set_position(new_position):
    global POSITION_TYPE
    POSITION_TYPE = new_position
    # Update config file to persist
    config['LLM']['position_type'] = new_position
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Position set to: {new_position}")

def toggle_flag(flag_name):
    current = config.getboolean('General', flag_name) if flag_name in ['enable_llm', 'enable_trading'] else False
    new_value = not current
    config['General'][flag_name] = str(new_value).lower()
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Toggled {flag_name} to {new_value}")

def set_account(new_account_id):
    config['Topstep']['account_id'] = new_account_id
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    logging.info(f"Account set to: {new_account_id or 'Default (None)'}")

def test_positions():
    logging.info("Testing positions endpoint.")
    position_type = get_current_position(SYMBOL, TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
    logging.info(f"Test result: Position type = {position_type}")

def test_active_trades():
    logging.info("Testing active positions check.")
    has_active_trades = check_active_trades(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
    logging.info(f"Test result: Active positions = {has_active_trades}")

def reload_config():
    """Reload configuration from config.ini without restarting the application."""
    global config, INTERVAL_MINUTES, INTERVAL_SECONDS, INTERVAL_SCHEDULE, TRADE_STATUS_CHECK_INTERVAL, BEGIN_TIME, END_TIME
    global NO_NEW_TRADES_WINDOWS, FORCE_CLOSE_TIME
    global WINDOW_TITLE, WINDOW_PROCESS_NAME, TOP_OFFSET, BOTTOM_OFFSET, LEFT_OFFSET, RIGHT_OFFSET, SAVE_FOLDER
    global ENABLE_LLM, ENABLE_TRADING, EXECUTE_TRADES, ENABLE_SAVE_SCREENSHOTS
    global SYMBOL, DISPLAY_SYMBOL, POSITION_TYPE, NO_POSITION_PROMPT
    global LONG_POSITION_PROMPT, SHORT_POSITION_PROMPT, RUNNER_PROMPT, MODEL
    global TOPSTEP_CONFIG, OPENAI_API_KEY, OPENAI_API_URL, TELEGRAM_CONFIG
    
    try:
        logging.info("=" * 80)
        logging.info("RELOADING CONFIGURATION")
        logging.info("=" * 80)
        
        # Reload config file
        config = configparser.ConfigParser()
        config.read('config.ini')
        
        # Reload General settings
        INTERVAL_MINUTES = int(config.get('General', 'interval_minutes', fallback='5'))
        INTERVAL_SECONDS = int(config.get('General', 'interval_seconds', fallback=str(INTERVAL_MINUTES * 60)))
        INTERVAL_SCHEDULE = config.get('General', 'interval_schedule', fallback='')
        TRADE_STATUS_CHECK_INTERVAL = int(config.get('General', 'trade_status_check_interval', fallback='10'))
        BEGIN_TIME = config.get('General', 'begin_time', fallback='00:00')
        END_TIME = config.get('General', 'end_time', fallback='23:59')
        NO_NEW_TRADES_WINDOWS = config.get('General', 'no_new_trades_windows', fallback='')
        FORCE_CLOSE_TIME = config.get('General', 'force_close_time', fallback='23:59')
        WINDOW_TITLE = config.get('General', 'window_title', fallback=None)
        WINDOW_PROCESS_NAME = config.get('General', 'window_process_name', fallback=None)
        TOP_OFFSET = int(config.get('General', 'top_offset', fallback='0'))
        BOTTOM_OFFSET = int(config.get('General', 'bottom_offset', fallback='0'))
        LEFT_OFFSET = int(config.get('General', 'left_offset', fallback='0'))
        RIGHT_OFFSET = int(config.get('General', 'right_offset', fallback='0'))
        SAVE_FOLDER = config.get('General', 'save_folder', fallback=None)
        ENABLE_LLM = config.getboolean('General', 'enable_llm', fallback=True)
        ENABLE_TRADING = config.getboolean('General', 'enable_trading', fallback=False)
        EXECUTE_TRADES = config.getboolean('General', 'execute_trades', fallback=False)
        ENABLE_SAVE_SCREENSHOTS = config.getboolean('General', 'enable_save_screenshots', fallback=False)
        
        # Reload LLM settings
        SYMBOL = config.get('LLM', 'symbol', fallback='ES')
        DISPLAY_SYMBOL = config.get('LLM', 'display_symbol', fallback='ES')
        POSITION_TYPE = config.get('LLM', 'position_type', fallback='none')
        
        # Load prompts (supports both file paths and inline text)
        no_position_prompt_config = config.get('LLM', 'no_position_prompt', fallback='')
        NO_POSITION_PROMPT = load_prompt_from_config(no_position_prompt_config, no_position_prompt_config)
        
        long_prompt_config = config.get('LLM', 'long_position_prompt', fallback=None)
        short_prompt_config = config.get('LLM', 'short_position_prompt', fallback=None)
        position_prompt_config = config.get('LLM', 'position_prompt', fallback='')
        
        if long_prompt_config:
            LONG_POSITION_PROMPT = load_prompt_from_config(long_prompt_config, position_prompt_config)
        else:
            LONG_POSITION_PROMPT = load_prompt_from_config(position_prompt_config, position_prompt_config)
        
        if short_prompt_config:
            SHORT_POSITION_PROMPT = load_prompt_from_config(short_prompt_config, position_prompt_config)
        else:
            SHORT_POSITION_PROMPT = load_prompt_from_config(position_prompt_config, position_prompt_config)
        
        # Load runner prompt for managing runner contracts after scaling out
        runner_prompt_config = config.get('LLM', 'runner_prompt', fallback='runner_prompt.txt')
        RUNNER_PROMPT = load_prompt_from_config(runner_prompt_config, runner_prompt_config)
        
        MODEL = config.get('LLM', 'model', fallback='gpt-4o')
        
        # Reload Topstep settings
        TOPSTEP_CONFIG.update({
            'user_name': config.get('Topstep', 'user_name', fallback=''),
            'api_key': config.get('Topstep', 'api_key', fallback=''),
            'api_secret': config.get('Topstep', 'api_secret', fallback=''),
            'account_id': config.get('Topstep', 'account_id', fallback=''),
            'contract_id': config.get('Topstep', 'contract_id', fallback=''),
            'quantity': config.get('Topstep', 'quantity', fallback='1'),
            'runners_quantity': config.getint('Topstep', 'runners_quantity', fallback=0),
            'contract_to_search': config.get('Topstep', 'contract_to_search', fallback='ES'),
            'trade_search_endpoint': config.get('Topstep', 'trade_search_endpoint', fallback='/api/Trade/search'),
            'max_risk_per_contract': config.get('Topstep', 'max_risk_per_contract', fallback=''),
            'max_profit_per_contract': config.get('Topstep', 'max_profit_per_contract', fallback=''),
            'enable_stop_loss': config.getboolean('Topstep', 'enable_stop_loss', fallback=True),
            'enable_take_profit': config.getboolean('Topstep', 'enable_take_profit', fallback=True),
            'tick_size': config.getfloat('Topstep', 'tick_size', fallback=0.25)
        })
        
        # Reload OpenAI settings
        OPENAI_API_KEY = config.get('OpenAI', 'api_key', fallback='')
        OPENAI_API_URL = config.get('OpenAI', 'api_url', fallback='https://api.openai.com/v1/chat/completions')
        
        # Reload Telegram settings
        TELEGRAM_CONFIG.update({
            'api_key': config.get('Telegram', 'telegram_api_key', fallback=''),
            'chat_id': config.get('Telegram', 'telegram_chat_id', fallback='')
        })
        
        # Reload Market Holidays settings
        global HOLIDAY_CONFIG
        HOLIDAY_CONFIG = {
            'enabled': config.getboolean('MarketHolidays', 'enable_holiday_check', fallback=True),
            'cme_url': config.get('MarketHolidays', 'cme_url', fallback='https://www.cmegroup.com/trading-hours.html'),
            'data_file': config.get('MarketHolidays', 'data_file', fallback='market_data/market_holidays.json'),
            'minutes_before_close': int(config.get('MarketHolidays', 'minutes_before_close', fallback='30')),
            'minutes_after_open': int(config.get('MarketHolidays', 'minutes_after_open', fallback='5')),
            'force_refresh': config.getboolean('MarketHolidays', 'force_refresh', fallback=False),
            'market_closed': config.get('MarketHolidays', 'market_closed', fallback='')
        }
        
        logging.info("Configuration reloaded successfully:")
        logging.info(f"  INTERVAL_MINUTES={INTERVAL_MINUTES}, INTERVAL_SECONDS={INTERVAL_SECONDS}")
        logging.info(f"  INTERVAL_SCHEDULE={INTERVAL_SCHEDULE or 'Not set (using interval_seconds)'}")
        logging.info(f"  BEGIN_TIME={BEGIN_TIME}, END_TIME={END_TIME}")
        logging.info(f"  NO_NEW_TRADES_WINDOWS={NO_NEW_TRADES_WINDOWS}")
        logging.info(f"  FORCE_CLOSE_TIME={FORCE_CLOSE_TIME}")
        logging.info(f"  ENABLE_LLM={ENABLE_LLM}, ENABLE_TRADING={ENABLE_TRADING}, EXECUTE_TRADES={EXECUTE_TRADES}")
        logging.info(f"  ACCOUNT_ID={TOPSTEP_CONFIG['account_id']}, CONTRACT_ID={TOPSTEP_CONFIG['contract_id']}")
        logging.info("=" * 80)
        
        # Clear and reschedule only the context refresh (job scheduling is handled dynamically)
        schedule.clear()
        schedule.every(30).minutes.do(refresh_base_context)
        
        logging.info("Config reload complete - changes will take effect immediately")
        logging.info(f"Dynamic scheduler will use: INTERVAL_SECONDS={INTERVAL_SECONDS}s or INTERVAL_SCHEDULE={INTERVAL_SCHEDULE or 'Not set'}")
        logging.info("Base context refresh rescheduled every 30 minutes")
        
        return True
        
    except Exception as e:
        logging.error(f"Error reloading configuration: {e}")
        logging.exception("Full traceback:")
        return False

def list_all_contracts():
    """Manually fetch and log all available contracts from Topstep API."""
    logging.info("Manually fetching all available contracts...")
    if not ENABLE_TRADING:
        logging.warning("Trading is disabled - cannot fetch contracts")
        return
    
    if not AUTH_TOKEN:
        logging.error("No auth token available - cannot fetch contracts")
        return
    
    all_contracts = get_available_contracts(TOPSTEP_CONFIG, AUTH_TOKEN)  # No symbol parameter = fetch all
    if all_contracts:
        logging.info(f"Successfully fetched {len(all_contracts) if isinstance(all_contracts, list) else 'N/A'} available contracts")
        # Log some contract details for better readability
        if isinstance(all_contracts, list) and len(all_contracts) > 0:
            logging.info("Sample contracts:")
            for contract in all_contracts[:5]:  # Show first 5 contracts
                if isinstance(contract, dict):
                    symbol = contract.get('symbol', 'Unknown')
                    name = contract.get('name', 'Unknown')
                    logging.info(f"  - {symbol}: {name}")
            if len(all_contracts) > 5:
                logging.info(f"  ... and {len(all_contracts) - 5} more contracts")
        TOPSTEP_CONFIG['all_available_contracts'] = all_contracts  # Store for later use
    else:
        logging.warning("Failed to fetch all available contracts")

def refresh_market_context():
    """Manually refresh BASE market context by fetching fresh data from Yahoo Finance.
    
    This regenerates the original market data context (YYMMDD.txt) from Yahoo Finance.
    It does NOT affect the LLM's updated context (YYMMDD_LLM.txt).
    """
    try:
        logging.info("=" * 80)
        logging.info("MANUALLY REFRESHING BASE MARKET CONTEXT FROM YAHOO FINANCE")
        logging.info("=" * 80)
        
        analyzer = MarketDataAnalyzer()
        market_context = analyzer.generate_market_context(force_refresh=True)
        
        # Check if data fetch failed
        if "Market data unavailable" in market_context:
            logging.error("=" * 80)
            logging.error("MARKET DATA FETCH FAILED")
            logging.error("Yahoo Finance data is unavailable")
            logging.error("Existing context file will not be overwritten")
            logging.error("=" * 80)
            return
        
        # Save the generated context to base context file (YYMMDD.txt) only if successful
        # This does NOT overwrite the LLM's updated context (YYMMDD_LLM.txt)
        context_folder = 'context'
        os.makedirs(context_folder, exist_ok=True)
        today = datetime.datetime.now().strftime("%y%m%d")
        context_file = os.path.join(context_folder, f"{today}.txt")
        
        with open(context_file, 'w', encoding='utf-8') as f:
            f.write(market_context)
        
        # Add after-hours notice for display (but don't save it to file)
        display_context = market_context
        if is_after_hours():
            display_context += "\n\n⚠️ PLEASE NOTE: THIS IS AFTER HOURS TRADING (Outside Regular Trading Hours 8:30 AM - 3:00 PM CT)"
        
        logging.info("=" * 80)
        logging.info("UPDATED MARKET CONTEXT:")
        logging.info("=" * 80)
        logging.info(display_context)
        logging.info("=" * 80)
        logging.info(f"Market context saved to {context_file}")
        logging.info("Context will be used in next trading job")
        
    except Exception as e:
        logging.error(f"Error refreshing market context: {e}")
        logging.exception("Full traceback:")
        logging.error("Existing context file will not be overwritten")

def manual_job():
    logging.info("Manual screenshot triggered.")
    job(
        window_title=WINDOW_TITLE, 
        window_process_name=WINDOW_PROCESS_NAME, 
        top_offset=TOP_OFFSET, 
        bottom_offset=BOTTOM_OFFSET, 
        left_offset=LEFT_OFFSET, 
        right_offset=RIGHT_OFFSET, 
        save_folder=SAVE_FOLDER, 
        begin_time=BEGIN_TIME, 
        end_time=END_TIME,
        symbol=SYMBOL,
        position_type=POSITION_TYPE,
        no_position_prompt=NO_POSITION_PROMPT,
        long_position_prompt=LONG_POSITION_PROMPT,
        short_position_prompt=SHORT_POSITION_PROMPT,
        runner_prompt=RUNNER_PROMPT,
        model=MODEL,
        topstep_config=TOPSTEP_CONFIG,
        enable_llm=ENABLE_LLM,
        enable_trading=ENABLE_TRADING,
        openai_api_url=OPENAI_API_URL,
        openai_api_key=OPENAI_API_KEY,
        enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
        auth_token=AUTH_TOKEN,
        execute_trades=EXECUTE_TRADES,
        telegram_config=TELEGRAM_CONFIG,
        no_new_trades_windows=NO_NEW_TRADES_WINDOWS,
        force_close_time=FORCE_CLOSE_TIME
    )
    logging.info("Manual job completed.")

if __name__ == "__main__":
    # Create the main tkinter root window
    root = tk.Tk()
    root.withdraw()  # Hide root initially
    
    # Show dashboard on startup
    show_dashboard(root)
    
    # Create and run tray icon in separate thread
    icon = create_tray_icon()
    
    # Start the scheduler by default
    start_scheduler(icon)
    
    # Run tray icon in a separate thread so it doesn't block tkinter
    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()
    
    # Run tkinter main loop
    root.mainloop()

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
from ctypes import windll

def get_window_by_partial_title(partial_title):
    """Find a window handle by partial, case-insensitive title match."""
    def callback(hwnd, results):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if partial_title.lower() in title.lower():
                results.append(hwnd)
    results = []
    win32gui.EnumWindows(callback, results)
    if results:
        return results[0]  # Return the first match
    return None

def capture_screenshot(window_title=None, top_offset=0, bottom_offset=0, save_folder=None, enable_save_screenshots=False):
    """Capture the full screen or a specific window (by partial title) using Win32 PrintWindow without activating, apply offsets by cropping, save to folder if enabled, and return as base64-encoded string."""
    logging.info("Capturing screenshot.")
    if window_title:
        hwnd = get_window_by_partial_title(window_title)
        if not hwnd:
            logging.error(f"No window found matching partial title '{window_title}'.")
            raise ValueError(f"No window found matching partial title '{window_title}'.")
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

        # Check if offsets would result in invalid height
        effective_height = height - top_offset - bottom_offset
        if effective_height <= 0:
            logging.error(f"Offsets result in invalid effective height: {effective_height} (original height: {height}, top_offset: {top_offset}, bottom_offset: {bottom_offset})")
            raise ValueError("Offsets result in invalid effective height.")

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
        if top_offset > 0 or bottom_offset > 0:
            screenshot = screenshot.crop((0, top_offset, width, height - bottom_offset))
            logging.info(f"Applied offsets: top={top_offset}, bottom={bottom_offset}")
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
    logging.info(f"Uploading screenshot with prompt: {prompt}")
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
        ],
        "max_tokens": 300  # Adjust as needed
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

def job(window_title, top_offset, bottom_offset, save_folder, begin_time, end_time, symbol, position_type, no_position_prompt, long_position_prompt, short_position_prompt, model, topstep_config, enable_llm, enable_trading, openai_api_url, openai_api_key, enable_save_screenshots, auth_token=None, execute_trades=False):
    """The main job to run periodically."""
    if not is_within_time_range(begin_time, end_time):
        logging.info(f"Current time {datetime.datetime.now().time()} is outside the range {begin_time}-{end_time}. Skipping.")
        return

    logging.info(f"Starting job at {time.ctime()}")
    
    # Check if there are active positions - if yes, skip screenshot and LLM analysis
    if check_active_trades(topstep_config, enable_trading, auth_token):
        logging.info("Active position detected - Skipping screenshot and LLM analysis until position is closed")
        return
    
    try:
        current_position_type = get_current_position(symbol, topstep_config, enable_trading, auth_token)
        logging.info(f"Determined current position_type: {current_position_type}")

        image_base64 = capture_screenshot(window_title, top_offset, bottom_offset, save_folder, enable_save_screenshots)
        # Select and format prompt based on current_position_type
        if current_position_type == 'none':
            prompt = no_position_prompt.format(symbol=DISPLAY_SYMBOL)
        elif current_position_type == 'long':
            prompt = long_position_prompt.format(symbol=DISPLAY_SYMBOL)
        elif current_position_type == 'short':
            prompt = short_position_prompt.format(symbol=DISPLAY_SYMBOL)
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
                price_target = advice.get('price_target')
                stop_loss = advice.get('stop_loss')
                reasoning = advice.get('reasoning')
                logging.info(f"Parsed Advice: Action={action}, Target={price_target}, Stop={stop_loss}, Reasoning={reasoning}")

                # Execute trade based on action
                if action in ['buy', 'sell', 'scale', 'close', 'flatten']:
                    logging.info(f"Executing trade: {action}")
                    execute_topstep_trade(action, price_target, stop_loss, topstep_config, enable_trading, current_position_type, auth_token, execute_trades)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing LLM response as JSON: {e}")
    except ValueError as e:
        logging.error(f"Error: {e}")

def get_current_position(symbol, topstep_config, enable_trading, auth_token=None):
    """Query Topstep API for current position of the symbol and determine type (or mock if disabled)."""
    if not enable_trading:
        logging.info("Trading disabled - Mock positions query: Returning 'none'")
        return 'none'

    if not auth_token:
        logging.error("No auth token available for positions query")
        return 'none'

    base_url = topstep_config['base_url']
    positions_endpoint = topstep_config.get('positions_endpoint', '/positions')
    account_id = topstep_config.get('account_id', '')
    
    if not account_id:
        logging.error("No account_id configured for positions query")
        return 'none'

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
        positions = response.json()  # Assume returns list of {'symbol': str, 'quantity': int}
        logging.info(f"Positions Response: {json.dumps(positions, indent=2)}")
        
        for pos in positions:
            if pos['symbol'] == symbol:
                quantity = pos['quantity']
                if quantity > 0:
                    return 'long'
                elif quantity < 0:
                    return 'short'
                else:
                    return 'none'
        return 'none'  # No position found
    except requests.exceptions.Timeout:
        logging.error("Positions query timed out")
        return 'none'
    except requests.exceptions.RequestException as e:
        logging.error(f"Error querying positions: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
        return 'none'  # Default to none on error
    except Exception as e:
        logging.error(f"Unexpected error querying positions: {e}")
        return 'none'

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
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "accountId": int(account_id)
    }

    try:
        # Check for active positions
        positions_endpoint = topstep_config.get('positions_endpoint', '/positions')
        positions_url = base_url + positions_endpoint
        
        response = requests.post(positions_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        positions = response.json()
        
        # If positions is a list and has any items with non-zero quantity, we have active trades
        if isinstance(positions, list) and len(positions) > 0:
            for pos in positions:
                quantity = pos.get('quantity', 0)
                if quantity != 0:
                    symbol = pos.get('symbol', 'Unknown')
                    logging.info(f"Active position found: {symbol} with quantity {quantity}")
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

def execute_topstep_trade(action, price_target, stop_loss, topstep_config, enable_trading, position_type='none', auth_token=None, execute_trades=False):
    """Execute trade via Topstep API based on action with stop loss and take profit (or mock/log details if disabled)."""
    logging.info(f"Preparing to execute trade: {action} with target {price_target} and stop {stop_loss}")
    
    # Get configuration values
    account_id = topstep_config.get('account_id', '')
    if not account_id:
        logging.error("No account_id configured - cannot place order")
        return
    
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
        return
    
    # Get order size
    size = int(topstep_config['quantity']) if action != 'scale' else int(topstep_config['quantity']) // 2
    
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
            return
    elif action == 'scale':
        # Scale position: if long, sell; if short, buy
        if position_type == 'long':
            side = 1  # Ask (sell to scale out long)
        elif position_type == 'short':
            side = 0  # Bid (buy to scale out short)
        else:
            logging.error("Scale action requires long or short position_type")
            return
    elif action == 'flatten':
        logging.error("Flatten action not implemented - use close instead")
        return
    else:
        logging.error(f"Unknown action: {action}")
        return
    
    # Build the correct TopstepX API payload
    # type: 2 = Market order
    payload = {
        "accountId": int(account_id),
        "contractId": contract_id,
        "type": 2,  # Market order
        "side": side,  # 0 = bid (buy), 1 = ask (sell)
        "size": size
    }
    
    # Add stop loss and take profit brackets if enabled and provided
    # Only add these for entry orders (buy/sell), not for close/scale actions
    enable_sl = topstep_config.get('enable_stop_loss', True)
    enable_tp = topstep_config.get('enable_take_profit', True)
    
    if action in ['buy', 'sell']:
        # Calculate or use provided stop loss and take profit
        max_risk = topstep_config.get('max_risk_per_contract', '')
        max_profit = topstep_config.get('max_profit_per_contract', '')
        tick_size = topstep_config.get('tick_size', 0.25)
        
        # Build stopLossBracket object
        if enable_sl and (stop_loss or (max_risk and max_risk.strip())):
            stop_loss_bracket = {
                "type": 4  # 4 = Stop order
            }
            
            if max_risk and max_risk.strip():
                # Use configured max risk in points
                max_risk_points = float(max_risk)
                # Calculate ticks from points
                stop_loss_ticks = int(max_risk_points / tick_size)
                
                # For long positions (side=0/buy), stop loss ticks should be negative (below entry)
                if side == 0:
                    stop_loss_ticks = -stop_loss_ticks
                
                stop_loss_bracket['ticks'] = stop_loss_ticks
                logging.info(f"Stop Loss Bracket set to: {stop_loss_ticks} ticks ({max_risk_points} points)")
            elif stop_loss:
                # Use LLM suggestion - calculate from price if we have an entry price
                # For market orders, we might not know exact entry, so use the stop_loss as price
                stop_loss_bracket['price'] = float(stop_loss)
                logging.info(f"Stop Loss Bracket set to price: {stop_loss} (from LLM)")
            
            if stop_loss_bracket:
                payload['stopLossBracket'] = stop_loss_bracket
        
        # Build takeProfitBracket object
        if enable_tp and (price_target or (max_profit and max_profit.strip())):
            take_profit_bracket = {
                "type": 1  # 1 = Limit order
            }
            
            if max_profit and max_profit.strip():
                # Use configured max profit in points
                max_profit_points = float(max_profit)
                # Calculate ticks from points
                take_profit_ticks = int(max_profit_points / tick_size)
                
                # For short positions (side=1/sell), take profit ticks should be negative
                if side == 1:
                    take_profit_ticks = -take_profit_ticks
                
                take_profit_bracket['ticks'] = take_profit_ticks
                logging.info(f"Take Profit Bracket set to: {take_profit_ticks} ticks ({max_profit_points} points)")
            elif price_target:
                # Use LLM suggestion - use the target price
                take_profit_bracket['price'] = float(price_target)
                logging.info(f"Take Profit Bracket set to price: {price_target} (from LLM)")
            
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
        logging.info(f"Trade executed successfully: {action}")
        
        # Log stop loss and take profit bracket details if present
        if 'stopLossBracket' in payload:
            sl_bracket = payload['stopLossBracket']
            if 'ticks' in sl_bracket:
                logging.info(f"Stop Loss bracket placed: {sl_bracket['ticks']} ticks")
            elif 'price' in sl_bracket:
                logging.info(f"Stop Loss bracket placed at price: {sl_bracket['price']}")
        if 'takeProfitBracket' in payload:
            tp_bracket = payload['takeProfitBracket']
            if 'ticks' in tp_bracket:
                logging.info(f"Take Profit bracket placed: {tp_bracket['ticks']} ticks")
            elif 'price' in tp_bracket:
                logging.info(f"Take Profit bracket placed at price: {tp_bracket['price']}")
            
    except requests.exceptions.Timeout:
        logging.error("Trade request timed out")
    except requests.exceptions.RequestException as e:
        logging.error(f"Trade request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Error response: {e.response.text}")
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

# Load configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

# Logging setup
LOG_FOLDER = config.get('General', 'log_folder', fallback='logs')
os.makedirs(LOG_FOLDER, exist_ok=True)
today = datetime.datetime.now().strftime("%Y%m%d")
log_file = os.path.join(LOG_FOLDER, f"{today}.txt")

file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])

logging.info("Application started.")

INTERVAL_MINUTES = int(config.get('General', 'interval_minutes', fallback='5'))
TRADE_STATUS_CHECK_INTERVAL = int(config.get('General', 'trade_status_check_interval', fallback='10'))
BEGIN_TIME = config.get('General', 'begin_time', fallback='00:00')
END_TIME = config.get('General', 'end_time', fallback='23:59')
WINDOW_TITLE = config.get('General', 'window_title', fallback=None)
TOP_OFFSET = int(config.get('General', 'top_offset', fallback='0'))
BOTTOM_OFFSET = int(config.get('General', 'bottom_offset', fallback='0'))
SAVE_FOLDER = config.get('General', 'save_folder', fallback=None)
ENABLE_LLM = config.getboolean('General', 'enable_llm', fallback=True)
ENABLE_TRADING = config.getboolean('General', 'enable_trading', fallback=False)
EXECUTE_TRADES = config.getboolean('General', 'execute_trades', fallback=False)
ENABLE_SAVE_SCREENSHOTS = config.getboolean('General', 'enable_save_screenshots', fallback=False)

logging.info(f"Loaded config: INTERVAL_MINUTES={INTERVAL_MINUTES}, TRADE_STATUS_CHECK_INTERVAL={TRADE_STATUS_CHECK_INTERVAL}s, BEGIN_TIME={BEGIN_TIME}, END_TIME={END_TIME}, WINDOW_TITLE={WINDOW_TITLE}, TOP_OFFSET={TOP_OFFSET}, BOTTOM_OFFSET={BOTTOM_OFFSET}, SAVE_FOLDER={SAVE_FOLDER}, ENABLE_LLM={ENABLE_LLM}, ENABLE_TRADING={ENABLE_TRADING}, EXECUTE_TRADES={EXECUTE_TRADES}, ENABLE_SAVE_SCREENSHOTS={ENABLE_SAVE_SCREENSHOTS}")

SYMBOL = config.get('LLM', 'symbol', fallback='ES')
DISPLAY_SYMBOL = config.get('LLM', 'display_symbol', fallback='ES')  # Symbol for LLM communications and human readable formats
POSITION_TYPE = config.get('LLM', 'position_type', fallback='none')
NO_POSITION_PROMPT = config.get('LLM', 'no_position_prompt', fallback='Analyze this Bookmap screenshot for {symbol} futures and advise: buy, hold, or sell. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "buy/hold/sell", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
LONG_POSITION_PROMPT = config.get('LLM', 'long_position_prompt', fallback='Analyze this Bookmap screenshot for a long position in {symbol} futures and advise: hold, scale, or close. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "hold/scale/close", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
SHORT_POSITION_PROMPT = config.get('LLM', 'short_position_prompt', fallback='Analyze this Bookmap screenshot for a short position in {symbol} futures and advise: hold, scale, or close. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "hold/scale/close", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
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
    'working_orders_endpoint': config.get('Topstep', 'working_orders_endpoint', fallback='/api/Order/searchWorking'),
    'accounts_endpoint': config.get('Topstep', 'accounts_endpoint', fallback='/api/Account/search'),
    'contracts_endpoint': config.get('Topstep', 'contracts_endpoint', fallback='/api/Contract/search'),
    'contracts_available_endpoint': config.get('Topstep', 'contracts_available_endpoint', fallback='/api/Contract/available'),
    'account_id': config.get('Topstep', 'account_id', fallback=''),
    'contract_id': config.get('Topstep', 'contract_id', fallback=''),
    'quantity': config.get('Topstep', 'quantity', fallback='1'),
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

# Global auth token for Topstep API
AUTH_TOKEN = None

# Login to TopstepX and get auth token
if ENABLE_TRADING:
    logging.info("Trading enabled - Attempting to login to TopstepX API")
    AUTH_TOKEN = login_topstep(TOPSTEP_CONFIG)
    if AUTH_TOKEN:
        logging.info("Login successful - Auth token obtained")
        TOPSTEP_CONFIG['auth_token'] = AUTH_TOKEN  # Store in config for convenience

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

# Log exact Topstep URLs and example POST requests for debug
logging.info("Topstep Debug URLs (all POST requests):")
logging.info(f"Login URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['login_endpoint']}")
logging.info(f"Accounts URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['accounts_endpoint']}")
logging.info(f"Contract Search URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['contracts_endpoint']}")
logging.info(f"Order Place URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['buy_endpoint']}")
logging.info(f"Positions URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['positions_endpoint']}")
logging.info(f"Working Orders URL: {TOPSTEP_CONFIG['base_url'] + TOPSTEP_CONFIG['working_orders_endpoint']}")

# Example payloads for different endpoints
logging.info("Example POST Payloads:")
if TOPSTEP_CONFIG['account_id']:
    account_payload = {"accountId": int(TOPSTEP_CONFIG['account_id'])}
    logging.info(f"  Positions/Orders payload: {json.dumps(account_payload)}")
    
    order_payload = {
        "accountId": int(TOPSTEP_CONFIG['account_id']),
        "contractId": TOPSTEP_CONFIG.get('contract_id', 'CON.F.US.EP.Z25'),
        "type": 2,
        "side": 0,
        "size": int(TOPSTEP_CONFIG['quantity']),
        "stopLossBracket": {"type": 4, "ticks": -16},
        "takeProfitBracket": {"type": 1, "ticks": 64}
    }
    logging.info(f"  Order payload example: {json.dumps(order_payload, indent=2)}")
logging.info(f"Headers Template: {{'Authorization': 'Bearer [auth_token]', 'Content-Type': 'application/json'}}")

# Schedule the job every INTERVAL_MINUTES minutes
schedule.every(INTERVAL_MINUTES).minutes.do(
    job, 
    window_title=WINDOW_TITLE, 
    top_offset=TOP_OFFSET, 
    bottom_offset=BOTTOM_OFFSET, 
    save_folder=SAVE_FOLDER, 
    begin_time=BEGIN_TIME, 
    end_time=END_TIME,
    symbol=SYMBOL,
    position_type=POSITION_TYPE,
    no_position_prompt=NO_POSITION_PROMPT,
    long_position_prompt=LONG_POSITION_PROMPT,
    short_position_prompt=SHORT_POSITION_PROMPT,
    model=MODEL,
    topstep_config=TOPSTEP_CONFIG,
    enable_llm=ENABLE_LLM,
    enable_trading=ENABLE_TRADING,
    openai_api_url=OPENAI_API_URL,
    openai_api_key=OPENAI_API_KEY,
    enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
    auth_token=AUTH_TOKEN,
    execute_trades=EXECUTE_TRADES
)

# Run the first job immediately on startup (before entering the scheduler loop)
logging.info("Running initial screenshot job immediately on startup...")
job(
    window_title=WINDOW_TITLE, 
    top_offset=TOP_OFFSET, 
    bottom_offset=BOTTOM_OFFSET, 
    save_folder=SAVE_FOLDER, 
    begin_time=BEGIN_TIME, 
    end_time=END_TIME,
    symbol=SYMBOL,
    position_type=POSITION_TYPE,
    no_position_prompt=NO_POSITION_PROMPT,
    long_position_prompt=LONG_POSITION_PROMPT,
    short_position_prompt=SHORT_POSITION_PROMPT,
    model=MODEL,
    topstep_config=TOPSTEP_CONFIG,
    enable_llm=ENABLE_LLM,
    enable_trading=ENABLE_TRADING,
    openai_api_url=OPENAI_API_URL,
    openai_api_key=OPENAI_API_KEY,
    enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
    auth_token=AUTH_TOKEN,
    execute_trades=EXECUTE_TRADES
)

# Global flag to control the scheduler
running = False
scheduler_thread = None
trade_monitor_thread = None

def run_scheduler():
    global running
    while running:
        schedule.run_pending()
        time.sleep(1)

def run_trade_monitor():
    """Background thread to continuously monitor trade status."""
    global running
    last_active_state = None
    
    while running:
        try:
            is_active = check_active_trades(TOPSTEP_CONFIG, ENABLE_TRADING, AUTH_TOKEN)
            
            # Log state changes
            if is_active != last_active_state:
                if is_active:
                    logging.info("⚠️ Trade monitoring: Active position detected - LLM analysis paused")
                else:
                    logging.info("✅ Trade monitoring: No active positions - LLM analysis will resume on next cycle")
                last_active_state = is_active
            
            time.sleep(TRADE_STATUS_CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Error in trade monitor thread: {e}")
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

# Create tray icon
def create_tray_icon():
    # Use simple icons (green for running, red for stopped)
    green_image = Image.new('RGB', (64, 64), color=(0, 255, 0))
    red_image = Image.new('RGB', (64, 64), color=(255, 0, 0))
    menu = (
        item('Start', start_scheduler),
        item('Stop', stop_scheduler),
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

def manual_job():
    logging.info("Manual screenshot triggered.")
    job(
        window_title=WINDOW_TITLE, 
        top_offset=TOP_OFFSET, 
        bottom_offset=BOTTOM_OFFSET, 
        save_folder=SAVE_FOLDER, 
        begin_time=BEGIN_TIME, 
        end_time=END_TIME,
        symbol=SYMBOL,
        position_type=POSITION_TYPE,
        no_position_prompt=NO_POSITION_PROMPT,
        long_position_prompt=LONG_POSITION_PROMPT,
        short_position_prompt=SHORT_POSITION_PROMPT,
        model=MODEL,
        topstep_config=TOPSTEP_CONFIG,
        enable_llm=ENABLE_LLM,
        enable_trading=ENABLE_TRADING,
        openai_api_url=OPENAI_API_URL,
        openai_api_key=OPENAI_API_KEY,
        enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS,
        auth_token=AUTH_TOKEN,
        execute_trades=EXECUTE_TRADES
    )
    logging.info("Manual job completed.")

if __name__ == "__main__":
    icon = create_tray_icon()
    # Start the scheduler by default (optional)
    start_scheduler(icon)
    icon.run()

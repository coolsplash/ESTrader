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
    """Capture the full screen or a specific window (by partial title) without activating it, apply offsets by cropping, save to folder if enabled, and return as base64-encoded string."""
    logging.info("Capturing screenshot.")
    if window_title:
        hwnd = get_window_by_partial_title(window_title)
        if not hwnd:
            logging.error(f"No window found matching partial title '{window_title}'.")
            raise ValueError(f"No window found matching partial title '{window_title}'.")
        logging.info(f"Window found: HWND={hwnd}, Title={win32gui.GetWindowText(hwnd)}")

        # Get window dimensions
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bottom - top

        # Check if offsets would result in invalid height
        effective_height = height - top_offset - bottom_offset
        if effective_height <= 0:
            logging.error(f"Offsets result in invalid effective height: {effective_height} (original height: {height}, top_offset: {top_offset}, bottom_offset: {bottom_offset})")
            raise ValueError("Offsets result in invalid effective height.")

        # Create device context
        hdc = win32gui.GetWindowDC(hwnd)
        dc_obj = win32ui.CreateDCFromHandle(hdc)
        mem_dc = dc_obj.CreateCompatibleDC()

        # Create bitmap for full client area
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(dc_obj, width, height)
        mem_dc.SelectObject(bmp)

        # Print window into bitmap (captures even if not foreground)
        result = windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)  # 3 = PW_RENDERFULLCONTENT (Windows 10+)
        if result != 1:
            logging.warning("PrintWindow failed; falling back to simple copy.")
            mem_dc.BitBlt((0, 0), (width, height), dc_obj, (left, top), win32con.SRCCOPY)

        # Convert to PIL Image
        bmp_info = bmp.GetInfo()
        bmp_str = bmp.GetBitmapBits(True)
        screenshot = Image.frombuffer('RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']), bmp_str, 'raw', 'BGRX', 0, 1)

        # Clean up
        win32gui.DeleteObject(bmp.GetHandle())
        mem_dc.DeleteDC()
        dc_obj.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)

        # Apply crop for offsets
        screenshot = screenshot.crop((0, top_offset, width, height - bottom_offset))
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

def job(window_title, top_offset, bottom_offset, save_folder, begin_time, end_time, symbol, position_type, no_position_prompt, long_position_prompt, short_position_prompt, model, topstep_config, enable_llm, enable_trading, openai_api_url, openai_api_key, enable_save_screenshots):
    """The main job to run periodically."""
    if not is_within_time_range(begin_time, end_time):
        logging.info(f"Current time {datetime.datetime.now().time()} is outside the range {begin_time}-{end_time}. Skipping.")
        return

    logging.info(f"Starting job at {time.ctime()}")
    try:
        image_base64 = capture_screenshot(window_title, top_offset, bottom_offset, save_folder, enable_save_screenshots)
        # Select and format prompt based on position_type
        if position_type == 'none':
            prompt = no_position_prompt.format(symbol=symbol)
        elif position_type == 'long':
            prompt = long_position_prompt.format(symbol=symbol)
        elif position_type == 'short':
            prompt = short_position_prompt.format(symbol=symbol)
        else:
            logging.error(f"Invalid position_type: {position_type}")
            raise ValueError(f"Invalid position_type: {position_type}")

        llm_response = upload_to_llm(image_base64, prompt, model, enable_llm, openai_api_url, openai_api_key)
        if llm_response:
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
                    execute_topstep_trade(action, price_target, stop_loss, topstep_config, enable_trading)
            except json.JSONDecodeError:
                logging.error("Error parsing LLM response as JSON.")
    except ValueError as e:
        logging.error(f"Error: {e}")

def execute_topstep_trade(action, price_target, stop_loss, topstep_config, enable_trading):
    """Execute trade via Topstep API based on action (or mock if disabled)."""
    logging.info(f"Preparing to execute trade: {action} with target {price_target} and stop {stop_loss}")
    if not enable_trading:
        logging.info(f"Trading disabled - Mock execution: {action}")
        return

    base_url = topstep_config['base_url']
    api_key = topstep_config['api_key']
    api_secret = topstep_config['api_secret']
    quantity = int(topstep_config['quantity'])
    symbol = config['LLM']['symbol']  # From LLM config

    headers = {
        "Authorization": f"Bearer {api_key}",  # Assuming Bearer token; adjust if needed
        "Content-Type": "application/json"
    }

    # Example payload; adjust based on actual Topstep API docs
    payload = {
        "symbol": symbol,
        "quantity": quantity,
        "price_target": price_target,
        "stop_loss": stop_loss
    }

    if action == 'buy':
        url = base_url + topstep_config['buy_endpoint']
    elif action == 'sell' or action == 'close' or action == 'flatten':
        url = base_url + topstep_config['sell_endpoint'] if action in ['sell', 'close'] else base_url + topstep_config['flatten_endpoint']
        if action == 'scale':
            payload['quantity'] = quantity // 2  # Example: scale by halving; customize
    else:
        logging.error(f"Unknown action: {action}")
        return

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logging.info(f"Trade executed: {action} - Response: {response.json()}")
    except Exception as e:
        logging.error(f"Error executing trade: {e}")

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
BEGIN_TIME = config.get('General', 'begin_time', fallback='00:00')
END_TIME = config.get('General', 'end_time', fallback='23:59')
WINDOW_TITLE = config.get('General', 'window_title', fallback=None)
TOP_OFFSET = int(config.get('General', 'top_offset', fallback='0'))
BOTTOM_OFFSET = int(config.get('General', 'bottom_offset', fallback='0'))
SAVE_FOLDER = config.get('General', 'save_folder', fallback=None)
ENABLE_LLM = config.getboolean('General', 'enable_llm', fallback=True)
ENABLE_TRADING = config.getboolean('General', 'enable_trading', fallback=False)
ENABLE_SAVE_SCREENSHOTS = config.getboolean('General', 'enable_save_screenshots', fallback=False)

logging.info(f"Loaded config: INTERVAL_MINUTES={INTERVAL_MINUTES}, BEGIN_TIME={BEGIN_TIME}, END_TIME={END_TIME}, WINDOW_TITLE={WINDOW_TITLE}, TOP_OFFSET={TOP_OFFSET}, BOTTOM_OFFSET={BOTTOM_OFFSET}, SAVE_FOLDER={SAVE_FOLDER}, ENABLE_LLM={ENABLE_LLM}, ENABLE_TRADING={ENABLE_TRADING}, ENABLE_SAVE_SCREENSHOTS={ENABLE_SAVE_SCREENSHOTS}")

SYMBOL = config.get('LLM', 'symbol', fallback='ES')
POSITION_TYPE = config.get('LLM', 'position_type', fallback='none')
NO_POSITION_PROMPT = config.get('LLM', 'no_position_prompt', fallback='Analyze this Bookmap screenshot for {symbol} futures and advise: buy, hold, or sell. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "buy/hold/sell", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
LONG_POSITION_PROMPT = config.get('LLM', 'long_position_prompt', fallback='Analyze this Bookmap screenshot for a long position in {symbol} futures and advise: hold, scale, or close. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "hold/scale/close", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
SHORT_POSITION_PROMPT = config.get('LLM', 'short_position_prompt', fallback='Analyze this Bookmap screenshot for a short position in {symbol} futures and advise: hold, scale, or close. Provide a price target and stop loss. Explain your reasoning based on order book, heat map, and volume. Respond in JSON: {{"action": "hold/scale/close", "price_target": number, "stop_loss": number, "reasoning": "text"}}')
MODEL = config.get('LLM', 'model', fallback='gpt-4o')

logging.info(f"Loaded LLM config: SYMBOL={SYMBOL}, POSITION_TYPE={POSITION_TYPE}, MODEL={MODEL}")

TOPSTEP_CONFIG = {
    'api_key': config.get('Topstep', 'api_key', fallback='your-topstep-api-key'),
    'api_secret': config.get('Topstep', 'api_secret', fallback='your-topstep-api-secret'),
    'base_url': config.get('Topstep', 'base_url', fallback='https://api.topstep.com/v1'),
    'buy_endpoint': config.get('Topstep', 'buy_endpoint', fallback='/orders'),
    'sell_endpoint': config.get('Topstep', 'sell_endpoint', fallback='/orders'),
    'flatten_endpoint': config.get('Topstep', 'flatten_endpoint', fallback='/positions/flatten'),
    'quantity': config.get('Topstep', 'quantity', fallback='1')
}

logging.info(f"Loaded Topstep config: BASE_URL={TOPSTEP_CONFIG['base_url']}, QUANTITY={TOPSTEP_CONFIG['quantity']}")

OPENAI_API_KEY = config.get('OpenAI', 'api_key', fallback='your-openai-api-key-here')
OPENAI_API_URL = config.get('OpenAI', 'api_url', fallback='https://api.openai.com/v1/chat/completions')

logging.info(f"Loaded OpenAI config: API_URL={OPENAI_API_URL}")

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
    enable_save_screenshots=ENABLE_SAVE_SCREENSHOTS
)

# Global flag to control the scheduler
running = False
scheduler_thread = None

def run_scheduler():
    global running
    while running:
        schedule.run_pending()
        time.sleep(1)

def start_scheduler(icon):
    global running, scheduler_thread
    if not running:
        running = True
        scheduler_thread = threading.Thread(target=run_scheduler)
        scheduler_thread.start()
        icon.notify("Scheduler started.")
        logging.info("Scheduler started.")

def stop_scheduler(icon):
    global running
    if running:
        running = False
        if scheduler_thread:
            scheduler_thread.join()
        icon.notify("Scheduler stopped.")
        logging.info("Scheduler stopped.")

def quit_app(icon):
    stop_scheduler(icon)
    icon.stop()
    logging.info("Application quit.")

# Create tray icon
def create_tray_icon():
    # Use a simple icon (you can replace with a real ICO file)
    image = Image.new('RGB', (64, 64), color=(0, 255, 0))
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
        item('Exit', quit_app)
    )
    icon = pystray.Icon("screenshot_uploader", image, "Screenshot Uploader", menu)
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

if __name__ == "__main__":
    icon = create_tray_icon()
    # Start the scheduler by default (optional)
    start_scheduler(icon)
    icon.run()

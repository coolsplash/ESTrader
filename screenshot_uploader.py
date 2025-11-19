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

# Configuration
INTERVAL_MINUTES = 5  # Adjust this
OPENAI_API_KEY = "your-openai-api-key-here"  # Replace with your actual key
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"  # For GPT-4 with vision

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

def capture_screenshot(window_title=None, top_offset=0, bottom_offset=0, save_folder=None):
    """Capture the full screen or a specific window (by partial title), apply offsets, save to folder, and return as base64-encoded string."""
    if window_title:
        hwnd = get_window_by_partial_title(window_title)
        if not hwnd:
            raise ValueError(f"No window found matching partial title '{window_title}'.")
        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        # Apply offsets
        top += top_offset
        bottom -= bottom_offset
        if top >= bottom:
            raise ValueError("Offsets result in invalid bounding box.")
        bbox = (left, top, right, bottom)
    else:
        bbox = None  # Full screen (offsets not applied for full screen)

    screenshot = ImageGrab.grab(bbox=bbox)
    buffered = BytesIO()
    screenshot.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    # Save to file if folder specified
    if save_folder:
        os.makedirs(save_folder, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(save_folder, f"screenshot_{timestamp}.png")
        screenshot.save(file_path)
        print(f"Screenshot saved to {file_path}")

    return image_base64

def upload_to_llm(image_base64, prompt, model):
    """Upload the screenshot to OpenAI API with custom prompt and model, and get a response."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
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
        response = requests.post(OPENAI_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        print("LLM Response:", content)
        return content  # Return the response for parsing
    except Exception as e:
        print(f"Error uploading to LLM: {e}")
        return None

def is_within_time_range(begin_time, end_time):
    """Check if current time is within the specified range."""
    now = datetime.datetime.now().time()
    begin = datetime.datetime.strptime(begin_time, "%H:%M").time()
    end = datetime.datetime.strptime(end_time, "%H:%M").time()
    return begin <= now <= end

def job(window_title, top_offset, bottom_offset, save_folder, begin_time, end_time, symbol, position_type, no_position_prompt, long_position_prompt, short_position_prompt, model, topstep_config):
    """The main job to run periodically."""
    if not is_within_time_range(begin_time, end_time):
        print(f"Current time {datetime.datetime.now().time()} is outside the range {begin_time}-{end_time}. Skipping.")
        return

    print(f"Capturing screenshot at {time.ctime()}")
    try:
        image_base64 = capture_screenshot(window_title, top_offset, bottom_offset, save_folder)
        # Select and format prompt based on position_type
        if position_type == 'none':
            prompt = no_position_prompt.format(symbol=symbol)
        elif position_type == 'long':
            prompt = long_position_prompt.format(symbol=symbol)
        elif position_type == 'short':
            prompt = short_position_prompt.format(symbol=symbol)
        else:
            raise ValueError(f"Invalid position_type: {position_type}")

        llm_response = upload_to_llm(image_base64, prompt, model)
        if llm_response:
            # Parse JSON response
            try:
                advice = json.loads(llm_response)
                action = advice.get('action')
                price_target = advice.get('price_target')
                stop_loss = advice.get('stop_loss')
                reasoning = advice.get('reasoning')
                print(f"Parsed Advice: Action={action}, Target={price_target}, Stop={stop_loss}, Reasoning={reasoning}")

                # Execute trade based on action
                if action in ['buy', 'sell', 'scale', 'close', 'flatten']:  # Assuming 'flatten' might be used
                    execute_topstep_trade(action, price_target, stop_loss, topstep_config)
            except json.JSONDecodeError:
                print("Error parsing LLM response as JSON.")
    except ValueError as e:
        print(f"Error: {e}")

def execute_topstep_trade(action, price_target, stop_loss, topstep_config):
    """Execute trade via Topstep API based on action."""
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
        print(f"Unknown action: {action}")
        return

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Trade executed: {action} - Response: {response.json()}")
    except Exception as e:
        print(f"Error executing trade: {e}")

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
    topstep_config=TOPSTEP_CONFIG
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

def stop_scheduler(icon):
    global running
    if running:
        running = False
        if scheduler_thread:
            scheduler_thread.join()
        icon.notify("Scheduler stopped.")

def quit_app(icon):
    stop_scheduler(icon)
    icon.stop()

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
    print(f"Position set to: {new_position}")

# Load configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

INTERVAL_MINUTES = int(config['General']['interval_minutes'])
BEGIN_TIME = config['General']['begin_time']
END_TIME = config['General']['end_time']
WINDOW_TITLE = config['General']['window_title'] if config['General']['window_title'] else None
TOP_OFFSET = int(config['General']['top_offset'])
BOTTOM_OFFSET = int(config['General']['bottom_offset'])
SAVE_FOLDER = config['General']['save_folder'] if config['General']['save_folder'] else None

SYMBOL = config['LLM']['symbol']
POSITION_TYPE = config['LLM']['position_type']
NO_POSITION_PROMPT = config['LLM']['no_position_prompt']
LONG_POSITION_PROMPT = config['LLM']['long_position_prompt']
SHORT_POSITION_PROMPT = config['LLM']['short_position_prompt']
MODEL = config['LLM']['model']

TOPSTEP_CONFIG = {
    'api_key': config['Topstep']['api_key'],
    'api_secret': config['Topstep']['api_secret'],
    'base_url': config['Topstep']['base_url'],
    'buy_endpoint': config['Topstep']['buy_endpoint'],
    'sell_endpoint': config['Topstep']['sell_endpoint'],
    'flatten_endpoint': config['Topstep']['flatten_endpoint'],
    'quantity': config['Topstep']['quantity']
}

OPENAI_API_KEY = "your-openai-api-key-here"  # Replace with your actual key
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"  # For GPT-4 with vision

if __name__ == "__main__":
    icon = create_tray_icon()
    # Start the scheduler by default (optional)
    start_scheduler(icon)
    icon.run()

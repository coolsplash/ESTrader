"""Test script to debug the bar data issue with TopstepX API"""
import requests
import datetime
import json

# Config
BASE_URL = "https://api.topstepx.com"
CONTRACT_ID = "CON.F.US.EP.Z25"
USERNAME = "moonwhat@gmail.com"
API_SECRET = "afHUXWLeGfSoGY+m19Cc38TS8ceE3wD+C5m9jWRbMjc="

def login():
    """Login and get auth token"""
    url = f"{BASE_URL}/api/Auth/loginKey"
    payload = {
        "userName": USERNAME,
        "apiKey": API_SECRET
    }
    headers = {"Content-Type": "application/json"}
    
    print(f"Logging in as {USERNAME}...")
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    result = response.json()
    
    if result.get('success'):
        print("Login successful!")
        return result.get('token')
    else:
        print(f"Login failed: {result.get('errorMessage')}")
        return None

def fetch_bars(auth_token, start_time, end_time, live=False, account_id=None):
    """Fetch bar data"""
    url = f"{BASE_URL}/api/History/retrieveBars"
    
    payload = {
        "contractId": CONTRACT_ID,
        "live": live,
        "startTime": start_time,
        "endTime": end_time,
        "unit": 2,  # Minutes
        "unitNumber": 5,  # 5 minutes
        "limit": 200,
        "includePartialBar": True
    }
    
    if account_id:
        payload["accountId"] = account_id
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    print(f"\n{'='*60}")
    print(f"Fetching bars: {start_time} to {end_time}")
    print(f"Live flag: {live}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    result = response.json()
    
    print(f"\nResponse status: {response.status_code}")
    print(f"Full response: {json.dumps(result, indent=2)}")
    print(f"Success: {result.get('success')}")
    print(f"Error code: {result.get('errorCode')}")
    print(f"Error message: {result.get('errorMessage')}")
    
    bars = result.get('bars', []) or []
    print(f"Bars returned: {len(bars)}")
    
    if bars:
        print(f"First bar: {bars[0]}")
        print(f"Last bar: {bars[-1]}")
    
    return bars

def main():
    auth_token = login()
    if not auth_token:
        return
    
    ACCOUNT_ID = 15182868  # From config
    
    current_utc = datetime.datetime.utcnow()
    print(f"\nCurrent UTC time: {current_utc}")
    print(f"Current Local time: {datetime.datetime.now()}")
    
    # Test 1: Last 30 minutes (should have ~6 bars)
    print("\n" + "="*60)
    print("TEST 1: Last 30 minutes (no account)")
    end_time = current_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_time = (current_utc - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Test 1b: Last 5 minutes (very small window)
    print("\n" + "="*60)
    print("TEST 1b: Last 5 minutes (very small window)")
    start_time = (current_utc - datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Test 1c: Last 10 minutes
    print("\n" + "="*60)
    print("TEST 1c: Last 10 minutes")
    start_time = (current_utc - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Test 1d: Today's data from market open (9:30 AM ET = 14:30 UTC)
    print("\n" + "="*60)
    print("TEST 1d: Today's data from 9:30 AM to 10:00 AM ET")
    today_open = current_utc.replace(hour=14, minute=30, second=0, microsecond=0)
    today_end = current_utc.replace(hour=15, minute=0, second=0, microsecond=0)
    start_time = today_open.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_time = today_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Reset end_time for remaining tests
    end_time = current_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    # Test 2: With account ID
    print("\n" + "="*60)
    print("TEST 2: Last 30 minutes WITH account ID")
    start_time = (current_utc - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False, account_id=ACCOUNT_ID)
    
    # Test 3: Yesterday's data - specific time range
    print("\n" + "="*60)
    print("TEST 3: Yesterday 9:30 AM to 10:00 AM ET (30 min window)")
    yesterday = current_utc - datetime.timedelta(days=1)
    # 9:30 AM ET = 14:30 UTC (EST)
    start_time = yesterday.replace(hour=14, minute=30, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_time = yesterday.replace(hour=15, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Test 4: 2 days ago (Dec 3rd was Tuesday, definitely a trading day)
    print("\n" + "="*60)
    print("TEST 4: 2 days ago 9:30 AM to 10:00 AM ET")
    two_days_ago = current_utc - datetime.timedelta(days=2)
    start_time = two_days_ago.replace(hour=14, minute=30, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_time = two_days_ago.replace(hour=15, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)
    
    # Test 5: Nov 27th (day that had good data in cache)
    print("\n" + "="*60)
    print("TEST 5: Nov 27th 9:00 AM to 9:30 AM ET (known good day)")
    # Nov 27 would be around 8 days ago
    nov27 = datetime.datetime(2025, 11, 27)
    # 9:00 AM ET = 14:00 UTC
    start_time = nov27.replace(hour=14, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_time = nov27.replace(hour=14, minute=30, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fetch_bars(auth_token, start_time, end_time, live=False)

if __name__ == "__main__":
    main()


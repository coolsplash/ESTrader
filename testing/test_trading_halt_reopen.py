"""
Test the Trading Halt with Reopen logic.

This tests that on Thanksgiving:
- Trading stops at 12:30 (13:00 - 30min buffer)
- Trading resumes at 18:00 (reopen time)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_holidays
import datetime

# Check the holiday data
holiday_file = "market_data/market_holidays.json"
data = market_holidays.load_holiday_data(holiday_file)

print("=" * 80)
print("TRADING HALT WITH REOPEN TEST")
print("=" * 80)
print()

if data and 'holidays' in data:
    thanksgiving = None
    for holiday in data['holidays']:
        if holiday['date'] == '2025-11-27':
            thanksgiving = holiday
            break
    
    if thanksgiving:
        print("Thanksgiving Data:")
        print(f"  Date: {thanksgiving['date']}")
        print(f"  Type: {thanksgiving['type']}")
        print(f"  Open Time: {thanksgiving['open_time']}")
        print(f"  Close Time: {thanksgiving['close_time']}")
        print(f"  Notes: {thanksgiving['notes']}")
        print()
        
        # Test different times
        test_times = [
            ("12:00", "Before halt"),
            ("12:30", "At halt time (12:30 = 13:00 - 30min buffer)"),
            ("13:00", "At close time (halt starts)"),
            ("15:00", "During halt period"),
            ("17:59", "Just before reopen"),
            ("18:00", "At reopen time"),
            ("18:01", "After reopen"),
            ("19:00", "After reopen"),
        ]
        
        print("Expected Behavior:")
        print("-" * 80)
        
        # Parse reopen time from notes
        import re
        reopen_time = None
        notes = thanksgiving.get('notes', '')
        if 'reopen' in notes.lower():
            match = re.search(r'(?:Reopen|Open)\s+@\s+(\d{1,2}):(\d{2})\s+(?:CT|ET)', notes, re.IGNORECASE)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                if 'CT' in match.group(0):
                    hour += 1  # CT to ET conversion
                reopen_time = datetime.time(hour, minute)
        
        close_time = market_holidays.get_close_time(datetime.date(2025, 11, 27), holiday_file)
        minutes_before = 30
        adjusted_close = datetime.time(close_time.hour, close_time.minute)
        adjusted_close_dt = datetime.datetime.combine(datetime.date(2025, 11, 27), adjusted_close)
        adjusted_close_dt = adjusted_close_dt - datetime.timedelta(minutes=minutes_before)
        adjusted_close = adjusted_close_dt.time()
        
        print(f"Close Time: {close_time}")
        print(f"Adjusted Close (with 30min buffer): {adjusted_close}")
        print(f"Reopen Time: {reopen_time}")
        print()
        
        for time_str, description in test_times:
            hour, minute = map(int, time_str.split(':'))
            test_time = datetime.time(hour, minute)
            
            # Simulate the logic
            should_trade = True
            reason = "Trading allowed"
            
            if reopen_time:
                if adjusted_close <= test_time < reopen_time:
                    should_trade = False
                    reason = "HALT period (between adjusted close and reopen)"
                elif test_time >= reopen_time:
                    should_trade = True
                    reason = "Market reopened"
                else:
                    should_trade = True
                    reason = "Before halt"
            else:
                if test_time >= adjusted_close:
                    should_trade = False
                    reason = "Past adjusted close"
            
            status = "[TRADE]" if should_trade else "[SKIP]"
            print(f"{time_str} ({description:40s}) -> {status} - {reason}")
        
    else:
        print("ERROR: Thanksgiving (2025-11-27) not found in holiday data")
else:
    print("ERROR: No holiday data loaded")

print()
print("=" * 80)


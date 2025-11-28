"""
Test script for market holidays integration.

This script tests the market_holidays module and verifies that:
1. Holiday checking works correctly
2. Early close detection works
3. Buffer time calculations are correct
"""

import sys
import os
import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_holidays

def test_holiday_detection():
    """Test that Thanksgiving is correctly detected as early close (not fully closed per EdgeClear)."""
    print("=" * 80)
    print("TEST 1: Early Close Detection (Thanksgiving)")
    print("=" * 80)
    
    # Thanksgiving 2025 - EdgeClear shows Trading Halt @ 12:00 CT (13:00 ET) = early close
    thanksgiving = datetime.datetime(2025, 11, 27, 10, 0)
    holiday_file = "market_data/market_holidays.json"
    
    is_early = market_holidays.is_early_close_day(thanksgiving.date(), holiday_file)
    close_time = market_holidays.get_close_time(thanksgiving.date(), holiday_file)
    
    print(f"Date: {thanksgiving.strftime('%Y-%m-%d %H:%M')}")
    print(f"Is Early Close: {is_early}")
    print(f"Close Time: {close_time}")
    print(f"Expected: True, 13:00:00")
    print(f"Status: {'PASS' if is_early and close_time == datetime.time(13, 0) else 'FAIL'}")
    print()
    
    return is_early and close_time == datetime.time(13, 0)


def test_early_close_detection():
    """Test that Black Friday is correctly detected as early close at 13:15 ET."""
    print("=" * 80)
    print("TEST 2: Early Close Detection (Black Friday)")
    print("=" * 80)
    
    # Black Friday 2025 - EdgeClear shows Close @ 12:15 CT (13:15 ET)
    black_friday = datetime.date(2025, 11, 28)
    holiday_file = "market_data/market_holidays.json"
    
    is_early = market_holidays.is_early_close_day(black_friday, holiday_file)
    close_time = market_holidays.get_close_time(black_friday, holiday_file)
    
    print(f"Date: {black_friday.isoformat()}")
    print(f"Is Early Close: {is_early}")
    print(f"Close Time: {close_time}")
    print(f"Expected: True, 13:15:00")
    print(f"Status: {'PASS' if is_early and close_time == datetime.time(13, 15) else 'FAIL'}")
    print()
    
    return is_early and close_time == datetime.time(13, 15)


def test_normal_day():
    """Test that a normal day is correctly identified."""
    print("=" * 80)
    print("TEST 3: Normal Trading Day")
    print("=" * 80)
    
    # Monday before Thanksgiving
    normal_day = datetime.datetime(2025, 11, 24, 10, 0)
    holiday_file = "market_data/market_holidays.json"
    
    is_holiday = market_holidays.is_market_holiday(normal_day, holiday_file)
    is_early = market_holidays.is_early_close_day(normal_day.date(), holiday_file)
    close_time = market_holidays.get_close_time(normal_day.date(), holiday_file)
    
    print(f"Date: {normal_day.strftime('%Y-%m-%d %H:%M')}")
    print(f"Is Market Holiday: {is_holiday}")
    print(f"Is Early Close: {is_early}")
    print(f"Close Time: {close_time}")
    print(f"Expected: False, False, 17:00:00")
    print(f"Status: {'PASS' if not is_holiday and not is_early and close_time == datetime.time(17, 0) else 'FAIL'}")
    print()
    
    return not is_holiday and not is_early and close_time == datetime.time(17, 0)


def test_buffer_calculation():
    """Test buffer time calculations for early close."""
    print("=" * 80)
    print("TEST 4: Buffer Time Calculation")
    print("=" * 80)
    
    # Black Friday with 30-minute buffer - Close @ 13:15 ET
    black_friday = datetime.date(2025, 11, 28)
    holiday_file = "market_data/market_holidays.json"
    
    close_time = market_holidays.get_close_time(black_friday, holiday_file)
    minutes_before = 30
    
    # Calculate adjusted close
    close_datetime = datetime.datetime.combine(black_friday, close_time)
    adjusted_close = close_datetime - datetime.timedelta(minutes=minutes_before)
    
    expected_adjusted = datetime.time(12, 45)  # 13:15 - 30 min = 12:45
    
    print(f"Date: {black_friday.isoformat()}")
    print(f"Actual Close Time: {close_time}")
    print(f"Buffer: {minutes_before} minutes")
    print(f"Adjusted Close Time: {adjusted_close.strftime('%H:%M')}")
    print(f"Expected: {expected_adjusted}")
    print(f"Status: {'PASS' if adjusted_close.time() == expected_adjusted else 'FAIL'}")
    print()
    
    return adjusted_close.time() == expected_adjusted


def test_has_current_week_data():
    """Test that current week data check works."""
    print("=" * 80)
    print("TEST 5: Current Week Data Check")
    print("=" * 80)
    
    holiday_file = "market_data/market_holidays.json"
    
    has_data = market_holidays.has_current_week_data(holiday_file)
    
    print(f"Holiday File: {holiday_file}")
    print(f"Has Current Week Data: {has_data}")
    print(f"Expected: True")
    print(f"Status: {'PASS' if has_data else 'FAIL'}")
    print()
    
    return has_data


def run_all_tests():
    """Run all tests and report results."""
    print("\n")
    print("=" * 80)
    print("MARKET HOLIDAYS INTEGRATION TEST SUITE")
    print("=" * 80)
    print()
    
    tests = [
        ("Thanksgiving Early Close", test_holiday_detection),
        ("Black Friday Early Close", test_early_close_detection),
        ("Normal Day Detection", test_normal_day),
        ("Buffer Calculation", test_buffer_calculation),
        ("Current Week Data Check", test_has_current_week_data)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"X {test_name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("All tests passed!")
        return 0
    else:
        print(f"WARNING: {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)


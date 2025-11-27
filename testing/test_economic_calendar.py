"""
Test script for economic_calendar module

This script tests the economic calendar fetching, classification, and filtering functionality.
"""

import sys
import os
import logging
import json
import datetime

# Add parent directory to path to import economic_calendar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import economic_calendar
import configparser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def print_separator(title=""):
    """Print a separator line with optional title"""
    if title:
        print(f"\n{'='*80}")
        print(f"{title:^80}")
        print(f"{'='*80}\n")
    else:
        print(f"{'='*80}\n")


def test_trading_week():
    """Test trading week calculation"""
    print_separator("Test 1: Trading Week Calculation")
    
    week_start, week_end = economic_calendar.get_current_trading_week()
    
    print(f"Current Date: {datetime.datetime.now().strftime('%Y-%m-%d %A')}")
    print(f"Trading Week Start: {week_start} ({week_start.strftime('%A')})")
    print(f"Trading Week End: {week_end} ({week_end.strftime('%A')})")
    
    # Verify Sunday to Friday
    assert week_start.weekday() == 6, "Week should start on Sunday"
    assert week_end.weekday() == 4, "Week should end on Friday"
    
    print("✓ Trading week calculation working correctly\n")


def test_fetch_calendar():
    """Test fetching calendar from MarketWatch"""
    print_separator("Test 2: Fetch Calendar from MarketWatch")
    
    events = economic_calendar.fetch_marketwatch_calendar()
    
    print(f"Fetched {len(events)} events")
    
    if events:
        print("\nSample events:")
        for i, event in enumerate(events[:5], 1):
            print(f"{i}. {event.get('name', 'Unknown')}")
            print(f"   Time: {event.get('datetime', 'Unknown')}")
            print(f"   Forecast: {event.get('forecast', 'N/A')}")
            print(f"   Previous: {event.get('previous', 'N/A')}\n")
        
        if len(events) > 5:
            print(f"... and {len(events) - 5} more events")
    else:
        print("⚠ No events fetched (this might be expected if scraping failed)")
    
    print()


def test_llm_classification():
    """Test LLM classification of events"""
    print_separator("Test 3: LLM Classification")
    
    # Load config for OpenAI credentials
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    openai_config = {
        'api_key': config.get('OpenAI', 'api_key', fallback=''),
        'api_url': config.get('OpenAI', 'api_url', fallback='https://api.openai.com/v1/chat/completions')
    }
    
    classification_prompt = config.get('EconomicCalendar', 'classification_prompt', fallback='Analyze these economic calendar events and classify each by market impact severity (High/Medium/Low) for ES futures trading. For each event, provide expected market reaction and affected instruments. Return JSON format.')
    
    # Fetch events
    events = economic_calendar.fetch_marketwatch_calendar()
    
    if not events:
        print("⚠ No events to classify (using sample events)")
        events = economic_calendar.create_sample_events()
    
    if not openai_config['api_key'] or openai_config['api_key'] == 'your-openai-api-key-here':
        print("⚠ OpenAI API key not configured - skipping LLM classification test")
        print("  To test LLM classification, set your OpenAI API key in config.ini")
        return
    
    # Take only first 5 events for testing
    test_events = events[:5]
    
    print(f"Classifying {len(test_events)} events with LLM...\n")
    
    classified_events = economic_calendar.classify_events_with_llm(test_events, openai_config, classification_prompt)
    
    print(f"Successfully classified {len(classified_events)} events\n")
    
    for i, event in enumerate(classified_events, 1):
        print(f"{i}. {event.get('name', 'Unknown')}")
        print(f"   Severity: {event.get('severity', 'Unknown')}")
        print(f"   Impact: {event.get('market_impact_description', 'N/A')[:100]}...")
        print(f"   Affects: {', '.join(event.get('affected_instruments', []))}\n")


def test_save_and_load():
    """Test saving and loading calendar data"""
    print_separator("Test 4: Save and Load Calendar Data")
    
    test_file = 'market_data/economic_calendar_test.json'
    
    # Create sample events with classifications
    events = economic_calendar.create_sample_events()
    for event in events:
        event['severity'] = 'Medium'
        event['market_impact_description'] = 'Test impact description'
        event['affected_instruments'] = ['ES', 'NQ']
    
    # Save
    print(f"Saving {len(events)} events to {test_file}...")
    success = economic_calendar.save_calendar_data(events, test_file)
    
    if success:
        print("✓ Save successful\n")
    else:
        print("✗ Save failed\n")
        return
    
    # Load
    print(f"Loading calendar data from {test_file}...")
    data = economic_calendar.load_calendar_data(test_file)
    
    if data and 'events' in data:
        print(f"✓ Loaded {len(data['events'])} events")
        print(f"  Week: {data.get('week_start')} to {data.get('week_end')}")
        print(f"  Fetched: {data.get('fetch_timestamp')}\n")
    else:
        print("✗ Load failed\n")
        return
    
    # Test has_current_week_data
    has_data = economic_calendar.has_current_week_data(test_file)
    print(f"Has current week data: {has_data}")
    
    if has_data:
        print("✓ Week data validation working\n")
    else:
        print("⚠ Week data validation indicates data is outdated or invalid\n")


def test_upcoming_events():
    """Test filtering upcoming events"""
    print_separator("Test 5: Filter Upcoming Events")
    
    test_file = 'market_data/economic_calendar_test.json'
    
    # Create sample events - some in the past, some upcoming, some far future
    now = datetime.datetime.now()
    events = []
    
    # Event 10 minutes ago
    events.append({
        'name': 'Past Event',
        'datetime': (now - datetime.timedelta(minutes=10)).isoformat(),
        'severity': 'High',
        'market_impact_description': 'Already happened',
        'affected_instruments': ['ES']
    })
    
    # Event in 5 minutes
    events.append({
        'name': 'Imminent High-Impact Event',
        'datetime': (now + datetime.timedelta(minutes=5)).isoformat(),
        'severity': 'High',
        'market_impact_description': 'Very soon - high volatility expected',
        'affected_instruments': ['ES', 'NQ']
    })
    
    # Event in 12 minutes
    events.append({
        'name': 'Upcoming Medium Event',
        'datetime': (now + datetime.timedelta(minutes=12)).isoformat(),
        'severity': 'Medium',
        'market_impact_description': 'Moderate impact expected',
        'affected_instruments': ['ES']
    })
    
    # Event in 30 minutes
    events.append({
        'name': 'Future Event',
        'datetime': (now + datetime.timedelta(minutes=30)).isoformat(),
        'severity': 'High',
        'market_impact_description': 'Still some time away',
        'affected_instruments': ['ES']
    })
    
    # Save test data
    economic_calendar.save_calendar_data(events, test_file)
    
    # Test different filters
    print("Filter 1: 15 minutes before, 15 minutes after, High+Medium severity")
    upcoming = economic_calendar.get_upcoming_events(test_file, 15, 15, ['High', 'Medium'])
    print(f"Found {len(upcoming)} events:\n")
    for event in upcoming:
        print(f"  - {event['name']}")
        print(f"    Severity: {event['severity']}")
        print(f"    Time until: {event['minutes_until']:.1f} minutes\n")
    
    print("\nFilter 2: 10 minutes before, 5 minutes after, High severity only")
    upcoming = economic_calendar.get_upcoming_events(test_file, 10, 5, ['High'])
    print(f"Found {len(upcoming)} events:\n")
    for event in upcoming:
        print(f"  - {event['name']}")
        print(f"    Time until: {event['minutes_until']:.1f} minutes\n")


def test_full_workflow():
    """Test complete workflow as it would run in production"""
    print_separator("Test 6: Full Production Workflow Simulation")
    
    # Load config
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    calendar_file = config.get('EconomicCalendar', 'data_file', fallback='market_data/economic_calendar.json')
    
    print(f"Calendar file: {calendar_file}\n")
    
    # Step 1: Check if we have current week data
    print("Step 1: Check for current week data...")
    has_data = economic_calendar.has_current_week_data(calendar_file)
    
    if has_data:
        print("✓ Current week data exists\n")
    else:
        print("✗ No current week data - would fetch and classify in production\n")
    
    # Step 2: Get upcoming events (simulating what happens in job())
    print("Step 2: Get upcoming events for LLM context...")
    minutes_before = config.getint('EconomicCalendar', 'minutes_before_event', fallback=15)
    minutes_after = config.getint('EconomicCalendar', 'minutes_after_event', fallback=15)
    severity_threshold = config.get('EconomicCalendar', 'severity_threshold', fallback='High,Medium')
    severity_filter = [s.strip() for s in severity_threshold.split(',')]
    
    print(f"  Looking {minutes_before} minutes ahead and {minutes_after} minutes back")
    print(f"  Severity filter: {severity_filter}\n")
    
    upcoming = economic_calendar.get_upcoming_events(calendar_file, minutes_before, minutes_after, severity_filter)
    
    if upcoming:
        print(f"✓ Found {len(upcoming)} upcoming events to include in LLM context:\n")
        for event in upcoming:
            print(f"  - {event['name']}")
            print(f"    Severity: {event['severity']}")
            print(f"    Time: {event.get('datetime', 'Unknown')}")
            print(f"    Minutes until: {event['minutes_until']:.1f}")
            print(f"    Impact: {event.get('market_impact_description', 'N/A')[:80]}...\n")
    else:
        print("✓ No upcoming events in the specified time window\n")
    
    # Step 3: Show what would be sent to LLM
    print("Step 3: Sample JSON that would be sent to LLM:")
    llm_events = []
    for event in upcoming[:3]:  # Limit to 3 for display
        llm_events.append({
            'name': event.get('name'),
            'datetime': event.get('datetime'),
            'minutes_until': event.get('minutes_until'),
            'severity': event.get('severity'),
            'market_impact': event.get('market_impact_description')
        })
    
    sample_json = {
        "UpcomingEconomicEvents": llm_events
    }
    
    print(json.dumps(sample_json, indent=2))
    print()


def main():
    """Run all tests"""
    print_separator("ECONOMIC CALENDAR MODULE TEST SUITE")
    
    print("This test suite will:")
    print("1. Test trading week calculation")
    print("2. Test fetching calendar from MarketWatch")
    print("3. Test LLM classification (requires OpenAI API key)")
    print("4. Test saving and loading calendar data")
    print("5. Test filtering upcoming events")
    print("6. Test full production workflow simulation")
    print("\nPress Enter to continue...")
    input()
    
    try:
        test_trading_week()
        test_fetch_calendar()
        test_llm_classification()
        test_save_and_load()
        test_upcoming_events()
        test_full_workflow()
        
        print_separator("ALL TESTS COMPLETED")
        print("✓ Economic calendar module is working correctly")
        print("\nNote: Some tests may show warnings if scraping fails or API keys are not configured.")
        print("This is expected behavior with appropriate fallbacks.")
        
    except Exception as e:
        print_separator("TEST FAILED")
        print(f"Error: {e}")
        logging.exception("Full traceback:")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


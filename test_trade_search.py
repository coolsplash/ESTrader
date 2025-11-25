"""
Test script to query TopstepX Trade/search API and see the response format.
"""
import requests
import json
import configparser
import sys

def authenticate(topstep_config):
    """Authenticate with TopstepX and get auth token."""
    base_url = topstep_config['base_url']
    login_endpoint = topstep_config['login_endpoint']
    url = base_url + login_endpoint
    
    payload = {
        "userName": topstep_config['user_name'],
        "apiKey": topstep_config['api_secret']
    }
    
    print("=" * 80)
    print("AUTHENTICATING WITH TOPSTEPX")
    print("=" * 80)
    print(f"URL: {url}")
    print(f"Username: {topstep_config['user_name']}")
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('success'):
            token = data.get('token')
            print(f"[SUCCESS] Authentication successful!")
            print(f"Token: {token[:20]}..." if token else "No token returned")
            return token
        else:
            print(f"[ERROR] Authentication failed: {data.get('errorMessage')}")
            return None
            
    except Exception as e:
        print(f"[ERROR] Error authenticating: {e}")
        return None

def search_trades(topstep_config, auth_token, account_id, start_timestamp, end_timestamp):
    """Query the Trade/search API."""
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
    
    print("\n" + "=" * 80)
    print("QUERYING TRADE/SEARCH API")
    print("=" * 80)
    print(f"URL: {url}")
    print(f"Payload:")
    print(json.dumps(payload, indent=2))
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        print("\n" + "=" * 80)
        print("API RESPONSE")
        print("=" * 80)
        print(f"Status Code: {response.status_code}")
        print(f"Success: {data.get('success')}")
        print(f"Error Code: {data.get('errorCode')}")
        print(f"Error Message: {data.get('errorMessage')}")
        
        # Pretty print the full response
        print("\n" + "=" * 80)
        print("FULL JSON RESPONSE")
        print("=" * 80)
        print(json.dumps(data, indent=2))
        
        # Analyze trades if present
        trades = data.get('trades', [])
        print("\n" + "=" * 80)
        print(f"TRADES SUMMARY ({len(trades)} trades found)")
        print("=" * 80)
        
        if trades:
            for idx, trade in enumerate(trades, 1):
                print(f"\n--- Trade {idx} ---")
                print(f"  ID: {trade.get('id')}")
                print(f"  Order ID: {trade.get('orderId')}")
                print(f"  Account ID: {trade.get('accountId')}")
                print(f"  Contract ID: {trade.get('contractId')}")
                print(f"  Side: {trade.get('side')} (0=Buy, 1=Sell)")
                print(f"  Size: {trade.get('size')}")
                print(f"  Price: {trade.get('price')}")
                
                pnl = trade.get('profitAndLoss')
                fees = trade.get('fees', 0)
                print(f"  Profit & Loss: {'N/A' if pnl is None else f'${pnl:.2f}'}")
                print(f"  Fees: ${fees:.2f}" if fees else "  Fees: $0.00")
                
                if pnl is not None:
                    net = pnl - fees
                    print(f"  Net P&L: ${net:.2f}")
                else:
                    print(f"  Net P&L: N/A (entry trade)")
                    
                print(f"  Voided: {trade.get('voided')}")
                print(f"  Creation Time: {trade.get('creationTimestamp')}")
            
            # Calculate totals (only for trades with P&L)
            total_pnl = sum(trade.get('profitAndLoss', 0) for trade in trades if trade.get('profitAndLoss') is not None)
            total_fees = sum(trade.get('fees', 0) for trade in trades)
            net_pnl = total_pnl - total_fees
            
            print("\n" + "=" * 80)
            print("TOTALS")
            print("=" * 80)
            print(f"Total P&L: ${total_pnl:.2f}")
            print(f"Total Fees: ${total_fees:.2f}")
            print(f"Net P&L: ${net_pnl:.2f}")
            print(f"Net P&L (Points): {net_pnl / 50:.2f} pts (assuming ES @ $50/point)")
        else:
            print("No trades found in the specified time range.")
        
        return data
        
    except Exception as e:
        print(f"\n[ERROR] Error querying Trade/search API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response text: {e.response.text}")
        return None

def main():
    # Load config
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    topstep_config = {
        'base_url': config.get('Topstep', 'base_url'),
        'login_endpoint': config.get('Topstep', 'login_endpoint'),
        'user_name': config.get('Topstep', 'user_name'),
        'api_secret': config.get('Topstep', 'api_secret'),
        'trade_search_endpoint': config.get('Topstep', 'trade_search_endpoint', fallback='/api/Trade/search')
    }
    
    # Authentication
    auth_token = authenticate(topstep_config)
    if not auth_token:
        print("\n[ERROR] Authentication failed. Exiting.")
        sys.exit(1)
    
    # Search trades
    account_id = 14664776
    start_timestamp = "2025-11-24T00:00:00Z"
    end_timestamp = "2025-11-24T00:20:00Z"
    
    print(f"\n[INFO] Searching for trades between {start_timestamp} and {end_timestamp}")
    
    result = search_trades(topstep_config, auth_token, account_id, start_timestamp, end_timestamp)
    
    if result:
        print("\n[SUCCESS] Query completed successfully!")
    else:
        print("\n[ERROR] Query failed.")

if __name__ == "__main__":
    main()


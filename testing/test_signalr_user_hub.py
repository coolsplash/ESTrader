"""
SignalR User Hub Test Script

This script connects to the TopstepX/ProjectX SignalR user hub to monitor
real-time events for accounts, orders, positions, and trades.

Purpose: Evaluate if SignalR can replace the current REST API polling mechanism.
"""

import sys
import os
import time
import json
import datetime
import configparser
from pathlib import Path

# Add parent directory to path to import from main project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder
    SIGNALR_AVAILABLE = True
except ImportError:
    print("ERROR: signalrcore library not installed!")
    print("Please run: pip install signalrcore")
    SIGNALR_AVAILABLE = False
    sys.exit(1)


class SignalRUserHubTest:
    """Test harness for SignalR user hub connection and events."""
    
    def __init__(self, config_path='../config.ini'):
        """Initialize the test harness."""
        self.config = configparser.ConfigParser()
        # If running from testing folder, look in parent directory
        if not os.path.exists(config_path):
            config_path = 'config.ini'
        self.config.read(config_path)
        
        # Connection state
        self.hub_connection = None
        self.is_connected = False
        self.connection_start_time = None
        self.reconnect_count = 0
        
        # Event statistics
        self.event_counts = {
            'GatewayUserAccount': 0,
            'GatewayUserOrder': 0,
            'GatewayUserPosition': 0,
            'GatewayUserTrade': 0
        }
        
        # Event storage
        self.events_log = []
        self.current_positions = {}
        self.current_orders = {}
        self.account_info = {}
        
        # Logging
        self.log_directory = Path('testing/signalr_logs')
        self.log_directory.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_directory / f'signalr_events_{timestamp}.log'
        self.summary_file = self.log_directory / f'signalr_summary_{timestamp}.json'
        
        # Get configuration
        self.account_id = self.config.get('Topstep', 'account_id')
        
        # Get SignalR hub base URL from config
        signalr_base = self.config.get('SignalRTest', 'signalr_url', fallback='https://gateway-rtc-topstepx.projectx.com/hubs')
        
        # Convert https:// to wss:// for WebSocket connection
        if signalr_base.startswith('https://'):
            signalr_base = signalr_base.replace('https://', 'wss://')
        elif signalr_base.startswith('http://'):
            signalr_base = signalr_base.replace('http://', 'ws://')
        
        # Construct user hub URL by appending /user
        self.hub_url = f"{signalr_base}/user"
        
        print(f"Hub URL: {self.hub_url}")
        
    def log_event(self, event_type, data):
        """Log an event to both console and file."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # Create log entry
        log_entry = {
            'timestamp': timestamp,
            'event_type': event_type,
            'data': data
        }
        
        self.events_log.append(log_entry)
        
        # Write to file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Console output with color coding
        color_codes = {
            'GatewayUserAccount': '\033[94m',  # Blue
            'GatewayUserOrder': '\033[93m',     # Yellow
            'GatewayUserPosition': '\033[92m', # Green
            'GatewayUserTrade': '\033[91m',     # Red
            'INFO': '\033[96m',                 # Cyan
            'ERROR': '\033[91m'                 # Red
        }
        reset_code = '\033[0m'
        
        color = color_codes.get(event_type, '')
        print(f"{color}[{timestamp}] {event_type}{reset_code}")
        print(f"  {json.dumps(data, indent=2)}")
        print()
    
    def handle_account_update(self, data):
        """Handle GatewayUserAccount event."""
        self.event_counts['GatewayUserAccount'] += 1
        self.account_info[data.get('id', 'unknown')] = data
        self.log_event('GatewayUserAccount', data)
    
    def handle_order_update(self, data):
        """Handle GatewayUserOrder event."""
        self.event_counts['GatewayUserOrder'] += 1
        order_id = data.get('id', 'unknown')
        self.current_orders[order_id] = data
        self.log_event('GatewayUserOrder', data)
        
        # Calculate latency if timestamp present
        if 'updateTimestamp' in data:
            try:
                event_time = datetime.datetime.fromisoformat(data['updateTimestamp'].replace('Z', '+00:00'))
                receive_time = datetime.datetime.now(datetime.timezone.utc)
                latency_ms = (receive_time - event_time).total_seconds() * 1000
                print(f"  --> Latency: {latency_ms:.0f}ms")
            except:
                pass
    
    def handle_position_update(self, data):
        """Handle GatewayUserPosition event."""
        self.event_counts['GatewayUserPosition'] += 1
        position_id = data.get('id', 'unknown')
        
        # Track position changes
        if position_id in self.current_positions:
            old_data = self.current_positions[position_id]
            print(f"  --> Position UPDATED: Size {old_data.get('size')} -> {data.get('size')}")
        else:
            print(f"  --> Position OPENED: {data.get('contractId')} ({data.get('type')})")
        
        self.current_positions[position_id] = data
        self.log_event('GatewayUserPosition', data)
        
        # Calculate latency if timestamp present
        if 'creationTimestamp' in data:
            try:
                event_time = datetime.datetime.fromisoformat(data['creationTimestamp'].replace('Z', '+00:00'))
                receive_time = datetime.datetime.now(datetime.timezone.utc)
                latency_ms = (receive_time - event_time).total_seconds() * 1000
                print(f"  --> Latency: {latency_ms:.0f}ms")
            except:
                pass
    
    def handle_trade_update(self, data):
        """Handle GatewayUserTrade event."""
        self.event_counts['GatewayUserTrade'] += 1
        self.log_event('GatewayUserTrade', data)
        
        # Highlight P&L
        pnl = data.get('profitAndLoss', 0)
        fees = data.get('fees', 0)
        net_pnl = pnl - fees
        print(f"  --> Trade P&L: ${net_pnl:+.2f} (Gross: ${pnl:+.2f}, Fees: ${fees:.2f})")
        
        # Calculate latency if timestamp present
        if 'creationTimestamp' in data:
            try:
                event_time = datetime.datetime.fromisoformat(data['creationTimestamp'].replace('Z', '+00:00'))
                receive_time = datetime.datetime.now(datetime.timezone.utc)
                latency_ms = (receive_time - event_time).total_seconds() * 1000
                print(f"  --> Latency: {latency_ms:.0f}ms")
            except:
                pass
    
    def on_open(self):
        """Callback when connection is opened."""
        self.is_connected = True
        self.connection_start_time = time.time()
        print("\n" + "="*80)
        print("SignalR Connection OPENED")
        print("="*80 + "\n")
        
        # Subscribe to all events
        try:
            print(f"Subscribing to account: {self.account_id}")
            self.hub_connection.send("SubscribeAccounts", [])
            self.hub_connection.send("SubscribeOrders", [int(self.account_id)])
            self.hub_connection.send("SubscribePositions", [int(self.account_id)])
            self.hub_connection.send("SubscribeTrades", [int(self.account_id)])
            print("✓ Subscriptions sent successfully\n")
        except Exception as e:
            print(f"ERROR subscribing: {e}\n")
    
    def on_close(self):
        """Callback when connection is closed."""
        self.is_connected = False
        print("\n" + "="*80)
        print("SignalR Connection CLOSED")
        print("="*80 + "\n")
    
    def on_reconnect(self):
        """Callback when connection is reconnected."""
        self.reconnect_count += 1
        print("\n" + "="*80)
        print(f"SignalR Connection RECONNECTED (Attempt #{self.reconnect_count})")
        print("="*80 + "\n")
        
        # Resubscribe after reconnection
        try:
            print(f"Resubscribing to account: {self.account_id}")
            self.hub_connection.send("SubscribeAccounts", [])
            self.hub_connection.send("SubscribeOrders", [int(self.account_id)])
            self.hub_connection.send("SubscribePositions", [int(self.account_id)])
            self.hub_connection.send("SubscribeTrades", [int(self.account_id)])
            print("✓ Resubscriptions sent successfully\n")
        except Exception as e:
            print(f"ERROR resubscribing: {e}\n")
    
    def on_error(self, data):
        """Callback when an error occurs."""
        print("\n" + "="*80)
        print("SignalR ERROR")
        print("="*80)
        print(f"Error: {data}\n")
        self.log_event('ERROR', {'message': str(data)})
    
    def connect(self, auth_token):
        """Establish SignalR connection."""
        if not SIGNALR_AVAILABLE:
            print("ERROR: signalrcore not available")
            return False
        
        try:
            print(f"Connecting to SignalR hub: {self.hub_url}")
            print(f"Using account ID: {self.account_id}\n")
            
            # Build SignalR connection
            self.hub_connection = HubConnectionBuilder()\
                .with_url(
                    f"{self.hub_url}?access_token={auth_token}",
                    options={
                        "skip_negotiation": True
                    }
                )\
                .with_automatic_reconnect({
                    "type": "interval",
                    "keep_alive_interval": 10,
                    "intervals": [1, 2, 5, 10, 30]
                })\
                .build()
            
            # Register event handlers
            self.hub_connection.on("GatewayUserAccount", self.handle_account_update)
            self.hub_connection.on("GatewayUserOrder", self.handle_order_update)
            self.hub_connection.on("GatewayUserPosition", self.handle_position_update)
            self.hub_connection.on("GatewayUserTrade", self.handle_trade_update)
            
            # Register connection state handlers
            self.hub_connection.on_open(self.on_open)
            self.hub_connection.on_close(self.on_close)
            self.hub_connection.on_reconnect(self.on_reconnect)
            self.hub_connection.on_error(self.on_error)
            
            # Start connection
            self.hub_connection.start()
            
            print("✓ SignalR connection started\n")
            return True
            
        except Exception as e:
            print(f"ERROR connecting to SignalR: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def disconnect(self):
        """Close SignalR connection."""
        if self.hub_connection:
            try:
                self.hub_connection.stop()
                print("\n✓ SignalR connection stopped")
            except Exception as e:
                print(f"\nERROR stopping connection: {e}")
    
    def print_status(self):
        """Print current status and statistics."""
        uptime = time.time() - self.connection_start_time if self.connection_start_time else 0
        
        print("\n" + "="*80)
        print("SignalR Connection Status")
        print("="*80)
        print(f"Connected: {self.is_connected}")
        print(f"Uptime: {uptime:.0f} seconds ({uptime/60:.1f} minutes)")
        print(f"Reconnections: {self.reconnect_count}")
        print()
        print("Event Counts:")
        for event_type, count in self.event_counts.items():
            print(f"  {event_type}: {count}")
        print()
        print(f"Current Positions: {len(self.current_positions)}")
        print(f"Current Orders: {len(self.current_orders)}")
        print(f"Total Events Logged: {len(self.events_log)}")
        print("="*80 + "\n")
    
    def save_summary(self):
        """Save summary statistics to JSON file."""
        uptime = time.time() - self.connection_start_time if self.connection_start_time else 0
        
        summary = {
            'test_start_time': self.connection_start_time,
            'uptime_seconds': uptime,
            'reconnect_count': self.reconnect_count,
            'event_counts': self.event_counts,
            'total_events': len(self.events_log),
            'final_positions': self.current_positions,
            'final_orders': self.current_orders,
            'account_info': self.account_info
        }
        
        with open(self.summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"✓ Summary saved to: {self.summary_file}")


def get_auth_token(config):
    """Get authentication token from TopstepX API."""
    import requests
    
    base_url = config.get('Topstep', 'base_url')
    user_name = config.get('Topstep', 'user_name')
    api_key = config.get('Topstep', 'api_key')
    login_endpoint = config.get('Topstep', 'login_endpoint')
    
    print("Authenticating with TopstepX API...")
    
    try:
        response = requests.post(
            f"{base_url}{login_endpoint}",
            json={"userName": user_name, "apiKey": api_key},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if authentication was successful
            if not data.get('success', False):
                print(f"ERROR: Authentication failed - errorCode: {data.get('errorCode')}")
                print(f"Error message: {data.get('errorMessage')}")
                return None
            
            # Try both 'token' and 'accessToken' keys
            token = data.get('token') or data.get('accessToken')
            if token:
                print("✓ Authentication successful\n")
                return token
            else:
                print("ERROR: No token in response")
                print(f"Response data: {json.dumps(data, indent=2)}")
                return None
        else:
            print(f"ERROR: Authentication failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"ERROR authenticating: {e}")
        return None


def main():
    """Main test function."""
    print("\n" + "="*80)
    print("SignalR User Hub Test - TopstepX Real-Time Events")
    print("="*80 + "\n")
    
    # Initialize test harness
    test = SignalRUserHubTest()
    
    # Check if manual auth token is provided in config
    auth_token = None
    if test.config.has_option('SignalRTest', 'auth_token'):
        auth_token = test.config.get('SignalRTest', 'auth_token')
        if auth_token:
            print("Using manual auth token from config\n")
    
    # If no manual token, try to authenticate
    if not auth_token:
        auth_token = get_auth_token(test.config)
        if not auth_token:
            print("FAILED: Could not authenticate")
            return
    
    # Connect to SignalR hub
    if not test.connect(auth_token):
        print("FAILED: Could not connect to SignalR hub")
        return
    
    print("Monitoring events... (Press Ctrl+C to stop)\n")
    
    # Main monitoring loop
    try:
        last_status_print = time.time()
        
        while True:
            time.sleep(1)
            
            # Print status every 60 seconds
            if time.time() - last_status_print >= 60:
                test.print_status()
                last_status_print = time.time()
    
    except KeyboardInterrupt:
        print("\n\nStopping test...")
    
    finally:
        # Clean up
        test.print_status()
        test.save_summary()
        test.disconnect()
        
        print("\n" + "="*80)
        print("Test Complete")
        print("="*80)
        print(f"Events log: {test.log_file}")
        print(f"Summary: {test.summary_file}")
        print()


if __name__ == "__main__":
    main()


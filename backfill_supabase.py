"""
Backfill existing CSV trade data and LLM interactions into Supabase.

This script reads all existing CSV files in the trades/ and logs/ directories
and imports them into Supabase for centralized storage and analytics.
"""

import os
import sys
import csv
import datetime
import configparser
from supabase import create_client, Client

# Configure UTF-8 encoding for console output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # Already configured or not needed

# Load configuration
config = configparser.ConfigParser()
config.read('config.ini')

# Supabase configuration
SUPABASE_URL = config.get('Supabase', 'supabase_url', fallback='')
SUPABASE_KEY = config.get('Supabase', 'supabase_anon_key', fallback='')
ACCOUNT_ID = config.get('Topstep', 'account_id', fallback='')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Supabase configuration missing in config.ini")
    print("Please add [Supabase] section with supabase_url and supabase_anon_key")
    exit(1)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("="*80)
print("ESTrader - Supabase Backfill Script")
print("="*80)
print(f"Supabase URL: {SUPABASE_URL}")
print(f"Account ID: {ACCOUNT_ID}")
print("="*80)

def backfill_trades():
    """Backfill trade data from monthly CSV files."""
    trades_dir = 'trades'
    if not os.path.exists(trades_dir):
        print(f"No trades directory found at {trades_dir}")
        return 0
    
    total_imported = 0
    csv_files = [f for f in os.listdir(trades_dir) if f.endswith('.csv')]
    
    print(f"\nFound {len(csv_files)} trade CSV files to process...")
    
    for csv_file in sorted(csv_files):
        filepath = os.path.join(trades_dir, csv_file)
        print(f"\nProcessing: {csv_file}")
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                if not rows:
                    print(f"  Skipping empty file")
                    continue
                
                batch = []
                for row in rows:
                    # Parse timestamp
                    timestamp_str = f"{row.get('date', '')} {row.get('time', '')}".strip()
                    try:
                        timestamp = datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    except:
                        print(f"  Warning: Could not parse timestamp: {timestamp_str}")
                        timestamp = datetime.datetime.now()
                    
                    # Prepare trade data
                    trade_data = {
                        'account_id': ACCOUNT_ID,
                        'order_id': str(row.get('order_id', 'UNKNOWN')),
                        'timestamp': timestamp.isoformat(),
                        'event_type': row.get('event_type', 'UNKNOWN'),
                        'symbol': row.get('symbol', 'ES'),
                        'position_type': row.get('position_type', 'long'),
                        'size': int(row.get('size', 0)) if row.get('size') else 0,
                        'price': float(row.get('price', 0)) if row.get('price') else None,
                        'entry_price': float(row.get('entry_price', 0)) if row.get('entry_price') else None,
                        'stop_loss': float(row.get('stop_loss', 0)) if row.get('stop_loss') else None,
                        'take_profit': float(row.get('take_profit', 0)) if row.get('take_profit') else None,
                        'reasoning': row.get('reasoning', ''),
                        'confidence': int(row.get('confidence', 0)) if row.get('confidence') else None,
                        'profit_loss': float(row.get('profit_loss', 0)) if row.get('profit_loss') else None,
                        'profit_loss_points': float(row.get('profit_loss_points', 0)) if row.get('profit_loss_points') else None,
                        'balance': float(row.get('balance', 0)) if row.get('balance') else None,
                        'market_context': row.get('market_context', '')
                    }
                    
                    batch.append(trade_data)
                
                # Insert batch
                if batch:
                    response = supabase.table('trades').insert(batch).execute()
                    total_imported += len(batch)
                    print(f"  ✅ Imported {len(batch)} trades")
        
        except Exception as e:
            print(f"  ❌ Error processing {csv_file}: {e}")
    
    return total_imported

def backfill_llm_interactions():
    """Backfill LLM interaction data from daily CSV files."""
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        print(f"No logs directory found at {logs_dir}")
        return 0
    
    total_imported = 0
    csv_files = [f for f in os.listdir(logs_dir) if f.endswith('_LLM.csv')]
    
    print(f"\nFound {len(csv_files)} LLM interaction CSV files to process...")
    
    for csv_file in sorted(csv_files):
        filepath = os.path.join(logs_dir, csv_file)
        print(f"\nProcessing: {csv_file}")
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                if not rows:
                    print(f"  Skipping empty file")
                    continue
                
                batch = []
                for row in rows:
                    # Parse timestamp
                    timestamp_str = row.get('date_time', '')
                    try:
                        timestamp = datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    except:
                        print(f"  Warning: Could not parse timestamp: {timestamp_str}")
                        timestamp = datetime.datetime.now()
                    
                    # Prepare LLM data
                    llm_data = {
                        'account_id': ACCOUNT_ID,
                        'order_id': None,  # Not tracked in old CSV format
                        'timestamp': timestamp.isoformat(),
                        'request': row.get('request', '')[:1000],  # Truncate
                        'response': row.get('response', '')[:1000],  # Truncate
                        'action': row.get('action', ''),
                        'entry_price': float(row.get('entry_price', 0)) if row.get('entry_price') else None,
                        'price_target': float(row.get('price_target', 0)) if row.get('price_target') else None,
                        'stop_loss': float(row.get('stop_loss', 0)) if row.get('stop_loss') else None,
                        'confidence': int(row.get('confidence', 0)) if row.get('confidence') else None,
                        'reasoning': row.get('reasoning', '')[:500],  # Truncate
                        'context': row.get('context', '')[:500]  # Truncate
                    }
                    
                    batch.append(llm_data)
                
                # Insert batch
                if batch:
                    response = supabase.table('llm_interactions').insert(batch).execute()
                    total_imported += len(batch)
                    print(f"  ✅ Imported {len(batch)} LLM interactions")
        
        except Exception as e:
            print(f"  ❌ Error processing {csv_file}: {e}")
    
    return total_imported

def register_account():
    """Register the current account in Supabase if not exists."""
    try:
        # Check if account exists
        response = supabase.table('accounts').select('*').eq('account_id', ACCOUNT_ID).execute()
        
        if not response.data:
            # Register account
            account_data = {
                'account_id': ACCOUNT_ID,
                'account_name': f'TopstepX Account {ACCOUNT_ID}',
                'broker': 'TopstepX'
            }
            supabase.table('accounts').insert(account_data).execute()
            print(f"✅ Registered account {ACCOUNT_ID} in Supabase")
        else:
            print(f"✅ Account {ACCOUNT_ID} already registered")
    except Exception as e:
        print(f"❌ Error registering account: {e}")

if __name__ == "__main__":
    print("\nStarting backfill process...\n")
    
    # Register account
    register_account()
    
    # Backfill trades
    print("\n" + "="*80)
    print("BACKFILLING TRADES")
    print("="*80)
    trades_imported = backfill_trades()
    
    # Backfill LLM interactions
    print("\n" + "="*80)
    print("BACKFILLING LLM INTERACTIONS")
    print("="*80)
    llm_imported = backfill_llm_interactions()
    
    # Summary
    print("\n" + "="*80)
    print("BACKFILL COMPLETE")
    print("="*80)
    print(f"Total trades imported: {trades_imported}")
    print(f"Total LLM interactions imported: {llm_imported}")
    print(f"\nYou can now view your data at: {SUPABASE_URL}")
    print("="*80)


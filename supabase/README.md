# ESTrader Supabase Database

This directory contains SQL migration files for setting up the ESTrader database in Supabase.

## Database Schema

### Tables

#### 1. **accounts**
Tracks multiple trading accounts across different brokers.
- `id`: Primary key
- `account_id`: Unique account identifier
- `account_name`: Human-readable account name
- `broker`: Broker name (default: 'TopstepX')
- `created_at`, `updated_at`: Timestamps

#### 2. **trades**
All trade events including entries, adjustments, scales, and closes.
- `id`: Primary key
- `account_id`: References the trading account
- `order_id`: TopstepX order ID
- `timestamp`: When the event occurred
- `event_type`: ENTRY, ADJUSTMENT, SCALE, or CLOSE
- `symbol`: Trading symbol (e.g., 'ES')
- `position_type`: long or short
- `size`: Number of contracts
- `price`: Current price for this event
- `entry_price`: Original entry price
- `stop_loss`: Stop loss price
- `take_profit`: Take profit price
- `reasoning`: LLM reasoning for the decision
- `confidence`: LLM confidence level (0-100)
- `profit_loss`: P&L in dollars
- `profit_loss_points`: P&L in points
- `balance`: Account balance after event
- `market_context`: Market context at time of event

#### 3. **llm_interactions**
LLM requests, responses, and trading decisions.
- `id`: Primary key
- `account_id`: References the trading account
- `order_id`: Associated order ID (if applicable)
- `timestamp`: When the interaction occurred
- `request`: Truncated prompt sent to LLM
- `response`: Truncated LLM response
- `action`: Parsed action (buy, sell, hold, etc.)
- `entry_price`: Suggested entry price
- `price_target`: Suggested take profit
- `stop_loss`: Suggested stop loss
- `confidence`: LLM confidence level
- `reasoning`: LLM reasoning
- `context`: Market context used

#### 4. **market_context**
Daily market context and analysis snapshots.
- `id`: Primary key
- `date`: Trading date (unique)
- `symbol`: Trading symbol
- `context_base`: Base market analysis
- `context_llm`: LLM-generated observations
- `gap_type`: Gap up/down information
- `vwap`: Volume-weighted average price

#### 5. **account_snapshots**
Account balance snapshots for tracking equity curve.
- `id`: Primary key
- `account_id`: References the trading account
- `timestamp`: Snapshot time
- `balance`: Account balance
- `daily_pnl`: Daily profit/loss

### Views

#### 1. **daily_trade_stats**
Daily aggregated trading statistics by account and symbol.
- Total trades, entries, closes
- Long vs short trades
- Total P&L, average P&L
- Winning vs losing trades
- Largest win/loss
- End of day balance

#### 2. **win_rate_analysis**
Win rate and profitability metrics by account, symbol, and position type.
- Total closed trades
- Wins vs losses
- Win rate percentage
- Average win/loss
- Profit factor

#### 3. **monthly_performance**
Monthly performance summary with P&L and drawdown.
- Total trades per month
- Monthly P&L in dollars and points
- Winning vs losing trades
- Ending/lowest balance
- Drawdown calculation

#### 4. **recent_trades**
Most recent 100 trades for quick reference.

## Setup Instructions

### Option 1: Using Supabase CLI

```bash
# Install Supabase CLI
npm install -g supabase

# Initialize Supabase project (if not done)
supabase init

# Link to your project
supabase link --project-ref YOUR_PROJECT_REF

# Apply migrations
supabase db push
```

### Option 2: Manual Setup via Supabase Dashboard

1. Go to your Supabase project dashboard
2. Navigate to SQL Editor
3. Run each migration file in order (001 → 007):
   - `001_create_accounts_table.sql`
   - `002_create_trades_table.sql`
   - `003_create_llm_interactions_table.sql`
   - `004_create_market_context_table.sql`
   - `005_create_account_snapshots_table.sql`
   - `006_create_aggregation_views.sql`
   - `007_create_update_triggers.sql`

### Option 3: Using Python (Already Applied)

The migrations have already been applied via the Supabase MCP integration.

## Backfilling Historical Data

To import existing CSV trade data into Supabase:

```bash
# Install required package
pip install supabase

# Run backfill script
python backfill_supabase.py
```

The script will:
- Register your account in the `accounts` table
- Import all trades from `trades/*.csv` files
- Import all LLM interactions from `logs/*_LLM.csv` files

## Configuration

Add to your `config.ini`:

```ini
[Supabase]
supabase_url = https://your-project.supabase.co
supabase_anon_key = your-anon-key
enable_supabase_logging = true
```

## Querying Data

### Example Queries

**Get today's trades:**
```sql
SELECT * FROM trades
WHERE DATE(timestamp) = CURRENT_DATE
ORDER BY timestamp DESC;
```

**View win rate:**
```sql
SELECT * FROM win_rate_analysis
WHERE account_id = 'YOUR_ACCOUNT_ID';
```

**Get monthly performance:**
```sql
SELECT * FROM monthly_performance
WHERE account_id = 'YOUR_ACCOUNT_ID'
ORDER BY month DESC;
```

**Recent profitable trades:**
```sql
SELECT * FROM trades
WHERE event_type = 'CLOSE' AND profit_loss > 0
ORDER BY timestamp DESC
LIMIT 10;
```

## Indexes

The schema includes optimized indexes for:
- Account lookups
- Order ID searches
- Timestamp-based queries
- Event type filtering
- Composite account+timestamp queries

## Maintenance

### Backup

Supabase automatically backs up your database daily. You can also export data via:

```sql
COPY trades TO '/path/to/backup.csv' WITH CSV HEADER;
```

### Performance

- All tables have appropriate indexes
- Views are materialized for fast aggregation
- Timestamps use TIMESTAMPTZ for timezone support
- Numeric types optimized for financial precision

## Support

For issues or questions:
- Supabase Docs: https://supabase.com/docs
- ESTrader GitHub: [Your Repo URL]


-- Create trades table for all trade events
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL CHECK (event_type IN ('ENTRY', 'ADJUSTMENT', 'SCALE', 'CLOSE')),
    symbol TEXT NOT NULL,
    position_type TEXT NOT NULL CHECK (position_type IN ('long', 'short')),
    size INTEGER NOT NULL,
    price NUMERIC(10, 2),
    entry_price NUMERIC(10, 2),
    stop_loss NUMERIC(10, 2),
    take_profit NUMERIC(10, 2),
    reasoning TEXT,
    confidence INTEGER CHECK (confidence >= 0 AND confidence <= 100),
    profit_loss NUMERIC(12, 2),
    profit_loss_points NUMERIC(10, 2),
    balance NUMERIC(15, 2),
    market_context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_trades_account_id ON trades(account_id);
CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_event_type ON trades(event_type);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_position_type ON trades(position_type);
CREATE INDEX IF NOT EXISTS idx_trades_account_timestamp ON trades(account_id, timestamp DESC);

-- Add comment
COMMENT ON TABLE trades IS 'All trade events including entries, adjustments, scales, and closes';


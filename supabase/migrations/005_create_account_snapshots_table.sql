-- Create account_snapshots table for balance tracking over time
CREATE TABLE IF NOT EXISTS account_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    balance NUMERIC(15, 2) NOT NULL,
    daily_pnl NUMERIC(12, 2),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_snapshots_account_id ON account_snapshots(account_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON account_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_account_timestamp ON account_snapshots(account_id, timestamp DESC);

-- Add comment
COMMENT ON TABLE account_snapshots IS 'Account balance snapshots for tracking equity curve';


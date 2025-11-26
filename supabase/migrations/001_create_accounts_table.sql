-- Create accounts table to track multiple trading accounts
CREATE TABLE IF NOT EXISTS accounts (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT UNIQUE NOT NULL,
    account_name TEXT,
    broker TEXT DEFAULT 'TopstepX',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add index on account_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_accounts_account_id ON accounts(account_id);

-- Add comment
COMMENT ON TABLE accounts IS 'Tracks multiple trading accounts across different brokers';


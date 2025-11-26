-- Create llm_interactions table for AI decision logging
CREATE TABLE IF NOT EXISTS llm_interactions (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    order_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    request TEXT,
    response TEXT,
    action TEXT,
    entry_price NUMERIC(10, 2),
    price_target NUMERIC(10, 2),
    stop_loss NUMERIC(10, 2),
    confidence INTEGER CHECK (confidence >= 0 AND confidence <= 100),
    reasoning TEXT,
    context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_llm_account_id ON llm_interactions(account_id);
CREATE INDEX IF NOT EXISTS idx_llm_order_id ON llm_interactions(order_id);
CREATE INDEX IF NOT EXISTS idx_llm_timestamp ON llm_interactions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_llm_action ON llm_interactions(action);
CREATE INDEX IF NOT EXISTS idx_llm_account_timestamp ON llm_interactions(account_id, timestamp DESC);

-- Add comment
COMMENT ON TABLE llm_interactions IS 'LLM requests, responses, and trading decisions';


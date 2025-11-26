-- Create market_context table for daily market analysis
CREATE TABLE IF NOT EXISTS market_context (
    id BIGSERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'ES',
    context_base TEXT,
    context_llm TEXT,
    gap_type TEXT,
    vwap NUMERIC(10, 2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_market_context_date ON market_context(date DESC);
CREATE INDEX IF NOT EXISTS idx_market_context_symbol ON market_context(symbol);

-- Add comment
COMMENT ON TABLE market_context IS 'Daily market context and analysis snapshots';


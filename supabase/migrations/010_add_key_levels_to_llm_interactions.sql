-- Add key_levels column to llm_interactions table
-- This field stores key price levels (support/resistance) the LLM is tracking

ALTER TABLE llm_interactions
ADD COLUMN IF NOT EXISTS key_levels JSONB;

-- Add comment
COMMENT ON COLUMN llm_interactions.key_levels IS 'Key price levels being tracked by LLM (support, resistance, POC, etc.) with price, type, and reason';

-- Create index for JSONB queries (optional but recommended for performance)
CREATE INDEX IF NOT EXISTS idx_llm_key_levels ON llm_interactions USING GIN (key_levels);


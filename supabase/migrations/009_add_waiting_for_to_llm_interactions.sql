-- Add waiting_for column to llm_interactions table
-- This field stores what condition the LLM is waiting for before taking action

ALTER TABLE llm_interactions
ADD COLUMN IF NOT EXISTS waiting_for TEXT;

-- Add comment
COMMENT ON COLUMN llm_interactions.waiting_for IS 'Condition the LLM is waiting for before taking action (e.g., "Break above 6675 with aggressive buying")';


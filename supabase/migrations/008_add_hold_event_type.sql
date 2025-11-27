-- Add 'HOLD' to the event_type constraint for trades table
-- This allows logging position management events where no changes were made

ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_event_type_check;

ALTER TABLE trades ADD CONSTRAINT trades_event_type_check 
CHECK (event_type IN ('ENTRY', 'ADJUSTMENT', 'SCALE', 'CLOSE', 'HOLD'));

COMMENT ON CONSTRAINT trades_event_type_check ON trades IS 'Valid event types: ENTRY (new position), ADJUSTMENT (modified stops/targets), SCALE (partial close), CLOSE (full close), HOLD (position reviewed, no changes)';


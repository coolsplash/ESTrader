# Dynamic Snapshot Timing Implementation

## Overview
Implemented LLM-controlled dynamic screenshot timing. The LLM can now request specific intervals for the next snapshot based on market conditions, overriding the configured schedule.

## Feature Description

The LLM analyzes market conditions and determines optimal timing for the next screenshot:
- **Fast-moving setups**: 10-20 seconds (when setup is developing quickly)
- **Slow/choppy markets**: 60-300 seconds (when no clear structure)
- **Default RTH**: 45 seconds (normal market hours)

This allows the system to be more responsive during critical moments and reduce API costs during quiet periods.

## Implementation Details

### 1. Updated LLM Prompt
**File:** `no_position_prompt.txt`

Added `next_snapshot` field to JSON response format:
```json
{
  "action": "buy" | "sell" | "hold",
  "entry_price": number | null,
  "price_target": number | null,
  "stop_loss": number | null,
  "confidence": 0-100,
  "reasoning": "...",
  "context": "...",
  "waiting_for": "...",
  "next_snapshot": number,  // NEW: Time in seconds until next screenshot
  "key_levels": [...]
}
```

### 2. Code Changes

**File:** `screenshot_uploader.py`

#### Added Global Variable (line ~5526)
```python
NEXT_SNAPSHOT_OVERRIDE = None  # LLM-requested interval for next snapshot (in seconds)
```

#### Parse next_snapshot from LLM Response (line ~3350)
```python
next_snapshot = advice.get('next_snapshot')
logging.info(f"Parsed Advice: ... NextSnapshot={next_snapshot}s")
```

#### Store Override Globally (line ~3381)
```python
global NEXT_SNAPSHOT_OVERRIDE
if next_snapshot and isinstance(next_snapshot, (int, float)) and next_snapshot > 0:
    NEXT_SNAPSHOT_OVERRIDE = int(next_snapshot)
    logging.info(f"🕐 LLM requested next snapshot in {NEXT_SNAPSHOT_OVERRIDE}s (overriding schedule)")
else:
    NEXT_SNAPSHOT_OVERRIDE = None
    logging.debug("No next_snapshot override from LLM - using schedule")
```

#### Modified get_current_interval() (line ~6387)
```python
def get_current_interval():
    """Get interval_seconds with LLM override priority.
    
    Priority order:
    1. LLM-requested override (dynamic based on market conditions)
    2. Time-based schedule (interval_schedule)
    3. Fallback default (interval_seconds)
    """
    global INTERVAL_SCHEDULE, INTERVAL_SECONDS, NEXT_SNAPSHOT_OVERRIDE
    
    # Priority 1: LLM-requested override
    if NEXT_SNAPSHOT_OVERRIDE is not None:
        logging.debug(f"Using LLM-requested override: {NEXT_SNAPSHOT_OVERRIDE}s")
        return NEXT_SNAPSHOT_OVERRIDE
    
    # Priority 2 & 3: Schedule or default (existing logic)
    ...
```

#### Clear Override After Use (line ~6523)
```python
# Clear the LLM override after using it (it only applies to the NEXT screenshot)
global NEXT_SNAPSHOT_OVERRIDE
if NEXT_SNAPSHOT_OVERRIDE is not None:
    logging.debug(f"Clearing NEXT_SNAPSHOT_OVERRIDE ({NEXT_SNAPSHOT_OVERRIDE}s) - was used for this screenshot")
    NEXT_SNAPSHOT_OVERRIDE = None
```

#### Clear on Immediate Analysis (line ~6461)
```python
if FORCE_IMMEDIATE_ANALYSIS:
    FORCE_IMMEDIATE_ANALYSIS = False
    
    # Clear any LLM snapshot override since we're taking an immediate screenshot
    NEXT_SNAPSHOT_OVERRIDE = None
```

#### Added to Global Declarations (line ~6451)
```python
global ... NEXT_SNAPSHOT_OVERRIDE
```

## How It Works

### Normal Flow
```
1. Screenshot taken → LLM analyzes
2. LLM returns: {"action": "hold", "next_snapshot": 60, ...}
3. System stores: NEXT_SNAPSHOT_OVERRIDE = 60
4. Scheduler uses 60s for NEXT screenshot (instead of schedule)
5. After screenshot taken, override is cleared
6. System returns to using schedule for subsequent screenshots
```

### Example Scenarios

#### Fast Setup Developing
```
LLM sees: Price approaching key level, strong momentum
LLM returns: {"action": "hold", "next_snapshot": 15, ...}
System: Takes next screenshot in 15 seconds (fast monitoring)
```

#### Slow/Choppy Market
```
LLM sees: No structure, two-way chop, no clear setup
LLM returns: {"action": "hold", "next_snapshot": 180, ...}
System: Takes next screenshot in 3 minutes (reduces API costs)
```

#### Position Discrepancy Detected
```
Trade monitor detects position closed
System: FORCE_IMMEDIATE_ANALYSIS = True
Scheduler: Clears NEXT_SNAPSHOT_OVERRIDE, takes immediate screenshot
System: LLM provides fresh analysis with accurate position state
```

## Priority Order

The system determines screenshot intervals in this priority:

1. **FORCE_IMMEDIATE_ANALYSIS** (highest priority)
   - Position discrepancy detected
   - Takes screenshot within ~1 second
   - Clears any LLM override

2. **NEXT_SNAPSHOT_OVERRIDE** (LLM-controlled)
   - LLM's requested interval from previous response
   - Applies to NEXT screenshot only
   - Cleared after use

3. **INTERVAL_SCHEDULE** (time-based)
   - Configured schedule (e.g., "09:30-16:00=30,18:00-23:59=300")
   - Different intervals for different times

4. **INTERVAL_SECONDS** (default fallback)
   - Used when no schedule or override present

## Benefits

### 1. Adaptive Responsiveness
- Fast monitoring during critical setups (10-20s)
- Reduced frequency during quiet periods (60-300s)

### 2. Cost Optimization
- Fewer API calls during slow/choppy markets
- More calls only when needed

### 3. Context-Aware Timing
- LLM understands market pace better than fixed schedule
- Can adjust based on volatility, time of day, structure clarity

### 4. No Configuration Changes
- Works with existing interval_schedule
- Override is temporary (one screenshot only)
- Graceful fallback if LLM doesn't provide next_snapshot

## Log Indicators

### LLM Requests Override
```
Parsed Advice: Action=hold, ... NextSnapshot=20s
🕐 LLM requested next snapshot in 20s (overriding schedule)
```

### Scheduler Uses Override
```
Current interval: 20s (0.3 minutes)  # Instead of configured 45s
Using LLM-requested override: 20s
```

### Override Cleared
```
Clearing NEXT_SNAPSHOT_OVERRIDE (20s) - was used for this screenshot
```

### No Override (Normal Schedule)
```
No next_snapshot override from LLM - using schedule
Current interval: 45s (0.8 minutes)
```

## Edge Cases Handled

1. **Invalid Values**: If next_snapshot is null, 0, negative, or non-numeric → ignored
2. **Position Discrepancy**: Override cleared when immediate analysis triggered
3. **One-Time Use**: Override automatically cleared after being used once
4. **Missing Field**: System gracefully falls back to schedule if next_snapshot not in response

## Configuration

No new config.ini settings required. The feature works with existing:
- `interval_seconds` - Default interval (fallback)
- `interval_schedule` - Time-based schedule (overridden by LLM when provided)

## Testing

### Verify LLM Control
1. Check logs for "🕐 LLM requested next snapshot in Xs"
2. Verify next screenshot uses that timing
3. Confirm override is cleared after use

### Verify Fallback
1. LLM response without next_snapshot → uses schedule
2. LLM response with invalid next_snapshot → uses schedule

### Verify Priority
1. Position discrepancy + LLM override → immediate analysis wins
2. LLM override + schedule → LLM override wins
3. No override + schedule → schedule wins

## Status

✅ **IMPLEMENTATION COMPLETE**
- All code changes made
- No linter errors
- Fully integrated with existing scheduling system
- Backwards compatible (works if next_snapshot not provided)

---

**Implementation Date:** December 1, 2025
**Modified Files:** 
- screenshot_uploader.py (main implementation)
- no_position_prompt.txt (already updated by user)
**Lines Modified:** ~50 lines across 6 locations
**Testing Status:** Code complete, ready for live trading validation


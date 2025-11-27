# Prompt Formatting and Escaping Guide

## Overview

The ESTrader system uses external `.txt` files for LLM prompts with variable substitution. To ensure robust handling of special characters (curly braces, quotes, etc.) in replacement values, the system implements safe formatting with automatic escaping.

## How It Works

### 1. Prompt Template Files

Prompts are stored in `.txt` files with placeholder variables:

- `no_position_prompt.txt` - For identifying new trade entries
- `position_prompt.txt` - For managing existing positions
- `position_variables.txt` - Documentation of all available variables

### 2. Variable Placeholders

Variables use single curly braces in the template:
```
{Context}
{Symbol}
{position_type}
{size}
{Reason}
```

### 3. JSON Format Specification

When the prompt includes JSON structure examples for the LLM, use **double braces** to escape them:

```
Your response MUST be valid JSON:
{{
    "action": "buy" | "sell" | "hold",
    "entry_price": number,
    "reasoning": "text"
}}
```

The double braces `{{` and `}}` will be converted to single braces `{` and `}` in the final output.

## Safe Formatting Implementation

### Functions

#### `escape_format_string(text)`
Escapes curly braces in replacement values to prevent format string issues.

**Input:**
```python
text = '{"price": 6000, "volume": 1000}'
```

**Output:**
```python
'{{"price": 6000, "volume": 1000}}'
```

#### `safe_format_prompt(prompt_template, **kwargs)`
Safely formats a prompt by:
1. Escaping all replacement values
2. Calling `.format()` with escaped values
3. Handling errors gracefully with detailed logging

### Example Usage

```python
# Load prompt template
prompt_template = load_prompt_from_config('no_position_prompt.txt')

# Format with variables (automatically escaped)
formatted_prompt = safe_format_prompt(
    prompt_template,
    symbol="ES",
    Context='Market data: {"price": 6000, "trend": "up"}',
    LLM_Context='Previous observation: "sweep detected"'
)
```

## Special Characters Handling

### Curly Braces `{ }`

**Problem:** Curly braces in replacement values conflict with Python's `.format()` syntax.

**Solution:** All replacement values are automatically escaped:
- `{` → `{{`
- `}` → `}}`

**Example:**
```python
# Replacement value contains JSON
context = '{"support": 5990, "resistance": 6010}'

# After escaping and formatting
# Result: Market data: {{"support": 5990, "resistance": 6010}}
```

### Quotes `" '`

**Handling:** Quotes in replacement values are passed through as-is. No escaping needed.

**Example:**
```python
reason = 'Entry signal: "sweep and reclaim" detected'
# Result: Entry signal: "sweep and reclaim" detected
```

### Numeric Values

**Handling:** Numeric types are converted to strings automatically.

**Example:**
```python
safe_format_prompt(template, size=3, entry_price=6000.25, pnl=-125.50)
# Result: Size: 3, Entry: 6000.25, P&L: -125.5
```

### None Values

**Handling:** `None` values are converted to empty strings.

**Example:**
```python
safe_format_prompt(template, stop_loss=None)
# Result: Stop Loss: 
```

## Common Scenarios

### Scenario 1: Market Data with JSON

**Template:**
```
Trading {symbol}.

Market Context:
{Context}

Respond in JSON format:
{{
    "action": "buy" | "sell" | "hold"
}}
```

**Variables:**
```python
symbol = "ES"
context = """Current Price: 6000.25
Key Levels: {"support": 5990, "resistance": 6010}"""
```

**Result:**
```
Trading ES.

Market Context:
Current Price: 6000.25
Key Levels: {{"support": 5990, "resistance": 6010}}

Respond in JSON format:
{
    "action": "buy" | "sell" | "hold"
}
```

### Scenario 2: Position Management with Details

**Template:**
```
Managing {position_type} position.
Size: {size} contracts
Entry: {average_price}
Current P&L: {unrealized_pnl}

Original Reason: {Reason}
```

**Variables:**
```python
position_type = "long"
size = 3
average_price = 6000.25
unrealized_pnl = 125.50
reason = 'Sweep of 5995 -> reclaim pattern with delta +2500'
```

**Result:**
```
Managing long position.
Size: 3 contracts
Entry: 6000.25
Current P&L: 125.5

Original Reason: Sweep of 5995 -> reclaim pattern with delta +2500
```

## Error Handling

### Missing Placeholder

If a placeholder in the template doesn't have a corresponding value:

```python
# Template has {Context} but we don't provide it
safe_format_prompt(template, symbol="ES")

# Logs error:
# ERROR: Missing placeholder in prompt template: 'Context'
# Available keys: ['symbol']
# Raises KeyError
```

### Invalid Template Syntax

If the template has unmatched braces:

```python
# Invalid template
template = "Trading {symbol but missing closing brace"

# Logs error and raises exception
```

## Best Practices

### 1. Always Use safe_format_prompt()

✅ **Good:**
```python
prompt = safe_format_prompt(template, symbol="ES", Context=market_data)
```

❌ **Bad:**
```python
prompt = template.format(symbol="ES", Context=market_data)  # Unsafe!
```

### 2. Document All Variables

Keep `position_variables.txt` updated with:
- Variable name
- Description
- Format/type
- Example value

### 3. Test with Real Data

When modifying prompts, test with actual market data that may contain:
- JSON structures
- Curly braces
- Quotes
- Special characters

### 4. Use Double Braces in Templates

For literal braces in prompt (like JSON examples), always use double braces:

```
{{
    "field": "value"
}}
```

## Debugging Tips

### Enable Detailed Logging

Check the logs for formatting errors:
```
logs/YYYYMMDD.txt
```

Look for lines containing:
- "Missing placeholder in prompt template"
- "Error formatting prompt"

### Verify Template Syntax

Before deployment, verify your template has:
1. Matching placeholder names in template and code
2. Double braces for literal JSON examples
3. No unmatched single braces

### Test Locally

Use the test pattern:
```python
# Test your prompt
prompt = load_prompt_from_config('your_prompt.txt')
result = safe_format_prompt(
    prompt,
    symbol="TEST",
    Context='{"test": "data"}',
    # ... other variables
)
print(result)
```

## Summary

✅ **Automatic escaping** of special characters in replacement values  
✅ **Safe handling** of JSON, quotes, and braces  
✅ **Error reporting** with detailed logging  
✅ **Backward compatible** with inline prompts  
✅ **Hot-reloadable** via config reload  

The safe formatting system ensures that complex market data, JSON structures, and special characters in prompts are handled correctly without manual escaping.


# LLM Testing Utility

This utility allows you to test and compare different LLM models by sending the same prompt and screenshot to different APIs and saving their responses for comparison.

## Setup

### 1. Configure the Test

Edit the configuration variables at the top of `test_llm.py`:

```python
# API Configuration
API_KEY = "your-api-key-here"
API_URL = "https://api.openai.com/v1/chat/completions"

# Model Configuration (single or comma-separated list)
MODEL = "gpt-4o-mini"  # Single model
# MODEL = "gpt-4o-mini,gpt-4o,gpt-5.1"  # Multiple models

# Test Configuration
TIMES_TO_RUN = 1  # Number of times to run each model
DELAY_SECONDS = 2  # Delay between runs (in seconds)

# File Locations
TEXT_FILE_PATH = "testing/prompt.txt"
SCREENSHOT_PATH = "screenshots/screenshot_20251126_202500.png"
```

### 2. Prepare Your Files

**Create your prompt:**
- Edit `testing/prompt.txt` with your prompt text
- Or create a new text file and update `TEXT_FILE_PATH`

**Add your screenshot:**
- Place a screenshot in the `screenshots/` folder
- Update `SCREENSHOT_PATH` to point to it
- Or use an existing screenshot from your trading session

### 3. Run the Test

```bash
cd C:\Users\Maurice\ESTrader
python testing/test_llm.py
```

## Output

### Text Files

Results are saved to `testing/responses/YYYYMMDD_hhmmss.txt` with the following format:

```
model-name-here
screenshot-filename.png
================================================================================
PROMPT SENT TO MODEL:
================================================================================

[Your full prompt text here]

================================================================================
RESPONSE FROM MODEL:
================================================================================

[Full LLM response here]
```

### CSV Log

All test results are automatically logged to `testing/results.csv` with the following columns:

| Column | Description |
|--------|-------------|
| `timestamp` | When the test was run (YYYY-MM-DD HH:MM:SS) |
| `model` | Model name (e.g., gpt-4o-mini, gpt-5.1) |
| `duration_seconds` | Response time in seconds |
| `action` | Parsed action from LLM (buy/sell/hold/close/adjust) |
| `entry_price` | Entry price from LLM response |
| `price_target` | Target price from LLM response |
| `stop_loss` | Stop loss price from LLM response |
| `confidence` | Confidence level (0-100) |
| `reasoning` | First 200 characters of reasoning |

**Example CSV row:**
```csv
2025-11-26 20:58:29,gpt-4o-mini,3.557,hold,,,,,60,"Current market conditions show a minor gap up and price trading above both daily and intraday VWAP, suggesting bullish bias. However, the presence of potential resistance at 6030.00-6032.50..."
```

This makes it easy to:
- Compare performance across models
- Track response times
- Analyze model recommendations
- Import into Excel/Google Sheets for analysis

### Console Summary

After running multiple tests, you'll see a summary like this:

```
================================================================================
✅ ALL TESTS COMPLETE
================================================================================
Total tests run: 6

gpt-4o-mini:
  ✅ Successful: 3/3
  ⏱️  Avg time: 3.245s (min: 3.120s, max: 3.450s)

gpt-4o:
  ✅ Successful: 3/3
  ⏱️  Avg time: 5.123s (min: 4.980s, max: 5.290s)

📊 Results logged to: testing/results.csv
================================================================================
```

This gives you an instant comparison of:
- Success rate for each model
- Average response time
- Min/max response times (helps identify outliers)

## Comparing Models

To compare different models:

1. **Test OpenAI GPT-4o:**
   ```python
   MODEL = "gpt-4o"
   API_URL = "https://api.openai.com/v1/chat/completions"
   API_KEY = "your-openai-key"
   ```

2. **Test OpenAI GPT-4o-mini:**
   ```python
   MODEL = "gpt-4o-mini"
   API_URL = "https://api.openai.com/v1/chat/completions"
   API_KEY = "your-openai-key"
   ```

3. **Test OpenAI GPT-5 (Preview):**
   ```python
   MODEL = "gpt-5.1"
   API_URL = "https://api.openai.com/v1/chat/completions"
   API_KEY = "your-openai-key"
   ```
   *Note: GPT-5+ models automatically use `max_completion_tokens` instead of `max_tokens`*

4. **Test Anthropic Claude:**
   ```python
   MODEL = "claude-3-5-sonnet-20241022"
   API_URL = "https://api.anthropic.com/v1/messages"
   API_KEY = "your-anthropic-key"
   ```
   *Note: Claude uses a different API format - you may need to modify the request payload*

5. **Test Google Gemini:**
   ```python
   MODEL = "gemini-1.5-pro-vision"
   API_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro-vision:generateContent"
   API_KEY = "your-google-key"
   ```
   *Note: Gemini uses a different API format - you may need to modify the request payload*

## Tips

- **Keep the same screenshot and prompt** when testing multiple models for fair comparison
- **Use multiple runs** to test consistency - does the model give the same answer every time?
- **Add delays between runs** to avoid rate limiting (especially important for API limits)
- **Test multiple models** at once using comma-separated MODEL list
- **Check response times** - the script shows average, min, and max times for each model
- **Compare JSON parsing** - see which models consistently return valid JSON
- **Analyze reasoning quality** - compare the depth and accuracy of analysis
- **Test edge cases** - choppy markets, ranging markets, strong trends
- **Use CSV for analysis** - import results.csv into Excel to compare models side-by-side

## Example Workflows

### Single Model, Single Run
```python
MODEL = "gpt-4o-mini"
TIMES_TO_RUN = 1
DELAY_SECONDS = 2
```
```bash
python testing/test_llm.py
```

### Single Model, Multiple Runs (Test Consistency)
```python
MODEL = "gpt-4o-mini"
TIMES_TO_RUN = 5  # Run 5 times to see consistency
DELAY_SECONDS = 3  # 3 second delay between runs
```
```bash
python testing/test_llm.py
```
This will run the same model 5 times and log all results to CSV. Useful for measuring:
- Response time consistency
- Decision consistency (does it always pick the same action?)
- Confidence variation

### Multiple Models, Single Run (Compare Models)
```python
MODEL = "gpt-4o-mini,gpt-4o,gpt-5.1"
TIMES_TO_RUN = 1
DELAY_SECONDS = 2
```
```bash
python testing/test_llm.py
```
This will run each model once and compare their responses in the CSV.

### Multiple Models, Multiple Runs (Comprehensive Test)
```python
MODEL = "gpt-4o-mini,gpt-4o"
TIMES_TO_RUN = 3  # Run each model 3 times
DELAY_SECONDS = 2
```
```bash
python testing/test_llm.py
```
Total tests: 6 (2 models × 3 runs each)

### Fast Batch Testing (No Delay)
```python
MODEL = "gpt-4o-mini,gpt-4o-mini,gpt-4o-mini"  # Same model 3 times
TIMES_TO_RUN = 1
DELAY_SECONDS = 0  # No delay
```
This runs the same model back-to-back as fast as possible.

## Notes

- This script is completely independent from the main trading system
- All configuration is hard-coded in the script
- No dependency on `config.ini`
- Safe to test without affecting live trading
- Responses are timestamped and never overwritten
- **Automatic API Compatibility**: GPT-5+ models automatically use `max_completion_tokens` parameter instead of `max_tokens`


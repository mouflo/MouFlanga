# Cloudflare Bypass Solution - Current Status

## Overview
The Japscan scraper is blocked by Cloudflare's "Just a moment..." challenge on individual chapter pages (URLs like `/manga/dandadan/247/`). We're testing a wait-and-reload approach to bypass it.

## Current Architecture

```
Request Flow (Current):
├─ Manga list (/) → ✓ Works (543 found)
├─ Chapter list (/manga/x) → ✗ 403 Blocked by Cloudflare
└─ Chapter pages (/manga/x/chapters/y) → ✗ 403 Blocked by Cloudflare

Cloudflare Protection Stack:
├─ headless=True detection → 403 Forbidden
├─ Playwright webdriver detection → 403 Forbidden
└─ "Just a moment..." challenge → temporary block
```

## Solution Approach: Wait & Reload

**Hypothesis**: Cloudflare returns initial challenge that resolves after waiting and reloading.

**Implementation**: Three phases

### Phase 1: Diagnostic Test (In Progress)
- **File**: `probe_wait_cloudflare.py` ✓ Created & Pushed
- **Status**: Awaiting server auto-deployment and execution
- **Location on server**: `/opt/mouflanga/probe_wait_cloudflare.py`
- **How to run**: 
  ```bash
  cd /opt/mouflanga && xvfb-run -a python3 probe_wait_cloudflare.py
  ```
- **What it does**:
  1. Launches browser with `headless=False` via Xvfb
  2. Adds anti-detection JavaScript
  3. Loads chapter page
  4. Detects "just a moment" challenge
  5. Waits 10 seconds
  6. Reloads page
  7. Checks if challenge is gone
  8. Lists images if successful

### Phase 2: Integration (Ready to Deploy)
- **File**: `japscan_scraper_cloudflare_handler.py` ✓ Created & Pushed
- **Status**: Waiting for Phase 1 success to activate
- **What to do**: Once `probe_wait_cloudflare.py` succeeds:
  1. Copy the enhanced `_fetch_with_browser()` method from this file
  2. Replace the method in `japscan_scraper.py`
  3. Update browser launch to use `headless=False + Xvfb`
  4. Re-test full pipeline

### Phase 3: Production Deployment
- Update Flask web interface to wrap calls with `xvfb-run`
- Test complete workflow: list mangas → get chapters → download pages
- Create CBR files successfully

## Files Committed

| File | Status | Purpose |
|------|--------|---------|
| `probe_wait_cloudflare.py` | Pushed | Diagnostic test for wait-and-reload approach |
| `TEST_CLOUDFLARE_WAIT.md` | Pushed | Testing guide with expected outputs |
| `japscan_scraper_cloudflare_handler.py` | Pushed | Enhanced method ready for integration |
| `setup-xvfb.sh` | Already on server | Xvfb + dependencies installer |

## Infrastructure Status

- ✓ Xvfb installed on server
- ✓ playwright-stealth installed
- ✓ Chromium binaries present
- ✓ All dependencies satisfied
- ⏳ Waiting for `probe_wait_cloudflare.py` test results

## What Happens Next

### If Test SUCCEEDS ✓
1. We have the solution!
2. Integrate `japscan_scraper_cloudflare_handler.py` into main scraper
3. Update browser launch strategy in `_get_browser()` to use headless=False + Xvfb
4. Re-run `test_scraper.py` to validate full pipeline
5. Update Flask interface if needed
6. Mark as solved

### If Test FAILS ✗
1. Wait-and-reload doesn't work
2. Try alternative: `undetected-chromium`
3. Create `probe_undetected.py` for testing
4. Consider: proxy services, API discovery, or manual approaches

## Testing Timeline

- **T+0**: Server auto-deploys `probe_wait_cloudflare.py` (within ~5 minutes)
- **T+5m**: You can run the test manually or wait for cron
- **T+15m**: Results should be available

## How to Monitor Server Auto-Deployment

The server checks GitHub every few minutes via cron. You can:
1. Wait for auto-deployment (passive)
2. Manually pull: `cd /opt/mouflanga && git pull origin main`
3. Run tests immediately after pull

## Current Blockers

None - all diagnostic infrastructure is in place. Just need to execute the test.

## Notes

- All probe files use `xvfb-run -a python3 <script>` to provide virtual X display
- The wait-and-reload logic is non-blocking (simple `time.sleep(10)`)
- Fallback to `requests` if Playwright fails (maintains robustness)
- Browser launch options tuned for headless Linux environment

## Commands for Server Execution

```bash
# Monitor auto-deployment
watch -n 5 'ls -la /opt/mouflanga/ | grep probe_wait'

# Pull latest
cd /opt/mouflanga && git pull origin main

# Run diagnostic test
xvfb-run -a python3 probe_wait_cloudflare.py

# View test logs
cat /opt/mouflanga/logs/*.log  # if logging configured

# Full pipeline test (after integration)
xvfb-run -a python3 test_scraper.py
```

## Decision Tree

```
Test Result?
├─ SUCCESS (images found, no CF challenge)
│  └─ Integrate cloudflare_handler into scraper
│     └─ Update _get_browser() for headless=False + Xvfb
│        └─ Re-test full pipeline
│           └─ READY FOR PRODUCTION ✓
│
└─ FAILURE (CF challenge persists)
   └─ Try undetected-chromium approach
      ├─ Create probe_undetected.py
      ├─ Test: pip install undetected-chromedriver
      └─ If works: integrate, else seek alternatives
```

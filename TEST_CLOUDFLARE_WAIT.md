# Test: Cloudflare Challenge Resolution via Waiting

## Hypothesis
Cloudflare returns an initial "Just a moment..." challenge that resolves after waiting ~10 seconds and reloading the page.

## Prerequisites
- Xvfb installed: `apt-get install xvfb`
- playwright-stealth installed: `pip install --break-system-packages playwright-stealth`
- Verify with: `playwright install chromium` (if needed)

## Run the Test

On your Proxmox server:

```bash
cd /opt/mouflanga
xvfb-run -a python3 probe_wait_cloudflare.py
```

## Expected Output

### If SUCCESS ✓
```
✓ SUCCÈS ! Page chargée sans Cloudflare !
✓ Titre: ...
✓ Images trouvées: N
```

This means the wait-and-reload approach bypasses Cloudflare. Next step: integrate into `japscan_scraper.py`

### If FAILURE ✗
```
✗ Cloudflare toujours présent
```

Cloudflare challenge persists even after waiting. Next step: try `undetected-chromium` or other approaches.

## What This Test Does

1. Launches Playwright with `headless=False` via Xvfb (simulates real browser)
2. Adds anti-detection JavaScript to hide webdriver
3. Loads chapter page: `https://www.japscan.foo/manga/dandadan/247/`
4. Detects "just a moment" in HTML (Cloudflare challenge marker)
5. Waits 10 seconds with countdown
6. Calls `page.reload()` to fetch fresh response
7. Checks if Cloudflare challenge is gone
8. Lists found images if successful

## Files Involved
- **probe_wait_cloudflare.py**: The diagnostic probe
- **setup-xvfb.sh**: Installation script (already run)
- **japscan_scraper.py**: Main scraper (will integrate solution here after validation)

## Next Steps After Test

- **If SUCCESS**: 
  1. Update `japscan_scraper.py` to use wait-and-reload approach in `_fetch_with_browser()`
  2. Test full pipeline: manga list → chapters → pages
  3. Update Flask web interface to support xvfb-run wrapper

- **If FAILURE**:
  1. Install undetected-chromium: `pip install undetected-chromedriver`
  2. Create `probe_undetected.py` to test specialized approach
  3. Evaluate other solutions (proxy services, API discovery)

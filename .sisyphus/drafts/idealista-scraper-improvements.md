# Draft: Idealista Scraper Improvements

## Requirements (confirmed)
- Improve the Idealista scraper to handle safety mechanisms
- Current issue: blocking after first page
- Need to bypass or handle anti-scraping measures

## Technical Decisions
- **Goal**: Robust solution for reliable multi-page scraping
- **Anti-Blocking Focus**: Enhanced stealth + session management (all areas: fingerprint evasion, human-like behavior, session persistence)
- **CAPTCHA Handling**: Detect and alert for manual intervention (no auto-solving)
- **Performance Priority**: Maximum reliability over speed (slower is OK)
- **Retry Strategy**: Exponential backoff with configurable limits
- **Session Persistence**: No persistence between runs (fresh sessions each time)
- **Stealth Enhancements**: Comprehensive improvements across fingerprint evasion, human-like behavior, and session management

## Research Findings
- Main scraper file: `src/house_search/scrapers/idealista.py`
- Debug file exists: `debug_idealista_p2.py` - shows CAPTCHA blocking on page 2
- Test file: `tests/test_scrapers_idealista.py`
- Base scraper class: `src/house_search/scrapers/base.py`
- Also have Fotocasa scraper for comparison

**Key Discoveries:**
1. **Current Implementation**: Uses Playwright with stealth plugin, Firefox browser, random delays (3-6s between pages)
2. **Blocking Evidence**: Saved HTML shows CAPTCHA page with message "Please enable JS and disable any ad blocker"
3. **Anti-Bot Detection**: Idealista uses `captcha-delivery.com` service
4. **Current Approach**: 
   - Uses `playwright_stealth` plugin
   - Random user agents (4 Firefox variants)
   - Spanish locale/timezone
   - Accepts cookies automatically (multiple selector attempts)
   - Clicks "next page" button with scroll into view
   - Waits for DOM content loaded
   - 3-6 second random delays between pages

**Explore Agent Analysis Summary:**
- **Strengths**: Good browser-based approach with stealth, human-like interactions
- **Gaps**: No retry logic, no exponential backoff, no proxy/IP rotation
- **Error Handling**: Basic try/except around parsing, but no recovery from CAPTCHA blocks
- **Safety Mechanisms**: User-agent rotation, stealth plugin, cookie handling, random delays
- **Recommendations**: Add retry/backoff, enhance anti-blocking measures, improve observability

## Open Questions
1. What specific safety mechanisms is Idealista using? **ANSWER: CAPTCHA/anti-bot service (captcha-delivery.com)**
2. What is the current scraping approach (libraries, headers, delays)? **ANSWER: Playwright + stealth, 3-6s delays, Firefox**
3. What error patterns are observed when blocked? **ANSWER: CAPTCHA page instead of listings**
4. Are there any existing retry mechanisms? **ANSWER: None found in current code**
5. What's the pagination strategy? **ANSWER: Click "next page" button, wait for DOM load**
6. Test infrastructure? **ANSWER: pytest with pytest-asyncio, test files exist, asyncio_mode=auto**

## Test Infrastructure Assessment (Partial)
- **Framework**: pytest with pytest-asyncio (from pyproject.toml)
- **Configuration**: asyncio_mode = auto
- **Test files**: test_scrapers_idealista.py, test_scrapers_fotocasa.py, test_models.py, test_storage.py
- **Fixtures**: idealista_article.html fixture exists
- **CI/CD**: No .github/workflows found
- **Coverage**: No coverage config found

## Scope Boundaries
- INCLUDE: Idealista-specific anti-scraping bypass techniques
- INCLUDE: Robust error handling and retry logic
- INCLUDE: Rate limiting and request spacing
- INCLUDE: Session management and cookie handling
- EXCLUDE: Other real estate platforms (Fotocasa, etc.)
- EXCLUDE: Database/storage changes (unless required for session persistence)
- EXCLUDE: Frontend/UI changes
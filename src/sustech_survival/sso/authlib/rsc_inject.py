"""
RSC Cookie Injection — load saved session cookies into any browser context.
This bridges the gap: Playwright logs in once, Hermes browser uses the cookies.
"""
import json, sys, os
from pathlib import Path

def load_rsc_session(cookie_path: str = None) -> list:
    """Load RSC session cookies from JSON file. Returns list of cookie dicts."""
    if cookie_path is None:
        cookie_path = Path(__file__).parent.parent.parent / "rsc" / "session.json"
    with open(cookie_path) as f:
        data = json.load(f)
    # Handle both {"name": "val"} and {"name": {"value": "val", ...}} formats
    cookies = []
    for name, val in data.items():
        if isinstance(val, dict):
            cookies.append({"name": name, **val})
        else:
            cookies.append({"name": name, "value": val})
    return cookies

def inject_into_context(ctx, cookies: list):
    """Inject cookies into a Playwright browser context."""
    ctx.add_cookies(cookies)

def test_with_playwright(cookie_path: str = None) -> bool:
    """Test: load cookies, inject into fresh Playwright browser, verify RSC is authenticated."""
    from playwright.sync_api import sync_playwright

    cookies = load_rsc_session(cookie_path)
    print(f"Loaded {len(cookies)} RSC cookies", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        page = ctx.new_page()
        page.goto("https://pubs.rsc.org/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        url = page.url
        title = page.title()
        body_text = page.inner_text("body")

        print(f"URL: {url}", flush=True)
        print(f"Title: {title}", flush=True)

        if "Log in or register" in body_text:
            print("❌ NOT logged in — cookie injection failed", flush=True)
            browser.close()
            return False
        else:
            print("✅ Logged in — cookie injection works!", flush=True)

            # Test search
            page.goto(
                "https://pubs.rsc.org/en/search?q=machine+learning+catalysis",
                timeout=30000,
                wait_until="networkidle"
            )
            print(f"Search URL: {page.url}", flush=True)

            # Extract article links
            links = page.locator("a[href*='/en/content/articlehtml/']").all()
            print(f"Article links: {len(links)}", flush=True)
            for link in links[:5]:
                try:
                    href = link.get_attribute("href")
                    text = link.inner_text()[:80].strip()
                    print(f"  {text} -> {href}", flush=True)
                except:
                    pass

            browser.close()
            return True


if __name__ == "__main__":
    success = test_with_playwright()
    sys.exit(0 if success else 1)
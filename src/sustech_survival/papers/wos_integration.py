import sys, json, time
from pathlib import Path
sys.path.insert(0, "src")
# Resolve skill root from this file's location (independent of install path).
# Works from any install location (editable install, wheel, source tree, etc.).
skill_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
from playwright.sync_api import sync_playwright

SESSION_FILE = f"{skill_dir}/bb/wos_session.json"

# Singleton Playwright/browser — keep alive across calls
browser_singleton = None
ctx_singleton = None


def get_browser():
    """Get or create the singleton Playwright browser."""
    global _browser, _ctx
    if _browser is None:
        _browser = sync_playwright().start()
        _ctx = _browser.chromium.launch(headless=True).new_context()
    return _ctx


def login_to_wos():
    """
    Full login to Web of Science via SUSTech CARSI Shibboleth.
    Uses a persistent browser session. Call once at start of session.
    """
    ctx = get_browser()
    page = ctx.new_page()
    page.set_default_timeout(30000)

    from sustech_survival.sso import Authorizer
    _auth = Authorizer()
    username, password = _auth.read_creds()

    page.goto("https://www.webofscience.com/wos/woscc/summary/basic",
               wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(8000)
    print(f"[WoS] Global site: {page.url[:60]}")

    try:
        page.get_by_text("Accept all").click(timeout=3000)
    except:
        pass

    page.locator('mat-select[aria-label="Institution"]').click(timeout=5000)
    page.wait_for_timeout(2000)
    page.get_by_text("CHINA CERNET Federation", exact=True).click(timeout=5000)
    page.wait_for_timeout(1000)
    page.get_by_text("Go to institution").click(timeout=5000)
    print("[WoS] Selected institution")

    try:
        page.wait_for_url("**ds.carsi.edu.cn**", timeout=20000)
    except Exception:
        try:
            page.wait_for_url("**carsi.edu.cn**", timeout=10000)
        except Exception:
            print(f"[WoS] ⚠ Not redirected to CARSI: {page.url[:60]}")

    page.wait_for_timeout(3000)
    print(f"[WoS] CARSI WAYF: {page.url[:60]}")

    page.evaluate("""
        () => {
            const form = document.querySelector('form');
            if (!form) return;
            const inp = form.querySelector('input[name="entityID"]');
            if (inp) inp.value = 'https://idp.sustech.edu.cn/idp/shibboleth';
            form.submit();
        }
    """)
    print("[WoS] Injected SUSTech entityID")

    try:
        page.wait_for_url("**cas.sustech.edu.cn**", timeout=30000)
    except Exception:
        if "webofknowledge" in page.url or "webofscience" in page.url:
            print("[WoS] → Already authenticated, session active")
            save_session(ctx)
            return True
        print(f"[WoS] ⚠ Not at CAS: {page.url[:60]}")
        return False

    page.wait_for_timeout(3000)
    print(f"[WoS] SUSTech CAS: {page.url[:60]}")

    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.evaluate("""
        () => {
            document.querySelectorAll('form').forEach(f => {
                if (f.querySelector('input[name=username]')) f.submit();
            });
        }
    """)
    page.wait_for_timeout(8000)

    if "idp.sustech.edu.cn" in page.url:
        page.locator('input[name="_eventId_proceed"]').click()
        page.wait_for_timeout(6000)

    print(f"[WoS] ✅ Logged in: {page.url[:70]}")
    save_session(ctx)
    page.close()
    return True


def search_wos(query, max_results=10):
    """
    Search WoS (Chinese mirror) and return list of {title, doi, url}.
    Must call login_to_wos() first.
    """
    ctx = get_browser()
    page = ctx.new_page()
    page.set_default_timeout(30000)

    page.goto("https://webofscience.clarivate.cn/wos/woscc/basic-search/basic",
               wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(8000)
    print(f"[WoS Search] URL: {page.url[:60]}")

    # Find search input
    search_input = None
    for inp in page.locator("input").all():
        try:
            if inp.is_visible():
                ph = inp.get_attribute("placeholder") or ""
                label = inp.get_attribute("aria-label") or ""
                if "search" in (ph + label).lower():
                    search_input = inp
                    print(f"[WoS Search] Found: ph={ph!r} label={label!r}")
                    break
        except:
            pass

    if not search_input:
        print("[WoS Search] ❌ No search input visible!")
        page.screenshot(path="/tmp/wos_search_fail.png")
        page.close()
        return []

    search_input.fill(query)
    page.keyboard.press("Enter")
    page.wait_for_timeout(8000)
    print(f"[WoS Search] Results: {page.url[:80]}")

    results = []
    for a in page.locator("a[href*='/article/']").all():
        try:
            href = a.get_attribute("href")
            title = a.inner_text().strip()
            if href and title:
                doi = href.split("/article/")[-1].split("?")[0]
                results.append({"title": title, "doi": doi, "url": href})
        except:
            pass

    print(f"[WoS Search] {len(results)} results")
    page.close()
    return results[:max_results]


def get_article_html(doi):
    """
    Get full HTML of a WoS article page. Must call login_to_wos() first.
    """
    ctx = get_browser()
    page = ctx.new_page()
    page.set_default_timeout(20000)
    url = f"https://webofscience.clarivate.cn/wos/woscc/article/{doi}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    html = page.content()
    page.close()
    return html


def save_session(ctx):
    cookies = {c['name']: c['value'] for c in ctx.cookies()}
    with open(SESSION_FILE, "w") as f:
        json.dump(cookies, f)


if __name__ == "__main__":
    print("=== Testing WoS login + search ===\n")
    ok = login_to_wos()
    if ok:
        print("\n--- Testing search ---")
        results = search_wos("electrochromic polymer flexible", max_results=5)
        for r in results:
            print(f"  {r['title'][:65]}")

        if results:
            print(f"\n--- Fetching article HTML for {results[0]['doi']} ---")
            html = get_article_html(results[0]['doi'])
            print(f"HTML: {len(html)} chars")
            has_paywall = any(x in html.lower() for x in ["subscribe", "access denied", "not authorized"])
            print(f"Paywall: {has_paywall}")
            if not has_paywall:
                open("/tmp/wos_article_sample.html", "w").write(html)
                print("Saved to /tmp/wos_article_sample.html")
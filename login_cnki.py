"""
login_cnki.py — Playwright login to CNKI, save cookies for fetch_cnki_paper.
Usage: python login_cnki.py [--headless]
"""
import sys, json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from sustech_survival.sso.authlib.cnki import CNKIAuth

def login_cnki_save(headless=True):
    auth = CNKIAuth()
    ok = auth.login(headless=headless)
    if not ok:
        print("❌ CNKI login failed")
        return False
    
    # Get cookies from browser context
    cookies = auth.browser.contexts[0].cookies()
    
    # Save to cookies dir
    cookie_dir = Path(__file__).parent / "src" / "cookies"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    with open(cookie_dir / "cnki_cookies.json", "w") as f:
        json.dump(cookies, f)
    
    print(f"✅ CNKI login saved {len(cookies)} cookies")
    print("Domains:", set(c.get("domain","") for c in cookies))
    auth.browser.close()
    return True

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--visible", action="store_true")
    args = p.parse_args()
    
    headless = not args.visible
    login_cnki_save(headless=headless)
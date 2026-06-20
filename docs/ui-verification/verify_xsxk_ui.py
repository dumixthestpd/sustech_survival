"""
verify_xsxk_ui.py — Login + UI verification workflow for TIS Xsxk (选课).

Run this anytime you need to verify the live UI matches the code claims
in selectcourse/SKILL.md and references/tis-api.md. Workflow:

  1. Login via CAS (using saved credentials)
  2. Open /Xsxk/query/1 in headless Chromium
  3. Wait for the xkgzszList Vue data to populate (it loads via AJAX after page load)
  4. Take a full-page screenshot
  5. Extract the live xkgzszList + xkgzszOne from the page's Vue app
  6. Print a human-readable round summary
  7. Save everything to docs/ui-verification/<timestamp>/

Why this matters: HTML/JS source tells you what the code CAN do. Only the
live UI tells you what it IS doing for your account, right now. Round
names, current sfkx/sfkt flags, available xkfsdm codes — all of these
change per semester and per user. Re-verify after every semester boundary.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add skill to path
SKILL_ROOT = Path("/Users/dumix/.openclaw/workspace/skills/sustech_survival")
sys.path.insert(0, str(SKILL_ROOT / "src"))

from playwright.sync_api import sync_playwright

TIS_BASE = "https://tis.sustech.edu.cn"
OUT_ROOT = SKILL_ROOT / "docs" / "ui-verification"


def login_and_capture(*, headless: bool = True, dry_run_only: bool = False) -> dict:
    """Login to TIS, navigate to /Xsxk/query/1, capture the live UI state.

    Returns a dict with:
      - screenshot_path: Path to the PNG
      - html_path: Path to the saved page HTML
      - rounds: list of {xkfsdm, xkfsmc, lcmc, sfkx, sfkt, xkms, ksrq, jsrq, xkqzsj}
      - current: the active round (matches xkgzszOne)
      - captured_at: ISO timestamp

    The TIS-internal login (tis.sustech.edu.cn/cas/login) requires a CAPTCHA,
    but the original SUSTech CAS (cas.sustech.edu.cn/cas/login) doesn't —
    we use that to get cookies via the requests-based _tis_login flow, then
    inject them into the Playwright browser context.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read credentials
    from sustech_survival.sso import Authorizer
    creds = Authorizer(skill_dir=str(SKILL_ROOT))
    username, password = creds.read_creds()
    print(f"[1/6] Logging in as {username} (via CAS, no CAPTCHA)...")

    # Step 1: get cookies via the existing _tis_login flow (no CAPTCHA path)
    from sustech_survival.selectcourse.selectcourse import _tis_login
    sess = _tis_login(username, password)
    cookies_requests = []
    for c in sess.cookies:
        cookies_requests.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain or "tis.sustech.edu.cn",
            "path": c.path or "/",
            "httpOnly": bool(getattr(c, "_rest", {}).get("HttpOnly", False))
                         if hasattr(c, "_rest") else False,
            "secure": bool(getattr(c, "secure", False)),
            "expires": int(c.expires) if c.expires and c.expires > 0
                       else int(time.time()) + 86400,
        })
    # Filter to only tis.sustech.edu.cn cookies (cas cookies may not transfer)
    tis_cookies = [c for c in cookies_requests
                   if "tis.sustech.edu.cn" in (c.get("domain") or "")]
    print(f"  ✓ Got {len(tis_cookies)} TIS cookies from CAS")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            locale="zh-CN",
        )
        # Inject TIS cookies BEFORE navigating so /Xsxk/query/1 sees the session
        if tis_cookies:
            context.add_cookies(tis_cookies)
            print(f"  ✓ Injected cookies into browser context")
        page = context.new_page()

        # Save cookies for reuse
        cookies_path = out_dir / "cookies.json"
        cookies_path.write_text(json.dumps(cookies_requests, indent=2, ensure_ascii=False))

        # Navigate to the course selection page
        print("[2/6] Loading /Xsxk/query/1 ...")
        resp = page.goto(f"{TIS_BASE}/Xsxk/query/1", timeout=30000, wait_until="domcontentloaded")
        # If we landed on /session/invalid, the cookies didn't transfer
        if "/session/invalid" in page.url:
            print(f"  ⚠ Landed on {page.url} — cookies may have expired")
            print("    Falling back to: re-login with CAPTCHA (headed mode required)")
            return {"error": "session_invalid", "url": page.url}
        page.wait_for_load_state("networkidle", timeout=30000)
        print(f"  ✓ Loaded {page.url} (HTTP {resp.status})")

        # Wait for Vue to populate xkgzszList. The data loads via AJAX after
        # the page mounts. Look for the green banner element to appear.
        try:
            page.wait_for_selector("text=轮次", timeout=15000)
            print("  ✓ Banner rendered")
        except Exception:
            # Might be between semesters — banner might not render
            print("  ⚠ '轮次' banner not found within 15s; page may be empty")
            print("    (likely no active selection round)")

        # Give the AJAX-loaded data another second to settle
        page.wait_for_timeout(2000)

        # Screenshot — full page
        print("[3/6] Taking screenshot...")
        screenshot_path = out_dir / "xsxk-query-1.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"  ✓ {screenshot_path}")

        # Save HTML for archival
        print("[4/6] Saving HTML...")
        html = page.content()
        html_path = out_dir / "xsxk-query-1.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"  ✓ {html_path} ({len(html)} chars)")

        # Extract the Vue data by walking window/iframe
        # The xsxk app is a Vue 2 instance — look for the data in the rendered DOM
        print("[5/6] Extracting live round data...")
        rounds, current = _extract_rounds_from_dom(page, html)

        # Save JSON
        live_data = {
            "captured_at": datetime.now().isoformat(),
            "username": username,
            "current_url": page.url,
            "current_round": current,
            "all_rounds": rounds,
            "tabs_visible": _extract_tabs(page, html),
        }
        data_path = out_dir / "live-data.json"
        data_path.write_text(json.dumps(live_data, indent=2, ensure_ascii=False))
        print(f"  ✓ {data_path}")

        # Print summary
        print("[6/6] Summary:")
        _print_summary(live_data)

        browser.close()

        return {
            "screenshot_path": str(screenshot_path),
            "html_path": str(html_path),
            "data_path": str(data_path),
            "rounds": rounds,
            "current": current,
            "captured_at": live_data["captured_at"],
        }


def _extract_rounds_from_dom(page, html: str) -> tuple[list, dict]:
    """Pull xkgzszList and xkgzszOne from the rendered Vue app.

    Two strategies, used together:
    1. Read Vue data directly via page.evaluate (gives the raw config)
    2. Parse the rendered iview tabs (gives the human-readable labels
       with actual computed labels like 已选 / 通识必修选课)
    """
    rounds = []
    current = {}

    # Strategy 1: read Vue data via page.evaluate (raw config)
    vue_data = page.evaluate("""
        () => {
            const root = document.getElementById('app') || document.querySelector('[data-v-]');
            if (!root || !root.__vue__) return null;
            const vm = root.__vue__;
            let target = vm;
            while (target) {
                if (target.xkgzszList || target.xkgzszOne) {
                    return {
                        xkgzszList: target.xkgzszList || [],
                        xkgzszOne: target.xkgzszOne || {},
                        queryform: target.queryform || {},
                    };
                }
                target = target.$parent;
            }
            return null;
        }
    """)

    if vue_data:
        rounds_enriched = vue_data.get("xkgzszList") or []
        current = vue_data.get("xkgzszOne") or {}
        print(f"  ✓ Pulled Vue data: {len(rounds_enriched)} rounds configured")
        for r in rounds_enriched:
            rounds.append({
                "xkfsdm": r.get("xkfsdm"),
                "xkfsmc": r.get("xkfsmc"),
                "xkfsmc_en": r.get("xkfsmc_en"),
                "lcmc": r.get("lcmc"),
                "xkms": r.get("xkms"),
                "sfkx": r.get("sfkx"),
                "sfkt": r.get("sfkt"),
                "ksrq": r.get("ksrq"),
                "jsrq": r.get("jsrq"),
                "xkqzsj": r.get("xkqzsj"),
                "sfxzrl": r.get("sfxzrl"),
                "xzcxtjz": r.get("xzcxtjz"),
            })
    else:
        print("  ⚠ Could not access Vue __vue__ — falling back to DOM scrape")

    # Strategy 2: scrape the rendered iview tab labels (gives labels even
    # if Vue access fails). iview compiles <Tab-Pane> to <div class="ivu-tabs-tab">.
    rendered_tabs = _extract_tabs(page, html)
    if rendered_tabs:
        print(f"  ✓ Rendered tabs: {[t['label'] for t in rendered_tabs]}")
        # If we have round config from Vue, also annotate with the
        # computed label (what users actually see)
        if rounds:
            # Heuristic: skip 已选/购物车 tabs in the config-round mapping
            for t in rendered_tabs:
                if t["name"] in ("yixuan", "gouwuche"):
                    continue
                # Find matching round by xkfsdm
                match = next((r for r in rounds if r.get("xkfsdm") == t["name"]), None)
                if match:
                    match["tab_label_rendered"] = t["label"]

    return rounds, current


def _extract_tabs(page, html: str) -> list:
    """List all visible tabs.

    iview (Vue component library) compiles <Tab-Pane> into rendered DOM as
    <div class="ivu-tabs-tab"> with the label text inside. The original
    <Tab-Pane :label="..."> is in the script source, not the rendered HTML.
    """
    tabs = []

    # Strategy A: read live from the page DOM (most reliable)
    try:
        rendered = page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.ivu-tabs-tab');
                return Array.from(tabs).map(t => {
                    const text = (t.textContent || '').replace(/\\s+/g, ' ').trim();
                    // name is stored on the parent Tab-Pane via __vue__ if mounted
                    return {label: text, name: null};
                });
            }
        """)
        # Also try to read names from the rendered panes
        pane_names = page.evaluate("""
            () => {
                const panes = document.querySelectorAll('.ivu-tabs-tabpane');
                return Array.from(panes).map(p => {
                    // Try data-name, or grab from Vue
                    return p.getAttribute('data-name') || null;
                });
            }
        """)
        # Tabs and panes are paired; first two are usually yixuan + gouwuche
        for i, t in enumerate(rendered):
            name = None
            # Common naming: yixuan (Tab 0), gouwuche (Tab 1), then xkfsdm codes
            if i == 0:
                name = "yixuan"
            elif i == 1 and "购物车" in t["label"]:
                name = "gouwuche"
            tabs.append({"name": name, "label": t["label"]})
        if tabs:
            return tabs
    except Exception:
        pass

    # Strategy B: regex over the raw HTML (fallback)
    for m in re.finditer(
        r'<Tab-Pane[^>]+:name="([^"]+)"[^>]*:label="([^"]+)"',
        html,
    ):
        name = m.group(1)
        label_html = m.group(2)
        sub = re.search(r"i18[kn]?\(['\"]([^'\"]+)['\"]", label_html)
        label = sub.group(1) if sub else label_html
        tabs.append({"name": name, "label": label})
    return tabs


def _print_summary(data: dict) -> None:
    """Human-readable summary of the captured live state."""
    print()
    print(f"  Captured:   {data['captured_at']}")
    print(f"  URL:        {data['current_url']}")
    print()
    print(f"  Visible tabs ({len(data['tabs_visible'])}):")
    for t in data["tabs_visible"]:
        name = t['name'] or '(unnamed)'
        print(f"    [{name:15}]  {t['label']}")
    print()
    print(f"  Active round (xkgzszOne):")
    cur = data["current_round"]
    if cur:
        print(f"    lcmc:    {cur.get('lcmc', '—')}")
        print(f"    xkfsdm:  {cur.get('xkfsdm', '—')}")
        print(f"    xkms:    {cur.get('xkms', '—')}  (1=直选/first-come)")
        print(f"    sfkx:    {cur.get('sfkx', '—')}  (1=可选 / 0=不可选)")
        print(f"    sfkt:    {cur.get('sfkt', '—')}  (1=可退 / 0=不可退)")
        print(f"    ksrq:    {cur.get('ksrq', '—')}")
        print(f"    jsrq:    {cur.get('jsrq', '—')}")
    else:
        print("    (no active round — likely between semesters)")
    print()
    print(f"  All configured rounds ({len(data['all_rounds'])}):")
    for r in data["all_rounds"]:
        sfkx = r.get("sfkx", "?")
        sfkt = r.get("sfkt", "?")
        xkms = r.get("xkms", "?")
        markers = []
        if sfkx == "1":
            markers.append("✓可选")
        elif sfkx == "0":
            markers.append("✗不可选")
        if sfkt == "1":
            markers.append("✓可退")
        elif sfkt == "0":
            markers.append("✗不可退")
        if xkms == "1":
            markers.append("直选")
        flags = "  ".join(markers) if markers else ""
        print(f"    [{r.get('xkfsdm', '?'):15}]  {r.get('xkfsmc', '?'):20}  "
              f"{r.get('lcmc', ''):20}  {flags}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true",
                    help="Run with visible browser (for CAPTCHA solving)")
    args = ap.parse_args()

    result = login_and_capture(headless=not args.headed)
    if "error" in result:
        sys.exit(1)
    print()
    print(f"✓ Artifacts in: {Path(result['screenshot_path']).parent}")


if __name__ == "__main__":
    main()
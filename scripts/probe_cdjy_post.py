#!/usr/bin/env python3
"""
probe_cdjy_post.py — Capture the EXACT wire payload that TIS /cdjy/addChangDiJieYongShenQing/1
sends when the user clicks "保存" (save) or "提交" (submit) on the venue-borrowing form.

Strategy:
  1. Use Playwright to log into TIS CAS with the existing saved session.
  2. Open /cdjy/query/1/sq.
  3. Click the "add" button to open the create drawer.
  4. Fill the form with a minimal-but-valid row (uses the in-page dropdowns).
  5. Click 保存 (save) — and use page.route() to INTERCEPT + ABORT the POST
     so the real application is NOT created. We log the body that was about
     to be sent. This is the exact wire payload.

This is the safe way to capture the wire shape per iron law #1
(dry_run default; explicit confirmation for live writes).

Output: writes the captured JSON to /tmp/cdjy_post_payload.json
and dumps the route URL + headers to /tmp/cdjy_post_meta.json.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

# Add sustech_survival src to path
sys.path.insert(0, str(Path.home() / ".openclaw/code/sustech_survival/src"))

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from sustech_survival.sso import TISAuth


CAPTURED_BODY = None
CAPTURED_META = None


def intercept_save(route, request):
    """Playwright route handler: capture the save POST and ABORT (no real create)."""
    global CAPTURED_BODY, CAPTURED_META
    if "addChangDiJieYongShenQing" in request.url or "updateChangDiJieYongShenQing" in request.url:
        # Try to parse the body
        try:
            body = request.post_data
            try:
                parsed = json.loads(body) if body else None
            except (ValueError, TypeError):
                parsed = None
        except Exception as e:
            body = None
            parsed = f"<parse error: {e}>"

        CAPTURED_BODY = parsed if parsed is not None else body
        CAPTURED_META = {
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "body_raw": body,
        }
        print(f"\n=== CAPTURED POST to {request.url} ===")
        print(f"Content-Type: {request.headers.get('content-type')}")
        print(f"Body length: {len(body) if body else 0}")
        if parsed is not None:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        else:
            print(body[:500] if body else "<empty>")

        # Fulfill with a fake success to prevent real create
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"code": 200, "content": "captured-and-aborted-by-probe"}),
        )
    else:
        route.continue_()


def main():
    print("=== Authenticating to TIS ===")
    auth = TISAuth()
    ok, reason = auth.ensure()
    if not ok:
        print(f"❌ Auth failed: {reason}")
        sys.exit(1)
    print("✅ Auth OK")

    # Convert requests session cookies to Playwright format
    cookies_list = []
    for k, v in auth.cookies.items():
        cookies_list.append({
            "name": k,
            "value": v,
            "domain": ".sustech.edu.cn",
            "path": "/",
        })
    print(f"Loaded {len(cookies_list)} cookies")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ua = auth.requests_session.headers.get("User-Agent") or ""
        ctx = browser.new_context(
            user_agent=str(ua),
            viewport={"width": 1440, "height": 900},
        )
        ctx.add_cookies(cookies_list)
        page = ctx.new_page()

        # Set up the route interceptor
        page.route("**/cdjy/addChangDiJieYongShenQing*", intercept_save)
        # Also intercept the PUT (update) endpoint
        page.route("**/cdjy/updateChangDiJieYongShenQingPut*", intercept_save)

        print("\n=== Navigating to /cdjy/query/1/sq ===")
        try:
            page.goto(
                "https://tis.sustech.edu.cn/cdjy/query/1/sq",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except PWTimeout as e:
            print(f"goto timeout: {e}")
            sys.exit(1)
        print(f"URL: {page.url}")
        if "login" in page.url or "cas.sustech" in page.url:
            print("❌ Redirected to login — session dead")
            sys.exit(1)
        print(f"Title: {page.title()}")
        # Wait for the Vue app to mount
        page.wait_for_timeout(3000)

        # Find and click the "add" button
        # Look for buttons with text 申请 / 添加 / 新建
        print("\n=== Looking for the 'add application' button ===")
        add_btn = None
        for txt in ["申请", "添加", "新建", "新增", "Add", "Apply"]:
            try:
                btn = page.get_by_role("button", name=txt).first
                if btn.is_visible(timeout=2000):
                    add_btn = btn
                    print(f"Found button: {txt!r}")
                    break
            except (PWTimeout, Exception):
                continue
        if not add_btn:
            # try a generic CSS selector
            try:
                add_btn = page.locator("button:has-text('申请')").first
            except Exception:
                pass
        if not add_btn:
            print("❌ Could not find the add button")
            print("\nAvailable buttons on page:")
            buttons = page.locator("button").all()
            for i, b in enumerate(buttons[:30]):
                try:
                    txt = b.inner_text(timeout=500).strip()
                    if txt:
                        print(f"  [{i}] {txt!r}")
                except Exception:
                    pass
            sys.exit(1)

        print(f"Clicking add button...")
        add_btn.click()

        # The openAddDrawer function uses $nextTick + an async POST + localStorage.
        # Wait for the drawer to actually open and the form to be populated.
        # localStorage 'user' must exist (we'll inject it if not).
        print("\n=== Ensuring localStorage 'user' is populated ===")
        ls_user = page.evaluate("() => localStorage.getItem('user')")
        print(f"  localStorage user: {ls_user[:200] if ls_user else 'NONE'}")
        if not ls_user or 'xm' not in ls_user:
            # Inject a minimal user object based on the credentials
            # The i18n flag PKGL.CDJY.SQRXZSFJY determines if syr/xq are populated
            # We force them to be set by injecting directly into cdjyform after
            # openAddDrawer runs.
            page.evaluate("""
                () => {
                    const user = {
                        xm: '段斯宸',
                        xm_en: 'Sicheng Duan',
                        yhdm: '12413021',
                        bmmc: '测试单位',
                        bmmc_en: 'Test Dept',
                        bmdm: '000',
                        lxdh: '13800138000',
                    };
                    localStorage.setItem('user', JSON.stringify(user));
                }
            """)
            print("  Injected test user into localStorage")
        # Wait for the drawer to open (addDrawer.cdjyshow = true)
        print("  Waiting for drawer to open...")
        for i in range(20):
            drawer_open = page.evaluate("""
                () => {
                    const walk = (el, depth) => {
                        if (depth > 30) return null;
                        if (el.__vue__ && el.__vue__.addDrawer) {
                            return el.__vue__.addDrawer;
                        }
                        for (const c of el.children || []) {
                            const r = walk(c, depth+1);
                            if (r) return r;
                        }
                        return null;
                    };
                    const ad = walk(document.documentElement, 0);
                    return ad ? {cdjyshow: ad.cdjyshow, id: ad.id, flag: ad.flag} : null;
                }
            """)
            if drawer_open and drawer_open.get('cdjyshow'):
                print(f"  Drawer open: {drawer_open}")
                break
            time.sleep(0.5)
        else:
            print("  ❌ Drawer did not open in 10s")
        page.wait_for_timeout(2000)
        page.wait_for_timeout(2000)

        # Now we should be in the drawer. Find the "add row" button (添加借用时间 / 新增)
        print("\n=== Looking for the 'add row' button ===")
        for txt in ["添加", "新增", "添加借用", "添加场地", "Add Row"]:
            try:
                btn = page.get_by_role("button", name=txt).nth(0)
                if btn.is_visible(timeout=1000):
                    btn.click()
                    print(f"Clicked: {txt!r}")
                    page.wait_for_timeout(1000)
                    break
            except (PWTimeout, Exception):
                continue

        # Now we need to fill the form. The simplest is to fill
        # the first row with: date, weekday, periods, headcount, purpose
        # This is complex because the form has date pickers, selects, etc.
        # Let me take a simpler approach: just trigger the saveOrSubmit
        # function directly via JS evaluation. The form has client-side
        # validation that will fail, but we can see the JSON.stringify
        # call.
        # The drawer is now open — wait for the actual form to mount
        # (it appears as a Drawer element with a Form-Item child)
        page.wait_for_timeout(3000)
        # Walk the Vue tree to find a component that has cdjyform with
        # __user-derived fields filled in (sqr != "")
        print("\n=== Looking for the actual cdjy Vue instance with form filled in ===")
        result = page.evaluate("""
            () => {
                // Walk the entire DOM and collect all Vue instances
                const all = [];
                const walk = (el, depth) => {
                    if (depth > 50) return;
                    if (el.__vue__) {
                        const v = el.__vue__;
                        all.push({el, v, depth, tag: v.$options && (v.$options._componentTag || v.$options.name)});
                    }
                    for (const c of el.children || []) walk(c, depth+1);
                };
                walk(document.documentElement, 0);
                // Find the one with saveOrSubmit AND __user-derived fields filled
                for (const {v, tag} of all) {
                    if (v.saveOrSubmit && v.cdjyform && v.cdjyform.sqr) {
                        return {
                            tag,
                            has_saveOrSubmit: typeof v.saveOrSubmit === 'function',
                            has_addjxx: typeof v.addjxx === 'function',
                            has_copyData: typeof v.copyData === 'function',
                            sqr: v.cdjyform.sqr,
                            syr: v.cdjyform.syr,
                            xn: v.cdjyform.xn,
                            xq: v.cdjyform.xq,
                            cdjymxlist_len: (v.cdjyform.cdjymxlist||[]).length,
                        };
                    }
                }
                // If none with sqr filled, return what we have
                const candidates = all
                    .filter(x => x.v.saveOrSubmit)
                    .map(x => ({
                        tag: x.tag,
                        sqr: x.v.cdjyform ? x.v.cdjyform.sqr : 'N/A',
                        xn: x.v.cdjyform ? x.v.cdjyform.xn : 'N/A',
                    }));
                return {error: 'no instance with sqr filled', candidates, total_vue: all.length};
            }
        """)
        print(f"Discovery: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # Now try to fill the form via the right instance and call saveOrSubmit
        print("\n=== Calling saveOrSubmit('bc') via the right Vue instance ===")
        try:
            page.evaluate("""
                () => {
                    const walk = (el, depth) => {
                        if (depth > 50) return null;
                        if (el.__vue__ && el.__vue__.saveOrSubmit && el.__vue__.cdjyform) {
                            return el.__vue__;
                        }
                        for (const c of el.children || []) {
                            const r = walk(c, depth+1);
                            if (r) return r;
                        }
                        return null;
                    };
                    const inst = walk(document.documentElement, 0);
                    if (!inst) {
                        window.__CDJY_PROBE_ERROR__ = 'no instance found';
                        return;
                    }
                    // Force 用户 fields that may have been skipped due to i18n check
                    inst.cdjyform.syr = inst.cdjyform.sqr || '段斯宸';
                    inst.cdjyform.syrdh = inst.cdjyform.syrdh || '13800138000';
                    inst.cdjyform.sqrdw = inst.cdjyform.sqrdw || '测试单位';
                    inst.cdjyform.sqrdwdh = inst.cdjyform.sqrdwdh || '000';
                    // Add a row if there isn't one
                    if (inst.cdjyform.cdjymxlist.length === 0) {
                        inst.addjxx();
                    }
                    // Fill minimal data on the first row
                    const r = inst.cdjyform.cdjymxlist[0];
                    if (r) {
                        r.ksrq = '2026-07-01';
                        r.jsrq = '2026-07-01';
                        r.xqj = '3';
                        r.ksjc = '3';
                        r.jsjc = '4';
                        r.rs = '30';
                        r.jyyy = '测试借用';
                        r.cddm = 'YJ-101';
                        r.cdmc = '一教101';
                        r.zc = '1';
                        r.qsjsz = '1';
                        r.sfsysb = '1';
                        r.zysfkyd = '2';
                        r.sfjtjs = '2';
                        r.jyxq = inst.cdjyform.xn + inst.cdjyform.xq;
                        r.xn = inst.cdjyform.xn;
                        r.xq = inst.cdjyform.xq;
                        r.xiaoqu = '1';
                    }
                    // Fill form-level fields
                    inst.cdjyform.rs = 30;
                    inst.cdjyform.jyyy = '测试借用';
                    inst.cdjyform.xiaoqu = '1';
                    // Build a fake rlsjd to bypass the date check
                    inst.rlsjd = [{ksrq: '2026-06-01', jsrq: '2026-08-31'}];
                    // BYPASS form validation: replace validate() with always-true Promise
                    const cdjyformRef = inst.$refs.cdjyform;
                    if (cdjyformRef) {
                        cdjyformRef.validate = function() { return Promise.resolve(true); };
                    }
                    // Hook $.ajax to log the request details
                    if (window.$ && !window.__CDJY_AJAX_HOOKED__) {
                        const origAjax = window.$.ajax;
                        window.$.ajax = function(opts) {
                            window.__CDJY_LAST_AJAX__ = {
                                url: opts.url,
                                type: opts.type,
                                contentType: opts.contentType,
                                data: opts.data,
                                data_preview: typeof opts.data === 'string' ? opts.data.substring(0, 500) : 'non-string',
                            };
                            return origAjax.apply(this, arguments);
                        };
                        window.__CDJY_AJAX_HOOKED__ = true;
                    }
                    // Now call saveOrSubmit directly
                    window.__CDJY_PROBE_RESULT__ = 'calling saveOrSubmit';
                    try {
                        const r = inst.saveOrSubmit('bc');
                        window.__CDJY_PROBE_RESULT__ = 'returned: ' + (r ? typeof r : 'null');
                        if (r && r.catch) {
                            r.catch(e => {
                                window.__CDJY_PROBE_REJECT__ = e && e.content ? e.content : JSON.stringify(e);
                            });
                        }
                    } catch (e) {
                        window.__CDJY_PROBE_RESULT__ = 'EXCEPTION: ' + e;
                    }
                }
            """)
            # Check the JS-side error log
            result = page.evaluate("() => ({result: window.__CDJY_PROBE_RESULT__, error: window.__CDJY_PROBE_ERROR__, reject: window.__CDJY_PROBE_REJECT__})")
            print(f"JS-side result: {result}")

            # Wait for the AJAX to fire
            print("\n=== Waiting for AJAX to fire... ===")
            for i in range(15):
                page.wait_for_timeout(1000)
                check = page.evaluate("""
                    () => ({
                        captured: window.__CDJY_CAPTURED__,
                        lastAjax: window.__CDJY_LAST_AJAX__,
                        addDrawer: (() => {
                            const walk = (el, depth) => {
                                if (depth > 30) return null;
                                if (el.__vue__ && el.__vue__.addDrawer) return el.__vue__.addDrawer;
                                for (const c of el.children || []) {
                                    const r = walk(c, depth+1);
                                    if (r) return r;
                                }
                                return null;
                            };
                            const ad = walk(document.documentElement, 0);
                            return ad ? {loading: ad.loading, flag: ad.flag} : null;
                        })(),
                    })
                """)
                print(f'  t={i+1}s: {check}')
                if check.get('captured'):
                    break

        except Exception as e:
            print(f"evaluate error: {e}")

        # Now try the actual save click
        print("\n=== Looking for 提交 (submit) button ===")
        for txt in ["提交", "Submit", "提交申请", "保存"]:
            try:
                btn = page.get_by_role("button", name=txt).first
                if btn.is_visible(timeout=2000):
                    print(f"Found button: {txt!r}")
                    try:
                        # First do 'bc' (save) — we already captured this
                        # Then do 'tj' (submit) — we'll capture that
                        page.evaluate("""
                            () => {
                                const walk = (el, depth) => {
                                    if (depth > 50) return null;
                                    if (el.__vue__ && el.__vue__.saveOrSubmit && el.__vue__.cdjyform) {
                                        return el.__vue__;
                                    }
                                    for (const c of el.children || []) {
                                        const r = walk(c, depth+1);
                                        if (r) return r;
                                    }
                                    return null;
                                };
                                const inst = walk(document.documentElement, 0);
                                if (!inst) return;
                                inst.saveOrSubmit('tj');
                            }
                        """)
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"JS direct call failed: {e}, trying click")
                        btn.click()
                        page.wait_for_timeout(3000)
                    break
            except (PWTimeout, Exception):
                continue

        # Wait for the intercept to fire
        page.wait_for_timeout(5000)

        # DEBUG: dump all Vue instances we can find
        if CAPTURED_BODY is None:
            print("\n=== DEBUG: walking Vue tree to find saveOrSubmit ===")
            debug = page.evaluate("""
                () => {
                    const all = [];
                    const seen = new Set();
                    const walk = (el, depth) => {
                        if (depth > 30) return;
                        if (el.__vue__) {
                            const v = el.__vue__;
                            const sig = v.$options && v.$options._componentTag;
                            const methods = Object.keys(v.$options.methods || {});
                            const has = methods.filter(m => ['saveOrSubmit', 'updateOrSubmit', 'addjxx', 'copyData', 'addDrawer', 'cdjyform'].includes(m));
                            if (has.length > 0 && !seen.has(sig)) {
                                seen.add(sig);
                                all.push({tag: sig, methods: has, has_cdjyform: !!v.cdjyform, has_addDrawer: !!v.addDrawer});
                            }
                        }
                        for (const c of el.children || []) walk(c, depth+1);
                    };
                    walk(document.documentElement, 0);
                    return all;
                }
            """)
            print(f"Vue components with cdjy methods: {json.dumps(debug, indent=2)}")
            page.screenshot(path="/tmp/cdjy_debug.png")
            print("Screenshot saved to /tmp/cdjy_debug.png")

        if CAPTURED_BODY is not None:
            out = Path("/tmp/cdjy_post_payload.json")
            out.write_text(json.dumps(CAPTURED_BODY, ensure_ascii=False, indent=2))
            print(f"\n✅ Captured payload written to {out}")
            meta_out = Path("/tmp/cdjy_post_meta.json")
            meta_out.write_text(json.dumps(CAPTURED_META, ensure_ascii=False, indent=2))
            print(f"✅ Meta written to {meta_out}")
        else:
            print("\n❌ No POST captured. Possible reasons:")
            print("  - The save button didn't fire saveOrSubmit (validation blocked)")
            print("  - The route handler didn't match (URL pattern)")
            print("  - The form has additional required fields we didn't fill")

        browser.close()


if __name__ == "__main__":
    main()

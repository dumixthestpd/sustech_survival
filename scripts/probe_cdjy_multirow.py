#!/usr/bin/env python3
"""
probe_cdjy_multirow.py — Multi-row + data() block + room-search probe.

Probes three things:
  1. The Vue component's `data()` block (curr_ksrq, curr_jsrq, kgztlist, xnxw, etc.)
  2. A MULTI-ROW form submission (2+ cdjymxlist entries, different weekdays/weeks)
  3. The room-search modal (POST /component/queryDiDian) and its response

All POSTs are intercepted — no real applications created.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".openclaw/code/sustech_survival/src"))

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from sustech_survival.sso import TISAuth

CAPTURED_BODY = None
CAPTURED_META = None
CAPTURED_QUERY_RESPONSES = []


def intercept_cdjy(route, request):
    global CAPTURED_BODY, CAPTURED_META
    if "addChangDiJieYongShenQing" in request.url:
        body = request.post_data
        try:
            parsed = json.loads(body) if body else None
        except (ValueError, TypeError):
            parsed = None
        CAPTURED_BODY = parsed
        CAPTURED_META = {
            "url": request.url, "method": request.method,
            "headers": dict(request.headers), "body_raw": body,
        }
        print(f"\n=== CAPTURED POST to {request.url} ===")
        print(json.dumps(parsed, ensure_ascii=False, indent=2) if parsed else body)
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"code": 200, "content": "probe-intercept"}),
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

    cookies_list = []
    for k, v in auth.cookies.items():
        cookies_list.append({
            "name": k, "value": v,
            "domain": ".sustech.edu.cn", "path": "/",
        })
    print(f"Loaded {len(cookies_list)} cookies")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ua = auth.requests_session.headers.get("User-Agent") or ""
        ctx = browser.new_context(
            user_agent=str(ua), viewport={"width": 1440, "height": 900},
        )
        ctx.add_cookies(cookies_list)
        page = ctx.new_page()

        page.route("**/cdjy/addChangDiJieYongShenQing*", intercept_cdjy)
        page.route("**/cdjy/updateChangDiJieYongShenQingPut*", intercept_cdjy)

        print("\n=== Navigating to /cdjy/query/1/sq ===")
        try:
            page.goto(
                "https://tis.sustech.edu.cn/cdjy/query/1/sq",
                wait_until="domcontentloaded", timeout=60000,
            )
        except PWTimeout:
            print("goto timeout"); sys.exit(1)
        print(f"URL: {page.url}")
        if "login" in page.url or "cas.sustech" in page.url:
            print("❌ Redirected to login — session dead"); sys.exit(1)
        page.wait_for_timeout(3000)

        # Inject localStorage user
        page.evaluate("""() => {
            const user = {
                xm: '段斯宸', xm_en: 'Sicheng Duan',
                yhdm: '12413021', bmmc: '测试单位',
                bmmc_en: 'Test Dept', bmdm: '000', lxdh: '13800138000',
            };
            localStorage.setItem('user', JSON.stringify(user));
        }""")
        print("✅ localStorage user injected")

        # Find and click add button
        add_btn = None
        for txt in ["申请", "添加", "新建", "新增"]:
            try:
                btn = page.get_by_role("button", name=txt).first
                if btn.is_visible(timeout=2000):
                    add_btn = btn; print(f"Found add button: {txt!r}"); break
            except (PWTimeout, Exception):
                continue
        if not add_btn:
            print("❌ Could not find add button"); sys.exit(1)

        add_btn.click()
        page.wait_for_timeout(3000)

        # Wait for drawer to open
        for i in range(20):
            drawer_open = page.evaluate("""() => {
                const walk = (el, d) => { if(d>30)return null;
                    if(el.__vue__ && el.__vue__.addDrawer) return el.__vue__.addDrawer;
                    for(const c of el.children||[]) {const r=walk(c,d+1); if(r) return r;}
                    return null;
                };
                const ad = walk(document.documentElement, 0);
                return ad ? {cdjyshow: ad.cdjyshow, id: ad.id, flag: ad.flag} : null;
            }""")
            if drawer_open and drawer_open.get('cdjyshow'):
                print(f"Drawer open: {drawer_open}"); break
            time.sleep(0.5)
        else:
            print("❌ Drawer did not open"); page.screenshot(path="/tmp/cdjy_drawer_fail.png"); sys.exit(1)

        page.wait_for_timeout(2000)

        # ── PHASE 1: Capture the data() block ──
        print("\n=== PHASE 1: Extracting form-level data() block ===")
        data_block = page.evaluate("""() => {
            const walk = (el, d) => { if(d>50)return null;
                if(el.__vue__ && el.__vue__.saveOrSubmit && el.__vue__.cdjyform) return el.__vue__;
                for(const c of el.children||[]) {const r=walk(c,d+1); if(r) return r;}
                return null;
            };
            const inst = walk(document.documentElement, 0);
            if (!inst) return null;

            // Grab data() reactive properties
            const d = {};
            for (const k of Object.keys(inst.$data || {})) {
                const v = inst[k];
                if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' || v === null) {
                    d[k] = v;
                }
            }
            // Also grab specific keys we know exist
            d['selectSksjShow'] = inst.selectSksjShow;
            d['curr_ksrq'] = inst.curr_ksrq;
            d['curr_jsrq'] = inst.curr_jsrq;
            d['kgztlist'] = JSON.stringify(inst.kgztlist || []);
            d['rlsjd'] = JSON.stringify(inst.rlsjd || []);
            d['cdjyformKeys'] = Object.keys(inst.cdjyform || {});
            d['xd'] = inst.xd;
            d['xnxw'] = inst.xnxw;
            d['cdjyFormValidRules'] = typeof inst.cdjyFormValidRules;

            return d;
        }""")
        print(f"data() block: {json.dumps(data_block, ensure_ascii=False, indent=2)}")

        # ── PHASE 2: Multi-row submission (2 different days) ──
        print("\n=== PHASE 2: Injecting multi-row data and calling saveOrSubmit('bc') ===")
        multirow_result = page.evaluate("""() => {
            const walk = (el, d) => { if(d>50)return null;
                if(el.__vue__ && el.__vue__.saveOrSubmit && el.__vue__.cdjyform) return el.__vue__;
                for(const c of el.children||[]) {const r=walk(c,d+1); if(r) return r;}
                return null;
            };
            const inst = walk(document.documentElement, 0);
            if (!inst) { window.__CDJY_ERROR__ = 'no inst'; return 'no inst'; }

            // Set form-level fields
            inst.cdjyform.xn = '2025-2026';
            inst.cdjyform.xq = '3';
            inst.cdjyform.sqr = '段斯宸';
            inst.cdjyform.sqr_en = 'Sicheng Duan';
            inst.cdjyform.sqrdh = '13800138000';
            inst.cdjyform.sqrzgh = '12413021';
            inst.cdjyform.sqrdw = '测试单位';
            inst.cdjyform.sqrdw_en = 'Test Dept';
            inst.cdjyform.sqrdwdh = '000';
            inst.cdjyform.syr = '段斯宸';
            inst.cdjyform.syrdh = '13800138000';
            inst.cdjyform.syrzgh = '12413021';
            inst.cdjyform.xiaoqu = '1';
            inst.cdjyform.rs = 30;
            inst.cdjyform.jyyy = '学术讲座';
            inst.cdjyform.sfsjysxtly = '';

            // Build a fake rlsjd
            inst.rlsjd = [{ksrq: '2026-06-29', jsrq: '2026-08-31'}];

            // Add TWO rows
            const addRows = (n) => {
                for (let i = 0; i < n; i++) {
                    if (inst.addjxx && typeof inst.addjxx === 'function') {
                        inst.addjxx();
                    }
                }
            };
            addRows(2);

            // Fill row 0 — Tuesday (xqj=2) week 5, period 3-4
            if (inst.cdjyform.cdjymxlist[0]) {
                const r0 = inst.cdjyform.cdjymxlist[0];
                r0.ksrq = '2026-07-01';
                r0.jsrq = '2026-07-01';
                r0.xqj = '2';
                r0.ksjc = '3';
                r0.jsjc = '4';
                r0.rs = '30';
                r0.jyyy = '学术讲座';
                r0.cddm = 'YJ-107';
                r0.cdmc = '一教107';
                r0.zc = '5';
                r0.qsjsz = '5';
                r0.sfsysb = '1';
                r0.zysfkyd = '2';
                r0.sfjtjs = '2';
                r0.jyxq = '2025-20263';
                r0.xn = '2025-2026';
                r0.xq = '3';
                r0.xiaoqu = '1';
                // Add per-row jtsjlist
                if (!r0.jtsjlist) r0.jtsjlist = [];
                r0.jtsjlist.push({xqj: '2', ksjc: '3', jsjc: '4'});
            }

            // Fill row 1 — Thursday (xqj=4) week 6, period 5-6
            if (inst.cdjyform.cdjymxlist[1]) {
                const r1 = inst.cdjyform.cdjymxlist[1];
                r1.ksrq = '2026-07-02';
                r1.jsrq = '2026-07-02';
                r1.xqj = '4';
                r1.ksjc = '5';
                r1.jsjc = '6';
                r1.rs = '30';
                r1.jyyy = '学术讲座';
                r1.cddm = 'ZH-201';
                r1.cdmc = '智华楼201';
                r1.zc = '6';
                r1.qsjsz = '6';
                r1.sfsysb = '1';
                r1.zysfkyd = '2';
                r1.sfjtjs = '2';
                r1.jyxq = '2025-20263';
                r1.xn = '2025-2026';
                r1.xq = '3';
                r1.xiaoqu = '1';
                if (!r1.jtsjlist) r1.jtsjlist = [];
                r1.jtsjlist.push({xqj: '4', ksjc: '5', jsjc: '6'});
            }

            // Compute per-row time_slot strings for the form-level jtsjlist
            const formSlots = [];
            for (const r of inst.cdjyform.cdjymxlist) {
                formSlots.push({xqj: r.xqj, ksjc: r.ksjc, jsjc: r.jsjc});
            }

            // BYPASS iview validation
            const ref = inst.$refs.cdjyform;
            if (ref) { ref.validate = function() { return Promise.resolve(true); }; }

            // Hook $.ajax
            if (window.$ && !window.__CDJY_AJAX_HOOKED__) {
                const orig = window.$.ajax;
                window.$.ajax = function(opts) {
                    window.__CDJY_PROBE_AJAX_DATA__ = opts.data;
                    window.__CDJY_PROBE_AJAX_URL__ = opts.url;
                    return orig.apply(this, arguments);
                };
                window.__CDJY_AJAX_HOOKED__ = true;
            }

            // Now call saveOrSubmit
            window.__CDJY_PROBE_START__ = Date.now();
            try {
                const r = inst.saveOrSubmit('bc');
                window.__CDJY_PROBE_RESULT__ = 'called: ' + (r && r.catch ? 'promise' : typeof r);
                if (r && r.catch) {
                    r.then(v => { window.__CDJY_PROBE_RESOLVED__ = JSON.stringify(v); });
                    r.catch(e => { window.__CDJY_PROBE_REJECTED__ = e ? (e.content || e.toString()) : 'unknown'; });
                }
            } catch (e) {
                window.__CDJY_PROBE_RESULT__ = 'EXCEPTION: ' + e;
            }
            return 'saveOrSubmit called';
        }""")
        print(f"Multi-row inject result: {multirow_result}")

        # Wait for AJAX to fire
        print("\n=== Waiting for AJAX to fire ===")
        for i in range(20):
            page.wait_for_timeout(1000)
            check = page.evaluate("""() => ({
                captured: !!window.__CDJY_CAPTURED__,
                ajaxData: window.__CDJY_PROBE_AJAX_DATA__ ? typeof window.__CDJY_PROBE_AJAX_DATA__ : null,
                result: window.__CDJY_PROBE_RESULT__,
                resolved: window.__CDJY_PROBE_RESOLVED__,
                rejected: window.__CDJY_PROBE_REJECTED__,
            })""")
            print(f'  t={i+1}s: result={check.get("result","?")} captured={check.get("captured")}')
            if CAPTURED_BODY is not None:
                break

        # ── PHASE 3: Room-search modal (queryDiDian) ──
        print("\n=== PHASE 3: Probing the room-search modal ===")
        # Set up a separate route to capture the queryDiDian response
        query_responses = []

        def intercept_query(route, request):
            if "queryDiDian" in request.url:
                print(f"\n=== INTERCEPTED queryDiDian ===")
                print(f"  Method: {request.method}")
                print(f"  Body: {request.post_data[:200] if request.post_data else '<empty>'}")
                # Continue to get the real response, but capture it
                response = route.fetch()
                body = response.text()
                query_responses.append({
                    "url": request.url,
                    "method": request.method,
                    "body": request.post_data,
                    "response_status": response.status,
                    "response_body_preview": body[:2000] if body else "<empty>",
                })
                route.fulfill(
                    status=response.status,
                    body=body,
                    content_type=response.headers.get("content-type", "application/json"),
                )
                print(f"  Response: {body[:500]}")
            else:
                route.continue_()

        page.route("**/component/queryDiDian*", intercept_query)

        # Try to open the room-search modal — look for the 选择场地 button
        print("Looking for '选择场地' / room-search trigger...")
        for txt in ["选择场地", "选择教室", "Search Room", "场地选择"]:
            try:
                btn = page.get_by_role("button", name=txt).first
                if btn.is_visible(timeout=1000):
                    print(f"Clicking: {txt!r}")
                    btn.click()
                    page.wait_for_timeout(3000)
                    break
            except (PWTimeout, Exception):
                continue

        # Also try the iView/iSelect modal trigger
        # The modal may be a dropdown or a separate dialog
        page.wait_for_timeout(3000)
        print(f"queryDiDian captures so far: {len(query_responses)}")

        # If modal opened, try searching with filters
        if query_responses:
            print("Room-search modal was triggered. Trying with filters...")
        else:
            # Try clicking the search button inside the room modal
            for txt in ["查询", "搜索", "查找"]:
                try:
                    btn = page.get_by_role("button", name=txt).first
                    if btn.is_visible(timeout=1000):
                        print(f"Clicking search: {txt!r}")
                        btn.click()
                        page.wait_for_timeout(2000)
                        break
                except (PWTimeout, Exception):
                    continue
            page.wait_for_timeout(2000)
            print(f"queryDiDian captures after search: {len(query_responses)}")

        # ── OUTPUT ──
        output = {}

        if data_block:
            output["data_block"] = data_block
            print(f"\n✅ data() block captured")

        if CAPTURED_BODY:
            output["multirow_payload"] = CAPTURED_BODY
            output["multirow_meta"] = CAPTURED_META
            out_path = Path("/tmp/cdjy_multirow_payload.json")
            out_path.write_text(json.dumps(CAPTURED_BODY, ensure_ascii=False, indent=2))
            print(f"✅ Multi-row payload written to {out_path}")

        if query_responses:
            output["query_responses"] = query_responses
            print(f"✅ {len(query_responses)} queryDiDian captures")

        out_all = Path("/tmp/cdjy_multirow_probe.json")
        out_all.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"\n✅ Full probe output to {out_all}")

        page.screenshot(path="/tmp/cdjy_multirow_probe.png")
        print("Screenshot: /tmp/cdjy_multirow_probe.png")

        browser.close()


if __name__ == "__main__":
    main()

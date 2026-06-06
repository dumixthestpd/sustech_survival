from __future__ import annotations

import json
from typing import Optional

from ...sso import TISAuth
from .semester import Season, Semester
from .evaluation import Evaluation

BASE = TISAuth.BASE_URL


class TISAuthEval(TISAuth):
    """
    TIS auth + evaluation workflow.

    Inherits all auth methods from TISAuth (login, refresh, load, session).

    Usage::

        auth = TISAuthEval().login()
        for ev in auth.evaluations(xnxq="2025-2026-2"):
            ev.load().autofill().save()
    """

    def evaluations(
        self,
        xnxq: str = "2025-2026-2",
        status: str = "all",
    ) -> list[dict]:
        """
        List evaluation tasks for a semester via REST API.

        API flow (2 steps):
          1. GET /personnelEvaluation/listObtainPersonnelEvaluationTasks
             → 3 category tasks (rwid, firstwjid, rwmc)
          2. For each category: GET /personnelEvaluation/listEcaluationRalationshipEnriry
             with wjid=<firstwjid> + rwid=<task rwid>
             → course list (kcmc, kcdm, lsjgzt, etc.)

        Args:
            xnxq:   Semester code (e.g. "2025-20262" or "2025-2026-2")
            status: "all", "pending" (lsjgzt=0), or "saved" (lsjgzt=3)

        Returns list of course dicts with keys:
            course_name, course_code, teacher, task_type, lsjgzt, status_text,
            wjid, jgwid, xnxq, rwh, questionnaire_uuid, theme_uuid, task_rwid
        """
        # Normalise xnxq: "2025-2026-2" → "2025-20262" (backend format)
        xnxq_raw = xnxq  # preserve original for storage
        if xnxq and len(xnxq) == 11 and xnxq.count("-") == 2:
            # "2025-2026-2" → indices: 0-3=year, 4="-", 5-8=year2, 9="-", 10=term
            # "2025-20262" → indices: 0-3=year, 4="-", 5-9=year2+term, 10=empty
            xnxq = f"{xnxq[:4]}-{xnxq[5:9]}{xnxq[10]}"  # "2025-2026-2" → "2025-20262"
        elif not xnxq:
            xnxq = "2025-20262"
        sess = self.session

        # Step 1: get 3 category tasks
        tasks_resp = sess.get(
            f"{BASE}/personnelEvaluation/listObtainPersonnelEvaluationTasks",
            params={"yhdm": "12413021", "rwmc": "", "sfyp": "0",
                    "pageNum": "1", "pageSize": "20"},
            timeout=15,
        )
        if tasks_resp.status_code != 200:
            raise RuntimeError(f"Task list API returned {tasks_resp.status_code}")
        tasks = tasks_resp.json()["result"]["list"]

        all_courses: list[dict] = []

        # Step 2: per-category course list
        for task in tasks:
            rwid = task["rwid"]          # category task rwid
            firstwjid = task["firstwjid"]  # wjid for course list query
            rwmc = task["rwmc"]          # e.g. "学生评价（理论类 Theoretical courses）"

            # Determine task_type from label
            if "理论" in rwmc:
                task_type = "理论类"
            elif "体育" in rwmc:
                task_type = "体育类"
            elif "实验" in rwmc or "实践" in rwmc:
                task_type = "实验实践类"
            else:
                task_type = rwmc

            courses_resp = sess.get(
                f"{BASE}/personnelEvaluation/listEcaluationRalationshipEnriry",
                params={
                    "pjrdm": "12413021",
                    "wjid": firstwjid,
                    "bpmc": "", "sfyp": "0", "xnxq": xnxq,
                    "pageNum": "1", "pageSize": "50",
                    "zc": "", "xqj": "", "jc": "", "skdd": "",
                    "kkyxdm": "", "bpssyxdm": "", "kcmc": "", "sfcxqbwj": "0",
                    "rwid": rwid,       # kept for category context; backend tolerates it
                    "lsjgzt": "",
                },
                timeout=15,
            )
            data = courses_resp.json()
            if data.get("code") != "200":
                # Skip failed categories (e.g. empty categories)
                continue

            for c in data["result"]["list"]:
                lsjgzt = c.get("lsjgzt", "0")
                # lsjgzt=2 → submitted (submitted after clicking 提交 button in browser)
                # lsjgzt=3 → saved-draft (form filled and saved, but not yet submitted)
                # lsjgzt=0 → not-yet-started
                if lsjgzt == "0":
                    status_text = "待评价"
                elif lsjgzt == "1":
                    status_text = "已放弃"
                elif lsjgzt == "2":
                    status_text = "已评价"
                elif lsjgzt == "3":
                    status_text = "已保存"
                elif lsjgzt == "4":
                    status_text = "未结课"
                elif lsjgzt == "5":
                    status_text = "已评价"
                else:
                    status_text = "未知"
                all_courses.append({
                    "course_name": c.get("kcmc", ""),
                    "course_code": c.get("kcdm", ""),
                    "teacher": c.get("bpdm", ""),      # department code = teacher dept
                    "task_type": task_type,
                    "department": c.get("yxmc", ""),    # school name
                    "class_info": c.get("bj", ""),
                    "lsjgzt": c.get("lsjgzt", "0"),
                    "deadline": c.get("jzsj", ""),
                    "status_text": status_text,
                    "xnxq": xnxq_raw,
                    "wjid": c.get("wjid", ""),
                    "jgwid": c.get("jgwid", ""),
                    "rwh": c.get("rwh", ""),
                    "questionnaire_uuid": c.get("sxz", ""),  # encrypted form id
                    "theme_uuid": "",
                    "task_rwid": rwid,
                })

        # Filter by status
        result: list[dict] = []
        for c in all_courses:
            lsjgzt = c["lsjgzt"]
            if status == "pending" and lsjgzt != "0":
                continue
            if status == "draft" and lsjgzt != "3":
                continue
            if status == "submitted" and lsjgzt not in ("2", "5"):
                continue
            result.append(c)

        return result

    def open_evaluation(self, course: dict, xnxq: str = "2025-2026-2") -> Evaluation:
        """
        Open the evaluation form for a course dict (from evaluations()).

        Args:
            course:      Full course dict from self.evaluations()
            xnxq:        Semester code (e.g. "2025-20262" or "2025-2026-2")

        Returns an Evaluation object. Call ``ev.load()`` then ``ev.save()``.
        """
        from playwright.sync_api import sync_playwright

        target = course
        r = self.session.get(f"{BASE}/user/me")
        r.raise_for_status()
        yhdm = r.json().get("yhdm", "")
        if not yhdm:
            raise RuntimeError("Could not determine user ID from TIS session")

        # Launch Playwright — connect to real Chrome via CDP so we get HttpOnly cookies (TGC)
        # Fall back to stealth launch if real Chrome isn't available
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        except Exception:
            # Fallback: stealth launch (no HttpOnly cookies — auth may fail)
            browser = pw.chromium.launch(headless=True)
        raw = self.load()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        for name, value in raw.items():
            ctx.add_cookies([{"name": name, "value": value,
                              "domain": "tis.sustech.edu.cn", "path": "/"}])
        page = ctx.new_page()

        # Intercept AJAX calls — fix xnxq format so backend understands it.
        # Vue SPA sends hyphenated "2025-2026-2" but the API only accepts compact "2025-20262".
        # Semester(str) parses any TIS code and .tis exports compact form.
        def fix_xnxq(route, request):
            url = request.url
            val = url.partition("xnxq=")[2].partition("&")[0]
            # Normalize: handle both hyphenated (2025-2026-2) and compact (2025-20262)
            # Safe: Semester raises on invalid formats, we skip if it fails
            try:
                normalized = Semester(val).tis
                if normalized != val:
                    url = url.replace(f"xnxq={val}", f"xnxq={normalized}")
            except ValueError:
                pass  # unknown format, leave unchanged
            route.continue_(url=url)

        page.route("**/listEcaluationRalationshipEnriry*", _fix_xnxq)

        # Navigate to task page — wjid (task-level) identifies the category.
        # Do NOT include rwid in page URL — Vue needs it absent to fire AJAX.
        sem = Semester(xnxq)
        page.goto(
            f"{BASE}/studentAssess/studentEvaluationObjectPage"
            f"?yhdm={yhdm}&wjid={target['wjid']}&sfyp=0&xnxq={sem.tis}",
            wait_until="commit", timeout=30000
        )
        page.wait_for_timeout(7000)  # Vue init + AJAX call takes ~4-5s

        # Click 查询 if button present — wait for it to be visible first
        try:
            page.wait_for_selector("button:has-text('查询')", timeout=8000)
        except Exception:
            raise RuntimeError("查询 button never appeared — page failed to load")
        qbtn = page.query_selector("button:has-text('查询')")
        if qbtn:
            qbtn.click()
            page.wait_for_timeout(5000)

        # Wait for table rows to appear
        for _ in range(8):
            rows = page.query_selector_all("table tbody tr")
            if rows and "暂无数据" not in (rows[0].inner_text() if rows else ""):
                break
            page.wait_for_timeout(1000)

        # Click the correct 去评价 button — find by row text then use CSS nth-child
        all_btns = page.query_selector_all("button:has-text('去评价')")
        row_texts = page.evaluate(
            "() => Array.from(document.querySelectorAll('table tbody tr')).map(r => r.innerText)"
        )
        clicked = False
        for i, rt in enumerate(row_texts):
            if course_name.upper() in rt.upper():
                btn = page.query_selector(f"table tbody tr:nth-child({i+1}) button:has-text('去评价')")
                if btn:
                    btn.click()
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError(f"去评价 button not found for course '{course_name}' in table")
        page.wait_for_timeout(8000)
        page.wait_for_timeout(8000)

        ev = Evaluation(
            course_code=target["course_code"],
            course_name=target["course_name"],
            task_type=target["task_type"],
            wjid=target["wjid"],
            jgwid=target["jgwid"],
            xnxq=xnxq,
            rwh=target["rwh"],
            questionnaire_uuid=target["questionnaire_uuid"],
            theme_uuid=target["theme_uuid"],
            task_rwid=target["task_rwid"],
            page=page,
            browser=browser,
        )
        ev._playwright = pw   # keep alive
        return ev

    def auto_fill(
        self,
        xnxq: str = "2025-2026-2",
        courses: Optional[list[str]] = None,
        score: int = 10,
        text: str = "很好",
        status: str = "pending",
    ) -> dict:
        """
        Auto-fill (and save) all evaluations for a semester.

        Args:
            xnxq:     Semester code
            courses:  Optional list of course names to process. All matching if None.
            score:    Numeric score for RATING questions (default 10)
            text:     Answer for TEXT questions (default "很好")
            status:   Which evaluations to fill: "pending" (lsjgzt=0, not-yet-started),
                      "draft" (lsjgzt=3, saved-draft), "submitted" (lsjgzt=2, submitted),
                      or "all". Default "pending". Use "submitted" to re-fill submitted evals.
        """
        from playwright.sync_api import sync_playwright

        target = self.evaluations(xnxq=xnxq, status=status)
        if courses:
            target = [
                c for c in target
                if c["course_name"].upper() in [x.upper() for x in courses]
                or c["course_code"].upper() in [x.upper() for x in courses]
            ]

        results = {"total": len(target), "saved": 0, "skipped": 0, "errors": []}

        if not target:
            results["errors"].append(f"No {status} evaluations found")
            return results

        # Get cookies for Playwright
        raw = self.load()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-chrome-login",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            # Remove navigator.webdriver flag
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            )
            for name, value in raw.items():
                ctx.add_cookies([{"name": name, "value": value,
                                  "domain": "tis.sustech.edu.cn", "path": "/"}])

            # Route interceptor: normalize xnxq in AJAX calls
            def fix_xnxq(route, req):
                url = req.url
                val = url.partition("xnxq=")[2].partition("&")[0]
                try:
                    normalized = Semester(val).tis
                    if normalized != val:
                        url = url.replace(f"xnxq={val}", f"xnxq={normalized}")
                except ValueError:
                    pass
                route.continue_(url=url)

            page.route("**/listEcaluationRalationshipEnriry*", _fix_xnxq)

            for c in target:
                kcmc = c["course_name"]
                kcdm = c["course_code"]
                wjid = c["wjid"]
                task_rwid = c["task_rwid"]

                print(f"[AUTO-FILL] {kcmc} ({kcdm})")

                # Navigate
                r = self.session.get(f"{BASE}/user/me")
                yhdm = r.json().get("yhdm", "")
                sem = Semester(xnxq)
                # Navigate to eval list page — wjid (task-level) identifies category.
                # Do NOT include rwid in page URL — Vue needs it absent to fire AJAX.
                page.goto(
                    f"{BASE}/studentAssess/studentEvaluationObjectPage"
                    f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={sem.tis}",
                    wait_until="commit", timeout=30000,
                )
                page.wait_for_timeout(7000)  # Vue init + AJAX takes ~4-5s

                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    page.wait_for_timeout(5000)

                # Click 去评价 for this course
                btns = page.query_selector_all("button:has-text('去评价')")
                target_btn = None
                for b in btns:
                    row_text = b.evaluate(
                        "el => { let r = el.closest('tr'); return r ? r.innerText : ''; }"
                    )
                    if kcdm.upper() in row_text.upper() or kcmc.upper() in row_text.upper():
                        target_btn = b
                        break
                if not target_btn:
                    results["errors"].append(f"No button for {kcmc}")
                    results["skipped"] += 1
                    continue

                target_btn.click()
                page.wait_for_timeout(8000)

                # Multi-page fill — fill current page, navigate, repeat until 保存 appears
                while True:
                    # Fill unanswered rating questions: click "5" on inactive grids
                    # (grid options are <div class="grid inactive">0-10</div>)
                    page.evaluate("""() => {
                        const grids = Array.from(document.querySelectorAll('.grid.inactive'));
                        grids.forEach(g => { if (g.innerText.trim() === '5') g.click(); });
                    }""")
                    # Fill unanswered text questions on current page
                    page.evaluate("""() => {
                        const textareas = Array.from(document.querySelectorAll('textarea'));
                        for (const ta of textareas) {
                            if (!ta.value || ta.value.trim() === '') {
                                ta.focus();
                                ta.fill('很好');
                            }
                        }
                    }""")
                    # Check if 保存 is now visible (last page)
                    save_btn = page.query_selector("button:has-text('保存')")
                    if save_btn:
                        save_btn.click()
                        page.wait_for_timeout(3000)
                        results["saved"] += 1
                        break
                    # Not last page — go to next
                    next_btn = page.query_selector("button:has-text('下一步')")
                    if not next_btn or "is-disabled" in (next_btn.get_attribute("class") or ""):
                        results["errors"].append(f"No next/save button for {kcmc}")
                        results["skipped"] += 1
                        break
                    next_btn.click()
                    page.wait_for_timeout(4000)

        return results





    def lazy_submit(
        self,
        xnxq: str = "2025-2026-2",
        courses: Optional[list[str]] = None,
        score: int = 10,
        text: str = "很好",
        status: str = "pending",
    ) -> dict:
        """
        Auto-fill AND submit all evaluations for a semester (full workflow).

        Navigates through ALL pages of each evaluation form, fills every question
        with the given score/text, then clicks 提交 (not 保存) to actually submit.

        Args:
            xnxq:     Semester code (e.g. "2025-2026-2" or "2025-20262")
            courses:  Optional list of course names to process. All matching if None.
            score:    Numeric score for RATING questions (default 10)
            text:     Answer for TEXT questions (default "很好")
            status:   Which evaluations to fill: "pending" (lsjgzt=0),
                      "draft" (lsjgzt=3), "submitted" (lsjgzt=2), or "all".
                      Default "pending".

        Returns dict: {total, submitted, skipped, errors}
        """
        from playwright.sync_api import sync_playwright

        target = self.evaluations(xnxq=xnxq, status=status)
        if courses:
            target = [
                c for c in target
                if c["course_name"].upper() in [x.upper() for x in courses]
                or c["course_code"].upper() in [x.upper() for x in courses]
            ]

        results = {"total": len(target), "submitted": 0, "skipped": 0, "errors": []}

        if not target:
            results["errors"].append(f"No {status} evaluations found")
            return results

        raw = self.load()

        with sync_playwright() as p:
            # Prefer connecting to real Chrome (has HttpOnly TGC cookie)
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-chrome-login",
                    ],
                )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            # Remove navigator.webdriver flag
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            )
            for name, value in raw.items():
                ctx.add_cookies([{"name": name, "value": value,
                                  "domain": "tis.sustech.edu.cn", "path": "/"}])

            # Intercept AJAX calls to fix xnxq format: normalize any variant to TIS compact
            def fix_xnxq(route, request):
                url = request.url
                val = url.partition("xnxq=")[2].partition("&")[0]
                try:
                    normalized = Semester(val).tis
                    if normalized != val:
                        url = url.replace(f"xnxq={val}", f"xnxq={normalized}")
                except ValueError:
                    pass
                route.continue_(url=url)

            page.route("**/listEcaluationRalationshipEnriry*", _fix_xnxq)

            for c in target:
                kcmc = c["course_name"]
                kcdm = c["course_code"]
                wjid = c["wjid"]
                task_rwid = c["task_rwid"]

                print(f"[LAZY_SUBMIT] {kcmc} ({kcdm})")

                sem = Semester(xnxq)
                r = self.session.get(f"{BASE}/user/me")
                yhdm = r.json().get("yhdm", "")
                # Navigate to eval list page — wjid (task-level) identifies category.
                # Do NOT include rwid in page URL — Vue needs it absent to fire AJAX.
                page.goto(
                    f"{BASE}/studentAssess/studentEvaluationObjectPage"
                    f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={sem.tis}",
                    wait_until="commit", timeout=30000,
                )
                page.wait_for_timeout(7000)  # Vue init + AJAX call takes ~4-5s

                try:
                    page.wait_for_selector("button:has-text('查询')", timeout=8000)
                except Exception:
                    raise RuntimeError(f"查询 button not found for {kcmc} — page failed to load")
                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    page.wait_for_timeout(4000)

                # Wait for data rows (not "暂无数据")
                for _ in range(8):
                    rows = page.query_selector_all("table tbody tr")
                    if rows and "暂无数据" not in (rows[0].inner_text() if rows else ""):
                        break
                    page.wait_for_timeout(1000)

                # Find and click 去评价 using nth-child (avoids evaluate context issues)
                row_texts = page.evaluate(
                    "() => Array.from(document.querySelectorAll('table tbody tr')).map(r => r.innerText)"
                )
                clicked = False
                for i, rt in enumerate(row_texts):
                    if kcdm.upper() in rt.upper() or kcmc.upper() in rt.upper():
                        btn = page.query_selector(f"table tbody tr:nth-child({i+1}) button:has-text('去评价')")
                        if btn:
                            btn.click()
                            clicked = True
                            break
                if not clicked:
                    results["errors"].append(f"去评价 not found for {kcmc}")
                    results["skipped"] += 1
                    continue

                page.wait_for_timeout(8000)

                # Multi-page fill — fill current page, navigate, repeat until 提交 appears
                while True:
                    # Fill unanswered rating questions on current page
                    page.evaluate("""() => {
                        const containers = Array.from(document.querySelectorAll('.grid-container'));
                        for (const container of containers) {
                            const grids = Array.from(container.querySelectorAll('.grid'));
                            const ten = grids[grids.length - 1];
                            if (ten && !ten.classList.contains('active')) {
                                ten.click();
                            }
                        }
                    }""")
                    # Fill unanswered text questions on current page
                    page.evaluate("""() => {
                        const textareas = Array.from(document.querySelectorAll('textarea'));
                        for (const ta of textareas) {
                            if (!ta.value || ta.value.trim() === '') {
                                ta.focus();
                                ta.fill('很好');
                            }
                        }
                    }""")
                    # Check if 提交 is now visible (last page)
                    submit_btn = page.query_selector("button:has-text('提交')")
                    if submit_btn:
                        submit_btn.click()
                        page.wait_for_timeout(3000)
                        results["submitted"] += 1
                        break
                    # Not last page — go to next
                    next_btn = page.query_selector("button:has-text('下一步')")
                    if not next_btn or "is-disabled" in (next_btn.get_attribute("class") or ""):
                        results["errors"].append(f"No next/final button for {kcmc}")
                        results["skipped"] += 1
                        break
                    next_btn.click()
                    page.wait_for_timeout(4000)

        return results



    def submit(
        self,
        course: str,
        xnxq: str = "2025-2026-2",
    ) -> dict:
        """
        Submit a single already-filled evaluation by clicking 提交.

        Use this when the form is already filled (e.g. via save + manual review,
        or via autofill + save). Finds the course in the specified semester's
        evaluation list and clicks 提交.

        Args:
            course:  Exact or partial course name to submit (case-insensitive)
            xnxq:    Semester code (e.g. "2025-2026-2")

        Returns dict: {submitted, skipped, errors}
        """
        from playwright.sync_api import sync_playwright

        evals = self.evaluations(xnxq=xnxq, status="draft")
        target = None
        for c in evals:
            if course.upper() in c["course_name"].upper() or course.upper() in c["course_code"].upper():
                target = c
                break
        if not target:
            return {"error": f"Course '{course}' not found in saved drafts (lsjgzt=3)", "submitted": 0, "skipped": 1}

        raw = self.load()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-chrome-login",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            # Remove navigator.webdriver flag
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            )
            for name, value in raw.items():
                ctx.add_cookies([{"name": name, "value": value,
                                  "domain": "tis.sustech.edu.cn", "path": "/"}])

            kcmc = target["course_name"]
            kcdm = target["course_code"]
            wjid = target["wjid"]
            task_rwid = target["task_rwid"]

            print(f"[SUBMIT] {kcmc} ({kcdm})")

            r = self.session.get(f"{BASE}/user/me")
            yhdm = r.json().get("yhdm", "")
            # For "第五种评价" (asyncData hangs in headless Playwright),
            # navigate WITHOUT rwid and inject course data directly into Vue.
            # The asyncData $.ajax call hangs forever (no response) so we bypass it.
            search_url = (
                f"{BASE}/studentAssess/studentEvaluationObjectPage"
                f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={xnxq}"
            )
            page.goto(search_url, wait_until="commit", timeout=30000)
            page.wait_for_timeout(6000)

            # Inject the course data into Vue's datas array
            inject_ok = page.evaluate(
                f"""
                (function() {{
                    try {{
                        var el = document.querySelector('#app');
                        var vue = el.__vue__;
                        while (vue && vue.$data && vue.$data.datas === undefined) {{
                            vue = vue.$parent;
                        }}
                        if (vue && vue.$data) {{
                            vue.$data.datas = [{json.dumps(target)}];
                            vue.$data.elements = [{{name: '{kcdm}'}}];
                            return 'ok';
                        }}
                        return 'no_datas_property';
                    }} catch(e) {{
                        return 'error: ' + e.message;
                    }}
                }})()
                """
            )
            print(f"[SUBMIT] Vue inject: {inject_ok}")

            # Un-hide app and trigger query to re-render
            page.evaluate("document.querySelector('#app').style.display='block'")
            page.wait_for_timeout(500)
            try:
                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            # Find and click 提交 button
            submit_btn = page.query_selector("button:has-text('提交')")
            if submit_btn:
                submit_btn.click()
                page.wait_for_timeout(3000)
                return {"submitted": 1, "skipped": 0, "errors": []}
            else:
                return {"error": f"提交 button not found for {kcmc}", "submitted": 0, "skipped": 1}


# -----------------------------------------------------------------------
# auto_fill functional API (backwards compat)
# -----------------------------------------------------------------------


# ── standalone wrappers ───────────────────────────────────────────────────────────-
def auto_fill(
    xnxq: str = "2025-2026-2",
    courses: Optional[list[str]] = None,
    score: int = 10,
    text: str = "很好",
) -> dict:
    """
    Auto-fill all pending evaluations. Uses TISAuthEval internally.

    Returns dict: {total, saved, skipped, errors}
    """
    auth = TISAuthEval()
    if not auth.refresh():
        return {"error": "auth", "message": "TIS auth refresh failed", "hint": "sustech tis session refresh"}
    return auth.auto_fill(xnxq=xnxq, courses=courses, score=score, text=text)

def lazy_submit(
    xnxq: str = "2025-2026-2",
    courses: Optional[list[str]] = None,
    score: int = 10,
    text: str = "很好",
) -> dict:
    """
    Auto-fill AND submit all pending evaluations. Uses TISAuthEval internally.

    Returns dict: {total, submitted, skipped, errors}
    """
    auth = TISAuthEval()
    if not auth.refresh():
        return {"error": "auth", "message": "TIS auth refresh failed", "hint": "sustech tis session refresh"}
    return auth.lazy_submit(xnxq=xnxq, courses=courses, score=score, text=text)

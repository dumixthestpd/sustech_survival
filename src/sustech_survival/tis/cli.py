#!/usr/bin/env python3
"""
TIS CLI — Teaching Information System

Usage:
  tis.py session [check|refresh|login]   Manage session
  tis.py courses [--semester X]           List courses
  tis.py grades [--semester X]            List grades
  tis.py evals [--pending]                Show eval status
  tis.py query <path> [key=value ...]     Raw API query
  tis.py grades --export grades.csv       Export grades to CSV

Credentials: credentials.txt (format: sid:password)
Session: in-memory only, not persisted to disk.
"""
import sys
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI_DIR.parent.parent))

import click
from sustech_survival.sso import TISAuth
from sustech_survival.exceptions import SessionExpired, NetworkError
from sustech_survival.tis.grades import _get_grades, _calc_gpa, _format_grade_row

# Shared auth instance — refreshed once per CLI invocation
_auth_singleton = None


def auth_or_exit():
    global _auth_singleton
    if _auth_singleton is None:
        _auth_singleton = TISAuth()
    ok, reason = _auth_singleton.ensure()
    if not ok:
        click.secho(f"❌  Session invalid: {reason}", fg="red")
        sys.exit(1)
    return _auth_singleton


def em(s):
    return click.style(s, bold=True)


def ok_s(s):
    return click.style(s, fg="green")


def err_s(s):
    return click.style(s, fg="red")


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """TIS CLI — SUSTech Teaching Information System"""
    pass


# ── Session commands ──────────────────────────────────────────────────────────

@cli.command(name="session")
@click.argument("cmd", default="check", type=click.Choice(["check", "refresh", "login"]))
def session_cmd(cmd):
    """
    Manage TIS session.

    Examples:
      tis.py session          # check
      tis.py session check   # same
      tis.py session refresh # re-authenticate via CAS (headless)
      tis.py session login   # manual browser login
    """
    auth = TISAuth()
    if cmd == "check":
        ok, reason = auth.check()
        if ok:
            click.secho("✅  Session valid (in-memory)", fg="green")
        else:
            click.secho(f"❌  {reason}", fg="red")
            sys.exit(1)
    elif cmd == "refresh":
        click.secho("Refreshing session via CAS...", fg="cyan")
        ok = auth.refresh()
        if ok:
            click.secho("✅  Session refreshed", fg="green")
        else:
            click.secho("❌  Refresh failed. Try: tis.py session login", fg="red")
            sys.exit(1)
    elif cmd == "login":
        click.secho("Opening browser for manual CAS login...", fg="cyan")
        ok = auth.login()
        if ok:
            click.secho("✅  Login complete", fg="green")
        else:
            click.secho("⚠️  Login incomplete — captcha may be required", fg="yellow")
            sys.exit(1)


# ── Courses ───────────────────────────────────────────────────────────────────

@cli.command(name="courses")
@click.option("--semester", "-s", default=None,
              help="Filter by semester name (e.g. '2025-2026-2')")
def courses_cmd(semester):
    """List courses from TIS."""
    try:
        auth = auth_or_exit()
    except AuthorizerError as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    click.secho("📚 Fetching courses...", fg="cyan")
    try:
        from sustech_survival.tis.courses import _get_courses
        courses = get_courses(auth.session, semester=semester)
    except (SessionExpired, NetworkError) as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    if not courses:
        click.secho(
            "No courses returned — Spring 2026 grades may not be posted yet. "
            "Available: 2024秋季, 2025春季, 2025秋季. "
            "Use --semester 2025-2026-1 to filter for Fall 2025.",
            fg="yellow"
        )
        return

    by_sem = {}
    for c in courses:
        sem = c.get("xnxqmc", "未知")
        by_sem.setdefault(sem, []).append(c)

    for sem, sem_courses in sorted(by_sem.items()):
        total = sum(c.get("xf", 0) for c in sem_courses)
        click.secho(f"\n{'─' * 55}")
        click.secho(f"  {sem}  ({len(sem_courses)} 门课, {total:.0f} 学分)")
        click.secho(f"  {'─' * 55}")
        for c in sem_courses:
            code = c.get("kcdm", "")
            name = c.get("kcmc", "") or c.get("kcmc_en", "")
            credit = c.get("xf", 0)
            teacher = c.get("dgjsmc", "") or ""
            display = f"{code} {name}" if code else name
            click.echo(f"    {display[:45]:<46} {credit:.1f}学分")
            if teacher:
                click.echo(f"      👤 {teacher}")


# ── Grades ────────────────────────────────────────────────────────────────────

@cli.command(name="grades")
@click.option("--semester", "-s", default=None,
              help="Filter by semester (e.g. '2025-20262' or '2025-2026-2')")
@click.option("--export", "-e", "export_path", default=None,
              help="Export to CSV file")
def grades_cmd(semester, export_path):
    """Show grades from TIS."""
    # Normalize semester format if provided
    if semester:
        semester = semester.replace("-", "")  # 2025-2026-2 → 2025-20262

    try:
        auth = auth_or_exit()
    except AuthorizerError as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    click.secho("📊 Fetching grades...", fg="cyan")
    try:
        grades = get_grades(auth.session, semester=semester)
    except (SessionExpired, NetworkError) as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    if not grades:
        click.secho(
            "No grades returned — either semester not published, wrong code, "
            "or Spring 2026 grades not yet posted. "
            "Published: 2024秋季, 2025春季, 2025秋季. "
            "Try without --semester to see all available.",
            fg="yellow"
        )
        return

    if export_path:
        import csv
        with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
            fields = ["课程代码", "课程名称", "学期", "学分", "分数", "性质"]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for g in grades:
                row = format_grade_row(g)
                w.writerow({k: row.get(k, "") for k in fields})
        click.secho(f"📄  Exported to {export_path}", fg="green")
        return

    gpa, total_creds = calc_gpa(grades)
    click.secho(f"\n{'─' * 60}", fg="cyan")
    click.secho(f"  {len(grades)} 门课  |  GPA: {gpa}  |  总学分: {total_creds:.0f}")
    click.secho(f"{'─' * 60}\n")
    for g in grades:
        row = format_grade_row(g)
        code = row.get("课程代码", "")
        name = row.get("课程名称", "")
        score = row.get("分数", "-")
        nature = row.get("性质", "")
        display = f"{code} {name}" if code else name
        click.echo(f"  {display[:44]:<45} {score:>5}  {nature}")
    click.echo("")


# ── Evals ─────────────────────────────────────────────────────────────────────

STATUS_MAP = {"0": "待评价", "1": "已放弃", "2": "已评价",
              "3": "已保存", "4": "未结课", "5": "已评价"}


@cli.command(name="evals")
@click.option("--pending", is_flag=True, help="Show only unsubmitted evals")
def evals_cmd(pending):
    """
    Show TIS course evaluation (评教) status.

    Status codes:
      已评价 (2/5) = fully submitted
      已保存  (3)   = saved as draft, NOT submitted
      待评价  (0)   = not started
    """
    try:
        auth = auth_or_exit()
    except AuthorizerError as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    r = auth.get(
        "/personnelEvaluation/listObtainPersonnelEvaluationTasks",
        params={"yhdm": auth.username, "rwmc": "", "sfyp": "0",
                "pageNum": "1", "pageSize": "20"},
        timeout=15,
    )
    if r.status_code == 401:
        click.secho("❌  Session expired. Run: tis.py session refresh", fg="red")
        sys.exit(1)
    if r.status_code != 200:
        click.secho(f"❌  API error {r.status_code}", fg="red")
        sys.exit(1)

    data = r.json()
    if data.get("code") != "200":
        click.secho(f"❌  API error: {data}", fg="red")
        sys.exit(1)

    tasks = data.get("result", {}).get("list", [])
    if not tasks:
        click.secho("No evaluation tasks found.", fg="yellow")
        return

    xnxq = "2025-20262"  # Spring 2026
    all_courses = []

    for task in tasks:
        rwid = task["rwid"]
        firstwjid = task["firstwjid"]

        cr = auth.get(
            "/personnelEvaluation/listEcaluationRalationshipEnriry",
            params={"pjrdm": auth.username, "wjid": firstwjid, "bpmc": "",
                    "sfyp": "0", "xnxq": xnxq, "pageNum": "1", "pageSize": "50",
                    "zc": "", "xqj": "", "jc": "", "skdd": "", "kkyxdm": "",
                    "bpssyxdm": "", "kcmc": "", "sfcxqbwj": "0",
                    "rwid": rwid, "lsjgzt": ""},
            timeout=15,
        )
        if cr.status_code != 200:
            continue
        cdata = cr.json()
        if cdata.get("code") != "200":
            continue
        for c in cdata["result"]["list"]:
            all_courses.append(c)

    if not all_courses:
        click.secho("No courses found in eval tasks.", fg="yellow")
        return

    if pending:
        all_courses = [c for c in all_courses
                       if c.get("lsjgzt") not in ("2", "5")]

    def sort_key(c):
        return (c.get("lsjgzt") in ("2", "5"), c.get("kcmc", ""))

    for c in sorted(all_courses, key=sort_key):
        lsjgzt = c.get("lsjgzt", "0")
        status_text = STATUS_MAP.get(lsjgzt, f"未知({lsjgzt})")
        is_submitted = lsjgzt in ("2", "5")
        code = c.get("kcdm", "")
        name = c.get("kcmc", "") or c.get("kcmc_en", "")

        if is_submitted:
            icon = ok_s("✓")
            status_display = ok_s(f"[{status_text}]")
        else:
            icon = err_s("✗")
            status_display = err_s(f"[{status_text}]")

        click.echo(f"  {icon} {status_display}  {code} {name}")

    pending_count = sum(1 for c in all_courses if c.get("lsjgzt") not in ("2", "5"))
    total = len(all_courses)
    click.echo(f"\n  {pending_count}/{total} unsubmitted")


# ── Raw query ─────────────────────────────────────────────────────────────────

@cli.command(name="query")
@click.argument("path")
@click.argument("params", nargs=-1)
@click.option("--method", "-m", default="GET", type=click.Choice(["GET", "POST"]))
def query_cmd(path, params, method):
    """
    Raw API query against TIS.

    Example:
      tis.py query /personnelEvaluation/listObtainPersonnelEvaluationTasks yhdm=12413021 sfyp=0
    """
    try:
        auth = auth_or_exit()
    except AuthorizerError as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    param_dict = {}
    for p in params:
        if "=" in p:
            k, v = p.split("=", 1)
            param_dict[k] = v

    url = f"{auth.BASE_URL}{path}"
    click.secho(f"→ {method} {url}", fg="cyan")
    if param_dict:
        click.echo(f"   params: {param_dict}")

    if method == "GET":
        r = auth.get(path, params=param_dict, timeout=15)
    else:
        r = auth.post(path, json=param_dict, timeout=15)

    click.secho(f"← {r.status_code}", fg="cyan")
    try:
        import json
        click.echo(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        click.echo(r.text[:500])


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()

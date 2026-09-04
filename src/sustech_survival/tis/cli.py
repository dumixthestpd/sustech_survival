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
import unicodedata
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI_DIR.parent.parent))

import click
from sustech_survival.sso import TISAuth
from sustech_survival.exceptions import SessionExpired, NetworkError, APIError
from sustech_survival.tis.grades import get_grades, calc_gpa, format_grade_row

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


def _normalize_semester_label(value):
    """Map a '--semester' value to the Chinese xnxqmc label the grade API uses.

    Accepts either a raw label/substring ('2025春季', '2025') or a TIS code
    ('2025-2026-2' / '2025-20262'); codes are converted to their label
    (e.g. '2025-20262' -> '2025春季').
    """
    if not value:
        return value
    v = value.strip()
    compact = v.replace("-", "")
    if len(compact) == 9 and compact.isdigit():
        from sustech_survival.semester import Semester
        try:
            return Semester(compact).xnxqmc
        except ValueError:
            pass
    return v


# -- CJK-aware table helpers ---------------------------------------------------

def _disp_width(text):
    """On-screen width of ``text``: CJK / full-width chars occupy 2 columns."""
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _clip(text, max_width):
    """Truncate ``text`` to ``max_width`` display columns, appending '…'."""
    text = str(text)
    if _disp_width(text) <= max_width:
        return text
    out = ""
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > max_width - 1:  # keep a column free for the ellipsis
            break
        out += ch
        used += w
    return out + "…"


def _pad(text, width, align="left"):
    """Pad ``text`` to ``width`` display columns (left or right aligned)."""
    text = str(text)
    gap = width - _disp_width(text)
    if gap <= 0:
        return text
    return (" " * gap + text) if align == "right" else (text + " " * gap)


# -- CLI group ----------------------------------------------------------------

@click.group()
def cli():
    """TIS CLI — SUSTech Teaching Information System"""
    pass


# -- Session commands ----------------------------------------------------------

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


# -- Courses -------------------------------------------------------------------

@cli.command(name="courses")
@click.option("--semester", "-s", default=None,
              help="List a specific term's courses: the Chinese label "
                   "('2025春季') or a TIS code ('2025-2026-2'). "
                   "Default: the current in-progress term (your enrolled "
                   "courses, from the personal timetable).")
@click.option("--all", "show_all", is_flag=True, default=False,
              help="List every term: the current in-progress term (from the "
                   "personal timetable) plus all past terms that already have "
                   "posted grades. Mutually exclusive with --semester.")
def courses_cmd(semester, show_all):
    """List courses.

    Default (no flags): the CURRENT in-progress term's enrolled courses,
    fetched from your personal timetable (xszykb) — the grade API only covers
    terms that already have posted grades, so a just-started term would
    otherwise show nothing.

    --all: every term in one listing — the current in-progress term (from the
    personal timetable) plus each past term that already has posted grades
    (from the grade records), one section per term.

    --semester: a specific past term's graded courses (Chinese label
    '2025春季' or TIS code '2025-2026-2').
    """
    if semester and show_all:
        click.secho("❌  --all and --semester are mutually exclusive", fg="red")
        sys.exit(1)
    auth = auth_or_exit()

    click.secho("📚 Fetching courses...", fg="cyan")
    try:
        if semester:
            from sustech_survival.tis.courses import get_courses
            courses = get_courses(auth.session, semester=_normalize_semester_label(semester))
        elif show_all:
            from sustech_survival.tis.courses import get_courses, get_current_courses
            courses = get_courses(auth.session) + get_current_courses()
        else:
            from sustech_survival.tis.courses import get_current_courses
            courses = get_current_courses()
    except (SessionExpired, NetworkError) as e:
        click.secho(f"❌  {e}", fg="red")
        sys.exit(1)

    if not courses:
        click.secho(
            "No courses found. If the current term just started, its "
            "timetable may not be published yet; for a past term pass "
            "--semester, e.g. --semester 2025春季.",
            fg="yellow"
        )
        return

    # Dedupe by (semester, course) — when a term is reachable both via the
    # grade API and the timetable (--all merge), the grade row comes first and
    # wins (it carries credits); the timetable's duplicate drops out.
    by_sem = {}
    seen_in_sem = {}
    for c in courses:
        sem = c.get("xnxqmc", "未知")
        key = (c.get("kcdm", ""), c.get("kcmc", "") or c.get("kcmc_en", ""))
        if key in seen_in_sem.get(sem, set()):
            continue
        seen_in_sem.setdefault(sem, set()).add(key)
        by_sem.setdefault(sem, []).append(c)

    # One shared table layout for every term so the current (timetable) and
    # past (grade-record) sections line up column-for-column.
    headers = ("课程代码", "课程名称", "学分", "教师")
    aligns = ("left", "left", "right", "left")
    caps = (16, 44, 7, 20)  # per-column display-width caps
    sections = []
    all_cells = []
    for sem, sem_courses in sorted(by_sem.items()):
        total = sum(c.get("xf", 0) or 0 for c in sem_courses)
        title = f"{sem}  ({len(sem_courses)} 门课"
        title += f", {total:.0f} 学分)" if total else ")"
        cells = []
        for c in sem_courses:
            code = (c.get("kcdm", "") or "").strip() or "—"
            name = (c.get("kcmc", "") or c.get("kcmc_en", "") or "").strip()
            credit = c.get("xf", 0) or 0
            # Timetable rows carry no credit figure — "—" until grades post.
            credit_s = f"{credit:.1f}" if credit else "—"
            teacher = (c.get("dgjsmc", "") or "").strip() or "—"
            cells.append((code, name, credit_s, teacher))
        sections.append((title, cells))
        all_cells.extend(cells)

    widths = []
    for i, header in enumerate(headers):
        w = max([_disp_width(header)] + [_disp_width(r[i]) for r in all_cells])
        widths.append(min(w, caps[i]))

    def fmt(values):
        return "  ".join(
            _pad(_clip(v, widths[i]), widths[i], aligns[i])
            for i, v in enumerate(values)
        )

    separator = "─" * (sum(widths) + (len(headers) - 1) * 2)
    for title, cells in sections:
        click.secho(f"\n{title}", bold=True)
        click.secho(fmt(headers), bold=True)
        click.echo(separator)
        for row in cells:
            click.echo(fmt(row))


# -- Grades --------------------------------------------------------------------

@cli.command(name="grades")
@click.option("--semester", "-s", default=None,
              help="Filter by semester (e.g. '2025-20262' or '2025-2026-2')")
@click.option("--export", "-e", "export_path", default=None,
              help="Export to CSV file")
@click.option("--json", "as_json", is_flag=True,
              help="Emit JSON instead of a text table")
def grades_cmd(semester, export_path, as_json):
    """Show grades from TIS."""
    # Normalize semester format if provided
    if semester:
        semester = semester.replace("-", "")  # 2025-2026-2 → 2025-20262

    auth = auth_or_exit()

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

    if as_json:
        import json as _json
        click.echo(_json.dumps([format_grade_row(g) for g in grades], ensure_ascii=False, indent=2))
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
    click.secho(f"\n{'-' * 78}", fg="cyan")
    click.secho(f"  {len(grades)} 门课  |  GPA: {gpa}  |  总学分: {total_creds:.0f}")
    click.secho(f"{'-' * 78}\n", fg="cyan")
    # Header so the score/credit/type columns don't look like random numbers.
    click.secho(f"  {'课程 (code)':<44} {'分数':>5}  {'学分':>4}  {'性质':<6}  学期", fg="cyan")
    for g in grades:
        row = format_grade_row(g)
        code = row.get("课程代码", "")
        name = row.get("课程名称", "")
        score = row.get("分数", "-")
        credit = row.get("学分", "")
        nature = row.get("性质", "")
        term = row.get("学期", "")
        display = f"{code} {name}".strip() if code else name
        click.echo(f"  {display[:42]:<44} {score:>5}  {credit:>4}  {nature:<6}  {term}")
    click.echo("")


# -- Evals ---------------------------------------------------------------------

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
    auth = auth_or_exit()

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

    from sustech_survival.semester import Semester
    xnxq = Semester.current().tis  # live current semester
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


# -- Raw query -----------------------------------------------------------------

@cli.command(name="query")
@click.argument("path")
@click.argument("params", nargs=-1)
@click.option("--method", "-m", default="GET", type=click.Choice(["GET", "POST"]))
def query_cmd(path, params, method):
    """
    Raw API query against TIS.

    Example:
      tis.py query /personnelEvaluation/listObtainPersonnelEvaluationTasks yhdm=<sid> sfyp=0
    """
    auth = auth_or_exit()

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


@cli.command(name="timetable", help="Solve a non-conflicting timetable from a list of course codes.")
@click.argument("courses", nargs=-1)
@click.option("--exclude", "-e", multiple=True,
              help="Exclude course code from search (repeatable).")
@click.pass_context
def timetable_cmd(ctx, courses, exclude) -> None:
    """
    Solve a non-conflicting timetable from course codes (e.g. MSE306 SS143).

    NOTE: This command is a stub that surfaces the underlying `solve()`,
    `render_grid()`, and `describe_section()` functions from the
    timetable module. For the full solver with --exclude / --codes-file /
    --block / --json / --semester options, use the Python API:

        from sustech_survival.tis.timetable import (
            fetch_sections, solve, render_grid, describe_section,
            parse_block, DAY_LABELS,
        )

    Example:
        sustech tis timetable MSE306 SS143
    """
    from ..sso import TISAuth
    from .timetable import fetch_sections, solve, render_grid, describe_section, parse_block, DAY_LABELS, SKILL_ROOT
    from .schedule import current_semester
    import sys as _sys
    import json as _json
    if not courses:
        click.secho("❌ No courses specified", fg="red", err=True)
        raise SystemExit(1)
    auth = TISAuth()
    ok, reason = auth.ensure()
    if not ok:
        click.secho("❌ Login failed", fg="red", err=True)
        raise SystemExit(1)
    click.secho("🔑 Session OK", fg="cyan", err=True)
    xn, xq = current_semester()
    click.secho(f"📡 Fetching sections ({xn}-{xq})...", fg="cyan", err=True)
    sections = fetch_sections(list(courses), auth, xn, xq)
    for code in courses:
        n = len(sections.get(code, []))
        click.echo(f"  {code}: {n} sections", err=True)
    if all(len(sections.get(c, [])) == 0 for c in courses):
        click.secho(f"⚠️  No sections found: {', '.join(courses)}", fg="yellow", err=True)
        raise SystemExit(1)
    results = solve(sections, max_results=100)
    click.secho(f"\n✅ Found {len(results)} conflict-free schedule(s)\n", fg="green", err=True)
    for i, sched in enumerate(results):
        click.echo(f"--- Schedule {i + 1} ---")
        click.echo(render_grid(sched))
        click.echo("")
        for sec in sched:
            click.echo(f"  {sec['code']}/{sec['section']} | {sec['name']}")
            click.echo(f"    {describe_section(sec)}")
        click.echo("")


@cli.command(name="schedule", help="Show personal TIS course schedule.")
@click.option("--zc", "zc", type=int, default=None,
              help="Week number (default: current week).")
@click.option("--xn", default=None, help="Academic year e.g. 2025-2026.")
@click.option("--xq", default=None, help="Semester 1 or 2.")
@click.option("--all", "fetch_all", is_flag=True,
              help="Fetch full semester instead of single week.")
def schedule_cmd(zc, xn, xq, fetch_all) -> None:
    """Print your personal course schedule for one week (default) or full semester."""
    import json as _json
    from .schedule import week_schedule, semester_schedule, current_week
    if fetch_all:
        try:
            data = semester_schedule(xn, xq)
        except APIError as e:
            click.secho(f"❌  {e}", fg="red", err=True)
            raise SystemExit(1)
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
        return
    try:
        week = zc if zc is not None else current_week()
        data = week_schedule(week, xn, xq)
    except APIError as e:
        # APIError covers SessionExpired + NetworkError (both subclasses).
        click.secho(f"❌  {e}", fg="red", err=True)
        raise SystemExit(1)
    click.echo(f"=== Week {week} ===")
    for entry in data:
        click.echo(f"  [{entry['KEY']}] {entry['SKSJ']}")


@cli.command(name="campus-schedule", help="Full TIS campus schedule (all rooms, all courses).")
@click.option("--semester", default=None,
              help="Format: YYYY-YYYY-Q. Defaults to the live term.")
@click.option("--full", is_flag=True, help="Include every entry.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Output CSV.")
def campus_schedule_cmd(semester, full, as_json, as_csv) -> None:
    """Dump the entire TIS campus schedule — every room, every course."""
    import json as _json
    import csv as _csv
    import sys as _sys
    from .campus_schedule import get_campus_schedule as campus_schedule
    if semester is None:
        from sustech_survival.semester import Semester
        current = Semester.current()
        semester = f"{current.xn}-{current.xq}"
    parts = semester.rsplit("-", 1)
    xn, xq = parts[0], parts[1]
    rows = campus_schedule(xn=xn, xq=xq, full=full)
    if as_json:
        click.echo(_json.dumps(rows, ensure_ascii=False, indent=2))
    elif as_csv:
        w = _csv.writer(_sys.stdout)
        if rows:
            w.writerow(rows[0].keys())
            for row in rows:
                w.writerow(row.values())
    else:
        # Plain text — default
        for row in rows:
            click.echo(str(row))


# -- Classroom inquiry + booking ---------------------------------------------
# `tis/classroom/cli.py` is a self-contained click group; mount it under the
# TIS CLI so `sustech tis classroom {rooms,room,refresh,...}` works. Without
# this registration, dispatching into the package name raises
# `is a package and cannot be directly executed` (Click tries to invoke the
# package itself as a __main__).

from .classroom.cli import cli as _classroom_cli  # noqa: E402

cli.add_command(_classroom_cli)


# -- Main ----------------------------------------------------------------------

if __name__ == "__main__":
    cli()

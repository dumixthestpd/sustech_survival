#!/usr/bin/env python3
"""
BB CLI - SUSTech Blackboard Assignment Automation

Usage:
  bb.py courses                              # list all courses
  bb.py courses "physical"                   # search courses
  bb.py course 8053 assignments             # list all + attempts overview
  bb.py course 8053 assignment status        # all: submitted/not submitted
  bb.py course 8053 assignment 619093        # all attempts for that assignment
  bb.py course 8053 assignment 619093 status # status of specific assignment
  bb.py course 8053 assignment 619093 attempts # all attempts (explicit keyword)
  bb.py course 8053 assignment 619093 2       # details of attempt 2
  bb.py course 8053 assignment 619093 2 --download # download attempt 2
"""
import sys, os, json
from pathlib import Path

BB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BB_DIR))

import click
from sustech_survival.sso import BBAuth
from sustech_survival.sso.authorizer import AuthorizerError
from .courses import list_courses, find_course, get_course_numeric_id, discover_assignments_for_course, load_courses
from .download import discover_attempt_ids, scrape_attempt_details, download_file
from .pages import preview_page
from .query import (
    discover_all_items, type_stats_items, print_stats,
    format_item,
)

# ── Helpers ────────────────────────────────────────────────────────────

def em(s):
    return click.style(s, bold=True)

def ok_s(s):
    return click.style(s, fg="green")
def err_s(s):
    return click.style(s, fg="red")


_bb = BBAuth()


def load_session_or_exit():
    """Ensure session is valid and return Playwright-format cookies list."""
    try:
        ok, reason = _bb.ensure()
        if not ok:
            click.secho(f"\n❌  Session invalid: {reason}", fg="red")
            sys.exit(1)
        # Get cookies from in-memory cache
        raw = _bb.cookies
        return [{"name": k, "value": v, "domain": ".bb.sustech.edu.cn", "path": "/"}
                for k, v in raw.items() if v]
    except AuthorizerError as e:
        click.secho(f"\n❌  Session error: {e}", fg="red")
        sys.exit(1)
    except FileNotFoundError:
        click.secho("\n❌  No session. Run: python3 bb.py session login", fg="red")
        sys.exit(1)


# ── Last course cache ──────────────────────────────────────────────────

_LAST_COURSE_FILE = Path(__file__).parent / "lastcourse.txt"

def get_last_course():
    if not _LAST_COURSE_FILE.exists():
        return None
    cid = _LAST_COURSE_FILE.read_text().strip()
    if not cid:
        return None
    for c in load_courses():
        if c["id"] == cid:
            return (cid, get_course_numeric_id(cid), c["name"])
    return None

def set_last_course(cid):
    _LAST_COURSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_COURSE_FILE.write_text(cid)


# ── Safe wrappers ──────────────────────────────────────────────────────

def _safe_attempts(ctx, numeric_cid, content_id):
    try:
        return discover_attempt_ids(ctx, numeric_cid, content_id)
    except Exception:
        return []


# ── Assignment list command ────────────────────────────────────────────

def _list_assignments(ctx, numeric_cid, course_name, assignments):
    """List all assignments with attempt counts."""
    click.secho(f"\n📋  Assignments - {course_name}\n", fg="cyan", bold=True)
    for cid, title in assignments:
        atts = _safe_attempts(ctx, numeric_cid, cid)
        status = f"{len(atts)} attempt(s)" if atts else err_s("not submitted")
        click.secho(f"  [{cid}] {title[:44]}", fg="white")
        click.echo(f"       {status}")
        for aid, (anum, ts) in atts:
            click.echo(f"         {em(f'Attempt {anum}')}  {ts[:25]}")
        print()


# ── All-status command ─────────────────────────────────────────────────

def _all_status(ctx, numeric_cid, course_name, assignments):
    """Show submitted/not submitted for all assignments."""
    click.secho(f"\n📋  Submission Status - {course_name}\n", fg="cyan", bold=True)
    for cid, title in assignments:
        atts = _safe_attempts(ctx, numeric_cid, cid)
        status = ok_s(f"submitted ({len(atts)} attempt(s))") if atts else err_s("not submitted")
        click.secho(f"  [{cid}] {title[:44]}", fg="white")
        click.echo(f"       {status}")
    print()


# ── Single assignment command ──────────────────────────────────────────

def _single_assignment(ctx, session_cookies, numeric_cid,
                       content_id, attempt_arg, download_flag, output_dir):
    """Handle: assignment <id> [status|attempt|N]"""
    att_keyword = str(attempt_arg).lower() if attempt_arg else None

    if att_keyword == "status":
        # Status of one specific assignment
        atts = _safe_attempts(ctx, numeric_cid, content_id)
        status = ok_s(f"submitted ({len(atts)} attempt(s))") if atts else err_s("not submitted")
        click.secho(f"\n📋  Assignment {content_id}\n", fg="cyan", bold=True)
        click.echo(f"  Status: {status}")
        if atts:
            for aid, (anum, ts) in atts:
                click.echo(f"  {em(f'Attempt {anum}')}  {ts[:25]}")
        print()
        return

    if att_keyword == "attempts" or attempt_arg is None:
        # All attempts for this assignment
        atts = _safe_attempts(ctx, numeric_cid, content_id)
        click.secho(f"\n🔍  Attempts - {content_id}\n", fg="cyan", bold=True)
        if not atts:
            click.secho("  No attempts found.", fg="yellow")
        else:
            for aid, (anum, ts) in atts:
                try:
                    det = scrape_attempt_details(ctx, numeric_cid, content_id, aid)
                except Exception:
                    det = {"files": [], "graded": False, "grade": None}
                grade_str = f" {det['grade']}/100" if det["grade"] else (" (ungraded)" if not det["graded"] else "")
                click.echo(f"  {em(f'Attempt {anum}')}  {ts[:25]}{grade_str}")
                click.echo(f"           {len(det['files'])} file(s)")
                print()
        return

    # Must be an attempt number
    try:
        anum = int(attempt_arg)
    except ValueError:
        click.secho(f"❌  Invalid: {attempt_arg}", fg="red")
        sys.exit(1)

    # Details of specific attempt
    atts = _safe_attempts(ctx, numeric_cid, content_id)
    att_map = {a: aid for aid, (a, _) in atts}
    if anum not in att_map:
        click.secho(f"❌  Attempt {anum} not found. Available: {list(att_map.keys())}", fg="red")
        sys.exit(1)

    aid = att_map[anum]
    try:
        details = scrape_attempt_details(ctx, numeric_cid, content_id, aid)
    except Exception as e:
        click.secho(f"  ⚠ Error loading details: {e}", fg="yellow")
        details = {"timestamp": "", "files": [], "graded": False,
                   "grade": None, "comment": None, "comment_date": None}

    ts = details["timestamp"]
    files = details["files"]
    graded = details["graded"]
    grade = details["grade"]
    comment = details["comment"]
    comment_date = details["comment_date"]

    click.secho(f"\n  Assignment {content_id} - Attempt {anum}\n", fg="cyan", bold=True)
    click.echo(f"  Timestamp:  {ts or 'unknown'}")
    click.echo(f"  Status:     {'graded' if graded else 'ungraded'}")
    if grade:
        click.echo(f"  Grade:      {grade}/100")
    if comment_date:
        click.echo(f"  Feedback:   {comment_date}")
    if comment:
        click.echo(f"  {comment[:100]}")
    click.echo(f"  Files:      {len(files)}")
    for fname, href in files:
        click.echo(f"    • {fname[:60]}")

    if download_flag:
        out_dir = Path(output_dir) / slugify(f"assignment_{content_id}")
        out_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"\n  Downloading to {out_dir}...")
        for fname, href in files:
            stem, ext = os.path.splitext(fname)
            out_path = out_dir / f"attempt{anum}_{stem}{ext}"
            if out_path.exists():
                click.echo(f"    (exists: {out_path.name})")
                continue
            try:
                download_file(out_path, href, session_cookies)
                size = out_path.stat().st_size
                click.secho(f"    ✓ {out_path.name} ({size:,})", fg="green")
            except Exception as e:
                click.secho(f"    ✗ {fname}: {e}", fg="red")


# ── CLI group + commands ───────────────────────────────────────────────

@click.group()
@click.pass_context
def cli(ctx):
    """BB CLI - SUSTech Blackboard Assignment Automation"""
    ctx.ensure_object(dict)


# ── Session commands ────────────────────────────────────────────────────────

@cli.command(name="session")
@click.argument("cmd", default="check", type=click.Choice(["check", "login", "refresh"]))
def session_cmd(cmd):
    """
    Manage BB session: check, login, or refresh.

    Examples:
      bb.py session          # check session validity
      bb.py session check   # same as above
      bb.py session refresh # re-authenticate via CAS
      bb.py session login   # manual browser login
    """
    if cmd == "check":
        ok, reason = _bb.check()
        if ok:
            click.secho("✅ Session valid", fg="green")
        else:
            click.secho(f"❌ {reason}", fg="red")
            sys.exit(1)
    elif cmd == "refresh":
        click.secho("Refreshing session via CAS...", fg="cyan")
        ok = _bb.refresh()
        if ok:
            click.secho("✅ Session refreshed", fg="green")
        else:
            click.secho("❌ Refresh failed. Try: bb.py session login", fg="red")
            sys.exit(1)
    elif cmd == "login":
        click.secho("Opening browser for manual CAS login...", fg="cyan")
        _bb.login()
        click.secho("✅ Login complete", fg="green")


@cli.command(name="courses")
@click.argument("query", default="", required=False)
def courses_cmd(query):
    """List all courses, or search by name/ID."""
    all_courses = list_courses()
    if not all_courses:
        click.secho("❌  No courses found.", fg="red")
        return
    results = find_course(query) if query else sorted(all_courses, key=lambda x: x[1])
    last = get_last_course()
    last_cid = last[0] if last else None
    click.secho(f"\n📚  Courses", fg="cyan", bold=True)
    if query:
        click.secho(f"   Search: '{query}' → {len(results)} result(s)\n", fg="white")
    else:
        click.secho(f"   {len(results)} course(s)\n", fg="white")
    for cid, name in results:
        marker = " ▶" if cid == last_cid else ""
        click.echo(f"  {get_course_numeric_id(cid):<6}  {name}{marker}")
    click.echo("")


@cli.command(name="search")
@click.option("-c", "--course", help="Filter by course name (substring match)")
@click.option("-t", "--type", "type_filter", multiple=True,
              help="Filter by item type. Options: content_page, tool_page, tool_link, file, submission, gradebook, inline_view, bb_content, external, other")
@click.option("-s", "--text", help="Search in item titles (substring match)")
@click.option("-C", "--content", "content_text", help="Search in item content text")
@click.option("-a", "--has-attachments", "has_attachments", is_flag=True,
              help="Only show items with file attachments")
@click.option("--hide", "hide_types", multiple=True, help="Hide items of this type")
@click.option("--show", "show_types", multiple=True, help="Show ONLY items of this type")
@click.option("--sort", "sort_by", default="course", type=click.Choice(["course", "type", "title"]),
              help="Sort order (default: course)")
@click.option("-o", "--output", "output_fmt", default="text", type=click.Choice(["text", "json"]),
              help="Output format")
@click.option("-v", "--verbose", is_flag=True, help="Show more detail per item")
@click.option("-r", "--refresh", is_flag=True, help="Bust cache and rescrape BB")
def search_cmd(course, type_filter, text, content_text, has_attachments,
               hide_types, show_types, sort_by, output_fmt, verbose, refresh):
    """Search and filter BB items (fully dynamic - live scrape)."""
    load_session_or_exit()
    from .query import discover_all_items, format_item
    from _cache import invalidate_all

    if refresh:
        if course:
            # Invalidate only pages for the matching course(s)
            from courses import list_courses, find_course
            courses = find_course(course) if course else list_courses()
            for cid, _ in courses:
                invalidate_all(f"discover_pages_{cid}")
                invalidate_all(f"page_items_")
        else:
            invalidate_all()
        click.secho("  Cache cleared.", fg="yellow", err=True)

    def progress(done, total):
        if total > 3:
            click.secho(f"  Scanning pages: {done}/{total}", fg="cyan", err=True)

    results_list = discover_all_items(
        course_filter=course,
        text_filter=text,
        content_text=content_text,
        type_filter=list(type_filter) if type_filter else None,
        has_attachments=has_attachments,
        hide_types=list(hide_types) if hide_types else None,
        show_types=list(show_types) if show_types else None,
        progress=progress,
        refresh=refresh,
    )

    # Sort
    if sort_by == "type":
        results_list.sort(key=lambda u: (u.get("type", ""), u["course"], u["title"]))
    elif sort_by == "title":
        results_list.sort(key=lambda u: u["title"].lower())
    else:  # course (default)
        results_list.sort(key=lambda u: (u["course"], u.get("type", ""), u["title"]))

    if output_fmt == "json":
        print(json.dumps(results_list, ensure_ascii=False, indent=2))
    else:
        if not results_list:
            click.secho("No items match the search criteria.", fg="yellow")
            return
        click.secho(f"\n🔍 Search Results ({len(results_list)} item(s))\n", fg="cyan", bold=True)
        for u in results_list:
            format_item(u, verbose=verbose)


@cli.command(name="types")
@click.option("-c", "--course", "course_filter", help="Filter by course name")
@click.option("-r", "--refresh", is_flag=True, help="Bust cache and rescrape BB")
def types_cmd(course_filter, refresh):
    """Show BB item type statistics (fully dynamic - live scrape)."""
    load_session_or_exit()
    from .query import type_stats_items, print_stats
    from _cache import invalidate_all

    if refresh:
        if course_filter:
            from courses import find_course, list_courses
            courses = find_course(course_filter) if course_filter else list_courses()
            for cid, _ in courses:
                invalidate_all(f"discover_pages_{cid}")
                invalidate_all(f"page_items_")
        else:
            invalidate_all()
        click.secho("  Cache cleared.", fg="yellow", err=True)

    def progress(done, total):
        if total > 3:
            click.secho(f"  Scanning pages: {done}/{total}", fg="cyan", err=True)

    stats = type_stats_items(course_filter=course_filter, progress=progress)
    print_stats(stats)


@cli.command(name="page")
@click.argument("content_id")
@click.option("-c", "--course", "course_id", help="Course ID (numeric). Auto-resolved if omitted.")
@click.option("-v", "--verbose", is_flag=True, help="Show full description and video URL")
def page_cmd(content_id, course_id, verbose):
    """
    Show all items inside a BB content page.

    Calls preview_page(content_id) to scrape the page live and list its items.

    Example:
      bb.py page 610786             # items in page 610786
      bb.py page 610786 -c 8328    # with explicit course ID
      bb.py page 610786 -v         # verbose (show descriptions)
    """
    load_session_or_exit()
    click.secho(f"\n📄 Page {content_id}\n", fg="cyan", bold=True)
    try:
        items = preview_page(content_id, course_id)
    except Exception as e:
        click.secho(f"❌  Error fetching page: {e}", fg="red")
        sys.exit(1)

    if not items:
        click.secho("  No items found on this page.", fg="yellow")
        return

    for item in items:
        type_icon = {
            "file": "📄", "video": "🎬", "homework": "📝",
            "folder": "📁", "inline": "🖼", "link": "🔗",
            "text": "📃", "unknown": "❓",
        }.get(item.TYPE, "?")
        click.echo(f"  {type_icon} [{item.sub_id}] {item.title}")
        click.echo(f"       type={item.TYPE}")

        if verbose:
            if hasattr(item, "files") and item.files:
                for name, url in item.files:
                    click.echo(f"       📎 {name}")
            if hasattr(item, "video_url") and item.video_url:
                click.echo(f"       🎬 video: {item.video_url}")
            if hasattr(item, "bb_url") and item.bb_url:
                click.echo(f"       📁 → {item.bb_url}")
            if item.description:
                click.echo(f"       💬 {item.description[:120]}")
            if hasattr(item, "deadline") and item.deadline:
                click.echo(f"       ⏰ deadline: {item.deadline}")
            if hasattr(item, "submission_count") and item.submission_count > 0:
                click.echo(f"       ✅ {item.submission_count} submission(s)")
        print()


@cli.command(name="course")
@click.argument("course_id")
@click.argument("sub", default=None, required=False)
@click.argument("content_id", default=None, required=False)
@click.argument("attempt_arg", default=None, required=False)
@click.option("--download", "download_flag", is_flag=True, default=False,
              help="Download the specified attempt")
@click.option("-o", "--output", "output_dir", default="./downloads",
              help="Output directory")
def course_cmd(course_id, sub, content_id, attempt_arg, download_flag, output_dir):
    """
    View and manage course assignments and submission attempts.

    Examples:
      bb_cli.py course 8053 assignments                    # list all + attempts overview
      bb_cli.py course 8053 assignment status             # all: submitted/not submitted
      bb_cli.py course 8053 assignment 619093              # all attempts for that assignment
      bb_cli.py course 8053 assignment 619093 status       # status of specific assignment
      bb_cli.py course 8053 assignment 619093 attempts     # all attempts (explicit)
      bb_cli.py course 8053 assignment 619093 2            # details of attempt 2
      bb_cli.py course 8053 assignment 619093 2 --download # download attempt 2
    """
    cookies = load_session_or_exit()

    results = find_course(course_id)
    if not results:
        click.secho(f"❌  No course found for '{course_id}'", fg="red")
        sys.exit(1)
    course_id_str, course_name = results[0]
    numeric_cid = get_course_numeric_id(course_id_str)
    set_last_course(course_id_str)

    all_assignments = discover_assignments_for_course(course_id_str) if needs_assignments else []

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx_b = browser.new_context()
        ctx_b.add_cookies(cookies)
        try:
            if sub == "assignments" or sub is None:
                _list_assignments(ctx_b, numeric_cid, course_name, all_assignments)
            elif sub == "assignment":
                if content_id is None:
                    click.secho("❌  assignment needs a content_id or 'status'", fg="red")
                    sys.exit(1)
                if content_id == "status":
                    _all_status(ctx_b, numeric_cid, course_name, all_assignments)
                else:
                    _single_assignment(ctx_b, cookies, numeric_cid,
                                       content_id, attempt_arg, download_flag, output_dir)
            else:
                click.secho(f"❌  Unknown: {sub}", fg="red")
                sys.exit(1)
        finally:
            browser.close()


@cli.command(name="submit")
@click.argument("content_id")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("-c", "--course", "course_id", help="Course ID (numeric). Auto-resolved if omitted.")
@click.option("--comment", "comment", default=None, help="Optional comment text")
def submit_cmd(content_id, file_path, course_id, comment):
    """
    Submit a file to a BB assignment.

    Example:
      bb.py submit 622821 /tmp/hw.pdf          # auto-detect course
      bb.py submit 622821 /tmp/hw.pdf -c 8221  # explicit course
    """
    from download import submit_homework
    load_session_or_exit()
    try:
        ok = submit_homework(content_id, file_path, course_id=course_id, comment=comment)
        if ok:
            click.secho("✓  Submission successful!", fg="green")
        else:
            click.secho("⚠  Submission returned without confirmation.", fg="yellow")
    except Exception as e:
        click.secho(f"❌  Submission failed: {e}", fg="red")
        sys.exit(1)


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""
SUSTech Survival CLI — unified entry point.

Usage:
    sustech bb <subcommand>
    sustech tis <subcommand>
    sustech lib <subcommand>
    sustech --help

Examples:
    sustech bb session check
    sustech bb courses
    sustech bb search "homework"
    sustech tis courses
    sustech lib login
    sustech lib check
"""
import sys
from pathlib import Path

_src = Path(__file__).parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import click

from sustech_survival import bb as bb_mod
from sustech_survival.bb.query import format_item
from sustech_survival import tis as tis_mod
from sustech_survival import lib as lib_mod


@click.group()
@click.version_option(prog_name="sustech")
def cli():
    """SUSTech Survival — unified CLI for BB, TIS, and Library."""
    pass


# ── BB ────────────────────────────────────────────────────────────────────────

@cli.group("bb")
def bb():
    """Blackboard commands."""
    pass


@bb.command("session")
@click.argument("action", default="check", type=click.Choice(["check", "login", "refresh"]))
def bb_session(action):
    """Check, login, or refresh BB session."""
    if action == "check":
        ok, reason = bb_mod.check_session()
        click.echo(f"{'OK' if ok else 'FAIL'}: {reason}")
    elif action == "login":
        ok = bb_mod.login()
        click.echo(f"{'OK' if ok else 'FAIL'}: login {'succeeded' if ok else 'failed'}")
    elif action == "refresh":
        ok = bb_mod.refresh()
        click.echo(f"{'OK' if ok else 'FAIL'}: refresh {'succeeded' if ok else 'failed'}")


@bb.command("courses")
@click.argument("query", required=False)
def bb_courses(query):
    """List BB courses, optionally filtered by QUERY."""
    courses = bb_mod.list_courses()
    if query:
        courses = [c for c in courses if query.lower() in c[1].lower()]
    for cid, name in courses:
        click.echo(f"  {cid}: {name}")


@bb.command("search")
@click.option("--course", help="Filter by course name or ID")
@click.option("--type", "type_filter", help="Filter by item type (homework, file, video, ...)")
@click.option("--has-attachments", is_flag=True, help="Items with attachments only")
@click.argument("text", required=False)
def bb_search(text, course, type_filter, has_attachments):
    """Search BB items (live scrape). TEXT is matched against item titles."""
    kwargs = {}
    if text:
        kwargs["text"] = text
    if course:
        kwargs["course"] = course
    if type_filter:
        kwargs["type_filter"] = [type_filter]
    if has_attachments:
        kwargs["has_attachments"] = True

    results = bb_mod.search(**kwargs)
    if hasattr(results, '__iter__') and results and isinstance(results[0], dict):
        # discover_all_items returns dicts — use format_item like the CLI
        for item in results:
            format_item(item)
    else:
        # Fallback for any legacy Item objects
        for item in results:
            click.echo(f"  {item.id_}: [{item.type_}] {item.title}")


@bb.command("submit")
@click.argument("content_id")
@click.argument("filepath", required=False, type=click.Path(exists=True))
@click.option("--course", help="Course ID")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.option("--text", "text_content", help="Text content to submit")
@click.option("--files", "file_paths", multiple=True, help="Additional file paths (can repeat)")
def bb_submit(content_id, filepath, course, yes, text_content, file_paths):
    """Submit FILE(s) and/or TEXT to BB assignment CONTENT_ID."""
    course_kw = {"course_id": course} if course else {}
    text_kw = {"text_content": text_content} if text_content else {}
    # Combine filepath argument with --files options
    all_paths = list(file_paths or [])
    if filepath:
        all_paths.insert(0, filepath)
    if not all_paths and not text_content:
        click.echo("Error: provide FILE and/or --text and/or --files")
        sys.exit(1)
    if not yes and (all_paths or text_content):
        click.confirm(f"Submit to {content_id}?", abort=True)
    result = bb_mod.submit_homework(content_id, file_paths=all_paths, **course_kw, **text_kw)
    click.echo(f"OK: {result}")


# ── TIS ──────────────────────────────────────────────────────────────────────

@cli.group("tis")
def tis():
    """TIS commands."""
    pass


@tis.command("courses")
@click.option("--out", "out_path", help="Output CSV path")
def tis_courses(out_path):
    """Fetch and save TIS courses."""
    result = tis_mod.courses(out_path=out_path)
    click.echo(f"OK: {result}")


@tis.command("login")
def tis_login():
    """Headless CAS login to TIS."""
    ok = tis_mod.login()
    click.echo(f"{'OK' if ok else 'FAIL'}: TIS login {'succeeded' if ok else 'failed'}")


# ── Lib ───────────────────────────────────────────────────────────────────────

@cli.group("lib")
def lib():
    """Library commands."""
    pass


@lib.command("login")
@click.option("--headless", is_flag=True, help="Headless mode")
def lib_login(headless):
    """Login to library Primo."""
    ok = lib_mod.login(headless=headless)
    click.echo(f"{'OK' if ok else 'FAIL'}: lib login {'succeeded' if ok else 'failed'}")


@lib.command("check")
def lib_check():
    """Check library session validity."""
    ok, reason = lib_mod.check()
    click.echo(f"{'OK' if ok else 'FAIL'}: {reason}")


# ── passthrough to bb CLI ──────────────────────────────────────────────────────

@cli.command("help")
@click.argument("command", required=False)
def help_cmd(command):
    """Show detailed help for COMMAND (bb, tis, lib)."""
    if command == "bb":
        click.echo(bb.get_help(None))
    elif command == "tis":
        click.echo(tis.get_help(None))
    elif command == "lib":
        click.echo(lib.get_help(None))
    else:
        click.echo(cli.get_help(None))


if __name__ == "__main__":
    cli()

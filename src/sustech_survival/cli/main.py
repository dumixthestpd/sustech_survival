"""
sustech-survival unified CLI.

Single entry point for all submodules. Mirrors the ``git <subcmd>`` style::

    sustech bb courses              # Blackboard
    sustech tis grades              # TIS
    sustech ws list                 # Student exchange
    sustech transit facilities      # Campus bus
    sustech faculty depts           # Faculty directory
    sustech context                 # What's happening now
    sustech webui serve             # Unified web UI
    sustech --version

Every Click group is defined right here in this module. For the heavyweight
CLIs (bb, tis, ws, nces) we re-mount the commands from each module's own
``cli.py`` via ``_mount``. For the rest, commands are inline and call the
module's Python API directly — no per-module Click wrapper needed.

A submodule dependency that fails to import shows as ``(unavailable: ...)``
in help text but doesn't crash the top-level CLI.
"""
from __future__ import annotations

import json as _json
import sys
import webbrowser
from datetime import date
from typing import Optional

import click

from .._version import __version__


# ── Mount helpers ───────────────────────────────────────────

def _mount(module: str, target: click.Group) -> None:
    """Import ``<module>.cli:cli`` and copy its commands onto ``target``.

    On ImportError, sets ``target.help`` to the reason and returns.
    """
    try:
        mod = __import__(f"sustech_survival.{module}.cli", fromlist=["cli"])
        sub_cli: Optional[click.Command] = getattr(mod, "cli", None)
    except Exception as e:
        target.help = f"(unavailable: {e})"
        target.short_help = f"{module} (unavailable)"
        return
    if sub_cli is None:
        target.help = (
            f"(unavailable: no `cli` symbol in sustech_survival.{module}.cli)"
        )
        return
    if isinstance(sub_cli, click.Group):
        for name, cmd in sub_cli.commands.items():
            target.add_command(cmd, name=name)
    else:
        target.add_command(sub_cli, name="run")


def _mount_into(parent: click.Group, child_name: str, module: str) -> click.Group:
    """Create a child Click group under ``parent``. Returns the new group."""
    child = click.Group(name=child_name)
    try:
        mod = __import__(f"sustech_survival.{module}.cli", fromlist=["cli"])
        sub_cli = getattr(mod, "cli", None)
    except Exception as e:
        child.help = f"(unavailable: {e})"
        child.short_help = f"{child_name} (unavailable)"
    else:
        if isinstance(sub_cli, click.Group):
            for name, cmd in sub_cli.commands.items():
                child.add_command(cmd, name=name)
        elif sub_cli is not None:
            child.add_command(sub_cli, name="run")
        else:
            child.help = (
                f"(unavailable: no `cli` symbol in "
                f"sustech_survival.{module}.cli)"
            )
    parent.add_command(child)
    return child


# ========================================================================
# Inline helper — json or plain text output
# ========================================================================

def _pp(obj, *, as_json: bool, key: str | None = None) -> None:
    """Print ``obj`` as JSON (when ``as_json``) or its ``__str__``."""
    if as_json:
        click.echo(_json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        click.echo(str(obj[key] if key else obj))


# ========================================================================
# Groups that re-mount from the module's own cli.py (bb, tis, ws, nces)
# ========================================================================

@click.group(name="bb")
def bb_cmd() -> None:
    """Blackboard — courses, assignments, submissions."""


@click.group(name="tis")
def tis_cmd() -> None:
    """TIS — Teaching Information System (courses, grades, evals)."""


@click.group(name="ws")
def ws_cmd() -> None:
    """WS — student exchange / abroad programs."""


@click.group(name="nces", help="NCES — community course eval (optional [nces] extra).")
def nces_cmd() -> None:
    pass


_mount("bb", bb_cmd)
_mount("tis", tis_cmd)
_mount("ws", ws_cmd)
_mount_into(tis_cmd, "classroom", "tis.classroom")
_mount("nces", nces_cmd)


# ========================================================================
# transit — campus navigation and bus data
# ========================================================================

@click.group(name="transit", help="Campus bus + navigation (live GPS, route).")
def transit_cmd() -> None:
    pass


@transit_cmd.command(name="facilities", help="List all known buildings + gates.")
@click.option("--json", "as_json", is_flag=True)
def transit_facilities(as_json: bool) -> None:
    from .transit import transit as _t
    facs = _t.list_facilities()
    if as_json:
        click.echo(_json.dumps([f.to_dict() for f in facs], ensure_ascii=False, indent=2))
    else:
        for f in facs:
            click.echo(f"  {f}")


@transit_cmd.command(name="find", help="Fuzzy name search.")
@click.argument("query")
@click.option("--limit", type=int, default=10)
@click.option("--json", "as_json", is_flag=True)
def transit_find(query: str, limit: int, as_json: bool) -> None:
    from .transit import transit as _t
    hits = _t.find_facility(query)[:limit]
    _pp(hits, as_json=as_json)


@transit_cmd.command(name="stops", help="List bus stops.")
@click.option("--json", "as_json", is_flag=True)
def transit_stops(as_json: bool) -> None:
    from .transit import transit as _t
    from .transit.schema import BusLine
    stops = _t.get_bus_stops()
    _pp(stops, as_json=as_json)


@transit_cmd.command(name="live", help="Poll live bus positions.")
@click.option("--json", "as_json", is_flag=True)
def transit_live(as_json: bool) -> None:
    from .transit import transit as _t
    buses = _t.get_live_positions()
    _pp(buses, as_json=as_json)


@transit_cmd.command(name="route", help="Shortest path between two facilities.")
@click.argument("from_", metavar="FROM")
@click.argument("to_", metavar="TO")
@click.option("--json", "as_json", is_flag=True)
def transit_route(from_: str, to_: str, as_json: bool) -> None:
    from .transit import transit as _t
    r = _t.shortest_path(from_, to_)
    _pp(r.to_markdown() if hasattr(r, "to_markdown") else r, as_json=as_json)


# ========================================================================
# faculty — live SUSTech faculty directory
# ========================================================================

@click.group(name="faculty", help="SUSTech faculty directory (live lookup).")
def faculty_cmd() -> None:
    pass


@faculty_cmd.command(name="depts", help="List 50+ department names.")
def faculty_depts() -> None:
    from .faculty import faculty as _fc
    click.echo(f"# {len(_fc.departments)} known departments")
    for d in _fc.departments:
        click.echo(f"  {d}")


@faculty_cmd.command(name="list", help="List faculty in a department.")
@click.argument("dept")
@click.option("--full", is_flag=True, help="Fetch all profiles (~30-70s).")
@click.option("--limit", type=int, default=None)
def faculty_list(dept: str, full: bool, limit: int | None) -> None:
    from .faculty import faculty as _fc
    rows = _fc.list(dept, full=full, limit=limit)
    mode = "full profiles" if full else "lightweight"
    click.echo(f"# {dept}  ({len(rows)} faculty — {mode})")
    for f in rows:
        click.echo(f"  {f.name} [{f.title or ''}] /{f.slug}/")


@faculty_cmd.command(name="get", help="Fetch one profile by slug.")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True)
def faculty_get(slug: str, as_json: bool) -> None:
    from .faculty import faculty as _fc
    f = _fc.get(slug)
    _pp(f.to_dict() if as_json else f.to_markdown(), as_json=as_json)


@faculty_cmd.command(name="search", help="Live keyword search.")
@click.argument("query")
@click.option("--dept", default=None, help="Restrict to one department.")
@click.option("--limit", type=int, default=10)
def faculty_search(query: str, dept: str | None, limit: int) -> None:
    from .faculty import faculty as _fc
    hits = _fc.search(query, dept=dept, limit=limit)
    scope = dept or "ALL"
    click.echo(f"# search: {query!r}  scope={scope}  → {len(hits)} hits")
    for f in hits:
        click.echo(f"  {f.name}  ({f.title or '?'}) — score={f.relevance_score}")


@faculty_cmd.command(name="render", help="AI-readable Markdown for one profile.")
@click.argument("slug")
def faculty_render(slug: str) -> None:
    from .faculty import faculty as _fc
    click.echo(_fc.render(slug))


# ========================================================================
# booking — e-hall 场地预约
# ========================================================================

@click.group(name="booking", help="E-Hall 场地预约 (booking.sustech.edu.cn).")
def booking_cmd() -> None:
    pass


@booking_cmd.command(name="whoami", help="Print current user profile.")
@click.option("--json", "as_json", is_flag=True)
def booking_whoami(as_json: bool) -> None:
    from .booking import booking as _client
    c = _client()
    u = c.whoami()
    _pp(u, as_json=as_json)


@booking_cmd.command(name="rooms", help="List all rooms (optional substring filter).")
@click.argument("keyword", required=False, default="")
@click.option("--available", is_flag=True, help="Only show available rooms.")
@click.option("--json", "as_json", is_flag=True)
def booking_rooms(keyword: str, available: bool, as_json: bool) -> None:
    from .booking import booking as _client
    c = _client()
    rooms = c.rooms(keyword=keyword)
    if available:
        rooms = [r for r in rooms if r.is_available]
    _pp([r.name for r in rooms], as_json=as_json)


@booking_cmd.command(name="my-meetings", help="List my current bookings.")
@click.option("--json", "as_json", is_flag=True)
def booking_my_meetings(as_json: bool) -> None:
    from .booking import booking as _client
    c = _client()
    meetings = c.my_meetings()
    _pp(meetings, as_json=as_json)


# ========================================================================
# pms — campus printing system
# ========================================================================

@click.group(name="pms", help="联创 PMS — campus print / scan / copy.")
def pms_cmd() -> None:
    pass


@pms_cmd.command(name="check", help="Verify PMS auth.")
def pms_check() -> None:
    from sustech_survival.sso.authlib.pms import PMSAuth
    auth = PMSAuth()
    ok, msg = auth.ensure()
    click.echo(("✅ " if ok else "❌ ") + msg)


@pms_cmd.command(name="stations", help="List campus printers.")
@click.argument("group", required=False, default=None)
@click.option("--json", "as_json", is_flag=True)
def pms_stations(group: str | None, as_json: bool) -> None:
    from .pms import PMSClient
    from sustech_survival.sso.authlib.pms import PMSAuth
    auth = PMSAuth()
    auth.ensure()
    c = PMSClient(auth.session)
    stations = c.list_stations()
    _pp([s.to_dict() if as_json else s.name for s in stations], as_json=as_json)


@pms_cmd.command(name="jobs", help="List uploaded-but-not-printed jobs.")
@click.option("--json", "as_json", is_flag=True)
def pms_jobs(as_json: bool) -> None:
    from .pms import PMSClient
    from sustech_survival.sso.authlib.pms import PMSAuth
    auth = PMSAuth()
    auth.ensure()
    c = PMSClient(auth.session)
    jobs = c.list_print_jobs()
    _pp([j.to_dict() if as_json else f"[{j.dw_job_id}] {j.file_name}" for j in jobs],
        as_json=as_json)


# ========================================================================
# lib-booking — IC library booking
# ========================================================================

@click.group(name="lib-booking", help="IC library booking (research rooms, etc).")
def lib_booking_cmd() -> None:
    pass


@lib_booking_cmd.command(name="whoami", help="Show current user info.")
@click.option("--json", "as_json", is_flag=True)
def lib_booking_whoami(as_json: bool) -> None:
    from .lib.booking import lib_booking
    c = lib_booking()
    u = c.whoami()
    _pp(u.name if hasattr(u, 'name') else str(u), as_json=as_json)


@lib_booking_cmd.command(name="home-summary", help="Idle room summary (homepage).")
@click.option("--json", "as_json", is_flag=True)
def lib_booking_home_summary(as_json: bool) -> None:
    from .lib.booking import lib_booking
    c = lib_booking()
    summary = c.home_summary()
    _pp(summary, as_json=as_json)


@lib_booking_cmd.command(name="policy", help="Print the library booking policy.")
def lib_booking_policy() -> None:
    from .lib.booking import lib_booking
    c = lib_booking()
    from .lib.booking.schema import POLICY_TEXT
    click.echo(POLICY_TEXT)


# ========================================================================
# selectcourse — TIS course selection
# ========================================================================

@click.group(name="selectcourse", help="TIS course selection — browse, cart.")
def selectcourse_cmd() -> None:
    pass


@selectcourse_cmd.command(name="list", help="Browse course catalog.")
@click.argument("keyword", required=False, default="")
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--json", "as_json", is_flag=True)
def selectcourse_list(keyword: str, xn: str | None, xq: str | None,
                      as_json: bool) -> None:
    from .selectcourse import SelectCourseClient
    sc = SelectCourseClient(xn=xn, xq=xq)
    courses = sc.list_courses(keyword=keyword)
    _pp([{"code": c.code, "name": c.name, "class_group": c.class_group,
          "teachers": c.teachers, "credits": c.credits}
         for c in courses[:50]], as_json=as_json)
    if not as_json:
        click.echo(f"\n({len(courses)} total, showing first 50)")


@selectcourse_cmd.command(name="enrolled", help="Your enrolled courses.")
@click.option("--json", "as_json", is_flag=True)
def selectcourse_enrolled(as_json: bool) -> None:
    from .selectcourse import SelectCourseClient
    sc = SelectCourseClient(xn="2025-2026", xq="2")
    enrolled = sc.my_courses()
    _pp(enrolled, as_json=as_json)


# ========================================================================
# papers — academic paper search
# ========================================================================

@click.group(name="papers", help="Academic paper search (CrossRef).")
def papers_cmd() -> None:
    pass


@papers_cmd.command(name="search", help="Search CrossRef for papers.")
@click.argument("query")
@click.option("--max", "max_results", type=int, default=10)
@click.option("--min-year", type=int, default=None)
def papers_search(query: str, max_results: int, min_year: int | None) -> None:
    from .papers.search import crossref_search
    papers = crossref_search(query, max_results=max_results, min_year=min_year)
    for i, p in enumerate(papers, 1):
        click.echo(f"[{i}] {p.title}")
        click.echo(f"    {', '.join(p.authors[:3])} ({p.year or '?'})")
        if p.doi:
            click.echo(f"    DOI: {p.doi}")


# ========================================================================
# webui — the Flask app is mounted here as subcommands
# ========================================================================

@click.group(name="webui", help="Unified Flask web UI (TIS + transit).")
def webui_cmd() -> None:
    pass


@webui_cmd.command(name="serve", help="Start the web UI.")
@click.option("--port", "-p", type=int, default=None, help="Port (default 61019).")
@click.option("--host", "-H", default="0.0.0.0", show_default=True)
@click.option("--transit-data", default=None,
              help="Directory of exported transit GeoJSON.")
@click.option("--debug/--no-debug", default=False)
def webui_serve(port: Optional[int], host: str,
                transit_data_dir: Optional[str], debug: bool) -> None:
    from .webui.app import run, DEFAULT_PORT
    run(host=host, port=port or DEFAULT_PORT,
        transit_data_dir=transit_data_dir, debug=debug)


@webui_cmd.command(name="open", help="Open UI in default browser.")
@click.option("--port", "-p", type=int, default=61019, show_default=True)
@click.option("--path", "-P", default="/", show_default=True)
def webui_open(port: int, path: str) -> None:
    if not path.startswith("/"):
        path = "/" + path
    webbrowser.open(f"http://localhost:{port}{path}")


# ========================================================================
# context — daily-use snapshot (inline, no module cli.py)
# ========================================================================

@click.command(name="context", help="What's happening right now.")
@click.option("--level", "-l", type=click.Choice(["terse", "normal", "verbose"]),
              default="terse", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def context_cmd(level: str, as_json: bool) -> None:
    from .context import Context
    ctx = Context()
    if as_json:
        click.echo(_json.dumps(ctx.to_dict(level=level),
                               ensure_ascii=False, indent=2))
    else:
        click.echo(ctx.to_str(level=level))


# ========================================================================
# Top-level group — register everything under `sustech`
# ========================================================================


def build_cli() -> click.Group:
    """Create and return the ``sustech`` Click group with all commands.

    Called by ``cli/__init__.py``. Separated so the module can be imported
    without side-effects.
    """
    @click.group(
        name="sustech",
        help="sustech-survival unified CLI. Use `sustech <subcommand> --help` for details.",
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    @click.version_option(__version__, "-V", "--version", prog_name="sustech")
    def cli() -> None:
        """Top-level command group. Use `sustech <subcommand>` to dispatch."""

    cli.add_command(bb_cmd)
    cli.add_command(tis_cmd)
    cli.add_command(ws_cmd)
    cli.add_command(transit_cmd)
    cli.add_command(context_cmd)
    cli.add_command(webui_cmd)
    cli.add_command(nces_cmd)
    cli.add_command(faculty_cmd)
    cli.add_command(booking_cmd)
    cli.add_command(pms_cmd)
    cli.add_command(lib_booking_cmd)
    cli.add_command(selectcourse_cmd)
    cli.add_command(papers_cmd)
    return cli
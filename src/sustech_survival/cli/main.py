"""
sustech_survival unified CLI.

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
_mount("nces", nces_cmd)
_mount_into(tis_cmd, "classroom", "tis.classroom")


# ========================================================================
# sso — shared credentials + auth
# ========================================================================

@click.group(name="sso", help="SSO — shared CAS auth backbone.")
def sso_cmd() -> None:
    pass


@sso_cmd.group(name="creds", help="Shared credentials file (set / status).")
def sso_creds_cmd() -> None:
    pass


@sso_creds_cmd.command(name="set", help="Write the shared credentials file.")
@click.option("--sid", default=None, help="SUSTech SID (e.g. 12410000).")
@click.option("--pass", "password", "--password", default=None,
              help="SUSTech password (or prompt, hidden).")
def sso_creds_set(sid: Optional[str], password: Optional[str]) -> None:
    """Write ``sid:password`` to the shared credentials file (0600).

    Usage: ``sustech sso creds set --sid 12410000 --pass '...'``
    Omitting ``--sid`` or ``--pass`` prompts for them (password hidden).
    """
    from ..sso.authorizer import write_credentials

    if not sid:
        sid = click.prompt("SUSTech SID", type=str)
    if not password:
        password = click.prompt("SUSTech password", hide_input=True,
                                confirmation_prompt=True)
    try:
        target = write_credentials(sid, password)  # default: ./credentials.txt (cwd)
    except Exception as e:  # noqa: BLE001 — surface a clean message
        click.secho(f"Failed to write credentials: {e}", fg="red")
        raise SystemExit(1)
    click.secho(f"✅ credentials written to {target} (mode 0600)", fg="green")


@sso_creds_cmd.command(name="status", help="Show the credentials path + existence.")
def sso_creds_status() -> None:
    """Print the resolved creds source and whether the file exists.

    Precedence: cred_set() (in-memory) > ./credentials.txt (cwd) >
    SUSTECH_CREDENTIALS env var. Never prints the password.
    """
    from ..sso.authorizer import resolve_creds_path, _IN_MEMORY_CREDS
    if _IN_MEMORY_CREDS is not None:
        click.secho("Credentials source: cred_set() (in memory)", bold=True)
        click.echo("File: n/a (in-memory override active)")
        click.echo("Set a file: `sustech sso creds set --sid 12410000` "
                   "(password prompts hidden).")
        return
    path = resolve_creds_path()
    click.secho(f"Credentials path: {path}", bold=True)
    click.echo(f"Exists: {path.exists()}")
    click.echo("Set them: `sustech sso creds set --sid 12410000` "
               "(password prompts hidden).")


@sso_creds_cmd.command(name="path", hidden=True, help="Print the resolved credentials path.")
def sso_creds_path() -> None:
    from ..sso.authorizer import resolve_creds_path
    click.echo(str(resolve_creds_path()))


@sso_cmd.command(name="check", help="Verify credentials against CAS (no service binding).")
def sso_check() -> None:
    """Validate that the stored SID+password authenticates on SUSTech CAS.

    Performs only the CAS accounting check (GET login page → POST creds →
    expect a ticket redirect). A 302/303 ``ticket=`` stub means VALID; a
    re-rendered login form means INVALID. Requires network + credentials.
    """
    from ..sso.authorizer import read_credentials, resolve_creds_path, AuthorizerError
    from ..exceptions import InvalidCredentials, NetworkError
    try:
        sid, pw = read_credentials()
    except AuthorizerError as e:
        click.secho(f"❌ {e}", fg="red")
        raise SystemExit(1)

    try:
        from ..sso.providers.cas import CASAuthorizer
    except Exception as e:  # noqa: BLE001
        click.secho(f"❌ cannot import CAS provider: {e}", fg="red")
        raise SystemExit(1)

    class _Probe(CASAuthorizer):
        BASE_URL = "https://cas.sustech.edu.cn"
        SERVICE_URL = "https://cas.sustech.edu.cn/cas/login?service=data"
        SUBMIT_VALUE = ""
        _idp_cas_base = "https://cas.sustech.edu.cn/cas/login"

    probe = _Probe()
    try:
        cookies = probe._get_ticket_cookies(sid, pw)
    except InvalidCredentials as e:
        click.secho(f"❌ INVALID — {sid} was rejected by CAS.", fg="red")
        raise SystemExit(2)
    except NetworkError as e:
        click.secho(f"❌ NETWORK — cannot reach CAS: {e}", fg="red")
        raise SystemExit(3)
    except Exception as e:  # noqa: BLE001
        click.secho(f"❌ CAS check failed: {e}", fg="red")
        raise SystemExit(4)

    click.secho(
        f"✅ VALID — {sid} authenticated on CAS "
        f"({len(cookies)} cookies returned; no service touched).",
        fg="green")


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
    sc = SelectCourseClient()  # defaults to the live academic term
    enrolled = sc.my_courses()
    _pp(enrolled, as_json=as_json)


@selectcourse_cmd.command(name="export-table",
                           help="Export picked sections as a structured schedule table.")
@click.argument("codes", nargs=-1)
@click.option("--keyword", default=None,
              help="Search the catalog by keyword instead of passing codes.")
@click.option("--xn", default=None, help="Academic year (e.g. 2025-2026). Default: current semester.")
@click.option("--xq", default=None, help="Term (1=fall, 2=spring, 3=summer). Default: current.")
@click.option("--format", "fmt", default="markdown",
              type=click.Choice(["markdown", "json", "csv"]),
              show_default=True)
@click.option("--output", "output", default=None,
              help="Output file path. Default: stdout.")
@click.option("--headcount/--no-headcount", default=True,
              help="Include headcount column (uses /component/queryHeadCount for non-zero values).")
def selectcourse_export_table(
    codes: tuple, keyword: str | None, xn: str | None, xq: str | None,
    fmt: str, output: str | None, headcount: bool,
) -> None:
    """Build a structured schedule table from picked course codes or a catalog search.

    Output formats:
      - markdown (default): human-readable, TUI-friendly
      - json: machine-readable (one object per section-span)
      - csv: import-friendly (one row per section-span)

    Examples:

        sustech selectcourse export-table MSE306 SS143
        sustech selectcourse export-table --keyword "electrochromic" --format csv
        sustech selectcourse export-table MSE306 --format json --output ~/Desktop/term.json
    """
    from ..selectcourse import SelectCourseClient
    from ..selectcourse.course import export_schedule_table
    # SelectCourseClient rejects None for xn/xq — let it use its own
    # defaults (currently "2025-2026" / "2") when user didn't pass --xn/--xq.
    if xn and xq:
        from ..semester import Semester
        sem = Semester(xn, xq)
        sc = SelectCourseClient(semester=sem)
    else:
        sc = SelectCourseClient()
    if keyword:
        courses = sc.search_campus(keyword=keyword)
        if not courses:
            click.echo(f"(no courses matched keyword={keyword!r})", err=True)
            raise SystemExit(1)
        # Filter to user-supplied codes if both given
        if codes:
            codes_set = set(c.upper() for c in codes)
            courses = [c for c in courses if c.code.upper() in codes_set]
            if not courses:
                click.echo(f"(keyword {keyword!r} matched but none of {codes!r} present)",
                           err=True)
                raise SystemExit(1)
    elif codes:
        courses = []
        for code in codes:
            found = sc.search_campus(keyword=code)
            if not found:
                click.echo(f"⚠️  no match for {code!r} — skipping", err=True)
                continue
            courses.extend(found)
    else:
        click.echo("pass course codes (e.g. MSE306 SS143) or --keyword", err=True)
        raise SystemExit(1)

    out = export_schedule_table(courses, format=fmt)
    if output:
        from pathlib import Path
        Path(output).write_text(out, encoding="utf-8")
        click.secho(f"✅ {len(courses)} section(s) → {output}", fg="green")
    else:
        click.echo(out)


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

# ``sustech webui`` alone = show help (never an implicit serve). Only an
# explicit ``sustech webui serve`` starts the server.
@click.group(
    name="webui",
    help="Unified Flask web UI (TIS + transit). Run `sustech webui serve` to start it.",
)
def webui_cmd() -> None:
    """Web-UI commands: serve, open, install, skins.

    `sustech webui` alone prints this help — nothing is started. Run
    `sustech webui serve` to start the server (or `sustech webui open`
    to open the default head in your browser).
    """


def _webui_serve_impl(port: Optional[int], host: str, skin: Optional[str],
                      skin_path: Optional[str], transit_data_dir: Optional[str],
                      debug: bool) -> None:
    """Shared implementation of `sustech webui serve`."""
    from ..webui.app import run, DEFAULT_PORT
    from ..webui import loader
    if skin_path:
        try:
            loader.skin_from_path(skin_path)     # validate up front
        except ValueError as e:
            click.secho(f"cannot serve --skin-path: {e}", fg="red")
            raise SystemExit(1)
    elif skin:
        try:
            loader.find_skin(skin)               # validate up front
        except KeyError as e:
            click.secho(f"cannot serve: {e}", fg="red")
            click.echo("  install a skin first, e.g. `sustech webui install default`, "
                       "or pass --skin <one-of-the-above>.")
            raise SystemExit(1)
    elif not loader.installed_skins():
        # Zero skins installed: still serve the built-in default head, but say
        # so and point at `install default` so the user owns a moddable copy.
        click.secho("no skins installed — serving the built-in default head.",
                    fg="yellow")
        click.echo("  tip: `sustech webui install default` copies it into your "
                   "on-disk skin cache so you can skin/mod it.")
    run(host=host, port=port or DEFAULT_PORT,
        transit_data_dir=transit_data_dir, skin=skin, skin_path=skin_path,
        debug=debug)


@webui_cmd.command(name="serve", help="Start the web UI.")
@click.option("--port", "-p", type=int, default=None, help="Port (default 20129).")
@click.option("--host", "-H", default="0.0.0.0", show_default=True)
@click.option("--transit-data", "transit_data_dir", default=None,
              help="Directory of exported transit GeoJSON.")
@click.option("--skin", "skin", default=None,
              help="Name of an installed skin to serve. Omit to use the first "
                   "installed skin (or the built-in default).")
@click.option("--skin-path", "skin_path", default=None,
              help="Serve a skin directly from a directory path (no install). "
                   "Wins over --skin / any installed skin.")
@click.option("--debug/--no-debug", default=False)
def webui_serve(port: Optional[int], host: str,
                transit_data_dir: Optional[str], skin: Optional[str],
                skin_path: Optional[str], debug: bool) -> None:
    """Start the web UI.

    ``--skin`` changes the active head on the spot: name any installed skin
    (see ``sustech webui skins``) and it becomes the served page immediately,
    without re-installing. If ``--skin`` names something unknown, serve exits
    with the list of installed skins and an install hint.

    ``--skin-path <dir>`` serves a skin straight from a directory on disk —
    no install/copy into the cache — and wins over ``--skin``. Use it to
    point at a skin under version control or a local copy you're still
    editing.
    """
    _webui_serve_impl(port=port, host=host, skin=skin, skin_path=skin_path,
                      transit_data_dir=transit_data_dir, debug=debug)


@webui_cmd.command(name="open", help="Open UI in default browser.")
@click.option("--port", "-p", type=int, default=20129, show_default=True)
@click.option("--path", "-P", default="/", show_default=True)
def webui_open(port: int, path: str) -> None:
    if not path.startswith("/"):
        path = "/" + path
    webbrowser.open(f"http://localhost:{port}{path}")


@webui_cmd.command(name="install", help="Install a web-UI skin (head).")
@click.argument("source", required=False, default="default")
@click.option("--path", "skin_path", default=None,
              help="Path to a skin directory with a manifest.json.")
def webui_install(source: str, skin_path: str) -> None:
    """Install a skin into the user's webui cache.

    ``source``:
      - ``default``          → install the shipped default head (ours) so you
                               can mod it without touching the installed package.
      - any directory path   → ``--path <dir>`` points at a custom skin.
    Then ``sustech webui serve`` / ``open`` uses the newest installed skin.
    """
    from ..webui import loader
    from pathlib import Path

    # An explicit --path wins over the positional SOURCE default of "default".
    if skin_path:
        p = Path(skin_path)
        if not p.is_dir():
            click.secho(f"not a directory: {p}", fg="red")
            raise SystemExit(1)
        try:
            dst = loader.install_skin(p)
        except ValueError as e:
            click.secho(f"not a valid skin: {e}", fg="red")
            raise SystemExit(1)
        click.secho(f"✅ Installed skin → {dst}", fg="green")
        return

    # `source == "default"` → install the shipped default head (moddable copy).
    if source == "default":
        dst = loader.install_skin("default", default=True)
        click.secho(f"✅ Installed the default skin → {dst}", fg="green")
        click.echo(f"   Saved under the on-disk skin cache: {dst.parent}")
        click.echo("   edit it, or run `sustech webui install --path <your-skin>` for your own.")
        return

    # Otherwise treat SOURCE as a directory path to a custom skin.
    p = Path(source)
    if not p.is_dir():
        click.secho(f"not a directory / unknown source: {source}", fg="red")
        raise SystemExit(1)
    try:
        dst = loader.install_skin(p)
    except ValueError as e:
        click.secho(f"not a valid skin: {e}", fg="red")
        raise SystemExit(1)
    click.secho(f"✅ Installed skin → {dst}", fg="green")


@webui_cmd.command(name="skins", help="List installed web-UI skins.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def webui_skins(as_json: bool) -> None:
    """Show which skins are available to serve and which is active."""
    from ..webui import loader
    skins = loader.installed_skins()
    if as_json:
        click.echo(_json.dumps([
            {"name": s.name, "version": s.version, "entry": s.entry,
             "path": str(s.root)} for s in skins
        ], ensure_ascii=False, indent=2))
        return
    if not skins:
        click.echo("(no skins installed — `sustech webui install default` to set one up)")
        return
    active = skins[0]
    click.secho(f"{len(skins)} skin(s); active = {active.name}@{active.version}", bold=True)
    click.echo("\t".join(("name", "version", "path")))
    for s in skins:
        click.echo("\t".join((s.name, f"v{s.version}", str(s.root))))


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


@click.command(name="profile", help="Fill and write the user's SUSTech profile.")
@click.option("-o", "--output", "output", default=None,
              help="Where to write the profile Markdown (default: ./sustech_profile.md).")
@click.option("--json", "as_json", is_flag=True, help="Print the profile as JSON instead.")
def profile_cmd(output: Optional[str], as_json: bool) -> None:
    """Build the user profile from live SUSTech data and render it.

    Requires SUSTech SSO credentials (credentials.txt) — see ``sustech --help``
    / the ``sso`` subcommand. Prints the generated path on success.
    """
    from ..context import fetch_profile, gen_usr_profile
    if as_json:
        click.echo(_json.dumps(fetch_profile(), ensure_ascii=False, indent=2))
        return
    path = gen_usr_profile(output)
    click.secho(f"✅ Profile written to {path}", fg="green")


# ========================================================================
# consequence — the safety contract surface (read-only introspection)
# ========================================================================

@click.group(name="consequence",
             help="List the consequence-rich operations and their risks.")
def consequence_cmd() -> None:
    """Safety registry: every operation that mutates real SUSTech state.

    These require confirmation before firing. Read the risk + verification
    info here, or at runtime via each operation's ``--help``.
    """


@consequence_cmd.command(name="list", help="List all consequence-rich operations.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def consequence_list(as_json: bool) -> None:
    """Print every registered consequence-rich operation and its severity."""
    import sustech_survival  # noqa: F401  (ensure registry populated)
    import sustech_survival.selectcourse.writes  # noqa: F401
    import sustech_survival.lib.booking.client    # noqa: F401
    import sustech_survival.tis.classroom.booking # noqa: F401
    import sustech_survival.bb.submit             # noqa: F401
    import sustech_survival.pms.pms               # noqa: F401
    from sustech_survival.consequence import consequence_by_name
    # Read the registry directly via the module's internal name->desc map.
    import sustech_survival.consequence as _cs
    items = sorted(_cs._NAME_REGISTRY.values(), key=lambda c: (c.severity.value, c.name))
    if as_json:
        click.echo(_json.dumps([
            {"name": c.name, "severity": c.severity.value, "irreversible": c.irreversible,
             "what_changes": c.what_changes, "risk": c.risk, "verify_url": c.verify_url}
            for c in items
        ], ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("(no consequence-rich operations registered)")
        return
    click.secho(f"{len(items)} consequence-rich operation(s):", bold=True)
    for c in items:
        flag = "IRREV" if c.irreversible else "care "
        click.echo(f"  [{flag} / {c.severity.value:8}] {c.name}")
        if c.what_changes:
            click.echo(f"        {c.what_changes}")
        if c.risk:
            click.echo(f"        Risk: {c.risk}")


@consequence_cmd.command(name="show", help="Show one operation's risk + verification info.")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def consequence_show(name: str, as_json: bool) -> None:
    """Show the risk/verification details for one consequence-rich operation."""
    import sustech_survival.selectcourse.writes  # noqa: F401
    import sustech_survival.lib.booking.client    # noqa: F401
    import sustech_survival.tis.classroom.booking # noqa: F401
    import sustech_survival.bb.submit             # noqa: F401
    import sustech_survival.pms.pms               # noqa: F401
    import sustech_survival.consequence as _cs
    c = _cs.consequence_by_name(name)
    if c is None:
        click.secho(f"unknown operation: {name!r} (run `sustech consequence list`)", fg="red")
        raise SystemExit(1)
    if as_json:
        click.echo(_json.dumps({
            "name": c.name, "severity": c.severity.value, "irreversible": c.irreversible,
            "what_changes": c.what_changes, "risk": c.risk,
            "verify_url": c.verify_url, "read_back": c.read_back, "docs": c.docs,
        }, ensure_ascii=False, indent=2))
        return
    click.secho(f"{c.name}  [{c.severity.value} / {'IRREVERSIBLE' if c.irreversible else 'reversible'}]", bold=True)
    if c.what_changes:
        click.echo(f"  Changes: {c.what_changes}")
    if c.risk:
        click.echo(f"  Risk:    {c.risk}")
    if c.verify_url:
        click.echo(f"  Verify:  {c.verify_url}")
    if c.docs:
        click.echo(f"  Docs:    {c.docs}")


# ========================================================================
# wifi — SUSTech campus Wi-Fi (SUSTC-Wifi / SUSTC-Wifi-5G)
# ========================================================================

@click.group(name="wifi", help="SUSTech campus Wi-Fi: status, login, recent events.")
def wifi_cmd() -> None:
    pass


@wifi_cmd.command(name="status", help="Current Wi-Fi association (SSID, BSSID, signal, MAC).")
@click.option("--json", "as_json", is_flag=True)
def wifi_status(as_json: bool) -> None:
    from ..wifi import current_association
    assoc = current_association()
    if as_json:
        click.echo(_json.dumps(assoc, ensure_ascii=False, indent=2))
        return
    if assoc is None:
        click.echo("Not associated with any Wi-Fi network.")
        return
    ssid = assoc.get("ssid", "?")
    iface = assoc.get("interface", "?")
    click.echo(f"SSID: {ssid}  (interface {iface})")
    if "bssid" in assoc:
        click.echo(f"BSSID: {assoc['bssid']}")
    if "signal_dbm" in assoc:
        click.echo(f"Signal: {assoc['signal_dbm']} dBm")
    if "channel" in assoc:
        click.echo(f"Channel: {assoc['channel']}")
    if "security" in assoc:
        click.echo(f"Security: {assoc['security']}")
    if "mac" in assoc:
        click.echo(f"MAC: {assoc['mac']}")


@wifi_cmd.command(name="login", help="CAS-authenticate to the campus Wi-Fi gateway.")
@click.option("--headless/--headed", default=True,
              help="Headless (default) or open a browser if captcha appears.")
def wifi_login(headless: bool) -> None:
    """
    Run `WiFiAuth().ensure()` to log into the campus Wi-Fi CAS.

    Note: this completes the CAS auth step. The gateway at
    http://172.16.16.20/srun_portal_sso may require an additional POST
    with the device MAC / IP — that step is not yet implemented. See
    the wifi module docstring for details.
    """
    from ..sso import WiFiAuth
    from ..exceptions import InvalidCredentials, NetworkError
    auth = WiFiAuth()
    try:
        if headless:
            ok, reason = auth.ensure()
        else:
            ok = auth.login(headless=False)
            reason = "" if ok else "browser login failed"
    except InvalidCredentials as e:
        click.echo(f"auth failed: invalid credentials — {e}", err=True)
        raise SystemExit(2)
    except NetworkError as e:
        click.echo(f"auth failed: network — {e}", err=True)
        raise SystemExit(3)
    if ok:
        click.echo("CAS auth: OK (gateway registration: pending — see wifi module docs)")
    else:
        click.echo(f"auth failed: {reason}", err=True)
        raise SystemExit(1)


@wifi_cmd.command(name="events", help="Recent SUSTC-Wifi events from the macOS unified log.")
@click.option("--minutes", "-m", type=int, default=60, show_default=True,
              help="How far back to scan.")
@click.option("--limit", "-n", type=int, default=20, show_default=True,
              help="Max events to show.")
@click.option("--json", "as_json", is_flag=True)
def wifi_events(minutes: int, limit: int, as_json: bool) -> None:
    from ..wifi import list_recent_events
    events = list_recent_events(minutes=minutes)
    if as_json:
        click.echo(_json.dumps([e.as_dict() for e in events[:limit]],
                               ensure_ascii=False, indent=2))
        return
    if not events:
        click.echo(f"(no SUSTC-Wifi events in the last {minutes} minutes)")
        return
    for ev in events[:limit]:
        click.echo(f"[{ev.timestamp}] [{ev.category}] "
                   f"ssid={ev.ssid} bssid={ev.bssid}")
        click.echo(f"  {ev.message}")


# ========================================================================
# ws — Student Exchange / Abroad Program search
# ========================================================================


def _ws_print_program(p: dict) -> None:
    """One program as text rows."""
    click.echo(f"  [{p.get('ID', '?')}] {p.get('Name', '?')}  ({p.get('YearCode', '?')})")
    if p.get("RegionName"):
        click.echo(f"     地区: {p['RegionName']}")
    if p.get("ProjectTypeText"):
        click.echo(f"     类型: {p['ProjectTypeText']}")
    if p.get("StudentExchangeProjectGradeIDText"):
        click.echo(f"     级别: {p['StudentExchangeProjectGradeIDText']}")
    if p.get("ApplyBeginDate") and p.get("ApplyEndDate"):
        click.echo(f"     申请: {p['ApplyBeginDate']} ~ {p['ApplyEndDate']}")
    if p.get("ApplyStudentCount") or p.get("LuQuStudentCount"):
        click.echo(f"     报名/录取: {p.get('ApplyStudentCount', '-')} / "
                   f"{p.get('LuQuStudentCount', '-')}")
    status = p.get("IsValidText") or ("有效" if p.get("IsValid") else "无效")
    click.echo(f"     状态: {status}")


def _ws_print_detail(d: dict) -> None:
    """Project detail (sections + tables) as text."""
    sections = d.get("sections", {})
    for sec, pairs in sections.items():
        click.secho(f"\n  [{sec}]", fg="cyan", bold=True)
        for k, v in pairs.items():
            click.echo(f"    {k}: {v}")
    tables = d.get("tables", [])
    for tbl in tables:
        for row in tbl:
            click.echo("    " + " | ".join(str(c) for c in row))


@ws_cmd.command(name="list", help="List exchange programs.")
@click.option("-p", "--page", default=1, show_default=True)
@click.option("-n", "--page-size", default=10, show_default=True)
@click.option("--year", "year_code", default=None, help="Year code, e.g. 2026")
@click.option("--type", "project_type", default=None, type=int,
              help="Project type ID (1=短期, 2=长期)")
@click.option("--grade", "grade_id", default=None, type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def ws_list_cmd(page, page_size, year_code, project_type, grade_id, as_json) -> None:
    """List exchange programs with optional filters."""
    from ..ws.programs import list_programs
    result = list_programs(page=page, page_size=page_size,
                          year_code=year_code, project_type=project_type,
                          grade_id=grade_id)
    if as_json:
        click.echo(_json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"\n📋 第 {result['page']} 页 / 共 {result['record_count']} 个项目")
    for p in result["programs"]:
        click.echo("")
        _ws_print_program(p)


@ws_cmd.command(name="search", help="Search programs by keyword.")
@click.argument("query")
@click.option("-p", "--page", default=1, show_default=True)
@click.option("-n", "--page-size", default=10, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def ws_search_cmd(query, page, page_size, as_json) -> None:
    """Search programs by keyword."""
    from ..ws.programs import search_programs
    result = search_programs(query, page=page, page_size=page_size)
    if as_json:
        click.echo(_json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"\n🔍 '{query}' → {result['record_count']} 个结果")
    for p in result["programs"]:
        click.echo("")
        _ws_print_program(p)


@ws_cmd.command(name="show", help="Show full detail for a program ID.")
@click.argument("program_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def ws_show_cmd(program_id, as_json) -> None:
    """Show full detail for a program ID."""
    from ..ws.programs import get_program_detail
    d = get_program_detail(program_id)
    if d is None:
        click.echo(f"❌ project {program_id} not found", err=True)
        raise SystemExit(1)
    if as_json:
        click.echo(_json.dumps(d, ensure_ascii=False, indent=2))
        return
    _ws_print_detail(d)


@ws_cmd.command(name="count", help="Total program count (with optional filters).")
@click.option("--year", "year_code", default=None)
@click.option("--type", "project_type", default=None, type=int)
@click.option("--keywords", default=None)
def ws_count_cmd(year_code, project_type, keywords) -> None:
    """Total program count (with optional filters)."""
    from ..ws.programs import get_count
    click.echo(f"{get_count(year_code=year_code, project_type=project_type, keywords=keywords)} 个项目")


# ========================================================================
# lib — search + detail for the SUSTech Library (Primo)
# ========================================================================


@click.group(name="lib", help="SUSTech Library Primo (book/article search).")
def lib_cmd() -> None:
    """SUSTech Library Primo catalog search + detail."""


@lib_cmd.command(name="search", help="Search Primo for books / articles.")
@click.argument("query")
@click.option("--scope", default="catalog",
              type=click.Choice(["catalog", "eresource", "default"]),
              show_default=True,
              help="catalog=全部资源 / eresource=电子资源 / default=纸本书目")
@click.option("--material-type", "-t", multiple=True,
              help="Filter to these resource types (Book, Article, Journal, ...). Repeatable.")
@click.option("--library", "-L", multiple=True,
              help="Filter to these physical libraries (琳恩图书馆, 一丹图书馆, ...). Repeatable.")
@click.option("--lang-filter", "-F", multiple=True,
              help="Filter to these publication languages (eng, chi, jpn, ...). Repeatable.")
@click.option("--peer-reviewed/--no-peer-reviewed", default=False,
              help="Only peer-reviewed items.")
@click.option("--full-text-online/--no-full-text-online", default=False,
              help="Only items with online full text available.")
@click.option("--date-from", help="Publication date range start, e.g. 2018 or 2018-01.")
@click.option("--date-to", help="Publication date range end, e.g. 2025 or 2025-12.")
@click.option("--limit", type=int, default=10, show_default=True,
              help="Max results to return.")
@click.option("--offset", type=int, default=0, show_default=True,
              help="Pagination start position (0-based).")
@click.option("--sort-by", default="relevance", show_default=True,
              type=click.Choice(["relevance", "date", "title", "author"]),
              help="Result ordering.")
@click.option("--lang", default="zh_CN", show_default=True,
              help="Interface language (zh_CN or en).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def lib_search_cmd(query: str, scope: str, material_type: tuple, library: tuple,
                    lang_filter: tuple, peer_reviewed: bool, full_text_online: bool,
                    date_from: str, date_to: str, limit: int, offset: int,
                    sort_by: str, lang: str, as_json: bool) -> None:
    """
    Search the SUSTech Library Primo catalog for QUERY (Chinese or English).

    Supports the full Primo search surface: multi-field queries, material
    type / library / language / date filters, peer-reviewed + full-text
    online toggles, pagination, and sort ordering.

    Uses Playwright because Primo's SSL config (sustc.primo.exlibrisgroup.com.cn)
    refuses modern OpenSSL's handshake — Python urllib/requests can't reach it.
    If Playwright isn't installed (`pip install sustech_survival[playwright]`),
    returns no results.

    Each result includes rank, title, format (图书/文章/期刊/...), detail URL,
    full-text availability flag, and peer-review flag. Run `sustech lib detail
    <docid>` to fetch full metadata for one record.

    Examples:

        sustech lib search aspirin
        sustech lib search "electrochromic polymer" --limit 25
        sustech lib search 哈利波特 --scope default
        sustech lib search --material-type Book --lang-filter eng polymer
        sustech lib search --peer-reviewed --sort-by date "machine learning"
        sustech lib search --offset 10 --limit 10 aspirin      # page 2
    """
    from ..lib.search import search
    results = search(
        query=query, scope=scope,
        material_types=list(material_type) if material_type else None,
        libraries=list(library) if library else None,
        languages=list(lang_filter) if lang_filter else None,
        peer_reviewed=peer_reviewed,
        full_text_online=full_text_online,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset, sort_by=sort_by, lang=lang,
    )
    if as_json:
        click.echo(_json.dumps([
            {"rank": r.rank, "title": r.title, "format": r.format,
             "detail_url": r.detail_url, "docid": r.docid,
             "full_text": r.full_text, "peer_reviewed": r.peer_reviewed,
             "snippet": r.snippet}
            for r in results
        ], ensure_ascii=False, indent=2))
        return
    if not results:
        click.echo(
            "no results (auth required? Playwright installed? "
            "→ pip install sustech_survival[playwright])", err=True)
        raise SystemExit(1)
    for r in results:
        flags = []
        if r.full_text: flags.append("full-text")
        if r.peer_reviewed: flags.append("peer-reviewed")
        flag_str = ("  [" + ", ".join(flags) + "]") if flags else ""
        click.echo(f"{r.rank:>3}. {r.title}{flag_str}")
        click.echo(f"     {r.format}  {r.detail_url}")


@lib_cmd.command(name="detail", help="Fetch full metadata for one Primo record.")
@click.argument("docid")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def lib_detail_cmd(docid: str, as_json: bool) -> None:
    """
    Fetch full Primo record metadata by DOCID.

    DOCID is the unique identifier from a `sustech lib search` result
    (visible in the detail URL's `?docid=...` parameter).

    Returns title, format, authors, publisher, year, language, subjects,
    abstract, ISBN, full-text availability, and online URL.
    """
    from ..lib.search import detail
    d = detail(docid)
    if d is None:
        click.echo("detail fetch failed (auth? Playwright installed?)", err=True)
        raise SystemExit(1)
    if as_json:
        click.echo(_json.dumps({
            "title": d.title, "format": d.format,
            "authors": d.authors, "publisher": d.publisher,
            "year": d.year, "language": d.language,
            "subjects": d.subjects, "abstract": d.abstract,
            "isbn": d.isbn, "full_text_availability": d.full_text_availability,
            "online_url": d.online_url, "detail_url": d.detail_url,
        }, ensure_ascii=False, indent=2))
        return
    click.echo(f"题名: {d.title}")
    click.echo(f"格式: {d.format}")
    if d.authors:
        click.echo("作者: " + "; ".join(d.authors))
    if d.publisher:
        click.echo(f"出版: {d.publisher}")
    if d.year:
        click.echo(f"年份: {d.year}")
    if d.isbn:
        click.echo(f"ISBN: {d.isbn}")
    if d.language:
        click.echo(f"语种: {d.language}")
    if d.subjects:
        click.echo("主题: " + ", ".join(d.subjects))
    if d.abstract:
        click.echo(f"摘要: {d.abstract[:400]}{'...' if len(d.abstract) > 400 else ''}")
    if d.full_text_availability:
        click.echo(f"全文可用性: {d.full_text_availability}")
    if d.online_url:
        click.echo(f"在线查看: {d.online_url}")


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
        help="sustech_survival unified CLI. Use `sustech <subcommand> --help` for details.",
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    @click.version_option(__version__, "-V", "--version", prog_name="sustech")
    def cli() -> None:
        """Top-level command group. Use `sustech <subcommand>` to dispatch."""

    cli.add_command(bb_cmd)
    cli.add_command(tis_cmd)
    cli.add_command(ws_cmd)
    cli.add_command(sso_cmd)
    cli.add_command(transit_cmd)
    cli.add_command(context_cmd)
    cli.add_command(profile_cmd)
    cli.add_command(consequence_cmd)
    cli.add_command(webui_cmd)
    cli.add_command(nces_cmd)
    cli.add_command(faculty_cmd)
    cli.add_command(booking_cmd)
    cli.add_command(pms_cmd)
    cli.add_command(lib_booking_cmd)
    cli.add_command(selectcourse_cmd)
    cli.add_command(papers_cmd)
    cli.add_command(wifi_cmd)
    cli.add_command(lib_cmd)
    return cli
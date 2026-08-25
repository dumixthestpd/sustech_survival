"""
sustech_survival.tis.classroom.cli — Click wrapper around the argparse-based
``tis.classroom.__main__`` CLI.

Approach: each Click subcommand invokes the existing argparse entry point
as a subprocess (``python -m sustech_survival.tis.classroom <args>``). This
keeps the actual logic in __main__.py untouched and avoids re-implementing
the 30+ argparse options.

The trade-off is one Python startup per command (≈80ms). Acceptable for
an interactive CLI, and it guarantees parity with the existing parser.

For programmatic use, prefer importing __main__'s helper functions
directly (e.g. ``from sustech_survival.tis.classroom import classroom``)
rather than going through this CLI.
"""
from __future__ import annotations

import sys

import click


def _delegate(argv: list) -> None:
    """Run ``python -m sustech_survival.tis.classroom <argv>`` and exit with its code."""
    import subprocess
    rc = subprocess.call([sys.executable, "-m", "sustech_survival.tis.classroom", *argv])
    if rc:
        sys.exit(rc)


def _opt(name: str, value) -> list:
    """Append --name value pair if value is not None."""
    if value is None:
        return []
    return [f"--{name.replace('_', '-')}", str(value)]


def _flag(name: str, enabled: bool) -> list:
    """Append --name if enabled, else nothing."""
    return [f"--{name.replace('_', '-')}"] if enabled else []


@click.group(name="classroom",
             help="TIS 全校课表 reverse view + venue borrowing (场地借用).")
def cli() -> None:
    pass


@cli.command("rooms")
@click.argument("keyword", default="", required=False)
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--building", default=None)
@click.option("--min-cap", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def rooms(keyword, xn, xq, building, min_cap, as_json):
    """List rooms matching a keyword/building/capacity filter."""
    _delegate(["rooms", keyword,
               *_opt("xn", xn), *_opt("xq", xq),
               *_opt("building", building), *_opt("min-cap", min_cap),
               *_flag("json", as_json)])


@cli.command("room")
@click.argument("name")
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--day", type=int, default=None)
@click.option("--week", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def room(name, xn, xq, day, week, as_json):
    """Show schedule for one room (substring match on the name)."""
    _delegate(["room", name,
               *_opt("xn", xn), *_opt("xq", xq),
               *_opt("day", day), *_opt("week", week),
               *_flag("json", as_json)])


@cli.command("occupancy")
@click.argument("room")
@click.option("--week", type=int, required=True)
@click.option("--day", type=int, required=True, help="1=Mon ... 7=Sun")
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--json", "as_json", is_flag=True)
def occupancy(room, week, day, xn, xq, as_json):
    """Show what's in a given room on a specific day/week."""
    _delegate(["occupancy", room,
               "--week", str(week), "--day", str(day),
               *_opt("xn", xn), *_opt("xq", xq),
               *_flag("json", as_json)])


@cli.command("free")
@click.option("--week", type=int, required=True)
@click.option("--day", type=int, required=True, help="1=Mon ... 7=Sun")
@click.option("--period", "periods", type=int, multiple=True, required=True,
              help="Period number(s) 1-12. Pass twice for a range.")
@click.option("--capacity-min", type=int, default=None)
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--json", "as_json", is_flag=True)
def free(week, day, periods, capacity_min, xn, xq, as_json):
    """Find rooms free at a given week/day/period."""
    argv = ["free", "--week", str(week), "--day", str(day),
            "--period", *[str(p) for p in periods]]
    argv += _opt("capacity-min", capacity_min)
    argv += _opt("xn", xn) + _opt("xq", xq)
    argv += _flag("json", as_json)
    _delegate(argv)


@cli.command("refresh")
def refresh():
    """Force-refresh the TIS campus-room catalog cache."""
    _delegate(["refresh"])


@cli.command("live")
@click.argument("room")
@click.option("--xn", default=None)
@click.option("--xq", default=None)
@click.option("--week", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def live(room, xn, xq, week, as_json):
    """All live schedule entries for a room (incl. borrowings 借用)."""
    _delegate(["live", room,
               *_opt("xn", xn), *_opt("xq", xq), *_opt("week", week),
               *_flag("json", as_json)])


@cli.command("live-at")
@click.argument("room")
@click.option("--week", type=int, required=True)
@click.option("--day", type=int, required=True, help="1=Mon ... 7=Sun")
@click.option("--period", type=int, default=None, help="Period (1-12). Optional.")
@click.option("--json", "as_json", is_flag=True)
def live_at(room, week, day, period, as_json):
    """Live entries active at (week, day[, period])."""
    _delegate(["live-at", room,
               "--week", str(week), "--day", str(day),
               *_opt("period", period),
               *_flag("json", as_json)])


@cli.command("now")
@click.argument("room")
@click.option("--json", "as_json", is_flag=True)
def now(room, as_json):
    """What's currently in this room (local time)."""
    _delegate(["now", room, *_flag("json", as_json)])


@cli.command("book")
@click.option("--room", required=True, help="Room display name (e.g. 一教324) or code (YJ-324)")
@click.option("--day", type=int, help="Weekday 1=Mon ... 7=Sun")
@click.option("--period", "periods", type=int, multiple=True,
              help="Period number(s) 1-12. Pass twice for a range.")
@click.option("--clock-start", default=None, help='e.g. "14:00"')
@click.option("--clock-end", default=None, help='e.g. "16:00"')
@click.option("--week", type=int, multiple=True, help="Week number(s) 1-17.")
@click.option("--headcount", type=int, required=True)
@click.option("--purpose", required=True, help="借用原因")
@click.option("--campus", default="1", help="校区: 1=一期, 2=二期, 9=九祥")
@click.option("--start-date", default=None, help="Start date YYYY-MM-DD")
@click.option("--end-date", default=None, help="End date YYYY-MM-DD")
@click.option("--applicant-name", default=None)
@click.option("--applicant-phone", default=None)
@click.option("--applicant-id", default=None)
@click.option("--applicant-dept", default=None)
@click.option("--applicant-dept-en", default=None)
@click.option("--user-name", default=None)
@click.option("--user-phone", default=None)
@click.option("--no-media", is_flag=True, default=False)
@click.option("--tiered", default="not-care",
              type=click.Choice(["not-care", "yes", "no"]))
@click.option("--movable-seats", default="not-care",
              type=click.Choice(["not-care", "yes", "no"]))
@click.option("--save", is_flag=True,
              help="Save draft (shbj='0') instead of submit (shbj='1').")
@click.option("--commit", is_flag=True,
              help="Actually POST to TIS (requires --yes or interactive confirm).")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt (with --commit).")
def book(room, day, periods, clock_start, clock_end, week, headcount,
         purpose, campus, start_date, end_date, applicant_name,
         applicant_phone, applicant_id, applicant_dept, applicant_dept_en,
         user_name, user_phone, no_media, tiered, movable_seats,
         save, commit, yes):
    """Submit a venue-borrowing application (dry-run by default)."""
    argv = ["book",
            "--room", room,
            "--headcount", str(headcount),
            "--purpose", purpose,
            "--campus", campus]
    if day is not None:
        argv += ["--day", str(day)]
    for p in periods:
        argv += ["--period", str(p)]
    argv += _opt("clock-start", clock_start)
    argv += _opt("clock-end", clock_end)
    for w in week:
        argv += ["--week", str(w)]
    argv += _opt("start-date", start_date)
    argv += _opt("end-date", end_date)
    argv += _opt("applicant-name", applicant_name)
    argv += _opt("applicant-phone", applicant_phone)
    argv += _opt("applicant-id", applicant_id)
    argv += _opt("applicant-dept", applicant_dept)
    argv += _opt("applicant-dept-en", applicant_dept_en)
    argv += _opt("user-name", user_name)
    argv += _opt("user-phone", user_phone)
    if no_media:
        argv += ["--no-media"]
    argv += ["--tiered", tiered]
    argv += ["--movable-seats", movable_seats]
    if save:
        argv += ["--save"]
    if commit:
        argv += ["--commit"]
    if yes:
        argv += ["--yes"]
    _delegate(argv)


@cli.command("search-rooms")
@click.option("--week", type=int, default=1)
@click.option("--day", type=int, required=True, help="Weekday 1=Mon ... 7=Sun")
@click.option("--period", "periods", type=int, multiple=True,
              help="Period number(s) 1-12. Pass twice for a range.")
@click.option("--campus", default="1")
@click.option("--building", default=None)
@click.option("--min-cap", type=int, default=None)
@click.option("--tiered", default="not-care",
              type=click.Choice(["not-care", "yes", "no"]))
@click.option("--movable-seats", default="not-care",
              type=click.Choice(["not-care", "yes", "no"]))
def search_rooms(week, day, periods, campus, building, min_cap,
                 tiered, movable_seats):
    """Search available rooms matching filters (TIS 选择场地 dialog)."""
    argv = ["search-rooms",
            "--week", str(week),
            "--day", str(day),
            "--campus", campus]
    for p in periods:
        argv += ["--period", str(p)]
    argv += _opt("building", building)
    argv += _opt("min-cap", min_cap)
    argv += ["--tiered", tiered]
    argv += ["--movable-seats", movable_seats]
    _delegate(argv)
"""
sustech_survival.classroom — CLI.

Usage:
    python -m sustech_survival.classroom <command> [...]

Commands (human + agent friendly):
    rooms [KW]                       List all rooms (with slot counts)
        --xn YEAR --xq N              Override semester (default 2025-2026 / 2)
        --min-cap N                   Filter by minimum capacity
        --json
    room NAME                        Show all slots in one room
        --json
    occupancy ROOM --week N --day N  What's in this room on this (week, day)?
        --day N                       1=Mon ... 7=Sun
        --json
    free --week N --day N --period [PEND]
                                     Find rooms free during this timeslot
        --period 3                    Single period (1-12)
        --period 3 4                  Range periods 3-4
        --capacity-min N              Only show rooms with cap >= N
        --json
    refresh                          Force-refresh from TIS (bust cache)
        --xn YEAR --xq N

Note: All commands use a 1-hour disk cache. Run `refresh` if you want
fresh data.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .classroom import classroom as classroom_factory
from .schema import (
    DAY_NAMES_ZH, DAY_NAMES_EN, PERIOD_TIMES,
)


def _print_rooms(rooms, as_json: bool = False) -> None:
    if as_json:
        out = [
            {"name": r.name, "capacity": r.capacity,
             "slot_count": r.slot_count, "building": r.short_name}
            for r in rooms
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"{'NAME':<28} {'BUILDING':<14} {'CAP':>6}  SLOTS")
    print("-" * 65)
    for r in rooms:
        cap = str(r.capacity) if r.capacity is not None else "?"
        print(f"{r.name:<28} {r.short_name:<14} {cap:>6}  {r.slot_count}")


def _print_slots(slots, as_json: bool = False) -> None:
    if as_json:
        out = [
            {
                "course_code": s.course_code,
                "course_name": s.course_name,
                "class_group": s.class_group,
                "weeks": s.weeks,
                "day": s.day, "day_zh": DAY_NAMES_ZH[s.day],
                "period_start": s.period_start, "period_end": s.period_end,
                "duration": s.duration,
                "room": s.room,
                "when": s.when_str,
            }
            for s in slots
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not slots:
        print("(no slots)")
        return
    for s in slots:
        times = PERIOD_TIMES[s.period_start]
        if s.period_end != s.period_start:
            times += f" - {PERIOD_TIMES[s.period_end].split('-')[-1]}"
        print(f"  [{s.course_code:<10} {s.class_group:<3}] {s.course_name}")
        print(f"      {s.when_str}  ({times})")
        print()


def _print_free_rooms(rooms: List[str], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(rooms, ensure_ascii=False, indent=2))
        return
    print(f"  ({len(rooms)} rooms free)")
    for r in rooms:
        print(f"  {r}")


# ── Command handlers ─────────────────────────────────────────────────────────


def cmd_rooms(args) -> int:
    c = classroom_factory(xn=args.xn, xq=args.xq)
    rooms = c.rooms(keyword=args.keyword or "")
    if args.min_cap is not None:
        rooms = [r for r in rooms
                 if r.capacity is not None and r.capacity >= args.min_cap]
    _print_rooms(rooms, as_json=args.json)
    return 0


def cmd_room(args) -> int:
    c = classroom_factory(xn=args.xn, xq=args.xq)
    slots = c.slots_for_room(args.name)
    if not slots:
        print(f"Room {args.name!r} not found in current semester.", file=sys.stderr)
        return 1
    print(f"=== {slots[0].room} ({len(slots)} slots) ===")
    _print_slots(slots, as_json=args.json)
    return 0


def cmd_occupancy(args) -> int:
    c = classroom_factory(xn=args.xn, xq=args.xq)
    occ = c.occupancy(args.room, week=args.week, day=args.day)
    day_zh = DAY_NAMES_ZH[args.day] if 1 <= args.day <= 7 else f"day{args.day}"
    print(f"=== {args.room} on week {args.week} {day_zh} ===")
    if not occ:
        print("(room is free)")
    _print_slots(occ, as_json=args.json)
    return 0


def cmd_free(args) -> int:
    c = classroom_factory(xn=args.xn, xq=args.xq)
    rooms = c.free(args.week, args.day, args.period_start, args.period_end)
    if args.capacity_min is not None:
        # Need room capacity → re-fetch rooms index.
        rooms_all = {r.name: r for r in c.rooms()}
        rooms = [r for r in rooms
                 if r in rooms_all and rooms_all[r].capacity is not None
                 and rooms_all[r].capacity >= args.capacity_min]
    day_zh = DAY_NAMES_ZH[args.day] if 1 <= args.day <= 7 else f"day{args.day}"
    pstr = (f"period {args.period_start}-{args.period_end}"
            if args.period_end and args.period_end != args.period_start
            else f"period {args.period_start}")
    print(f"=== Free rooms, week {args.week} {day_zh} {pstr} ===")
    _print_free_rooms(rooms, as_json=args.json)
    return 0


def cmd_refresh(args) -> int:
    c = classroom_factory(xn=args.xn, xq=args.xq)
    n = c.refresh()
    print(f"Refreshed: {n} slots cached.")
    return 0


# ── Parser ──────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.classroom",
        description="TIS 全校课表 reverse view: room-centric queries",
    )
    p.add_argument("--xn", default="2025-2026",
                   help="Academic year (e.g. 2025-2026)")
    p.add_argument("--xq", default="2",
                   help="Semester: 1=Fall, 2=Spring, 3=Summer")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("rooms", help="List all rooms")
    sp.add_argument("keyword", nargs="?", default="",
                    help="Filter by room name substring")
    sp.add_argument("--min-cap", type=int, default=None,
                    help="Minimum capacity (filter)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_rooms)

    sp = sub.add_parser("room", help="Show all slots in one room")
    sp.add_argument("name", help="Room name or substring (e.g. 一教324)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_room)

    sp = sub.add_parser("occupancy", help="What's in this room on this day?")
    sp.add_argument("room", help="Room name")
    sp.add_argument("--week", type=int, required=True, help="Week number")
    sp.add_argument("--day", type=int, required=True,
                    help="Day of week (1=Mon ... 7=Sun)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_occupancy)

    sp = sub.add_parser("free",
                        help="Find rooms free during a timeslot")
    sp.add_argument("--week", type=int, required=True)
    sp.add_argument("--day", type=int, required=True,
                    help="1=Mon ... 7=Sun")
    sp.add_argument("--period", type=int, nargs="+", required=True,
                    help="Period number(s) (1-12). One or two numbers (range).")
    sp.add_argument("--capacity-min", type=int, default=None,
                    help="Minimum capacity filter")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_free)

    sp = sub.add_parser("refresh", help="Force-refresh from TIS")
    sp.set_defaults(func=cmd_refresh)

    return p


def _normalize_period_args(args) -> None:
    """Convert --period list into (start, end) attributes."""
    if not hasattr(args, "period"):
        return
    if len(args.period) == 1:
        args.period_start = args.period[0]
        args.period_end = args.period[0]
    elif len(args.period) == 2:
        args.period_start, args.period_end = args.period
    else:
        print("error: --period takes 1 or 2 numbers", file=sys.stderr)
        sys.exit(2)


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    _normalize_period_args(args)
    try:
        return args.func(args)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

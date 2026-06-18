"""
sustech_survival.booking — CLI.

Usage:
    python -m sustech_survival.booking <command> [...]

Commands (human + agent friendly):
    whoami                           Print current user profile
    rooms [KW]                       List all rooms (optionally filter by name)
        --available                  Only show IsAvailable=True rooms
        --json                       Output JSON to stdout
    room ROOM_ID                     Print details for a single room
        --json
    my-meetings                      List my current bookings
        --json
    add --room ID --start TS --end TS --title TXT [OPTS]
                                    Create a booking
        --participants N             (default: 1)
        --description "..."          (default: empty)
        --dry-run                    Prepare the payload, print it, don't POST
    cancel MEETING_ID                Cancel one of my bookings
        --dry-run

All output is plain text — readable for both humans and LLMs. Use --json for
machine-readable output.

Note: `add` and `cancel` hit real destructive endpoints. Always `--dry-run`
first to inspect the staged payload before going live.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import List

from . import booking as booking_factory
from .booking import BookingError


# ── Output helpers ───────────────────────────────────────────────────────────


def _print_rooms(rooms, as_json: bool = False) -> None:
    if as_json:
        out = [
            {
                "id": r.id, "name": r.name, "type": r.room_type,
                "capacity": r.capacity, "location": r.location,
                "is_available": r.is_available, "needs_approval": r.needs_approval,
                "bookable_hours": r.bookable_hours_str(),
                "dept": r.dept_name, "managers": r.managers,
            }
            for r in rooms
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"{'ID':<40} {'NAME':<24} {'TYPE':<10} {'CAP':>4}  HOURS       LOC")
    print("-" * 110)
    for r in rooms:
        print(
            f"{r.id:<40} {r.name:<24} {r.room_type:<10} "
            f"{r.capacity:>4}  {r.bookable_hours_str():<11} {r.location}"
        )


def _print_my_meetings(meetings, as_json: bool = False) -> None:
    if as_json:
        out = [
            {
                "id": m.id, "room_id": m.room_id, "room_name": m.room_name,
                "title": m.title,
                "start_at": m.start_at.isoformat() if m.start_at else None,
                "end_at": m.end_at.isoformat() if m.end_at else None,
                "status": m.status, "unread": m.unread,
            }
            for m in meetings
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not meetings:
        print("(no bookings)")
        return
    print(f"{'ID':<24} {'ROOM':<28} {'WHEN':<32} TITLE")
    print("-" * 110)
    for m in meetings:
        when = ""
        if m.start_at and m.end_at:
            when = f"{m.start_at:%Y-%m-%d %H:%M} → {m.end_at:%H:%M}"
        print(f"{m.id:<24} {m.room_name[:26]:<28} {when:<32} {m.title}")


def _print_room(room, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({
            "id": room.id, "name": room.name, "type": room.room_type,
            "capacity": room.capacity, "location": room.location,
            "is_available": room.is_available, "needs_approval": room.needs_approval,
            "bookable_hours": room.bookable_hours_str(),
            "dept": room.dept_name, "managers": room.managers,
            "equipment": room.equipment,
            "longitude": room.longitude, "latitude": room.latitude,
            "register_distance_m": room.register_distance_m,
        }, ensure_ascii=False, indent=2))
        return
    print(f"  ID:           {room.id}")
    print(f"  Name:         {room.name}")
    print(f"  Type:         {room.room_type}")
    print(f"  Capacity:     {room.capacity}")
    print(f"  Location:     {room.location}")
    print(f"  Available:    {room.is_available}")
    print(f"  Approval:     {'required' if room.needs_approval else 'not required'}")
    print(f"  Hours:        {room.bookable_hours_str()}")
    print(f"  Dept:         {room.dept_name}")
    if room.managers:
        print(f"  Managers:     {', '.join(room.managers)}")
    if room.equipment:
        print(f"  Equipment:    {', '.join(room.equipment)}")


def _print_whoami(me: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(me, ensure_ascii=False, indent=2))
        return
    print(f"  Name:    {me.get('name')}")
    print(f"  SID:     {me.get('sid')}")
    print(f"  Email:   {me.get('DZYX')}")
    print(f"  Groups:  {me.get('groups')}")
    if me.get("SJHM"):
        # Phone number — treat carefully, only show on explicit JSON
        pass


# ── Command handlers ─────────────────────────────────────────────────────────


def cmd_whoami(args) -> int:
    client = booking_factory()
    _print_whoami(client.whoami(), as_json=args.json)
    return 0


def cmd_rooms(args) -> int:
    client = booking_factory()
    rooms = client.rooms()
    if args.available:
        rooms = [r for r in rooms if r.is_available]
    if args.keyword:
        kw = args.keyword.lower()
        rooms = [r for r in rooms if kw in r.name.lower() or kw in r.id.lower()]
    _print_rooms(rooms, as_json=args.json)
    return 0


def cmd_room(args) -> int:
    client = booking_factory()
    room = client.room_by_id(args.room_id)
    if room is None:
        print(f"Room {args.room_id!r} not found.", file=sys.stderr)
        return 1
    _print_room(room, as_json=args.json)
    return 0


def cmd_my_meetings(args) -> int:
    client = booking_factory()
    meetings = client.my_meetings()
    _print_my_meetings(meetings, as_json=args.json)
    return 0


def _parse_dt(s: str) -> datetime:
    """Parse a datetime string. Accepts ISO 8601 or 'YYYY-MM-DD HH:MM'."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r} (use ISO 8601 like 2026-06-20T14:00)")


def cmd_add(args) -> int:
    client = booking_factory()
    start = _parse_dt(args.start)
    end = _parse_dt(args.end)

    payload = {
        "MeetingRoomID": args.room,
        "MeetingName": args.title,
        "MeetingStart": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "MeetingEnd": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "NumberOfParticipants": args.participants,
        "MeetingDesc": args.description or "",
    }
    print("Staged payload:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("\n(dry-run: not POSTed)")
        return 0

    try:
        result = client.add_meeting(
            room_id=args.room,
            start=start, end=end, title=args.title,
            participants=args.participants,
            description=args.description or "",
        )
    except BookingError as e:
        print(f"\n❌ Booking failed: {e}", file=sys.stderr)
        return 2
    print("\n✓ Booked.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_cancel(args) -> int:
    client = booking_factory()
    if args.dry_run:
        print(f"(dry-run: would cancel meeting {args.meeting_id})")
        return 0
    try:
        result = client.cancel_meeting(args.meeting_id)
    except BookingError as e:
        print(f"❌ Cancel failed: {e}", file=sys.stderr)
        return 2
    print(f"✓ Cancelled {args.meeting_id}.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ── Parser ──────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.booking",
        description="SUSTech ehall 场地预约 CLI",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("whoami", help="Print current user profile")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_whoami)

    sp = sub.add_parser("rooms", help="List all rooms")
    sp.add_argument("keyword", nargs="?", default="",
                    help="Filter by name or id (substring, case-insensitive)")
    sp.add_argument("--available", action="store_true",
                    help="Only show IsAvailable=True rooms")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_rooms)

    sp = sub.add_parser("room", help="Show one room by id")
    sp.add_argument("room_id", help="e.g. ZC02 or full UUID")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_room)

    sp = sub.add_parser("my-meetings", help="List my current bookings")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_my_meetings)

    sp = sub.add_parser("add", help="Create a booking")
    sp.add_argument("--room", required=True, help="Room ID (e.g. ZC02)")
    sp.add_argument("--start", required=True,
                    help="Start datetime (ISO 8601, e.g. 2026-06-20T14:00)")
    sp.add_argument("--end", required=True,
                    help="End datetime (ISO 8601, e.g. 2026-06-20T16:00)")
    sp.add_argument("--title", required=True, help="Booking title")
    sp.add_argument("--participants", type=int, default=1,
                    help="Number of participants (default: 1)")
    sp.add_argument("--description", default="", help="Booking description")
    sp.add_argument("--dry-run", action="store_true",
                    help="Stage the payload and print it; don't POST")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("cancel", help="Cancel one of my bookings")
    sp.add_argument("meeting_id", help="Meeting ID (from `my-meetings`)")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_cancel)

    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BookingError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

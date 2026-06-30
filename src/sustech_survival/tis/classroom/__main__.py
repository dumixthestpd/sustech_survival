"""
sustech_survival.tis.classroom — CLI.

Usage:
    python -m sustech_survival.tis.classroom <command> [...]

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

    LIVE OCCUPANCY (cdkb/querycdkbList — incl. borrowings 借用):
    live ROOM                        All live schedule entries for a room
                                     (courses + ad-hoc borrowings)
        --json
    live-at ROOM --week N --day N    Live entries active on (week, day)
        --period N                    Filter to one period (1-12)
        --json
    now ROOM                         What's currently in this room
                                     (uses local time → TIS format)
        --json

    BOOKING (cdjy/addChangDiJieYongShenQing/1 — wire-shape verified 2026-06-29):
    book --room NAME --day N --period P1 [P2] --week N [N2..]
         --headcount N --purpose "..."
         [--applicant-name NAME --applicant-phone PHONE]
         [--user-name NAME --user-phone PHONE]
         [--media | --no-media]
         [--tiered not-care|yes|no --movable-seats not-care|yes|no]
         [--save | (submit default)] [--dry-run | --commit]
                                     Build a venue-borrowing application.
        --room 一教107              Room display name OR code (YJ-107)
        --day 3                     Weekday 1=Mon ... 7=Sun
        --period 3 4                Period range (1-12)
        --clock-start 14:00         Clock-time alternative to --period
        --clock-end 16:00
        --week 5 6 7 8              Week numbers (1-17)
        --headcount 30              Number of people
        --purpose "学术讲座"          借用原因
        --campus 1                  1=一期 (default), 2=二期, 9=九祥
        --applicant-name "段斯宸"    申请人 sqr (who requests)
        --applicant-phone 13800138000
        --user-name "李四"           使用人 syr (who actually uses the room,
                                     defaults to applicant if omitted)
        --user-phone 13900139000
        --media                     sfsysb='1' (default: use equipment)
        --no-media                  sfsysb='0'
        --tiered not-care           阶梯教室 sfjtjs (default: 不限制)
        --movable-seats yes         座椅可移动 zysfkyd
        --start-date 2026-07-01     Per-row ksrq (auto-derived from week if omitted)
        --save                      保存 draft (shbj='0') instead of 提交 submit
        --dry-run                   Print wire, no POST (default)
        --commit                    Actually POST to TIS
        --yes                       Skip confirmation prompt

    Multi-ticket (repeat --slot instead of --room/--day/--period/--week):
    book --slot "room=一教107 day=3 period=3-4 week=5" \\
         --slot "room=智华楼201 day=5 clock=14:00-16:00 week=6" \\
         --headcount 30 --purpose "学术讲座"

Note: All commands use a 1-hour disk cache. Run `refresh` to bust.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import List, Optional

from .classroom import classroom as classroom_factory
from .live import current_weekday_and_period
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


# ── Book command (wire-shape verified 2026-06-29) ──────────────────────────


def cmd_book(args) -> int:
    """Build a venue-borrowing application from CLI args.

    Uses the new ``build_booking()`` + ``RowTicket`` API.
    See ``booking_schema.build_booking`` for the full parameter doc.

    Modes:
        --dry-run       Default. Print the wire payload that would be sent.
        --commit        Actually POST to TIS.

    Single-ticket (backward compat):
        --room NAME --day N --period P1 [P2] --week N [N..]
    Multi-ticket:
        --slot room=一周107 day=3 period=3-4 week=5 [date=2026-07-01] \\
        --slot room=智华楼201 day=5 period=5-6 week=6 [date=2026-07-02]
    """
    from pathlib import Path
    from sustech_survival.tis.classroom.booking_schema import (
        build_booking, RowTicket, Semester,
    )

    # Resolve room name → TIS code if single-ticket mode
    actual_skill_root = Path.home() / ".openclaw" / "code" / "sustech_survival"
    from sustech_survival.tis.classroom.classroom import ClassroomOccupancy
    classroom_obj = ClassroomOccupancy(
        xn=args.xn, xq=args.xq, skill_root=actual_skill_root,
    )

    # ── Build tickets from args ──
    tickets: list[RowTicket] = []

    if hasattr(args, "slot") and args.slot:
        # Multi-ticket: --slot key=value key=value ...
        from sustech_survival.tis.classroom._booking_time import _clock_to_period, ClockTime
        for slot_str in args.slot:
            fields = {}
            for pair in slot_str.split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    fields[k.strip().lower()] = v.strip()
            room_query = fields.get("room", "")
            room_lookup = _resolve_room(room_query, classroom_obj)
            if room_lookup is None:
                print(f"❌ Room not found: {room_query!r}", file=sys.stderr)
                return 2
            room_code, room_name, _ = room_lookup
            day = int(fields.get("day", "0"))
            period_str = fields.get("period", "")
            clock_str = fields.get("clock", "")
            week = fields.get("week", "")
            date = fields.get("date", "")
            # Clock-time support: "14:00-16:00" or "14:00 16:00"
            if clock_str:
                parts = clock_str.replace("-", " ").split()
                if len(parts) >= 2:
                    ps = _clock_to_period(ClockTime.from_str(parts[0]))
                    pe = _clock_to_period(ClockTime.from_str(parts[1]))
                else:
                    print(f"❌ Invalid clock format: {clock_str!r} (need start-end)", file=sys.stderr)
                    return 2
            else:
                period_parts = period_str.replace("-", " ").split()
                ps = int(period_parts[0]) if period_parts else 0
                pe = int(period_parts[-1]) if period_parts else 0
            if not (1 <= ps <= pe <= 12):
                print(f"❌ Invalid period/clock in slot: {slot_str!r}", file=sys.stderr)
                return 2
            tickets.append(RowTicket(
                room_code=room_code, room_name=room_name,
                weekday=day, period_start=ps, period_end=pe,
                week=week, week_range=week,
                start_date=date, end_date=date,
            ))
    else:
        # Single-ticket mode (original style or --clock-start/--clock-end)
        room_lookup = _resolve_room(args.room, classroom_obj)
        if room_lookup is None:
            print(f"❌ Room not found: {args.room!r}", file=sys.stderr)
            return 2
        room_code, room_name, _ = room_lookup

        # Convert clock times → periods if clock-start/clock-end provided
        if args.clock_start and args.clock_end:
            from sustech_survival.tis.classroom._booking_time import _clock_to_period, ClockTime
            ps = _clock_to_period(ClockTime.from_str(args.clock_start))
            pe = _clock_to_period(ClockTime.from_str(args.clock_end))
        elif args.period:
            ps = args.period[0]
            pe = args.period[-1]
        else:
            print("❌ Must specify either --period or --clock-start/--clock-end",
                  file=sys.stderr)
            return 2

        weeks = " ".join(str(w) for w in args.week)
        week_str = "-".join(str(w) for w in args.week) if len(args.week) > 1 else str(args.week[0])
        ksrq = args.start_date or ""
        jsrq = args.end_date or ""
        tickets.append(RowTicket(
            room_code=room_code, room_name=room_name,
            weekday=args.day, period_start=ps, period_end=pe,
            week=weeks, week_range=week_str,
            start_date=ksrq, end_date=jsrq,
        ))

    if not tickets:
        print("❌ No tickets specified. Use --slot or --room/--day/--period/--week.",
              file=sys.stderr)
        return 2

    # ── Build application ──
    from sustech_survival.semester import Semester
    semester = Semester(args.xn, args.xq)

    tiered_map = {"not-care": "2", "yes": "1", "no": "0", "2": "2", "1": "1", "0": "0"}
    movable_map = {"not-care": "2", "yes": "1", "no": "0", "2": "2", "1": "1", "0": "0"}

    app = build_booking(
        tickets=tickets,
        semester=semester,
        applicant_name=args.applicant_name or "",
        applicant_phone=args.applicant_phone or "",
        applicant_id=args.applicant_id or "",
        applicant_dept=args.applicant_dept or "",
        applicant_dept_en=args.applicant_dept_en or "",
        user_name=args.user_name or args.applicant_name or "",
        user_phone=args.user_phone or args.applicant_phone or "",
        campus=args.campus,
        headcount=args.headcount,
        use_media=args.media,
        purpose=args.purpose,
        save_as_draft=args.save,
        tiered=tiered_map.get(args.tiered, "2"),
        movable_seats=movable_map.get(args.movable_seats, "2"),
    )

    wire = app.to_api()

    # ── Dry-run mode ──
    if args.dry_run:
        print(f"=== DRY RUN — wire payload (NOT POSTed) ===")
        print(f"Endpoint: POST https://tis.sustech.edu.cn/cdjy/addChangDiJieYongShenQing/1")
        print(f"Body ({len(wire)} form-level keys, "
              f"{len(wire['cdjymxlist'])} detail rows, "
              f"{len(wire['jtsjlist'])} flat slots):")
        print(json.dumps(wire, ensure_ascii=False, indent=2))
        print()
        for i, t in enumerate(tickets):
            print(f"  Ticket {i+1}: {t.room_name} ({t.room_code}), "
                  f"day {t.weekday} period {t.period_start}-{t.period_end}, "
                  f"week {t.week}")
        print(f"  shbj: {args.save} → wire = "
              f"{'0 (draft)' if args.save else '1 (submit)'!r}")
        print()
        if not args.yes:
            print("To actually POST, re-run with --commit (will prompt for confirmation).")
        return 0

    # ── Commit mode ──
    if not args.yes:
        print(f"=== CONFIRM BOOKING ===")
        for i, t in enumerate(tickets):
            print(f"  [{i+1}] {t.room_name} ({t.room_code}), "
                  f"day {t.weekday} period {t.period_start}-{t.period_end}, "
                  f"week {t.week}")
        print(f"  People:  {args.headcount}")
        print(f"  Purpose: {args.purpose}")
        print(f"  Action:  {'保存 (draft)' if args.save else '提交 (submit)'}")
        print()
        try:
            confirm = input("Type 'yes' to confirm POST to TIS: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("Aborted.", file=sys.stderr)
            return 130
        if confirm != "yes":
            print("Aborted.", file=sys.stderr)
            return 1

    # ── Real POST ──
    from sustech_survival.tis.classroom.booking import (
        venue_borrow, BorrowError,
    )
    c = venue_borrow()
    sess = c.ensure_session()

    missing = []
    if not args.applicant_name:
        missing.append("--applicant-name")
    if not args.applicant_phone:
        missing.append("--applicant-phone")
    if missing:
        print(f"❌ Missing required fields: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        saved = c.create_borrow_application(app, dry_run=False)
        print(f"✅ Application created!")
        print(f"   id:   {saved.id}")
        print(f"   jhdh: {saved.jhdh}")
        print(f"   status: {saved.status}")
        return 0
    except BorrowError as e:
        print(f"❌ Borrow error: {e}", file=sys.stderr)
        return 1


def _resolve_room(query: str, classroom) -> Optional[tuple]:
    """Resolve a room display name OR code to (cddm, cdmc, capacity).

    Strategy (in order):
      1. Try didian catalog (TIS-side cddm/mc) if accessible.
      2. Fall back to the public schedule's room index
         (display name only — cddm will be the display name itself,
         which TIS may not accept for non-trivial room codes).

    Returns None if not found anywhere.
    """
    # Strategy 1: didian catalog (TIS-side identifiers)
    try:
        didian = classroom._query_didian_catalog()
    except Exception:
        didian = None

    if didian:
        # Exact match on TIS code (e.g. "YJ-107")
        for r in didian:
            if r.get("dm") == query:
                return (r["dm"], r.get("mc") or query, int(r.get("zws") or 0))
        # Exact match on display name (e.g. "一教107")
        for r in didian:
            if r.get("mc") == query:
                return (r["dm"], r.get("mc") or query, int(r.get("zws") or 0))
        # Substring match on display name
        matches = [r for r in didian if query in (r.get("mc") or "")]
        if matches:
            r = matches[0]
            return (r["dm"], r.get("mc") or query, int(r.get("zws") or 0))

    # Strategy 2: public schedule Room index (display name only)
    try:
        rooms = classroom.rooms()
    except Exception:
        rooms = []

    for r in rooms:
        if r.name == query or query in r.name:
            return (r.name, r.short_name or r.name, r.capacity or 0)
    for r in rooms:
        if query in (r.short_name or ""):
            return (r.name, r.short_name or r.name, r.capacity or 0)

    return None


# ── Live occupancy commands ─────────────────────────────────────────────────


def _print_live_entries(entries, as_json: bool = False) -> None:
    if as_json:
        out = []
        for e in entries:
            out.append({
                "cddm": e.cddm,
                "type": e.type,
                "is_borrowing": e.is_borrowing,
                "is_course": e.is_course,
                "weekday": e.weekday,
                "period_start": e.period_start,
                "weeks": e.weeks,
                "course_code": e.course_code,
                "course_name": e.course_name,
                "borrower": e.borrower,
                "phone": e.phone,
                "purpose": e.purpose,
                "sksj_text": e.sksj_text,
                "when": e.when_str,
            })
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not entries:
        print("(no live entries)")
        return
    for e in entries:
        print(f"  {e.to_markdown()}")


def cmd_live(args) -> int:
    """Show all live schedule entries for a room (incl. borrowings)."""
    c = classroom_factory(xn=args.xn, xq=args.xq)
    entries = c.live_entries_for_name(args.room)
    if not entries:
        print(f"No live entries for {args.room!r} (room not found or empty).",
              file=sys.stderr)
        return 1
    borrow_count = sum(1 for e in entries if e.is_borrowing)
    course_count = sum(1 for e in entries if e.is_course)
    print(f"=== Live schedule for {args.room!r} "
          f"({len(entries)} entries: {course_count} courses + "
          f"{borrow_count} borrowings) ===")
    _print_live_entries(entries, as_json=args.json)
    return 0


def cmd_live_at(args) -> int:
    """Live entries active at (week, day[, period]) in a room."""
    c = classroom_factory(xn=args.xn, xq=args.xq)
    if args.period is not None:
        hits = c.live_occupancy_at(args.room, week=args.week,
                                   day=args.day, period=args.period)
    else:
        hits = c.live_occupancy(args.room, week=args.week, day=args.day)
    day_zh = DAY_NAMES_ZH[args.day] if 1 <= args.day <= 7 else f"day{args.day}"
    pstr = f" period {args.period}" if args.period is not None else ""
    print(f"=== {args.room!r} live on week {args.week} {day_zh}{pstr} ===")
    _print_live_entries(hits, as_json=args.json)
    return 0


def cmd_now(args) -> int:
    """What's currently in this room (now = local time)."""
    c = classroom_factory(xn=args.xn, xq=args.xq)
    weekday, period = current_weekday_and_period()
    inferred_week = _infer_current_week(c)
    if period is None:
        print(f"Now is {datetime.now().isoformat(timespec='minutes')} — "
              "outside class hours (8:00-22:30). Showing full day instead.",
              file=sys.stderr)
        # Fall back to full-day occupancy for the current weekday
        hits = c.live_occupancy(args.room, week=inferred_week, day=weekday)
    else:
        hits = c.live_occupancy_at(args.room,
                                   week=inferred_week,
                                   day=weekday, period=period)
    day_zh = DAY_NAMES_ZH[weekday] if 1 <= weekday <= 7 else f"day{weekday}"
    pstr = f" period {period}" if period is not None else ""
    week_str = f"week {inferred_week}" if inferred_week else "week ?"
    print(f"=== {args.room!r} NOW ({datetime.now().isoformat(timespec='minutes')}, "
          f"{week_str}, weekday={weekday} {day_zh}{pstr}) ===")
    _print_live_entries(hits, as_json=args.json)
    return 0


def _infer_current_week(c) -> int:
    """Best-effort guess of current semester week (1-18).

    Uses `live.current_week()` which reads `ACADEMIC_CALENDARS` (the
    hand-maintained table in `sustech_survival.context`) and rounds
    `semester_start` back to the most recent Monday before computing
    `(today - aligned_start).days // 7 + 1`.

    Falls back to 1 if:
      - The (xn, xq) isn't in ACADEMIC_CALENDARS
      - Today is outside the semester window
      - Anything else goes wrong

    To get a real number for a semester not yet in the table, add it to
    `sustech_survival/context/__init__.py:ACADEMIC_CALENDARS`.
    """
    try:
        from .live import current_week
        w = current_week(c.xn, c.xq)
        return w if w is not None else 1
    except Exception:
        return 1


def cmd_search_rooms(args) -> int:
    """Find rooms matching demand + time filters (TIS 选择场地 modal).

    Uses `live_rooms_free_at()` for occupancy check + `queryDiDian` catalog
    for filter matching (capacity, building, media, tiered, movable-seats).

    This is the CLI equivalent of the TIS UI's 选择场地 dialog.
    """
    from sustech_survival.tis.classroom.classroom import ClassroomOccupancy
    from pathlib import Path
    actual_skill_root = Path.home() / ".openclaw" / "code" / "sustech_survival"
    c = ClassroomOccupancy(xn=args.xn, xq=args.xq, skill_root=actual_skill_root)

    didian = c._query_didian_catalog()
    if not didian:
        print("❌ Could not fetch room catalog from TIS. Check your session.", file=sys.stderr)
        return 1

    # Filter by campus
    if args.campus:
        didian = [r for r in didian if str(r.get("xiaoqu", "")) == str(args.campus)]

    # Filter by building
    if args.building:
        building = args.building
        didian = [r for r in didian if building in (r.get("jxlmc") or "") or building in (r.get("mc") or "")]

    # Filter by capacity
    if args.min_cap:
        didian = [r for r in didian if int(r.get("zws", 0) or 0) >= args.min_cap]

    # Filter by movable-seats
    movable_map = {"not-care": None, "yes": "1", "no": "0"}
    movable_filter = movable_map.get(args.movable_seats)
    if movable_filter is not None:
        didian = [r for r in didian if r.get("zysfkyd") == movable_filter]

    # Filter by tiered
    tiered_map = {"not-care": None, "yes": "1", "no": "0"}
    tiered_filter = tiered_map.get(args.tiered)
    if tiered_filter is not None:
        didian = [r for r in didian if r.get("sfjtjs") == tiered_filter]

    # Categorize by type (cdlb / lbmc)
    cdlb_map = {}
    for r in didian:
        lbmc = r.get("lbmc") or r.get("cdlb") or "未知"
        cdlb_map.setdefault(lbmc, []).append(r)

    # ── Check live occupancy (who's free at this time) ──
    free_names = set()
    if args.period_start:
        try:
            free_names = set(c.live_rooms_free_at(
                week=args.week, day=args.day,
                period_start=args.period_start, period_end=args.period_end,
            ))
        except Exception:
            pass

    # Cross-reference: only rooms in both catalog filter AND free
    if free_names:
        didian_free = [r for r in didian if r.get("mc") in free_names]
        didian_occupied = [r for r in didian if r.get("mc") not in free_names]
    else:
        didian_free = didian
        didian_occupied = []

    print(f"=== Room search: week {args.week} day {args.day} "
          f"period {args.period_start if args.period_start else ''}"
          f"{'-'+str(args.period_end) if args.period_end and args.period_end != args.period_start else ''} ===")
    print(f"Filters: campus={args.campus} capacity≥{args.min_cap or 0} "
          f"building={args.building or 'any'} "
          f"tiered={args.tiered} movable={args.movable_seats}")
    print(f"Catalog-matched: {len(didian)}  "
          f"Free at that time: {len(didian_free)}  "
          f"Occupied: {len(didian_occupied)}")

    # Group free rooms by category
    cdlb_map_free = {}
    for r in didian_free:
        lbmc = r.get("lbmc") or r.get("cdlb") or "未知"
        cdlb_map_free.setdefault(lbmc, []).append(r)

    for lbmc, rooms in sorted(cdlb_map_free.items()):
        print(f"\n  {lbmc} ({len(rooms)} free)")
        for r in sorted(rooms, key=lambda x: int(x.get("zws", 0) or 0), reverse=True)[:10]:
            mc = r.get("mc", "?")
            dm = r.get("dm", "?")
            zws = r.get("zws", "?")
            print(f"    ✓ {mc} ({dm}) — {zws}座")
        if len(rooms) > 10:
            print(f"    ... ({len(rooms) - 10} more)")

    if didian_occupied:
        print(f"\n  ── Occupied ({len(didian_occupied)} rooms) ──")
        for r in sorted(didian_occupied,
                        key=lambda x: int(x.get("zws", 0) or 0), reverse=True)[:5]:
            mc = r.get("mc", "?")
            dm = r.get("dm", "?")
            print(f"    ✗ {mc} ({dm})")
        if len(didian_occupied) > 5:
            print(f"    ... ({len(didian_occupied) - 5} more)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.tis.classroom",
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

    sp = sub.add_parser("live",
                        help="All live schedule entries for a room "
                             "(incl. borrowings 借用)")
    sp.add_argument("room", help="Room display name (e.g. 一教123)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_live)

    sp = sub.add_parser("live-at",
                        help="Live entries active at (week, day[, period])")
    sp.add_argument("room", help="Room display name")
    sp.add_argument("--week", type=int, required=True)
    sp.add_argument("--day", type=int, required=True,
                    help="1=Mon ... 7=Sun")
    sp.add_argument("--period", type=int, default=None,
                    help="Period number (1-12). Optional.")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_live_at)

    sp = sub.add_parser("now",
                        help="What's currently in this room (local time)")
    sp.add_argument("room", help="Room display name")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_now)

    sp = sub.add_parser("book",
                        help="Build a venue-borrowing application "
                             "(dry-run by default)")
    sp.add_argument("--room",
                    help="Room display name (e.g. 一教324) or code (YJ-324)")
    sp.add_argument("--day", type=int,
                    help="Weekday 1=Mon ... 7=Sun")
    sp.add_argument("--period", type=int, nargs="+",
                    help="Period number(s) (1-12). One or two (range). "
                         "Alternative to --clock-start/--clock-end.")
    sp.add_argument("--clock-start", default=None,
                    help='Clock start (e.g. "14:00"). Alternative to --period.')
    sp.add_argument("--clock-end", default=None,
                    help='Clock end (e.g. "16:00"). Alternative to --period.')
    sp.add_argument("--week", type=int, nargs="+",
                    help="Week number(s) (1-17). One or more.")
    sp.add_argument("--slot", action="append", default=None,
                    help='Multi-ticket: "room=X day=N [period=P1-P2|clock=14:00-16:00] week=W [date=YYYY-MM-DD]" '
                         'Repeat for each ticket. Alternative to --room/--day/--period/--week.')
    sp.add_argument("--headcount", type=int, required=True,
                    help="Number of people")
    sp.add_argument("--purpose", required=True,
                    help="借用原因 (purpose)")
    sp.add_argument("--campus", default="1",
                    help="校区: 1=一期 (default), 2=二期, 9=九祥")
    sp.add_argument("--start-date", default=None,
                    help="Start date YYYY-MM-DD (per-row ksrq)")
    sp.add_argument("--end-date", default=None,
                    help="End date YYYY-MM-DD (per-row jsrq)")
    sp.add_argument("--applicant-name", default=None,
                    help="申请人 sqr (override session default)")
    sp.add_argument("--applicant-phone", default=None,
                    help="申请人 sqrdh")
    sp.add_argument("--applicant-id", default=None,
                    help="申请人职工/学号 sqrzgh")
    sp.add_argument("--applicant-dept", default=None,
                    help="申请人单位 sqrdw")
    sp.add_argument("--applicant-dept-en", default=None,
                    help="申请人单位 EN sqrdw_en")
    sp.add_argument("--user-name", default=None,
                    help="使用人 syr (defaults to --applicant-name)")
    sp.add_argument("--user-phone", default=None,
                    help="使用人 syrdh (defaults to --applicant-phone)")
    sp.add_argument("--media", action="store_true", default=True,
                    help="使用设备 sfsysb='1' (default)")
    sp.add_argument("--no-media", dest="media", action="store_false",
                    help="不使用设备 sfsysb='0'")
    sp.add_argument("--tiered", default="not-care",
                    choices=["not-care", "yes", "no"],
                    help="阶梯教室 sfjtjs: not-care(默认)/yes/no")
    sp.add_argument("--movable-seats", default="not-care",
                    choices=["not-care", "yes", "no"],
                    help="座椅可移动 zysfkyd: not-care(默认)/yes/no")
    sp.add_argument("--save", action="store_true",
                    help="保存 draft (shbj='0') instead of 提交 submit (shbj='1')")
    sp.add_argument("--dry-run", action="store_true", default=True,
                    help="Print wire payload, no POST (default)")
    sp.add_argument("--commit", dest="dry_run", action="store_false",
                    help="Actually POST to TIS (requires --yes or interactive confirm)")
    sp.add_argument("--yes", action="store_true",
                    help="Skip confirmation prompt (with --commit)")
    sp.set_defaults(func=cmd_book)

    sp = sub.add_parser("search-rooms",
                        help="Search available rooms matching filters "
                             "(TIS 选择场地 dialog)")
    sp.add_argument("--week", type=int, default=1,
                    help="Week number (1-17)")
    sp.add_argument("--day", type=int, required=True,
                    help="Weekday 1=Mon ... 7=Sun")
    sp.add_argument("--period", type=int, nargs="+",
                    help="Period number(s) (1-12). One or two (range).")
    sp.add_argument("--campus", default="1",
                    help="校区: 1=一期 (default), 2=二期, 9=九祥")
    sp.add_argument("--building", default=None,
                    help="Filter by building name (e.g. 一教, 智华楼)")
    sp.add_argument("--min-cap", type=int, default=None,
                    help="Minimum capacity")
    sp.add_argument("--tiered", default="not-care",
                    choices=["not-care", "yes", "no"],
                    help="阶梯教室 sfjtjs")
    sp.add_argument("--movable-seats", default="not-care",
                    choices=["not-care", "yes", "no"],
                    help="座椅可移动 zysfkyd")
    sp.set_defaults(func=cmd_search_rooms)

    return p


def _normalize_period_args(args) -> None:
    """Convert --period list into (start, end) attributes for the `free` and `search-rooms` cmds."""
    if not hasattr(args, "period") or not isinstance(args.period, list):
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

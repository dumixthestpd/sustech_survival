"""
sustech_survival.selectcourse — CLI.

Usage:
    python -m sustech_survival.selectcourse <command> [...]

Commands (human + agent friendly):
    list [KW]                      List course offerings for the semester
        --xn YEAR --xq N            Override semester (default 2025-2026 / 2)
        --cultivation 本科|研究生   Filter by 本科/研究生
        --college "生命科学学院"    Filter by college (substring)
        --nature "必修|选修"        Filter by course nature
        --campus "一期校区"         Filter by campus
        --scheduled                 Only show courses with parsed schedule
        --json
    course CODE [--group N]        Show details for one course offering
        --json
    enrolled                       Your enrolled courses for the semester
        --semester "2025-2026-3"    Override (default: current xn/xq)
        --json
    refresh                        Force-refresh from TIS (bust cache)

    # WRITE-side (state-mutating; default to --dry-run for safety)
    add RWH                        Add course (Xsxk/addXuanke) --dry-run
        --dry-run / --no-dry-run   Toggle (default: dry-run)
        --ignore-conflicts         Pass p_sfhlctkc=1
    drop RWH                       Drop course (Xsxk/tuike) --dry-run
        --dry-run / --no-dry-run   Toggle
    add-to-cart RWH                Add to shopping cart (Xsxk/addGouwuche)
    remove-from-cart RWH           Remove from cart (Xsxk/delGouwuche)

Examples:
    # Browse SUMMER 2026 offerings
    python -m sustech_survival.selectcourse list --xq 3
    python -m sustech_survival.selectcourse list 生物学 --xq 3

    # Course detail
    python -m sustech_survival.selectcourse course BIO463 --group 001 --xq 3

    # What you're enrolled in
    python -m sustech_survival.selectcourse enrolled --semester 2025-2026-3

    # Add course (dry-run: shows payload, doesn't mutate)
    python -m sustech_survival.selectcourse add 2025-2026-2-BIO101-001
    # Real add (mutates your enrollment — be sure!)
    python -m sustech_survival.selectcourse add 2025-2026-2-BIO101-001 --no-dry-run

    # Drop course
    python -m sustech_survival.selectcourse drop 2025-2026-2-BIO101-001
"""
from __future__ import annotations

import argparse
import json
import sys

from .selectcourse import selectcourse as sc_factory


def _print_courses(courses, as_json: bool = False) -> None:
    if as_json:
        out = [
            {
                "code": c.code, "name": c.name, "name_en": c.name_en,
                "class_group": c.class_group, "rwh": c.rwh,
                "college": c.college, "nature": c.nature,
                "credits": c.credits, "capacity": c.capacity,
                "rooms": c.rooms, "teachers": c.teachers,
                "schedule": c.schedule_str,
                "slots": c.slots_raw,
            }
            for c in courses
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not courses:
        print("(no courses)")
        return
    print(f"{'CODE':<10} {'GRP':<4} {'CR':>4} {'NATURE':<8} COURSE")
    print("-" * 100)
    for c in courses:
        print(f"{c.code:<10} {c.class_group:<4} {c.credits:>4.1f} {c.nature:<8} {c.name}")
        if c.teachers:
            print(f"           teachers: {', '.join(c.teachers)}")
        if c.rooms:
            print(f"           rooms:    {', '.join(c.rooms)}")
        if c.has_schedule:
            print(f"           schedule: {c.schedule_str}")


def _print_course(c, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({
            "code": c.code, "name": c.name, "name_en": c.name_en,
            "class_group": c.class_group, "rwh": c.rwh,
            "college": c.college, "category": c.category,
            "nature": c.nature, "campus": c.campus,
            "credits": c.credits, "total_hours": c.total_hours,
            "capacity": c.capacity, "undergrad_seats": c.undergrad_seats,
            "grad_seats": c.grad_seats,
            "cultivation": c.cultivation,
            "rooms": c.rooms, "teachers": c.teachers,
            "schedule": c.schedule_str,
            "slots": c.slots_raw,
        }, ensure_ascii=False, indent=2))
        return
    print(f"  Code:         {c.code}  ({c.class_group})")
    print(f"  RWH:          {c.rwh}")
    print(f"  Name:         {c.name}")
    print(f"  EN:           {c.name_en}")
    print(f"  College:      {c.college}")
    print(f"  Category:     {c.category}")
    print(f"  Nature:       {c.nature}  ({c.cultivation})")
    print(f"  Campus:       {c.campus}")
    print(f"  Credits/Hrs:  {c.credits}学分 / {c.total_hours}学时")
    if c.capacity is not None:
        u = c.undergrad_seats or 0
        g = c.grad_seats or 0
        print(f"  Capacity:     {c.capacity}  (本科 {u}, 研究生 {g})")
    if c.teachers:
        print(f"  Teachers:     {', '.join(c.teachers)}")
    if c.rooms:
        print(f"  Rooms:        {', '.join(c.rooms)}")
    if c.has_schedule:
        print(f"  Schedule:     {c.schedule_str}")
    else:
        print(f"  Schedule:     (none parsed — see kcxx HTML)")


def _print_enrolled(items, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        print("(no courses enrolled)")
        return
    print(f"  {len(items)} courses enrolled")
    for item in items:
        name = item.get("rwmc") or item.get("kcmc") or "?"
        code = item.get("kcdm") or "?"
        group = item.get("kxh") or ""
        rwh = item.get("RWH") or item.get("rwh") or ""
        when = item.get("SKSJ") or ""
        print(f"  [{code} {group}] {name}  ({rwh})  {when}")


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_list(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    courses = sc.list_courses(
        keyword=args.keyword or "",
        cultivation=args.cultivation,
        college=args.college,
        nature=args.nature,
        campus=args.campus,
    )
    if args.scheduled:
        courses = [c for c in courses if c.has_schedule]
    print(f"=== Catalog {args.xn} xq={args.xq} ({len(courses)} courses) ===")
    _print_courses(courses, as_json=args.json)
    return 0


def cmd_course(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    c = sc.by_code(args.code, args.group or "")
    if c is None:
        print(f"Course {args.code!r} (group {args.group!r}) not found "
              f"in {args.xn} xq={args.xq}.", file=sys.stderr)
        return 1
    _print_course(c, as_json=args.json)
    return 0


def cmd_enrolled(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    sem = args.semester or f"{args.xn}-{args.xq}"
    items = sc.my_courses(sem)
    print(f"=== Enrolled in {sem} ===")
    _print_enrolled(items, as_json=args.json)
    return 0


def cmd_refresh(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    n = sc.refresh()
    print(f"Refreshed: {n} courses cached.")
    return 0


def _print_write_result(label: str, rwh: str, res: dict, *,
                        dry_run: bool, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({"action": label, "rwh": rwh, **res},
                         ensure_ascii=False, indent=2))
        return
    if dry_run:
        print(f"[DRY RUN] {label} {rwh}")
        print(f"  endpoint: {res['endpoint']}")
        print(f"  would POST:")
        for k, v in res["would_post"].items():
            if v not in (None, "", [], "0"):
                print(f"    {k} = {v!r}")
        return
    jg = res.get("jg", "?")
    msg = res.get("message", "")
    ok = jg == "1"
    marker = "✓" if ok else "✗"
    print(f"{marker} {label} {rwh}: jg={jg}  {msg}")
    if not ok:
        print(f"  (this would have raised EnrollmentError if called from Python)")


def cmd_add(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    res = sc.add_course(
        args.rwh,
        dry_run=args.dry_run,
        ignore_conflicts=args.ignore_conflicts,
        ignore_zero_capacity=args.ignore_zero_capacity,
        pylx=args.pylx,
    )
    label = "ADD COURSE →" if args.dry_run else "ADDED COURSE →"
    _print_write_result(label, args.rwh, res,
                        dry_run=args.dry_run, as_json=args.json)
    return 0 if (args.dry_run or res.get("jg") == "1") else 1


def cmd_drop(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    res = sc.drop_course(args.rwh, dry_run=args.dry_run, pylx=args.pylx)
    label = "DROP COURSE →" if args.dry_run else "DROPPED COURSE →"
    _print_write_result(label, args.rwh, res,
                        dry_run=args.dry_run, as_json=args.json)
    return 0 if (args.dry_run or res.get("jg") == "1") else 1


def cmd_add_to_cart(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    res = sc.add_to_cart(args.rwh, dry_run=args.dry_run, pylx=args.pylx)
    label = "ADD TO CART →" if args.dry_run else "ADDED TO CART →"
    _print_write_result(label, args.rwh, res,
                        dry_run=args.dry_run, as_json=args.json)
    return 0 if (args.dry_run or res.get("jg") == "1") else 1


def cmd_remove_from_cart(args) -> int:
    sc = sc_factory(xn=args.xn, xq=args.xq)
    res = sc.remove_from_cart(args.rwh, dry_run=args.dry_run, pylx=args.pylx)
    label = "REMOVE FROM CART →" if args.dry_run else "REMOVED FROM CART →"
    _print_write_result(label, args.rwh, res,
                        dry_run=args.dry_run, as_json=args.json)
    return 0 if (args.dry_run or res.get("jg") == "1") else 1


def _add_write_common(p):
    """Common args for write-side commands."""
    p.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                   default=True,
                   help="Actually fire the request (default: dry-run)")
    p.add_argument("--pylx", default=None,
                   help="培养类型 (1=本科, 2=研究生). Auto if omitted.")
    p.add_argument("--json", action="store_true")


# ── Parser ──────────────────────────────────────────────────────────────────


def _add_semester_args(p):
    """Add --xn / --xq to a subparser."""
    p.add_argument("--xn", default="2025-2026",
                   help="Academic year (default 2025-2026)")
    p.add_argument("--xq", default="2",
                   help="Semester: 1=Fall, 2=Spring, 3=Summer")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.selectcourse",
        description="TIS course catalog + enrollment browser",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="Browse course catalog")
    _add_semester_args(sp)
    sp.add_argument("keyword", nargs="?", default="",
                    help="Filter by code/name/college/category substring")
    sp.add_argument("--cultivation", default=None,
                    help="Filter by 本科 / 研究生")
    sp.add_argument("--college", default=None, help="Filter by college")
    sp.add_argument("--nature", default=None,
                    help="Filter by 必修 / 选修 / etc.")
    sp.add_argument("--campus", default=None, help="Filter by campus")
    sp.add_argument("--scheduled", action="store_true",
                    help="Only show courses with parsed schedule")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("course", help="Show details for one course")
    _add_semester_args(sp)
    sp.add_argument("code", help="Course code, e.g. BIO463")
    sp.add_argument("--group", default="", help="Class group, e.g. 001")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_course)

    sp = sub.add_parser("enrolled", help="Your enrolled courses")
    _add_semester_args(sp)
    sp.add_argument("--semester", default=None,
                    help="YYYY-YYYY-N (default: current xn/xq)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_enrolled)

    sp = sub.add_parser("refresh", help="Force-refresh from TIS")
    _add_semester_args(sp)
    sp.set_defaults(func=cmd_refresh)

    # ── Write-side commands (state-mutating; default dry-run) ────────────
    sp = sub.add_parser("add", help="Add course (Xsxk/addXuanke) — dry-run by default")
    _add_semester_args(sp)
    sp.add_argument("rwh", help="Course 任务号 (rwh), e.g. 2025-2026-2-BIO101-001")
    _add_write_common(sp)
    sp.add_argument("--ignore-conflicts", action="store_true",
                    help="Set p_sfhlctkc=1 (skip schedule conflict check)")
    sp.add_argument("--ignore-zero-capacity", action="store_true",
                    help="Set p_sfhllrlkc=1 (skip zero-capacity check)")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("drop", help="Drop course (Xsxk/tuike) — dry-run by default")
    _add_semester_args(sp)
    sp.add_argument("rwh", help="Course 任务号 (rwh)")
    _add_write_common(sp)
    sp.set_defaults(func=cmd_drop)

    sp = sub.add_parser("add-to-cart",
                        help="Add to shopping cart (Xsxk/addGouwuche) — dry-run")
    _add_semester_args(sp)
    sp.add_argument("rwh", help="Course 任务号 (rwh)")
    _add_write_common(sp)
    sp.set_defaults(func=cmd_add_to_cart)

    sp = sub.add_parser("remove-from-cart",
                        help="Remove from cart (Xsxk/delGouwuche) — dry-run")
    _add_semester_args(sp)
    sp.add_argument("rwh", help="Course 任务号 (rwh)")
    _add_write_common(sp)
    sp.set_defaults(func=cmd_remove_from_cart)

    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

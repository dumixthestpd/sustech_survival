#!/usr/bin/env python3
"""
sustech_survival.lib.booking — CLI for the IC library booking system.

Usage:
    python -m sustech_survival.lib.booking whoami
    python -m sustech_survival.lib.booking home-summary
    python -m sustech_survival.lib.booking labs
    python -m sustech_survival.lib.booking rooms --kind 1 --lab 4
    python -m sustech_survival.lib.booking my-reservations
    python -m sustech_survival.lib.booking my-reservations --start 2026-06-01 --end 2026-07-30
    python -m sustech_survival.lib.booking resv-count
    python -m sustech_survival.lib.booking resv-info --id 12345
    python -m sustech_survival.lib.booking reserve \
        --room 13 --start "2026-07-01 14:00" --end "2026-07-01 15:00" --title "team sync"
    python -m sustech_survival.lib.booking cancel --id 12345

Add `--dry-run` to any write to stage the payload without POSTing.
Add `--json` to any command for machine-readable output.

This is a thin wrapper over the Python API. All business logic lives in
`client.py` and `schema.py`; the CLI is for human convenience only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from typing import Any

from .client import DEFAULT_CLASS_KIND, lib_booking
from .client import LibBookingPolicyError  # noqa: E402
from .schema import build_reservation_payload


# ── Helpers ──────────────────────────────────────────────────────────────────


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _print_kv(items: list, *, as_json: bool = False) -> None:
    if as_json:
        _print_json(dict(items))
        return
    width = max(len(k) for k, _ in items) if items else 0
    for k, v in items:
        print(f"  {k:<{width}}  {v}")


def _parse_dt(s: str) -> datetime:
    """Parse a datetime string in either "YYYY-MM-DD HH:MM" or ISO format."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Could not parse datetime: {s!r} (expected YYYY-MM-DD HH:MM)"
    )


def _parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Could not parse date: {s!r} (expected YYYY-MM-DD)"
    )


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_whoami(args, client) -> int:
    me = client.whoami()
    items = [
        ("name", me.true_name),
        ("acc_no", me.acc_no),
        ("pid", me.pid),
        ("logon_name", me.logon_name),
        ("class", me.class_name),
        ("dept", me.dept_name),
        ("kind", me.kind),
        ("ident", me.ident),
        ("manager", me.manager),
        ("status", me.status),
    ]
    if args.json:
        _print_json(me.__dict__)
    else:
        _print_kv(items)
    return 0


def cmd_home_summary(args, client) -> int:
    cats = client.home_summary()
    if args.json:
        _print_json([c.__dict__ for c in cats])
        return 0
    print(f"=== IC library idle summary ({len(cats)} categories) ===")
    for c in cats:
        print(f"  {c.idle_quantity:>3}/{c.total_quantity:<3}  {c.name}")
    return 0


def cmd_labs(args, client) -> int:
    labs = client.labs(class_kind=args.class_kind)
    if args.json:
        _print_json([l.__dict__ for l in labs])
        return 0
    print(f"=== Labs (classKind={args.class_kind}) — {len(labs)} ===")
    for l in labs:
        print(f"  [{l.lab_id:>3}]  {l.lab_name}")
    return 0


def cmd_rooms(args, client) -> int:
    groups = client.rooms(kind_id=args.kind, lab_id=args.lab, class_kind=args.class_kind)
    if args.json:
        _print_json([
            {
                "campus_id": g.campus_id,
                "campus_name": g.campus_name,
                "labs": [
                    {
                        "lab_id": l.lab_id,
                        "lab_name": l.lab_name,
                        "rooms": [r.__dict__ for r in l.rooms],
                    }
                    for l in g.labs
                ],
            }
            for g in groups
        ])
        return 0
    print(f"=== Rooms (kind={args.kind}, lab={args.lab}, classKind={args.class_kind}) ===")
    for g in groups:
        print(f"\nCampus [{g.campus_id}] {g.campus_name}")
        for l in g.labs:
            print(f"  Lab [{l.lab_id}] {l.lab_name}")
            for r in l.rooms:
                open_str = ", ".join(
                    f"{t.open_start_time}-{t.open_end_time}" for t in r.open_times
                ) or "(no open times)"
                print(f"    [{r.dev_id:>3}] {r.dev_name}  ({r.min_resv_time}m min, open {open_str})")
    return 0


def cmd_my_reservations(args, client) -> int:
    end = args.end or date.today() + timedelta(days=30)
    start = args.start or (end - timedelta(days=30))
    resvs = client.my_reservations(start, end, page=args.page, page_size=args.page_size)
    if args.json:
        _print_json([
            {
                "resv_id": r.resv_id,
                "dev_id": r.dev_id,
                "dev_name": r.dev_name,
                "title": r.title,
                "begin_time": r.begin_time.isoformat() if r.begin_time else None,
                "end_time": r.end_time.isoformat() if r.end_time else None,
                "memo": r.memo,
                "status": r.status,
            }
            for r in resvs
        ])
        return 0
    print(f"=== My reservations ({start} → {end}) — {len(resvs)} ===")
    for r in resvs:
        b = r.begin_time.isoformat() if r.begin_time else "?"
        e = r.end_time.isoformat() if r.end_time else "?"
        print(f"  [{r.resv_id}] {r.dev_name or f'devId={r.dev_id}'}  {b} → {e}  {r.title!r}")
    return 0


def cmd_resv_count(args, client) -> int:
    n = client.reservation_count()
    print(f"Current reservation count: {n}")
    return 0


def cmd_resv_info(args, client) -> int:
    r = client.resv_info(args.id)
    if r is None:
        print(f"No reservation found with id {args.id}")
        return 1
    items = [
        ("resv_id", r.resv_id),
        ("dev_id", r.dev_id),
        ("dev_name", r.dev_name),
        ("title", r.title),
        ("begin", r.begin_time.isoformat() if r.begin_time else None),
        ("end", r.end_time.isoformat() if r.end_time else None),
        ("memo", r.memo),
        ("status", r.status),
    ]
    if args.json:
        _print_json(r.__dict__)
    else:
        _print_kv(items)
    return 0


def cmd_reserve(args, client) -> int:
    me = client.whoami()
    payload = build_reservation_payload(
        acc_no=me.acc_no,
        dev_id=args.room,
        begin=args.start,
        end=args.end,
        title=args.title,
        class_kind=args.class_kind,
        member_kind=args.member_kind,
        memo=args.memo or "",
    )
    if args.dry_run:
        print("=== DRY RUN — not POSTing. Wire payload that WOULD be sent: ===")
        result = {"endpoint": "POST /reserve (params=...)", "payload": payload}
        if args.enforce_policy:
            # Dry-run with policy check
            dry = client.add_reservation(
                dev_id=args.room,
                begin=args.start,
                end=args.end,
                title=args.title,
                class_kind=args.class_kind,
                member_kind=args.member_kind,
                memo=args.memo or "",
                dry_run=True,
                enforce_policy=True,
            )
            if "policy_warnings" in dry:
                result["policy_warnings"] = dry["policy_warnings"]
        _print_json(result)
        if result.get("policy_warnings"):
            print("\n⚠ Policy warnings (advisory only in dry-run):")
            for w in result["policy_warnings"]:
                print(f"  - {w}")
        print("\nTo commit, re-run with --commit (or remove --dry-run).")
        return 0
    print(f"Creating reservation for {me.true_name} (accNo={me.acc_no}) ...")
    try:
        result = client.add_reservation(
            dev_id=args.room,
            begin=args.start,
            end=args.end,
            title=args.title,
            class_kind=args.class_kind,
            member_kind=args.member_kind,
            memo=args.memo or "",
            dry_run=False,
            enforce_policy=args.enforce_policy,
        )
    except LibBookingPolicyError as e:
        print(f"✗ Policy violation:\n{e}", file=sys.stderr)
        return 1
    print("✓ Reservation created:")
    _print_json(result)
    return 0


def cmd_cancel(args, client) -> int:
    if args.dry_run:
        print("=== DRY RUN — not POSTing. Wire params that WOULD be sent: ===")
        result = {
            "endpoint": "POST /reserve/delete",
            "params": {"resvId": args.id},
        }
        if args.enforce_policy:
            dry = client.cancel_reservation(args.id, dry_run=True, enforce_policy=True)
            if "policy_warnings" in dry:
                result["policy_warnings"] = dry["policy_warnings"]
        _print_json(result)
        if result.get("policy_warnings"):
            print("\n⚠ Policy warnings (advisory only in dry-run):")
            for w in result["policy_warnings"]:
                print(f"  - {w}")
        print("\nTo commit, re-run with --commit.")
        return 0
    print(f"Cancelling reservation {args.id} ...")
    try:
        result = client.cancel_reservation(
            args.id, dry_run=False, enforce_policy=args.enforce_policy,
        )
    except LibBookingPolicyError as e:
        print(f"✗ Policy violation:\n{e}", file=sys.stderr)
        return 1
    print("✓ Cancelled:")
    _print_json(result)
    return 0


def cmd_policy(args, client=None) -> int:
    """Print the library booking policy (no auth required)."""
    print(LIB_POLICY_TEXT)
    return 0


LIB_POLICY_TEXT = """\
南方科技大学图书馆讨论间使用办法
================================

学校图书馆面向本校全体师生提供学习研究和学术研讨的独立讨论间，
所有讨论间采用自助式服务。为规范讨论间管理，特制定本办法。

1、预约及使用方式

  1.1 读者可使用学校统一认证系统的用户名及密码通过以下三种方式预约：
      (1) 登录图书馆网站 http://lib.sustech.edu.cn/，点击首页下方"讨论间预约"。
      (2) 登录微信公众号，点击"资源"下的"讨论间预约"。
      (3) 通过讨论间门口PAD屏扫码预约。

  1.2 读者可提前 2天 预约，每次最多可预约 2小时，
      讨论间使用完毕后可再次预约。

  1.3 1-3人讨论间由主预约人填写使用主题后即可预约；
      3人以上讨论间由主预约人填写使用主题后，需在组成员中
      再添加 2位及以上组员 校园卡号后方可预约。

  1.4 读者可提前 10分钟 到预约房间门口PAD屏上刷卡签到。
      3人以上讨论间，至少需 3人刷卡 才算签到成功，否则
      记主预约人 1次违规，取消预约权限 1周。

  1.5 超过预约时间 15分钟 不到的，系统自动取消该时段预约权限，
      并记主预约人 1次违规，取消预约权限 1周。

  1.6 预约成功后如计划更改，请在预约开始时间 10分钟之前
      登录讨论间管理系统，点击"个人中心"取消预约。

2、使用要求

  2.1 使用时需遵守国家法律及学校有关规章制度，不得从事学习、研究以外的活动。
  2.2 爱护公物，不得移动、损坏室内设施、设备。
  2.3 勿携带食物及饮料进入，保持室内清洁卫生。
  2.4 按时离开，离开时带走个人随身物品；临时借阅的馆内图书
      放至讨论间外的书车上，并随手关门。
  2.5 违反讨论间使用管理要求，停止使用讨论间 1个月。

服务咨询电话：0755-88010800。

⚠ This policy is enforced client-side by sustech_survival.lib.booking.
By default the CLI surfaces violations as warnings (dry-run) or errors
(commit). Pass --no-policy to skip the check (NOT recommended).
"""


# ── Argument parser ──────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sustech_survival.lib.booking",
        description="IC library booking CLI (research rooms, meeting rooms, etc.)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--json", action="store_true", help="Output JSON")

    # whoami
    sp = sub.add_parser("whoami", help="Show current user info")
    add_common(sp)
    sp.set_defaults(func=cmd_whoami)

    # home-summary
    sp = sub.add_parser("home-summary", help="Idle room summary (homepage)")
    add_common(sp)
    sp.set_defaults(func=cmd_home_summary)

    # labs
    sp = sub.add_parser("labs", help="List labs (楼层 / 区域)")
    add_common(sp)
    sp.add_argument("--class-kind", type=int, default=DEFAULT_CLASS_KIND,
                    help=f"classKind (default {DEFAULT_CLASS_KIND} = research rooms)")
    sp.set_defaults(func=cmd_labs)

    # rooms
    sp = sub.add_parser("rooms", help="List rooms in a (kind, lab) pair")
    add_common(sp)
    sp.add_argument("--kind", type=int, required=True, help="kindId (e.g. 1)")
    sp.add_argument("--lab", type=int, required=True, help="labId (e.g. 4)")
    sp.add_argument("--class-kind", type=int, default=DEFAULT_CLASS_KIND)
    sp.set_defaults(func=cmd_rooms)

    # my-reservations
    sp = sub.add_parser("my-reservations", help="List my reservations")
    add_common(sp)
    sp.add_argument("--start", type=_parse_date, help="Start date (default: end-30d)")
    sp.add_argument("--end", type=_parse_date, help="End date (default: today+30d)")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--page-size", type=int, default=20)
    sp.set_defaults(func=cmd_my_reservations)

    # resv-count
    sp = sub.add_parser("resv-count", help="Current reservation count")
    add_common(sp)
    sp.set_defaults(func=cmd_resv_count)

    # resv-info
    sp = sub.add_parser("resv-info", help="Single reservation info by ID")
    add_common(sp)
    sp.add_argument("--id", type=int, required=True, help="Reservation ID")
    sp.set_defaults(func=cmd_resv_info)

    # reserve (create)
    sp = sub.add_parser("reserve", help="Create a reservation (DRY-RUN by default)")
    sp.add_argument("--room", type=int, required=True, help="devId (room ID)")
    sp.add_argument("--start", type=_parse_dt, required=True,
                    help='Start datetime (e.g. "2026-07-01 14:00")')
    sp.add_argument("--end", type=_parse_dt, required=True,
                    help='End datetime (e.g. "2026-07-01 15:00")')
    sp.add_argument("--title", required=True, help='Reservation title (testName)')
    sp.add_argument("--memo", default="", help="Notes/memo")
    sp.add_argument("--class-kind", type=int, default=DEFAULT_CLASS_KIND)
    sp.add_argument("--member-kind", type=int, default=1,
                    help="1=self, 2=group (default 1)")
    sp.add_argument("--no-policy", dest="enforce_policy",
                    action="store_false", default=True,
                    help="Skip library policy validation (NOT recommended)")
    sp.add_argument("--dry-run", action="store_true", default=True,
                    help="Stage the payload without POSTing (default)")
    sp.add_argument("--commit", dest="dry_run", action="store_false",
                    help="Actually POST the reservation")
    sp.set_defaults(func=cmd_reserve)

    # cancel
    sp = sub.add_parser("cancel", help="Cancel a reservation (DRY-RUN by default)")
    sp.add_argument("--id", type=int, required=True, help="Reservation ID to cancel")
    sp.add_argument("--no-policy", dest="enforce_policy",
                    action="store_false", default=True,
                    help="Skip library policy validation (NOT recommended)")
    sp.add_argument("--dry-run", action="store_true", default=True)
    sp.add_argument("--commit", dest="dry_run", action="store_false")
    sp.set_defaults(func=cmd_cancel)

    # policy — print the library booking policy
    sp = sub.add_parser("policy", help="Print the library booking policy")
    sp.set_defaults(func=cmd_policy)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # `policy` doesn't need auth — short-circuit.
    if args.command == "policy":
        return args.func(args, None)
    try:
        client = lib_booking()
    except Exception as e:
        print(f"✗ Auth failed: {e}", file=sys.stderr)
        return 2
    try:
        return args.func(args, client)
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

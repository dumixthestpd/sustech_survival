"""
sustech_survival.pms — CLI.

Usage:
    python -m sustech_survival.pms <command> [...]

Commands (human + agent friendly):
    check                Verify the session is alive
    stations [GROUP]     List campus printers/copiers/scanners
    groups               List server groups (the dropdown)
    jobs                 List uploaded-but-not-printed documents
    job-delete ID        Delete a print job
    scans                List scanned documents
    scan-delete ID       Delete a scan
    history [OPTS]       Usage records (打印/扫描/复印)
        --type print|scan|copy   (default: print)
        --from YYYY-MM-DD        (default: 3 years ago)
        --to   YYYY-MM-DD        (default: today)
        --page N                 (default: 1)
        --size N                 (default: 20)
    upload FILE [OPTS]   Upload a file for printing at any station
        --color bw|color         (default: bw)
        --paper A4|A3|none       (default: none)
        --duplex single|short|long  (default: single)
        --copies N               (default: 1)
        --from-page N --to-page N  (default: all pages)
        --dry-run                prepare form but don't POST

All output is plain text — readable for both humans and LLMs. Use --json for
machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import pms as pms_singleton_factory
from .pms import PMSError
from .schema import (
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY,
)


def _build_client():
    """Build the PMSClient. Auth handled inside the singleton factory."""
    return pms_singleton_factory()


# ── Output formatting ───────────────────────────────────────────────────────

def _print_station(s, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps({
            "name": s.sz_name,
            "dev_sn": s.dw_dev_sn,
            "state": s.state_text,
            "state_flag": s.state_flag,
            "is_idle": s.is_idle,
            "is_busy": s.is_busy,
            "is_fault": s.is_fault,
            "papers": s.papers,
            "can_print": s.can_print,
            "can_copy": s.can_copy,
            "can_scan": s.can_scan,
            "can_color": s.can_color,
            "ip": "",  # not exposed in Station dataclass — keep schema lean
            "model": "",
        }, ensure_ascii=False))
        return
    flag = {2: "🟢", 1: "🟡", 3: "🔴"}.get(s.state_flag, "⚪")
    papers = "/".join(s.papers) if s.papers else "—"
    funcs = s.functions_text or "—"
    print(f"{flag} {s.sz_name}")
    print(f"     状态: {s.state_text} | 纸型: {papers} | 功能: {funcs}")


def _print_job(j, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps({
            "id": j.dw_job_id,
            "name": j.file_name,
            "pages": j.dw_total_pages,
            "paper": j.paper,
            "copies": j.dw_copies,
            "color": j.is_color,
            "duplex": j.duplex_label,
            "uploaded": j.datetime_str,
        }, ensure_ascii=False))
        return
    print(f"📄 [{j.dw_job_id}] {j.file_name}")
    print(f"     {j.paper or '不指定'}; {j.dw_total_pages}页; {j.dw_copies}份; "
          f"{'彩色' if j.is_color else '黑白'}; {j.duplex_label}")
    print(f"     上传: {j.datetime_str or '—'}")


def _print_scan(s, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps({
            "id": s.dw_job_id,
            "name": s.file_name,
            "size_kb": s.file_size_kb,
            "uploaded": s.datetime_str,
        }, ensure_ascii=False))
        return
    print(f"🔍 [{s.dw_job_id}] {s.file_name} ({s.file_size_kb:.1f} KB) — {s.datetime_str or '—'}")


def _print_record(r, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps({
            "sid": r.dw_sid,
            "datetime": r.datetime_str,
            "paper": r.paper,
            "pages": r.dw_pages,
            "money": r.money_total,
            "settle": r.settle_label,
            "device": r.dw_mfp_sn,
        }, ensure_ascii=False))
        return
    print(f"  {r.datetime_str} | {r.paper or '?'};{r.dw_pages}页 | "
          f"¥{r.money_total:.2f} | {r.settle_label} | dev={r.dw_mfp_sn}")


# ── Command handlers ────────────────────────────────────────────────────────

def cmd_check(args) -> int:
    from sustech_survival.sso.authlib.pms import PMSAuth
    auth = PMSAuth()
    ok, msg = auth.ensure()
    if args.json:
        print(json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False))
    else:
        print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


def cmd_stations(args) -> int:
    c = _build_client()
    group_sn = None
    if args.group:
        groups = c.list_server_groups()
        for g in groups:
            if g.sz_name == args.group or str(g.dw_sn) == args.group:
                group_sn = g.dw_sn
                break
        if group_sn is None:
            print(f"❌ Unknown server group: {args.group!r}", file=sys.stderr)
            print(f"   Known: {[g.sz_name for g in groups]}", file=sys.stderr)
            return 2
    stations = c.list_stations(group_sn=group_sn)
    if not args.json:
        idle = sum(1 for s in stations if s.is_idle)
        busy = sum(1 for s in stations if s.is_busy)
        fault = sum(1 for s in stations if s.is_fault)
        print(f"# {len(stations)} stations ({idle} idle, {busy} busy, {fault} fault)")
        print()
    for s in stations:
        _print_station(s, json_out=args.json)
    return 0


def cmd_groups(args) -> int:
    c = _build_client()
    groups = c.list_server_groups()
    if args.json:
        print(json.dumps([{"sn": g.dw_sn, "name": g.sz_name} for g in groups],
                         ensure_ascii=False))
    else:
        for g in groups:
            print(f"  [{g.dw_sn}] {g.sz_name}")
    return 0


def cmd_jobs(args) -> int:
    c = _build_client()
    jobs = c.list_print_jobs()
    if not args.json:
        print(f"# {len(jobs)} uploaded print jobs")
        print()
    for j in jobs:
        _print_job(j, json_out=args.json)
    return 0


def cmd_job_delete(args) -> int:
    c = _build_client()
    ok = c.delete_print_job(int(args.id))
    if args.json:
        print(json.dumps({"ok": ok, "id": int(args.id)}, ensure_ascii=False))
    else:
        print(("✅ " if ok else "❌ ") + f"Deleted print job {args.id}")
    return 0 if ok else 1


def cmd_scans(args) -> int:
    c = _build_client()
    scans = c.list_scan_jobs()
    if not args.json:
        print(f"# {len(scans)} scanned documents")
        print()
    for s in scans:
        _print_scan(s, json_out=args.json)
    return 0


def cmd_scan_delete(args) -> int:
    c = _build_client()
    ok = c.delete_scan_job(int(args.id))
    if args.json:
        print(json.dumps({"ok": ok, "id": int(args.id)}, ensure_ascii=False))
    else:
        print(("✅ " if ok else "❌ ") + f"Deleted scan {args.id}")
    return 0 if ok else 1


def _type_code(name: str) -> int:
    return {"print": REPORT_TYPE_PRINT, "scan": REPORT_TYPE_SCAN,
            "copy": REPORT_TYPE_COPY}.get(name.lower(), REPORT_TYPE_PRINT)


def cmd_history(args) -> int:
    c = _build_client()
    type_code = _type_code(args.type)
    begin = date.fromisoformat(args.begin) if args.begin else \
        date.today() - timedelta(days=365 * 3)
    end = date.fromisoformat(args.end) if args.end else date.today()
    records, total_pages = c.history(
        begin=begin, end=end, type=type_code,
        page=args.page, page_size=args.size,
    )
    if not args.json:
        total_money = sum(r.money_total for r in records)
        print(f"# {len(records)} records (page {args.page}/{total_pages}) — "
              f"type={args.type}, range={begin}..{end}")
        print(f"# Total ¥{total_money:.2f} on this page")
        print()
    for r in records:
        _print_record(r, json_out=args.json)
    return 0


def cmd_upload(args) -> int:
    c = _build_client()
    if not Path(args.file).exists():
        print(f"❌ File not found: {args.file}", file=sys.stderr)
        return 2
    result = c.upload_print(
        args.file,
        color=args.color,
        paper=args.paper,
        duplex=args.duplex,
        page_from=0 if args.from_page is None else args.from_page,
        page_to=0 if args.to_page is None else args.to_page,
        copies=args.copies,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps({
            "ok": result.ok,
            "uploaded": result.uploaded,
            "code": result.code,
            "message": result.message,
            "file": result.file_name,
            "color": result.color,
            "paper": result.paper,
            "duplex": result.duplex,
            "page_from": result.page_from,
            "page_to": result.page_to,
            "copies": result.copies,
        }, ensure_ascii=False))
    else:
        print(result.to_markdown())
    return 0 if result.ok or args.dry_run else 1


# ── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.pms",
        description="SUSTech 联创 PMS — print, scan, history",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="verify auth").set_defaults(func=cmd_check)

    s_stations = sub.add_parser("stations", help="list campus printers")
    s_stations.add_argument("group", nargs="?", help="server group name/SN")
    s_stations.set_defaults(func=cmd_stations)

    sub.add_parser("groups", help="list server groups").set_defaults(func=cmd_groups)

    sub.add_parser("jobs", help="list uploaded print jobs").set_defaults(func=cmd_jobs)
    s_jd = sub.add_parser("job-delete", help="delete a print job")
    s_jd.add_argument("id", help="job ID")
    s_jd.set_defaults(func=cmd_job_delete)

    sub.add_parser("scans", help="list scanned documents").set_defaults(func=cmd_scans)
    s_sd = sub.add_parser("scan-delete", help="delete a scan")
    s_sd.add_argument("id", help="scan ID")
    s_sd.set_defaults(func=cmd_scan_delete)

    s_hist = sub.add_parser("history", help="usage records")
    s_hist.add_argument("--type", default="print", choices=["print", "scan", "copy"])
    s_hist.add_argument("--from", dest="begin", help="YYYY-MM-DD (default: 3y ago)")
    s_hist.add_argument("--to", dest="end", help="YYYY-MM-DD (default: today)")
    s_hist.add_argument("--page", type=int, default=1)
    s_hist.add_argument("--size", type=int, default=20)
    s_hist.set_defaults(func=cmd_history)

    s_up = sub.add_parser("upload", help="upload a file for printing")
    s_up.add_argument("file", help="path to file (PDF/doc/image)")
    s_up.add_argument("--color", default="bw", choices=["bw", "color"],
                      help="黑白 or 彩色 (default: bw)")
    s_up.add_argument("--paper", default="none",
                      choices=["A4", "A3", "none", "unspecified"],
                      help="纸型 (default: 不指定)")
    s_up.add_argument("--duplex", default="single",
                      choices=["single", "short", "long"],
                      help="单面 / 双面短边 / 双面长边 (default: single)")
    s_up.add_argument("--copies", type=int, default=1)
    s_up.add_argument("--from-page", type=int, default=None,
                      help="start page (1-indexed); omit for all pages")
    s_up.add_argument("--to-page", type=int, default=None,
                      help="end page (1-indexed); ignored when --from-page omitted")
    s_up.add_argument("--dry-run", action="store_true",
                      help="prepare form data without POSTing")
    s_up.set_defaults(func=cmd_upload)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Make --json propagate to subcommand namespace
    if not hasattr(args, "json"):
        args.json = False
    try:
        return args.func(args)
    except PMSError as e:
        # PMS API / server errors — render as a one-line message instead of
        # a Python traceback. The off-campus hint fires from here too.
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
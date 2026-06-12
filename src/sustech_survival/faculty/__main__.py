"""CLI: python -m sustech_survival.faculty <cmd> [args]

ONE client (`faculty`) — uses the same API as the Python module.

Commands:
  depts                          Print 50+ department names
  list    <dept> [--full]        List faculty in a dept
                                 (--full fetches all profiles, ~30-70s)
  get     <slug> [--json]        Fetch one profile
  search  <query> [--dept D]     Live keyword search
  render  <slug>                 AI-readable Markdown
"""
from __future__ import annotations

import argparse
import json

from . import faculty


def cmd_list(args):
    rows = faculty.list(args.dept, full=args.full, limit=args.limit)
    mode = "full profiles" if args.full else "lightweight"
    print(f"# {args.dept}  ({len(rows)} faculty — {mode})")
    print()
    for f in rows:
        title = f" [{f.title}]" if f.title else ""
        dept = f" — {f.department}" if f.department else ""
        print(f"- {f.name}{title}{dept}  /{f.slug}/")
    if args.full:
        for f in rows:
            if f.research_interests:
                print(f"  {f.name}: {', '.join(f.research_interests[:3])}")


def cmd_get(args):
    f = faculty.get(args.slug)
    if args.json:
        print(json.dumps(f.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f.to_markdown())


def cmd_search(args):
    hits = faculty.search(args.query, dept=args.dept, limit=args.limit)
    scope = args.dept or "ALL"
    print(f"# search: {args.query!r}  scope={scope}  → {len(hits)} hits")
    print()
    for f in hits:
        print(f"## {f.name}  (score={f.relevance_score}, matched={','.join(f.matched_fields)})")
        if f.title:
            print(f"  {f.title} — {f.department or '?'}")
        if f.email:
            print(f"  {f.email}")
        if f.research_interests:
            print(f"  Research: {', '.join(f.research_interests[:5])}")
        print(f"  Profile: {f.profile_url}")
        print()


def cmd_depts(args):
    print(f"# {len(faculty.departments)} known departments")
    for d in faculty.departments:
        print(f"  {d}")


def cmd_render(args):
    print(faculty.render(args.slug))


def main():
    p = argparse.ArgumentParser(prog="python -m sustech_survival.faculty",
                                description="Live SUSTech faculty directory query")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_depts = sub.add_parser("depts", help="List 50+ department names")
    p_depts.set_defaults(func=cmd_depts)

    p_list = sub.add_parser("list", help="List faculty in a department")
    p_list.add_argument("dept")
    p_list.add_argument("--full", action="store_true",
                       help="fetch all profiles (research interests, ~30-70s)")
    p_list.add_argument("--limit", type=int, default=None)
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="Fetch one profile by slug")
    p_get.add_argument("slug")
    p_get.add_argument("--json", action="store_true")
    p_get.set_defaults(func=cmd_get)

    p_search = sub.add_parser("search", help="Live keyword search (fetches profiles)")
    p_search.add_argument("query")
    p_search.add_argument("--dept", default=None, help="restrict to one department")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_render = sub.add_parser("render", help="AI-readable Markdown for one profile")
    p_render.add_argument("slug")
    p_render.set_defaults(func=cmd_render)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

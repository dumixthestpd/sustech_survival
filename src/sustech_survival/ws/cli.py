# ─────────────────────────────────────────────────────────────────────────────
# cli.py — WS Student Exchange CLI
# ─────────────────────────────────────────────────────────────────────────────
"""
WS CLI — SUSTech Student Exchange / Abroad Program Search

Commands:
    ws list          List programs (--page, --page-size, --year, --type, --grade)
    ws search <q>    Search programs by keyword
    ws show <id>     Show full detail for a program ID
    ws count         Total program count
"""
from __future__ import annotations

import json
import sys

import click

from .programs import get_count, get_program_detail, list_programs, search_programs


# ── Helpers ─────────────────────────────────────────────────────────────────

def print_program(p: dict) -> None:
    click.echo(f"  [{p.get('ID', '?')}] {p.get('Name', '?')}  ({p.get('YearCode', '?')})")
    if p.get("RegionName"):
        click.echo(f"         地区: {p['RegionName']}")
    if p.get("ProjectTypeText"):
        click.echo(f"         类型: {p['ProjectTypeText']}")
    if p.get("StudentExchangeProjectGradeIDText"):
        click.echo(f"         级别: {p['StudentExchangeProjectGradeIDText']}")
    if p.get("ApplyBeginDate") and p.get("ApplyEndDate"):
        click.echo(f"         申请: {p['ApplyBeginDate']} ~ {p['ApplyEndDate']}")
    if p.get("ApplyStudentCount") or p.get("LuQuStudentCount"):
        click.echo(
            f"         报名/录取: {p.get('ApplyStudentCount', '-')} / "
            f"{p.get('LuQuStudentCount', '-')}"
        )
    status = p.get("IsValidText") or ("有效" if p.get("IsValid") else "无效")
    click.echo(f"         状态: {status}")
    click.echo("")


def print_detail(d: dict) -> None:
    sections = d.get("sections", {})
    for sec, pairs in sections.items():
        click.secho(f"\n{'─' * 40}", fg="cyan")
        click.secho(f"  {sec}", fg="cyan", bold=True)
        for k, v in pairs.items():
            click.echo(f"  {k}: {v}")
    tables = d.get("tables", [])
    if tables:
        click.secho(f"\n{'─' * 40}", fg="cyan")
        click.secho("  附件", fg="cyan", bold=True)
        for tbl in tables:
            for row in tbl:
                click.echo("  " + " | ".join(str(c) for c in row))
    click.echo(f"\n  token: {d.get('token', '')}")


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
@click.pass_context
def cli(ctx):
    """WS CLI — SUSTech Student Exchange Program Search"""
    ctx.ensure_object(dict)


# ── list ────────────────────────────────────────────────────────────────────

@cli.command(name="list")
@click.option("-p", "--page", default=1, help="Page number")
@click.option("-n", "--page-size", default=10, help="Results per page")
@click.option("--year", "year_code", default=None, help="Year code (e.g. 2026)")
@click.option("--type", "project_type", default=None, type=int,
              help="Project type ID (1=短期, 2=长期)")
@click.option("--grade", "grade_id", default=None, type=int, help="Grade ID")
@click.option("--output", "output_fmt", default="text",
              type=click.Choice(["text", "json"]))
def list_cmd(page, page_size, year_code, project_type, grade_id, output_fmt):
    """List exchange programs with optional filters."""
    try:
        result = list_programs(
            page=page, page_size=page_size,
            year_code=year_code, project_type=project_type, grade_id=grade_id,
        )
    except Exception as e:
        click.secho(f"❌  Error: {e}", fg="red")
        sys.exit(1)

    if output_fmt == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    click.secho(f"\n📋  项目列表", fg="cyan", bold=True)
    click.secho(f"   第 {result['page']} 页 / 共 {result['record_count']} 个项目\n", fg="white")

    programs = result["programs"]
    if not programs:
        click.secho("   无结果", fg="yellow")
        return

    for p in programs:
        print_program(p)

    total = result["record_count"]
    per = result["page_size"]
    if total > per:
        pages = (total + per - 1) // per
        click.secho(f"  → 第 {page}/{pages} 页  |  ws list --page {page + 1}", fg="cyan")


# ── search ───────────────────────────────────────────────────────────────────

@cli.command(name="search")
@click.argument("query", default="")
@click.option("-p", "--page", default=1, help="Page number")
@click.option("-n", "--page-size", default=10, help="Results per page")
@click.option("--output", "output_fmt", default="text",
              type=click.Choice(["text", "json"]))
def search_cmd(query, page, page_size, output_fmt):
    """Search programs by keyword."""
    if not query:
        click.secho("❌  请提供搜索关键词: ws search 新加坡", fg="yellow")
        return
    try:
        result = search_programs(query, page=page, page_size=page_size)
    except Exception as e:
        click.secho(f"❌  Error: {e}", fg="red")
        sys.exit(1)

    if output_fmt == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    click.secho(f"\n🔍  搜索: '{query}' → {result['record_count']} 个结果",
                fg="cyan", bold=True)
    click.secho(f"   第 {result['page']} 页\n", fg="white")

    for p in result["programs"]:
        print_program(p)

    total = result["record_count"]
    per = result["page_size"]
    if total > per:
        pages = (total + per - 1) // per
        click.secho(
            f"  → 第 {page}/{pages} 页  |  ws search {query} --page {page + 1}",
            fg="cyan"
        )


# ── show ─────────────────────────────────────────────────────────────────────

@cli.command(name="show")
@click.argument("program_id", type=int)
@click.option("--code", default=None, help="Program code (auto-resolved if omitted)")
@click.option("--token", default=None, help="Token (auto-resolved if omitted)")
@click.option("--output", "output_fmt", default="text",
              type=click.Choice(["text", "json"]))
def show_cmd(program_id, code, token, output_fmt):
    """Show full detail for a program ID."""
    try:
        d = get_program_detail(program_id, code=code, token=token)
    except Exception as e:
        click.secho(f"❌  Error: {e}", fg="red")
        sys.exit(1)

    if output_fmt == "json":
        click.echo(json.dumps(d, ensure_ascii=False, indent=2))
        return

    if d is None:
        click.secho(f"❌  项目 {program_id} 不存在或无法访问", fg="red")
        sys.exit(1)

    print_detail(d)


# ── count ─────────────────────────────────────────────────────────────────────

@cli.command(name="count")
@click.option("--year", "year_code", default=None, help="Year code filter")
@click.option("--type", "project_type", default=None, type=int,
              help="Project type ID")
@click.option("--keywords", default=None, help="Keyword filter")
def count_cmd(year_code, project_type, keywords):
    """Show total program count matching filters."""
    try:
        total = get_count(
            year_code=year_code, project_type=project_type, keywords=keywords,
        )
    except Exception as e:
        click.secho(f"❌  Error: {e}", fg="red")
        sys.exit(1)
    click.secho(f"{total} 个项目", fg="cyan", bold=True)


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()

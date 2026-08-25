"""
sustech_survival.ws.cli — WS Student Exchange CLI.

Standalone ``sustech-ws`` / ``python -m sustech_survival.ws`` entry point for
the SUSTech 外事工作服务系统 (Student Exchange / Abroad Portal).

Mirrors the inline ``sustech ws`` subcommands from ``cli/main.py`` so that both
the unified dispatcher and the standalone entry point behave identically. All
logic lives in ``sustech_survival.ws.programs``.
"""
from __future__ import annotations

import json

import click

from sustech_survival.ws.programs import (
    get_count,
    get_program_detail,
    list_programs,
    search_programs,
)


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
    for sec, pairs in d.get("sections", {}).items():
        click.secho(f"\n  [{sec}]", fg="cyan", bold=True)
        for k, v in pairs.items():
            click.echo(f"    {k}: {v}")
    tables = d.get("tables", [])
    for tbl in tables:
        for row in tbl:
            click.echo("    " + " | ".join(str(c) for c in row))


@click.group(name="ws")
def cli() -> None:
    """SUSTech Student Exchange / Abroad programs (ws.sustech.edu.cn)."""


@cli.command(name="list", help="List exchange programs.")
@click.option("-p", "--page", default=1, show_default=True)
@click.option("-n", "--page-size", default=10, show_default=True)
@click.option("--year", "year_code", default=None, help="Year code, e.g. 2026")
@click.option("--type", "project_type", default=None, type=int,
              help="Project type ID (1=短期, 2=长期)")
@click.option("--grade", "grade_id", default=None, type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def list_cmd(page, page_size, year_code, project_type, grade_id, as_json) -> None:
    """List exchange programs with optional filters."""
    result = list_programs(
        page=page,
        page_size=page_size,
        year_code=year_code,
        project_type=project_type,
        grade_id=grade_id,
    )
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"\n📋 第 {result['page']} 页 / 共 {result['record_count']} 个项目")
    for p in result["programs"]:
        click.echo("")
        _ws_print_program(p)


@cli.command(name="search", help="Search programs by keyword.")
@click.argument("query")
@click.option("-p", "--page", default=1, show_default=True)
@click.option("-n", "--page-size", default=10, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def search_cmd(query, page, page_size, as_json) -> None:
    """Search programs by keyword."""
    result = search_programs(query, page=page, page_size=page_size)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"\n🔍 '{query}' → {result['record_count']} 个结果")
    for p in result["programs"]:
        click.echo("")
        _ws_print_program(p)


@cli.command(name="show", help="Show full detail for a program ID.")
@click.argument("program_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def show_cmd(program_id, as_json) -> None:
    """Show full detail for a program ID."""
    d = get_program_detail(program_id)
    if d is None:
        click.echo(f"❌ project {program_id} not found", err=True)
        raise SystemExit(1)
    if as_json:
        click.echo(json.dumps(d, ensure_ascii=False, indent=2))
        return
    _ws_print_detail(d)


@cli.command(name="count", help="Total program count (with optional filters).")
@click.option("--year", "year_code", default=None)
@click.option("--type", "project_type", default=None, type=int)
@click.option("--keywords", default=None)
def count_cmd(year_code, project_type, keywords) -> None:
    """Total program count (with optional filters)."""
    click.echo(f"{get_count(year_code=year_code, project_type=project_type, keywords=keywords)} 个项目")


if __name__ == "__main__":
    cli()

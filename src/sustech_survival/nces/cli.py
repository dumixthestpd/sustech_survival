"""sustech nces — NCES CLI subcommand.

Usage:
    sustech nces refresh [--sort rating|popular] [--max-pages N]
    sustech nces lookup <CODE>          # e.g. sustech nces lookup HUM032
    sustech nces status                 # cache freshness
    sustech nces clear                  # delete cache
"""
from __future__ import annotations

import click

from .scraper import NCESScraper


@click.group("nces")
def cli():
    """NCES — Niuwa Curriculum Evaluation System (community course eval)."""
    pass


@cli.command("refresh")
@click.option("--sort", default="rating",
              type=click.Choice(["rating", "popular"]),
              help="Listing sort order (default: rating)")
@click.option("--max-pages", default=6, type=int,
              help="Number of listing pages to fetch (each ~20 courses)")
@click.option("--no-cache", is_flag=True,
              help="Don't use existing cache; force refresh")
def refresh_cmd(sort: str, max_pages: int, no_cache: bool):
    """Refresh the NCES course index cache."""
    s = NCESScraper(use_cache=not no_cache)
    n = s.refresh_index(sort=sort, max_pages=max_pages, progress=True)
    click.echo(f"✓ cached {n} courses at {s.CACHE_FILE}")


@cli.command("lookup")
@click.argument("code")
def lookup_cmd(code: str):
    """Look up a course by TIS-style code (e.g. HUM032)."""
    s = NCESScraper()
    c = s.lookup(code)
    if c is None:
        raise click.ClickException(f"course not found: {code}")
    click.echo(f"{c.name} · {c.teacher}  [{c.code}]")
    click.echo(f"  semester:  {c.semester}")
    click.echo(f"  ★ {c.rating:.1f}/10  ({c.review_count} reviews)")
    click.echo(f"  Difficulty: {c.difficulty[0]:>10} ({c.difficulty[1]:.0f}%)")
    click.echo(f"  Workload:   {c.workload[0]:>10} ({c.workload[1]:.0f}%)")
    click.echo(f"  Grading:    {c.grading[0]:>10} ({c.grading[1]:.0f}%)")
    click.echo(f"  Takeaways:  {c.takeaways[0]:>10} ({c.takeaways[1]:.0f}%)")
    click.echo(f"  {c.direct_url}")


@cli.command("status")
def status_cmd():
    """Show cache freshness + count."""
    s = NCESScraper()
    st = s.status()
    if not st.get("cached"):
        click.echo("✗ no cache. Run: sustech nces refresh")
        return
    age = st.get("age_hours", 0)
    fresh = "fresh" if age < 24 else "stale"
    click.echo(
        f"{'✓' if fresh == 'fresh' else '⚠'} "
        f"{st['count']} courses · age {age:.1f}h · sort={st['sort']}"
    )
    click.echo(f"  cache: {st['path']}")


@cli.command("clear")
def clear_cmd():
    """Delete the NCES cache file."""
    s = NCESScraper()
    if s.clear_cache():
        click.echo("✓ cache cleared")
    else:
        click.echo("(no cache to clear)")
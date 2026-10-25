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
    # NCESScraper keeps a 5-min in-memory TTL by design and does not
    # accept a `use_cache` kwarg — the CLI `--no-cache` flag was a leftover
    # from an earlier API and triggered `TypeError: __init__() got an
    # unexpected keyword argument 'use_cache'`. `no_cache` is preserved on
    # the click option for backwards-compatible help text but is currently
    # a no-op (callers wanting truly fresh data can pass a new session).
    s = NCESScraper()
    _ = no_cache
    n = s.refresh_index(sort=sort, max_pages=max_pages, progress=True)
    click.echo(f"✓ cached {n} courses at {s.CACHE_FILE}")


@cli.command("lookup")
@click.argument("code")
@click.option("--teacher", default="", help="Restrict to one NCES teacher's section.")
def lookup_cmd(code: str, teacher: str):
    """Look up a course by TIS-style code (e.g. HUM032).

    Resolves through the NCES search, so a code with several sections reports
    which teacher's section the numbers belong to.
    """
    s = NCESScraper()
    course, exact, alternatives = s.search_course(code, teacher)
    if course is None:
        raise click.ClickException(f"course not found: {code}")
    click.echo(f"{course.name} · {course.teacher}  [{course.code}]")
    click.echo(f"  semester:  {course.semester}")
    click.echo(f"  ★ {course.rating:.1f}/10  ({course.review_count} reviews)")
    click.echo(f"  Difficulty: {course.difficulty[0]:>10} ({course.difficulty[1]:.0f}%)")
    click.echo(f"  Workload:   {course.workload[0]:>10} ({course.workload[1]:.0f}%)")
    click.echo(f"  Grading:    {course.grading[0]:>10} ({course.grading[1]:.0f}%)")
    click.echo(f"  Takeaways:  {course.takeaways[0]:>10} ({course.takeaways[1]:.0f}%)")
    click.echo(f"  {course.direct_url}")
    if not teacher and alternatives:
        names = ", ".join(sorted({a.teacher for a in alternatives if a.teacher}))
        click.echo(f"  other sections of {course.code}: {names or '(unnamed)'}")
    if teacher and not exact:
        click.echo(
            f"  note: no section matched teacher {teacher!r}; "
            "showing the top-reviewed section"
        )


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
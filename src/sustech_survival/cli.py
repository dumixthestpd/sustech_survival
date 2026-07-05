"""
sustech-survival unified CLI.

Single entry point for all submodules. Mirrors the ``git <subcmd>`` style:

    sustech bb courses              # Blackboard
    sustech tis grades              # TIS
    sustech ws list                 # Student exchange
    sustech context                 # What's happening now
    sustech webui serve             # Unified web UI
    sustech webui open              # Open UI in browser
    sustech --version

Each module's own Click commands are mounted under the matching subcommand,
so ``sustech bb session login`` is equivalent to ``bb session login``.
A submodule that fails to import (e.g. missing optional dep) shows as
``(unavailable: ...)`` in help text but doesn't crash the top-level CLI.
"""
from __future__ import annotations

import json as _json
import webbrowser
from typing import Optional

import click

from ._version import __version__


def _mount(module: str, target: click.Group) -> None:
    """Import ``<module>.cli:cli`` and copy its commands onto ``target``.

    On ImportError, sets ``target.help`` to the reason and returns.
    """
    try:
        mod = __import__(f"sustech_survival.{module}.cli", fromlist=["cli"])
        sub_cli: Optional[click.Command] = getattr(mod, "cli", None)
    except Exception as e:
        target.help = f"(unavailable: {e})"
        target.short_help = f"{module} (unavailable)"
        return
    if sub_cli is None:
        target.help = f"(unavailable: no `cli` symbol in sustech_survival.{module}.cli)"
        return
    if isinstance(sub_cli, click.Group):
        for name, cmd in sub_cli.commands.items():
            target.add_command(cmd, name=name)
    else:
        target.add_command(sub_cli, name="run")


def _mount_into(parent: click.Group, child_name: str, module: str) -> click.Group:
    """Create a child Click group under ``parent`` named ``child_name`` by
    importing ``<module>.cli:cli``. Returns the new (or existing) child group,
    which the caller can mount more sub-commands onto if needed.
    """
    child = click.Group(name=child_name)
    try:
        mod = __import__(f"sustech_survival.{module}.cli", fromlist=["cli"])
        sub_cli = getattr(mod, "cli", None)
    except Exception as e:
        child.help = f"(unavailable: {e})"
        child.short_help = f"{child_name} (unavailable)"
    else:
        if isinstance(sub_cli, click.Group):
            for name, cmd in sub_cli.commands.items():
                child.add_command(cmd, name=name)
        elif sub_cli is not None:
            child.add_command(sub_cli, name="run")
        else:
            child.help = f"(unavailable: no `cli` symbol in sustech_survival.{module}.cli)"
    parent.add_command(child)
    return child


# ── Module groups ────────────────────────────────────────────────────────

@click.group(name="bb")
def bb_cmd() -> None:
    """Blackboard — courses, assignments, submissions."""


@click.group(name="tis")
def tis_cmd() -> None:
    """TIS — Teaching Information System (courses, grades, evals)."""


@click.group(name="ws")
def ws_cmd() -> None:
    """WS — student exchange / abroad programs."""


@click.group(name="transit")
def transit_cmd() -> None:
    """Transit — live bus GPS + campus map data export."""


@click.group(name="webui")
def webui_cmd() -> None:
    """Unified Flask web UI (TIS + transit)."""


_mount("bb", bb_cmd)
_mount("tis", tis_cmd)
_mount("ws", ws_cmd)
_mount("transit", transit_cmd)


# Nested subcommands — modules that live under another module's namespace.
_mount_into(tis_cmd, "classroom", "tis.classroom")


# ── nces: community course evaluation ─────────────────────────────────────

@click.group(name="nces", help="NCES — community course eval (optional [nces] extra).")
def nces_cmd() -> None:
    pass


_mount("nces", nces_cmd)


# ── context: terse/normal/verbose snapshot ────────────────────────────────

@click.command(name="context")
@click.option(
    "--level", "-l",
    type=click.Choice(["terse", "normal", "verbose"]),
    default="terse",
    show_default=True,
    help="terse=date+time only · normal=+next deadline · verbose=+weather/library",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of text")
def context_cmd(level: str, as_json: bool) -> None:
    """What's happening right now — date, time, next deadline, etc."""
    from .context import Context
    ctx = Context()
    if as_json:
        click.echo(_json.dumps(ctx.to_dict(level=level), ensure_ascii=False, indent=2))
    else:
        click.echo(ctx.to_str(level=level))


# ── webui ────────────────────────────────────────────────────────────────

@webui_cmd.command(name="serve")
@click.option("--port", "-p", type=int, default=None,
              help="Port to listen on (default 61019)")
@click.option("--host", "-H", default="0.0.0.0", show_default=True,
              help="Interface to bind")
@click.option("--transit-data", "transit_data_dir", default=None,
              help="Directory of exported transit GeoJSON")
@click.option("--debug/--no-debug", default=False, help="Flask debug mode")
def webui_serve(port: Optional[int], host: str,
                transit_data_dir: Optional[str], debug: bool) -> None:
    """Start the unified web UI (TIS course selector + transit map)."""
    from .webui.app import run, DEFAULT_PORT
    run(host=host, port=port or DEFAULT_PORT,
        transit_data_dir=transit_data_dir, debug=debug)


@webui_cmd.command(name="open")
@click.option("--port", "-p", type=int, default=61019, show_default=True)
@click.option("--path", "-P", default="/", show_default=True)
def webui_open(port: int, path: str) -> None:
    """Open the running web UI in your default browser."""
    if not path.startswith("/"):
        path = "/" + path
    webbrowser.open(f"http://localhost:{port}{path}")


# ── Top-level group ──────────────────────────────────────────────────────

@click.group(
    name="sustech",
    help="sustech-survival unified CLI. Use `sustech <subcommand> --help` for details.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, "-V", "--version", prog_name="sustech")
def cli() -> None:
    """Top-level command group. Use `sustech <subcommand>` to dispatch."""


cli.add_command(bb_cmd)
cli.add_command(tis_cmd)
cli.add_command(ws_cmd)
cli.add_command(transit_cmd)
cli.add_command(context_cmd)
cli.add_command(webui_cmd)
cli.add_command(nces_cmd)


if __name__ == "__main__":
    cli()
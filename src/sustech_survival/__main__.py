"""``python -m sustech_survival`` — invoke the unified CLI dispatcher.

Mirrors the ``sustech`` console-script entry point defined in
``pyproject.toml``'s ``[project.scripts]``. The actual command tree lives
in ``sustech_survival.cli:cli`` (built by ``cli/main.py:build_cli()``),
which mounts every submodule as a subcommand — see ``sustech --help``.
"""
from sustech_survival.cli import cli

if __name__ == "__main__":
    cli()
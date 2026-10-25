"""Machine-readable output must stay machine-readable.

``sustech context --json`` used to print auth diagnostics on stdout before the
payload, so ``json.load`` failed on perfectly healthy output. Diagnostics are
narration and belong on stderr; this test runs the real CLI with no
credentials (the case where the narration fires) and parses stdout.
"""
from __future__ import annotations

import json

from click.testing import CliRunner

from sustech_survival.cli import cli as sustech_cli


def test_context_json_is_parseable_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("SUSTECH_HOME", str(tmp_path))
    monkeypatch.delenv("SUSTECH_CREDENTIALS", raising=False)

    result = CliRunner().invoke(sustech_cli, ["context", "--json"])

    payload = json.loads(result.stdout)  # fails if anything else is on stdout
    assert payload.get("date")


def test_auth_diagnostics_go_to_stderr(monkeypatch, tmp_path):
    monkeypatch.setenv("SUSTECH_HOME", str(tmp_path))
    monkeypatch.delenv("SUSTECH_CREDENTIALS", raising=False)

    result = CliRunner().invoke(sustech_cli, ["context", "--json"])

    stderr = getattr(result, "stderr", "") or ""
    assert "Auth refresh skipped" in stderr
    assert "Auth refresh skipped" not in result.stdout

"""
Tests for webui port-occupancy detection.

The dev server used to rely on the OS bind failure — a raw OSError
(WinError 10048 / EADDRINUSE) traceback — when the port was already taken
by another process (typically a second `sustech webui serve`). ``run()``
now probes the port first and fails with a clear message and exit code 1
without ever building or starting the app.

These tests only use sockets (no tmp_path / network), so they run anywhere.
"""
from __future__ import annotations

import socket

import pytest

from sustech_survival.webui.app import _port_in_use, _port_owner, run


@pytest.fixture()
def busy_port():
    """Bind and LISTEN on an ephemeral port; yield (port, socket)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    yield port, s
    s.close()


def test_port_in_use_when_bound(busy_port):
    port, _s = busy_port
    assert _port_in_use("127.0.0.1", port) is True


def test_port_free_after_release(busy_port):
    port, s = busy_port
    s.close()
    # The listener is gone; the port should probe free again.
    assert _port_in_use("127.0.0.1", port) is False


def test_run_fails_fast_on_busy_port(busy_port, monkeypatch):
    """run() must return 1 and never build the app when the port is taken."""
    port, _s = busy_port
    create_calls = []
    monkeypatch.setattr("sustech_survival.webui.app.create_app",
                        lambda *a, **k: create_calls.append(1) or object())
    rc = run(port=port, host="127.0.0.1")
    assert rc == 1
    assert create_calls == []          # fail fast — no create_app, no server


def test_run_serves_when_port_free(monkeypatch, busy_port):
    """With a free port, run() proceeds to create_app and serve.

    The real app.run would block forever, so stub it after create_app and
    assert run() reached the serving stage (and returned 0 on "exit")."""
    import sustech_survival.webui.app as wapp
    port, s = busy_port
    s.close()                          # free the port for the probe

    fake_app = type("FakeApp", (), {"config": {}, "run": lambda *a, **k: None})()
    monkeypatch.setattr(wapp, "create_app", lambda **k: fake_app)
    monkeypatch.setattr(wapp, "_port_in_use", lambda h, p: False)
    rc = run(port=port, host="127.0.0.1")
    assert rc == 0                     # served "forever", clean exit
    assert fake_app.config["PORT"] == port


def test_cli_serve_exits_1_on_busy_port(busy_port):
    from click.testing import CliRunner
    from sustech_survival.cli import cli
    port, _s = busy_port
    r = CliRunner().invoke(cli, ["webui", "serve", "--port", str(port),
                                 "--host", "127.0.0.1"])
    assert r.exit_code == 1
    assert "already in use" in r.output


def test_port_owner_never_raises():
    """_port_owner is best-effort: any lookup failure yields ''."""
    owner = _port_owner("127.0.0.1", 1)
    assert isinstance(owner, str)

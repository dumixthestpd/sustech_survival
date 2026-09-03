"""/api/tis/drop|add canonical response shape.

Regression: TIS write success returns a raw dict {jg:'1', message:'选课成功'}
with NO `ok` key — UI callers checking `r.ok` reported REAL successes as
failures ("drop succeeded but the UI said it did not"). The endpoint must
add `ok: true` on success (EnrollmentError already yields ok:false).
"""
from __future__ import annotations

import pytest

from sustech_survival.webui.app import create_app
import sustech_survival.selectcourse.api as scapi


class _FakeClient:
    """Write methods return TIS's raw success dict — no `ok` key."""

    def drop_course(self, rwh, *, dry_run=True, **kw):
        return {"jg": "1", "message": "退课成功", "rwh": rwh, "dry_run": dry_run}

    def add_course(self, rwh, *, dry_run=True, **kw):
        return {"jg": "1", "message": "选课成功", "rwh": rwh, "dry_run": dry_run}

    def add_to_cart(self, rwh, *, dry_run=True, **kw):
        return {"jg": "1", "message": "加入购物车成功", "rwh": rwh, "dry_run": dry_run}

    def remove_from_cart(self, rwh, *, dry_run=True, **kw):
        return {"jg": "1", "message": "移出购物车成功", "rwh": rwh, "dry_run": dry_run}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(scapi, "_client", lambda xn, xq: _FakeClient())
    return create_app().test_client()


def test_drop_success_carries_ok_true(client):
    r = client.post("/api/tis/drop?xn=2026-2027&xq=1", json={"rwh": "X", "dry_run": False})
    d = r.get_json()
    assert d["ok"] is True, f"successful drop must be ok:true, got {d}"
    assert d["jg"] == "1"


def test_add_success_carries_ok_true(client):
    r = client.post("/api/tis/add?xn=2026-2027&xq=1", json={"rwh": "X", "dry_run": False})
    d = r.get_json()
    assert d["ok"] is True
    assert d["message"] == "选课成功"


def test_dry_run_stays_not_ok(client):
    # dry_run never fires a request and must NOT claim success.
    r = client.post("/api/tis/drop?xn=2026-2027&xq=1", json={"rwh": "X", "dry_run": True})
    d = r.get_json()
    assert d.get("ok") is not True
    assert d.get("dry_run") is True

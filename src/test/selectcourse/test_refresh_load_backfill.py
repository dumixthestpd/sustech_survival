"""tis.refresh-load rwh backfill — picks outside the search page still get
live counts (one keyword=code personal search per missing code)."""
from __future__ import annotations

import pytest

from sustech_survival.selectcourse.course import Course
from sustech_survival.webui.app import create_app
import sustech_survival.selectcourse.api as scapi


def _course(rwh, code, enrolled=None, **kw):
    base = dict(code=code, name=code, name_en=code, class_group="", rwh=rwh,
                college="", category="", nature="", campus="", credits=1,
                total_hours=0, capacity=40, undergrad_seats=None,
                grad_seats=None, cultivation="1", rooms=[], teachers=["T"],
                slots_raw=[{"day": 1, "period_start": 1, "period_end": 1, "room": ""}],
                id=rwh)
    base.update(kw)
    if enrolled is not None:
        base["enrolled"] = enrolled
    return Course(**base)


class _RLClient:
    """Fake selectcourse client for refresh-load.

    The FIRST search_personal call (no keyword) is the "current filters"
    page and returns only RWH-A1 with a count. Keyword searches return the
    other sections (as TIS would for keyword=CODE).
    """

    def __init__(self):
        self.calls: list = []

    def list_courses(self):
        return [
            _course("RWH-A1", "AAA"), _course("RWH-A2", "AAA"),
            _course("RWH-B1", "BBB"), _course("RWH-C1", "CCC"),
        ]

    def search_personal(self, **kw):
        self.calls.append(kw.get("keyword", ""))
        keyword = kw.get("keyword", "")
        if keyword == "":
            return {"ok": True, "courses": [_course("RWH-A1", "AAA", enrolled=3)],
                    "round": {}}
        if keyword == "AAA":
            return {"ok": True,
                    "courses": [_course("RWH-A1", "AAA", enrolled=3),
                                _course("RWH-A2", "AAA", enrolled=5)],
                    "round": {}}
        if keyword == "BBB":
            return {"ok": True, "courses": [_course("RWH-B1", "BBB", enrolled=7)],
                    "round": {}}
        return {"ok": True, "courses": [], "round": {}}


@pytest.fixture()
def app():
    return create_app()


def test_refresh_load_backfills_requested_rwhs(app, monkeypatch):
    fake = _RLClient()
    monkeypatch.setattr(scapi, "_client", lambda xn, xq: fake)
    resp = app.test_client().post(
        "/api/tis/refresh-load?xn=2026-2027&xq=1&page_size=500"
        "&rwhs=RWH-A2,RWH-B1,RWH-A1", json={})
    d = resp.get_json()
    assert d["ok"] is True
    # A1 came from the filtered page; A2 + B1 from keyword backfills.
    assert d["loads"]["RWH-A1"] == 3
    assert d["loads"]["RWH-A2"] == 5
    assert d["loads"]["RWH-B1"] == 7
    # Backfill ran one search per missing CODE (AAA, BBB) — C1 never asked.
    assert "AAA" in fake.calls and "BBB" in fake.calls
    assert "CCC" not in fake.calls

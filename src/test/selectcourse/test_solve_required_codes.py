"""tis.solve `required_codes` (MUST-take courses) — constraint + feasibility.

Scenario geometry:
  AAA has sections at Mon P1 and Mon P2.
  BBB has ONE section spanning Mon P1–P2.
  → the BBB section overlaps BOTH AAA sections, so AAA and BBB are
    mutually exclusive (no AAA section can coexist with BBB).
  CCC is at Tue P1 — conflicts with nothing.

So: AAA+BBB can never coexist; AAA+CCC and BBB+CCC always can.
"""
from __future__ import annotations

import pytest

from sustech_survival.selectcourse.course import Course
from sustech_survival.webui.app import create_app
import sustech_survival.selectcourse.api as scapi


def _course(rwh, code, slots, **kw):
    base = dict(code=code, name=code, name_en=code, class_group="", rwh=rwh,
                college="", category="", nature="", campus="", credits=1,
                total_hours=0, capacity=40, undergrad_seats=None,
                grad_seats=None, cultivation="1", rooms=[], teachers=["T"],
                slots_raw=slots, id=rwh)
    base.update(kw)
    return Course(**base)


class _FakeClient:
    def __init__(self, courses):
        self._courses = courses

    def list_courses(self):
        return list(self._courses)


def _solve(client, body):
    return client.post("/api/tis/solve?xn=2026-2027&xq=1", json=body).get_json()


@pytest.fixture()
def app():
    return create_app()


def _patch_client(monkeypatch, courses):
    fake = _FakeClient(courses)
    monkeypatch.setattr(scapi, "_client", lambda xn, xq: fake)
    return fake


COURSES = [
    _course("RWH-A1", "AAA", [{"day": 1, "period_start": 1, "period_end": 1, "room": ""}]),
    _course("RWH-A2", "AAA", [{"day": 1, "period_start": 2, "period_end": 2, "room": ""}]),
    _course("RWH-B1", "BBB", [{"day": 1, "period_start": 1, "period_end": 2, "room": ""}]),
    _course("RWH-C1", "CCC", [{"day": 2, "period_start": 1, "period_end": 1, "room": ""}]),
]
RWHS = ["RWH-A1", "RWH-A2", "RWH-B1", "RWH-C1"]
CODES = ["AAA", "BBB", "CCC"]


def test_no_required_codes_unchanged(app, monkeypatch):
    _patch_client(monkeypatch, COURSES)
    d = _solve(app.test_client(), {
        "codes": CODES, "priority": CODES, "rwhs": RWHS,
        "blocked": [], "max": 30,
    })
    assert d["must_feasible"] is True      # nothing required
    assert d["must_impossible"] == []
    # AAA and BBB can't coexist → max coverage is 2 codes.
    assert max(s["covered"] for s in d["solutions"]) == 2


def test_mutually_exclusive_required_codes_infeasible(app, monkeypatch):
    _patch_client(monkeypatch, COURSES)
    d = _solve(app.test_client(), {
        "codes": CODES, "priority": CODES, "rwhs": RWHS,
        "blocked": [], "required_codes": ["AAA", "BBB"], "max": 30,
    })
    assert d["must_feasible"] is False     # the pair can't coexist
    # …but each code appears in SOME solution, so neither is "impossible".
    assert d["must_impossible"] == []
    for s in d["solutions"]:
        # every solution drops at least one of the two must codes (the
        # full set can never fit); tiers may drop one or both.
        assert s["must_dropped"], "must_dropped must be non-empty"
        assert set(s["must_dropped"]) <= {"AAA", "BBB"}
        assert s["must_total"] == 2
    # The best tier keeps one must code and covers CCC (never drops both).
    assert max(s["must_covered"] for s in d["solutions"]) == 1


def test_compatible_required_codes_feasible(app, monkeypatch):
    _patch_client(monkeypatch, COURSES)
    d = _solve(app.test_client(), {
        "codes": CODES, "priority": CODES, "rwhs": RWHS,
        "blocked": [], "required_codes": ["AAA", "CCC"], "max": 30,
    })
    assert d["must_feasible"] is True
    # Full must-set solutions exist and are ranked FIRST (before any
    # partial tier that drops a required code).
    first = d["solutions"][0]
    assert first["must_dropped"] == []
    assert first["must_covered"] == 2 and first["must_total"] == 2
    assert "AAA" in {x["code"] for x in first["sections"]}
    assert "CCC" in {x["code"] for x in first["sections"]}
    assert any(not s["must_dropped"] for s in d["solutions"])


def test_required_code_without_picked_section_still_solvable(app, monkeypatch):
    # MUST means MUST: a required code is solved from the FULL catalog —
    # even if the user hasn't picked any section of it yet.
    _patch_client(monkeypatch, COURSES)
    d = _solve(app.test_client(), {
        "codes": ["BBB", "CCC"], "priority": ["BBB", "CCC"],
        "rwhs": ["RWH-B1", "RWH-C1"],
        "blocked": [], "required_codes": ["AAA"], "max": 30,
    })
    assert d["must_feasible"] is True
    first = d["solutions"][0]
    assert first["must_dropped"] == []
    assert any(s["code"] == "AAA" for s in first["sections"])


def test_required_code_uses_any_teacher_section(app, monkeypatch):
    # MUST means MUST "no matter the teacher": AAA is only PICKED at
    # Mon P1 (RWH-A1) which conflicts with the must BBB at Mon P1 — but
    # AAA ALSO has an UNPICKED section at Tue P1 (RWH-A2) that fits.
    # The solver must use RWH-A2 to satisfy the MUST, not report
    # infeasible because the picked section happens to clash.
    a1 = _course("RWH-A1", "AAA", [{"day": 1, "period_start": 1, "period_end": 1, "room": ""}])
    a2 = _course("RWH-A2", "AAA", [{"day": 2, "period_start": 1, "period_end": 1, "room": ""}])
    b1 = _course("RWH-B1", "BBB", [{"day": 1, "period_start": 1, "period_end": 1, "room": ""}])
    _patch_client(monkeypatch, [a1, a2, b1])
    d = _solve(app.test_client(), {
        "codes": ["AAA", "BBB"], "priority": ["AAA", "BBB"],
        "rwhs": ["RWH-A1", "RWH-B1"],   # RWH-A2 is NOT picked
        "blocked": [], "required_codes": ["AAA", "BBB"], "max": 30,
    })
    assert d["must_feasible"] is True
    assert d["must_impossible"] == []
    first = d["solutions"][0]
    assert first["must_dropped"] == []
    # The solver reached into the catalog and used the UNPICKED section.
    assert any(s["rwh"] == "RWH-A2" for s in first["sections"])


def test_feasible_must_hides_partial_tiers(app, monkeypatch):
    # When the full must-set fits, solutions that drop a required code
    # (partial tiers) must NOT appear — MUST means MUST.
    _patch_client(monkeypatch, COURSES)
    d = _solve(app.test_client(), {
        "codes": CODES, "priority": CODES, "rwhs": RWHS,
        "blocked": [], "required_codes": ["AAA", "CCC"], "max": 30,
    })
    assert d["must_feasible"] is True
    assert d["solutions"], "expected at least one solution"
    for s in d["solutions"]:
        assert s["must_dropped"] == [], "partial tier leaked into feasible results"

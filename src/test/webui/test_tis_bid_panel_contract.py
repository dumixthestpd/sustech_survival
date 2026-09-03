"""
Contract tests for the default skin's TIS bid panel visibility.

Regression (2026-09-02): applying a saved candidate (or picking from the
campus catalog) while TIS wasn't answering the query left step 5 blank —
the bid panel never appeared. Root cause: ``bidShouldShow()`` gated the
panel on ``MODE === 'personal'``, but picks exist in both modes and the
candidate-apply flow is mode-independent. The fix dropped that gate (the
panel now renders whenever PICKED / locked-enrolled has content) and made
the budget header honest when no live round data was ever fetched
(``ROUND_INFO.ok`` still false — TIS down) instead of printing a fake
"0 pts free".

These tests read the JS the skin actually serves (same file the browser
executes) and pin that contract down: no mode gate in bidShouldShow, no
leftover OFFLINE_REVIEW artifacts, and the no-live-round header exists.
"""
from __future__ import annotations

import re

from sustech_survival.webui.app import create_app


def _skin_js() -> str:
    app = create_app(skin="default")
    r = app.test_client().get("/static/tis/tis.js")
    assert r.status_code == 200
    return r.data.decode("utf-8", "replace")


def _skin_tis_page() -> str:
    """The /tis page shell — where step-5's terminal actions live."""
    app = create_app(skin="default")
    r = app.test_client().get("/tis")
    assert r.status_code == 200
    return r.data.decode("utf-8", "replace")


def _extract_function(js: str, name: str) -> str:
    """Return the source of ``function <name>() { ... }`` (top-level
    brace balance). Returns '' when the function is missing."""
    m = re.search(r"\bfunction %s\(\)\s*\{" % re.escape(name), js)
    if not m:
        return ""
    start = m.end() - 1  # the '{'
    depth = 0
    i = start
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[m.start():i + 1]
        i += 1
    return ""


def test_bid_panel_no_offline_review_artifacts():
    """The rejected '🧪 Offline bid review' experiment left no trace in
    the served JS — no flag, no button label."""
    js = _skin_js()
    assert "OFFLINE_REVIEW" not in js
    assert "Offline bid review" not in js


def test_bid_panel_visible_in_any_mode_with_picks():
    """bidShouldShow() must not consult MODE: the bid panel reflects
    PICKED / locked-enrolled content, which exists in both the personal
    and the campus (catalog) search modes. A saved candidate applied
    while browsing the catalog must bring step 5 back."""
    fn = _extract_function(_skin_js(), "bidShouldShow")
    assert fn, "bidShouldShow() missing from the served skin JS"
    assert "MODE" not in fn, (
        "bidShouldShow() still gates on MODE — the bid panel can't "
        "appear when a candidate is applied in catalog mode"
    )
    assert "Object.keys(PICKED).length" in fn
    assert "ENROLLED_RWH.size" in fn


def test_bid_panel_header_honest_without_live_round():
    """When ROUND_INFO was never populated (TIS down / no successful
    personal search), the header must say the budget is unknown — not
    claim a fake '0 pts free / 0 total'."""
    js = _skin_js()
    assert "no live round data" in js
    # The live-round test drives both the panel render and the live
    # edit-total/stat refresh paths.
    assert "liveRound" in js


def test_bid_panel_render_clears_when_no_content():
    """The early-out branch still exists: with zero picks and no
    locked-enrolled rows the panel stays cleared (mode-independent)."""
    fn = _extract_function(_skin_js(), "renderBidPanel")
    assert fn
    assert "bidShouldShow()" in fn


# -- Apply-schedule button placement (step 5, not the right bar) -------------
# User request (2026-09-02): the enroll-commit button ("Apply schedule to
# TIS" / "Overwrite TIS courses with schedule") must NOT sit beside the
# destructive Drop-all in the right bar — it belongs in step-5's terminal
# actions row next to Sync to TIS.

def test_apply_tis_button_lives_in_step5_terminal_row():
    """The served /tis shell must contain exactly one #btn-apply-tis, and
    it must be inside the step-5 terminal-actions row."""
    page = _skin_tis_page()
    assert page.count('id="btn-apply-tis"') == 1
    # Anchor on the actual button markup (the CSS earlier in <style> also
    # mentions step-terminal-row, so anchor on Export ICS and look back).
    ics_pos = page.index('id="btn-export-ics"')
    region = page[ics_pos - 400:ics_pos + 200]
    assert 'id="btn-apply-tis"' in region
    assert 'id="btn-sync-tis"' in region


def test_apply_tis_button_not_in_right_bar_drop_wrapper():
    """The button element is no longer authored in JS (right-bar drop
    wrapper). It must only exist in the static /tis HTML; the JS keeps
    references via getElementById (which has no 'id=\"' attribute
    template), and wires it in the step-5 terminal block."""
    js = _skin_js()
    # No HTML-template occurrence of the button anywhere in the JS.
    assert 'id="btn-apply-tis"' not in js
    # The right-bar drop wrapper only carries the destructive Drop-all.
    fn = _extract_function(js, "initPickedActions")
    assert fn
    drop_decl = fn.find("btn-drop-all")
    assert drop_decl != -1
    wrapper_region = fn[:fn.find("// Wire the toggle")]
    assert "btn-drop-all" in wrapper_region
    # Wiring lives in the DOMContentLoaded step-5 terminal block.
    assert "btnApplyTis" in js
    assert "applyScheduleToTIS" in js

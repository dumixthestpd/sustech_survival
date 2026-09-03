"""Tests for the NCES batch mini-ratings path (eager card badges).

Covers the scraper's ``mini_ratings`` (teacher-team matching, dedupe by
code, per-code search cache, brief-cache precedence, upstream failure
handling, key format) and the Flask-free ``api.nces.ratings`` delegation.
"""
from __future__ import annotations

import time

import pytest

from sustech_survival.nces import NCESScraper
from sustech_survival.nces.scraper import NCESCourse  # noqa: F401  (sanity import)
from sustech_survival.api import nces as api_nces


def _item(id_, teacher_names, rate, reviews, term_ids=None, code="BIO103"):
    return {
        "id": id_,
        "course_code": code,
        "name": "Principles of Biology",
        "teacher_names": teacher_names,
        "rate_average": rate,
        "review_count": reviews,
        "term_ids": term_ids or ["20251"],
        "difficulty_score": 40,
        "homework_score": 50,
        "grading_score": 60,
        "gain_score": 70,
    }


class StubScraper(NCESScraper):
    """NCESScraper with _api_search stubbed to a canned per-code table."""

    def __init__(self, table, errors=()):
        super().__init__()
        self.table = table          # code (upper) -> items list
        self.errors = set(errors)   # codes that raise (transient upstream)
        self.search_calls = []

    def _api_search(self, code):
        self.search_calls.append(code)
        if code in self.errors or code.upper() in self.errors:
            raise RuntimeError("upstream down")
        return {"courses": {"items": list(self.table.get(code.upper(), []))}}


# ── scraper.mini_ratings ────────────────────────────────────────────────────

def test_exact_teacher_team_match():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5),
                                _item(2, "王晓晨,温子龙", 9.5, 12)]})
    out = s.mini_ratings([{"code": "BIO103", "teacher": "王晓晨,温子龙"}])
    r = out["results"]["BIO103::王晓晨,温子龙"]
    assert r["available"] is True
    assert r["rating"] == 9.5
    assert r["review_count"] == 12
    assert r["nces_id"] == 2
    assert r["teacher_mismatch"] is False


def test_partial_teacher_overlap_is_mismatch_not_misattribution():
    # TIS card has 4 teachers; NCES section has only one of them → the
    # mini badge must NOT show that section's rating.
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5)]})
    out = s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎,王晓晨,温子龙,吴柘"}])
    r = out["results"]["BIO103::鲍志戎,王晓晨,温子龙,吴柘"]
    assert r["available"] is False
    assert r["teacher_mismatch"] is True


def test_no_teacher_given_uses_top_section():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5),
                                _item(2, "王晓晨", 9.5, 12)]})
    out = s.mini_ratings([{"code": "BIO103", "teacher": ""}])
    r = out["results"]["BIO103::"]
    assert r["available"] is True
    assert r["rating"] == 8.1  # first item, same convention as search_course


def test_not_found_code():
    s = StubScraper({})
    out = s.mini_ratings([{"code": "MSE999", "teacher": "张三"}])
    r = out["results"]["MSE999::张三"]
    assert r["available"] is False
    assert r["teacher_mismatch"] is False
    assert "not found" in r["reason"]


def test_one_search_per_unique_code_and_key_format():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5)]})
    out = s.mini_ratings([
        {"code": "BIO103", "teacher": "鲍志戎"},
        {"code": "BIO103", "teacher": "鲍志戎"},   # dup key — collapsed
        {"code": "bio103", "teacher": "李四"},     # different key, same code
    ])
    assert len(s.search_calls) == 1
    assert set(out["results"].keys()) == {"BIO103::鲍志戎", "bio103::李四"}


def test_per_code_search_cache_within_ttl():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5)]})
    s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎"}])
    s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎"}])
    assert len(s.search_calls) == 1


def test_brief_cache_precedence_skips_search():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5)]})
    # Seed a cached full brief for the exact (code, teacher, xn, xq).
    s._brief_cache[("BIO103", "鲍志戎", "", "")] = (
        time.time(),
        {"available": True, "rating": 7.7, "review_count": 3, "nces_id": 42,
         "teacher_mismatch": False},
    )
    out = s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎"}])
    assert s.search_calls == []  # served entirely from the brief cache
    r = out["results"]["BIO103::鲍志戎"]
    assert r["rating"] == 7.7 and r["nces_id"] == 42


def test_upstream_failure_is_not_negative_cached():
    s = StubScraper({"BIO103": [_item(1, "鲍志戎", 8.1, 5)]}, errors={"BIO103"})
    out1 = s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎"}])
    assert out1["results"]["BIO103::鲍志戎"]["available"] is False
    assert "unavailable" in out1["results"]["BIO103::鲍志戎"]["reason"]
    # Transient error cleared → next call retries the search and succeeds.
    s.errors.clear()
    out2 = s.mini_ratings([{"code": "BIO103", "teacher": "鲍志戎"}])
    assert out2["results"]["BIO103::鲍志戎"]["available"] is True


def test_bad_items_are_skipped():
    s = StubScraper({})
    out = s.mini_ratings([None, {}, {"code": ""}, {"code": "  "},
                          {"code": "BIO103"}])
    assert set(out["results"].keys()) == {"BIO103::"}
    assert out["ok"] is True


def test_term_preference_picks_current_term_section():
    s = StubScraper({"CS201": [
        _item(1, "张三", 6.0, 9, term_ids=["20241"]),
        _item(2, "张三", 7.0, 2, term_ids=["20261"]),
    ]})
    out = s.mini_ratings([{"code": "CS201", "teacher": "张三"}],
                         xn="2026-2027", xq="1")
    r = out["results"]["CS201::张三"]
    # Both sections match the team; the current-term one wins even though
    # it has fewer reviews.
    assert r["nces_id"] == 2


# ── Flask-free api layer delegation ─────────────────────────────────────────

def test_api_ratings_delegates_to_scraper(monkeypatch):
    class Fake:
        def mini_ratings(self, items, *, xn="", xq=""):
            self.seen = (items, xn, xq)
            return {"ok": True, "count": 1, "codes_searched": 0,
                    "results": {"BIO103::鲍志戎": {"available": True,
                                                   "rating": 9.0,
                                                   "review_count": 2,
                                                   "nces_id": 5,
                                                   "code": "BIO103",
                                                   "teacher_mismatch": False}}}

    fake = Fake()
    monkeypatch.setattr(api_nces, "_scraper", fake)
    out = api_nces.ratings([{"code": "BIO103", "teacher": "鲍志戎"}],
                           xn="2026-2027", xq="1")
    assert out["results"]["BIO103::鲍志戎"]["rating"] == 9.0
    assert fake.seen == ([{"code": "BIO103", "teacher": "鲍志戎"}], "2026-2027", "1")
    assert callable(api_nces.ratings)

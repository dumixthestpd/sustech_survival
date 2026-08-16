"""
sustech_survival.selectcourse.writes — Course add/drop/update_bid methods.

Split from `selectcourse.py` (2026-08-08) so the read-side client stays
narrow. These methods mutate enrollment on TIS — every one defaults to
`dry_run=True` and prints the payload that WOULD be POSTed. The user
must explicitly set `dry_run=False` to fire a real write.

The 5 public methods:
  add_course(rwh)         — Xsxk/addXuanke       (direct enroll)
  drop_course(rwh)        — Xsxk/tuike           (drop)
  add_to_cart(rwh)        — Xsxk/addGouwuche     (add to cart)
  remove_from_cart(rwh)   — Xsxk/delGouwuche     (remove from cart)
  update_bid(rwh, bid)    — Xsxk/updXkxsByyx|gwc (set bid on existing pick)
  submit_bids(picks)      — bulk wrapper around update_bid

Discovery doc: references/tis-api.md
"""
from __future__ import annotations

from typing import Optional

from .endpoints import (
    TIS_ADD_XUANKE_URL, TIS_TUIKE_URL, TIS_ADD_GOUWUCHE_URL, TIS_DEL_GOUWUCHE_URL,
    TIS_UPD_XKXS_BY_YX, TIS_UPD_XKXS_BY_GWC,
    XKTJZ_CART_TO_ENROLLED, XKTJZ_TASK_TO_ENROLLED,
)
from .errors import EnrollmentError
from .queryform import build_queryform
from sustech_survival.consequence import (
    Severity, Consequence, consequence_rich,
)


# -- POST helper --------------------------------------------------------

def _post_xsxk(self, endpoint: str, payload: dict, *,
               dry_run: bool, rwh: str) -> dict:
    """POST to a write-side Xsxk/* endpoint.

    With `dry_run=True`, returns a synthetic "would-post" response
    without sending anything. With `dry_run=False`, logs in via TIS
    and fires the real POST.

    Response shape: `{jg: '1'|'0'|'-1', message: '...', ...}`
    Raises EnrollmentError when jg != '1'.
    """
    if dry_run:
        return {
            "dry_run": True,
            "endpoint": endpoint,
            "would_post": payload,
            "jg": None, "message": "(dry_run: no request sent)",
        }

    self._auth.ensure()
    r = self._auth.post(endpoint, data=payload, timeout=30,
                        headers={"X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    res = r.json() if r.content else {}
    jg = str(res.get("jg", ""))
    if jg != "1":
        raise EnrollmentError(jg, res.get("message", "(no message)"),
                              endpoint=endpoint, rwh=rwh)
    return res


def _build(self, **kw) -> dict:
    """Shorthand for build_queryform bound to this client.

    Defaults:
    - `xkfsdm="yixuan"` (已选) — matches HAR for updXkxsByyx/tuike.
    - `xktjz="rwtjzyx"` (任务提交至已选) — HAR shows this for ALL write
      endpoints (addGouwuche/updXkxsByyx/tuike). If omitted, TIS
      rejects with 操作失败 because the field is required.
    Callers needing other values (e.g. "bxxk" for addGouwuche cart add,
    "gwctjzyx" for addXuanke cart-final) should pass them explicitly.
    """
    kw.setdefault("xkfsdm", "yixuan")
    kw.setdefault("xktjz", XKTJZ_TASK_TO_ENROLLED)
    return build_queryform(sem=self._sem, auth=self._auth, **kw)


# -- Single-pick writes --------------------------------------------------

@consequence_rich(Consequence(
    name="selectcourse.add_course",
    severity=Severity.MEDIUM,
    irreversible=False,
    what_changes="Enrolls this course section on TIS.",
    risk="Consumes selection/bid slots; verify the section is the one you want.",
    verify_url="https://tis.sustech.edu.cn/#/xsxk?rwh={rwh}",
))
def add_course(self, rwh: str, *,
               bid: int = 1,
               dry_run: bool = True,
               ignore_conflicts: bool = False,
               ignore_zero_capacity: bool = False,
               pylx: Optional[str] = None,
               id_field: Optional[str] = None,
               xkfsdm: Optional[str] = None) -> dict:
    """Add a course to your enrolled list (直接选课).

    `rwh`: the 任务号 (task number) from `Course.rwh` or `my_courses()`.
           Used as a key to look up the hex `id_field` if not given.
    `id_field`: 32-char hex UUID from `queryKxrw` row.id — the actual
           TIS write-key. If omitted, the client looks it up in its
           cached catalog (requires a prior personal-mode search to
           have populated `Course.id` for that rwh).
    `xkfsdm`: round code (HAR shows "yixuan" for enrolled-list ops).
           Defaults to "yixuan" via _build.

    `bid`: 选课系数 (the credit bid in 积分选课). 1 = minimum.

    `dry_run=True` (default): returns what would be POSTed without
                              firing the request. SAFE.
    `dry_run=False`: actually fires `Xsxk/addXuanke`. This MUTATES
                     your enrollment — use only after reviewing.

    Returns the TIS response dict. On dry_run, includes `dry_run=True`
    and `would_post=<full payload>`. On real call, includes `jg='1'`
    and `message='选课成功'` (or similar) on success.

    Raises EnrollmentError on real-call failure (jg != '1').
    Raises ValueError if id_field is missing AND can't be looked up
    from the catalog.
    """
    if id_field is None:
        id_field = self._lookup_id(rwh)
    payload = _build(self,
                     id_field=id_field,
                     xktjz=XKTJZ_CART_TO_ENROLLED,
                     pylx=pylx,
                     ignore_conflicts=ignore_conflicts,
                     ignore_zero_capacity=ignore_zero_capacity,
                     bid=bid,
                     xkfsdm=xkfsdm,
                     )
    return _post_xsxk(self, TIS_ADD_XUANKE_URL, payload,
                       dry_run=dry_run, rwh=rwh)


@consequence_rich(Consequence(
    name="selectcourse.drop_course",
    severity=Severity.HIGH,
    irreversible=True,
    what_changes="Drops this course section from your TIS enrollment.",
    risk=("If the course is popular, your slot can be taken by a "
          "vacancy-watcher and you may not get it back."),
    verify_url="https://tis.sustech.edu.cn/#/xsxk?rwh={rwh}",
))
def drop_course(self, rwh: str, *, dry_run: bool = True,
                pylx: Optional[str] = None,
                id_field: Optional[str] = None,
                xkfsdm: Optional[str] = None) -> dict:
    """Drop a course (退课) by 任务号.

    Same `dry_run` semantics as `add_course`. Fires `Xsxk/tuike`.
    `xkfsdm` defaults to "yixuan" (matches HAR).
    """
    if id_field is None:
        id_field = self._lookup_id(rwh)
    payload = _build(self, id_field=id_field, pylx=pylx, xkfsdm=xkfsdm)
    return _post_xsxk(self, TIS_TUIKE_URL, payload,
                       dry_run=dry_run, rwh=rwh)


@consequence_rich(Consequence(
    name="selectcourse.add_to_cart",
    severity=Severity.LOW,
    irreversible=False,
    what_changes="Adds this course to your TIS shopping cart (not enrolled).",
    verify_url="https://tis.sustech.edu.cn/#/xsxk?rwh={rwh}",
))
def add_to_cart(self, rwh: str, *, bid: int = 1,
                dry_run: bool = True,
                pylx: Optional[str] = None,
                id_field: Optional[str] = None,
                xkfsdm: Optional[str] = "bxxk") -> dict:
    """Add a course to your shopping cart (购物车).

    `xkfsdm` defaults to "bxxk" (通识必修选课) — matches HAR for
    `addGouwuche`. Set to "yixuan" to commit the cart in one step.

    Fires `Xsxk/addGouwuche`.
    """
    if id_field is None:
        id_field = self._lookup_id(rwh)
    payload = _build(self, id_field=id_field, pylx=pylx, bid=bid,
                     xkfsdm=xkfsdm)
    return _post_xsxk(self, TIS_ADD_GOUWUCHE_URL, payload,
                       dry_run=dry_run, rwh=rwh)


@consequence_rich(Consequence(
    name="selectcourse.remove_from_cart",
    severity=Severity.LOW,
    irreversible=False,
    what_changes="Removes this course from your TIS shopping cart.",
    verify_url="https://tis.sustech.edu.cn/#/xsxk?rwh={rwh}",
))
def remove_from_cart(self, rwh: str, *, dry_run: bool = True,
                     pylx: Optional[str] = None,
                     id_field: Optional[str] = None,
                     xkfsdm: Optional[str] = "yixuan") -> dict:
    """Remove a course from your shopping cart.

    Fires `Xsxk/delGouwuche`.
    """
    if id_field is None:
        id_field = self._lookup_id(rwh)
    payload = _build(self, id_field=id_field, pylx=pylx, xkfsdm=xkfsdm)
    return _post_xsxk(self, TIS_DEL_GOUWUCHE_URL, payload,
                       dry_run=dry_run, rwh=rwh)


# -- Bid (积分 / 选课系数) ----------------------------------------------

def update_bid(self, rwh: str, bid: int, *,
               where: str = "enrolled",
               pylx: Optional[str] = None,
               dry_run: bool = True,
               id_field: Optional[str] = None,
               xkfsdm: Optional[str] = None) -> dict:
    """Update the bid (选课系数) on an already-picked course.

    `where`: "enrolled" (已选 → calls Xsxk/updXkxsByyx)
             or  "cart"    (购物车 → calls Xsxk/upd_xkxsBygwc)
    `xkfsdm`: round code. HAR shows "yixuan" for both updXkxsByyx and
             upd_xkxsBygwc — default to "yixuan" if None.
    `bid`: positive integer. TIS rejects if the round uses 积分
           mode and bid is missing / 0 / non-integer.
    `id_field`: hex UUID for `p_id`. If omitted, looked up from catalog.

    For NEW picks (not yet in cart/enrolled), use `add_to_cart(bid=…)`
    or `add_course(bid=…)` instead — they pass the bid on the create.
    """
    bid = int(bid)
    if bid < 1:
        raise ValueError(f"bid must be a positive integer, got {bid}")
    if where == "enrolled":
        url = TIS_UPD_XKXS_BY_YX
    elif where == "cart":
        url = TIS_UPD_XKXS_BY_GWC
    else:
        raise ValueError(f"where must be 'enrolled' or 'cart', got {where!r}")
    if id_field is None:
        id_field = self._lookup_id(rwh)
    payload = _build(self, id_field=id_field, pylx=pylx, bid=bid, xkfsdm=xkfsdm)
    return _post_xsxk(self, url, payload, dry_run=dry_run, rwh=rwh)


@consequence_rich(Consequence(
    name="selectcourse.submit_bids",
    severity=Severity.HIGH,
    irreversible=True,
    what_changes="Commits your bid values for multiple courses (积分选课).",
    risk=("Bid window may not reopen; a wrong bid is hard to undo. "
          "Review the per-course preview before committing."),
    verify_url="https://tis.sustech.edu.cn/#/xsxk",
))
def submit_bids(self, picks: dict, *,
                round_code: str = "",
                where: str = "cart",
                jffs_limit: Optional[float] = None,
                pylx: Optional[str] = None,
                dry_run: bool = True,
                id_map: Optional[dict] = None,
                xkfsdm: Optional[str] = None) -> dict:
    """Submit a batch of bid values for the user's picked courses.

    `picks`:  {rwh: bid_int, ...} — the user's desired bid per course.
    `round_code`: the active round code. Used as the default xkfsdm if
                  `xkfsdm` not given (HAR shows both updXkxsByyx and
                  upd_xkxsBygwc use "yixuan" for the enrolled-cart round).
    `where`:  "enrolled" (call updXkxsByyx) or "cart" (call
              upd_xkxsBygwc) — same as `update_bid`.
    `jffs_limit`: if provided, validate that `sum(picks.values())`
                  does not exceed it (the 剩余积分 from the round).
                  If sum > jffs_limit, return ok=False without any
                  TIS calls.
    `id_map`: optional {rwh: id_hex} pre-populated by caller (e.g. from
              a prior personal search). If omitted, each rwh is
              looked up in the catalog; missing entries cause the
              per-pick result to be ok=False with a clear message
              rather than failing silently.

    Returns a dict:
      {
        "ok": True/False,
        "results": [{rwh, bid, ok, message}, ...],
        "sum": N,
        "jffs_limit": X or None,
        "over_limit": True/False,
        "round_code": str,
      }

    Each TIS call still respects `dry_run` — the loop is read+write
    either way; `dry_run` only controls whether the actual POST
    fires. Validation (jffs check) always runs.

    If `sum(picks.values()) > jffs_limit`, the function short-circuits
    BEFORE making any TIS calls (including dry-run). The result
    includes the picks you asked for so the caller can show them
    back to the user.
    """
    # If xkfsdm wasn't given explicitly, default to round_code. HAR
    # shows both upd endpoints use "yixuan" so if the user passes an
    # unrelated round_code (e.g. "kzyxk") as default we'd silently
    # use the wrong xkfsdm. Prefer the explicit param; fall back to
    # round_code; final fallback "yixuan".
    if xkfsdm is None:
        xkfsdm = round_code or "yixuan"

    results: list = []

    # Pre-compute the total. If it would blow the budget, return
    # WITHOUT firing any TIS calls (including dry-run). Build a
    # synthetic per-pick result so the caller can render what was
    # rejected.
    try:
        coerced = {rwh: int(b) for rwh, b in picks.items()}
    except (TypeError, ValueError):
        return {
            "ok": False, "results": [],
            "error": "all bid values must be integers",
            "sum": 0, "jffs_limit": jffs_limit, "over_limit": False,
            "round_code": round_code, "dry_run": dry_run,
        }
    total = sum(max(0, b) for b in coerced.values())
    if jffs_limit is not None and total > jffs_limit:
        results = [{"rwh": rwh, "bid": b, "ok": False,
                    "message": f"over budget ({total} > {jffs_limit})",
                    "dry_run": dry_run}
                   for rwh, b in coerced.items() if b >= 1]
        return {
            "ok": False,
            "results": results,
            "sum": total,
            "jffs_limit": jffs_limit,
            "over_limit": True,
            "round_code": round_code,
            "dry_run": dry_run,
        }

    for rwh, bid in coerced.items():
        if bid < 1:
            results.append({"rwh": rwh, "bid": bid, "ok": False,
                            "message": "bid must be ≥ 1",
                            "dry_run": dry_run})
            continue
        # Use pre-populated id_map if provided; else look up.
        id_for_rwh = (id_map or {}).get(rwh)
        try:
            res = update_bid(self, rwh, bid, where=where, pylx=pylx,
                             dry_run=dry_run, id_field=id_for_rwh,
                             xkfsdm=xkfsdm)
            results.append({
                "rwh": rwh,
                "bid": bid,
                "ok": res.get("jg") == "1" or res.get("dry_run"),
                "message": res.get("message", ""),
                "dry_run": res.get("dry_run", False),
            })
        except Exception as e:
            results.append({"rwh": rwh, "bid": bid, "ok": False,
                            "message": str(e),
                            "dry_run": dry_run})
    return {
        "ok": all(r["ok"] for r in results),
        "results": results,
        "sum": total,
        "jffs_limit": jffs_limit,
        "over_limit": False,
        "round_code": round_code,
        "dry_run": dry_run,
    }
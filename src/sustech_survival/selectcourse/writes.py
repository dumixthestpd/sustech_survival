"""
sustech_survival.selectcourse.writes 鈥?Course add/drop/update_bid methods.

Split from `selectcourse.py` (2026-08-08) so the read-side client stays
narrow. These methods mutate enrollment on TIS 鈥?every one defaults to
`dry_run=True` and prints the payload that WOULD be POSTed. The user
must explicitly set `dry_run=False` to fire a real write.

The 5 public methods:
  add_course(rwh)         鈥?Xsxk/addXuanke       (direct enroll)
  drop_course(rwh)        鈥?Xsxk/tuike           (drop)
  add_to_cart(rwh)        鈥?Xsxk/addGouwuche     (add to cart)
  remove_from_cart(rwh)   鈥?Xsxk/delGouwuche     (remove from cart)
  update_bid(rwh, bid)    鈥?Xsxk/updXkxsByyx|gwc (set bid on existing pick)
  submit_bids(picks)      鈥?bulk wrapper around update_bid

Discovery doc: references/tis-api.md
"""
from __future__ import annotations
from sustech_survival._net import timeout as _net_timeout

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
    r = self._auth.post(endpoint, data=payload, timeout=_net_timeout("tis"),
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
    - `xkfsdm="yixuan"` (宸查€? 鈥?matches HAR for updXkxsByyx/tuike.
    - `xktjz="rwtjzyx"` (浠诲姟鎻愪氦鑷冲凡閫? 鈥?HAR shows this for ALL write
      endpoints (addGouwuche/updXkxsByyx/tuike). If omitted, TIS
      rejects with 鎿嶄綔澶辫触 because the field is required.
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
    """Add a course to your enrolled list (鐩存帴閫夎).

    `rwh`: the 浠诲姟鍙?(task number) from `Course.rwh` or `my_courses()`.
           Used as a key to look up the hex `id_field` if not given.
    `id_field`: 32-char hex UUID from `queryKxrw` row.id 鈥?the actual
           TIS write-key. If omitted, the client looks it up in its
           cached catalog (requires a prior personal-mode search to
           have populated `Course.id` for that rwh).
    `xkfsdm`: round code (HAR shows "yixuan" for enrolled-list ops).
           Defaults to "yixuan" via _build.

    `bid`: 閫夎绯绘暟 (the credit bid in 绉垎閫夎). 1 = minimum.

    `dry_run=True` (default): returns what would be POSTed without
                              firing the request. SAFE.
    `dry_run=False`: actually fires `Xsxk/addXuanke`. This MUTATES
                     your enrollment 鈥?use only after reviewing.

    Returns the TIS response dict. On dry_run, includes `dry_run=True`
    and `would_post=<full payload>`. On real call, includes `jg='1'`
    and `message='閫夎鎴愬姛'` (or similar) on success.

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
    """Drop a course (閫€璇? by 浠诲姟鍙?

    Same `dry_run` semantics as `add_course`. Fires `Xsxk/tuike`.
    `xkfsdm` defaults to "yixuan" (matches HAR 鈥?tuike with any other
    code, or empty, is rejected with jg=-1 鎿嶄綔澶辫触; verified against
    the 2026-08-31 full-flow HAR where the official page's successful
    tuike carried p_xkfsdm=yixuan).
    """
    if xkfsdm is None:
        xkfsdm = "yixuan"
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
    """Add a course to your shopping cart (璐墿杞?.

    `xkfsdm` defaults to "bxxk" (閫氳瘑蹇呬慨閫夎) 鈥?matches HAR for
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

@consequence_rich(Consequence(
    name="selectcourse.update_bid",
    severity=Severity.MEDIUM,
    irreversible=False,
    what_changes="Updates the bid value for one selected course on TIS.",
    risk="A bid change can affect selection priority and the remaining bid budget.",
    verify_url="https://tis.sustech.edu.cn/#/xsxk?rwh={rwh}",
))
def update_bid(self, rwh: str, bid: int, *,
               where: str = "enrolled",
               pylx: Optional[str] = None,
               dry_run: bool = True,
               id_field: Optional[str] = None,
               xkfsdm: Optional[str] = None) -> dict:
    """Update the bid (閫夎绯绘暟) on an already-picked course.

    `where`: "enrolled" (宸查€?鈫?calls Xsxk/updXkxsByyx)
             or  "cart"    (璐墿杞?鈫?calls Xsxk/upd_xkxsBygwc)
    `xkfsdm`: round code. HAR shows "yixuan" for both updXkxsByyx and
             upd_xkxsBygwc 鈥?default to "yixuan" if None.
    `bid`: positive integer. TIS rejects if the round uses 绉垎
           mode and bid is missing / 0 / non-integer.
    `id_field`: hex UUID for `p_id`. If omitted, looked up from catalog.

    For NEW picks (not yet in cart/enrolled), use `add_to_cart(bid=鈥?`
    or `add_course(bid=鈥?` instead 鈥?they pass the bid on the create.
    """
    bid = int(bid)
    if bid < 1:
        raise ValueError(f"bid must be a positive integer, got {bid}")
    if xkfsdm is None:
        xkfsdm = "yixuan"   # HAR: upd endpoints use yixuan; "" 鈫?jg=-1
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
    what_changes="Commits your bid values for multiple courses (绉垎閫夎).",
    risk=("Bid window may not reopen; a wrong bid is hard to undo. "
          "Review the per-course preview before committing."),
    verify_url="https://tis.sustech.edu.cn/#/xsxk",
))
def submit_bids(self, picks: dict, *,
                round_code: str = "",
                where: str = "cart",
                jffs_limit: Optional[float] = None,
                baseline: Optional[dict] = None,
                pylx: Optional[str] = None,
                dry_run: bool = True,
                id_map: Optional[dict] = None,
                xkfsdm: Optional[str] = None) -> dict:
    """Submit a batch of bid values for the user's picked courses.

    `picks`:  {rwh: bid_int, ...} 鈥?the user's desired bid per course.
    `round_code`: the active round code. Used as the default xkfsdm if
                  `xkfsdm` not given (HAR shows both updXkxsByyx and
                  upd_xkxsBygwc use "yixuan" for the enrolled-cart round).
    `where`:  "enrolled" (call updXkxsByyx) or "cart" (call
              upd_xkxsBygwc) 鈥?same as `update_bid`.
    `jffs_limit`: the REMAINING bid points for this student (TIS
                  xkgzszOne.jfxs 鈥?verified live 2026-08-31: enrolled
                  bids are NOT part of it; semester total = committed +
                  jffs, e.g. 129 + 26 = 155). If provided, validate that
                  the batch's budget CONSUMPTION does not exceed it and
                  return ok=False without any TIS calls otherwise.
    `baseline`: optional {rwh: bid_int} 鈥?the bid values TIS already
                  holds (enrolled xkxs / cart xkxs). The budget
                  consumption of a pick is `max(0, bid - baseline)`:
                  re-stating an enrolled course's current bid costs
                  nothing, raising it costs the difference, lowering it
                  frees points. Without a baseline entry the full bid
                  counts (a brand-new pick).
    `id_map`: optional {rwh: id_hex} pre-populated by caller (e.g. from
              a prior personal search). If omitted, each rwh is
              looked up in the catalog; missing entries cause the
              per-pick result to be ok=False with a clear message
              rather than failing silently.

    Returns a dict:
      {
        "ok": True/False,
        "results": [{rwh, bid, ok, message}, ...],
        "sum": N,               # raw sum of the bids (display)
        "check_sum": N,         # budget consumption actually checked
        "jffs_limit": X or None,
        "over_limit": True/False,
        "round_code": str,
      }

    Each TIS call still respects `dry_run` 鈥?the loop is read+write
    either way; `dry_run` only controls whether the actual POST
    fires. Validation (jffs check) always runs.

    If the consumption exceeds `jffs_limit`, the function short-circuits
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
    base = baseline or {}

    # Pre-compute the totals. If the consumption would blow the
    # remaining budget, return WITHOUT firing any TIS calls (including
    # dry-run). Build a synthetic per-pick result so the caller can
    # render what was rejected.
    try:
        coerced = {rwh: int(b) for rwh, b in picks.items()}
    except (TypeError, ValueError):
        return {
            "ok": False, "results": [],
            "error": "all bid values must be integers",
            "sum": 0, "check_sum": 0, "jffs_limit": jffs_limit,
            "over_limit": False,
            "round_code": round_code, "dry_run": dry_run,
        }
    total = sum(max(0, b) for b in coerced.values())
    # Budget consumption: only the part ABOVE the TIS-held baseline
    # draws from the remaining points (enrolled/cart re-statements and
    # decreases are free / credit).
    check_total = sum(
        max(0, b - int(base.get(rwh) or 0)) for rwh, b in coerced.items()
    )
    if jffs_limit is not None and check_total > jffs_limit:
        results = [{"rwh": rwh, "bid": b, "ok": False,
                    "message": (f"over budget (needs {check_total} of "
                                f"{jffs_limit} remaining pts)"),
                    "dry_run": dry_run}
                   for rwh, b in coerced.items() if b >= 1]
        return {
            "ok": False,
            "results": results,
            "sum": total,
            "check_sum": check_total,
            "jffs_limit": jffs_limit,
            "over_limit": True,
            "round_code": round_code,
            "dry_run": dry_run,
        }

    for rwh, bid in coerced.items():
        if bid < 1:
            results.append({"rwh": rwh, "bid": bid, "ok": False,
                            "message": "bid must be 鈮?1",
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
        "check_sum": check_total,
        "jffs_limit": jffs_limit,
        "over_limit": False,
        "round_code": round_code,
        "dry_run": dry_run,
    }

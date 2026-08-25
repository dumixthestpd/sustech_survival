"""
sustech_survival.selectcourse.endpoints — TIS HTTP endpoints + write-side
constants (XKTJZ_*, etc.).

Single source of truth for the URLs this package hits. Imported by
`selectcourse.py` and `queryform.py` (which needs XKTJZ_TASK_TO_ENROLLED
to populate `p_xktjz`).

Discovery doc: sustech-dev/references/tis-api.md
"""

TIS_BASE = "https://tis.sustech.edu.cn"

# READ endpoints
TIS_CAMPUS_SCHEDULE_URL = f"{TIS_BASE}/Xsxktz/queryRwxxcxList"
TIS_PERSONAL_SCHEDULE_URL = f"{TIS_BASE}/xszykb/queryxszykbzong"
TIS_PERSONAL_WEEK_URL = f"{TIS_BASE}/xszykb/queryxszykbzhou"
TIS_QUERY_KXRW_URL = f"{TIS_BASE}/Xsxk/queryKxrw"        # 选课 search (personal selection)

# WRITE endpoints
TIS_ADD_XUANKE_URL = f"{TIS_BASE}/Xsxk/addXuanke"
TIS_TUIKE_URL = f"{TIS_BASE}/Xsxk/tuike"
TIS_ADD_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/addGouwuche"
TIS_DEL_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/delGouwuche"
TIS_UPD_XKXS_BY_YX = f"{TIS_BASE}/Xsxk/updXkxsByyx"
# NOTE: there is NO upd_xkxsBygwc endpoint on TIS — the HAR only shows
# addGouwuche/updXkxsByyx/tuike. Cart-update is folded into addGouwuche.
# `where="cart"` in submit_bids routes to addGouwuche (which behaves like
# an upsert for cart entries). Kept as an alias for back-compat but
# the URL is the same as addGouwuche.
TIS_UPD_XKXS_BY_GWC = TIS_ADD_GOUWUCHE_URL  # legacy alias — was a 404 phantom

# xktjz (选课提交至) values — where the action lands. Discovered from
# the user's HAR (tis.sustech.edu.cn.har, 2026-08-08): every write
# endpoint the user actually called — addGouwuche, updXkxsByyx, tuike,
# queryKxrw, queryYxkc — uses `p_xktjz=rwtjzyx` (任务提交至已选).
# Despite the endpoint name `addGouwuche` (add to cart), TIS does NOT
# accept `p_xktjz=rwtjzgwc` for it — that returns 操作失败 silently.
# Only `addXuanke` uses `gwctjzyx` (cart → enrolled finalization).
XKTJZ_CART_TO_ENROLLED = "gwctjzyx"        # used by addXuanke (cart final → enrolled)
XKTJZ_TASK_TO_ENROLLED = "rwtjzyx"        # used by addGouwuche / updXkxsByyx / tuike

# Back-compat alias (the OLD constant value was wrong; keep the name so
# old callers don't AttributeError, but point it to the correct value).
XKTJZ_TASK_TO_CART = XKTJZ_TASK_TO_ENROLLED  # legacy alias; semantically "task → enrolled"
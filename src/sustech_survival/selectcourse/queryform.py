"""
sustech_survival.selectcourse.queryform 鈥?TIS wire-format payload builder.

The TIS write-side endpoints (`Xsxk/addXuanke`, `Xsxk/tuike`,
`Xsxk/addGouwuche`, `Xsxk/delGouwuche`, `Xsxk/updXkxsByyx`,
`Xsxk/upd_xkxsBygwc`) all POST a `queryform`-shaped form-urlencoded
body with ~30 fixed keys + caller-supplied id/bid. This file is the
single source of truth for that shape, calibrated against a live HAR
capture (tis.sustech.edu.cn.har, 2026-08-08) of a successful
`updXkxsByyx` call.

The previous (inline) version missed several required fields (cxsfmt,
mxpylx, p_chaxunxkfsdm, pageNum, pageSize, p_dqxn/p_dqxq/p_dqxnxq)
and used a wrong flag for p_sfsyxkgwc, which together caused every
write to silently fail with 鎿嶄綔澶辫触 鈥?the user-visible symptom was
"bidsync does nothing."

Split from `selectcourse.py` (2026-08-08) so the wire format is isolated
from the read-side client and can be unit-tested against HAR bytes.
"""
from __future__ import annotations
from sustech_survival._net import timeout as _net_timeout

from typing import Optional


def build_queryform(*, sem,            # Semester
                    auth,            # TISAuth (for _fetch_dq)
                    id_field: Optional[str] = None,
                    ids: Optional[list] = None,
                    xktjz: Optional[str] = None,
                    xkfsdm: Optional[str] = None,
                    pylx: Optional[str] = None,
                    ignore_conflicts: bool = False,
                    ignore_zero_capacity: bool = False,
                    bid: Optional[int] = None) -> dict:
    """Build the TIS `queryform` payload for write-side endpoints.

    `id_field` is the 32-char hex UUID from `queryKxrw`'s row.id 鈥?this is
    what TIS expects as `p_id`. DO NOT pass the human-readable `rwh`
    (e.g. "2026-2027-1-MSE301-002"); TIS silently 鎿嶄綔澶辫触 with that.
    The hex UUID is only populated by the personal-mode search
    (`queryKxrw`); the campus catalog (`queryRwxxcxList`) doesn't carry
    it. Callers that don't have it must run a personal search first.

    `xkfsdm` is the round code (e.g. "bxxk" for 閫氳瘑蹇呬慨閫夎, "yixuan"
    for 宸查€?. HAR shows it's set on every successful write. Common
    values seen: "bxxk" for addGouwuche; "yixuan" for updXkxsByyx/tuike.
    Default "" matches HAR for fields that explicitly omit it.

    `bid` is the 閫夎绯绘暟 (selection coefficient, aka the credit bid
    in 绉垎閫夎). Goes into `p_xkxs`. Leave None to omit (TIS then
    uses the default 1 鈥?fine for round tables that don't score).

    `pylx` is the 鍩瑰吇绫诲瀷 code (1=鏈, 2=鐮旂┒鐢?. Defaults to "1"
    (undergrad) when the caller passes None 鈥?TIS rejects missing
    pylx with 鎿嶄綔澶辫触 for undergrad students.

    `sem` is a Semester (provides .xn, .xq). `auth` is a TISAuth
    (provides .post() and the cached `_fetch_dq()` round-trip).
    """
    # queryXkdqXnxq is required for p_dqxn/p_dqxq/p_dqxnxq/cxsfmt
    # (TIS's CURRENT active term, used as the round context). It's
    # cached for the session, so this is one HTTP call per session.
    try:
        dq = auth._fetch_dq() if hasattr(auth, "_fetch_dq") else _fetch_dq_via_auth(auth)
    except Exception:
        # Offline / no auth: fall back to empty strings. The request
        # will still be sent (it'll just be rejected by TIS), so the
        # caller sees a clean error instead of a confusing 500.
        dq = {"p_dqxn": "", "p_dqxq": "", "p_dqxnxq": "", "cxsfmt": ""}
    # p_xnxq = "2026-20271" (瀛﹀勾 + 瀛︽湡) 鈥?combine xn + xq directly.
    xnxq = sem.xn + sem.xq
    return {
        # -- Top-level (no p_ prefix in HAR) -------------------------
        "cxsfmt": dq.get("cxsfmt", "0"),
        "mxpylx": pylx if pylx is not None else "1",  # 鍩瑰吇绫诲瀷 (mirror of p_pylx)
        # -- queryform fields (HAR-derived, 2026-08-08) --------------
        "p_pylx": pylx if pylx is not None else "1",  # 1=鏈, 2=鐮旂┒鐢?
        "p_sfgldjr": "0",                            # 鏄惁绠＄悊绔繘鍏?
        "p_sfredis": "0",                            # 鏄惁Redis缂撳瓨 (HAR: 0)
        "p_sfsyxkgwc": "0",                          # 鏄惁浣跨敤閫夎璐墿杞?(HAR: 0)
        "p_xktjz": xktjz,                            # 閫夎鎻愪氦鑷?鈥?see XKTJZ_* constants
        "p_chaxunxh": "",                            # 绠＄悊绔煡璇㈠鍙?
        "p_chaxunxkfsdm": "",                        # mirrors p_xkfsdm in HAR
        "p_gjz": "",                                 # 鍏抽敭瀛?
        "p_skjs": "",                                # 涓婅鏁欏笀
        "p_xn": sem.xn,                              # 瀛﹀勾
        "p_xq": sem.xq,                              # 瀛︽湡
        "p_xnxq": xnxq,                              # 瀛﹀勾瀛︽湡鍚堝苟 "2026-20271"
        "p_dqxn": dq.get("p_dqxn", ""),              # CURRENT TIS active term xn
        "p_dqxq": dq.get("p_dqxq", ""),              # CURRENT TIS active term xq
        "p_dqxnxq": dq.get("p_dqxnxq", ""),          # CURRENT TIS active term xnxq
        "p_xkfsdm": xkfsdm or "",                    # 閫夎鏂瑰紡浠ｇ爜 (HAR: yixuan|bxxk|...)
        "p_xiaoqu": "",                              # 鏍″尯
        "p_kkyx": "",                                # 寮€璇鹃櫌绯?
        "p_kclb": "",                                # 璇剧▼绫诲埆
        "p_xkxs": bid if bid is not None else "",    # 閫夎绯绘暟 / 绉垎閫夎鐨?bid
        "p_dyc": "",                                 # 澶氳绉?
        "p_kkxnxq": "",                              # 寮€璇惧骞村鏈?
        "p_id": id_field,                            # 鈽?璇剧▼id (32-char hex UUID from queryKxrw)
        "p_ids": ids if ids is not None else [],     # 鈽?鎵归噺id鍒楄〃
        "p_sfhlctkc": "1" if ignore_conflicts else "0",      # 鏄惁蹇界暐鍐茬獊璇剧▼
        "p_sfhllrlkc": "1" if ignore_zero_capacity else "0", # 鏄惁蹇界暐闆跺閲忚绋?
        "p_kxsj_xqj": "", "p_kxsj_ksjc": "", "p_kxsj_jsjc": "",
        "p_kcdm_js": "", "p_kcdm_cxrw": "", "p_kcdm_cxrw_zckc": "",
        "p_kc_gjz": "",
        "p_xzcxtjz_nj": "", "p_xzcxtjz_yx": "", "p_xzcxtjz_zy": "",
        "p_xzcxtjz_zyfx": "", "p_xzcxtjz_bj": "",
        "p_sfxsgwckb": "1",                          # 鏄惁鏄剧ず璐墿璇捐〃
        "p_skyy": "",                                # 涓婅璇█
        "p_sfmxzj": "",                              # 婊¤冻鎬ц嚜鑽?(HAR: empty)
        "pageNum": "1",
        "pageSize": "19",
    }


def _fetch_dq_via_auth(auth):
    """Fallback for callers that don't carry the cache on auth.

    Most callers pass the SelectCourseClient as `auth`, which has
    `_fetch_dq()` cached on self. Newer code might pass a raw TISAuth
    and need to talk to TIS directly. Used by build_queryform above.
    """
    return auth.post("/Xsxk/queryXkdqXnxq", data={}, timeout=_net_timeout("tis"),
                     headers={"X-Requested-With": "XMLHttpRequest"}).json()

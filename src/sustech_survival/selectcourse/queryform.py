"""
sustech_survival.selectcourse.queryform — TIS wire-format payload builder.

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
write to silently fail with 操作失败 — the user-visible symptom was
"bidsync does nothing."

Split from `selectcourse.py` (2026-08-08) so the wire format is isolated
from the read-side client and can be unit-tested against HAR bytes.
"""
from __future__ import annotations

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

    `id_field` is the 32-char hex UUID from `queryKxrw`'s row.id — this is
    what TIS expects as `p_id`. DO NOT pass the human-readable `rwh`
    (e.g. "2026-2027-1-MSE301-002"); TIS silently 操作失败 with that.
    The hex UUID is only populated by the personal-mode search
    (`queryKxrw`); the campus catalog (`queryRwxxcxList`) doesn't carry
    it. Callers that don't have it must run a personal search first.

    `xkfsdm` is the round code (e.g. "bxxk" for 通识必修选课, "yixuan"
    for 已选). HAR shows it's set on every successful write. Common
    values seen: "bxxk" for addGouwuche; "yixuan" for updXkxsByyx/tuike.
    Default "" matches HAR for fields that explicitly omit it.

    `bid` is the 选课系数 (selection coefficient, aka the credit bid
    in 积分选课). Goes into `p_xkxs`. Leave None to omit (TIS then
    uses the default 1 — fine for round tables that don't score).

    `pylx` is the 培养类型 code (1=本科, 2=研究生). Defaults to "1"
    (undergrad) when the caller passes None — TIS rejects missing
    pylx with 操作失败 for undergrad students.

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
    # p_xnxq = "2026-20271" (学年 + 学期) — combine xn + xq directly.
    xnxq = sem.xn + sem.xq
    return {
        # ── Top-level (no p_ prefix in HAR) ─────────────────────────
        "cxsfmt": dq.get("cxsfmt", "0"),
        "mxpylx": pylx if pylx is not None else "1",  # 培养类型 (mirror of p_pylx)
        # ── queryform fields (HAR-derived, 2026-08-08) ──────────────
        "p_pylx": pylx if pylx is not None else "1",  # 1=本科, 2=研究生
        "p_sfgldjr": "0",                            # 是否管理端进入
        "p_sfredis": "0",                            # 是否Redis缓存 (HAR: 0)
        "p_sfsyxkgwc": "0",                          # 是否使用选课购物车 (HAR: 0)
        "p_xktjz": xktjz,                            # 选课提交至 — see XKTJZ_* constants
        "p_chaxunxh": "",                            # 管理端查询学号
        "p_chaxunxkfsdm": "",                        # mirrors p_xkfsdm in HAR
        "p_gjz": "",                                 # 关键字
        "p_skjs": "",                                # 上课教师
        "p_xn": sem.xn,                              # 学年
        "p_xq": sem.xq,                              # 学期
        "p_xnxq": xnxq,                              # 学年学期合并 "2026-20271"
        "p_dqxn": dq.get("p_dqxn", ""),              # CURRENT TIS active term xn
        "p_dqxq": dq.get("p_dqxq", ""),              # CURRENT TIS active term xq
        "p_dqxnxq": dq.get("p_dqxnxq", ""),          # CURRENT TIS active term xnxq
        "p_xkfsdm": xkfsdm or "",                    # 选课方式代码 (HAR: yixuan|bxxk|...)
        "p_xiaoqu": "",                              # 校区
        "p_kkyx": "",                                # 开课院系
        "p_kclb": "",                                # 课程类别
        "p_xkxs": bid if bid is not None else "",    # 选课系数 / 积分选课的 bid
        "p_dyc": "",                                 # 多语种
        "p_kkxnxq": "",                              # 开课学年学期
        "p_id": id_field,                            # ★ 课程id (32-char hex UUID from queryKxrw)
        "p_ids": ids if ids is not None else [],     # ★ 批量id列表
        "p_sfhlctkc": "1" if ignore_conflicts else "0",      # 是否忽略冲突课程
        "p_sfhllrlkc": "1" if ignore_zero_capacity else "0", # 是否忽略零容量课程
        "p_kxsj_xqj": "", "p_kxsj_ksjc": "", "p_kxsj_jsjc": "",
        "p_kcdm_js": "", "p_kcdm_cxrw": "", "p_kcdm_cxrw_zckc": "",
        "p_kc_gjz": "",
        "p_xzcxtjz_nj": "", "p_xzcxtjz_yx": "", "p_xzcxtjz_zy": "",
        "p_xzcxtjz_zyfx": "", "p_xzcxtjz_bj": "",
        "p_sfxsgwckb": "1",                          # 是否显示购物课表
        "p_skyy": "",                                # 上课语言
        "p_sfmxzj": "",                              # 满足性自荐 (HAR: empty)
        "pageNum": "1",
        "pageSize": "19",
    }


def _fetch_dq_via_auth(auth):
    """Fallback for callers that don't carry the cache on auth.

    Most callers pass the SelectCourseClient as `auth`, which has
    `_fetch_dq()` cached on self. Newer code might pass a raw TISAuth
    and need to talk to TIS directly. Used by build_queryform above.
    """
    return auth.post("/Xsxk/queryXkdqXnxq", data={}, timeout=15,
                     headers={"X-Requested-With": "XMLHttpRequest"}).json()
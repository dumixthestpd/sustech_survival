# TIS API Reference

> **What this is.** The endpoints exposed by `tis.sustech.edu.cn` that
> we've discovered and wrapped (or could wrap) in this skill tree. Sources:
>
> - `Xsxktz/queryRwxxcxList` and `xszykb/query*` — discovered by reading
>   the `authentication/main` Vue app source and the catalog page
>   `/Xsxk/query/1`.
> - All `Xsxk/*` write-side endpoints — discovered 2026-06-19 by walking
>   the `/pub/xkgl/xsxk/xsxk-*.js` JS bundle on the catalog page.
>
> **Status legend.** ✅ wrapped in `sustech_survival.selectcourse` (or
> elsewhere). ⚠️ discovered but not yet wrapped. ❓ observed in the bundle
> but semantics unverified.

## Base URL

```
https://tis.sustech.edu.cn
```

All endpoints are POST unless noted. Most require a valid TIS CAS
session (TGC cookie + JSESSIONID + route cookie). Auth flow lives in
`selectcourse._tis_login` / `sso.Authorizer`.

## Term encoding

```
xn   academic year (e.g. "2025-2026")
xq   semester: 1=Fall, 2=Spring, 3=Summer (Jul-Aug)
```

## READ-side endpoints

| Status | Endpoint                          | Used for                                             |
|--------|-----------------------------------|------------------------------------------------------|
| ✅     | `Xsxktz/queryRwxxcxList`          | Public catalog browse (any xq, including summer)     |
| ✅     | `xszykb/queryxszykbzong`          | Your enrolled courses for a semester                 |
| ✅     | `xszykb/queryxszykbzhou`          | Your enrolled courses for a specific week            |
| ⚠️     | `Xsxk/queryKxrw`                  | Selectable courses list (with enrollment filters)    |
| ⚠️     | `Xsxk/queryKkxqList`              | Open course sections list                            |
| ⚠️     | `Xsxk/queryXkxsDet`               | Student-course detail                               |
| ⚠️     | `Xsxk/queryXkgwc`                 | Shopping cart contents                               |
| ⚠️     | `Xsxk/queryYxkc`                  | Enrolled courses list (shopping cart UI panel)       |
| ⚠️     | `Xsxk/queryXkggZx`                | Selection rules (选课规则)                           |
| ⚠️     | `Xsxk/queryXsxkrzList`            | Selection log (选课日志)                             |
| ⚠️     | `Xsxk/queryKxrwByKcdm_js`         | Query by course code (JS variant)                    |
| ⚠️     | `Xsxk/queryJiaofei`               | Tuition payment query                                |
| ⚠️     | `Xsxk/queryXkdqXnxq`              | Current academic term                                |

### `Xsxktz/queryRwxxcxList` (catalog) — wrapped

```http
POST /Xsxktz/queryRwxxcxList
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

p_xn=2025-2026&p_xq=2&p_xnxq=&p_gjz=&p_xiaoqu=&p_kkyx=&p_rwlx=
&p_kclb=&p_kcxz=&p_chaxunpylx=3&pageNum=1&pageSize=500
```

Response shape: `{ rwList: { list: [...], total, pageNum, pageSize } }`.

Each row has `kcdm`, `kcmc`, `kxh`, `rwh`, `kkyxmc`, `kclbmc`, `kcxzmc`,
`xiaoqumc`, `xf`, `zxs`, `zrl`, `bksrl`, `yjsrl`, `pylx`, and a `kcxx`
HTML blob (where the real schedule+room data lives — parsed by
`classroom.schema.parse_kcxx`).

`rwh` (任务号 / task number) is the natural primary key for one
offering. It looks like `2025-2026-2-BIO101-001`.

### `xszykb/queryxszykbzong` (your enrolled) — wrapped

```http
POST /xszykb/queryxszykbzong
xn=2025-2026&xq=2
```

Response: a flat list of dicts with `RWH`, `kcdm`, `kcmc`, `kxh`,
`rwmc`, `SKSJ` (上课时间), etc.

## WRITE-side endpoints

> **All write-side endpoints default to `dry_run=True` in the
> `selectcourse` module.** Pass `dry_run=False` to actually fire the
> request. These mutate your enrollment — be careful.

| Status | Endpoint                       | Used for                                   |
|--------|--------------------------------|--------------------------------------------|
| ✅     | `Xsxk/addXuanke`               | Submit shopping cart → enrolled (选课)     |
| ✅     | `Xsxk/tuike`                   | Drop a course (退课)                       |
| ✅     | `Xsxk/addGouwuche`             | Add to shopping cart                       |
| ✅     | `Xsxk/delGouwuche`             | Remove from shopping cart                  |
| ⚠️     | `Xsxk/updXuefeijiaofei`        | Tuition payment update                     |
| ⚠️     | `Xsxk/updXkxsByyx`             | Update student-course by enrolled status   |
| ⚠️     | `Xsxk/updXkxsBygwc`            | Update student-course by cart status       |
| ❓     | `Xsxk/cxmtctPd`                | Conflict check (called before addXuanke)   |

### `Xsxk/addXuanke` (the "click select" button) — wrapped

```http
POST /Xsxk/addXuanke
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

p_pylx=1
p_sfgldjr=0
p_sfredis=
p_sfsyxkgwc=1
p_xktjz=gwctjzyx       # 购物车提交至已选
p_chaxunxh=
p_gjz=
p_skjs=
p_xn=2025-2026
p_xq=2
p_id=2025-2026-2-BIO101-001   # ★ the task number from catalog
p_ids=
p_sfhlctkc=0           # 0=check conflicts, 1=ignore
p_sfhllrlkc=0          # 0=check zero-capacity, 1=ignore
... (other filter fields default to '')
```

Response shape: `{ jg: '1'|'0'|'-1', message: '...', ... }`

- `jg='1'` → success
- `jg='0'` → failure (e.g. 已选满 = full)
- `jg='-1'` → not allowed (e.g. not in selection window)

### `Xsxk/tuike` (the "click drop" button) — wrapped

```http
POST /Xsxk/tuike
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

p_id=2025-2026-2-BIO101-001   # ★ task number of enrolled course
p_xn=2025-2026
p_xq=2
... (rest of queryform)
```

Same response shape as `addXuanke`.

### `Xsxk/addGouwuche` (add to cart) — wrapped

```http
POST /Xsxk/addGouwuche
p_id=<task number>
p_xktjz=rwtjzgwc      # 任务→购物车 (task → cart)
p_xkxs=null
...
```

### `Xsxk/delGouwuche` (remove from cart) — wrapped

```http
POST /Xsxk/delGouwuche
p_id=<task number>
...
```

## The `p_xktjz` (选课提交至) enum

| Value         | Meaning                  | Used by                   |
|---------------|--------------------------|---------------------------|
| `gwctjzyx`    | 购物车提交至已选 (cart→enrolled) | `Xsxk/addXuanke` (default for `add_course()`) |
| `rwtjzgwc`    | 任务提交至购物车 (task→cart)    | `Xsxk/addGouwuche` (default for `add_to_cart()`) |

`gwctjzyx` for `addGouwuche` skips the cart and goes straight to enrolled
(same effect as `addXuanke`).

## The full `queryform` payload

This is what TIS expects on every write-side POST. All keys are
required by the form (most default to empty string / `0` / null).
Extracted directly from `pub/xkgl/xsxk/xsxk-*.js`:

```python
{
    "p_pylx": None,             # 培养类型: 1=本科, 2=研究生
    "p_sfgldjr": "0",           # 是否管理端进入
    "p_sfredis": "",            # 是否Redis缓存
    "p_sfsyxkgwc": "1",         # 是否使用选课购物车
    "p_xktjz": None,            # 选课提交至 (gwctjzyx / rwtjzgwc)
    "p_chaxunxh": "",           # 管理端查询学号
    "p_gjz": "",                # 关键字
    "p_skjs": "",               # 上课教师
    "p_xn": "2025-2026",        # 学年
    "p_xq": "2",                # 学期
    "p_xnxq": None,             # 学年学期（合并）
    "p_dqxn": None,
    "p_dqxq": None,
    "p_dqxnxq": None,
    "p_xkfsdm": "",             # 选课方式代码
    "p_xiaoqu": "",             # 校区
    "p_kkyx": "",               # 开课院系
    "p_kclb": "",               # 课程类别
    "p_xkxs": None,             # 选课系数
    "p_dyc": None,              # 多语种
    "p_kkxnxq": "",             # 开课学年学期
    "p_id": None,               # ★ 课程id (任务号 rwh)
    "p_ids": [],                # ★ 批量id列表
    "p_sfhlctkc": "0",          # 是否忽略冲突课程
    "p_sfhllrlkc": "0",         # 是否忽略零容量课程
    "p_kxsj_xqj": "",
    "p_kxsj_ksjc": "",
    "p_kxsj_jsjc": "",
    "p_kcdm_js": "",
    "p_kcdm_cxrw": "",
    "p_kcdm_cxrw_zckc": "",
    "p_kc_gjz": "",
    "p_xzcxtjz_nj": "",
    "p_xzcxtjz_yx": "",
    "p_xzcxtjz_zy": "",
    "p_xzcxtjz_zyfx": "",
    "p_xzcxtjz_bj": "",
    "p_sfxsgwckb": "1",
    "p_skyy": "",
    "p_sfmxzj": "0",
}
```

## How the discover was done

```bash
# 1. Log in to TIS, capture cookies
# 2. Fetch the catalog page (the only page that loads the xsxk bundle):
curl -b cookies 'https://tis.sustech.edu.cn/Xsxk/query/1' > catalog.html

# 3. Extract the bundle URL from the HTML:
grep -oE '/pub/xkgl/xsxk/xsxk-[a-f0-9]+\.js' catalog.html
# → /pub/xkgl/xsxk/xsxk-e9251afcd0ca4995004098e91ec476b0.js

# 4. Download the bundle (needs Referer + session cookie):
curl -b cookies -e 'https://tis.sustech.edu.cn/Xsxk/query/1' \
  'https://tis.sustech.edu.cn/pub/xkgl/xsxk/xsxk-e9251afcd0ca4995004098e91ec476b0.js' \
  > xsxk.js

# 5. Grep for endpoints + method bodies:
grep -oE '"Xsxk/[A-Za-z_]+"' xsxk.js | sort -u
grep -A 30 'addXuanke.*function\|tuike.*function' xsxk.js
```

Result: 18 endpoints total, 4 wrapped (add/drop + cart add/remove), 7
discovered but not wrapped, 1 conflict-check helper observed.

## Selection rounds (轮次) — how 预选/补选/退选/跨学期 map to TIS

**These are NOT TIS technical terms.** They're policy terms from the
教务部 (Academic Affairs Office). TIS implements them through runtime
configuration — multiple "rounds" per semester, each with its own flags.

The TIS UI at `/Xsxk/query/1` has tabs (top right):
```
Tab 0: 已选 (yixuan)         — courses selected
Tab 1: 购物车 (gouwuche)     — shopping cart (only if p_sfsyxkgwc=='1')
Tab 2+: <one tab per round>  — labeled with xkgzszOne.xkfsmc / xkfsmc_en
```

Each round (`xkgzszOne`, populated from `xkgzszList`) carries:
| Field         | Meaning                                              |
|---------------|------------------------------------------------------|
| `xkfsdm`      | Round code (the `xkfsdm` value to POST in `p_xkfsdm`)|
| `xkfsmc`      | Round name in Chinese (e.g. "第一轮预选")             |
| `xkfsmc_en`   | Round name in English (e.g. "Round 1 Pre-selection") |
| `lcmc`        | 轮次名称 (displayed in the green banner as "轮次:{name}") |
| `xkms`        | 选课模式 — `'1'` = 先到先得 (first-come-first-served) |
| `cqms`        | 重修模式 (re-selection mode)                          |
| `sfkx`        | 是否可选 — `'1'` = addXuanke allowed, `'0'` = locked |
| `sfkt`        | 是否可退 — `'1'` = tuike allowed, `'0'` = locked     |
| `sfxzrl`      | 是否限制容量 (capacity-limited?)                      |
| `ksrq`/`jsrq` | 开始日期 / 结束日期 — round active window              |
| `xkqzsj`      | 选课起止时间 (full period text)                       |

### Concrete mapping

| Policy term | TIS mechanism |
|-------------|---------------|
| **预选 (pre-selection)** | One `xkgzszList` entry whose `lcmc` says "第一轮预选" or similar. Set `p_xkfsdm` to its `xkfsdm` and call `Xsxk/addXuanke`. |
| **补选 (make-up)**       | Another `xkgzszList` entry — registrar adds it after 预选 ends. Same `Xsxk/addXuanke` endpoint, different `xkfsdm`. |
| **退选 (drop)**          | Not a separate "round." The current round's `sfkt` flag controls whether `Xsxk/tuike` is allowed. When the round's window passes or `sfkt='0'`, tuike rejects. |
| **跨学期 (cross-semester)** | Not a separate endpoint. Set `p_kkxnxq` (开课学年学期) to a future xn/xq in the queryform. Same `addXuanke` endpoint, different term. |

### Live-verified data (2026-06-19, user 12413021, summer 2026)

Captured by `docs/ui-verification/verify_xsxk_ui.py` (login + Playwright +
read Vue `__vue__` data). The actual configured rounds for this user:

| `xkfsdm` | `xkfsmc` | `xkfsmc_en` | `xkms` | `sfkx` | `sfkt` | `ksrq` | `jsrq` |
|---|---|---|---|---|---|---|---|
| `bxxk` | 通识必修选课 | General Education Required | 1=直选 | 1 | 1 | 2026-06-22 13:00 | 2026-07-03 17:30 |
| `xxxk` | 通识选修选课 | General Education Elective | 1=直选 | 1 | 1 | 2026-06-22 13:00 | 2026-07-03 17:30 |
| `kzyxk` | 培养方案内课程 | Program Required | 1=直选 | 1 | 1 | 2026-06-22 13:00 | 2026-07-03 17:30 |
| `zynknjxk` | 非培养方案内课程 | Outside-Curriculum Accredited | 1=直选 | 1 | 1 | 2026-06-22 13:00 | 2026-07-03 17:30 |
| `cxxk` | 重修选课 | Retake Courses | 1=直选 | 1 | 1 | 2026-06-22 13:00 | 2026-07-03 17:30 |

**Findings:**
- All 5 rounds are `xkms='1'` = 直选 (first-come-first-served, direct selection).
- No "预选" / "补选" / "跨学期" round exists as separate `xkfsdm` codes — those
  are implemented by the registrar opening different time windows (`ksrq`/`jsrq`).
- Selection window opens **3 days from now** (2026-06-22) and closes **2026-07-03 17:30**.
- All rounds `sfkx=1` (selectable) and `sfkt=1` (droppable) once active.
- All `sfxzrl=1` = capacity-limited (zrl / yxrs visible in 容量/已选 column).
- The Chinese 政策 names (通识必修 vs 培养方案内 etc.) are **academic categories**,
  not selection rounds. Each one has its own `xkfsdm` and its own time window.

**The `xkgzszOne` was empty when captured** — because the user hadn't clicked
a round tab yet (defaults to 已选). Once a user clicks e.g. "通识必修选课", the
`xkgzszOne` populates with that round's config and the banner shows the live state.

### What I confirmed vs what I'm inferring

**Confirmed in the page source** (`/Xsxk/query/1` HTML, ~128KB):
- Tab structure (已选 / 购物车 / dynamic rounds)
- Field names: `xkfsdm`, `xkfsmc`, `xkfsmc_en`, `lcmc`, `xkms`, `sfkx`, `sfkt`, `sfxzrl`, `ksrq`, `jsrq`, `xkqzsj`
- The green banner shows "轮次:{lcmc}"
- `sfkt=='1' ? '可退/' : sfkt=='0' ? '不可退/' : ''` — UI renders this directly

**Inferred (not directly seen):**
- The exact strings `预选`, `补选` are not in the bundle. They likely come from the `messages/xkgl` i18n properties file (loaded by `jquery.i18n.properties`) or from the registrar's configured `lcmc` value.
- The actual `xkfsdm` codes are configured per-semester by the registrar — they're not hardcoded.

**Still unknown** (need login + UI screenshot to verify):
- The actual list of `xkfsdm` codes for the current semester (depends on what the registrar configured)
- Whether `跨学期` is enabled for your account (depends on `xkgzszOne.sfkx` for the cross-term round)

### How to find your current round

```bash
# (Requires live login — not yet wrapped in offline tests.)
# When logged in, the page renders the active round in the green banner:
#   轮次:{xkgzszOne.lcmc}    可选/不可选    可退/不可退
#   选课起止时间:{ksrq}~{jsrq}
#
# Programmatic: GET /Xsxk/query/1 with session cookies, parse
# `xkgzszOne.lcmc` from the HTML.
```

This is documented separately because the mechanism (rounds + flags) is
how TIS supports **any** selection policy the school wants — 预选, 补选,
抽签 (lottery), 重修 (re-take), 跨学期 (cross-term), etc. — without code
changes. The school configures `xkgzszList` each semester.

## Open questions

1. **`Xsxk/queryKxrw` vs `Xsxktz/queryRwxxcxList`.** Both return the
   catalog. `Xsxktz/queryRwxxcxList` is the simpler public-catalog view
   (what `selectcourse.list_courses()` uses). `Xsxk/queryKxrw` is the
   "selectable for me" view (filters out courses you can't take based
   on your major/grade/credits). The two share most fields but the
   response shapes differ slightly — `Xsxk/queryKxrw` includes
   `xkgzszList` (选课规则设置) and `yxkcList` (already-enrolled for the
   term). Wrapping the latter would give us a single round-trip for
   "browse + see what I've taken."
2. **`Xsxk/updXuefeijiaofei` (payment).** Triggers after `addXuanke`
   when the course requires tuition payment. Not commonly hit for
   选修课 but matters for credit-bearing courses. Skipped for now.
3. **`p_id` vs `rwh`.** We assume the catalog's `rwh` matches the
   enroll API's `p_id`. TIS doesn't document this mapping. If TIS
   rejects with a `jg='0'` saying the id is invalid, the answer is
   probably that `rwh` ≠ `p_id` for some course categories (e.g.
   cross-listed courses get multiple `rwh` for one `p_id`). Need a real
   test on a safe course to confirm.

## Source bundles

| Bundle                                                       | Purpose                          |
|--------------------------------------------------------------|----------------------------------|
| `/pub/xkgl/xsxk/xsxk-<hash>.js`                              | Main xsxk module — write-side lives here |
| `/pub/xkgl/xsxk/xsxkColumn-<hash>.js`                        | Column/table config              |
| `/js/Action-<hash>.js`                                       | Action utilities                 |
| `/js/RequestParam-<hash>.js`                                 | Request param helpers            |
| `/component/inco/inco.component.kcNew-<hash>.js`             | Course card component            |
| `/component/inco/inco.component.kcview2-<hash>.js`           | Course view (with cart buttons)  |
| `/component/inco/inco.component.moockc-<hash>.js`            | Mock-course component (admin)    |
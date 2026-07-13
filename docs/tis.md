# TIS (Teaching Information System)

教学信息管理系统 — exam schedule, grades, course info, campus schedule, **timetable solver**.

**Auth:** `TISAuth` — CAS-authenticated session via `sustech_survival.sso`. See [SSO](sso.md) for credential setup.

**⚠️ Access levels:** Student (学生（本）) vs teacher. Some endpoints are 403 for students.

---

## Authentication

```python
from sustech_survival.sso import TISAuth

auth = TISAuth()               # singleton-per-class
ok, reason = auth.ensure()     # check + auto-refresh if expired
if not ok:
    raise RuntimeError(reason)

# Use the authenticated session for all TIS calls
r = auth.get("/xszykb/queryxszykbzhou", json={"xn": "2025-2026", "xq": "2", "zc": 1})
```

Or with the decorator:

```python
from sustech_survival.sso import require_auth, TISAuth

@require_auth(TISAuth)
def fetch_exams(auth=None):
    return auth.get("/component/queryKsxxByXs", json={}).json()
```

```bash
# CLI — verify and manage the TIS session
sustech tis session check     # verify credentials work
sustech tis session refresh   # force re-login
```

---

## CLI Overview

```bash
sustech tis courses                    # list enrolled courses
sustech tis courses --semester 2026春季
sustech tis grades                     # show grades + GPA
sustech tis grades --csv path/to/file  # export CSV
sustech tis evals                      # list pending evaluations
sustech tis evals --pending            # only unsubmitted
sustech tis query /component/querydangqianzc  # raw API query
```

---

## User Profile

```
GET https://tis.sustech.edu.cn/user/me
```
Returns: `studentId`, `id` (internal), `name`, `department`, `pylx` (student type), 50+ auth codes.
Access: ✅ Student

---

## Grades

```
POST https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx
Content-Type: application/json

Body: {"xn":null,"xq":null,"kcmc":null,"cxbj":"-1","pylx":"1","current":1,"pageSize":500}
```
Returns: `content.list[]` with `kcmc`, `kcmc_en`, `kcdm`, `xscj` (letter grade), `zzcj` (numeric score), `xf` (credits), `xnxqmc` (semester), `kcxz` (nature), `yxmc` (department).
Access: ✅ Student

### Python API

```python
from sustech_survival.tis.grades import run

run()                        # all semesters, table output
run(semester='2025秋季')     # one semester
run(export='csv')            # exports to grades.csv
```

GPA is calculated using SUSTech's official 4.0 scale (A=3.94, A-=3.67, ...). See [grades.md](grades.md) for the full GPA table.

---

## Courses

```python
from sustech_survival.tis.courses import run

run()                        # all semesters, table output
run(semester='2026春季')
run(format='csv')            # exports to courses_tis.csv
```

Uses the same TIS grade API as grades (returns all course records including ungraded ones). Groups by semester and prints instructor, credits, course type.

| Field | Meaning |
|-------|---------|
| `kcdm` | Course code |
| `kcmc` | Course name |
| `xf` | Credits |
| `dgjsmc` | Instructor |
| `kcxz` | Course type |
| `yxmc` | Department |

---

## Personal Weekly Schedule

**REST API — `xszykb` endpoints (no browser):**

```
POST https://tis.sustech.edu.cn/xszykb/queryxszykbzhou   # one week
POST https://tis.sustech.edu.cn/xszykb/queryxszykbzong   # full semester
GET  https://tis.sustech.edu.cn/component/querydangqianzc  # current week number
```

| Endpoint | Params | Returns |
|---|---|---|
| `/xszykb/queryxszykbzhou` | `xn`, `xq`, `zc` | Personal schedule for week `zc` |
| `/xszykb/queryxszykbzong` | `xn`, `xq` | Full semester (all weeks), includes `ZC` bitmap |
| `/component/querydangqianzc` | — | Current week number (int, 1-18) |
| `/component/querydangqianxnxq` | — | Current semester: `XN`, `XQ`, `XNXQ`, `XNXQ_EN` |

**Key fields in each entry:**

| Field | Meaning |
|---|---|
| `SKSJ` | Course + teacher + class + weeks + room + periods (Chinese) |
| `SKSJ_EN` | Same as above in English |
| `KEY` | `"xq{weekday}_jc{period}"` e.g. `"xq2_jc3"` = Tuesday period 3 |
| `KSJC` / `JSJC` | Start / end period number (1-12, 13=evening) |
| `ZC` | 36-char bitmap — which weeks the course runs (full semester only) |
| `XB` | Number of periods per week for this entry |
| `RWH` | Course record ID: `{xn}-{xq}-{kcdm}-{section}` |

### Python API

```python
from sustech_survival.tis.schedule import (
    current_semester, current_week, week_schedule,
    semester_schedule, week_list
)

sem = current_semester()   # {'XN': '2025-2026', 'XQ': '2', 'XNXQ': '2026春季', ...}
zc  = current_week()       # 14
wk  = week_schedule(zc)    # list of course entries for this week
all = semester_schedule()  # full semester
```

**⚠️ Why not `kebiaoshow` component:** The `inco.component.kebiaoshow` Vue component renders the schedule grid but does not fetch course data itself — it receives `kbjg` as a prop from a parent. The actual data source is the `xszykb` API.

---

## Exam Schedule

```
POST https://tis.sustech.edu.cn/component/queryKsxxByXs
Content-Type: application/json

Body: {}
```
Returns: current semester exam entries. Key fields: `KCMC` (course), `KCDM` (code), `KSRQ` (date), `KSJTSJ` (time), `JXLMC` (building), `JXCDMC` (room), `XQJMC` (weekday), `KSSJDMC` (type), `XNXQMC` (semester).

**Note:** Returns the active semester only. Body `xn`/`xq` params are accepted but ignored.

Access: ✅ Student

```python
from sustech_survival.tis.exams import run

run()                # display exam schedule
run(export='csv')    # export to CSV
```

---

## Campus-wide Course Schedule (全校课表)

```
POST https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList
Content-Type: application/x-www-form-urlencoded

Form data:
  p_xn=2025-2026         academic year
  p_xq=2                 semester (1=fall, 2=spring)
  p_chaxunpylx=         cultivation type filter:
                          ''     = default filtered view (~188/sem)
                          '1'    = undergrad only (~1200/sem for Spr2026)
                          '2'    = grad only (~445/sem)
                          '3'    = full campus list (1488 for Spr2026, paginate)
  p_xiaoqu=             campus ("一期校区", "二期校区", etc.)
  p_kkyx=               college code
  p_kclb=               course category code (from queryKclb)
  p_kcxz=               course nature ("必修", "选修")
  p_gjz=                keyword search
  p_rwlx=               task type
  pageNum=1
  pageSize=500          max per page; use full=True in code to auto-paginate
```

Returns: `{total: N, pageSize: 500, rwList: {list: [courses]}}`

Key course fields:
- `kcmc` / `kcmc_en` — course name (Chinese / English)
- `kcdm` — course code (e.g. MSE306)
- `kkyxmc` — college/department
- `dgjsmc` — instructor
- `sksj` — time slots (e.g. "1-15周,星期三第3-4节")
- `xf` — credits
- `kclbmc` — category (培养环节, 专业基础课, 专业必修课, etc.)
- `kcxzmc` — nature (必修/选修)
- `xiaoqumc` — campus
- `nj` — grade level
- `pylx` — student type (1=undergrad, 2=grad)

```python
from sustech_survival.tis.campus_schedule import get_campus_schedule, get_semester_courses

courses = get_semester_courses(semester="2025-2026-2", full=True)
```

---

## Course Category Tree (培养环节 etc.)

```
POST https://tis.sustech.edu.cn/component/queryKclb
Content-Type: application/json

Body: {}
```
Returns: 26-node category hierarchy. Top-level categories:

| Code | Name | Subcategories |
|---|---|---|
| 01 | 培养环节 | 劳动教育, 军事理论, 创业创新, ... |
| 03 | 专业基础课 | (理科大类, 工科大类 etc.) |
| 04 | 专业必修课 | |
| 05 | 专业选修课 | |
| 06 | 专业核心课 | |
| 07 | 通识必修课 | 思政类, 体育类, 外语类, 军理类, 计算机类 |
| 08 | 通识选修课 | 人文类, 社科类, 艺术类, 生命健康类, 工程认证类 |

Access: ✅ Student

---

## Timetable Conflict Solver

Given a list of course codes, finds all non-conflicting section combinations for a semester.

### Usage

```bash
python -m sustech_survival.tis.timetable MSE306 MSE202 MSE210 --max 5
python -m sustech_survival.tis.timetable MSE306 EAP --exclude SS143 --semester 2025-2026-2
```

**Flags:**
- `--exclude CODE` — remove a course from the search (e.g. already taken)
- `--codes-file F` — read course codes from file (one per line)
- `--semester Y-Q` — academic year and quarter (default: 2025-2026-2)
- `--max N` — max schedules to show (default: 100)
- `--json` — output as JSON

### How it works

1. Authenticates via `TISAuth().ensure()`
2. For each course code, queries `POST /Xsxktz/queryRwxxcxList` with `p_gjz=<code>` + `p_chaxunpylx=1` (undergrad)
3. Parses `pkjgmx_en` HTML field — extracts plain text from `<p>` tags, then regex-matches English slot format: `1-15单Week,Mon. 5-6 一教321`
4. Backtracking solver: tries all combinations, skips any with time slot conflicts
5. Renders ASCII grid or JSON

### Slot format (pkjgmx_en English HTML)

```
1-15单Week,Mon. 5-6 一教321
1-9,11,13-15Week,Wed. 5-6 一教321
10Week,Wed. 5-6 分析测试中心109实验室
```

Regex: `(\d[\d,-]+)(单|双)?Week,(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.? (\d+-\d+|\d+) (.+)`

---

## Blocked (FineReport — browser-only)

These pages render entirely in-browser via FineReport JS. No REST equivalent found.

| Page | URL | Contains |
|---|---|---|
| 学业修读情况 | `/browserRedirect/queryReport?viewlet=byyt/xsxy/学业修读情况.cpt` | Per-category credit totals |
| 培养方案 | `/browserRedirect/queryReport?viewlet=byyt/pyfa/培养方案.cpt` | Curriculum requirements |
| 学分绩查询 | `/cjgl/xscjgl/xsgrcjcx/xspjxfjcx` | GPA details |

Access: ❌ CLI (browser-only)

---

## See also

- [SSO](sso.md) — credential setup and auth infrastructure
- [Courses](courses.md) — enrolled course data fields
- [Grades](grades.md) — grade records and GPA calculation
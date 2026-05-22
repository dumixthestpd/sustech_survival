# TIS (Teaching Information System)

教学信息管理系统 — exam schedule, grades, course info, campus schedule, **timetable solver**.

**Auth:** CAS session (`route` + `JSESSIONID` cookies). Login → redirect ticket exchange.

**⚠️ Access levels:** Student (学生（本）) vs teacher. Some endpoints are 403 for students.

---

## Login (CAS SSO — Python requests, no browser)

**3-step ticket exchange:**
```python
import requests, re

CAS  = "https://cas.sustech.edu.cn"
TIS  = "https://tis.sustech.edu.cn"
SVC  = f"{TIS}/cas"   # service URL — MUST match exactly

s = requests.Session()
headers = {"User-Agent": "Mozilla/5.0 ..."}

# 1. GET login page → captures TGC cookie + execution token
r = s.get(f"{CAS}/cas/login", params={"service": SVC},
          headers=headers, allow_redirects=False)
exec_token = re.search(r'name="execution" value="([^"]+)"', r.text).group(1)

# 2. POST credentials → returns Location: .../cas?ticket=ST-...
r = s.post(f"{CAS}/cas/login",
           params={"service": SVC},   # CAS needs this on POST too
           data={"username": SID, "password": PASS,
                 "execution": exec_token, "_eventId": "submit"},
           headers={**headers, "Referer": f"{CAS}/cas/login"},
           allow_redirects=False)
ticket = re.search(r"ticket=(ST-[^&]+)", r.headers["Location"]).group(1)

# 3. Exchange ticket → sets JSESSIONID + route cookies
s.get(f"{SVC}?ticket={ticket}", headers=headers, allow_redirects=False)

# Session now has: TGC (step1) + JSESSIONID (step3) + route (step3)
# TIS API calls work directly:
s.post(f"{TIS}/Xsxktz/queryRwxxcxList", data={...})
```

**Key mistakes that break it:**
- `allow_redirects=True` (default) — loses the `Set-Cookie` header with `JSESSIONID`
- Wrong `service=` URL — must be exactly `https://tis.sustech.edu.cn/cas`
- Omitting `params={"service": SVC}` on the POST — CAS validates it against the ticket

---

## Quick Status Check

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -b "route=<ROUTE>; JSESSIONID=<JSESSIONID>" \
  https://tis.sustech.edu.cn/user/me
# 200 = logged in, 401/302 = session expired
```

---

## User Profile

```
GET https://tis.sustech.edu.cn/user/me
Cookie: route=<val>; JSESSIONID=<val>
```
Returns: `studentId`, `id` (internal), `name`, `department`, `pylx` (student type), 50+ auth codes.
Access: ✅ Student

---

## Grades

```
POST https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {"xn":null,"xq":null,"kcmc":null,"cxbj":"-1","pylx":"1","current":1,"pageSize":500}
```
Returns: `content.list[]` with `kcmc`, `kcmc_en`, `kcdm`, `xscj` (letter grade), `zzcj` (numeric score), `xf` (credits), `xnxqmc` (semester), `kcxz` (nature), `yxmc` (department).
Access: ✅ Student

GPA is calculated using SUSTech's official 4.0 scale. Run via:
```bash
python3 src/sustech_survival/tis/grades.py          # display
python3 src/sustech_survival/tis/grades.py --csv   # export CSV
```

---

## Exam Schedule

```
POST https://tis.sustech.edu.cn/component/queryKsxxByXs
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {}
```
Returns: current semester exam entries. Key fields: `KCMC` (course), `KCDM` (code), `KSRQ` (date), `KSJTSJ` (time), `JXLMC` (building), `JXCDMC` (room), `XQJMC` (weekday), `KSSJDMC` (type), `XNXQMC` (semester).

**Note:** Returns the active semester only. Body `xn`/`xq` params are accepted but ignored. Fall 2026 exams are not in the system until that term is active.
Access: ✅ Student

Run via:
```bash
python3 src/sustech_survival/tis/exams.py          # display
python3 src/sustech_survival/tis/exams.py --csv   # export CSV
```

---

## Campus-wide Course Schedule (全校课表)

```
POST https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList
Content-Type: application/x-www-form-urlencoded
Cookie: route=<val>; JSESSIONID=<val>

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
- `kclbmc` — category (培养环节, 专业基础课, 专业必修课, 专业选修课, 通识必修课, 通识选修课, etc.)
- `kcxzmc` — nature (必修/选修)
- `xiaoqumc` — campus
- `nj` — grade level (undergrad/grad)
- `pylx` — student type (1=undergrad, 2=grad)

Semesters: `xn=2025-2026&q=2` = Spring 2026, `xn=2025-2026&q=1` = Fall 2025.
Access: ✅ Student

Run via:
```bash
python3 src/sustech_survival/tis/campus_schedule.py --semester 2025-2026-2 --full
# --json for JSON output, --csv for CSV
```

---

## Course Category Tree (培养环节 etc.)

```
POST https://tis.sustech.edu.cn/component/queryKclb
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

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

**Note:** This is a classification tree only. It does NOT return course lists. Use 全校课表 with `p_kclb` filter to get courses in a specific category.
Access: ✅ Student

---

## Menu Feature Discovery

Use this to find new endpoints before they are documented:

```
POST https://tis.sustech.edu.cn/user/mk
Body (form): {}  → top-level categories

POST https://tis.sustech.edu.cn/user/getMknodeMore
Body (form): mkdm[]=002&mkdm[]=102&mkdm[]=007&mkdm[]=16
→ all 27 feature items with `text` (name) and `url` (route)
```

Access: ✅ Student

---

## Blocked (FineReport — browser-only)

These pages render entirely in-browser via FineReport JS. No REST equivalent found.

| Page | URL | Contains |
|---|---|---|
| 学业修读情况 | `/browserRedirect/queryReport?viewlet=byyt/xsxy/学业修读情况.cpt` | Per-category credit totals (earned vs. required) |
| 培养方案 | `/browserRedirect/queryReport?viewlet=byyt/pyfa/培养方案.cpt` | Curriculum requirements |
| 学分绩查询 | `/cjgl/xscjgl/xsgrcjcx/xspjxfjcx` | GPA details |

The FineReport server is at `/webroot/decision/view/report` but `op=fs/load/execute` all return "Unresolvable Operation". Data loads client-side via FineReport's proprietary AJAX protocol.
Access: ❌ CLI (browser-only)

---

## Building a Curriculum Todo List

What's available:
1. **全校课表** → all courses with `kclbmc` (category) + `kcxzmc` (nature) + `xf` (credits)
2. **queryKclb** → category tree with codes
3. **Your grades** → courses you've already taken

What's missing:
- **Credit minimums per category** — the 培养方案 requirements. Source options:
  - 教务处 website (currently unreachable from this network)
  - FineReport 学业修读情况 (browser-only)
  - Manual input from student handbook

For 通识通修 specifically: the category tree shows 思政类, 体育类, 外语类, 军理类 under 通识必修课 (07). Cross-reference your grades against these categories to find missing courses.

---

## Timetable Conflict Solver

**Module:** `src/sustech_survival/tis/timetable.py`

Given a list of course codes, finds all non-conflicting section combinations for a semester.

### Usage

```bash
python3 src/sustech_survival/tis/timetable.py MSE306 MSE202 MSE210 --max 5
python3 src/sustech_survival/tis/timetable.py MSE306 EAP --exclude SS143 --semester 2025-2026-2
python3 src/sustech_survival/tis/timetable.py --codes-file my_courses.txt --json
```

**Flags:**
- `--exclude CODE` — remove a course from the search (e.g. already taken)
- `--codes-file F` — read course codes from file (one per line)
- `--semester Y-Q` — academic year and quarter (default: 2025-2026-2)
- `--max N` — max schedules to show (default: 100)
- `--json` — output as JSON

### How it works

1. Logs in via CAS (reads `credentials.txt`)
2. For each course code, queries `POST /Xsxktz/queryRwxxcxList` with `p_gjz=<code>` + `p_chaxunpylx=1` (undergrad)
3. Parses `pkjgmx_en` HTML field — extracts plain text from `<p>` tags, then regex-matches English slot format: `1-15单Week,Mon. 5-6 一教321`
4. Backtracking solver: tries all combinations, skips any with time slot conflicts (same day + overlapping weeks + shared periods)
5. Renders ASCII grid or JSON

### Slot format (pkjgmx_en English HTML)

```
1-15单Week,Mon. 5-6 一教321
1-9,11,13-15Week,Wed. 5-6 一教321
10Week,Wed. 5-6 分析测试中心109实验室
13Week,Sat. 3-4 一教321
```

Regex: `(\d[\d,-]+)(单|双)?Week,(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.? (\d+-\d+|\d+) (.+)`

Note: 单 (odd weeks) and 双 (even weeks) are embedded in the weeks string, not a separate group.

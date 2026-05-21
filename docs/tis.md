# TIS (Teaching Information System)

教学信息管理系统 — exam schedule, grades, course info.

**⚠️ Access levels:** Student account (学生（本）) vs Teacher account. Some endpoints return 403 for students.

---

## Access Denied / Unavailable

These paths exist in the frontend JS but return 403 or empty for student accounts — they are teacher-only or require additional auth:

| Endpoint | Status | Reason |
|----------|--------|--------|
| `POST /kscxtj/queryJkcxByXh` | 403 Forbidden | Invigilation schedule (教师) |
| `POST /kscxtj/queryJskccxByXh` | 403 Forbidden | Unknown (教师) |
| `POST /component/queryJsKsxxcxList` | 200, empty | Unknown (教师) |
| `POST /kscxtj/queryXskscxByXh` | 200, empty | Not implemented (no data) |
| `POST /ksgl/*` | 404 | Exam management module not accessible via REST |
| `POST /kscx/*` | 404 | Exam query module not accessible via REST |
| `POST /xsgrkb/*` | 404 | Personal schedule module not accessible via REST |
| `GET /student_index` | 200, HTML only | Iframe shell — actual data loaded inside browser Vue app |

## Quick Status Check

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -b "route=<ROUTE>; JSESSIONID=<JSESSIONID>" \
  https://tis.sustech.edu.cn/user/me
# 200 = logged in, 401/302 = not logged in
```

---

## Known APIs (Student Access ✅)

### User Profile
```
GET https://tis.sustech.edu.cn/user/me
```
Returns: student ID, name, department, role, 50+ authority codes.
Access: ✅ Student

### Grades
```
POST https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {"xn":null,"xq":null,"kcmc":null,"cxbj":"-1","pylx":"1","current":1,"pageSize":500}
```
Returns: list of grade records with `kcmc` (course), `xscj` (letter grade), `zzcj` (numeric score), `xf` (credits), `xnxqmc` (semester).
Access: ✅ Student

### Exam Schedule
```
POST https://tis.sustech.edu.cn/component/queryKsxxByXs
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {}
```
Returns: JSON array of exam entries. Key fields: `KCMC` (course), `KCDM` (code), `KSRQ` (date), `KSJTSJ` (time), `JXLMC` (building), `JXCDMC` (room), `XQJMC` (weekday), `KSSJDMC` (type), `XNXQMC` (semester).
**Note:** Returns the CURRENT semester's exams only. The `xn`/`xq` body params are accepted but ignored — the system always reads the active semester from the session. Fall 2026 exams are not available until that term is active in the system.
Access: ✅ Student

### Campus-wide Course Schedule (全校课表)
```
POST https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList
Content-Type: application/x-www-form-urlencoded
Cookie: route=<val>; JSESSIONID=<val>

Body (form data):
  p_xn=2025-2026    academic year
  p_xq=2            semester (1=fall, 2=spring)
  p_chaxunpylx=     cultivation type filter: ''=default filtered (~188/sem), '1'=undergrad (~1200/sem), '2'=grad (~445/sem), '3'=both+all history (1488 total, ignores xn/xq)
  p_xiaoqu=         campus filter ("一期校区", "二期校区", etc.)
  p_kkyx=           college code
  p_kclb=           course category code (from queryKclb)
  p_kcxz=           course nature ("必修", "选修")
  p_gjz=            keyword search (course name)
  p_rwlx=           task type
  pageNum=1
  pageSize=500
```
Returns: `{total: N, pageSize: 500, rwList: {list: [courses]}}`
Key course fields: `kcmc` (name), `kcmc_en`, `kcdm` (code), `kkyxmc` (college), `dgjsmc` (instructor), `kcxx` (HTML schedule), `xf` (credits), `kclbmc` (category), `kcxzmc` (nature), `xiaoqumc` (campus), `sksj` (time slots), `nj` (grade), `zrl` (enrollment cap), `pkjgmx` (HTML schedule detail).
**Semesters:** `xn=2025-2026&xq=2` → Spring 2026 (current), `xn=2025-2026&xq=1` → Fall 2025.
Access: ✅ Student

### Course Category Tree (培养环节 etc.)
```
POST https://tis.sustech.edu.cn/component/queryKclb
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {}
```
Returns: 26-node category hierarchy (培养环节, 专业基础课, 专业必修课, etc. with subcategories like 人文类, 社科类, 艺术类). No actual course list — classification only.
Access: ✅ Student

### Available Menu Features
```
POST https://tis.sustech.edu.cn/user/mk
POST https://tis.sustech.edu.cn/user/getMknodeMore
```
`/user/mk` → top-level categories (业务查询, 业务办理, 选课业务).
`/getMknodeMore` with `mkdm[]=002&mkdm[]=102&mkdm[]=007&mkdm[]=16` → all feature items with their `url`, `qxdm`, `jsdm`. Use this to discover new REST endpoints.
Access: ✅ Student

### Login
```
POST https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2Ftis.sustech.edu.cn%2Fcas
Body: username=<sid>&password=<pass>&execution=<token>&_eventId=submit
```
Exchange the resulting ticket at the `Location` header to get `route` and `JSESSIONID` cookies.
Access: ✅ Anyone

---

## Running the Exam Fetcher

```bash
cd ~/.openclaw/skills/sustech_survival
python3 src/sustech_survival/tis/exams.py          # display
python3 src/sustech_survival/tis/exams.py --csv   # export to ~/.openclaw/workspace/sustech/exams.csv
```

---

## Running Grades

```bash
cd ~/.openclaw/skills/sustech_survival
python3 src/sustech_survival/tis/grades.py          # display
python3 src/sustech_survival/tis/grades.py --csv   # export to ~/.openclaw/workspace/sustech/grades.csv
```

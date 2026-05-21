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

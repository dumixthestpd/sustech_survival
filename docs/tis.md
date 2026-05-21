# TIS (Teaching Information System)

教学信息管理系统 — exam schedule, grades, course info.

## Quick Status Check

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -b "route=<ROUTE>; JSESSIONID=<JSESSIONID>" \
  https://tis.sustech.edu.cn/user/me
# 200 = logged in, 401/302 = not logged in
```

---

## Known APIs

### User Profile
```
GET https://tis.sustech.edu.cn/user/me
```
Returns: student ID, name, department, role, 50+ authority codes.

### Grades
```
POST https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {"xn":null,"xq":null,"kcmc":null,"cxbj":"-1","pylx":"1","current":1,"pageSize":500}
```
Returns: list of grade records with `kcmc` (course), `xscj` (letter grade), `zzcj` (numeric score), `xf` (credits), `xnxqmc` (semester).

### Exam Schedule
```
POST https://tis.sustech.edu.cn/component/queryKsxxByXs
Content-Type: application/json
Cookie: route=<val>; JSESSIONID=<val>

Body: {}
```
Returns: JSON array of exam entries. Key fields: `KCMC` (course), `KCDM` (code), `KSRQ` (date), `KSJTSJ` (time), `JXLMC` (building), `JXCDMC` (room), `XQJMC` (weekday), `KSSJDMC` (type), `XNXQMC` (semester).

### Login
```
POST https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2Ftis.sustech.edu.cn%2Fcas
Body: username=<sid>&password=<pass>&execution=<token>&_eventId=submit
```
Exchange the resulting ticket at the `Location` header to get `route` and `JSESSIONID` cookies.

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

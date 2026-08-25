# Selectcourse

TIS course selection — browse course catalog, add/drop, manage cart, export iCal.

**Auth:** `TISAuth` via `sustech_survival.sso`. See [SSO](sso.md).

---

## CLI

```bash
sustech selectcourse list                    # browse catalog (current semester)
sustech selectcourse list "MSE"              # filter by keyword
sustech selectcourse enrolled               # your enrolled courses
```

---

## Python API

```python
from sustech_survival.selectcourse import SelectCourseClient

sc = SelectCourseClient()                      # current semester
courses = sc.list_courses(keyword="MSE")       # browse catalog
enrolled = sc.my_courses()                     # your courses

# Add/drop (destructive — always dry_run first)
# sc.add_to_cart(course_id, class_group="001")
# sc.drop_course(rwh)
```

### iCal Export

```python
from sustech_survival.selectcourse.ical import courses_to_ical
from sustech_survival.semester import Semester

sem = Semester.current()
ics_content = courses_to_ical(sem, cal_name="My Schedule")
```

Also available via the web UI at `GET /api/tis/ical`.
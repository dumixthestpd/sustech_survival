# Blackboard

**What:** SUSTech's LMS — assignment deadlines, file uploads, course materials, announcements.

**Use for:** Checking upcoming due dates before exams, submitting lab reports as PDF, downloading course slides.

**Auth:** CAS tickets (headless, no browser needed for deadlines).

## Module

```python
from sustech_survival.bb import ddl
```

## `ddl(days=7, course_id=None)`

Print upcoming assignment deadlines.

```python
ddl()                    # next 7 days, all 2026 courses
ddl(days=14)             # next 14 days
ddl(course_id='_8053_1') # single course
```

**How it works:** REST API for assignment items + portal page for course IDs (the REST API omits some enrolled courses). Due dates are parsed from item titles (Week N) or body text (每周六晚12点).

**Due date parsing rules:**

| Pattern | Interpretation |
|---------|---------------|
| `第12周` | Spring 2026: Saturday of week 12, 23:59 |
| `Week 12` | Same |
| `每周六晚12点` | Recurring Saturday 23:59 |
| `12月31日 23:59` | Specific date |
| (no date) | Status unknown |

**Active semester courses:** `_8053_1` CLE105, `_8157_1` Mechanics B, `_8221_1` EAP, `_8328_1` GOrganic Exp, `_8343_1` PhyChem Exp

## `BBAuth`

```python
from sustech_survival.bb.session import BBAuth
auth = BBAuth()
auth.check()    # (bool, str)
auth.login()    # headful Playwright CAS login
```

Session saved to `bb/session.json`. Auto-refresh on 401.

## `submit_assignment(file, content_id, course_id)`

Upload a file to a BB assignment.

```python
from sustech_survival.bb.submit import submit_assignment
ok = submit_assignment(
    file='/tmp/report.pdf',
    content_id=490876,
    course_id='_8053_1'
)
```

**BB submit flow (from browser network trace):**

1. `GET /webapps/assignment/uploadAssignment?assignId={id}` — fetch form token
2. `POST /webapps/assignment/uploadAssignment` — multipart upload: `patchType=part_upload`, `attempt_number=1`, `倍数=1`, `submit`, ` Plumlof`
3. BB returns confirmation HTML

**File input workaround:** `page.set_input_files()` won't trigger JS handlers. Use `page.evaluate()` to directly manipulate `input.files` and `dispatchEvent(new Event('change', {bubbles:true}))`.

**Known trap:** cloudscraper imported at top of `sso.authlib` → process exits silently. Always verify submission by checking attempt count increased after "success".

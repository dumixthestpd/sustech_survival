# Blackboard

**What:** SUSTech's LMS — assignment deadlines, file uploads, course materials, announcements.

**Use for:** Checking upcoming due dates before exams, submitting lab reports as PDF, downloading course slides.

**Auth:** `BBAuth` — CAS-authenticated session via `sustech_survival.sso`. See [SSO](sso.md) for credential setup.

---

## Authentication

```python
from sustech_survival.sso import BBAuth

auth = BBAuth()               # singleton-per-class
ok, reason = auth.ensure()    # check + auto-refresh if expired
if not ok:
    raise RuntimeError(reason)

# Use the authenticated session
auth.session.get("https://bb.sustech.edu.cn/...")
```

Or with the decorator:

```python
from sustech_survival.sso import require_auth, BBAuth

@require_auth(BBAuth)
def fetch_deadlines(auth=None):
    ...
```

```bash
# CLI — verify and manage the BB session
sustech bb session check      # verify credentials work
sustech bb session refresh    # force re-login
```

Sessions are kept in memory only. Auto-refresh on stale response (HTTP 401).

---

## CLI

```bash
sustech bb courses            # list enrolled courses
sustech bb courses --query MSE  # filter by keyword
sustech bb search --course MSE306 --has-attachments  # find attachments
sustech bb types              # list content types per course
```

---

## Deadlines

```python
from sustech_survival.bb import ddl

ddl()                    # next 7 days, all courses
ddl(days=14)             # next 14 days
ddl(course_id='_8053_1') # single course
```

**How it works:** REST API for assignment items + portal page for course IDs. Due dates are parsed from item titles (Week N) or body text (每周六晚12点).

**Due date parsing rules:**

| Pattern | Interpretation |
|---------|---------------|
| `第12周` | Spring 2026: Saturday of week 12, 23:59 |
| `Week 12` | Same |
| `每周六晚12点` | Recurring Saturday 23:59 |
| `12月31日 23:59` | Specific date |
| (no date) | Status unknown |

**Active semester courses:** Course IDs are internal BB IDs — use `sustech bb courses` to list yours.

---

## File Submission

The submitter is pure REST (no browser). `bb.submit` (formerly the
Playwright submitter) now hosts the REST path:

```python
from sustech_survival.bb.submit import submit_assignment_rest

submit_assignment_rest(
    course_id='_8053_1',
    content_id='490876',
    file_path='/tmp/report.pdf',
)
```

The legacy-signature wrapper (accepts a list of paths; only the first file
is submitted via REST) and the `submit_file(content_id, file_path)` helper
remain available:

```python
from sustech_survival.bb.submit import submit_assignment, submit_file

submit_assignment(
    course_id='_8053_1',
    content_id='490876',
    file_paths=['/tmp/report.pdf'],
)
ok, msg = submit_file('490876', '/tmp/report.pdf')  # auto-resolves course
```

**⚠️ Always verify submission by checking attempt count increased after "success".**

---

## Download

```python
from sustech_survival.bb.download import download_content

download_content(content_id='_12345_1', out_dir='./downloads')
```

Content file downloads are pure REST. Note: the gradebook REST API does not
expose the URLs of files submitted to an assignment (the old Playwright
scraper was removed), so `download_submission` reports attempts without
downloading files.

---

## See also

- [SSO](sso.md) — credential setup and auth infrastructure
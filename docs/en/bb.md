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
# CLI — auth is automatic (ensure()); diagnose only when something fails
sustech sso check             # verify credentials against CAS
sustech sso creds set         # write / update the credentials file
```

Sessions are kept in memory only. Auto-refresh on stale response (HTTP 401).

---

## CLI

```bash
sustech bb courses            # list enrolled courses (REST, fast)
sustech bb courses --query MSE  # filter by keyword
sustech bb search --course MSE306 --has-attachments  # find attachments
sustech bb types              # list content types per course
sustech bb page 629844 -c 8534 -v   # items on a BB content page (URL ids stripped)
sustech bb download <content_id> …  # fetch course-material files
sustech bb course <course> assignment <aid> [attempt] [--download]  # submissions
sustech bb submit <content_id> <file> --course <id> --name "<sid>-<name>-…" --yes

# BB content-page URL → command:
#   …/listContent.jsp?course_id=_8534_1&content_id=_629844_1 → sustech bb page 629844 -c 8534
```

---

## Cross-course pending work and submitted grades

```bash
sustech bb pending --json                  # current term, all due dates
sustech bb grades --json                   # own submitted assessment attempts
sustech bb pending --semester '2026-2027-1' --json
sustech bb grades --course 101 --course 102 --json
sustech bb pending --course 101 \
  --due-from '2026-10-07T00:00:00+08:00' \
  --due-until '2026-10-14T23:59:59+08:00' --json
```

Without an explicit scope, these commands read live enrollments and select the
unique BB term whose dated duration contains the query time. `--semester`
(alias `--term`) accepts a BB term ID, name substring or academic code. If the
site has overlapping/missing term dates, specify a semester or course IDs;
the query does not guess a term. Repeated `--course` IDs alone select those
enrolled courses without term inference. Adding `--semester` intersects the
two scopes and reports requested courses outside the term or enrollments.
There is no dependency on a private baseline, local course cache or archive.

`pending` includes overdue and undated work, and distinguishes unsubmitted
assessments from drafts. Optional inclusive due bounds require ISO timestamps
with an offset; applying either bound excludes undated tasks and reports that
window. It reads gradebook columns with `grading.type == Attempts`, content
metadata, the user's grade records (including exemptions) and all own attempts.
For compatibility with SUSTech BB, attempts GETs omit the optional `userId`
query filter, which can return 403 for student sessions. Every returned page
is still checked for attempt ownership and filtered locally to the current
user. Actual permission failures remain errors; there is no automatic retry.
Ordinary assignments and test/assignment links are included with distinct
`kind` labels. A test link is not silently presented as a written assignment.

Submitted/awaiting-grading tasks are absent from pending. Column exemptions
appear in `excluded`. Group tasks without a personal submission, unsupported
content, explicit notification-only/do-not-submit-here titles and failed
reads appear in `unknown`/`errors`, rather than being declared unsubmitted.
Notification detection recognizes explicit Chinese and English title markers;
it cannot infer every external-platform workflow. Personal deadline extensions,
late-submission access and external/group completion are not independently
verified by this report.

`grades` includes submitted attempt-based assessments, including test-type
items. Each own attempt retains its status, score, creation time and exemption
flag. Zero is valid; missing points remain unknown. `possible` comes from the
column's actual possible points. The separate `grade` field is the column
value reported by BB, labelled `source: gradebook_user_grade`; the client never
computes a highest/latest/average final grade from attempts. Known scores remain
visible if content metadata cannot be read. `InProgressAgain` without a known
submitted attempt stays unconfirmed.

Both commands default to readable text; `--json` writes only a versioned JSON
object to stdout. Authentication diagnostics use stderr. Key fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `mode`, `checked_at`, `timezone` | Schema version 1, view and query time in Asia/Shanghai |
| `scope` | Live source, semester/terms, selected courses, due bounds and whether undated work is included |
| `courses_checked`, `attempt_columns_checked` | Courses with successful column reads and considered assessment columns |
| `items` | Confirmed pending assessments or own submitted assessment attempts |
| `excluded` | Exempt columns excluded from the requested view |
| `unknown` | Scope/task states that cannot be established, with stable reason codes |
| `errors` | Read stage, safe diagnostic, HTTP status when available and endpoint without user identifiers/query values |
| `complete` | True only when `unknown` and `errors` are empty |

Exit status is **0** for a complete report, **1** for partial/failed reads and
**2** for invalid CLI arguments. A status-1 JSON report can contain useful known
items: consume them with the reported gaps. Never treat an incomplete empty
list as evidence that no work remains. No course names, raw authentication
responses or report snapshots are written to disk by these commands.

```python
from sustech_survival.bb.assessments import query

pending = query('pending', semester='2026-2027-1')
grades = query('grades', course_ids=['101', '102'])
# An existing package-authorized requests.Session may be passed as session=.
# All reads within one query share that session; query() itself never POSTs.
if not pending['complete']:
    print(pending['unknown'], pending['errors'])
```

---

## Content discovery and availability

`query.walk_contents()` and `query.discover_pages()` exclude items explicitly
marked `availability.available = "No"`, including their descendants. They do
not request those items' details during broad discovery. `Yes`,
`PartiallyVisible`, or missing availability metadata are still read normally;
these states do not guarantee permission. Direct requests for a specific item
retain normal server-side permission checks.

Each fresh walk reads parent listings again, so newly available folders are
included without relying on `modified` timestamps or a permanent deny list.
`discover_pages()` reports the excluded count on stderr, including cache hits.
Its usual one-hour cache still applies; use `refresh=True` when current
availability is required. Unavailable content is
excluded from totals; a successful read does not establish that the entire
course is accessible.

The walker reuses one session, reads each collection's pagination, rejects
pagination loops and links to other hosts, and reads the root collection only
once. Failed or malformed reads propagate; discovery does not cache a partial
result as an empty or successful listing. Cached listings created before the
availability filter are not reused.

```python
from sustech_survival.bb.query import walk_contents, discover_pages

unavailable = []
rows = list(walk_contents("1234", unavailable=unavailable))
# unavailable contains course/content IDs, titles, and availability_no reasons.
pages = discover_pages("1234", refresh=True)
```

See Blackboard's [REST API best practices](https://docs.blackboard.com/docs/blackboard/rest-apis/rest-api-best-practices)
and [content availability rules](https://help.anthology.com/blackboard/instructor/en/original-course-view/common-questions/common-questions-about-releasing-content.html).

---

## Deadlines

```python
from sustech_survival.bb import ddl

ddl.run()                    # next 7 days, all courses
ddl.run(days=14)             # next 14 days
ddl.run(course_id='_8053_1') # single course
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

Deadline reads inspect complete personal enrollments, with no fixed BB term ID; the date window scopes upcoming work. Attempt reads follow pagination and filter the current user. Failed reads or unknown attempt ownership raise errors. A file comment supplied to `apply_submission()` is sent in the same multipart submission, creating one attempt. CSV/display exports are separate from submission.

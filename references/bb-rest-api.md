# BB REST API Reference

**Discovered:** 2026-05-21. All endpoints work with CAS session cookies via curl/requests — no Playwright needed.

**Auth:** CAS session cookies (`JSESSIONID`, `s_session_id`) from `bb/session.json`.

**Base:** `https://bb.sustech.edu.cn`

---

## Working Endpoints

### Courses
```
GET /learn/api/public/v1/courses
  → JSON array of all courses (name, id, termId, availability)
  → Filter by term: ?termId=_57_1 (Spring 2026)

GET /learn/api/public/v1/courses/{id}
  → Single course details (name, enrollment type, locale)

GET /learn/api/public/v1/courses/{id}/contents
  → Content tree (folders, files, assignments)
  → ?_fields=id,title,contentHandler,hasChildren  (lighter)

GET /learn/api/public/v1/courses/{id}/contents/{contentId}
  → Single content item (body text, instructions, handler type)

GET /learn/api/public/v1/courses/{id}/contents/{contentId}/children
  → Nested items inside folders (e.g., assignment inside report folder)
```

### Users
```
GET /learn/api/public/v1/users/me
  → Current user (student ID, name, roles, email)
```

### Gradebook (DUE DATES — replaces Playwright ddl.py)
```
GET /learn/api/public/v1/courses/{id}/gradebook/columns
  → All assignments with:
    - id, name
    - contentId (maps to content item)
    - score.possible (max points)
    - grading.type ("Attempts")
    - grading.due (ISO timestamp — e.g. "2026-03-25T15:59:00.000Z")
    - grading.attemptsAllowed, grading.scoringModel

GET /learn/api/public/v1/courses/{id}/gradebook/columns/{columnId}/attempts
  → Student-specific attempts:
    - id (attempt ID), userId, status, score, feedback, created
```

---

## Still Requires Playwright

### Assignment submission
- `POST /webapps/assignment/uploadAssignment` — requires JS-rendered form
- BB form fields loaded dynamically; static HTML has no `<form>` tag
- No REST submission endpoint found

### File download (current workaround)
- `download.py` uses Playwright to navigate `listContent.jsp` and scrape file URLs
- Then uses `requests.get()` for actual download (already curl-friendly)
- **TODO:** Replace Playwright navigation with `/contents/{id}/children` → find `resource/x-bb-file` → extract download URL

---

## Content Handler Types
- `resource/x-bb-folder` — folder (check `/children`)
- `resource/x-bb-file` — downloadable file
- `resource/x-bb-assignment` — assignment item (has due date in gradebook)

## Known Content IDs (PhysChem Exp, course _8343_1)
| Content ID | Type | Name |
|------------|------|------|
| _612342_1 | assignment | Experiment 1- Report (Combustion) |
| _612344_1 | assignment | Experiment 2- Report (Rotation) |
| _612345_1 | assignment | Experiment 3- Report (Binary) |
| _611414_1 | folder | Experiment 1-Report (Combustion) folder |

---

## User Info (me)
- userId: `_70745_1`
- studentId: `12413021`
- name: 段斯宸(Duan Sichen)
- role: STUDENT

## Spring 2026 Courses (all)
| Course ID | courseId | Name |
|-----------|----------|------|
| _8157_1 | CLE030-30000212-2026SP | EAP Spring 2026 |
| _8053_1 | ... | CAD与工程制图 |
| _8328_1 | ... | 基础有机化学实验 |
| _8343_1 | ... | Physical Chemistry Exp |

---

## Next Steps
1. **Rewrite `ddl.py`**: Use `/gradebook/columns` instead of REST API + portal scraping
   - No Playwright needed for due dates
   - Reliable ISO timestamps instead of regex-parsed "Week N"
2. **Rewrite `query.py`**: Use `/contents/{id}/children` for content discovery
   - Already Playwright-free for content discovery
   - Still uses Playwright for `discover_pages` (sidebar only)
3. **Submit**: No viable curl path — form requires JS rendering
4. **Grade check**: `/gradebook/columns/{id}/attempts` gives actual scores + feedback

---
name: faculty
description: Live SUSTech faculty directory (faculty.sustech.edu.cn) — list, search, fetch profiles. 0 local data. Submodule of sustech_survival.
owner: Faux
category: sustech
last_updated: 2026-06-11
parent: sustech_survival
---

# faculty — Live SUSTech Faculty Directory

Live query of `https://faculty.sustech.edu.cn`. **0 local data** — every call
hits the live site. Polite (5 concurrent workers, 0.2s spacing).

## Source

| | |
|---|---|
| Base | `https://faculty.sustech.edu.cn` |
| Index | `GET /index.php?ajax=users&page=N&field=<dept>&lang=zh` |
| Profile | `GET /?tagid=<slug>&lang=zh&go=2` |
| Theme | WordPress + custom theme `nkdgrzy` |
| Auth | **none** — public |

The site's own `?search=` form is broken (the AJAX listing ignores the
search term). All search is done client-side after listing.

## API — one class, four operations

```python
from sustech_survival.faculty import faculty, Faculty

# list faculty in a department
cards = faculty.list("材料科学与工程系")                    # lightweight
full  = faculty.list("材料科学与工程系", full=True)         # with research_interests

# one profile
chengc = faculty.get("chengc")
print(chengc.to_markdown())                              # AI-readable

# live keyword search (fetches profiles in parallel as needed)
hits = faculty.search("电池", dept="材料科学与工程系", limit=5)
for f in hits:
    print(f"  {f.name}  score={f.relevance_score}  matched={f.matched_fields}")

# 50+ department names
print(faculty.departments)
```

Each `Faculty` returned from `search()` carries:
- `.relevance_score: int` — weighted match score
- `.matched_fields: list[str]` — which fields hit (`name`, `title`, `research_interests`, etc.)

## Architecture (object-oriented)

| File | Class | Responsibility |
|------|-------|----------------|
| `schema.py` | `IndexCard` | lightweight record; `IndexCard.list_from_index_html(html)` → `list[IndexCard]` |
| `schema.py` | `Faculty` | full record; `Faculty.from_profile_html(html, slug)` and `Faculty.from_index_card(card)` |
| `faculty.py` | `FacultyClient` | session, list/get/search/render + private HTTP + scoring |
| `faculty.py` | `faculty` | module-level singleton instance |
| `__main__.py` | (CLI) | thin wrappers over `faculty.<method>` |

No loose functions. Parsing lives ON the data classes (classmethods).
All I/O lives on `FacultyClient`. Module exports just the singleton +
the two record types.

## CLI

```bash
cd ~/.openclaw/code/sustech_survival
PYTHONPATH=src python -m sustech_survival.faculty <cmd>

Commands:
  depts                          # 50+ department names
  list    <dept> [--full]        # list faculty (--full = with research_interests, ~30-70s)
  get     <slug> [--json]        # one profile
  search  <query> [--dept D]     # live keyword search
  render  <slug>                 # AI-readable Markdown
```

## Custom client (advanced)

```python
from sustech_survival.faculty import FacultyClient

# Tighter rate limits
slow = FacultyClient(delay=1.0, workers=2)
hits = slow.search("...", dept="...", limit=5)

# Or for parallel callers, make your own instance
my = FacultyClient(delay=0.5, workers=10)
chengc = my.get("chengc")
```

## Performance

| Operation | Time | Notes |
|-----------|------|-------|
| `list(dept)` (60 faculty, lightweight) | ~16s | 3 pages × 5s/req |
| `get(slug)` (1 profile) | ~2.2s | single GET, ~30KB HTML |
| `list(dept, full=True)` (60 full profiles) | ~30s | 60 fetches at 5 workers |
| `search` in 1 dept | ~30-90s | depends on match count |
| `search` across all 50+ depts | ~10 min | card prefilter narrows to candidates first |

## What this fetches

Per profile, the parser extracts:
- name (h2.t_name), title (em.t_zw), department (span.t_xy)
- email, phone, office address (footer contact area)
- ResearcherID + Google Scholar links
- biography (`.t_descs` — prose intro)
- structured `个人简介` sections: 教育经历 / 工作经历 / 目前研究兴趣 / 人才获奖荣誉
- photo URL (dt.bgimgdt or img.opavatarimg)

## What this does NOT do

- No auth (the site is public)
- No local cache (every call is live — explicit requirement)
- No history tracking, no notifications
- Doesn't fetch 科研项目 / 学术成果 / 教学 tabs (raw HTML not stored)

## Caveats

- **Site changes will break parsers.** Selectors are tied to the `nkdgrzy` WordPress theme.
- **Some profiles are empty.** Not all faculty have filled in their pages.
- **Slugs are WordPress usernames, not stable.**
- **No `name_en` field yet.** English names go into `Faculty.other` if extracted.

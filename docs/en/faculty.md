# Faculty

SUSTech faculty directory — 50+ departments, listing, full-text search, profile lookup.

**Auth:** None (public endpoint at `faculty.sustech.edu.cn`).

---

## CLI

```bash
sustech faculty depts                  # list all departments
sustech faculty list 材料科学与工程系    # list faculty in a department
sustech faculty list 材料科学与工程系 --full  # fetch full profiles (slower)
sustech faculty get zhang-san           # fetch one profile by slug
sustech faculty search "electrochromic" # keyword search
sustech faculty render zhang-san        # AI-readable Markdown profile
```

---

## Python API

```python
from sustech_survival.faculty import faculty

depts = faculty.departments         # list of 50+ department names
rows = faculty.list("材料科学与工程系", full=False, limit=10)
f = faculty.get("zhang-san")        # full profile
hits = faculty.search("polymer", dept="材料科学与工程系", limit=10)
md = faculty.render("zhang-san")    # Markdown rendering
```
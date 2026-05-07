# SUSTech Library Search

Research method + database guide for SUSTech students.

## Login

**Python (recommended):**
```bash
cd ~/.openclaw/workspace/skills/sustech_survival/lib
python3 login.py
```
Reads credentials from `sustech_survival/credentials.txt`.

**Shell fallback:**
```bash
./login.sh
```

## Python API

```python
from sustech_survival import lib

lib.login()           # CAS login via Playwright / requests
lib.check()           # check session validity
lib.refresh()        # re-auth via requests
lib.ensure()         # check + auto-refresh
```

## Databases

Go to: `https://lib.sustech.edu.cn/sjk/` — 166 databases searchable A-Z.

| Database | URL |
|----------|-----|
| Web of Science | webofscience.com |
| Scopus | scopus.com |
| CNKI | cnki.net |
| PubMed | pubmed.ncbi.nlm.nih.gov |

**Off-campus?** → `lib.sustech.edu.cn` → 校外访问

## 4-Step Research Method

### Step 1 — Understand your topic
What are the core concepts? What's the research question asking?

### Step 2 — List synonyms
- `"dark humor"` → gallows humor, morbid humor, offensive humor
- `censorship` → prohibition, regulation, restriction

### Step 3 — Build the search
Use boolean:
```
("dark humor" OR "gallows humor") AND (death OR war) AND censorship
```

### Step 4 — Pick a database
- **Science/Engineering** → Web of Science
- **Broad coverage** → Scopus
- **Chinese sources** → CNKI

## Citation Management

Use **NoteExpress** (SUSTech site license) for citation management.

## Getting Help

- Library guides: `https://lib.sustech.edu.cn`
- Research methodology: Ask the AI for search strategy help

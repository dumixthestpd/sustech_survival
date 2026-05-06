# SUSTech Library Search

Research method + database guide for SUSTech students.

## Login

**Headless (no browser):**
```bash
cd ~/.openclaw/workspace/skills/sustech-survival/sustech-lib-search
python3 login-lib.py
```

Requires `~/.openclaw/workspace/credentials.txt` with your SUSTech CAS credentials (`username:password`).

**Browser relay (manual browsing):**
```bash
openclaw browser --browser-profile openclaw start
# Then open library URL
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

## Example: Dark Humor Research

Search query:
```
("dark humor" OR "gallows humor" OR "offensive humor") AND (death OR tragedy OR war) AND (censorship OR "free speech")
```

WoS: `TS=(dark humor OR gallows humor) AND (death OR war) AND censorship`

## Citation Management

Use **NoteExpress** (SUSTech site license) for citation management.

## Getting Help

- Library guides: `https://lib.sustech.edu.cn`
- Research methodology: Ask the AI (me) for search strategy help

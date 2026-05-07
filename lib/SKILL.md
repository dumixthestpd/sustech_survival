---
name: sustech-lib-search
description: SUSTech library database search assistant. Use when dumix asks to search for articles, find papers, or do research. Also use proactively when a research topic comes up.
---

# SUSTech Library Search

## Quick Start

```bash
# Login (headless CAS)
python3 ~/.openclaw/workspace/skills/sustech-survival/sustech-lib-search/login-lib.py

# Search for articles using WoS or Scopus
# (browser relay or direct database URLs)
```

## Login

**GUI method** (recommended — opens Chrome for manual login):
```bash
python3 login-lib.py
# OR
bash login-lib.sh
```

**Headless CAS** (CAS login only, Primo search may be blocked):
```bash
# CAS login works, but Primo search requires real browser
python3 login-lib.py --headless
```

Requires `~/.openclaw/workspace/credentials.txt` (format: `username:password`). Chrome is recommended for autofill.

## Off-Campus Access (Institutional / SSO Login)

Third-party databases (WoS, Scopus, JSTOR, SAGE, etc.) require **institutional verification** when off-campus. SUSTech uses **Shibboleth/CAS SSO** — the "Login via institution" / "SSO Login" button on database websites.

**The flow:**
1. Go to any database (SAGE, JSTOR, Wiley, etc.)
2. Click **"Login via institution"** or **"Access through your institution"** or **"SSO"**
3. Search for **"Southern University of Science and Technology"** or **"SUSTech"**
4. You get redirected to SUSTech's CAS login — use your SUSTech account
5. Done — database session is now institutional

**Direct link to library off-campus access:** `https://lib.sustech.edu.cn` → 校外访问 (Off-Campus Access)

**Common databases with Shibboleth/SSO:**
- SAGE Journals → "Log in via institution"
- JSTOR → "Institution login"
- Wiley → "Access through your institution"
- Taylor & Francis → "Login via Shibboleth"
- Springer → "Sign via institution"
- IEEE → "IEEE member login" (or Shibboleth)
- Elsevier (ScienceDirect) → institutional IP or "Other institution"

If Primo search is blocked (headless CAS limitation), use the browser relay method:
```bash
python3 login-lib.py --browser-profile openclaw
```
Or manually: `https://lib.sustech.edu.cn` → Collections → your database → Shibboleth login.

## 4-Step Research Method

**Step 1 — Understand the topic**
Identify 2-4 core concepts in the research question.

**Step 2 — List synonyms**
Alternative terms, broader/narrower concepts, related words.

**Step 3 — Build the query**
Boolean operators:
- `AND` — narrow (both terms required)
- `OR` — broaden (either term)
- `NOT` — exclude
- `"..."` — exact phrase
- `*` — truncation (word stem)
- `( )` — group/prioritize

**Step 4 — Select the database**
See `references/DATABASES.md`.

## Database Selection

| Database | Best for |
|----------|---------|
| **Web of Science** | Science, citation tracking |
| **Scopus** | Multi-disciplinary, broad coverage |
| **CNKI** | Chinese academic sources |
| **NoteExpress** | Citation management |

See `references/DATABASES.md` for full guidance.

## Query Examples

**Dark humor + censorship:**
```
("dark humor" OR "gallows humor" OR "offensive humor")
AND (death OR tragedy OR war)
AND (censorship OR "free speech" OR regulation)
```

**WoS (TS=topic):**
```
TS=(dark humor OR gallows humor) AND (death OR war) AND (censorship OR "free speech")
```

**Scopus (TITLE-ABS-KEY):**
```
TITLE-ABS-KEY(dark AND humor AND censorship)
```

## Trigger

When dumix gives a research topic → apply the 4-step method immediately. Build the query and offer to search.

## Browser Relay

Browser relay can be used for manual database browsing (OpenClaw managed browser, `--browser-profile openclaw`). Use it when:
- Need to click through database UI
- Need to read search results from rendered pages

Do NOT detail specific browser relay commands in AI-facing docs.

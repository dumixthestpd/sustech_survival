# personal.example.md

This file is a **template** — copy it to `personal.md` and fill in your own data.

## Purpose

`personal.md` is **gitignored** and stores:
- Course-specific resources (per-semester, per-course)
- Personal file locations on this device
- Credentials that this skill needs to run
- Anything too device-specific or private to share

## Copy this file to personal.md and fill in:

```bash
cp personal.example.md personal.md
```

## What's in here

| Section | What's stored |
|---------|---------------|
| **Course-specific resources** | Lab report templates, EAP files — tied to a specific semester/course |
| **Personal file arrangement** | Where your actual data lives on this device vs. the canonical paths |
| **Credentials** | BB/TIS login credentials for this device |

## Template Content (copy to personal.md)

```markdown
# personal.md — SUSTech Survival: Personal / Device-Specific Data
# This file is gitignored — do NOT commit real credentials or paths

## Course-Specific Resources (Spring 2026)

| Course | Resource | Path |
|--------|----------|------|
| Physical Chemistry Experiments | Lab report template | ~/.openclaw/workspace/sustech/26spring/PhyChemExp/template/ |
| General Organic Chemistry Experiments | Template | ~/.openclaw/workspace/sustech/26spring/GOrganicExp/template/ |
| EAP | Research files | ~/.openclaw/workspace/sustech/26spring/eap/ |

## Personal File Arrangement

| Data | Canonical Path | Local Path (this device) |
|------|----------------|--------------------------|
| SUSTech data root | ~/.openclaw/workspace/sustech/ | ~/Documents/sustech/ |
| Course CSV | ~/.openclaw/workspace/sustech/26spring/courses.csv | ~/Documents/sustech/26spring/courses.csv |
| PhyChemExp data | ~/.openclaw/workspace/sustech/26spring/PhyChemExp/ | ~/Documents/sustech/26spring/PhyChemExp/ |

## Credentials

| System | File |
|--------|------|
| Blackboard | bb/creds.txt (format: username:password) |
| TIS | tis/ credentials via CAS login |
| SUSTech account | credentials.txt in skill root |

## Notes

- courses.csv is fetched from TIS and stored locally
- BB session cookies are stored in bb/session.json (gitignored)
- Calendar sync uses gog — auth is handled separately
```

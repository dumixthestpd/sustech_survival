# Academic Calendar Fetcher

Downloads the public academic calendar PDF from `sustech.edu.cn` and parses it into `semester.json`.

**No AppleScript** — works on macOS, Linux, and Windows.

---

## Commands

```bash
# Download all calendars found on the page
python3 fetch_calendar.py

# Download + parse → writes semester.json
python3 fetch_calendar.py --parse

# Check for updates (don't download)
python3 fetch_calendar.py --check

# Parse the cached PDF without checking for updates
python3 fetch_calendar.py --parse --offline

# Work with a specific year
python3 fetch_calendar.py --year 2026
python3 fetch_calendar.py --year 2026 --parse

# When both 2026 and 2027 appear on the page, fetch all
python3 fetch_calendar.py --all
python3 fetch_calendar.py --all --parse
```

### Flags

| Flag | What it does |
|------|-------------|
| *(none)* | Check for updates, download any new calendars |
| `--parse` | After fetching, parse the PDF and write `semester.json` |
| `--check` | Just report whether updates exist — no download |
| `--offline` | Use only local cache — skip all network calls |
| `--year YYYY` | Target a specific calendar year |
| `--all` | Process every calendar found on the page |

---

## How It Works

1. Fetches `https://www.sustech.edu.cn/zh/academic-calendar.html`
2. Extracts PDF links from the page (handles multiple calendars, e.g. 2026 + 2027 coexist)
3. Downloads PDFs to `~/.openclaw/workspace/sustech/`
4. Parses PDF text → extracts `week_1_monday`, `first_class_day`, `semester_end`, holidays, compensatory days
5. Writes `semester.json`

---

## Requirements

- Python 3.9+
- `requests` (`pip install requests`)
- PDF text extraction (one of):
  - `pdftotext` — from poppler (`brew install poppler`)
  - `pdfminer.six` — `pip install pdfminer.six`

---

## Notes

- The academic calendar is **universal** — the same PDF for all students. It defines when the semester starts, holidays, and makeup days.
- This is **different from TIS**, which has your personal course schedule. See SKILL.md for the distinction.
- PDF text extraction quality varies. Always verify key dates in `semester.json` after parsing.

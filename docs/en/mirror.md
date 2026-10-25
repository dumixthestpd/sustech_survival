# Open-Source Mirror (mirrors.sustech.edu.cn)

The **SUSTech CRA open-source mirror** — official course syllabi, undergraduate
training-program compendia, the campus map, handbooks, and directory listings,
all public and **unauthenticated**. It is the fastest way to answer "what does
this course actually cover?" without finding a syllabus PDF by hand, and it
needs no login.

Content is maintained by SUSTech CRA and published under **CC-BY-SA-4.0**;
keep the attribution when you pass a file on.

**Auth:** none, except `mirror course`, which reads TIS grade history /
catalog metadata and therefore wants a TIS session (see [SSO](sso.md)).

---

## CLI

```bash
sustech mirror syllabus url CSE104        # print URL(s) — no network call
sustech mirror syllabus exists CSE104     # HEAD probe; exit 1 when absent
sustech mirror syllabus get CSE104        # download the PDF(s)
sustech mirror syllabus extract CSE104    # download + extract text (alias: text)
sustech mirror syllabus open CSE104       # open in the default browser
sustech mirror syllabus list-departments  # which departments have syllabi
sustech mirror syllabus batch --semester 2026-2027-1   # whole-term sweep

sustech mirror program years              # which plan years the mirror holds
sustech mirror program url 2024级         # the URL that exists (probes the PDF, then the year dir)
sustech mirror program list 2024级        # the per-major PDFs inside a year directory
sustech mirror program get 2024级         # download it — a directory year takes its 00-通识 plan
sustech mirror program get 2024级 --all   # every major's plan for that year
sustech mirror program get 2024级 --index 19   # just 19-计算机科学与技术专业…

sustech mirror handbook get freshman-2022 # one handbook, by kind
sustech mirror map get                    # the campus map PDF
sustech mirror list /courses              # directory listing (best-effort)
sustech mirror course CSE104              # TIS-backed course metadata
```

Downloads land under `~/.sustech_survival/downloads/` (`syllabus/`, `program/`,
`handbook/`, …) unless `-o/--output` says otherwise; an existing file is left
alone unless `--overwrite` is passed.

**2019–2024级 are directories, not files.** Each holds one PDF per major
(`00-…通识培养方案.pdf`, `01-…金融数学专业…`, …) plus the 通识必修课 requirement
table; only the newest year ships as a single whole-school PDF. So
`program url` probes rather than guesses, `program list` shows what a year
holds, and a bare `program get <year>` takes the `00-通识` plan that anchors the
directory. Every printed URL is percent-encoded — the mirror answers 404 to a
raw UTF-8 path, so an unencoded link works in a browser (which encodes on its
own) but fails in `curl`/`wget`/scripts.

`syllabus batch` walks every code the term's TIS schedule mentions and skips
what is already on disk, so it is safe to re-run; `--dry-run` lists what it
would fetch, `--extract` also stores text.

---

## Python API

```python
from sustech_survival.mirror import (
    MIRROR_BASE, syllabus_url, syllabus_exists, syllabus_fetch,
    syllabus_download, syllabus_extract_text, SyllabusNotFound,
)

syllabus_url("CSE104")                  # no network
syllabus_exists("CSE104")               # HEAD probe → bool
pdf = syllabus_fetch("CSE104")          # bytes (raises SyllabusNotFound)
path = syllabus_download("CSE104", out_dir="downloads")   # writes the PDF
text = syllabus_extract_text("CSE104")
```

`mirror/` also carries `tis_fallback.py`: when a code is not in the mirror, the
TIS catalog answers the same questions (course name, hours, prerequisites) so
callers do not have to special-case the miss.

---

## Same surface in the other lane

The TypeScript CLI (`sustech-cli`, fork) mounts the same family —
`mirror syllabus url|exists|get|text`, `mirror program years|url|list|get`
(also with `--all`/`--index`), `mirror map get`, `mirror handbook get`,
`mirror list`, `mirror course` — and
registers all of them in `capabilities`/`describe` so agents can discover them.
The Python lane additionally has `syllabus open`, `syllabus list-departments`
and `syllabus batch`, plus `mirror course --text/--include-raw`; the TS lane's
`mirror course` takes just the code. Discoveries travel both ways (fork rule),
so keep the two in step.

---

## See also

- [TIS](tis.md) — the schedule that `mirror syllabus batch` walks.
- [Course selection](selectcourse.md) — what to do with a syllabus once read.
- [NCES](nces.md) — community course ratings, the other half of "should I take
  this".

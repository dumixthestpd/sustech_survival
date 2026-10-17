# Contributing to sustech_survival

Mostly maintained by one person. Outside PRs are welcome, reviewed when I have time.

## Where to ask first

- **Bugs and small fixes** → open an issue, then a PR. The template asks which subsystem (`tis` / `bb` / `lib` / …).
- **Larger changes** → open a Discussion (or an issue tagged `proposal`) so the design lands before code does.
- **Usage questions** → Discussions, not issues.

## Languages

- **Issues, PRs, Discussions, commit messages** — English or 中文.
- **`README.md` and `docs/en/*.md`** are the canonical English sources.
  `README_cn.md` and `docs/zh/*.md` are Chinese translations maintained
  alongside.
- **Code (identifiers, comments, docstrings)** — English, ASCII
  identifiers. Chinese domain names get a one-time docstring comment;
  the variable stays English.

To translate a doc page: copy `docs/en/<page>.md` to
`docs/zh/<page>.md`, translate the body, keep the link structure
identical. Open a PR — no prior permission needed.

## Development setup

```bash
git clone https://github.com/dumixthestpd/sustech_survival.git
cd sustech_survival
pip install -e ".[all]"       # or specific extras: [webui] [papers] [nces] …
pytest -m "not live"          # skip tests that need real SUSTech credentials
```

## Code style

- `black` + `isort`, line-length 100 (in `pyproject.toml`).
- Python 3.10+.
- Type hints on new public APIs — the package ships `py.typed`.

## Subsystem-specific docs

Start at `docs/en/index.md` (or `docs/zh/index.md`). It maps each module to a per-subsystem doc. Most non-obvious decisions (CAS auth flow, TIS endpoint quirks, calendar compensatory-day logic, …) live in the relevant `docs/en/<subsystem>.md`. Read that one before changing the corresponding code.

## Pull requests

- One logical change per PR.
- Link the issue or discussion in the description.
- Tests added or updated for any user-visible change.
- User-visible changes get a clear commit-message body and a summary line in
  the working `CHANGELOG.md` (see [Releasing](#releasing)). Shipped release
  notes are written to GitHub Releases at tag time.
- Live tests (`@pytest.mark.live`) are optional — only add them if you can verify against your own SUSTech account.

## Releasing

The version lives in exactly one place — `src/sustech_survival/_version.py`
(`__version__ = "YYYY.M.D"`, CST; dev builds may use `YYYY.M.D.devHHMM`).
Hatchling reads it through `[tool.hatch.version]`, so `pip show
sustech_survival` and `sustech_survival.__version__` always agree.

1. Land the work: `git status -sb` for the working tree and
   `git log --oneline origin/main..main` for commits that are not pushed yet.
2. Bump `_version.py` to today's date.
3. Update the working changelog: turn `## [Unreleased]` in `CHANGELOG.md` into
   `## [YYYY.M.D]`, group entries by module (`bb` / `tis` / `ehall` / …), and
   credit anything adopted from another project (`(approach adopted from
   sustech-cli v0.11.x)`). `CHANGELOG.md` is **gitignored** (`.gitignore` line
   147) — it is a local working file, not shipped. The published notes are the
   body of the GitHub Release for the tag.
4. `git push origin main`
5. `git tag 2026.9.3 && git push --tags` — tags are the **bare version**, no
   `v` prefix.

CI (`.github/workflows/deploy.yml`) runs on **any** tag push. The `build` job
always produces the sdist + wheel; the `pypi` job only runs when the repository
variable `PUBLISH_TO_PYPI` is exactly `true` (OIDC trusted publishing, no
token). The documentation site is a separate `docs.yml` workflow.

Install reality (checked 2026-10-16): the package **is on PyPI**
(`https://pypi.org/project/sustech-survival/`), and releases carry **no
assets** — the sdist/wheel are built by CI, not attached. Users install from
PyPI; git remains the path for tracking `main`:

```bash
# released version
pip install "sustech_survival[webui]"
# update
pip install -U "sustech_survival[webui]"
# unreleased HEAD of main
pip install -U --force-reinstall --no-cache-dir "sustech_survival[webui] @ git+https://github.com/dumixthestpd/sustech_survival.git"
```

A tag reaches PyPI users only when `PUBLISH_TO_PYPI` is `true`; with it unset,
tagging only proves that the release builds.

## Commit messages

English or 中文. Multi-line messages with a body are encouraged for non-trivial changes.

## Security

Auth bypass, credential leak, XSS in the web UI — do not file a public issue. See `SECURITY.md` for a private channel.

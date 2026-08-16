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
- User-visible changes get a clear commit-message body. Release notes are
  written to GitHub Releases at tag time (no in-repo `CHANGELOG.md`;
  see `.gitignore`).
- Live tests (`@pytest.mark.live`) are optional — only add them if you can verify against your own SUSTech account.

## Commit messages

English or 中文. Multi-line messages with a body are encouraged for non-trivial changes.

## Security

Auth bypass, credential leak, XSS in the web UI — do not file a public issue. See `SECURITY.md` for a private channel.

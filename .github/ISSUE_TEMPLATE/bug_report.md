---
name: Bug report
about: Report a crash or unexpected behavior in sustech_survival
title: "[BUG] "
labels: bug
assignees: ""
---

## Subsystem

Which subsystem does this affect?
(`sso` / `tis` / `tis.classroom` / `selectcourse` / `bb` / `lib` / `lib.booking` /
`pms` / `papers` / `nces` / `transit` / `faculty` / `ws` / `webui` / `context` /
`calendar` / `cli`)

## Environment

- sustech_survival version: (run `pip show sustech_survival | grep Version`)
- Python version: (run `python --version`)
- OS: (e.g. macOS 26, Ubuntu 24.04)
- Install method: (`pip install ...[all]` / `pip install -e .[all]` / git+ URL)

## To reproduce

Steps to reproduce, with the smallest possible code snippet:

```python
from sustech_survival import ...
# ...
```

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Paste the **full** traceback (not a screenshot of one).

## Credentials

**DO NOT share real SUSTech credentials in the issue.** If the bug only
reproduces under a specific account state (major, year, enrolled courses),
describe the state 鈥?not the values.

## Network / session log

If the bug involves a SUSTech upstream request/response, run with logging
and paste the relevant lines:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```
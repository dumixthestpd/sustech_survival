# TIS Grades

**What:** Official grade records from SUSTech's Teaching Information System. Course code, credits, letter grade, numeric score, semester.

**Use for:** Official GPA calculation (SUSTech 4.0 scale, A=3.94 not 4.0), transcript export, checking if a course passed.

## Module

```python
from sustech_survival.tis.grades import run
```

## `run(semester=None, export=None)`

```python
run()                        # all semesters
run(semester='2025秋季')
run(export='csv')            # -> ~/.openclaw/workspace/sustech/grades.csv
```

Fetches from `https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx` via CAS-authenticated session. Returns grades grouped by semester with per-semester and overall GPA.

## GPA Table

SUSTech official 4.0 scale (本科, source: sustech.online/study → GPA换算表):

```
A+ 4.00   A  3.94   A- 3.85
B+ 3.73   B  3.55   B- 3.32
C+ 3.09   C  2.78   C- 2.42
D+ 2.08   D  1.63   D- 1.15
F  0.00
```

P (Pass) courses are excluded from GPA. Numeric scores fall back to standard Chinese 4.0 scale when letter grade is missing.

## TIS API Fields

| Field | Meaning |
|-------|---------|
| `kcdm` | Course code |
| `kcmc` | Course name (Chinese) |
| `kcmc_en` | Course name (English) |
| `xnxqmc` | Semester name |
| `xf` | Credits |
| `xscj` | Letter grade |
| `zzcj` | Numeric score |
| `kcxz` | Course type (必修/选修/...) |
| `yxmc` | Department |

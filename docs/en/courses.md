# TIS Courses

**What:** Course schedule from TIS — which courses are enrolled, instructor, credits, course type per semester.

**Use for:** Knowing what courses are registered, what semester you're in, instructor names. Does not show classroom locations or timetable slots.

## Module

```python
from sustech_survival.tis.courses import run
```

## `run(semester=None, format='table')`

```python
run()                        # all semesters, table output
run(semester='2026春季')
run(format='csv')            # -> Exports to courses_tis.csv in the current directory.
```

Uses the same TIS grade API as grades (it returns all course records including ungraded ones). Groups by semester and prints instructor, credits, course type.

## TIS Course Fields

| Field | Meaning |
|-------|---------|
| `kcdm` | Course code |
| `kcmc` | Course name |
| `xf` | Credits |
| `dgjsmc` | Instructor |
| `kcxz` | Course type |
| `yxmc` | Department |

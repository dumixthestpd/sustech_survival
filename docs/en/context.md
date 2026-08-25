# Context

"What's happening right now" — a daily-use snapshot for AI agents and students.

Returns: date, current semester week, next deadlines, upcoming exams, class-now, weather, AQI.

**Auth:** `TISAuth` + `BBAuth` (for deadlines/exams). Weather and AQI are public.

---

## CLI

```bash
sustech context                    # terse output (default)
sustech context --level normal     # more detail
sustech context --level verbose    # everything
sustech context --json             # JSON output
```

---

## Python API

```python
from sustech_survival import Context, Level

ctx = Context(level=Level.NORMAL)
print(ctx.to_str())              # human-readable
data = ctx.to_dict()             # structured
```

### Time simulation

```python
from sustech_survival import Context

ctx = Context(dt="2026-09-01")   # simulate the start of fall semester
```
# Calendar

SUSTech academic calendar — semesters, holidays, compensatory workdays, date intelligence.

Loads JSON from the `sustech-calendar` GitHub repo (online is canonical; local override at `~/Documents/sustech-calendar/` for offline use).

---

## Python API

```python
from sustech_survival.calendar import AcademicCalendar

ac = AcademicCalendar.load(2026, "undergraduate")             # online (default)
ac = AcademicCalendar.load(2026, "undergraduate", online=False) # local

s = ac.spring    # Semester object
print(s.teaching_start)       # date(2026, 2, 25)
print(s.total_teaching_weeks)  # 16
print(s.human)                 # "Spring 2026"

# Date intelligence
d = s.week_of(date(2026, 4, 1))   # → 6 (which week of the semester)
day = s.day_of(date(2026, 4, 1))  # → Day object
print(day.is_teaching_day())      # True/False
print(day.is_holiday())          # True for 春节
print(day.is_compensatory())     # True for 补班 Saturdays
```
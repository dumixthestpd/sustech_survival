"""
sustech_survival.tis.classroom.schema — Dataclasses + kcxx HTML parser.

The TIS campus schedule `kcxx` field embeds schedule data as
HTML strings in the form:
    "1-15周,星期一第3-4节 一教324"
    "3,7,9,13周,星期日第1-4节 校外活动场所"
    "1-9,11-15周,星期二第3-4节 一教326"

Each `<span class="ivu-tag-text"><p>...</p></span>` block in `kcxx` is one
schedule slot. We parse each block into a `ScheduleSlot`.

Quirks worth knowing:
- Week patterns can be ranges ("1-15") or discrete lists ("3,7,9,13") or
  mixed ("1-9,11-15" = weeks 1-9 + 11-15, skipping week 10 — typical for
  spring festival).
- Periods are 1-12 per day (4 periods in the morning, 4 in the afternoon,
  4 in the evening — SUSTech standard).
- Room names can include buildings ("一教324"), labs ("慧园2栋509"), or
  off-campus ("校外活动场所").
- Some courses have NO room in kcxx (e.g. 劳动教育 "off-campus activity").
  We keep those as slots with room="校外..." or empty.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ── Constants ────────────────────────────────────────────────────────────────

DAY_CHARS = "一二三四五六日"
DAY_NAMES_ZH = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DAY_NAMES_EN = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Periods 1-12 (4 morning, 4 afternoon, 4 evening — SUSTech standard).
# Most courses use 1-4 (morning), 5-8 (afternoon), 9-12 (evening).
PERIOD_TIMES = [
    "",   # 0 placeholder
    "08:00-08:45", "08:55-09:40", "10:00-10:45", "10:55-11:40",   # 1-4 morning
    "14:00-14:45", "14:55-15:40", "16:00-16:45", "16:55-17:40",   # 5-8 afternoon
    "19:00-19:45", "19:55-20:40", "20:50-21:35", "21:45-22:30",   # 9-12 evening
]


def day_char_to_int(c: str) -> int:
    """'一' → 1, '二' → 2, ..., '日' → 7. Returns 0 on unknown."""
    try:
        return DAY_CHARS.index(c) + 1
    except ValueError:
        return 0


# ── Parsing ──────────────────────────────────────────────────────────────────


# Match a single schedule line:
#   "1-15周,星期一第3-4节 一教324"
#   "3,7,9,13周,星期日第1-4节 校外活动场所"
#   "1-9,11-15周,星期二第3-4节 一教326"
#   "1-15单周,星期三第3-4节 一教125"  (odd weeks only)
#   "2-16双周,星期三第3-4节 一教426"  (even weeks only)
_SLOT_RE = re.compile(
    r"^(?P<weeks>[\d,\\-]+)(?P<parity>单|双)?周,"
    r"星期(?P<day>[一二三四五六日])"
    r"第(?P<pstart>\d+)(?:-(?P<pend>\d+))?节"
    r"\s+(?P<room>.+)$"
)

# Extract paragraphs from inside <span class="ivu-tag-text"><p>...</p></span>
_P_RE = re.compile(
    r'<span class="ivu-tag-text"><p>([^<]+)</p></span>',
    re.DOTALL,
)


def expand_weeks(weeks_str: str) -> List[int]:
    """Expand a week pattern like '1-9,11-15' or '3,7,9,13' into a sorted list.

    >>> expand_weeks("1-15")
    [1, 2, 3, ..., 15]
    >>> expand_weeks("3,7,9,13")
    [3, 7, 9, 13]
    >>> expand_weeks("1-9,11-15")
    [1, 2, ..., 9, 11, 12, ..., 15]
    """
    out: List[int] = []
    for chunk in weeks_str.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                a, b = int(a), int(b)
                if a <= b:
                    out.extend(range(a, b + 1))
                else:
                    # Reverse range — shouldn't happen but be defensive.
                    out.extend(range(b, a + 1))
            except (ValueError, TypeError):
                continue
        else:
            try:
                out.append(int(chunk))
            except (ValueError, TypeError):
                continue
    return sorted(set(out))


def parse_kcxx_slot(line: str) -> Optional[dict]:
    """Parse one schedule line. Returns None if not a schedule line.

    Returned dict keys: weeks (List[int]), day (int), period_start (int),
    period_end (int), room (str).

    Handles 单周 (odd weeks only) and 双周 (even weeks only) parity.
    """
    line = line.strip()
    m = _SLOT_RE.match(line)
    if not m:
        return None
    pstart = int(m.group("pstart"))
    pend = int(m.group("pend") or m.group("pstart"))
    weeks = expand_weeks(m.group("weeks"))
    parity = m.group("parity")
    if parity == "单":
        weeks = [w for w in weeks if w % 2 == 1]
    elif parity == "双":
        weeks = [w for w in weeks if w % 2 == 0]
    return {
        "weeks": weeks,
        "day": day_char_to_int(m.group("day")),
        "period_start": pstart,
        "period_end": pend,
        "room": m.group("room").strip(),
    }


def parse_kcxx(kcxx_html: str) -> List[dict]:
    """Extract all schedule slots from a course's `kcxx` HTML blob.

    Returns a list of slot dicts (see parse_kcxx_slot for shape).
    Non-schedule paragraphs (e.g. "选课要求:本课程只面向...") are skipped.

    The kcxx can have multiple <p> blocks inside a single
    <span class="ivu-tag-text"> — extract all of them, not just the first.
    """
    slots: List[dict] = []
    span_re = re.compile(
        r'<span class="ivu-tag-text">(.*?)</span>',
        re.DOTALL,
    )
    p_re = re.compile(r'<p>([^<]*)</p>')
    for span_m in span_re.finditer(kcxx_html or ""):
        span_content = span_m.group(1)
        for p_m in p_re.finditer(span_content):
            line = p_m.group(1).strip()
            # Unescape HTML entities (common in kcxx content).
            line = line.replace("&nbsp;", " ").replace("&amp;", "&")
            slot = parse_kcxx_slot(line)
            if slot:
                slots.append(slot)
    return slots


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class Room:
    """A physical classroom in the SUSTech catalog.

    Built by aggregating ScheduleSlots — name + capacity (from `jszws`).
    No GPS / building code (the API doesn't expose those for rooms).
    """
    name: str                       # "一教324"
    capacity: Optional[int] = None  # from course.jszws when available
    slot_count: int = 0             # number of (course × timeslot) tuples

    @property
    def short_name(self) -> str:
        """'慧园2栋509' → '慧园2栋', '一教324' → '一教'. Best-effort."""
        m = re.match(r"^([^\d]+)", self.name)
        return m.group(1) if m else self.name


@dataclass
class ScheduleSlot:
    """One (course × week × day × period-range) tuple in a specific room.

    A single course typically has multiple slots per semester — one per
    (day, period-range) combination. The `weeks` list is the EXPANDED set
    of weeks this slot is active.
    """
    course_code: str                # kcdm — "BIO2101"
    course_name: str                # kcmc — "生命科学概论"
    class_group: str                # kxh — "001"
    weeks: List[int]                # expanded [1,2,...,15]
    day: int                        # 1=Mon ... 7=Sun
    period_start: int               # 1-12
    period_end: int                 # 1-12
    room: str                       # "一教324"

    @property
    def duration(self) -> int:
        return self.period_end - self.period_start + 1

    def active_on(self, week: int, day: int) -> bool:
        """Is this slot active on a specific (week, day)?"""
        return day == self.day and week in self.weeks

    def overlaps(self, period_start: int, period_end: int) -> bool:
        """Does this slot's period range overlap with [period_start, period_end]?"""
        return not (self.period_end < period_start or self.period_start > period_end)

    @property
    def when_str(self) -> str:
        """Pretty '1-15周 周一 3-4节'."""
        weeks = self.weeks
        if not weeks:
            week_str = "?"
        elif len(weeks) == 1:
            week_str = f"{weeks[0]}"
        elif weeks == list(range(weeks[0], weeks[-1] + 1)):
            week_str = f"{weeks[0]}-{weeks[-1]}"
        else:
            week_str = ",".join(str(w) for w in weeks)
        day = DAY_NAMES_ZH[self.day] if 1 <= self.day <= 7 else f"day{self.day}"
        ps, pe = self.period_start, self.period_end
        p_str = f"第{ps}-{pe}节" if ps != pe else f"第{ps}节"
        return f"{week_str}周 {day} {p_str}"

    @classmethod
    def from_course_and_kcxx(cls, course: dict) -> List["ScheduleSlot"]:
        """Build all ScheduleSlots for one course dict from the campus API.

        Returns [] if the course has no parseable kcxx schedule.
        """
        code = course.get("kcdm") or ""
        name = course.get("kcmc") or ""
        group = course.get("kxh") or ""
        capacity = None
        try:
            if course.get("jszws"):
                capacity = int(course["jszws"])
        except (ValueError, TypeError):
            pass
        slots: List[ScheduleSlot] = []
        for slot in parse_kcxx(course.get("kcxx") or ""):
            slots.append(cls(
                course_code=code,
                course_name=name,
                class_group=group,
                weeks=slot["weeks"],
                day=slot["day"],
                period_start=slot["period_start"],
                period_end=slot["period_end"],
                room=slot["room"],
            ))
        return slots

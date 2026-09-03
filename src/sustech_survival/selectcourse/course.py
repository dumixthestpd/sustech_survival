"""
sustech_survival.selectcourse.course — Course dataclass + slot helpers.

A `Course` represents one offering of a class — one row in the
`Xsxktz/queryRwxxcxList` response — with its kcxx HTML already parsed
into `slots` (a list of ScheduleSlot-like dicts).

Reuses the parsing logic from `classroom.schema` (parse_kcxx_slot, expand_weeks)
to keep the parsing layer DRY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sustech_survival.tis.classroom.schema import (
    parse_kcxx, expand_weeks, day_char_to_int,
    DAY_NAMES_ZH,
)


# -- Schedule-export dataclasses --------------------------------------------
#
# These types are the structured form of "where/when a class meets" —
# the unit of time that the TUI schedule grid, the web UI course picker,
# and any downstream consumer (CalDAV export, .ics generator, etc.)
# should work with. They replace ad-hoc parsing of `schedule_str` and
# the kcxx HTML.


@dataclass(frozen=True)
class SectionSpan:
    """One weekly meeting of one section — structured.

    A single Course can have multiple spans (e.g., Mon 3-4 + Wed 7-8).
    The TUI grid places one cell per span; the web UI picker uses the
    spans to fill the time slots deterministically.
    """
    day: int                # 1=Monday, 7=Sunday
    day_name: str           # "周一"
    period_start: int       # 1
    period_end: int         # 4 (inclusive)
    weeks: tuple[int, ...]  # weeks the meeting happens (1..16)
    weeks_label: str        # "1-16 周" or "1-8,10-16 周" — human-readable
    room: str               # "智华楼102"
    teacher: str            # "张三"


@dataclass(frozen=True)
class SectionTable:
    """All meeting spans of one section, with parent-course metadata."""
    code: str
    name: str
    section_name: str
    class_group: str
    teachers: tuple[str, ...]
    credits: float
    total_hours: float
    nature: str
    campus: str
    spans: tuple[SectionSpan, ...]

    def to_markdown(self) -> str:
        """Render as a markdown bullet list — TUI / chat-friendly."""
        lines = [
            f"## {self.code} — {self.name}",
            f"**{self.section_name}** | 班号 {self.class_group} | "
            f"{self.nature} | {self.campus} | "
            f"{self.credits} 学分 / {self.total_hours} 学时",
            f"教师: {', '.join(self.teachers) or '(unknown)'}",
            "",
            "**Meetings:**",
        ]
        if not self.spans:
            lines.append("  (no scheduled meetings)")
        else:
            for s in self.spans:
                p = (f"{s.period_start}-{s.period_end}节"
                     if s.period_start != s.period_end
                     else f"{s.period_start}节")
                lines.append(
                    f"  - {s.day_name} 第{p} ({s.weeks_label}) "
                    f"@ {s.room or '(no room)'}"
                    f"{' / ' + s.teacher if s.teacher else ''}"
                )
        return "\n".join(lines)

    def to_json(self) -> str:
        """JSON-serializable dict (for web UI / API consumers)."""
        import json as _json
        return _json.dumps({
            "code": self.code, "name": self.name,
            "section_name": self.section_name,
            "class_group": self.class_group,
            "teachers": list(self.teachers),
            "credits": self.credits, "total_hours": self.total_hours,
            "nature": self.nature, "campus": self.campus,
            "spans": [
                {"day": s.day, "day_name": s.day_name,
                 "period_start": s.period_start, "period_end": s.period_end,
                 "weeks": list(s.weeks), "weeks_label": s.weeks_label,
                 "room": s.room, "teacher": s.teacher}
                for s in self.spans
            ],
        }, ensure_ascii=False, indent=2)


def _format_weeks_label(weeks: list[int]) -> str:
    """Compact human label for a weeks list.

    [1,2,3,4,5,6,7,8,10,11,12,13,14,15,16] → "1-8,10-16 周"
    [1,3,5,7,9]                       → "1,3,5,7,9 周"
    []                                 → ""
    """
    if not weeks:
        return ""
    sorted_w = sorted(set(int(w) for w in weeks))
    ranges: list[str] = []
    start = prev = sorted_w[0]
    for w in sorted_w[1:]:
        if w == prev + 1:
            prev = w
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = w
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges) + " 周"


def export_schedule_table(
    courses: list,
    *,
    format: str = "markdown",
) -> str:
    """Build a schedule table for many sections — TUI / web UI input.

    Args:
        courses: list of `Course` objects (any number, any course)
        format: "markdown" (default), "json", or "csv"

    Returns:
        formatted string for the chosen format. Markdown is the
        human-readable default; JSON is machine-readable (one object
        per course); CSV is import-friendly (one row per section-span).

    Example:
        >>> from sustech_survival.selectcourse import selectcourse as sc
        >>> from sustech_survival.selectcourse.course import export_schedule_table
        >>> client = sc.SelectCourseClient(xn="2025-2026", xq="2")
        >>> courses = client.search_campus(keyword="MSE306")
        >>> print(export_schedule_table(courses))
    """
    tables = [c.export_sections_table() for c in courses]
    if format == "json":
        import json as _json
        return _json.dumps(
            [_json.loads(t.to_json()) for t in tables],
            ensure_ascii=False, indent=2,
        )
    if format == "csv":
        rows = ["code,name,section,class_group,day,day_name,"
                "period_start,period_end,weeks_label,room,teacher"]
        for t in tables:
            if not t.spans:
                rows.append(f"{t.code},{t.name},{t.section_name},"
                            f"{t.class_group},,,,,,")
            for s in t.spans:
                rows.append(
                    f"{t.code},{t.name},{t.section_name},{t.class_group},"
                    f"{s.day},{s.day_name},{s.period_start},{s.period_end},"
                    f'"{s.weeks_label}",{s.room},{s.teacher}'
                )
        return "\n".join(rows)
    # markdown default
    return "\n\n---\n\n".join(t.to_markdown() for t in tables)


@dataclass
class Course:
    """One course offering from the TIS campus schedule API."""
    code: str                      # kcdm — "BIO101"
    name: str                      # kcmc — "生命科学概论"
    name_en: str                   # rwmc_en — "Life Science Introduction"
    class_group: str              # kxh — "001" / "002"
    rwh: str                       # rwh — "2025-2026-2-BIO101-001" (human label)
    college: str                   # kkyxmc — "生命科学学院"
    category: str                  # kclbmc — "大类基础"
    nature: str                    # kcxzmc — "必修" / "选修"
    campus: str                    # xiaoqumc — "一期校区"
    credits: float                 # xf — 学分
    total_hours: float             # zxs — 总学时
    capacity: Optional[int]        # zrl — total enrollment cap
    undergrad_seats: Optional[int] # bksrl — 本科生人数
    grad_seats: Optional[int]      # yjsrl — 研究生人数
    cultivation: str               # pylx — "本科" / "研究生"
    rooms: List[str] = field(default_factory=list)         # distinct rooms in kcxx
    teachers: List[str] = field(default_factory=list)      # from dgjsmc (preferred) or kcxx 教师 list
    slots_raw: List[dict] = field(default_factory=list)    # parsed ScheduleSlot dicts
    task_type: str = ""               # rwlxmc — "专业任务" / "通识必修选课" / etc.
    language: str = ""                # skyymc — "中文" / "英文" / "双语"
    college_code: str = ""            # kkyx — college ID code (e.g. "010030" for 化学系)
    section_name: str = ""            # rwmc — section name, e.g. "体育I-中文-空手道1班"
    section_name_en: str = ""         # rwmc_en — section name English
    enrolled: Optional[int] = None # 当前已选人数 (live from queryKxrw; None if unknown)
    id: str = ""                   # 32-char hex UUID — the actual TIS write-key.
                                   # Only present in queryKxrw rows; empty in the
                                   # catalog (queryRwxxcxList) which is read-only.
                                   # Write endpoints (addXuanke/tuike/updXkxsByyx/...)
                                   # take `p_id=<this hex>`, NOT the rwh.
    grading: str = ""              # jfzlbmc — 计分方式: "十三级制" / "二级制" (problem list #9)
    conflicts: str = ""            # ctkcxx — 冲突课程 (comma/HTML text, e.g. "材料学综合实验I(排课)。")
    requirement: str = ""          # xkyq — 选课要求 (e.g. "每次实验课都计入期末成绩…"); also
                                   # parsed from kcxx "选课要求:…" suffix when xkyq is empty
    note: str = ""                 # bz — 备注

    @property
    def has_schedule(self) -> bool:
        return bool(self.slots_raw)

    @property
    def schedule_str(self) -> str:
        """One-line human description of all slots, e.g. '周一 3-4节, 周三 7-8节'."""
        if not self.slots_raw:
            return "(no schedule)"
        parts = []
        for s in self.slots_raw:
            day = DAY_NAMES_ZH[s["day"]] if 1 <= s["day"] <= 7 else f"day{s['day']}"
            ps, pe = s["period_start"], s["period_end"]
            p_str = f"{ps}-{pe}" if ps != pe else f"{ps}"
            parts.append(f"{day} 第{p_str}节 ({s['room']})")
        return "; ".join(parts)

    @property
    def spans(self) -> tuple:
        """One `SectionSpan` per weekly meeting for this section.

        Structured form of `schedule_str`. The TUI grid places one cell
        per span; the web UI picker uses spans to fill time slots
        deterministically (no more re-parsing `kcxx` HTML).

        Returns a tuple of `SectionSpan` (frozen dataclass — safe to
        hash, safe to put in sets/dicts if needed).
        """
        out = []
        for s in self.slots_raw:
            weeks_raw = s.get("weeks") or s.get("week_list") or []
            weeks = tuple(int(w) for w in weeks_raw)
            day = int(s.get("day") or 0)
            ps = int(s.get("period_start") or 0)
            pe = int(s.get("period_end") or 0)
            out.append(SectionSpan(
                day=day,
                day_name=DAY_NAMES_ZH[day] if 1 <= day <= 7 else f"day{day}",
                period_start=ps,
                period_end=pe,
                weeks=weeks,
                weeks_label=_format_weeks_label(list(weeks)),
                room=str(s.get("room") or ""),
                teacher=str(s.get("teacher") or ""),
            ))
        return tuple(out)

    def export_sections_table(self) -> SectionTable:
        """Wrap this section's spans in a `SectionTable` for export.

        Use case: the course-grid web UI consumes this directly to fill
        its grid; the TUI uses `to_markdown()` for chat-friendly output;
        CalDAV/.ics generators consume `to_json()`.
        """
        return SectionTable(
            code=self.code,
            name=self.name,
            section_name=self.section_name or self.name,
            class_group=self.class_group,
            teachers=tuple(self.teachers),
            credits=float(self.credits or 0),
            total_hours=float(self.total_hours or 0),
            nature=self.nature,
            campus=self.campus,
            spans=self.spans,
        )

    @classmethod
    def from_api(cls, raw: dict) -> "Course":
        """Parse one row of Xsxktz/queryRwxxcxList.

        Field selection (TIS-2026 catalog format):
          name / name_en — rwmc/rwmc_en first (the actual section name with
            class group + language, e.g. "体育I-中文-空手道1班"). kcmc/kcmc_en
            is the generic course name ("体育I") — same for every section,
            useless in a per-class view. Fall back to kcmc if rwmc is missing.
          teachers       — dgjsmc is the clean teacher field, comma-separated
            for co-teach ("余春红,贾方兴"). Split on common delimiters.
            Fall back to the kcxx anchor-text extraction only if dgjsmc
            is empty (older TIS layouts).
          rooms/slots    — extracted from the kcxx HTML (the only place
            real schedule+room data lives).
        """
        kcxx = raw.get("kcxx") or ""
        slot_dicts = parse_kcxx(kcxx)
        rooms = []
        for s in slot_dicts:
            if s["room"] and s["room"] not in rooms:
                rooms.append(s["room"])

        # Name: kcmc (course, generic — same for every section, used for grouping)
        # is the canonical title. rwmc (section name — e.g. "体育I-中文-空手道1班")
        # is the section-specific sub-line, stored separately as section_name.
        name = raw.get("kcmc") or ""
        name_en = raw.get("kcmc_en") or ""
        section_name = raw.get("rwmc") or ""
        section_name_en = raw.get("rwmc_en") or ""

        # Teachers: prefer dgjsmc (clean field), fall back to kcxx anchors
        dgjs = raw.get("dgjsmc") or ""
        teachers: List[str] = []
        if dgjs:
            import re as _re
            # TIS uses comma (and sometimes Chinese 、 or ，) between co-teachers
            for t in _re.split(r"[,，、]", dgjs):
                t = t.strip()
                if t and t not in teachers:
                    teachers.append(t)
        if not teachers and kcxx:
            import re as _re
            for t in _re.findall(r"<a [^>]*>([^<]+)</a>", kcxx):
                t = t.strip()
                if t and t not in teachers:
                    teachers.append(t)

        # Capacity fields may be strings ("48") or None.
        def _int(v):
            try:
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None

        # 选课要求 note: prefer the structured `xkyq` field; when empty,
        # pull the "选课要求:…" suffix out of the kcxx HTML (verified in
        # the official TIS payload 2026-08-30 — e.g. "选课要求:课程即将停
        # 开，请同学们尽快退课").
        requirement = (raw.get("xkyq") or "").strip()
        if not requirement and kcxx:
            import re as _re
            m = _re.search(r"选课要求\s*[:：]\s*([^<]+)", kcxx)
            if m:
                requirement = m.group(1).strip()
        return cls(
            code=raw.get("kcdm") or "",
            name=name,
            name_en=name_en,
            class_group=(
                raw.get("kxh") or
                # personal endpoint sometimes leaves kxh null but encodes
                # the class group in the rwh tail ("...-BIO103-001")
                (raw.get("rwh", "").rsplit("-", 1)[-1] if raw.get("rwh") and raw.get("rwh").count("-") >= 4 else "")
                or ""
            ),
            rwh=raw.get("rwh") or "",
            college=raw.get("kkyxmc") or "",
            category=raw.get("kclbmc") or "",
            nature=raw.get("kcxzmc") or "",
            campus=raw.get("xiaoqumc") or "",
            credits=float(raw.get("xf") or 0),
            total_hours=float(raw.get("zxs") or 0),
            capacity=_int(raw.get("zrl")),
            undergrad_seats=_int(raw.get("bksrl")),
            grad_seats=_int(raw.get("yjsrl")),
            cultivation=raw.get("pylx_label") or {"1": "本科", "2": "研究生"}.get(raw.get("pylx", "")) or raw.get("pylx") or "",
            # Live "currently selected" count — only present in some TIS
            # payloads (personal-mode search and a few others). The field
            # name varies by year/round; try the common ones defensively.
            enrolled=_int(
                raw.get("bkrs") or raw.get("yxrs") or raw.get("xkrs")
                or raw.get("kchsrl") or raw.get("bkylrs") or raw.get("yxzrs")
            ),
            # TIS write-key: the 32-char hex UUID used as `p_id` on every
            # write endpoint (addXuanke/tuike/updXkxsByyx/...). Catalog
            # rows (queryRwxxcxList) don't have this — only queryKxrw
            # personal-mode rows do. Default "" so the catalog path is
            # unaffected.
            id=raw.get("id") or "",
            rooms=rooms,
            teachers=teachers,
            slots_raw=slot_dicts,
            task_type=raw.get("rwlxmc") or raw.get("rwlx") or "",
            language=raw.get("skyymc") or "",
            college_code=raw.get("kkyx") or "",
            section_name=section_name,
            section_name_en=section_name_en,
            grading=raw.get("jfzlbmc") or raw.get("jfzlbmc_en") or "",
            conflicts=raw.get("ctkcxx") or raw.get("ctkcxx_en") or "",
            requirement=requirement,
            note=(raw.get("bz") or "").strip(),
        )

"""
sustech_survival.selectcourse.schema — Course dataclass + helpers.

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


@dataclass
class Course:
    """One course offering from the TIS campus schedule API."""
    code: str                      # kcdm — "BIO101"
    name: str                      # kcmc — "生命科学概论"
    name_en: str                   # rwmc_en — "Life Science Introduction"
    class_group: str              # kxh — "001" / "002"
    rwh: str                       # rwh — "2025-2026-2-BIO101-001" (unique ID)
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
    teachers: List[str] = field(default_factory=list)      # from kcxx 教师 list
    slots_raw: List[dict] = field(default_factory=list)    # parsed ScheduleSlot dicts
    task_type: str = ""               # rwlxmc — "专业任务" / "通识必修选课" / etc.
    language: str = ""                # skyymc — "中文" / "英文" / "双语"
    college_code: str = ""            # kkyx — college ID code (e.g. "010030" for 化学系)

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

        # Name: prefer rwmc (section name) over kcmc (course name)
        name = raw.get("rwmc") or raw.get("kcmc") or ""
        name_en = raw.get("rwmc_en") or raw.get("kcmc_en") or ""

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
        return cls(
            code=raw.get("kcdm") or "",
            name=name,
            name_en=name_en,
            class_group=raw.get("kxh") or "",
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
            rooms=rooms,
            teachers=teachers,
            slots_raw=slot_dicts,
            task_type=raw.get("rwlxmc") or raw.get("rwlx") or "",
            language=raw.get("skyymc") or "",
            college_code=raw.get("kkyx") or "",
        )

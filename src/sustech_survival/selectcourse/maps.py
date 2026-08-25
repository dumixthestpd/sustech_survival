"""
sustech_survival.selectcourse.maps — TIS taxonomy maps + translation helpers.

Pure data: category-name ↔ code, language-name ↔ code. No HTTP, no I/O.
Imported by `selectcourse.py` (the client) and by `webui` for
/api/tis/info serialization.

Discovery doc: sustech-dev/references/tis-kclbdm-discovery-2026-07-08.md
"""
from __future__ import annotations


# kclbdm (课程类别代码) map — display name → DM code.
# Discovered from the TIS kclb SPA bundle (`inco.component.kclb-*.js`)
# endpoint `component/queryKclb` (NOT `/Xsxk/queryKclb` which 404s).
#
# Personal mode TIS search expects the kclbdm code in `p_kclb`. Passing
# the display name silently returns 0 results. Use this to translate
# dropdown values before hitting TIS.
#
# Public name is CATEGORY_MAP (semantic, no TIS jargon). KCLBDM_MAP kept
# as an alias for any external code that imported it.
#
# Sub-categories (level 2 like 0901-0909) are stored in TIS response
# kclbmc as `<parent>-<sub>` (e.g. "通识选修课-美育类"). The frontend
# dropdown shows only the bare sub-name (e.g. "美育类") so the bare
# name → code mapping covers the dropdown cases.
CATEGORY_MAP: dict = {
    # Top-level (level 1) — undergrad
    "专业基础课": "03",
    "专业必修课": "04",   # 04 (undergrad) and 10 both named "专业必修课"
    "专业选修课": "05",
    "专业核心课": "07",
    "通识必修课": "08",
    "通识选修课": "09",
    "实践": "11",
    "国际化人才培养": "13",
    "任选": "98",
    "其他": "99",
    "辅修专业选修学分": "998",
    "辅修专业必修学分": "999",
    # Sub-categories (level 2) — child of 09 通识选修课
    "人文类": "0901",
    "社科类": "0902",
    "艺术类": "0903",
    "其它任选类": "0904",
    "外语类": "0905",
    "劳育类": "0906",
    "美育类": "0907",
    "国学类": "0908",
    "专业导论类": "0909",
    # Graduate-only (level 1) — pylb=2
    "培养环节": "01",     # grad only (pylb=1 has no 培养环节 — it's a 研究生 thing)
    "校外共享课": "200",
}

# Reverse: code → display name (for /api/tis/info payload).
CATEGORY_REVERSE: dict = {v: k for k, v in CATEGORY_MAP.items()}
# Back-compat alias for any external code that imported the old name.
KCLBDM_MAP: dict = CATEGORY_MAP
KCLBDM_REVERSE: dict = CATEGORY_REVERSE


def category_name_to_code(name: str) -> str:
    """Translate TIS response `kclbmc` (category display name) to its
    internal code.

    Handles both bare names (`美育类`) and hyphenated names
    (`通识选修课-美育类`). If the input is already a digit code
    (`0907`), pass it through. Returns empty string if not recognized
    (callers should treat unknown as no-filter).
    """
    if not name:
        return ""
    s = name.strip()
    # Pass-through: already a digit code
    if s.isdigit():
        return s
    # Direct lookup first
    if s in CATEGORY_MAP:
        return CATEGORY_MAP[s]
    # Try stripping "<parent>-" prefix
    if "-" in s:
        suffix = s.split("-", 1)[1]
        if suffix in CATEGORY_MAP:
            return CATEGORY_MAP[suffix]
    return ""


# Back-compat alias (the old TIS-jargon name).
kclbmc_to_code = category_name_to_code


# Language code (p_skyy) — TIS personal mode expects a code, not name.
# 1=中文, 2=英文, 3=双语. Verified by trial 2026-07-07.
LANGUAGE_MAP: dict = {
    "中文": "1",
    "英文": "2",
    "双语": "3",
}


def language_to_code(language: str) -> str:
    """Translate display language name to TIS code. Returns input as-is
    if already a code (or unrecognized)."""
    if not language:
        return ""
    return LANGUAGE_MAP.get(language.strip(), language.strip())
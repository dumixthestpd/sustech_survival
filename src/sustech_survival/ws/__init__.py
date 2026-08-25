# -----------------------------------------------------------------------------
# __init__.py — ws module public API
# -----------------------------------------------------------------------------
"""
WS Student Exchange Module — sustech_survival

Provides program search and detail for the SUSTech 外事工作服务系统
(Student Exchange/Abroad Portal) at ws.sustech.edu.cn.

CLI:  python -m sustech_survival.ws <cmd>
       ws list / ws search <q> / ws show <id> / ws count
"""
from __future__ import annotations

from .programs import WSAuth, list_programs, search_programs, get_program_detail, get_count

__all__ = [
    "WSAuth",
    "list_programs",
    "get_program_detail",
    "search_programs",
    "get_count",
]

# -*- coding: utf-8 -*-
"""WebUI skin generator (v2 — self-contained, distinct skins).

The module ships ONLY the ``default`` fallback skin; every other skin is
generated here and lives in the user's home dotdir (``~/.sustech_survival/
skins/<name>/``) — the runtime skin store.

Each skin's ``tis.html`` is built from the default skin's self-contained
page (the shared DOM + shared ``/static/tis/tis.js`` engine) with:

  - its own palette (``:root``) and body background, and
  - its own **distinct design system** (``tis_extra``) — fonts, surfaces,
    layout treatment, card style, animations — so skins do NOT look like
    palette swaps of one another.

Run:  python tools/gen_skins.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TIS = (REPO / "src" / "sustech_survival" / "webui" / "skins"
               / "default" / "tis.html")
TRANSIT_BASE = REPO / "src" / "sustech_survival" / "transit" / "web"

sys.path.insert(0, str(REPO / "src"))
from sustech_survival._cache import config_root  # noqa: E402

HOME_SKINS = config_root() / "skins"

REQUIRES = "2026.8.0"
API = [
    "/api/tis/info", "/api/tis/courses", "/api/tis/enrolled",
    "/api/tis/course-types", "/api/tis/round", "/api/tis/bids",
    "/api/transit/live", "/api/nces/status",
]


def _tokenize(txt: str) -> str:
    """No raw accent literals survive (template blue + old orange bases)."""
    txt = txt.replace("rgba(91,157,255,", "rgba(var(--accent-rgb),")
    txt = txt.replace("rgba(220,100,0,", "rgba(var(--accent-rgb),")
    txt = txt.replace("#7fb0ff", "var(--accent2)")
    txt = txt.replace("#dc6400", "var(--accent)")
    txt = txt.replace("#b34a00", "var(--accent-dark)")
    return txt


def _replace_root(txt: str, root_css: str) -> str:
    return re.sub(r":root\{[^}]*\}", root_css, txt, count=1)


def _replace_body_bg(txt: str, body_bg: str) -> str:
    return re.sub(r"(body\{[^}]*?background:)[^}]*",
                  lambda m: m.group(1) + body_bg, txt, count=1)


def _append_before_style(txt: str, css: str) -> str:
    if css.strip() and css not in txt:
        return txt.replace("</style>", css + "\n</style>", 1)
    return txt


# ── per-skin: palette + body bg + DISTINCT design system ──────────────────
SKINS = {
    # ── clean & airy official light ─────────────────────────────────────
    "sustech_official_light": {
        "dark": False,
        "tis_root": ":root{--bg:#f5f6fa;--panel:#ffffff;--panel2:#eef1f6;--border:#d8dee8;--txt:#1a2233;--mut:#5d6b80;--fg:#1a2233;--teal:#003030;--teal2:#18a8a8;--accent:#dc6400;--accent2:#f07830;--ok:#2f9e5b;--warn:#e0941f;--bad:#d64535;--accent-rgb:220 100 0;--accent-dark:#b34a00;--radius:14px;--radius-sm:10px;--shadow-1:0 1px 2px rgba(26,34,51,.06),0 10px 28px rgba(26,34,51,.08);--shadow-2:0 6px 16px rgba(26,34,51,.14),0 20px 48px rgba(26,34,51,.16);--tr:.2s cubic-bezier(.2,.8,.2,1);--ring:color-mix(in srgb,var(--accent) 50%,transparent);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(220,100,0,.10),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(24,168,168,.09),transparent 60%),linear-gradient(160deg,#fafbfc,#ffffff 45%,#eef1f6)",
        "transit_root": ":root {\n  --bg: #f5f6fa;\n  --panel-bg: #ffffff;\n  --border: #dfe4ec;\n  --primary: #dc6400;\n  --primary-dark: #b34a00;\n  --accent-bus1: #18a8a8;\n  --accent-bus2: #f07830;\n  --accent-shuttle: #dc6400;\n  --text: #1a2233;\n  --text-dim: #5d6b80;\n  --shadow: 0 2px 8px rgba(0,0,0,0.12);\n}",
        "tis_extra": """
/* official_light — clean, airy, generous */
header{background:linear-gradient(180deg,rgba(255,255,255,.9),rgba(255,255,255,.55));border-bottom:1px solid var(--border);backdrop-filter:blur(10px)}
.wrap{gap:14px;padding:14px}
.col{background:var(--panel);border-radius:var(--radius);box-shadow:var(--shadow-1)}
.sub{padding:.9rem 1.1rem}
.sub h2{letter-spacing:.12em}
.c-card{border-radius:var(--radius-sm);padding:.7rem .95rem;border:1px solid var(--border)}
.c-card .top .nm{font-size:.9rem}
.slot-tag{border-radius:6px}
""",
    },

    # ── warm material orange (dark) ─────────────────────────────────────
    "sustech_orange": {
        "dark": True,
        "tis_root": ":root{--bg:#17130d;--panel:#221b12;--panel2:#2c2317;--border:#3d3222;--txt:#f0e7d8;--mut:#b3a183;--fg:#f0e7d8;--teal:#3a2a10;--teal2:#ffb45e;--accent:#ed7005;--accent2:#ff9e3d;--ok:#6fbf73;--warn:#e6b04c;--bad:#ef6a5e;--accent-rgb:237 112 5;--accent-dark:#c05c00;--radius:10px;--radius-sm:8px;--shadow-1:0 2px 4px rgba(0,0,0,.35),0 10px 26px rgba(0,0,0,.3);--shadow-2:0 6px 16px rgba(0,0,0,.45),0 18px 44px rgba(0,0,0,.4);--tr:.16s ease;--ring:color-mix(in srgb,var(--accent) 60%,transparent);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(237,112,5,.16),transparent 60%),linear-gradient(160deg,#17130d,#1e1810 50%,#120f0a)",
        "transit_root": ":root {\n  --bg: #17130d;\n  --panel-bg: #221b12;\n  --border: #3d3222;\n  --primary: #ed7005;\n  --primary-dark: #c05c00;\n  --accent-bus1: #ff9e3d;\n  --accent-bus2: #f0608f;\n  --accent-shuttle: #ffb45e;\n  --text: #f0e7d8;\n  --text-dim: #b3a183;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
        "tis_extra": """
/* sustech_orange — warm material, bold, elevated */
header{background:linear-gradient(180deg,#241c11,#1b150c);border-bottom:2px solid var(--accent)}
.sub h2{text-transform:uppercase;letter-spacing:.18em;font-weight:700}
.wrap{gap:10px;padding:10px}
.col{border-radius:var(--radius);box-shadow:var(--shadow-1);border:1px solid var(--border)}
.c-card{border-radius:var(--radius-sm);border:1px solid var(--border);border-left:4px solid transparent}
.c-card:hover{border-left-color:var(--accent);transform:translateY(-2px);box-shadow:var(--shadow-2)}
.c-card .code{letter-spacing:.04em}
.stepper .step-chip{border-radius:8px;font-weight:600}
.step-chip.active{background:linear-gradient(180deg,var(--accent),var(--accent-dark));color:#fff}
.step-chip.active .step-num{background:rgba(255,255,255,.25);color:#fff}
button.primary{background:linear-gradient(180deg,var(--accent2),var(--accent))}
""",
    },

    # ── midnight command center (dark, dense) ───────────────────────────
    "sustech_midnight": {
        "dark": True,
        "tis_root": ":root{--bg:#0d1420;--panel:#131c2a;--panel2:#182334;--border:#24334a;--txt:#dfe7f1;--mut:#8ea0b8;--fg:#dfe7f1;--teal:#1c2f33;--teal2:#2ec9c9;--accent:#ffb04d;--accent2:#ffc57a;--ok:#43c983;--warn:#e0b04c;--bad:#ef6a62;--accent-rgb:255 176 77;--accent-dark:#d98a2b;--radius:6px;--radius-sm:4px;--shadow-1:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.35);--shadow-2:0 4px 12px rgba(0,0,0,.5),0 14px 36px rgba(0,0,0,.45);--tr:.12s ease;--ring:color-mix(in srgb,var(--accent) 55%,transparent);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif;--mono:ui-monospace,'Cascadia Mono',Menlo,Consolas,monospace}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(255,176,77,.08),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(46,201,201,.06),transparent 60%),linear-gradient(160deg,#0d1420,#0f1725 50%,#0a0f18)",
        "transit_root": ":root {\n  --bg: #0d1420;\n  --panel-bg: #131c2a;\n  --border: #24334a;\n  --primary: #ffb04d;\n  --primary-dark: #d98a2b;\n  --accent-bus1: #2ec9c9;\n  --accent-bus2: #f0608f;\n  --accent-shuttle: #ffc57a;\n  --text: #dfe7f1;\n  --text-dim: #8ea0b8;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
        "tis_extra": """
/* sustech_midnight — dense command center, high information density */
header{background:#0a1019;border-bottom:1px solid var(--border)}
header h1{font-size:1rem;letter-spacing:.02em}
.wrap{gap:6px;padding:6px}
.col{border-radius:var(--radius);box-shadow:var(--shadow-1)}
.sub{padding:.5rem .7rem}
.sub h2{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase}
.c-card{padding:.4rem .6rem;border-bottom:1px solid var(--border)}
.c-card .code{font-family:var(--mono);font-size:.74rem}
.c-card .nm{font-size:.8rem}
.stat{font-size:.7rem}
.results-header{font-size:.72rem}
.step-chip{border-radius:4px;padding:.22rem .5rem .22rem .3rem;font-size:.72rem}
.step-num{width:1.1rem;height:1.1rem;font-size:.62rem}
button,select,input{font-size:12px}
.slot-tag{font-size:.66rem;padding:.04rem .3rem}
""",
    },

    # ── aurora glass gradient (dark, translucent) ───────────────────────
    "sustech_aurora": {
        "dark": True,
        "tis_root": ":root{--bg:#111a36;--panel:rgba(26,36,66,.72);--panel2:rgba(33,45,80,.6);--border:rgba(120,140,210,.28);--txt:#eef2ff;--mut:#9aa8cf;--fg:#eef2ff;--teal:#24345f;--teal2:#67e8f9;--accent:#a78bfa;--accent2:#c4b5fd;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent-rgb:167 139 250;--accent-dark:#7c5ce0;--radius:18px;--radius-sm:12px;--shadow-1:0 4px 12px rgba(5,8,28,.4),0 16px 44px rgba(5,8,28,.35);--shadow-2:0 8px 20px rgba(5,8,28,.55),0 26px 64px rgba(5,8,28,.5);--tr:.25s cubic-bezier(.2,.8,.2,1);--ring:color-mix(in srgb,var(--accent) 55%,transparent);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(167,139,250,.20),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(103,232,249,.14),transparent 60%),linear-gradient(160deg,#0f1530,#151f40 50%,#0c1226)",
        "transit_root": ":root {\n  --bg: #111a36;\n  --panel-bg: rgba(26,36,66,.85);\n  --border: rgba(120,140,210,.3);\n  --primary: #a78bfa;\n  --primary-dark: #7c5ce0;\n  --accent-bus1: #67e8f9;\n  --accent-bus2: #f472b6;\n  --accent-shuttle: #fbbf24;\n  --text: #eef2ff;\n  --text-dim: #9aa8cf;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
        "tis_extra": """
/* sustech_aurora — glass gradient, translucent panels, glow */
header{background:rgba(17,26,54,.55);border-bottom:1px solid var(--border);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
.wrap{gap:16px;padding:16px}
.col{backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow-1)}
.sub{background:transparent;border-bottom:1px solid var(--border)}
.sub h2{letter-spacing:.16em;background:linear-gradient(90deg,var(--accent),var(--teal2));-webkit-background-clip:text;background-clip:text;color:transparent}
.c-card{border-radius:var(--radius-sm);border:1px solid var(--border);background:rgba(26,36,66,.5);backdrop-filter:blur(6px);margin:.4rem .35rem}
.c-card:hover{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),var(--shadow-2)}
.c-card .mini-card .mc-rating{background:rgba(var(--accent-rgb),.18)}
.stepper{background:transparent}
.step-chip{background:rgba(26,36,66,.5);border-color:var(--border);backdrop-filter:blur(6px)}
.step-chip.active{box-shadow:0 0 16px rgba(var(--accent-rgb),.35)}
table.grid th{background:rgba(26,36,66,.5)}
""",
    },

    # ── paper editorial (light, serif) ──────────────────────────────────
    "sustech_paper": {
        "dark": False,
        "tis_root": ":root{--bg:#f7f2e8;--panel:#fffdf8;--panel2:#f0e9db;--border:#e0d5c0;--txt:#2b2620;--mut:#7a6f5f;--fg:#2b2620;--teal:#23303a;--teal2:#8a6d3b;--accent:#b0531a;--accent2:#c97a3c;--ok:#4d8b59;--warn:#a8842e;--bad:#a4473b;--accent-rgb:176 83 26;--accent-dark:#8a4112;--radius:4px;--radius-sm:2px;--shadow-1:0 1px 0 rgba(70,55,30,.08),0 4px 14px rgba(70,55,30,.06);--shadow-2:0 2px 0 rgba(70,55,30,.1),0 12px 30px rgba(70,55,30,.12);--tr:.18s ease;--ring:color-mix(in srgb,var(--accent) 45%,transparent);--disp:Georgia,'Times New Roman','Songti SC','SimSun',serif;--sans:'Segoe UI',system-ui,sans-serif}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(176,83,26,.06),transparent 60%),linear-gradient(160deg,#f7f2e8,#fdfaf3 45%,#efe7d6)",
        "transit_root": ":root {\n  --bg: #f7f2e8;\n  --panel-bg: #fffdf8;\n  --border: #e0d5c0;\n  --primary: #b0531a;\n  --primary-dark: #8a4112;\n  --accent-bus1: #4d8b59;\n  --accent-bus2: #c2576b;\n  --accent-shuttle: #a8842e;\n  --text: #2b2620;\n  --text-dim: #7a6f5f;\n  --shadow: 0 2px 8px rgba(70,55,30,0.14);\n}",
        "tis_extra": """
/* sustech_paper — editorial, serif headings, hairline rules */
body{font-family:var(--sans)}
header{border-bottom:2px solid var(--ink);background:#fbf7ee}
header h1{font-family:var(--disp);font-weight:700;letter-spacing:.01em}
.wrap{gap:10px;padding:10px;background:transparent}
.col{border-radius:0;border:1px solid var(--border);box-shadow:none;background:#fdfaf3}
.sub{border-bottom:1px solid var(--border);background:transparent}
.sub h2{font-family:var(--disp);font-size:.9rem;letter-spacing:.06em}
.c-card{border-radius:0;border:1px solid transparent;border-bottom:1px solid var(--border);background:transparent;box-shadow:none}
.c-card:hover{background:#fdf8ec;border-left:3px solid var(--accent)}
.c-card .code{font-family:var(--sans);font-weight:600}
.step-chip{border-radius:2px;font-family:var(--disp)}
.step-chip.active{border-bottom:2px solid var(--accent)}
button{border-radius:2px}
.filter-pill{border-radius:2px}
.slot-tag{border-radius:2px}
table.grid th{font-family:var(--disp)}
""",
    },

    # ── neon cyber (dark, glow, grid) ───────────────────────────────────
    "sustech_neon": {
        "dark": True,
        "tis_root": ":root{--bg:#07070f;--panel:rgba(19,19,34,.9);--panel2:rgba(26,26,48,.85);--border:#2c2c4e;--txt:#e8e8ff;--mut:#8f8fc0;--fg:#e8e8ff;--teal:#15153a;--teal2:#22d3ee;--accent:#22d3ee;--accent2:#67e8f9;--ok:#34d399;--warn:#facc15;--bad:#fb7185;--accent-rgb:34 211 238;--accent-dark:#0ea5c9;--radius:10px;--radius-sm:8px;--shadow-1:0 0 0 1px rgba(34,211,238,.10),0 8px 26px rgba(34,211,238,.08);--shadow-2:0 0 0 1px rgba(34,211,238,.28),0 0 30px rgba(34,211,238,.18),0 18px 48px rgba(0,0,0,.5);--tr:.15s ease;--ring:rgba(34,211,238,.6);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif;--mono:ui-monospace,'Cascadia Mono',Menlo,Consolas,monospace}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(34,211,238,.12),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(168,85,247,.14),transparent 60%),linear-gradient(160deg,#07070f,#0c0c1c 50%,#05050b)",
        "transit_root": ":root {\n  --bg: #07070f;\n  --panel-bg: #131322;\n  --border: #2c2c4e;\n  --primary: #22d3ee;\n  --primary-dark: #0ea5c9;\n  --accent-bus1: #34d399;\n  --accent-bus2: #e879f9;\n  --accent-shuttle: #facc15;\n  --text: #e8e8ff;\n  --text-dim: #8f8fc0;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
        "tis_extra": """
/* sustech_neon — cyber grid, neon glow */
body{background-image:linear-gradient(rgba(34,211,238,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(34,211,238,.05) 1px,transparent 1px);background-size:44px 44px}
header{border-bottom:1px solid rgba(34,211,238,.25);background:rgba(7,7,15,.7);backdrop-filter:blur(8px)}
header h1{font-family:var(--mono);letter-spacing:.08em;color:var(--accent)}
.wrap{gap:10px;padding:10px}
.col{border-radius:var(--radius);border:1px solid rgba(34,211,238,.16);box-shadow:var(--shadow-1);backdrop-filter:blur(6px)}
.sub{border-bottom:1px solid rgba(34,211,238,.14);background:transparent}
.sub h2{font-family:var(--mono);letter-spacing:.2em;color:var(--accent)}
.c-card{border-radius:var(--radius-sm);border:1px solid rgba(34,211,238,.12);margin:.35rem .3rem;background:rgba(19,19,34,.7)}
.c-card:hover{box-shadow:0 0 18px rgba(34,211,238,.22);border-color:var(--accent);transform:translateY(-1px)}
.c-card .code{font-family:var(--mono);color:var(--accent2)}
.step-chip{border-radius:999px;font-family:var(--mono);font-size:.72rem;letter-spacing:.04em}
.step-chip.active{border-color:var(--accent);box-shadow:0 0 14px rgba(34,211,238,.4);color:var(--accent)}
button.primary{box-shadow:0 0 16px rgba(34,211,238,.4)}
.slot-tag{font-family:var(--mono)}
.results-header{font-family:var(--mono);font-size:.7rem;letter-spacing:.06em}
""",
    },

    # ── emerald organic jade (light, soft) ──────────────────────────────
    "sustech_emerald": {
        "dark": False,
        "tis_root": ":root{--bg:#eef8f1;--panel:#ffffff;--panel2:#e3f2e9;--border:#cbe7d6;--txt:#113c2b;--mut:#4f7a68;--fg:#113c2b;--teal:#0b3d2e;--teal2:#10b981;--accent:#0e9f6e;--accent2:#2fbd8c;--ok:#2f9e5b;--warn:#c99a2e;--bad:#d64535;--accent-rgb:14 159 110;--accent-dark:#0a7d57;--radius:20px;--radius-sm:14px;--shadow-1:0 2px 6px rgba(11,61,46,.06),0 12px 30px rgba(11,61,46,.08);--shadow-2:0 8px 18px rgba(11,61,46,.12),0 22px 52px rgba(11,61,46,.14);--tr:.22s cubic-bezier(.2,.8,.2,1);--ring:color-mix(in srgb,var(--accent) 45%,transparent);--disp:'Segoe UI',system-ui,'PingFang SC','Microsoft YaHei',sans-serif}",
        "tis_bg": "radial-gradient(1000px 700px at 85% -10%,rgba(16,185,129,.12),transparent 60%),radial-gradient(800px 600px at -10% 110%,rgba(46,201,139,.10),transparent 60%),linear-gradient(160deg,#eef8f1,#f6fdf9 45%,#e1f2e8)",
        "transit_root": ":root {\n  --bg: #eef8f1;\n  --panel-bg: #ffffff;\n  --border: #cbe7d6;\n  --primary: #0e9f6e;\n  --primary-dark: #0a7d57;\n  --accent-bus1: #10b981;\n  --accent-bus2: #f07830;\n  --accent-shuttle: #c99a2e;\n  --text: #113c2b;\n  --text-dim: #4f7a68;\n  --shadow: 0 2px 8px rgba(11,61,46,0.12);\n}",
        "tis_extra": """
/* sustech_emerald — organic jade, soft rounded glass */
header{border-bottom:1px solid var(--border);background:rgba(255,255,255,.7);backdrop-filter:blur(10px)}
header h1{color:var(--teal)}
.wrap{gap:16px;padding:16px}
.col{border-radius:var(--radius);border:1px solid var(--border);box-shadow:var(--shadow-1)}
.sub{border-bottom:1px solid var(--border);background:linear-gradient(180deg,#fff,color-mix(in srgb,#fff 70%,var(--panel2)))}
.sub h2{letter-spacing:.14em;color:var(--teal)}
.c-card{border-radius:var(--radius-sm);border:1px solid var(--border);margin:.4rem .35rem;background:#fff}
.c-card:hover{border-color:var(--accent);transform:translateY(-2px) rotate(.2deg);box-shadow:var(--shadow-2)}
.c-card .code{color:var(--accent-dark)}
.step-chip{border-radius:999px}
.step-chip.active{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,var(--panel))}
.step-chip.done{background:color-mix(in srgb,var(--ok) 12%,var(--panel))}
button{border-radius:var(--radius-sm)}
button.primary{border-radius:999px;padding-left:1.1rem;padding-right:1.1rem}
table.grid th{border-radius:8px 8px 0 0}
""",
    },
}


def generate_tis(name: str, dest: Path) -> None:
    spec = SKINS[name]
    txt = DEFAULT_TIS.read_text(encoding="utf-8")
    txt = _tokenize(txt)
    txt = _replace_root(txt, spec["tis_root"])
    txt = _replace_body_bg(txt, spec["tis_bg"])
    # theme tint tokens: later :root overrides the palette's defaults so row
    # striping / chip surfaces follow the theme (dark = white tints, light =
    # black tints)
    tints = ("--row-tint-odd:rgba(255,255,255,.08);--row-tint-even:rgba(255,255,255,.04);--chip-bg:rgba(255,255,255,.08)"
             if spec.get("dark") else
             "--row-tint-odd:rgba(0,0,0,.03);--row-tint-even:rgba(0,0,0,.015);--chip-bg:rgba(0,0,0,.06)")
    txt = _append_before_style(txt, f":root{{{tints}}}")
    txt = _append_before_style(txt, spec["tis_extra"])
    (dest / "tis.html").write_text(txt, encoding="utf-8")


def generate_transit(name: str, dest: Path) -> None:
    spec = SKINS[name]
    txt = (TRANSIT_BASE / "static" / "style.css").read_text(encoding="utf-8")
    txt = re.sub(r":root\s*\{[^}]*\}", spec["transit_root"], txt, count=1)
    (dest / "transit" / "static" / "style.css").write_text(txt, encoding="utf-8")


def manifest(name: str, version: str) -> str:
    import json
    return json.dumps({
        "name": name, "version": version, "requires": REQUIRES,
        "entry": "index.html", "api": API, "author": "sustech-survival",
    }, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    HOME_SKINS.mkdir(parents=True, exist_ok=True)
    for name, spec in SKINS.items():
        dest = HOME_SKINS / name
        if not dest.is_dir():
            print(f"SKIP {name}: {dest} missing (copy the skin dir there first)")
            continue
        # keep the skin's existing manifest/index.html; regenerate inner pages
        generate_tis(name, dest)
        if (dest / "transit" / "static").is_dir():
            generate_transit(name, dest)
        print(f"OK {name} -> {dest}")


if __name__ == "__main__":
    main()

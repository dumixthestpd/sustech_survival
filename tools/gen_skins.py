# -*- coding: utf-8 -*-
"""WebUI skin generator.

Transforms the canonical TIS course-selector template and the transit base
with a display-redesign layer, then regenerates each themed skin's
``tis.html`` / ``transit/static/style.css`` into the user's home dotdir
(``~/.sustech_survival/skins/<name>/``) — the runtime skin store.

The module itself ships ONLY the ``default`` fallback skin; every other
skin is generated here and lives in home. Run:

    python tools/gen_skins.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "src" / "sustech_survival" / "webui" / "templates" / "tis.html"
DEFAULT_TIS = REPO / "src" / "sustech_survival" / "webui" / "skins" / "default" / "static" / "tis.html"
TRANSIT_BASE = REPO / "src" / "sustech_survival" / "transit" / "web"
DEFAULT_TRANSIT_CSS = (REPO / "src" / "sustech_survival" / "webui" / "skins"
                       / "default" / "static" / "transit" / "static" / "style.css")

sys.path.insert(0, str(REPO / "src"))
from sustech_survival._cache import config_root  # noqa: E402

HOME_SKINS = config_root() / "skins"

REQUIRES = "2026.8.0"
API = [
    "/api/tis/info", "/api/tis/courses", "/api/tis/enrolled",
    "/api/tis/course-types", "/api/tis/round", "/api/tis/bids",
    "/api/transit/live", "/api/nces/status",
]

# ── display-redesign layers (palette-agnostic; use var(--…)) ──────────────
TIS_REDESIGN = """
/* ═══════ display redesign layer ═══════
   Floating panel layout, card-based course rows, polished schedule grid,
   refined stepper, micro-interactions. Palette-agnostic (var(--…)). */
:root{--radius:12px;--radius-sm:8px;
  --shadow-1:0 1px 2px rgba(0,0,0,.20),0 8px 22px rgba(0,0,0,.14);
  --shadow-2:0 6px 14px rgba(0,0,0,.24),0 18px 44px rgba(0,0,0,.26);
  --tr:.18s cubic-bezier(.2,.8,.2,1);
  --ring:color-mix(in srgb,var(--accent) 55%,transparent)}
/* floating panels instead of a glued grid */
.wrap{background:transparent;gap:12px;padding:12px;height:calc(100vh - 53px)}
.col{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow-1)}
/* header + sub panels */
header{background:linear-gradient(180deg,var(--panel),color-mix(in srgb,var(--panel) 88%,var(--bg)));box-shadow:0 1px 0 var(--border),0 8px 24px rgba(0,0,0,.12)}
header h1{font-weight:700;letter-spacing:-.01em}
.sub{background:linear-gradient(180deg,var(--panel),color-mix(in srgb,var(--panel) 92%,var(--bg)));border-bottom:1px solid var(--border)}
.sub h2{font-weight:600;letter-spacing:.1em}
.stat{border-bottom:1px solid var(--border)}
/* stepper as a progress rail */
.stepper{border-bottom:1px solid var(--border);background:transparent;padding:.85rem 1.1rem}
.step-chip{background:var(--panel2);border-color:var(--border);box-shadow:0 1px 2px rgba(0,0,0,.14)}
.step-chip.active{box-shadow:0 0 0 3px var(--ring)}
.step-chip.done{box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 30%,transparent)}
.step-connector{height:2px;border-radius:2px;background:linear-gradient(90deg,var(--border),transparent)}
/* course results as real cards */
.results{padding:.45rem}
.results-header{margin:.25rem .25rem 0;border-radius:var(--radius-sm) var(--radius-sm) 0 0;background:var(--panel2)}
.c-card{background:var(--panel);border:1px solid var(--border);border-left:3px solid transparent;border-radius:var(--radius-sm);margin:.28rem .25rem;padding:.62rem .85rem;box-shadow:0 1px 3px rgba(0,0,0,.10);animation:card-in .22s ease both;transition:transform var(--tr),box-shadow var(--tr),border-color var(--tr),border-left-color var(--tr)}
.c-card:hover{transform:translateY(-2px);border-color:var(--accent);border-left-color:var(--accent);box-shadow:var(--shadow-2)}
.c-card.active{border-left-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--panel))}
.c-card.checked{border-left-color:var(--ok);background:color-mix(in srgb,var(--ok) 9%,var(--panel))}
@keyframes card-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
/* schedule grid polish */
table.grid{border-collapse:separate;border-spacing:1px}
table.grid th{background:var(--panel2);color:var(--mut);border-radius:4px 4px 0 0}
table.grid td{height:38px}
.blk{border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.35);border:1px solid rgba(255,255,255,.18)}
.blk:hover{outline:2px solid var(--ring)}
.persistent-grid,.block-section{border-radius:var(--radius);box-shadow:var(--shadow-1)}
.grid-legend-h .grid-legend{padding:.2rem 0}
/* compare / eval / bid surfaces */
.cmp-card,.brief-card,.eval-item{border-radius:var(--radius-sm);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.bid-panel-relaxed .bid-box{border-radius:var(--radius);box-shadow:var(--shadow-1)}
.bid-panel-relaxed .bid-box:hover{box-shadow:var(--shadow-2)}
/* buttons + inputs */
button{border-radius:var(--radius-sm)}
button.primary{box-shadow:0 2px 10px color-mix(in srgb,var(--accent) 35%,transparent)}
select,input,button{transition:border-color .15s ease,box-shadow .15s ease,background .15s ease,transform .1s ease}
button:active{transform:scale(.97)}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--ring);outline-offset:1px}
/* filter pills + badges */
.filter-pill{background:var(--panel2);border:1px solid var(--border);box-shadow:0 1px 2px rgba(0,0,0,.10)}
.filter-pill:hover{transform:translateY(-1px);border-color:var(--accent)}
.slot-tag,.badge{border:1px solid var(--border)}
/* loading bar + flash */
#loading-bar{height:3px}
#loading-bar .lb-fill{background:linear-gradient(90deg,var(--accent),var(--accent2,var(--accent)),var(--accent));background-size:200% 100%}
.flash{border-radius:var(--radius-sm);backdrop-filter:blur(6px)}
/* scrollbars + selection */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--mut) 30%,transparent);border-radius:8px;border:2px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--accent) 55%,transparent);background-clip:padding-box}
*{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--mut) 30%,transparent) transparent}
::selection{background:color-mix(in srgb,var(--accent) 35%,transparent)}
/* reduced motion */
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
"""

TRANSIT_REDESIGN = """
/* ═══════ display redesign layer ═══════ */
:root{--radius:12px;--radius-sm:8px;
  --shadow:0 2px 8px rgba(0,0,0,.08),0 10px 30px rgba(0,0,0,.10)}
#sidebar,.panel{border-radius:var(--radius);box-shadow:var(--shadow)}
button,.btn,select,input{border-radius:8px;transition:all .15s ease}
button:hover,.btn:hover{filter:brightness(1.06);transform:translateY(-1px)}
.day-toggle button{border-radius:999px}
.suggestions{border-radius:var(--radius-sm);box-shadow:var(--shadow)}
.suggestions li{border-radius:6px}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:rgba(120,120,150,.35);border-radius:6px}
*{scrollbar-width:thin}
"""

# ── per-skin palettes (tis :root, tis body bg, transit :root) ─────────────
SKINS = {
    "sustech_official_light": {
        "tis_root": ":root{--bg:#f5f6fa;--panel:#ffffff;--panel2:#eef1f6;--border:#d8dee8;--txt:#1a2233;--mut:#5d6b80;--fg:#1a2233;--teal:#003030;--teal2:#18a8a8;--accent:#dc6400;--accent2:#f07830;--ok:#2f9e5b;--warn:#e0941f;--bad:#d64535;--accent-rgb:220 100 0;--accent-dark:#b34a00}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(220,100,0,.12),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(24,168,168,.10),transparent 60%),linear-gradient(160deg,#fafbfc,#ffffff 45%,#eef1f6)",
        "transit_root": ":root {\n  --bg: #f5f6fa;\n  --panel-bg: #ffffff;\n  --border: #dfe4ec;\n  --primary: #dc6400;\n  --primary-dark: #b34a00;\n  --accent-bus1: #18a8a8;\n  --accent-bus2: #f07830;\n  --accent-shuttle: #dc6400;\n  --text: #1a2233;\n  --text-dim: #5d6b80;\n  --shadow: 0 2px 8px rgba(0,0,0,0.12);\n}",
    },
    "sustech_orange": {
        "tis_root": ":root{--bg:#17130d;--panel:#221b12;--panel2:#2c2317;--border:#3d3222;--txt:#f0e7d8;--mut:#b3a183;--fg:#f0e7d8;--teal:#3a2a10;--teal2:#ffb45e;--accent:#ed7005;--accent2:#ff9e3d;--ok:#6fbf73;--warn:#e6b04c;--bad:#ef6a5e;--accent-rgb:237 112 5;--accent-dark:#c05c00}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(237,112,5,.16),transparent 60%),linear-gradient(160deg,#17130d,#1e1810 50%,#120f0a)",
        "transit_root": ":root {\n  --bg: #17130d;\n  --panel-bg: #221b12;\n  --border: #3d3222;\n  --primary: #ed7005;\n  --primary-dark: #c05c00;\n  --accent-bus1: #ff9e3d;\n  --accent-bus2: #f0608f;\n  --accent-shuttle: #ffb45e;\n  --text: #f0e7d8;\n  --text-dim: #b3a183;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
    },
    "sustech_midnight": {
        "tis_root": ":root{--bg:#0e1623;--panel:#16202e;--panel2:#1c2838;--border:#2a3a4e;--txt:#e6edf5;--mut:#93a4b8;--fg:#e6edf5;--teal:#1d3a3a;--teal2:#2ec9c9;--accent:#ff9e3d;--accent2:#ffb45e;--ok:#3ecf7e;--warn:#e6b04c;--bad:#ef6a5e;--accent-rgb:255 158 61;--accent-dark:#c9761f}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(255,158,61,.14),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(46,201,201,.10),transparent 60%),linear-gradient(160deg,#0e1623,#101a28 50%,#0b1119)",
        "transit_root": ":root {\n  --bg: #0e1623;\n  --panel-bg: #16202e;\n  --border: #2a3a4e;\n  --primary: #ff9e3d;\n  --primary-dark: #c9761f;\n  --accent-bus1: #2ec9c9;\n  --accent-bus2: #f0608f;\n  --accent-shuttle: #ffb45e;\n  --text: #e6edf5;\n  --text-dim: #93a4b8;\n  --shadow: 0 2px 8px rgba(0,0,0,0.45);\n}",
    },
    "sustech_aurora": {
        "tis_root": ":root{--bg:#121a33;--panel:#1a2442;--panel2:#212d50;--border:#33406b;--txt:#eef2ff;--mut:#9aa8cf;--fg:#eef2ff;--teal:#2a3a6e;--teal2:#67e8f9;--accent:#a78bfa;--accent2:#c4b5fd;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent-rgb:167 139 250;--accent-dark:#7c5ce0}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(167,139,250,.18),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(103,232,249,.12),transparent 60%),linear-gradient(160deg,#101830,#151f40 50%,#0d1428)",
        "transit_root": ":root {\n  --bg: #121a33;\n  --panel-bg: #1a2442;\n  --border: #33406b;\n  --primary: #a78bfa;\n  --primary-dark: #7c5ce0;\n  --accent-bus1: #67e8f9;\n  --accent-bus2: #f472b6;\n  --accent-shuttle: #fbbf24;\n  --text: #eef2ff;\n  --text-dim: #9aa8cf;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
    },
    "sustech_paper": {
        "tis_root": ":root{--bg:#faf6ef;--panel:#fffdf8;--panel2:#f1ebe0;--border:#e0d6c4;--txt:#2b2620;--mut:#7a6f5f;--fg:#2b2620;--teal:#23303a;--teal2:#8a6d3b;--accent:#b85c1f;--accent2:#cf7a3a;--ok:#4d8b59;--warn:#b08a2e;--bad:#a4473b;--accent-rgb:184 92 31;--accent-dark:#8f4518}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(184,92,31,.08),transparent 60%),linear-gradient(160deg,#faf6ef,#fdfaf4 45%,#f0e8d8)",
        "transit_root": ":root {\n  --bg: #faf6ef;\n  --panel-bg: #fffdf8;\n  --border: #e0d6c4;\n  --primary: #b85c1f;\n  --primary-dark: #8f4518;\n  --accent-bus1: #4d8b59;\n  --accent-bus2: #c2576b;\n  --accent-shuttle: #c99a2e;\n  --text: #2b2620;\n  --text-dim: #7a6f5f;\n  --shadow: 0 2px 8px rgba(70,55,30,0.14);\n}",
    },
    "sustech_neon": {
        "tis_root": ":root{--bg:#0a0a14;--panel:#131322;--panel2:#1a1a30;--border:#2c2c4a;--txt:#e8e8ff;--mut:#8f8fc0;--fg:#e8e8ff;--teal:#1c1c3e;--teal2:#22d3ee;--accent:#22d3ee;--accent2:#67e8f9;--ok:#34d399;--warn:#facc15;--bad:#fb7185;--accent-rgb:34 211 238;--accent-dark:#0ea5c9}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(34,211,238,.12),transparent 60%),radial-gradient(900px 650px at -10% 110%,rgba(168,85,247,.14),transparent 60%),linear-gradient(160deg,#0a0a14,#0d0d1c 50%,#07070e)",
        "transit_root": ":root {\n  --bg: #0a0a14;\n  --panel-bg: #131322;\n  --border: #2c2c4a;\n  --primary: #22d3ee;\n  --primary-dark: #0ea5c9;\n  --accent-bus1: #34d399;\n  --accent-bus2: #e879f9;\n  --accent-shuttle: #facc15;\n  --text: #e8e8ff;\n  --text-dim: #8f8fc0;\n  --shadow: 0 2px 8px rgba(0,0,0,0.5);\n}",
    },
    "sustech_emerald": {
        "tis_root": ":root{--bg:#f0faf4;--panel:#ffffff;--panel2:#e4f3ea;--border:#cde6d8;--txt:#123a2b;--mut:#4f7a68;--fg:#123a2b;--teal:#0b3d2e;--teal2:#10b981;--accent:#0e9f6e;--accent2:#2fbd8c;--ok:#2f9e5b;--warn:#c99a2e;--bad:#d64535;--accent-rgb:14 159 110;--accent-dark:#0a7d57}",
        "tis_bg": "radial-gradient(1100px 700px at 85% -10%,rgba(16,185,129,.12),transparent 60%),linear-gradient(160deg,#f0faf4,#f6fdf9 45%,#e2f3ea)",
        "transit_root": ":root {\n  --bg: #f0faf4;\n  --panel-bg: #ffffff;\n  --border: #cde6d8;\n  --primary: #0e9f6e;\n  --primary-dark: #0a7d57;\n  --accent-bus1: #10b981;\n  --accent-bus2: #f07830;\n  --accent-shuttle: #c99a2e;\n  --text: #123a2b;\n  --text-dim: #4f7a68;\n  --shadow: 0 2px 8px rgba(11,61,46,0.12);\n}",
    },
}


def _tokenize_tis(txt: str) -> str:
    """Replace hardcoded accent literals with CSS vars (both the template's
    blue accent and the older orange accent bases)."""
    txt = txt.replace("rgba(91,157,255,", "rgba(var(--accent-rgb),")
    txt = txt.replace("rgba(220,100,0,", "rgba(var(--accent-rgb),")
    txt = txt.replace("#7fb0ff", "var(--accent2)")
    txt = txt.replace("#dc6400", "var(--accent)")
    txt = txt.replace("#b34a00", "var(--accent-dark)")
    return txt


def _replace_root(txt: str, root_css: str) -> str:
    txt = re.sub(r":root\{[^}]*\}", "/*__ROOT__*/", txt, count=1)
    txt = txt.replace("/*__ROOT__*/", root_css, 1)
    return txt


def _replace_body_bg(txt: str, body_bg: str) -> str:
    return re.sub(r"(body\{[^}]*?background:)[^}]*",
                  lambda m: m.group(1) + body_bg, txt, count=1)


def transform_template() -> None:
    """Enhance + tokenize + redesign the canonical TIS template (default skin's
    /tis page) and its copy inside the default skin."""
    txt = TEMPLATE.read_text(encoding="utf-8")
    if "display redesign layer" not in txt:
        txt = _tokenize_tis(txt)
        txt = _replace_root(txt, ":root{--bg:#0f1216;--panel:#161b22;--panel2:#1a212b;--border:#262d3a;--txt:#e7e9ee;--mut:#8a93a3;--fg:#e7e9ee;--accent:#5b9dff;--accent2:#7fb0ff;--accent-dark:#4a83d6;--ok:#3fb950;--warn:#e3b341;--bad:#f85149;--accent-rgb:91 157 255}")
        txt = txt.replace("</style>", TIS_REDESIGN + "\n</style>", 1)
        TEMPLATE.write_text(txt, encoding="utf-8")
        DEFAULT_TIS.write_text(txt, encoding="utf-8")
        print("transformed template (tis.html) + default/static/tis.html")


def transform_transit() -> None:
    """Append the transit redesign layer to the base style.css and the copy
    inside the default skin."""
    for css in (TRANSIT_BASE / "static" / "style.css", DEFAULT_TRANSIT_CSS):
        txt = css.read_text(encoding="utf-8")
        if "display redesign layer" not in txt:
            css.write_text(txt.rstrip() + "\n" + TRANSIT_REDESIGN, encoding="utf-8")
    print("transformed transit web style.css + default/static/transit style.css")


def generate_tis(name: str, dest: Path) -> None:
    spec = SKINS[name]
    txt = TEMPLATE.read_text(encoding="utf-8")
    txt = _tokenize_tis(txt)                       # defensive: no raw accents
    txt = _replace_root(txt, spec["tis_root"])
    txt = _replace_body_bg(txt, spec["tis_bg"])
    (dest / "tis.html").write_text(txt, encoding="utf-8")


def generate_transit(name: str, dest: Path) -> None:
    spec = SKINS[name]
    txt = (TRANSIT_BASE / "static" / "style.css").read_text(encoding="utf-8")
    txt = re.sub(r":root\s*\{[^}]*\}", spec["transit_root"], txt, count=1)
    (dest / "transit" / "static" / "style.css").write_text(txt, encoding="utf-8")


def main() -> None:
    transform_template()
    transform_transit()
    HOME_SKINS.mkdir(parents=True, exist_ok=True)
    for name in SKINS:
        dest = HOME_SKINS / name
        # tis.html + transit style.css are generated; everything else
        # (manifest, index.html, transit assets) must already exist in the
        # skin dir (installed/copied there).
        if not dest.is_dir():
            print(f"SKIP {name}: {dest} missing (copy the skin dir there first)")
            continue
        generate_tis(name, dest)
        if (dest / "transit" / "static").is_dir():
            generate_transit(name, dest)
        print(f"OK {name} -> {dest}")


if __name__ == "__main__":
    main()

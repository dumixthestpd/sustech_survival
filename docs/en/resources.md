# External Resources

**What:** Non-SUSTech-authenticated tools — mirrors, OA paper sources, campus maps, official SUSTech pages.

**Use for:** Downloading software mirrors, finding OA papers, checking GPA table, campus navigation.

## Official SUSTech

- [sustech.edu.cn](https://www.sustech.edu.cn)
- [sustech.online](https://sustech.online) — 南科大镜像站
  - GPA换算表（本科）: sustech.online/study → GPA换算表
  - 校园地图 PDF: mirrors.sustech.edu.cn/site/sustech-online/documents/campus-map/
  - 课表镜像: mirrors.sustech.edu.cn/site/sustech-online/documents/
- [tis.sustech.edu.cn](https://tis.sustech.edu.cn) — Teaching Information System
- [bb.sustech.edu.cn](https://bb.sustech.edu.cn) — Blackboard Learn
- [cas.sustech.edu.cn](https://cas.sustech.edu.cn) — CAS login
- [library.sustech.edu.cn](https://library.sustech.edu.cn)
- [primo](https://sustc.primo.exlibrisgroup.com.cn) — Library search

## Grade/GPA Sources

- **Official GPA table**: sustech.online/study → GPA换算表（本科）
  - A=3.94, B+=3.73, C+=3.09, D+=2.08 (NOT the guessed 4.0/3.0/2.0/1.0 scale)
- **lethal233/sustech-tis-converter** — TIS API reference

## Paper Databases

- **RSC**: pubs.rsc.org — via CARSI/Shibboleth
- **WoS**: webofscience.com — via CARSI/Shibboleth
- **CNKI**: cnki.net — via FSSO/Shibboleth
- **arXiv**: arxiv.org — free, no auth
- **Europe PMC**: europepmc.org — free, no auth (sometimes slow off-campus)
- **MDPI**: mdpi.com — 403 off-campus
- **Semantic Scholar**: semanticscholar.org — OA PDFs only

## GitHub Student Resources

- **SUSTech-CRA/sustech-online-ng** — SUSTech online manual (VuePress site)
  - Website: https://sustech.online/ | Stars: 118 | Forks: 86 | Issues: 6
  - Weather API: `https://api.sustech.online/weather`
    - Response: `{"msg": "南科大天气：气温26.8℃，体感29.1℃，近两个小时内无降雨。", "update_time": "...", "code": 602}`
    - Component: `docs/.vuepress/components/weather-span.vue` (`yr.get("https://api.sustech.online/weather")`)
  - Mirrors: https://mirrors.sustech.edu.cn/site/sustech-online/documents/
  - Miniapp repo: `SUSTech-CRA/sustech-online-wxapp`
  - Daily blog: `SUSTech-CRA/sustech-online-daily-blog`
  - License: CC BY-SA 4.0
  - Dev: Node.js v24, pnpm (`pnpm install`, `pnpm run docs:dev`)
- **SUSTech-CRA/sustech-course** — TIS scrape reference, course data model
- **lethal233/sustech-tis-converter** — TIS API (grade endpoint: `/score/scoreList`)
- **Fros1er/SUSTechTISHelper** — TIS JS helper (inactive)

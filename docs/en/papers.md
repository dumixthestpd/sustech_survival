# Papers

Academic paper search and fetch across CrossRef, CNKI, WoS, and RSC.

**Auth:** Database-specific (Shibboleth/CARSI for CNKI/WoS/RSC). CrossRef is public.

**Extras:** `[papers]` extra installs `cloudscraper` for publisher sites that block plain requests.

---

## CLI

```bash
sustech papers search "electrochromic polymer" --max 10
sustech papers search "electrochromic polymer" --min-year 2020
```

---

## Python API

```python
from sustech_survival.papers.search import crossref_search, search_multi

papers = crossref_search("electrochromic polymer", max_results=10, min_year=2020)
papers = search_multi(["electrochromic", "conjugated polymer"], max_per_query=10)
```

```python
from sustech_survival.papers import search_and_fetch

# Search + download PDFs (requires [papers] extra)
results = search_and_fetch(queries=["electrochromic polymer"], dest_dir="./papers")
```
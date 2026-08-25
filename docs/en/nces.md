# NCES (Community Course Evaluation)

Student-built course evaluation community platform — scrapes eval data from nces.sustech.edu.cn.

**Auth:** Session-based (Anubis PoW solver for listing scrape).

**Extras:** `[nces]` extra installs `anubis-solver` for the proof-of-work challenge.

---

## CLI

```bash
sustech nces                     # scrape + display course evaluations
```

---

## Python API

```python
from sustech_survival.nces.scraper import NCESScraper

scraper = NCESScraper()
courses = scraper.list_courses()
evals = scraper.get_evals(course_id="...")
```

The scraper solves an Anubis proof-of-work challenge to access the listing API. Rate-limited with internal throttling.
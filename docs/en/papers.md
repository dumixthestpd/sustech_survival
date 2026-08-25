# Papers

SUSTech paper search and off-campus access.

---

## Q&A

### Can `sustech.papers` fetch subscribed full-text papers via API off-campus?

No. `sustech.papers` only supports off-campus login for the
databases that federate via Shibboleth — **WoS, RSC, CNKI** — by
going through CARSI → SUSTech CAS. Most publisher sites have strict
bot protection: ACS / RSC / Wiley / IEEE are behind Cloudflare;
SciVal / Scopus / Springer are similar. Direct programmatic access
to those is not viable.

For the databases that *do* work off-campus, a real browser
(Playwright) handles the Shibboleth WAYF + IdP consent flow and
lands you on the publisher landing page; the actual full-text
download still happens at human reading speed in that session.
There is no headless / agent-level mass-fetch path for subscribed
content.

I'm not adding scraping to `sustech.papers`. Instead, there is a
separate browser plugin — **`sustech_quickread`** — for off-campus
use. It automates the Shibboleth WAYF / CAS / IdP consent dance
and stores the session cookies, so you click once instead of going
through six redirects each visit.

**Library ToS reminder.** SUSTech Library's
[《电子资源使用规定》](https://lib.sustech.edu.cn/dzzysygd/list.htm)
explicitly prohibits:

- Using network tools to batch-download library e-resources.
- Downloading faster than normal reading speed across multiple papers.
- Downloading whole journal issues or volumes.
- Setting up private proxies or VPNs to share off-campus access.

So: using the API to fetch paper data off-campus is not a good idea.
For Open Access content there are plenty of "Vibe Research" Skills
on Clawhub that can pull OA articles directly.
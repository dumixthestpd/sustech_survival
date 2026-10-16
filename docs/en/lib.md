# Library (Primo)

Search SUSTech's Primo catalog and read book/article metadata. Authentication
uses `LibAuth` and the shared CAS provider. Primo's existing TLS compatibility
context is used on both direct and proxy connection pools; normal proxy
settings can remain enabled. The successful login session retains cookie
domains, paths and rotations when passed to the browser renderer.

Install the renderer and its browser:

```bash
python -m pip install 'sustech_survival[playwright]'
python -m playwright install chromium
sustech lib search '微分几何入门与广义相对论' --limit 8 --json
sustech lib detail <docid> --json
```

```python
from sustech_survival.lib.search import search, detail, LibraryError

try:
    rows = search("微分几何入门与广义相对论", scope="default", limit=8)
    if rows:
        record = detail(rows[0].docid)
except LibraryError as exc:
    print(exc)
```

Search scopes are `catalog` (all resources), `default` (local catalog), and
`eresource` (electronic resources). Queries use the current `/discovery/search`
route. Filters use the Primo URL. Pagination is applied to the renderer's actual
read-only PNX request because Primo resets deep-link offsets to zero. Detail fields
are read by stable field keys, keeping translated UI headings and recommended
books out of titles, ISBNs and publisher fields.

An empty JSON array means Primo confirmed the requested window has no records. Authentication failure,
missing Playwright/Chromium, an HTTP error, a login/challenge redirect or an
unloaded/malformed result page raises `LibraryError`; CLI commands exit nonzero
and keep diagnostics on stderr. CAS network errors identify login versus ticket
exchange and the failing host without printing service tickets or raw responses.
Interactive authentication challenges stop before credentials are posted.

IC room booking uses the separate `lib-booking` service; see
[Library booking](lib-booking.md). A successful catalog query does not establish
publisher full-text access or permission to reserve a room.

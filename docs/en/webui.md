# Web UI

Unified Flask SPA — TIS course selector, campus transit map, NCES eval cards, and iCal export on a single port.

**Extras:** `[webui]` extra installs Flask.

---

## CLI

```bash
sustech webui serve                    # start on default port 61019
sustech webui serve -p 8080 -H 0.0.0.0 # custom port/host
sustech webui open                     # open in default browser
```

---

## Python API

```python
from sustech_survival.webui.app import create_app, run

app = create_app()           # Flask app for WSGI servers
run(port=61019, host="0.0.0.0", debug=False)
```

### Routes

| Route | Description |
|------|-------------|
| `/` | Landing page |
| `/tis` | TIS course selector + schedule grid |
| `/transit` | Campus map + bus navigation |
| `/api/tis/ical` | iCal export of picked schedule |
| `/api/nces/*` | NCES evaluation data endpoints |
| `/api/transit/*` | Transit data endpoints |
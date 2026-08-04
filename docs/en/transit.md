# Transit

Campus bus and walking navigation — schedules, live GPS, route planning.

**Auth:** None (public bus data).

---

## CLI

```bash
sustech transit facilities       # list all known buildings + gates
sustech transit find "图书馆"     # fuzzy name search
sustech transit stops            # list bus stops
sustech transit live             # poll live bus positions
sustech transit route "一教" "图书馆"  # shortest path between facilities
```

---

## Python API

```python
from sustech_survival.transit import transit

facs = transit.list_facilities()
hits = transit.find_facility("图书馆")[:5]
stops = transit.get_bus_stops()
buses = transit.get_live_positions()
route = transit.shortest_path("一教", "图书馆")
```
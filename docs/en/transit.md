# Transit

Campus bus and walking navigation — schedules, live GPS, route planning.

**Auth:** None (public bus data).

---

## CLI

```bash
sustech transit facilities       # list all known buildings + gates
sustech transit find "图书馆"     # fuzzy name search
sustech transit stops                         # Line 1, clockwise by default
sustech transit stops --line XYBS2 --direction ccw
sustech transit live             # poll live bus positions
sustech transit route "一教" "图书馆"  # shortest path between facilities
```

---

## Python API

```python
from sustech_survival.transit import DIR_CW, transit

client = transit()
facs = client.list_facilities()
hits = client.find_facility("图书馆")[:5]
stops = client.get_bus_stops("XYBS1", DIR_CW)
buses = client.get_live_positions()
origin = client.find_facility("一教")[0]
destination = client.find_facility("图书馆")[0]
route = client.shortest_path(origin.facility_id, destination.facility_id)
```

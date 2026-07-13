# Library Booking (IC Rooms)

IC library research room, meeting room, training room, recording studio, 3D printing booking.

**Auth:** `LibBookingClient` — auth-agnostic, pass an authenticated session.

---

## CLI

```bash
sustech lib-booking whoami          # show current user info
sustech lib-booking home-summary    # idle room summary (homepage)
sustech lib-booking policy          # print the library booking policy
```

---

## Python API

```python
from sustech_survival.lib.booking import lib_booking

c = lib_booking()
me = c.whoami()
summary = c.home_summary()
labs = c.labs()
rooms = c.rooms(class_kind=1, date="2026-07-13")
count = c.reservation_count()
my = c.my_reservations()
# c.add_reservation(lab_id=..., date=..., period=...)  # destructive — dry_run first
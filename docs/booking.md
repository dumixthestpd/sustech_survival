# E-Hall Booking (场地预约)

Facility booking — classrooms, meeting rooms, and other campus spaces via e-hall.

**Auth:** `BookingClient` — auth-agnostic, pass any authenticated session.

---

## CLI

```bash
sustech booking whoami            # show current user
sustech booking rooms             # list all rooms
sustech booking rooms "会议室" --available  # filter by keyword, available only
sustech booking my-meetings       # list your current bookings
```

---

## Python API

```python
from sustech_survival.booking import booking

c = booking()
me = c.whoami()
rooms = c.rooms(keyword="会议室")
my = c.my_meetings()
# c.add_meeting(room_id=..., title=..., start=..., end=...)  # destructive — dry_run first
# c.cancel_meeting(meeting_id="...")                        # destructive — dry_run first
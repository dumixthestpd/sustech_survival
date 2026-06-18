---
name: booking
description: ehall 场地预约 (booking.sustech.edu.cn) — SUSTech residential-college venue booking system. List 35 rooms, check availability, view/cancel own meetings, add new bookings (dry-run by default).
owner: Faux
last_updated: 2026-06-18
---

# SUSTech ehall 场地预约 (`booking.sustech.edu.cn`)

> **What this is.** The ehall mini-app **书院活动场地预约** (Residential College
> Activity Venue Reservation) — 35 rooms across the 6 书院 + 致诚/致仁/树仁 etc.
> Meeting rooms, gym rooms, study rooms. Manager approval required for some.
>
> **What this is NOT.** Sports facilities (润扬体育馆 羽毛球/足球) — those are on
> separate WeChat mini-apps / third-party systems, not on ehall.

## Quick start

```bash
# List all rooms
python -m sustech_survival.booking rooms

# Filter by name/type
python -m sustech_survival.booking rooms 自习
python -m sustech_survival.booking rooms 湖畔

# Details for one room
python -m sustech_survival.booking room ZC02

# My bookings
python -m sustech_survival.booking my-meetings

# Dry-run a booking (recommended; no POST)
python -m sustech_survival.booking add \
    --room ZC02 \
    --start 2026-06-20T14:00 \
    --end   2026-06-20T16:00 \
    --title "study" \
    --dry-run

# Actually book (real destructive POST)
python -m sustech_survival.booking add \
    --room ZC02 --start 2026-06-20T14:00 --end 2026-06-20T16:00 \
    --title "study" --participants 3
```

## Authentication

CAS + secondary token handshake (no browser/Playwright needed):

1. `GET https://cas.sustech.edu.cn/cas/login?service=https://booking.sustech.edu.cn/redirect`
   → extract `execution` token
2. `POST` with credentials, `submit="提交"` (Chinese — NOT empty like TIS)
   → 302 with `Location: ...?ticket=ST-...`
3. `GET <ticket URL>` → cookies (TGC) land on `booking.sustech.edu.cn`
4. `POST /api/SystemApi/GetUserProfile`
   `{MessageType:1001, MessageID:<uuid>, Data:{Url:..., St:ticket}}`
   → returns `Data.Token` (UUID) + user profile
5. All subsequent API calls attach `Authorization: <Token>`

Auth is handled by `sustech_survival.sso.authlib.booking.BookingAuth`. The
token lives in `~/.openclaw/workspace/skills/sustech_survival/booking/token.json`,
cookies in `session.json` — both survive process restart.

## API surface

All endpoints are `POST https://booking.sustech.edu.cn/api/SystemApi/{Method}` with body:
```json
{ "MessageType": <int>, "MessageID": "<uuid>", "Data": { ... } }
```

| Method | Used for |
|--------|----------|
| `GetMeetingRoomAllByCondition` | list rooms (paginated) |
| `GetMyMeetings`                 | my bookings (paginated) |
| `GetUserInfo`                   | NOT a whoami — returns paged user list |
| `AddMeeting`                    | create a booking |
| `UpdateMeeting`                 | modify a booking |
| `CancelMeeting`                 | cancel a booking |
| `GetMeetingCalendar`            | schedule view |

See `references/ehall-booking-venue-2026-06-15.md` for the full endpoint map
(80+ methods), `MeetingRoomEquipments` / `MeetingRoomManagers` shapes, and
the `MesageType` typo footnote.

## Programmatic API

```python
from sustech_survival.booking import booking, BookingError

client = booking()                       # auto-logs in
me = client.whoami()                     # {'name':'段斯宸','sid':'12413021',...}
print(me)

# All rooms
for room in client.rooms():
    print(f"[{room.id}] {room.name} cap={room.capacity} hrs={room.bookable_hours_str()}")

# Filter by name/type/location
study_rooms = client.rooms(keyword="自习")

# One room by id (case-insensitive)
zc = client.room_by_id("ZC02")

# My meetings
for m in client.my_meetings():
    print(f"{m.start_at} {m.title}")

# Create (with input validation; raises BookingError on bad inputs)
from datetime import datetime
client.add_meeting(
    room_id="ZC02",
    start=datetime(2026, 6, 20, 14, 0),
    end=datetime(2026, 6, 20, 16, 0),
    title="study",
    participants=3,
)
```

## Pitfalls

1. **`submit="提交"` (Chinese), NOT empty.** TIS uses `submit=""`; ehall sub-apps use `submit="提交"`. Wrong value → CAS returns the login page again instead of a ticket.
2. **Token + cookies are BOTH needed.** The cookie jar carries the CAS session; the `Authorization` header carries the per-app token. Drop either and the API returns `{"IsSuccess": false, "Message": "Authorization is NULL"}`.
3. **`GetUserInfo` is NOT a whoami.** It returns a paged list of ALL users (~11k rows total). For "who am I", use `client.whoami()` which returns the cached profile from login.
4. **Two room id patterns coexist.** Short codes (`ZC02`, `EQBK01`) for legacy rooms, UUIDs for newer ones. Always compare case-insensitively.
5. **Off-campus = HTTP 403 "Access forbidden".** Detect explicitly via `_looks_off_campus()` (matches PMS pattern). Catches the SUSTech firewall before any auth runs.
6. **Manager approval required for some rooms.** Check `room.needs_approval` before booking — `IsApproval: True` means a manager must sign off after submission.
7. **Phone (SJHM) is in the handshake response.** Don't log it; don't write it to disk.
8. **Auto-relogin handles dead tokens.** If the API returns `Authorization is NULL` (or one of `AUTH_ERROR_MESSAGES`), the client re-runs `BookingAuth.login_password()` and retries the call once. Failures propagate as `BookingError`.

## Files

- `booking/__init__.py` — public API
- `booking/booking.py` — `BookingClient` (one client, all ops) + `booking()` singleton
- `booking/schema.py` — `Room`, `Meeting`, `MyMeeting` dataclasses
- `booking/__main__.py` — CLI (`python -m sustech_survival.booking ...`)
- `sso/authlib/booking.py` — `BookingAuth` (CAS + token handshake, persistence)
- `session.json` — saved cookies (relative to skill root)
- `token.json` — saved API token + cached user info

## Tests

- `test_booking_schema.py` — `_time_only` / `_parse_dt` helpers, `from_api()` parsers against canned responses
- `test_booking_module.py` — module surface, constants, off-campus detection, auth-error detection, `add_meeting` input validation

Both pass offline (`pytest test/test_booking_*.py -q` → 37 passed).

## Reference

- `references/ehall-booking-venue-2026-06-15.md` — the original probe notes (auth flow, API surface, room data shape, 35-room catalog)
- `references/ehall-auth-2026-06-01.md` — ehall MAIN host auth (different system; Playwright+JSESSIONID — NOT what we use)
- `references/sustech-firewall-off-campus-403.md` — off-campus detection pattern (shared with PMS)
- `references/building-new-sub-skill.md` — the recipe this module follows (schema-first, one client, CLI with `--json`)

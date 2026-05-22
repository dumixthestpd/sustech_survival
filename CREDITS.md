# Credits & References

## Projects Studied

### xCipHanD/SUSTech_AutoScheduler
https://github.com/xCipHanD/SUSTech_AutoScheduler
- Primary reference for course data model (`Course`, `CourseBundle` types)
- Time code format (4-char hex: week parity + day + period range)
- Vue 3 + Element Plus frontend with schedule grid
- `ScheduleGrid.vue` component structure
- `courseTimeParser.ts` time code parsing logic
- `scheduleAlgo.ts` backtracking scheduler (with known bugs)
- TIS browser injection plugin pattern

### lethal233/sustech-tis-converter
https://github.com/lethal233/sustech-tis-converter
- Early exploration of TIS REST API endpoints
- Course code → schedule mapping approach

### Fros1er/SUSTechTISHelper
https://github.com/Fros1er/SUSTechTISHelper
- Referenced for TIS helper utilities

### SUSTech-CRA/awesome-sustech-service-tools
https://github.com/SUSTech-CRA/awesome-sustech-service-tools
- Curated list of SUSTech service tools and API references

## TIS APIs Used

- `POST /Xsxktz/queryRwxxcxList` — 全校课表 course section search
- `POST /user/mk` — feature menu tree
- `POST /user/getMknodeMore` — sub-feature nodes
- `POST /component/queryKsxxByXs` — exam schedule
- `GET /user/me` — student info
- CAS login at `/cas/login`

## Known Bugs in xCipHanD/SUSTech_AutoScheduler

1. **Conflict detection false negative**: `checkConflict()` stores one time code per course (e.g. `057` = periods 5-7).
   When checking a 7-8 course, it looks for `078` in the Set — different code, returns false.
   A 5-7 course and a 7-8 course are NOT detected as conflicting.

2. **Period-level rendering collapse**: `startRow = floor((startSlot-1)/2)` maps periods 5,6,7 all to row 2 (5-6 slot).
   A 5-7 period course renders only in row 2 — period 7 is invisible.
   This is why CAD lab (5-7 periods) looked like only 5-6 periods.

3. **`isExperiment` misidentifies letter-suffix sections**: Checks `kcdm` last char non-digit → assumes lab.
   But TIS letter suffixes are often section identifiers, not separate lab courses.

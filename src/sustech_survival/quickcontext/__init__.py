"""
DEPRECATED — use sustech_survival.context instead.

This module re-exports the new Context class for backwards compat.
The old QuickContext / DetailedContext names are gone — use
Context(level="terse"|"normal"|"verbose") instead.

The shim emits a DeprecationWarning on import. To silence:
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning,
                            module="sustech_survival.quickcontext")
"""
import warnings

warnings.warn(
    "sustech_survival.quickcontext is deprecated; "
    "use sustech_survival.context.Context(level=...) instead",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the new location so old import paths still work.
from sustech_survival.context import (  # noqa: F401, E402
    # The class + enum
    Context, Level,
    # Constants (used by Part B schedule_index and any other callers)
    CHINA_TZ, SUSTECH_LAT, SUSTECH_LON,
    ACADEMIC_CALENDARS, HOLIDAY_DATA,
    OVERRIDE_TIME,
    # Time helper
    now_,
    # I/O fetchers
    fetch_json, fetch_weather, fetch_aqi, fetch_library_status,
    fetch_next_deadline, fetch_next_eval, fetch_next_exam,
    # Schedule helpers (used by Context.class_now)
    slot_times, entry_time_range, entry_name, get_schedule_reminder,
    # Academic / holiday helpers
    get_academic_info, is_holiday,
    aqi_level, aqi_icon,
)

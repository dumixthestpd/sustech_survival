"""
sustech_survival.tis.classroom — TIS venue borrowing (场地借用) booking module.

Public API::

    from sustech_survival.tis.classroom.booking import (
        venue_borrow, VenueBorrowClient, BorrowError,
    )
    from sustech_survival.tis.classroom.booking_schema import (
        BorrowApplication, BorrowDetail, BorrowTimeSlot,
        AuditStatus, PermissionResult, VenueOccupancySlot,
    )
"""
from . import booking as booking

__all__ = ["booking"]

"""Conservative availability checks for BB content discovery.

Only an explicit ``No`` is sufficient to skip a listed content item. ``Yes``
is not a permission guarantee; partial visibility, release conditions, and
missing metadata must still go through the normal read/error handling.
"""

from collections.abc import Mapping


def is_explicitly_unavailable(content: Mapping) -> bool:
    """Whether the current content listing explicitly marks an item unavailable."""
    availability = content.get("availability")
    return isinstance(availability, Mapping) and availability.get("available") == "No"

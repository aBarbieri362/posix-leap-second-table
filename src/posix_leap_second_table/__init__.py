"""POSIX leap-second table.

Parses the IETF ``leap-seconds.list`` file and serves TAI-UTC offset
lookups keyed by Unix timestamp.

See :class:`posix_leap_second_table.core.LeapSecondTable` for the
public entry point.
"""

from .core import LeapSecondTable, LeapEntry, ParseError

__all__ = ["LeapSecondTable", "LeapEntry", "ParseError"]

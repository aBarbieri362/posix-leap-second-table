"""Parse IETF leap-seconds.list and look up the TAI-UTC offset.

The file format (inofficial but stable since the mid-1990s) is
documented in the comments at the top of
``https://www.ietf.org/timezones/data/leap-seconds.list``. Each data
line looks like::

    2272060800 10  # 1 Jan 1972

Column 1 is the NTP timestamp at which the offset changes (seconds since
1900-01-01 00:00:00 UTC), column 2 is the new TAI-UTC offset in seconds,
and the comment is a human-readable date.

The library interprets *Unix timestamps* on input, so the NTP epochs on
data lines are converted to Unix epochs by subtracting the NTP/Unix epoch
offset of 2208988800 seconds. We do NOT try to resolve the "during the
leap second" ambiguity; the table is consulted with a plain Unix integer
second, and the returned offset is the one that was in force at that
second.

Only the happy-path entries above are parsed; update lines (``#``
followed by ``File expires on``) and hash lines (``#h``) are recognised
only to the extent of being skipped. This is the one interpretation we
commit to: lines that are not blank, not comments, not ``#@``, and not
``#h`` are required to be leap entries or we raise ``ParseError``.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple

# Difference, in whole seconds, between the NTP epoch (1900-01-01
# 00:00:00 UTC) and the POSIX epoch (1970-01-01 00:00:00 UTC).
#
# Leap seconds did not exist before 1972; for the purposes of the table
# (which is published with NTP timestamps), the constant 2208988800 has
# been used in every reference implementation we are aware of and is
# exactly 70 years * 365 days plus 17 leap days, expressed in seconds.
# Using it as an integer is correct and intentional: leap seconds are
# the very thing we are tabulating, and attempting to account for them
# when converting the epoch offset would be circular.
NTP_TO_UNIX_EPOCH = 2208988800

# Sentinel used by upstream for "no entry yet". Exposed so a caller can
# recognise that a timestamp predates the first leap entry.
PRE_TABLE_OFFSET = 0


class ParseError(ValueError):
    """Raised when a line cannot be parsed as a leap entry or a comment."""


@dataclass(frozen=True)
class LeapEntry:
    """One row of the leap-seconds.list file, with Unix epoch.

    ``when_unix`` is the first Unix second at which ``offset`` is in
    force. ``ntp_timestamp`` and ``description`` preserve the raw fields
    for callers who need to reconstruct the original file.
    """

    when_unix: int
    offset: int
    ntp_timestamp: int
    description: str = ""

    def __post_init__(self) -> None:
        # Negative offsets have never occurred in practice, but rejecting
        # them here means a typo'd fixture fails loudly instead of
        # silently producing a nonsense offset.
        if self.offset < 0:
            raise ValueError(f"offset must be non-negative, got {self.offset}")


def _strip_comment(text: str) -> str:
    """Return the text of a ``#``-prefixed line, without the hash.

    Whitespace is collapsed to a single leading space so callers can
    split on the first space reliably.
    """
    return text[1:].strip()


def _is_directive(rest: str) -> bool:
    """Return True if the (already de-hashed) comment text is a directive.

    Directives we recognise and skip: ``@`` (arbitrary integer pairs the
    file uses for its own bookkeeping) and ``h`` (a hash of the table).
    Anything else starting with a letter is treated as ordinary prose.
    """
    if not rest:
        return False
    first = rest[0]
    return first in ("@", "h")


def _parse_entry_line(line: str) -> Optional[LeapEntry]:
    """Parse a single non-comment line, or return ``None`` if it is blank.

    Raises ``ParseError`` if the line has content that does not match
    the two-integer-plus-optional-comment shape of a leap entry.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Split off any trailing comment on the data line itself. The
    # upstream file always has one, but being defensive about lines
    # without comments costs nothing.
    hash_pos = stripped.find("#")
    if hash_pos >= 0:
        data_part = stripped[:hash_pos].strip()
        comment_part = _strip_comment(stripped[hash_pos:])
    else:
        data_part = stripped
        comment_part = ""

    fields = data_part.split()
    if len(fields) != 2:
        raise ParseError(
            f"expected exactly two integer fields, got {len(fields)}: {line!r}"
        )

    try:
        ntp_ts = int(fields[0])
        offset = int(fields[1])
    except ValueError as exc:
        raise ParseError(f"non-integer field in line: {line!r}") from exc

    when_unix = ntp_ts - NTP_TO_UNIX_EPOCH
    return LeapEntry(
        when_unix=when_unix,
        offset=offset,
        ntp_timestamp=ntp_ts,
        description=comment_part,
    )


class LeapSecondTable:
    """An in-memory leap-second table optimised for offset lookup.

    The table is loaded once and is immutable thereafter. Lookups are
    O(log n) via :func:`bisect.bisect_right` on the Unix-timestamp keys.

    ``clock`` is taken as a constructor argument so that callers who
    need "the current offset" can inject a fake clock in tests. The
    default is :func:`time.time` and is used only by
    :meth:`offset_now`.
    """

    def __init__(
        self,
        lines: Iterable[str],
        *,
        clock: Callable[[], float] = None,
    ) -> None:
        # Import locally so that simply constructing a table from a
        # string never imports the time module if a clock is supplied.
        # This keeps the object usable in environments where ``time``
        # is stubbed out.
        if clock is None:
            import time

            def _real_clock() -> float:
                return time.time()

            clock = _real_clock

        entries: List[LeapEntry] = []
        last_unix: Optional[int] = None
        last_offset: Optional[int] = None

        for lineno, raw in enumerate(lines, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue

            if line.lstrip().startswith("#"):
                rest = _strip_comment(line.lstrip())
                if _is_directive(rest):
                    continue
                # Ordinary prose comment. Skipped.
                continue

            try:
                entry = _parse_entry_line(line)
            except ParseError as exc:
                raise ParseError(f"line {lineno}: {exc}") from exc

            if entry is None:
                continue

            # The upstream file is required to be strictly increasing in
            # timestamp and non-decreasing in offset. Reject anything
            # else rather than silently returning wrong offsets for
            # ranges that would overlap.
            if last_unix is not None and entry.when_unix <= last_unix:
                raise ParseError(
                    f"line {lineno}: timestamps must strictly increase "
                    f"(previous unix={last_unix}, this unix={entry.when_unix})"
                )
            if last_offset is not None and entry.offset < last_offset:
                raise ParseError(
                    f"line {lineno}: offsets must not decrease "
                    f"(previous={last_offset}, this={entry.offset})"
                )

            entries.append(entry)
            last_unix = entry.when_unix
            last_offset = entry.offset

        if not entries:
            raise ParseError("no leap entries found in input")

        self._entries: Tuple[LeapEntry, ...] = tuple(entries)
        self._keys: Tuple[int, ...] = tuple(e.when_unix for e in self._entries)
        self._clock = clock

    # ----- introspection ------------------------------------------------

    @property
    def entries(self) -> Tuple[LeapEntry, ...]:
        """The parsed leap entries, in increasing Unix-timestamp order."""
        return self._entries

    @property
    def latest(self) -> LeapEntry:
        """The last (highest-timestamp) entry in the table."""
        return self._entries[-1]

    @property
    def first(self) -> LeapEntry:
        """The first (lowest-timestamp) entry in the table."""
        return self._entries[0]

    # ----- lookup -------------------------------------------------------

    def offset_at(self, unix_ts: int) -> int:
        """Return the TAI-UTC offset in force at ``unix_ts``.

        ``unix_ts`` is a POSIX integer second. Behaviour for timestamps
        before the first entry is defined: we return ``0``, matching the
        historical fact that TAI-UTC was zero before 1972. Behaviour for
        timestamps after the last entry is also defined: we return the
        last offset, since we have no knowledge of future leap seconds.
        Callers who need to know whether they are extrapolating into the
        future should compare ``unix_ts`` to :attr:`latest.when_unix`.
        """
        idx = bisect_right(self._keys, unix_ts)
        if idx == 0:
            return PRE_TABLE_OFFSET
        return self._entries[idx - 1].offset

    def entry_at(self, unix_ts: int) -> Optional[LeapEntry]:
        """Return the :class:`LeapEntry` whose offset is in force.

        Returns ``None`` for timestamps before the first entry, so
        callers can distinguish "no offset" from "offset zero" (the
        first real entry has offset 10, so the two are genuinely
        different).
        """
        idx = bisect_right(self._keys, unix_ts)
        if idx == 0:
            return None
        return self._entries[idx - 1]

    def offset_now(self) -> int:
        """Offset in force at the current Unix time, per the injected clock.

        Included as a convenience; tests inject a fake clock.
        """
        return self.offset_at(int(self._clock()))

    def offset_intervals(self) -> List[Tuple[int, int, int]]:
        """Return ``(start_unix, end_unix_exclusive, offset)`` tuples.

        The final interval has ``end_unix`` set to a very large sentinel
        so callers can iterate without special-casing the tail.
        """
        intervals: List[Tuple[int, int, int]] = []
        for i, entry in enumerate(self._entries):
            start = entry.when_unix
            if i + 1 < len(self._entries):
                end = self._entries[i + 1].when_unix
            else:
                end = 1 << 62
            intervals.append((start, end, entry.offset))
        return intervals

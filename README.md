posix-leap-second-table
=======================

Parses the IETF `leap-seconds.list` file and returns the TAI-UTC offset for any Unix timestamp.

```python
from posix_leap_second_table import LeapSecondTable

# Minimal inline sample; the real file is much longer.
lines = [
    "2272060800 10  # 1 Jan 1972",
    "3124136000 37  # 1 Jan 2017",
]
table = LeapSecondTable(lines)
print(table.offset_at(0))           # 0, before 1972
print(table.offset_at(63072000))    # 10, the first entry
print(table.offset_now())           # current offset
```

Exported names: `LeapSecondTable`, `LeapEntry`, `ParseError`.

Why this exists
---------------

Code that converts between TAI and UTC needs to know how many leap seconds have been inserted to date. The canonical source is the IETF `leap-seconds.list` file, whose format is a handful of NTP-timestamp + offset pairs interleaved with comments. This library turns that file into an immutable lookup table indexed by Unix timestamp, with no runtime dependencies.

The trade-off is simplicity over freshness: the table is whatever you loaded, and there is no auto-update. Callers who need "current" offset must reload the file themselves.

The awkward edge
---------------

The file uses NTP timestamps (seconds since 1900-01-01 UTC). We subtract the constant `2208988800` to convert them to Unix timestamps. This constant is an integer exactly 70 years long in SI seconds; treating it as fixed is the one deliberate interpretation in the library. If a caller feeds timestamps that land inside an actual leap second (e.g. `2016-12-31T23:59:60Z`), the result is the offset in force at the start of that second. We do not attempt to resolve the sub-second ambiguity.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.


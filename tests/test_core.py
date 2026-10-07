import unittest

from posix_leap_second_table.core import (
    LeapEntry,
    LeapSecondTable,
    ParseError,
    NTP_TO_UNIX_EPOCH,
)


# A trimmed but real excerpt of the upstream leap-seconds.list. The
# timestamps and offsets are taken verbatim; only the number of entries
# is reduced for readability.
SAMPLE_LINES = [
    "#",
    "# The following table shows pairs of the form:",
    "#",
    "#     NTP timestamp  TAI-UTC offset",
    "#",
    "#@ 3612265600",
    "#",
    "#h 5b31a0a3 c2e6b3e5 2015 jan 1"
    "",
    "2272060800 10  # 1 Jan 1972",
    "2287785600 11  # 1 Jul 1972",
    "2303683200 12  # 1 Jan 1973",
    "2335104000 13  # 1 Jan 1974",
    "2364832000 14  # 1 Jan 1975",
    "2395968000 15  # 1 Jan 1976",
    "2426496000 16  # 1 Jan 1977",
    "2457024000 17  # 1 Jan 1978",
    "2488160000 18  # 1 Jan 1979",
    "2510400000 19  # 1 Jan 1980",
    "2540131200 20  # 1 Jul 1981",
    "2569856000 21  # 1 Jul 1982",
    "2600400000 22  # 1 Jul 1983",
    "2631158400 23  # 1 Jul 1985",
    "2666774400 24  # 1 Jan 1988",
    "2701800000 25  # 1 Jan 1990",
    "2732064000 26  # 1 Jan 1991",
    "2751043200 27  # 1 Jul 1992",
    "2777184000 28  # 1 Jul 1993",
    "2813980800 29  # 1 Jul 1994",
    "2840160000 30  # 1 Jan 1996",
    "2874572800 31  # 1 Jul 1997",
    "2916416000 32  # 1 Jan 1999",
    "2950291200 33  # 1 Jan 2006",
    "2982016000 34  # 1 Jan 2009",
    "3029456000 35  # 1 Jul 2012",
    "3076704000 36  # 1 Jul 2015",
    "3124136000 37  # 1 Jan 2017",
    "",
    "# File expires on 28 June 2024",
    "",
    "#h 8e9f5c3a 1f3e1a2b 2024 jun 28",
]


class TestParsing(unittest.TestCase):
    def test_parses_entries_and_skips_comments(self):
        table = LeapSecondTable(SAMPLE_LINES)
        self.assertEqual(len(table.entries), 28)
        self.assertEqual(table.first.offset, 10)
        self.assertEqual(table.latest.offset, 37)

    def test_first_entry_has_correct_unix_epoch(self):
        table = LeapSecondTable(SAMPLE_LINES)
        first = table.first
        # NTP timestamp 2272060800 minus the epoch offset gives
        # 63072000, which is exactly 1972-01-01T00:00:00Z as Unix.
        self.assertEqual(first.when_unix, 2272060800 - NTP_TO_UNIX_EPOCH)
        self.assertEqual(first.when_unix, 63072000)
        self.assertEqual(first.description, "1 Jan 1972")
        self.assertEqual(first.ntp_timestamp, 2272060800)

    def test_entries_are_strictly_increasing(self):
        table = LeapSecondTable(SAMPLE_LINES)
        unixs = [e.when_unix for e in table.entries]
        self.assertEqual(unixs, sorted(set(unixs)))

    def test_directives_and_hash_lines_are_skipped(self):
        lines = [
            "#@ 3612265600",
            "#h 5b31a0a3 c2e6b3e5 2015 jan 1",
            "# File expires on 28 June 2024",
            "2272060800 10  # 1 Jan 1972",
        ]
        table = LeapSecondTable(lines)
        self.assertEqual(len(table.entries), 1)

    def test_blank_lines_are_skipped(self):
        lines = ["", "   ", "2272060800 10  # 1 Jan 1972", ""]
        table = LeapSecondTable(lines)
        self.assertEqual(len(table.entries), 1)

    def test_data_line_without_comment_is_accepted(self):
        lines = ["2272060800 10"]
        table = LeapSecondTable(lines)
        self.assertEqual(table.entries[0].description, "")


class TestParseErrors(unittest.TestCase):
    def test_non_integer_field_raises(self):
        with self.assertRaises(ParseError):
            LeapSecondTable(["2272060800 ten  # bad"])

    def test_wrong_field_count_raises(self):
        with self.assertRaises(ParseError):
            LeapSecondTable(["2272060800 10 extra  # bad"])

    def test_empty_input_raises(self):
        with self.assertRaises(ParseError):
            LeapSecondTable([])

    def test_only_comments_raises(self):
        with self.assertRaises(ParseError):
            LeapSecondTable(["# just a comment", "# another"])

    def test_non_increasing_timestamp_raises(self):
        lines = [
            "2272060800 10  # 1 Jan 1972",
            "2272060800 11  # same timestamp",
        ]
        with self.assertRaises(ParseError):
            LeapSecondTable(lines)

    def test_decreasing_offset_raises(self):
        lines = [
            "2272060800 11  # 1 Jan 1972",
            "2287785600 10  # offset went down",
        ]
        with self.assertRaises(ParseError):
            LeapSecondTable(lines)

    def test_negative_offset_raises(self):
        with self.assertRaises(ValueError):
            LeapEntry(when_unix=0, offset=-1, ntp_timestamp=0)


class TestOffsetLookup(unittest.TestCase):
    def setUp(self):
        self.table = LeapSecondTable(SAMPLE_LINES)

    def test_before_first_entry_returns_zero(self):
        # The day before the first entry: offset was zero by definition.
        self.assertEqual(self.table.offset_at(0), 0)
        self.assertEqual(self.table.offset_at(63071999), 0)

    def test_at_first_entry_returns_first_offset(self):
        self.assertEqual(self.table.offset_at(63072000), 10)

    def test_just_before_second_entry_returns_first_offset(self):
        second_unix = 2287785600 - NTP_TO_UNIX_EPOCH
        self.assertEqual(self.table.offset_at(second_unix - 1), 10)

    def test_at_second_entry_returns_second_offset(self):
        second_unix = 2287785600 - NTP_TO_UNIX_EPOCH
        self.assertEqual(self.table.offset_at(second_unix), 11)

    def test_after_last_entry_returns_last_offset(self):
        self.assertEqual(self.table.offset_at(2 ** 31), 37)

    def test_entry_at_before_first_returns_none(self):
        self.assertIsNone(self.table.entry_at(0))

    def test_entry_at_first_returns_first(self):
        first = self.table.entry_at(63072000)
        self.assertIsNotNone(first)
        self.assertEqual(first.offset, 10)

    def test_offset_intervals_cover_full_range(self):
        intervals = self.table.offset_intervals()
        self.assertEqual(len(intervals), len(self.table.entries))
        # The intervals are contiguous.
        for i in range(len(intervals) - 1):
            self.assertEqual(intervals[i][1], intervals[i + 1][0])
        # Last interval extends to the sentinel.
        self.assertEqual(intervals[-1][2], 37)


class TestFakeClock(unittest.TestCase):
    def test_offset_now_uses_injected_clock(self):
        captured = {"value": 63072000}

        def fake_clock() -> float:
            return float(captured["value"])

        table = LeapSecondTable(SAMPLE_LINES, clock=fake_clock)
        self.assertEqual(table.offset_now(), 10)

        captured["value"] = 2287785600 - NTP_TO_UNIX_EPOCH
        self.assertEqual(table.offset_now(), 11)

        captured["value"] = 0
        self.assertEqual(table.offset_now(), 0)


class TestMinExample(unittest.TestCase):
    def test_single_entry_table(self):
        lines = ["2272060800 10  # 1 Jan 1972"]
        table = LeapSecondTable(lines)
        self.assertEqual(table.offset_at(0), 0)
        self.assertEqual(table.offset_at(63072000), 10)
        self.assertEqual(table.offset_at(2 ** 40), 10)


if __name__ == "__main__":
    unittest.main()

"""The second request, which the arithmetic test cannot reach.

`tests/test_portfolio_sheet_write.py` already settles that write_rows() splits a
long write into CHUNK_ROWS and a remainder, at the ranges it computes. It settles
that against a double that agrees by construction, so what it cannot say is
whether a second request *arrives* -- and `Transactions` is written in full on
purpose, so that is not a detail.

check_write_volume() is what asks Sheets. These tests are what make it safe to
run: it creates a tab and deletes one, and everything below is about it deleting
only the tab it made, refusing a size that would pass without asking anything,
and reporting the two failures it exists to find rather than agreeing with them.

The fake here is a grid and not a recorder. A double that answered reads off
canned values could pass a run whose write never happened, which is the exact
defect this check is for -- so what is read back is what the writes addressed,
and a write sent to the wrong range comes back from the wrong place.
"""

import re
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import gspread.exceptions

from stonksmith.etc.portfolio import TRANSACTION_COLUMNS
from stonksmith.etc.portfolio_sheet import (
    BANNER,
    CHUNK_ROWS,
    FIRST_DATA_ROW,
    MACHINE_OWNED_TABS,
    VOLUME_CHECK_BROKER,
    VOLUME_CHECK_ROWS,
    VOLUME_CHECK_TAB,
    VOLUME_MARKER_COLUMN,
    _chunk_edges,
    _chunks,
    _volume_rows,
    check_write_volume,
)
from stonksmith.helpers.sheets import SheetsUnavailable

#: A1 references, as the two shapes this module produces them in: "A1" and
#: "A3:O2002" from write_rows, and the open-ended "D3:D" from _column_at.
REFERENCE = re.compile(pattern=r"^([A-Z]+)(\d*)$")

MARKER_INDEX: int = list(TRANSACTION_COLUMNS).index(VOLUME_MARKER_COLUMN)


def number(letter: str) -> int:
    """
    A column letter as a 1-indexed number.
    :param letter: "A", "O", "AA"
    :return: Its position
    :rtype: int
    """

    position: int = 0

    for character in letter:
        position = position * 26 + (ord(character) - ord("A") + 1)

    return position


def marked(count: int) -> list[list[Any]]:
    """
    Rows shaped like the real ones, marked so a displaced row is identifiable.

    Deliberately not _volume_rows: these tests are about the machinery around it,
    and pinning them to whatever scheme that function settles on would make a
    change of marker a change of test.
    :param count: How many rows
    :return: One list of cells per row
    :rtype: list[list[Any]]
    """

    built: list[list[Any]] = []

    for n in range(count):
        row: list[Any] = [""] * len(TRANSACTION_COLUMNS)
        row[MARKER_INDEX] = f"row-{n:05d}"
        built.append(row)

    return built


class GridTab:
    """
    A tab that stores cells where the write addressed them.

    Shared state with the book, so a second handle on the same title reads what
    the first one wrote -- which is what check_write_volume does, deliberately,
    to keep the read a round trip rather than something answered out of the
    handle that did the writing.
    """

    def __init__(self, book: FakeBook, title: str) -> None:
        self.book = book
        self.title = title

    @property
    def grid(self) -> dict[tuple[int, int], Any]:
        return self.book.tabs[self.title]

    @property
    def row_count(self) -> int:
        return self.book.sizes[self.title][0]

    @property
    def col_count(self) -> int:
        return self.book.sizes[self.title][1]

    def add_rows(self, count: int) -> None:
        rows, cols = self.book.sizes[self.title]
        self.book.sizes[self.title] = (rows + count, cols)

    def add_cols(self, count: int) -> None:
        rows, cols = self.book.sizes[self.title]
        self.book.sizes[self.title] = (rows, cols + count)

    def clear(self) -> None:
        self.grid.clear()

    def update(
        self, values: list[list[Any]], range_name: str, value_input_option: str = ""
    ) -> None:
        del value_input_option
        top, left = self._corner(reference=range_name.split(":")[0])

        for down, row in enumerate(values):
            for across, cell in enumerate(row):
                self.grid[(top + down, left + across)] = cell

    def acell(self, cell: str) -> MagicMock:
        return MagicMock(value=self.grid.get(self._corner(reference=cell)))

    def get_values(
        self, cells: str, value_render_option: Any = None
    ) -> list[list[Any]]:
        del value_render_option
        first, _, second = cells.partition(":")
        top, left = self._corner(reference=first)
        bottom, right = self._corner(
            reference=second or first, default_row=self._last()
        )

        rows: list[list[Any]] = [
            [
                str(object=self.grid.get((row, col), ""))
                for col in range(left, right + 1)
            ]
            for row in range(top, bottom + 1)
        ]

        # Sheets trims trailing empty rows off a range rather than padding it
        # out, which is the behaviour _column_at and _date_cases are written
        # around. A double that padded would hide a short return.
        while rows and not any(cell for cell in rows[-1]):
            rows.pop()

        return rows

    def get_all_values(self) -> list[list[Any]]:
        return self.get_values(cells=f"A1:{'A' if not self.grid else 'Z'}")

    def _last(self) -> int:
        return max((row for row, _ in self.grid), default=0)

    def _corner(
        self, reference: str, default_row: int | None = None
    ) -> tuple[int, int]:
        found = REFERENCE.match(string=reference)
        assert found is not None, reference
        letter, digits = found.groups()

        return (int(digits) if digits else (default_row or 1), number(letter=letter))


class FakeBook:
    """A spreadsheet that tracks which tabs were made and removed."""

    def __init__(self, existing: tuple[str, ...] = ()) -> None:
        self.tabs: dict[str, dict[tuple[int, int], Any]] = {
            name: {} for name in existing
        }
        self.sizes: dict[str, tuple[int, int]] = dict.fromkeys(existing, (100, 26))
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.delete_error: Exception | None = None

    def worksheet(self, title: str) -> GridTab:
        if title not in self.tabs:
            raise gspread.exceptions.WorksheetNotFound(title)

        return GridTab(book=self, title=title)

    def add_worksheet(self, title: str, rows: int, cols: int) -> GridTab:
        self.tabs[title] = {}
        self.sizes[title] = (rows, cols)
        self.created.append(title)

        return GridTab(book=self, title=title)

    def del_worksheet(self, worksheet: GridTab) -> None:
        if self.delete_error is not None:
            raise self.delete_error

        self.deleted.append(worksheet.title)
        self.tabs.pop(worksheet.title, None)


def api_error(code: int = 429) -> gspread.exceptions.APIError:
    return gspread.exceptions.APIError(
        MagicMock(
            status_code=code,
            json=lambda: {"code": code, "message": "nope", "status": "FAILED"},
        )
    )


#: Small enough to run in a test and still two requests, which is the only
#: property that matters. The real check sends VOLUME_CHECK_ROWS.
SHORT: int = CHUNK_ROWS + 3


class VolumeCheckTests(unittest.TestCase):
    """The check itself, over a grid that remembers where each write landed."""

    def run_check(self, book: FakeBook, rows: int = SHORT) -> tuple[Any, ...]:
        with patch(
            "stonksmith.etc.portfolio_sheet._volume_rows",
            side_effect=lambda count: marked(count=count),
        ):
            return check_write_volume(book=book, rows=rows)

    def test_both_writes_land_and_every_row_comes_back(self) -> None:
        book = FakeBook()

        cases = self.run_check(book=book)

        self.assertTrue(all(case.passed for case in cases), list(cases))
        # The count, the boundaries, and the teardown reporting as its own case.
        self.assertEqual(len(cases), 3)
        self.assertEqual(book.created, [VOLUME_CHECK_TAB])
        self.assertEqual(book.deleted, [VOLUME_CHECK_TAB])
        self.assertNotIn(VOLUME_CHECK_TAB, book.tabs)

    def test_it_goes_up_as_the_real_write_does_and_in_two_requests(self) -> None:
        # Not incidental. The whole claim rests on this being the same write, so
        # a check that skipped the banner or batched differently would be asking
        # Sheets about something other than what a sync sends it.
        book = FakeBook()
        seen: list[tuple[str, list[list[Any]]]] = []
        real = GridTab.update

        def watched(
            tab: GridTab, values: list[list[Any]], range_name: str, **kw: Any
        ) -> None:
            seen.append((range_name, values))
            real(tab, values, range_name, **kw)

        with patch.object(target=GridTab, attribute="update", new=watched):
            cases = self.run_check(book=book)

        self.assertTrue(all(case.passed for case in cases), list(cases))
        self.assertEqual(seen[0], ("A1", [[BANNER]]))
        self.assertEqual(seen[1][1], [list(TRANSACTION_COLUMNS)])
        # The banner, the header, and two data requests -- not one, and not
        # three, which is the arithmetic this is standing in front of.
        self.assertEqual([len(values) for _, values in seen[2:]], [CHUNK_ROWS, 3])

    def test_a_second_write_that_never_arrived_is_reported(self) -> None:
        # The finding this check exists for. Everything up to CHUNK_ROWS is
        # there, so a tab read without counting looks entirely healthy.
        book = FakeBook()

        with patch(
            "stonksmith.etc.portfolio_sheet._chunks",
            side_effect=lambda rows, size: [list(rows[:size])],
        ):
            cases = self.run_check(book=book)

        count, boundaries, teardown = cases
        self.assertFalse(count.passed)
        self.assertIn(str(object=CHUNK_ROWS), count.detail)
        self.assertFalse(boundaries.passed)
        self.assertTrue(teardown.passed)

    def test_a_second_write_at_the_wrong_range_is_reported(self) -> None:
        # The one a count cannot see: every row arrived, one request landed a row
        # lower than it was addressed to, and the tab holds the right number of
        # rows in the wrong places.
        book = FakeBook()
        real = GridTab.update

        def shifted(tab: GridTab, values: list[list[Any]], range_name: str, **kw: Any):
            if len(values) == SHORT - CHUNK_ROWS:
                letter, digits = REFERENCE.match(  # type: ignore[union-attr]
                    string=range_name.split(":")[0]
                ).groups()
                range_name = f"{letter}{int(digits) + 1}"

            return real(tab, values, range_name, **kw)

        with patch.object(target=GridTab, attribute="update", new=shifted):
            cases = self.run_check(book=book)

        count, boundaries, _ = cases
        self.assertTrue(count.passed, count.detail)
        self.assertFalse(boundaries.passed)
        self.assertIn(str(object=CHUNK_ROWS + FIRST_DATA_ROW), boundaries.detail)

    def test_a_size_that_fits_one_request_is_refused(self) -> None:
        # A check that sent CHUNK_ROWS rows would pass every time without ever
        # putting a second request in front of Sheets, which is the question.
        book = FakeBook()

        for rows in (1, CHUNK_ROWS - 1, CHUNK_ROWS):
            with (
                self.subTest(rows=rows),
                self.assertRaises(expected_exception=SheetsUnavailable) as caught,
            ):
                check_write_volume(book=book, rows=rows)

            self.assertIn(str(object=CHUNK_ROWS), str(object=caught.exception))

        self.assertEqual(book.created, [])

    def test_a_machine_owned_name_is_rejected_before_sheets_is_touched(self) -> None:
        # So that a tab quietly joining MACHINE_OWNED_TABS cannot turn this into
        # something that overwrites and then deletes it.
        book = FakeBook()

        for tab in MACHINE_OWNED_TABS:
            with (
                self.subTest(tab=tab),
                self.assertRaises(expected_exception=SheetsUnavailable),
            ):
                check_write_volume(book=book, tab=tab)

        self.assertEqual(book.created, [])
        self.assertEqual(book.deleted, [])

    def test_a_tab_that_is_already_there_is_refused_and_never_deleted(self) -> None:
        # The one that matters most, and more here than for the ownership check:
        # this one writes thousands of rows before it deletes anything.
        book = FakeBook(existing=(VOLUME_CHECK_TAB,))

        with self.assertRaises(expected_exception=SheetsUnavailable) as caught:
            self.run_check(book=book)

        self.assertIn(VOLUME_CHECK_TAB, str(object=caught.exception))
        self.assertEqual(book.created, [])
        self.assertEqual(book.deleted, [])
        self.assertEqual(book.tabs[VOLUME_CHECK_TAB], {})

    def test_a_lookup_that_was_rejected_is_not_read_as_an_absent_tab(self) -> None:
        # A request that failed for a reason other than absence, read as absence,
        # makes a second tab beside one already there. tab_exists routes through
        # _find_worksheet so this arrives as SheetsUnavailable instead.
        book = FakeBook()
        book.worksheet = MagicMock(side_effect=api_error())  # type: ignore[method-assign]

        with self.assertRaises(expected_exception=SheetsUnavailable):
            self.run_check(book=book)

        self.assertEqual(book.created, [])

    def test_the_tab_still_goes_when_the_write_raises(self) -> None:
        # A scratch tab holding thousands of rows is the most expensive litter
        # this module can leave, so the teardown has to survive the write.
        book = FakeBook()

        with (
            patch(
                "stonksmith.etc.portfolio_sheet.write_rows",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(expected_exception=RuntimeError),
        ):
            self.run_check(book=book)

        self.assertEqual(book.deleted, [VOLUME_CHECK_TAB])

    def test_a_scratch_tab_that_will_not_delete_is_reported_not_raised(self) -> None:
        # Teardown reports rather than raises. Raising would replace the findings
        # with the news that a scratch tab is still there -- true, and less
        # useful than the result it threw away.
        book = FakeBook()
        book.delete_error = api_error(code=403)

        cases = self.run_check(book=book)

        self.assertTrue(all(case.passed for case in cases[:2]), list(cases))
        self.assertFalse(cases[-1].passed)
        self.assertIn(VOLUME_CHECK_TAB, cases[-1].detail)


class VolumeContractTests(unittest.TestCase):
    def test_the_scratch_tab_is_not_one_of_the_tabs_that_get_written(self) -> None:
        self.assertNotIn(VOLUME_CHECK_TAB, MACHINE_OWNED_TABS)

    def test_the_two_scratch_tabs_do_not_share_a_name(self) -> None:
        # They are removed by handle rather than by name, so a collision would
        # not delete the wrong tab -- but it would let one check refuse to run
        # because the other's tab was still there after a failed teardown.
        from stonksmith.etc.portfolio_sheet import GUARD_CHECK_TAB

        self.assertNotEqual(VOLUME_CHECK_TAB, GUARD_CHECK_TAB)

    def test_the_default_size_clears_both_thresholds(self) -> None:
        # 500 is where get_transactions caps, and is the number a tab that
        # silently windowed would agree with. CHUNK_ROWS is where the write stops
        # fitting in one request. Neither alone is enough.
        self.assertGreater(VOLUME_CHECK_ROWS, 500)
        self.assertGreater(VOLUME_CHECK_ROWS, CHUNK_ROWS)

    def test_the_marker_column_is_the_one_the_real_check_counts(self) -> None:
        # _count_case counts Account Key on the real Transactions tab. A volume
        # check counting a different column would be checking something the
        # check it stands in for does not do.
        self.assertIn(VOLUME_MARKER_COLUMN, TRANSACTION_COLUMNS)
        self.assertEqual(VOLUME_MARKER_COLUMN, "Account Key")


class ChunkEdgeTests(unittest.TestCase):
    """Which rows get read back one at a time, and why those.

    A request that never arrived shows in the count. A request that arrived at
    the wrong range does not -- the rows are all there and only their addresses
    moved -- and it is the first and last row of a chunk that move when it does.
    """

    def test_an_exact_multiple_gives_both_ends_of_each_chunk(self) -> None:
        self.assertEqual(
            _chunk_edges(count=CHUNK_ROWS * 2),
            (0, CHUNK_ROWS - 1, CHUNK_ROWS, CHUNK_ROWS * 2 - 1),
        )

    def test_a_remainder_chunk_gives_both_of_its_ends_too(self) -> None:
        self.assertEqual(
            _chunk_edges(count=CHUNK_ROWS + 500),
            (0, CHUNK_ROWS - 1, CHUNK_ROWS, CHUNK_ROWS + 499),
        )

    def test_a_final_chunk_of_one_row_is_named_once(self) -> None:
        # Its own first and last. Naming it twice would report one cell as two
        # checks, and the count in the case name would be a row too high.
        self.assertEqual(
            _chunk_edges(count=CHUNK_ROWS + 1), (0, CHUNK_ROWS - 1, CHUNK_ROWS)
        )

    def test_every_edge_is_a_row_that_exists(self) -> None:
        for count in (1, 2, CHUNK_ROWS, CHUNK_ROWS + 1, CHUNK_ROWS * 3 + 7):
            with self.subTest(count=count):
                edges = _chunk_edges(count=count)
                self.assertTrue(all(0 <= n < count for n in edges), edges)
                self.assertEqual(sorted(set(edges)), list(edges))


class VolumeRowTests(unittest.TestCase):
    """What _volume_rows has to produce, whatever it puts in the cells.

    _volume_cases asks these rows one question -- what should row n have said? --
    so uniqueness and stability are the whole of the contract, and the cells other
    than the marker are deliberately not pinned. The one thing below that goes
    past the contract is the marker's *shape*, and it is here because the
    docstring makes a claim about what a failure will read like: a claim about
    output that no assertion checks is the shape this project keeps finding.
    """

    def test_it_builds_the_rows_that_were_asked_for(self) -> None:
        self.assertEqual(len(_volume_rows(count=7)), 7)
        self.assertEqual(_volume_rows(count=0), [])

    def test_every_row_is_the_width_of_the_contract(self) -> None:
        # write_rows addresses A through the contract's last column, so a short
        # row leaves cells from the previous write standing under it.
        for row in _volume_rows(count=5):
            self.assertEqual(len(row), len(TRANSACTION_COLUMNS))

    def test_no_two_rows_carry_the_same_marker(self) -> None:
        rows = _volume_rows(count=250)
        markers = [row[MARKER_INDEX] for row in rows]

        self.assertEqual(len(set(markers)), len(markers))
        self.assertTrue(all(str(object=marker) for marker in markers))

    def test_the_same_row_is_built_the_same_way_twice(self) -> None:
        # Nothing stores these. They are rebuilt to be compared against what came
        # back, so a marker carrying a timestamp or a random part would report
        # every boundary as displaced.
        self.assertEqual(_volume_rows(count=50), _volume_rows(count=50))
        self.assertEqual(_volume_rows(count=50)[:10], _volume_rows(count=10))

    def test_a_marker_names_its_request_and_the_sheet_row_it_was_sent_to(self) -> None:
        # Why the scheme is worth anything: _volume_cases prints the sheet row it
        # read beside the marker that should have been in it, so a marker holding
        # an index would make the reader subtract FIRST_DATA_ROW before knowing
        # whether anything moved.
        #
        # Walked the way write_rows walks it -- first_row at FIRST_DATA_ROW,
        # advancing by the length of each chunk -- rather than restating the
        # arithmetic, so a change to how a chunk is addressed fails here instead
        # of leaving markers that quietly name the wrong cell.
        rows = _volume_rows(count=CHUNK_ROWS + 2)
        sheet_row: int = FIRST_DATA_ROW

        for request, chunk in enumerate(_chunks(rows=rows, size=CHUNK_ROWS), start=1):
            self.assertEqual(chunk[0][MARKER_INDEX], f"write-{request}-row-{sheet_row}")
            self.assertEqual(
                chunk[-1][MARKER_INDEX],
                f"write-{request}-row-{sheet_row + len(chunk) - 1}",
            )
            sheet_row += len(chunk)

    def test_a_row_says_what_it_is_in_case_a_teardown_left_it_behind(self) -> None:
        # The tab is deleted at the end of the check, and reported rather than
        # raised if it will not go -- so the row somebody finds has to explain
        # itself. Every row, because row 1 is not the one they will be looking at.
        for row in _volume_rows(count=3):
            self.assertIn(VOLUME_CHECK_BROKER, row)
            self.assertTrue(
                any("delete it by hand" in str(object=cell) for cell in row), row
            )


if __name__ == "__main__":
    unittest.main()

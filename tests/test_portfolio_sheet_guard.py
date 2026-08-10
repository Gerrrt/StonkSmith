"""The machine-owned rule, as code rather than as a README paragraph.

The README has said "broker tabs are machine-owned, nothing hand-written ever
lives on one" since the column contract landed. A paragraph is not what stops a
sync from clearing a tab someone kept notes on, and the failure it describes is
the worst shape there is: silent, total, and reported as success. These are the
tests that make it a refusal.
"""

import unittest
from unittest.mock import MagicMock, patch

import gspread.exceptions

from etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    BANNER,
    BANNER_CELL,
    DASHBOARD_TAB,
    GUARD_CHECK_TAB,
    HOLDINGS_TAB,
    MACHINE_OWNED_TABS,
    TRANSACTIONS_TAB,
    check_ownership_guard,
    claim,
)
from helpers.sheets import SheetNotOwned, SheetsUnavailable

#: The five tabs the savers used to own. Never opened again, and named here so
#: that a tab quietly reappearing in MACHINE_OWNED_TABS fails rather than syncs.
RETIRED_TABS: tuple[str, ...] = ("Fidelity", "SnapTrade", "TSP", "Ally", "529 Plan")


def worksheet(
    first_cell: str | None, values: list[list[str]] | None = None
) -> MagicMock:
    """
    A gspread worksheet that answers the two reads ``claim`` makes.
    :param first_cell: What A1 holds, or None for an empty cell
    :param values: What the whole tab holds, if asked
    :return: The fake worksheet
    :rtype: MagicMock
    """

    fake = MagicMock()
    fake.acell.return_value = MagicMock(value=first_cell)
    fake.get_all_values.return_value = values if values is not None else []

    return fake


class FakeTab:
    """
    A tab that remembers what was written to it.

    Column A only, which is all the ownership check writes, and enough for
    ``claim`` to answer both of its reads off the same state rather than off two
    canned returns. A stub that answered them independently could pass a case
    whose staging never happened.
    """

    def __init__(self, book: FakeBook, title: str) -> None:
        self.book = book
        self.title = title

    @property
    def cells(self) -> dict[int, str]:
        return self.book.tabs[self.title]

    def clear(self) -> None:
        self.cells.clear()

    def update_acell(self, cell: str, text: str) -> None:
        self.cells[int(cell[1:])] = text

    def acell(self, cell: str) -> MagicMock:
        return MagicMock(value=self.cells.get(int(cell[1:])))

    def get_all_values(self) -> list[list[str]]:
        if not self.cells:
            return []

        return [[self.cells.get(row, "")] for row in range(1, max(self.cells) + 1)]


class FakeBook:
    """A spreadsheet that tracks which tabs were made and removed."""

    def __init__(self, existing: tuple[str, ...] = ()) -> None:
        self.tabs: dict[str, dict[int, str]] = {name: {} for name in existing}
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.lookups: list[str] = []
        self.delete_error: Exception | None = None

    def worksheet(self, title: str) -> FakeTab:
        self.lookups.append(title)

        if title not in self.tabs:
            raise gspread.exceptions.WorksheetNotFound(title)

        return FakeTab(book=self, title=title)

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeTab:
        del rows, cols
        self.tabs[title] = {}
        self.created.append(title)

        return FakeTab(book=self, title=title)

    def del_worksheet(self, worksheet: FakeTab) -> None:
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


class OwnershipCheckTests(unittest.TestCase):
    """The guard, asked its three questions on a tab made for the purpose.

    claim() decides on what a tab holds and not on what it is called, so the
    refusal can be exercised without defacing a real tab. These cover the part
    that has to be right for that to be safe: the check must never touch a tab it
    did not create.
    """

    def test_all_three_questions_are_asked_and_the_tab_is_removed(self) -> None:
        book = FakeBook()

        cases = check_ownership_guard(book=book)

        self.assertTrue(all(case.passed for case in cases), list(cases))
        # Three questions plus the teardown, which reports as a case of its own.
        self.assertEqual(len(cases), 4)
        self.assertEqual(book.created, [GUARD_CHECK_TAB])
        self.assertEqual(book.deleted, [GUARD_CHECK_TAB])
        self.assertNotIn(GUARD_CHECK_TAB, book.tabs)

    def test_a_tab_that_is_already_there_is_refused_and_never_deleted(self) -> None:
        # The one that matters most. A tab of this name that already exists is
        # somebody else's, and the check's whole safety rests on not adopting it.
        book = FakeBook(existing=(GUARD_CHECK_TAB,))

        with self.assertRaises(SheetsUnavailable) as caught:
            check_ownership_guard(book=book)

        self.assertIn(GUARD_CHECK_TAB, str(caught.exception))
        self.assertEqual(book.deleted, [])
        self.assertEqual(book.created, [])

    def test_a_machine_owned_name_is_rejected_before_sheets_is_touched(self) -> None:
        # So that a tab quietly joining MACHINE_OWNED_TABS cannot turn this into
        # something that deletes it.
        book = FakeBook()

        for tab in MACHINE_OWNED_TABS:
            with self.subTest(tab=tab), self.assertRaises(SheetsUnavailable):
                check_ownership_guard(book=book, tab=tab)

        self.assertEqual(book.lookups, [])
        self.assertEqual(book.created, [])
        self.assertEqual(book.deleted, [])

    def test_a_lookup_that_was_rejected_is_not_read_as_an_absent_tab(self) -> None:
        # The dangerous misreading: a request that failed for a reason other than
        # absence, treated as absence, makes a second tab beside one already
        # there. tab_exists routes through _find_worksheet so this arrives as
        # SheetsUnavailable instead.
        book = FakeBook()
        book.worksheet = MagicMock(side_effect=api_error())  # type: ignore[method-assign]

        with self.assertRaises(SheetsUnavailable):
            check_ownership_guard(book=book)

        self.assertEqual(book.created, [])

    def test_the_tab_still_goes_when_a_case_raises_unexpectedly(self) -> None:
        book = FakeBook()

        with (
            patch("etc.portfolio_sheet.claim", side_effect=RuntimeError("boom")),
            self.assertRaises(RuntimeError),
        ):
            check_ownership_guard(book=book)

        # The scratch tab is not left behind by a failure inside the check.
        self.assertEqual(book.deleted, [GUARD_CHECK_TAB])

    def test_a_guard_that_adopts_when_it_should_refuse_is_reported(self) -> None:
        # The finding this command exists to surface, and the shape that eats
        # somebody's work: claim() waving through a tab it should have refused.
        book = FakeBook()

        with patch("etc.portfolio_sheet.claim", return_value=None):
            cases = check_ownership_guard(book=book)

        refusals = [case for case in cases if case.expected == "refused"]

        self.assertEqual(len(refusals), 2)
        self.assertTrue(all(not case.passed for case in refusals))
        self.assertTrue(all(case.detail for case in refusals))

    def test_a_scratch_tab_that_will_not_delete_is_reported_not_raised(self) -> None:
        # Teardown reports rather than raises. Raising here would replace the
        # findings with the news that a scratch tab is still there.
        book = FakeBook()
        book.delete_error = api_error(code=403)

        cases = check_ownership_guard(book=book)

        self.assertTrue(all(case.passed for case in cases[:3]))
        self.assertFalse(cases[-1].passed)
        self.assertIn(GUARD_CHECK_TAB, cases[-1].detail)

    def test_the_scratch_tab_is_not_one_of_the_tabs_that_get_written(self) -> None:
        self.assertNotIn(GUARD_CHECK_TAB, MACHINE_OWNED_TABS)


class ClaimTests(unittest.TestCase):
    def test_an_empty_tab_is_adopted(self) -> None:
        tab = worksheet(first_cell=None)

        claim(worksheet=tab, tab=ACCOUNTS_TAB)

    def test_our_own_tab_is_claimed_without_reading_the_whole_thing(self) -> None:
        # The steady-state path, and the reason the guard costs one small read
        # per tab per sync rather than a full download of it.
        tab = worksheet(first_cell=BANNER)

        claim(worksheet=tab, tab=ACCOUNTS_TAB)

        tab.acell.assert_called_once_with(BANNER_CELL)
        tab.get_all_values.assert_not_called()

    def test_a_hand_written_tab_is_refused_by_name(self) -> None:
        tab = worksheet(first_cell="my notes")

        with self.assertRaises(SheetNotOwned) as caught:
            claim(worksheet=tab, tab=HOLDINGS_TAB)

        self.assertIn(HOLDINGS_TAB, str(caught.exception))

    def test_a_legacy_layout_with_a_blank_first_cell_is_refused(self) -> None:
        # The case an A1-only check would get wrong, and the one that matters
        # most: every tab StonkSmith used to write left A1 blank and started its
        # headers at B2. This is the exact shape the old TSP saver produced. A
        # guard that adopted it would eat the tab it was written to protect.
        tab = worksheet(
            first_cell="",
            values=[[], ["", "Fund", "Units", "Units as of", "Share price"]],
        )

        with self.assertRaises(SheetNotOwned) as caught:
            claim(worksheet=tab, tab=HOLDINGS_TAB)

        self.assertIn(HOLDINGS_TAB, str(caught.exception))

    def test_a_tab_of_only_blank_cells_is_still_adopted(self) -> None:
        # Google hands back rows of empty strings for a tab that has been used
        # and emptied. That is an empty tab, not somebody's work.
        tab = worksheet(first_cell=None, values=[["", ""], ["", "  "]])

        claim(worksheet=tab, tab=ACCOUNTS_TAB)

    def test_a_refusal_says_what_to_do_about_it(self) -> None:
        tab = worksheet(first_cell="Q1 targets")

        with self.assertRaises(SheetNotOwned) as caught:
            claim(worksheet=tab, tab=DASHBOARD_TAB)

        message: str = str(caught.exception)
        self.assertIn("left", message)
        self.assertIn("tab of your own", message)

    def test_nothing_is_written_when_a_tab_is_refused(self) -> None:
        # The whole point. A guard that raised after clearing would be a
        # rearrangement of the bug rather than a fix for it.
        tab = worksheet(first_cell="my notes")

        with self.assertRaises(SheetNotOwned):
            claim(worksheet=tab, tab=ACCOUNTS_TAB)

        tab.clear.assert_not_called()
        tab.update.assert_not_called()
        tab.batch_update.assert_not_called()


class ClaimIsAskedOnceTests(unittest.TestCase):
    """refresh() claims every tab up front; each write claims the tab it clears.

    Both are worth having -- the first so a tab that is not ours costs nothing
    instead of leaving one tab rewritten beside a stale one, the second so no
    write path can exist with the guard missing from it. Together they would
    otherwise mean two rounds of reads, and on a first adoption two whole-tab
    downloads. So the answer is remembered on the handle it was asked about.
    """

    def test_the_second_claim_on_one_handle_reads_nothing(self) -> None:
        tab = worksheet(first_cell=BANNER)

        claim(worksheet=tab, tab=ACCOUNTS_TAB)
        claim(worksheet=tab, tab=ACCOUNTS_TAB)
        claim(worksheet=tab, tab=ACCOUNTS_TAB)

        tab.acell.assert_called_once_with(BANNER_CELL)

    def test_adopting_an_empty_tab_downloads_it_once(self) -> None:
        # The expensive path. Twice would be two full reads of the same tab.
        tab = worksheet(first_cell=None)

        claim(worksheet=tab, tab=HOLDINGS_TAB)
        claim(worksheet=tab, tab=HOLDINGS_TAB)

        tab.get_all_values.assert_called_once()

    def test_a_refused_tab_is_never_remembered_as_ours(self) -> None:
        # The failure that would matter: a tab that said no once, then went
        # unchecked. Every later ask must ask again, and must still refuse.
        tab = worksheet(first_cell="my notes")

        for _ in range(3):
            with self.assertRaises(SheetNotOwned):
                claim(worksheet=tab, tab=ACCOUNTS_TAB)

        self.assertEqual(tab.acell.call_count, 3)

    def test_a_fresh_handle_is_vetted_again(self) -> None:
        # The memo rides on the handle, never on the tab's name, so a later run
        # opening the same tab cannot inherit an earlier run's answer.
        claim(worksheet=worksheet(first_cell=BANNER), tab=ACCOUNTS_TAB)
        second = worksheet(first_cell="somebody typed here")

        with self.assertRaises(SheetNotOwned):
            claim(worksheet=second, tab=ACCOUNTS_TAB)

    def test_an_attribute_that_merely_looks_right_does_not_vouch(self) -> None:
        # The reason the memo is a private sentinel rather than True. A handle
        # that invents attributes on demand -- a MagicMock is exactly that --
        # would otherwise answer "already claimed" to its very first ask, and
        # the guard would be off for anything that behaved like one.
        tab = worksheet(first_cell="my notes")
        tab._stonksmith_claimed = True

        with self.assertRaises(SheetNotOwned):
            claim(worksheet=tab, tab=ACCOUNTS_TAB)


class OwnershipContractTests(unittest.TestCase):
    def test_a_refusal_is_a_kind_of_sheets_unavailable(self) -> None:
        # Why no caller needed a new except clause: for the run, declining to
        # write is the same outcome as not reaching Sheets at all, because the
        # database has the data either way.
        self.assertTrue(issubclass(SheetNotOwned, SheetsUnavailable))

    def test_the_banner_is_exactly_this(self) -> None:
        # Pinned, because changing it orphans every tab already in the field:
        # the next sync reads a first cell it does not recognise and refuses
        # every tab at once. Change this only with a migration in hand.
        self.assertEqual(
            BANNER,
            "StonkSmith machine-owned tab. Cleared and rewritten on every sync "
            "-- anything you put here is lost. Keep your own work on a tab of "
            "your own.",
        )

    def test_only_these_four_tabs_are_ever_opened(self) -> None:
        # Pinned as a tuple rather than a set: a tab added here is a tab the
        # next sync will clear, which is the one change in this module that can
        # cost somebody data. It should be typed out deliberately.
        self.assertEqual(
            MACHINE_OWNED_TABS,
            (ACCOUNTS_TAB, HOLDINGS_TAB, TRANSACTIONS_TAB, DASHBOARD_TAB),
        )

    def test_the_retired_broker_tabs_are_not_among_them(self) -> None:
        # The five old tabs are frozen at whatever the last sync left. Nothing
        # reads or writes them, which is what makes them safe to keep.
        self.assertEqual(set(MACHINE_OWNED_TABS) & set(RETIRED_TABS), set())


if __name__ == "__main__":
    unittest.main()

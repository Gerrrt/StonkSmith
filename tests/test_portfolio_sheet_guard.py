"""The machine-owned rule, as code rather than as a README paragraph.

The README has said "broker tabs are machine-owned, nothing hand-written ever
lives on one" since the column contract landed. A paragraph is not what stops a
sync from clearing a tab someone kept notes on, and the failure it describes is
the worst shape there is: silent, total, and reported as success. These are the
tests that make it a refusal.
"""

import unittest
from unittest.mock import MagicMock

from etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    BANNER,
    BANNER_CELL,
    DASHBOARD_TAB,
    HOLDINGS_TAB,
    MACHINE_OWNED_TABS,
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
        # the next sync reads a first cell it does not recognise and refuses all
        # three tabs at once. Change this only with a migration in hand.
        self.assertEqual(
            BANNER,
            "StonkSmith machine-owned tab. Cleared and rewritten on every sync "
            "-- anything you put here is lost. Keep your own work on a tab of "
            "your own.",
        )

    def test_only_three_tabs_are_ever_opened(self) -> None:
        self.assertEqual(
            MACHINE_OWNED_TABS, (ACCOUNTS_TAB, HOLDINGS_TAB, DASHBOARD_TAB)
        )

    def test_the_retired_broker_tabs_are_not_among_them(self) -> None:
        # The five old tabs are frozen at whatever the last sync left. Nothing
        # reads or writes them, which is what makes them safe to keep.
        self.assertEqual(set(MACHINE_OWNED_TABS) & set(RETIRED_TABS), set())


if __name__ == "__main__":
    unittest.main()

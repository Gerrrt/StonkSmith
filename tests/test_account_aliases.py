"""Calling an account what you call it, without renaming anything stored.

The names a broker chooses are written for the broker's own screens.
"MICROSOFT CORPORATION SAVINGS PLUS 401(K) PLAN" and "Individual (...0847)" are
both perfectly correct and neither is what their owner calls the account at half
past six in the morning.

So an alias is a display name applied on the way out of the databases, and the
two things it must not do are the two this file pins.

**It must not touch identity.** ``account_key`` is what every join, every
baseline and every carried series point keys on, and a rename that reached it
would orphan the history of the account it renamed. Nothing stored changes,
which is what makes an alias safe to add tonight and remove tomorrow.

**It must not be silent when it stops working.** A broker renaming an account
breaks the match, and the account then reverts to the broker's own wording --
the exact outcome the alias was written to prevent, arriving with no error. So a
line matching nothing is reported.

That report is subtler than it looks, and the reason this file exists. The
portfolio has *already been renamed* by the time anything asks, so a check
against the original labels finds none of them and calls every working alias
broken. An alarm that fires precisely when the feature is working is worse than
no alarm.
"""

import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.config import get_account_aliases
from stonksmith.etc.portfolio import (
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
    TransactionRow,
    apply_aliases,
    normalize_label,
    unmatched_aliases,
)

ALIASES: dict[str, str] = {"tsp / TSP L 2060": "Garrett 401(k)"}


def _portfolio() -> Portfolio:
    """One account, carried through every row shape that repeats its name."""

    return Portfolio(
        accounts=(
            AccountRow(
                broker="tsp",
                source="tsp",
                account="TSP L 2060",
                account_key="TSP-1",
                value=7917.58,
            ),
        ),
        holdings=(
            HoldingRow(
                broker="tsp",
                source="tsp",
                account="TSP L 2060",
                account_key="TSP-1",
                symbol="L 2060",
                value=7917.58,
            ),
        ),
        transactions=(
            TransactionRow(
                broker="tsp",
                source="tsp",
                account="TSP L 2060",
                account_key="TSP-1",
                tx_type="CONTRIBUTION",
            ),
        ),
        net_worth=(
            NetWorthRow(
                broker="tsp",
                source="tsp",
                account="TSP L 2060",
                account_key="TSP-1",
                date="2026-08-13",
                value=7917.58,
            ),
        ),
    )


class AnAliasRenamesEveryViewAndNothingStored(unittest.TestCase):
    def setUp(self) -> None:
        self.renamed = apply_aliases(portfolio=_portfolio(), aliases=ALIASES)

    def test_the_account_view_uses_the_new_name(self) -> None:
        self.assertEqual(self.renamed.accounts[0].account, "Garrett 401(k)")

    def test_every_other_view_agrees(self) -> None:
        # Holdings and movements repeat the display name, and a holdings table
        # still saying the broker's wording under a renamed account is the same
        # inconsistency one table further down.
        self.assertEqual(self.renamed.holdings[0].account, "Garrett 401(k)")
        self.assertEqual(self.renamed.transactions[0].account, "Garrett 401(k)")
        self.assertEqual(self.renamed.net_worth[0].account, "Garrett 401(k)")

    def test_identity_is_untouched(self) -> None:
        # The whole safety argument. account_key is what joins a snapshot to
        # every previous one and what a stored baseline keys its holdings on;
        # renaming it would orphan the history of the account being renamed.
        for row in (
            self.renamed.accounts[0],
            self.renamed.holdings[0],
            self.renamed.transactions[0],
            self.renamed.net_worth[0],
        ):
            self.assertEqual(row.account_key, "TSP-1")

    def test_the_value_is_untouched(self) -> None:
        self.assertEqual(self.renamed.accounts[0].value, 7917.58)

    def test_an_account_with_no_alias_keeps_its_name(self) -> None:
        kept = apply_aliases(portfolio=_portfolio(), aliases={"x / y": "z"})

        self.assertEqual(kept.accounts[0].account, "TSP L 2060")

    def test_no_aliases_returns_the_same_portfolio(self) -> None:
        original = _portfolio()

        self.assertIs(apply_aliases(portfolio=original, aliases={}), original)


class TheLabelIsForgivingInTheSameWayExclusionIs(unittest.TestCase):
    """One normalizer, because two settings name accounts the same way."""

    def test_spacing_and_case_do_not_have_to_match(self) -> None:
        for written in (
            "TSP / tsp l 2060",
            "tsp/TSP L 2060",
            "  tsp   /   TSP  L  2060  ",
        ):
            with self.subTest(written=written):
                renamed = apply_aliases(
                    portfolio=_portfolio(), aliases={written: "Garrett 401(k)"}
                )

                self.assertEqual(renamed.accounts[0].account, "Garrett 401(k)")

    def test_a_name_containing_a_slash_is_not_a_special_case(self) -> None:
        self.assertEqual(
            normalize_label(label="Fidelity / Individual / TOD"),
            normalize_label(label="fidelity/individual/tod"),
        )


class AnAliasThatMatchesNothingIsReported(unittest.TestCase):
    def test_a_typo_is_named(self) -> None:
        missing = unmatched_aliases(
            portfolio=_portfolio(), aliases={"tsp / TSP L 2061": "Garrett 401(k)"}
        )

        self.assertEqual(missing, ["tsp / TSP L 2061"])

    def test_a_working_alias_is_not_reported_after_it_has_been_applied(self) -> None:
        # The bug this file was written after. read_databases applies aliases on
        # the way out, so by the time anything checks, the account is called
        # "Garrett 401(k)" and the original label matches nothing -- and a naive
        # check reports every working alias as broken, every morning.
        applied = apply_aliases(portfolio=_portfolio(), aliases=ALIASES)

        self.assertEqual(
            unmatched_aliases(portfolio=applied, aliases=ALIASES),
            [],
            "a working alias was reported as matching nothing once applied, so "
            "the report fires exactly when the feature is doing its job",
        )

    def test_it_is_still_reported_before_being_applied(self) -> None:
        # The other direction, so the fix above cannot be "never report".
        self.assertEqual(unmatched_aliases(portfolio=_portfolio(), aliases=ALIASES), [])
        self.assertEqual(
            unmatched_aliases(portfolio=Portfolio(), aliases=ALIASES),
            ["tsp / TSP L 2060"],
        )


class TheConfigParsesWhatTheCommentPromises(UserConfigMixin, unittest.TestCase):
    config_body: str = (
        "[ACCOUNTS]\n"
        "aliases =\n"
        "    tsp / TSP L 2060 = Garrett 401(k)\n"
        "    ally / Individual (...0847) = Joint Brokerage (Ally)\n"
        "    a line with no separator\n"
    )

    def test_it_reads_the_pairs(self) -> None:
        self.assertEqual(
            get_account_aliases(),
            {
                "tsp / TSP L 2060": "Garrett 401(k)",
                "ally / Individual (...0847)": "Joint Brokerage (Ally)",
            },
        )

    def test_a_line_with_no_separator_is_dropped_rather_than_guessed_at(self) -> None:
        self.assertNotIn("a line with no separator", get_account_aliases())


class TheSplitIsOnTheLastEquals(UserConfigMixin, unittest.TestCase):
    # An account name may contain "=", and splitting on the first would take the
    # name apart rather than the pair. The asset class table splits on the first
    # for the mirror-image reason: a class name is far likelier to contain one
    # than a symbol is.
    config_body: str = "[ACCOUNTS]\naliases =\n    Schwab / A=B Trust = Ezekiel 529\n"

    def test_the_left_hand_side_keeps_its_equals_sign(self) -> None:
        self.assertEqual(get_account_aliases(), {"Schwab / A=B Trust": "Ezekiel 529"})


if __name__ == "__main__":
    unittest.main()

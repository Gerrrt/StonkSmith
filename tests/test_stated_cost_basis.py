"""What you paid, where the source will not say -- and where it must not guess.

Three holdings in a real workspace report a balance and no cost, each refusing
for its own reason. A Fidelity 401k reaches SnapTrade as ``kind: "other"``
carrying units and price and nothing else. A scraped 529 arrives as a bare
balance with no symbol at all. And the TSP unit count is anchored to a figure
typed off a quarterly statement, so the only units whose cost is known are the
ones accrued since -- reporting *those* as the basis would put a five-figure
balance against a few hundred dollars and print a gain of some two thousand
percent. A partial cost basis is worse than none, which is why this is stated
rather than derived.

Filling it in is the easy half. The three rules that keep it honest are the
subject of this file:

**A stated cost never overwrites a reported one.** SnapTrade returns a real
average over real lots; a config line is a figure somebody typed. Preferring the
typed number would let a config left in place quietly diverge from a broker that
had been right the whole time.

**A lump sum is never split.** An account with three uncosted holdings cannot
have one total divided between them without inventing the per-position gains the
split appears to report. Refused and reported.

**Costs are applied before aliases.** Both settings name an account by the label
the broker gave. Renaming first would leave every working line hunting for an
account under a name it no longer has -- and reporting itself as unused, which is
the trap ``unmatched_aliases`` documents from the other side.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.brief import positions
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.config import get_account_costs
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.portfolio import (
    HoldingRow,
    Portfolio,
    apply_aliases,
    apply_costs,
    read_workspace,
)
from stonksmith.etc.records import AccountIdentity, Holding


def held(
    account: str,
    symbol: str,
    value: float,
    cost: float | None = None,
    units: float = 10.0,
) -> HoldingRow:
    """
    One position, from a broker that may or may not have stated a cost.
    :param account: The account's display name
    :param symbol: The ticker or fund code
    :param value: What it is worth
    :param cost: What the source said it cost, or None when it said nothing
    :param units: How many units are held
    :return: The row
    :rtype: HoldingRow
    """

    return HoldingRow(
        broker="b",
        source="src",
        account=account,
        account_key=account.lower().replace(" ", "-"),
        symbol=symbol,
        units=units,
        value=value,
        cost_basis=cost,
    )


class AStatedCostFillsInWhatTheSourceOmitted(unittest.TestCase):
    def setUp(self) -> None:
        self.filled = apply_costs(
            portfolio=Portfolio(
                holdings=(held(account="Sam", symbol="", value=2300.00),)
            ),
            costs={"src / Sam": 1300.0},
        )

    def test_the_holding_carries_the_stated_cost(self) -> None:
        self.assertEqual(self.filled.holdings[0].cost_basis, 1300.0)

    def test_nothing_is_reported_as_unused(self) -> None:
        self.assertEqual(self.filled.unused_costs, ())

    def test_a_529_with_no_symbol_at_all_still_matches(self) -> None:
        # Keyed on the account, not the symbol, precisely so this case works: the
        # Schwab 529 arrives as a balance and a unit count with no symbol, and a
        # setting keyed by ticker could never name it.
        self.assertEqual(self.filled.holdings[0].symbol, "")


class TheSourceWinsWhereItSpoke(unittest.TestCase):
    def test_a_reported_cost_is_not_overwritten(self) -> None:
        # A real average over real lots beats a figure typed off a statement.
        filled = apply_costs(
            portfolio=Portfolio(
                holdings=(
                    held(account="Alex", symbol="SWPPX", value=3500.00, cost=3000.00),
                )
            ),
            costs={"src / Alex": 1000.0},
        )

        self.assertEqual(filled.holdings[0].cost_basis, 3000.00)

    def test_and_the_line_says_it_did_nothing(self) -> None:
        # Silence would leave a stale config looking like a working one.
        filled = apply_costs(
            portfolio=Portfolio(
                holdings=(
                    held(account="Alex", symbol="SWPPX", value=3500.00, cost=3000.00),
                )
            ),
            costs={"src / Alex": 1000.0},
        )

        self.assertEqual(len(filled.unused_costs), 1)
        self.assertIn("already reports its own cost basis", filled.unused_costs[0])

    def test_a_line_naming_no_account_says_so(self) -> None:
        filled = apply_costs(
            portfolio=Portfolio(holdings=(held(account="Sam", symbol="", value=1.0),)),
            costs={"src / Nobody": 500.0},
        )

        self.assertIn("no holding in this workspace", filled.unused_costs[0])


class ALumpSumIsNeverSplit(unittest.TestCase):
    def setUp(self) -> None:
        self.filled = apply_costs(
            portfolio=Portfolio(
                holdings=(
                    held(account="Mixed", symbol="AAA", value=600.0),
                    held(account="Mixed", symbol="BBB", value=400.0),
                )
            ),
            costs={"src / Mixed": 900.0},
        )

    def test_neither_holding_is_given_a_share_of_it(self) -> None:
        # Splitting 900 across two positions -- by value, by units, evenly --
        # decides the per-position gains it then appears to report. There is no
        # honest split, so there is no split.
        self.assertEqual([row.cost_basis for row in self.filled.holdings], [None, None])

    def test_and_the_refusal_says_why(self) -> None:
        self.assertIn("2 holdings report no cost basis", self.filled.unused_costs[0])

    def test_an_account_whose_other_holdings_are_costed_still_fills(self) -> None:
        # Only one holding *wants* a cost here, so the total is unambiguous. The
        # rule is about ambiguity, not about how many positions an account has.
        filled = apply_costs(
            portfolio=Portfolio(
                holdings=(
                    held(account="Mixed", symbol="AAA", value=600.0, cost=500.0),
                    held(account="Mixed", symbol="BBB", value=400.0),
                )
            ),
            costs={"src / Mixed": 350.0},
        )

        self.assertEqual([row.cost_basis for row in filled.holdings], [500.0, 350.0])


class TheTwoComposeInTheRightOrder(unittest.TestCase):
    def test_a_cost_survives_a_rename_applied_after_it(self) -> None:
        # Composition only. What this does *not* check is that the read path
        # calls them this way round -- it names the order itself, so it would
        # pass against a read path that had them backwards. That claim needs the
        # real read, which is what the class below does.
        portfolio = apply_aliases(
            portfolio=apply_costs(
                portfolio=Portfolio(
                    holdings=(
                        held(account="TSP L 2060", symbol="L 2060", value=8500.00),
                    )
                ),
                costs={"src / TSP L 2060": 6100.0},
            ),
            aliases={"src / TSP L 2060": "Alex 401(k)"},
        )

        self.assertEqual(portfolio.holdings[0].account, "Alex 401(k)")
        self.assertEqual(portfolio.holdings[0].cost_basis, 6100.0)


class TheConfigReadsMoneyAsPeopleWriteIt(UserConfigMixin, unittest.TestCase):
    def _reload(self, body: str) -> tuple[dict[str, float], list[str]]:
        self.config_body = body
        self.tearDown()
        self.setUp()

        return get_account_costs()

    def test_nothing_configured_is_no_costs_and_no_complaints(self) -> None:
        self.assertEqual(get_account_costs(), ({}, []))

    def test_a_figure_copied_off_a_statement_is_read(self) -> None:
        # "$1,300.00" is what a statement says. Refusing it would be pedantry
        # about a value nobody could misread.
        costs, refused = self._reload(
            "[ACCOUNTS]\ncost_basis =\n\tsrc / Sam = $1,300.00\n"
        )

        self.assertEqual(costs, {"src / Sam": 1300.0})
        self.assertEqual(refused, [])

    def test_something_that_is_not_an_amount_is_refused_and_named(self) -> None:
        # Not silently dropped, and emphatically not zero: a zero cost reports
        # the position's whole value as profit.
        costs, refused = self._reload(
            "[ACCOUNTS]\ncost_basis =\n\tsrc / Sam = about a grand\n"
        )

        self.assertEqual(costs, {})
        self.assertIn("not an amount", refused[0])

    def test_a_special_float_is_refused(self) -> None:
        # float() accepts every one of these, and the sign check below cannot
        # see them -- `nan < 0` is False. A NaN reaching the cost basis is
        # contagious: the gain is nan, the growth is nan, the win/loss flag
        # compares false against everything, and the tile renders the word.
        # "1e400" is here because it does not look special and overflows to inf.
        for amount in ("nan", "inf", "-inf", "1e400", "Infinity"):
            with self.subTest(amount=amount):
                costs, refused = self._reload(
                    f"[ACCOUNTS]\ncost_basis =\n\tsrc / Sam = {amount}\n"
                )

                self.assertEqual(costs, {})
                self.assertEqual(len(refused), 1)

    def test_a_negative_cost_is_refused_rather_than_clamped(self) -> None:
        # Clamping to zero would keep a number nobody meant. It would also
        # invert the sign of the growth percentage on the way through.
        costs, refused = self._reload("[ACCOUNTS]\ncost_basis =\n\tsrc / Sam = -500\n")

        self.assertEqual(costs, {})
        self.assertIn("cannot be negative", refused[0])

    def test_an_account_name_containing_an_equals_still_parses(self) -> None:
        # Split on the last "=", as the aliases beside it are.
        costs, _refused = self._reload(
            "[ACCOUNTS]\ncost_basis =\n\tsrc / Plan A=B = 100\n"
        )

        self.assertEqual(costs, {"src / Plan A=B": 100.0})


class TheReadPathAppliesThemInThatOrder(
    UserConfigMixin, MemoryKeyringMixin, unittest.TestCase
):
    """
    The claim the composition test above cannot make.

    ``read_databases`` has to apply costs *before* aliases, and only a run
    through the real read can say whether it does. Reversed, the label would
    name an account that no longer answers to it: every working line would
    report itself unused and the holding would keep its dash -- the exact
    symptom this setting was added to remove, and the failure mode
    ``unmatched_aliases`` was written around from the other side.
    """

    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

        db = BrokerDatabase(
            db_engine=create_db_engine(
                db_path=self.root / "default" / "schwab529plan.db"
            ),
            broker="schwab529plan",
        )
        db.save_snapshot(
            account=AccountIdentity(account_key="529-1", display_name="Sam"),
            scraped_at="2026-08-12 18:30:00",
            as_of="2026-08-12",
            value=2300.00,
            currency="USD",
            # No symbol, which is how the 529 actually arrives.
            holdings=[Holding(symbol="", units=200.0000, value=2300.00)],
            transactions=[],
        )
        db.shutdown_db()

    def _read(self) -> Portfolio:
        with patch("stonksmith.etc.portfolio.workspace_dir", str(object=self.root)):
            return read_workspace(workspace="default")

    def test_the_cost_lands_on_an_account_the_aliases_also_rename(self) -> None:
        self.config_body = (
            "[ACCOUNTS]\n"
            "aliases =\n"
            "\tschwab529plan / Sam = Sam 529\n"
            "cost_basis =\n"
            "\tschwab529plan / Sam = 2100.00\n"
        )
        self.tearDown()
        self.setUp()

        portfolio: Portfolio = self._read()

        self.assertEqual(portfolio.holdings[0].account, "Sam 529")
        self.assertEqual(portfolio.holdings[0].cost_basis, 2100.0)
        self.assertEqual(
            portfolio.unused_costs,
            (),
            "the cost line reported itself unused against a renamed account",
        )

    def test_everything_downstream_follows_from_it(self) -> None:
        # What the setting is actually for. purchase price, gain, growth and the
        # win/loss flag are all computed from cost_basis, so stating the one
        # fills the other four -- and the Gain tile stops saying a position
        # reports no cost.
        self.config_body = "[ACCOUNTS]\ncost_basis =\n\tschwab529plan / Sam = 2100.00\n"
        self.tearDown()
        self.setUp()

        row = positions(portfolio=self._read(), classes={}, income={}, history={})[0]

        self.assertEqual(row.cost_basis, 2100.0)
        self.assertAlmostEqual(row.gain or 0.0, 200.00, places=2)
        self.assertAlmostEqual(row.growth or 0.0, 0.0952, places=4)
        self.assertAlmostEqual(row.purchase_price or 0.0, 10.50, places=2)

    def test_without_the_line_every_one_of_them_is_absent(self) -> None:
        # None rather than zero, all the way down. A zero cost would report
        # $2,300.00 of pure profit on an account nobody has priced.
        row = positions(portfolio=self._read(), classes={}, income={}, history={})[0]

        self.assertIsNone(row.cost_basis)
        self.assertIsNone(row.gain)
        self.assertIsNone(row.growth)
        self.assertIsNone(row.purchase_price)


if __name__ == "__main__":
    unittest.main()

"""An Ally run can succeed and still have lost an account.

The holdings page shows one account's positions but lists every account in the
left-hand rail, and the rail is the only place the page says how many accounts
exist. When its selectors stop matching, ``scrape_accounts()`` falls back to the
account named in the page heading -- which is always exactly the one already on
screen. One account is reported, the run prints "Ally sync complete", and a
second account is simply never mentioned.

That is the failure mode worth catching: not a crash, but a success that is
quietly incomplete. It has to announce itself and save the markup while the page
is still rendered, because every existing capture path fires on pages that never
rendered at all and so can never show what the rail actually looks like.

The rail also has to be waited for. It renders after the holdings do, and the
module only ever waited on the holdings -- so a rail that had merely not arrived
yet read exactly like a rail whose selectors had moved. That conclusion was
drawn once, from a live run, and the very next run parsed the same rail without
complaint.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from helpers.ally import SIDEBAR_SELECTOR
from modules.ally_module import AllyModule, capture_holdings

FIXTURE = Path(__file__).resolve().parent / "ally_holdings.html"

#: A rendered page with no account rail on it at all.
NO_RAIL = (
    "<html><body><holdings-account-totals></holdings-account-totals></body></html>"
)


def _run(markup: str, capture: str | None = "/tmp/ally-empty-account-rail.html"):
    """Drive on_login() over markup, with the scrape itself stubbed out."""
    connection = MagicMock()
    connection.page.content.return_value = markup
    connection.capture_page.return_value = capture

    module = AllyModule()
    module.scrape_accounts = MagicMock(
        return_value=[{"Label": "Individual (...0847)", "Holdings": []}]
    )
    context = MagicMock()

    # A real run carries the flag as False. Left as a MagicMock it is truthy,
    # which sends every one of these down the --from-prices path -- where the
    # rail is never read, so half of them would pass for the wrong reason.
    context.args.from_prices = False

    module.on_login(context, connection)
    return connection, context


def _highlights(context: MagicMock) -> str:
    return " ".join(str(object=c) for c in context.log.highlight.call_args_list)


class CaptureReason(unittest.TestCase):
    """The filename has to name what surprised the run."""

    def test_the_slug_is_passed_through(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = "/tmp/x.html"

        capture_holdings(connection=connection, reason="empty-account-rail")

        self.assertEqual(
            connection.capture_page.call_args.kwargs["reason"], "empty-account-rail"
        )

    def test_the_default_is_still_the_page_that_never_rendered(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = "/tmp/x.html"

        capture_holdings(connection=connection)

        self.assertEqual(
            connection.capture_page.call_args.kwargs["reason"], "no-holdings"
        )


class RailPresent(unittest.TestCase):
    """The ordinary run must stay quiet."""

    def test_a_page_with_a_rail_captures_nothing(self) -> None:
        connection, _context = _run(markup=FIXTURE.read_text(encoding="utf-8"))

        connection.capture_page.assert_not_called()

    def test_and_says_nothing_about_selectors(self) -> None:
        _connection, context = _run(markup=FIXTURE.read_text(encoding="utf-8"))

        self.assertNotIn("account rail", _highlights(context))


class RailMissing(unittest.TestCase):
    """The incomplete run must announce itself and leave evidence."""

    def test_the_markup_is_saved(self) -> None:
        connection, _context = _run(markup=NO_RAIL)

        self.assertEqual(
            connection.capture_page.call_args.kwargs["reason"], "empty-account-rail"
        )

    def test_it_says_which_file_to_look_at(self) -> None:
        _connection, context = _run(markup=NO_RAIL)

        self.assertIn("/tmp/ally-empty-account-rail.html", _highlights(context))

    def test_it_names_where_the_selectors_live(self) -> None:
        _connection, context = _run(markup=NO_RAIL)

        self.assertIn("helpers/ally.py", _highlights(context))

    def test_it_does_not_claim_the_selectors_moved(self) -> None:
        """A live run disproved that: the next run parsed the same rail."""
        _connection, context = _run(markup=NO_RAIL)

        self.assertNotIn("have moved", _highlights(context))

    def test_the_rail_is_waited_for_before_being_called_missing(self) -> None:
        """Waiting only on the holdings is what made the rail look absent."""
        connection, _context = _run(markup=NO_RAIL)
        waited = [
            call.args[0] if call.args else call.kwargs.get("selector")
            for call in connection.page.wait_for_selector.call_args_list
        ]

        self.assertIn(SIDEBAR_SELECTOR, waited)

    def test_it_is_still_reported_when_the_capture_fails(self) -> None:
        # Losing the markup must not also lose the warning.
        _connection, context = _run(markup=NO_RAIL, capture=None)

        self.assertIn("account rail", _highlights(context))

    def test_the_run_still_succeeds(self) -> None:
        # The positions on screen are real and belong in the database; an
        # incomplete run is worth more than no run.
        connection, _context = _run(markup=NO_RAIL)

        connection.capture_page.assert_called()


if __name__ == "__main__":
    unittest.main()

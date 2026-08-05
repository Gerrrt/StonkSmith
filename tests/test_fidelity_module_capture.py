"""A Fidelity scrape that finds nothing must leave usable evidence.

The previous advice was "re-run with -o DEBUG_DUMP=1". That never worked: the
dump logged at INFO, which the default log level hides, so running it produced
no output at all. It also would not have helped -- 4000 chars of console text is
not something selectors can be fixed from.
"""

import unittest
from unittest.mock import MagicMock

from modules.fidelity_module import FidelityModule, capture_summary


class CaptureSummaryTests(unittest.TestCase):
    def test_delegates_to_the_brokers_capture(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = "/tmp/fidelity-no-accounts.html"

        result = capture_summary(connection=connection)

        self.assertEqual(result, "/tmp/fidelity-no-accounts.html")
        self.assertEqual(
            connection.capture_page.call_args.kwargs["reason"], "no-accounts"
        )

    def test_connection_without_capture_returns_none(self) -> None:
        # A non-browser broker has no page to capture.
        connection = MagicMock(spec=[])

        self.assertIsNone(capture_summary(connection=connection))


class NoAccountsReportingTests(unittest.TestCase):
    def _run(self, connection: MagicMock) -> MagicMock:
        module = FidelityModule()
        module.scrape_accounts = MagicMock(return_value=[])
        context = MagicMock()

        # Scraping nothing is a failed sync, not an empty successful one.
        assert module.on_login(context, connection) is False
        return context

    def test_capture_path_is_named_in_the_failure(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = "/tmp/fidelity-no-accounts.html"

        context = self._run(connection)

        reported = " ".join(str(c) for c in context.log.fail.call_args_list)
        self.assertIn("/tmp/fidelity-no-accounts.html", reported)
        self.assertNotIn("DEBUG_DUMP", reported)

    def test_failure_is_still_reported_when_capture_fails(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = None

        context = self._run(connection)

        reported = " ".join(str(c) for c in context.log.fail.call_args_list)
        self.assertIn("No accounts found", reported)

    def test_nothing_is_saved_to_the_database(self) -> None:
        connection = MagicMock()
        connection.capture_page.return_value = "/tmp/x.html"

        context = self._run(connection)

        context.db.save_account_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()

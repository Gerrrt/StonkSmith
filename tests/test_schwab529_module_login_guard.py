import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from modules.schwab529plan_module import Schwab529Module


class _StubResponse:
    def __init__(self, *, url: str, text: str) -> None:
        self.url = url
        self.text = text


class Schwab529ModuleLoginGuardTests(unittest.TestCase):
    def test_detects_login_page_by_url(self) -> None:
        response = _StubResponse(
            url="https://www.schwab529plan.com/swatpl/aggregator/sessionCreate/collectAggrCredentials.cs",
            text="<html>ok</html>",
        )

        result = Schwab529Module._looks_like_login_page(response=response)  # type: ignore

        self.assertTrue(result)

    def test_detects_login_page_by_form_markers(self) -> None:
        response = _StubResponse(
            url="https://www.schwab529plan.com/some/intermediate/page",
            text="""<input name="struts.token.name" value="x" /><input name="passcode" />""",
        )

        result = Schwab529Module._looks_like_login_page(response=response)  # type: ignore

        self.assertTrue(result)

    def test_does_not_flag_dashboard_like_page(self) -> None:
        response = _StubResponse(
            url="https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs",
            text='<div id="txHistDiv">transactions</div>',
        )

        result = Schwab529Module._looks_like_login_page(response=response)  # type: ignore

        self.assertFalse(result)


class _StubDb:
    """Minimal DB stub that satisfies the save_account_data contract."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object]] = []

    def save_account_data(
        self, account_name: object, balance: object, timestamp: object
    ) -> None:
        self.calls.append((account_name, balance, balance))

    def get_credentials(self, filter_term: object = None) -> list[tuple[str, ...]]:
        return []

    def shutdown_db(self) -> None:
        pass


class _StubDbNoSave:
    """DB stub that deliberately lacks save_account_data."""

    def get_credentials(self, filter_term: object = None) -> list[tuple[str, ...]]:
        return []

    def shutdown_db(self) -> None:
        pass


def _make_on_login_context(db: object) -> MagicMock:
    """Build a minimal context stub."""
    log = MagicMock()
    log.fail = MagicMock()
    log.info = MagicMock()
    log.success = MagicMock()
    log.exception = MagicMock()
    ctx = MagicMock()
    ctx.db = db
    ctx.log = log
    return ctx


def _make_connection(session_response: object) -> MagicMock:
    conn = MagicMock()
    conn.username = "testuser"
    conn.session.get.return_value = session_response
    return conn


class Schwab529ModuleDbContractTests(unittest.TestCase):
    def _dashboard_response(self) -> object:
        resp = MagicMock()
        resp.ok = True
        resp.url = "https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs"
        resp.text = '<div id="txHistDiv">transactions</div>'
        return resp

    @patch("modules.schwab529plan_module.Saver")
    @patch("modules.schwab529plan_module.Parser")
    def test_on_login_saves_balances_with_valid_db_contract(
        self, MockParser: MagicMock, MockSaver: MagicMock
    ) -> None:
        parser_inst = MockParser.return_value
        parser_inst.beneficiary_data.return_value = []
        parser_inst.balance_data.return_value = [
            {"Title": "529 Balance", "Amount": "1000.00"}
        ]
        parser_inst.investment_data.return_value = []
        parser_inst.transaction_data.return_value = []

        MockSaver.return_value.save_beneficiary = MagicMock()
        MockSaver.return_value.save_balance = MagicMock()
        MockSaver.return_value.save_investment = MagicMock()
        MockSaver.return_value.save_transactions = MagicMock()

        db = _StubDb()
        ctx = _make_on_login_context(db=db)
        conn = _make_connection(session_response=self._dashboard_response())

        Schwab529Module().on_login(ctx, conn)

        self.assertEqual(len(db.calls), 1)
        account_name, balance, _ = db.calls[0]
        self.assertEqual(account_name, "529 Balance")
        self.assertEqual(balance, "1000.00")

    @patch("modules.schwab529plan_module.Saver")
    @patch("modules.schwab529plan_module.Parser")
    def test_on_login_fails_cleanly_when_db_missing_save_account_data(
        self, MockParser: MagicMock, MockSaver: MagicMock
    ) -> None:
        parser_inst = MockParser.return_value
        parser_inst.beneficiary_data.return_value = []
        parser_inst.balance_data.return_value = [
            {"Title": "529 Balance", "Amount": "1000.00"}
        ]
        parser_inst.investment_data.return_value = []
        parser_inst.transaction_data.return_value = []

        MockSaver.return_value.save_beneficiary = MagicMock()
        MockSaver.return_value.save_balance = MagicMock()
        MockSaver.return_value.save_investment = MagicMock()
        MockSaver.return_value.save_transactions = MagicMock()

        db = _StubDbNoSave()
        ctx = _make_on_login_context(db=db)
        conn = _make_connection(session_response=self._dashboard_response())

        Schwab529Module().on_login(ctx, conn)

        ctx.log.fail.assert_called_once()
        fail_msg: str = ctx.log.fail.call_args.kwargs.get(
            "msg", ctx.log.fail.call_args[0][0] if ctx.log.fail.call_args[0] else ""
        )
        self.assertIn("save_account_data", fail_msg)


if __name__ == "__main__":
    unittest.main()

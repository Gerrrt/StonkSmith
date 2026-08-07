import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, ClassVar

_BROKER_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "brokers"
    / "schwab529plan"
    / "broker.py"
)
_SPEC = spec_from_file_location("brokers_schwab529plan_file", _BROKER_FILE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Unable to load Schwab529plan broker module for tests")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
Schwab529plan = _MODULE.Schwab529plan


class _StubLogger:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.success_messages: list[str] = []
        self.fail_messages: list[str] = []

    def debug(self, msg: str) -> None:
        self.debug_messages.append(msg)

    def success(self, msg: str) -> None:
        self.success_messages.append(msg)

    def fail(self, msg: str) -> None:
        self.fail_messages.append(msg)

    def highlight(self, msg: str) -> None:
        pass


class _StubResponse:
    def __init__(self, *, text: str, url: str, ok: bool = True) -> None:
        self.text = text
        self.url = url
        self.ok = ok


class _StubSession:
    def __init__(
        self,
        *,
        get_responses: list[_StubResponse],
        post_response: _StubResponse,
    ) -> None:
        self._get_responses = get_responses
        self._get_index = 0
        self._post_response = post_response
        self.post_payload: dict[str, Any] | None = None

    def get(self, url: str, timeout: int = 10) -> _StubResponse:
        response = self._get_responses[self._get_index]
        self._get_index += 1
        return response

    def post(
        self,
        url: str,
        data: dict[str, Any],
        timeout: int = 10,
    ) -> _StubResponse:
        self.post_payload = data
        return self._post_response


class Schwab529LoginDetectionTests(unittest.TestCase):
    def _landing_page_html(self) -> str:
        return (
            "<html><body><form>"
            '<input name="struts.token.name" value="tok_name" />'
            '<input name="token" value="tok_value" />'
            '<input name="tplcb" value="tplcb_value" />'
            "</form></body></html>"
        )

    def test_plaintext_login_success_after_follow_up_get(self) -> None:
        broker = Schwab529plan()
        broker.logger = _StubLogger()  # type: ignore[assignment]

        post_response = _StubResponse(
            text="redirected",
            url="https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs",
            ok=True,
        )
        login_response = _StubResponse(
            text='<div id="txHistDiv"></div>',
            url="https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs",
            ok=True,
        )
        broker.session = _StubSession(  # type: ignore[assignment]
            get_responses=[
                _StubResponse(
                    text=self._landing_page_html(),
                    url=broker.login_url,
                    ok=True,
                ),
                login_response,
            ],
            post_response=post_response,
        )

        result = broker.plaintext_login("alice", "s3cr3t")

        self.assertTrue(result)
        assert isinstance(broker.session, _StubSession)
        assert broker.session.post_payload is not None
        self.assertEqual(broker.session.post_payload["struts.token.name"], "tok_name")
        self.assertEqual(broker.session.post_payload["token"], "tok_value")
        self.assertEqual(broker.session.post_payload["tplcb"], "tplcb_value")
        self.assertEqual(broker.session.post_payload["username"], "alice")
        self.assertEqual(broker.session.post_payload["passcode"], "s3cr3t")

    def test_plaintext_login_fails_when_follow_up_is_login_page(self) -> None:
        broker = Schwab529plan()
        broker.logger = _StubLogger()  # type: ignore[assignment]

        post_response = _StubResponse(
            text="still login",
            url=broker.login_url,
            ok=True,
        )
        login_response = _StubResponse(
            text="""<input name="struts.token.name" value="tok_name" />""",
            url=broker.login_url,
            ok=True,
        )
        broker.session = _StubSession(  # type: ignore[assignment]
            get_responses=[
                _StubResponse(
                    text=self._landing_page_html(),
                    url=broker.login_url,
                    ok=True,
                ),
                login_response,
            ],
            post_response=post_response,
        )

        result = broker.plaintext_login("alice", "bad-password")

        self.assertFalse(result)


_PARSER_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "brokers"
    / "schwab529plan"
    / "parser.py"
)
_PARSER_SPEC = spec_from_file_location("brokers_schwab529plan_parser", _PARSER_FILE)
if _PARSER_SPEC is None or _PARSER_SPEC.loader is None:
    raise RuntimeError("Unable to load Schwab529plan parser module for tests")
_PARSER_MODULE = module_from_spec(_PARSER_SPEC)
_PARSER_SPEC.loader.exec_module(_PARSER_MODULE)
Parser = _PARSER_MODULE.Parser


def _fund_table(caption: str, rows: list[tuple[str, str, str, str, str]]) -> str:
    """Build a fund table in the shape the dashboard renders."""

    body: str = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )

    return (
        f"<table><caption>{caption}</caption>"
        f"<tbody>{body}</tbody>"
        "<tfoot>"
        "<tr><td>$3,000.00</td></tr>"
        "<tr><td>$2,500.00</td></tr>"
        "<tr><td>$500.00</td></tr>"
        "</tfoot></table>"
    )


def _dashboard(tables: str) -> str:
    """Wrap markup in the nesting the parser's absolute xpath expects."""

    return (
        "<html><body><div><div><div><div><div>"
        f"{tables}"
        "</div></div></div></div></body></html>"
    )


class Schwab529InvestmentParsingTests(unittest.TestCase):
    """A fund table has as many holdings as it has rows.

    The original spelling evaluated `.//tbody/tr/td[1]/text()` against the
    *table* and took `.get()`, which returns the first match. An account holding
    six funds reported one, and the other five were silently dropped -- which
    only became visible once holdings were stored rather than pushed straight to
    a sheet that nobody diffed.
    """

    ROWS: ClassVar[list[tuple[str, str, str, str, str]]] = [
        ("SWX01", "Index 2030", "10.5", "$117.58", "$1,234.56"),
        ("SWX02", "Index 2035", "5.25", "$200.00", "$1,050.00"),
        ("SWX03", "Bond Fund", "7.0", "$100.00", "$700.00"),
    ]

    def parse(self, html: str) -> list[dict[str, Any]]:
        response = _StubResponse(text=html, url="https://www.schwab529plan.com/")
        return Parser(response=response).investment_data()

    def test_every_row_becomes_a_holding(self) -> None:
        holdings = self.parse(_dashboard(_fund_table("Ezekiel", self.ROWS)))

        self.assertEqual(len(holdings), 3)

    def test_each_holding_keeps_its_own_fund(self) -> None:
        holdings = self.parse(_dashboard(_fund_table("Ezekiel", self.ROWS)))

        self.assertEqual(
            [item["Fund Code"] for item in holdings], ["SWX01", "SWX02", "SWX03"]
        )
        self.assertEqual(
            [item["Value"] for item in holdings],
            ["$1,234.56", "$1,050.00", "$700.00"],
        )

    def test_table_level_totals_are_repeated_onto_every_row(self) -> None:
        holdings = self.parse(_dashboard(_fund_table("Ezekiel", self.ROWS)))

        for holding in holdings:
            self.assertEqual(holding["Total Assets"], "$3,000.00")
            self.assertEqual(holding["Principal"], "$2,500.00")
            self.assertEqual(holding["Earnings"], "$500.00")
            self.assertEqual(holding["Title"], "Ezekiel")

    def test_holdings_carry_the_index_of_the_table_they_came_from(self) -> None:
        # This is what pairs a holding with its account: the page renders one
        # fund table per beneficiary, in the same order as the balance headings.
        markup: str = _fund_table("Ezekiel", self.ROWS[:2]) + _fund_table(
            "Naomi", self.ROWS[2:]
        )

        holdings = self.parse(_dashboard(markup))

        self.assertEqual([item["Table"] for item in holdings], [0, 0, 1])
        self.assertEqual(holdings[2]["Title"], "Naomi")

    def test_a_single_row_table_still_works(self) -> None:
        holdings = self.parse(_dashboard(_fund_table("Ezekiel", self.ROWS[:1])))

        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["Fund Code"], "SWX01")

    def test_a_page_with_no_fund_table_yields_nothing(self) -> None:
        self.assertEqual(self.parse(_dashboard("")), [])

    def test_a_row_with_no_cells_is_skipped(self) -> None:
        markup: str = (
            "<table><caption>Ezekiel</caption><tbody>"
            "<tr><th>Fund</th></tr>"
            "<tr><td>SWX01</td><td>Index 2030</td><td>1</td><td>$1.00</td>"
            "<td>$1.00</td></tr>"
            "</tbody></table>"
        )

        holdings = self.parse(_dashboard(markup))

        self.assertEqual(len(holdings), 1)


#: The six columns the transaction table has always printed, in order.
_TX_ROW: tuple[str, str, str, str, str, str] = (
    "12/30/2025",
    "12/29/2025",
    "Contribution",
    "1",
    "$50.00",
    "$50.00",
)


def _tx_row(cells: tuple[str, ...], attrs: str = "") -> str:
    """Build one transaction row, optionally carrying attributes."""

    return f"<tr{attrs}>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _tx_table(
    body: str, headers: tuple[str, ...] | None = None, caption: str | None = None
) -> str:
    """Build a transaction table in the shape the dashboard renders."""

    head: str = (
        "<thead><tr>"
        + "".join(f"<th>{cell}</th>" for cell in headers)
        + "</tr></thead>"
        if headers
        else ""
    )
    top: str = f"<caption>{caption}</caption>" if caption else ""

    return f"<table>{top}{head}<tbody>{body}</tbody></table>"


def _tx_div(tables: str) -> str:
    """Wrap transaction markup in the div the parser looks the table up by."""

    return f'<html><body><div id="txHistDiv">{tables}</div></body></html>'


class Schwab529TransactionParsingTests(unittest.TestCase):
    """What the transaction table says about which account a row belongs to.

    Issue #36: on a multi-beneficiary page the movements were dropped entirely,
    because the parser read one page-wide selector and stamped nothing onto a
    row naming its account. It now reads all four places a marker could be --
    the table's position, its caption, a section heading, and the row itself --
    and none of them existing is still a valid answer.
    """

    def parse(self, html: str) -> list[dict[str, Any]]:
        response = _StubResponse(text=html, url="https://www.schwab529plan.com/")
        return Parser(response=response).transaction_data()

    def test_the_plain_six_column_table_reads_as_it_always_did(self) -> None:
        rows = self.parse(_tx_div(_tx_table(_tx_row(_TX_ROW))))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Processed"], "12/30/2025")
        self.assertEqual(rows[0]["Traded"], "12/29/2025")
        self.assertEqual(rows[0]["Type"], "Contribution")
        self.assertEqual(rows[0]["Units"], "1")
        self.assertEqual(rows[0]["Price"], "$50.00")
        self.assertEqual(rows[0]["Value"], "$50.00")

    def test_a_page_with_no_transaction_table_yields_nothing(self) -> None:
        self.assertEqual(self.parse(_tx_div("")), [])

    def test_the_known_rendering_names_no_account(self) -> None:
        # The whole of issue #36 in one assertion: nothing here says whose
        # movement this is, and the parser must not pretend otherwise.
        rows = self.parse(_tx_div(_tx_table(_tx_row(_TX_ROW))))

        self.assertIsNone(rows[0]["Account"])
        self.assertIsNone(rows[0]["Section"])
        self.assertIsNone(rows[0]["Title"])

    def test_rows_carry_the_index_of_the_table_they_came_from(self) -> None:
        markup: str = _tx_table(_tx_row(_TX_ROW) * 2) + _tx_table(_tx_row(_TX_ROW))

        rows = self.parse(_tx_div(markup))

        self.assertEqual([row["Table"] for row in rows], [0, 0, 1])

    def test_a_table_wrapped_in_a_container_is_still_found(self) -> None:
        # The old xpath required the table to be a direct child of the div, so
        # a page that wraps each account's table yielded nothing at all.
        rows = self.parse(
            _tx_div(f"<div><div>{_tx_table(_tx_row(_TX_ROW))}</div></div>")
        )

        self.assertEqual(len(rows), 1)

    def test_a_nested_table_is_not_counted_twice(self) -> None:
        # A table wrapping another is layout. Reading both would emit the inner
        # rows once on their own and once through the wrapper's descendant
        # rows, doubling every movement.
        inner: str = _tx_table(_tx_row(_TX_ROW))
        outer: str = f"<table><tbody><tr><td>{inner}</td></tr></tbody></table>"

        rows = self.parse(_tx_div(outer))

        self.assertEqual([row["Table"] for row in rows], [0])
        self.assertEqual(rows[0]["Processed"], "12/30/2025")

    def test_a_caption_is_read_as_the_tables_title(self) -> None:
        rows = self.parse(
            _tx_div(_tx_table(_tx_row(_TX_ROW), caption="Ezekiel 529 Plan"))
        )

        self.assertEqual(rows[0]["Title"], "Ezekiel 529 Plan")

    def test_an_account_column_is_read_by_its_header(self) -> None:
        headers = ("Account", "Processed", "Traded", "Type", "Units", "Price", "Value")
        rows = self.parse(
            _tx_div(_tx_table(_tx_row(("ACC-1", *_TX_ROW)), headers=headers))
        )

        self.assertEqual(rows[0]["Account"], "ACC-1")

    def test_an_extra_column_does_not_shift_the_other_six(self) -> None:
        # Fixed td[1]..td[6] would have read the account as Processed and slid
        # every other field one column left, filling the database with
        # plausible nonsense.
        headers = ("Account", "Processed", "Traded", "Type", "Units", "Price", "Value")
        rows = self.parse(
            _tx_div(_tx_table(_tx_row(("ACC-1", *_TX_ROW)), headers=headers))
        )

        self.assertEqual(rows[0]["Processed"], "12/30/2025")
        self.assertEqual(rows[0]["Value"], "$50.00")

    def test_a_header_row_inside_the_body_is_not_a_transaction(self) -> None:
        # It used to become a movement with every field None.
        body: str = (
            "<tr><th>Processed</th><th>Traded</th><th>Type</th>"
            "<th>Units</th><th>Price</th><th>Value</th></tr>"
        ) + _tx_row(_TX_ROW)

        rows = self.parse(_tx_div(_tx_table(body)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Processed"], "12/30/2025")
        self.assertIsNone(rows[0]["Section"], "a header row is not a section")

    def test_a_section_heading_is_carried_onto_the_rows_beneath_it(self) -> None:
        body: str = (
            '<tr><td colspan="6">Ezekiel -- Account 1234</td></tr>'
            + _tx_row(_TX_ROW)
            + '<tr><td colspan="6">Naomi -- Account 5678</td></tr>'
            + _tx_row(_TX_ROW)
        )

        rows = self.parse(_tx_div(_tx_table(body)))

        self.assertEqual(len(rows), 2, "a heading is not itself a movement")
        self.assertEqual(rows[0]["Section"], "Ezekiel -- Account 1234")
        self.assertEqual(rows[1]["Section"], "Naomi -- Account 5678")

    def test_an_account_attribute_on_the_row_is_read(self) -> None:
        rows = self.parse(
            _tx_div(
                _tx_table(_tx_row(_TX_ROW, attrs=' data-account-number="XXXX4321"'))
            )
        )

        self.assertEqual(rows[0]["Account"], "XXXX4321")

    def test_a_title_on_a_cell_is_read(self) -> None:
        # A page that labels one cell will not have labelled the row too, so
        # reading title off the row alone misses the marker entirely.
        row: str = (
            "<tr><td>12/30/2025</td><td>12/29/2025</td>"
            '<td title="Naomi">Contribution</td>'
            "<td>1</td><td>$50.00</td><td>$50.00</td></tr>"
        )

        rows = self.parse(_tx_div(_tx_table(row)))

        self.assertEqual(rows[0]["Account"], "Naomi")

    def test_a_named_attribute_beats_a_title(self) -> None:
        # A title is as likely to read "Click to expand" as a beneficiary.
        rows = self.parse(
            _tx_div(
                _tx_table(
                    _tx_row(
                        _TX_ROW,
                        attrs=' title="Click to expand" data-account="ACC-1"',
                    )
                )
            )
        )

        self.assertEqual(rows[0]["Account"], "ACC-1")

    def test_an_account_attribute_on_a_cell_is_read(self) -> None:
        row: str = (
            '<tr><td data-beneficiary="Naomi">12/30/2025</td>'
            "<td>12/29/2025</td><td>Contribution</td>"
            "<td>1</td><td>$50.00</td><td>$50.00</td></tr>"
        )

        rows = self.parse(_tx_div(_tx_table(row)))

        self.assertEqual(rows[0]["Account"], "Naomi")

    def test_a_spacer_row_is_skipped(self) -> None:
        body: str = "<tr><td></td><td></td></tr>" + _tx_row(_TX_ROW)

        rows = self.parse(_tx_div(_tx_table(body)))

        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()

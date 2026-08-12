"""
Parse data downloaded from https://www.schwab529plan.com
"""

from typing import Any

import parsel

from stonksmith.helpers.schwab529plan import column_map


class Parser:
    """
    Parse data downloaded from https://www.schwab529plan.com
    """

    def __init__(self, response: Any) -> None:
        self.response: Any = response
        self.selector: parsel.Selector = parsel.Selector(text=response.text)

    def beneficiary_data(self) -> list[dict[str, str | None]]:
        """
        Parse data downloaded from https://www.schwab529plan.com
        :return: List of beneficiary data dictionaries
        """

        return [
            {
                "Title": beneficiary.xpath(query=".//text()").get(),
                "Name": beneficiary.xpath(query=".//span[1]/text()").get(),
                "Account": beneficiary.xpath(query=".//span[2]/text()").get(),
            }
            for beneficiary in self.selector.xpath(
                query="/html/body/div/div/div[1]/div/div/div[1]/h2"
            )
        ]

    def balance_data(self) -> list[dict[str, str | None]]:
        """
        Parse data downloaded from https://www.schwab529plan.com
        :return: List of balance data dictionaries
        """

        return [
            {
                "Title": balance.xpath(query=".//text()").get(),
                "Amount": balance.xpath(query=".//span[1]/text()").get(),
                "Date": balance.xpath(query=".//span[2]/text()").get(),
            }
            for balance in self.selector.xpath(
                query="/html/body/div/div/div[1]/div/div/div[2]/h2"
            )
        ]

    def investment_data(self) -> list[dict[str, Any]]:
        """
        Parse the fund tables from https://www.schwab529plan.com

        One dictionary per holding, not per table. The obvious spelling --
        ``.//tbody/tr/td[1]/text()`` evaluated against the table -- returns the
        *first* match, so an account holding six funds reported exactly one of
        them and the other five were never seen. Cells therefore come from the
        row, and only the caption and the ``tfoot`` totals come from the table.

        ``Table`` is the table's position on the page, which is what pairs a
        holding with its account: the page renders one fund table per
        beneficiary, in the same order as the balance headings.
        :return: List of holding dictionaries, in page order
        :rtype: list[dict[str, Any]]
        """

        investment_data: list[dict[str, Any]] = []

        for index, investment in enumerate(
            self.selector.xpath(query="/html/body/div/div/div[1]/div/div/table")
        ):
            # Table-level, repeated onto every row so a holding carries the
            # account totals it belongs to without a second lookup.
            shared: dict[str, Any] = {
                "Table": index,
                "Title": investment.xpath(query=".//caption/text()").get(),
                "Total Assets": investment.xpath(
                    query=".//tfoot/tr[1]/td/text()"
                ).get(),
                "Principal": investment.xpath(query=".//tfoot/tr[2]/td/text()").get(),
                "Earnings": investment.xpath(query=".//tfoot/tr[3]/td/text()").get(),
            }

            for row in investment.xpath(query=".//tbody/tr"):
                # Single slash: a nested table inside this row would otherwise
                # contribute its cells to this holding.
                cells: list[str] = row.xpath(query="./td/text()").getall()

                if not cells:
                    # A spacer or header row inside the body.
                    continue

                investment_data.append(
                    {
                        **shared,
                        "Fund Code": row.xpath(query="./td[1]/text()").get(),
                        "Fund": row.xpath(query="./td[2]/text()").get(),
                        "Units": row.xpath(query="./td[3]/text()").get(),
                        "Price": row.xpath(query="./td[4]/text()").get(),
                        "Value": row.xpath(query="./td[5]/text()").get(),
                    }
                )

        return investment_data

    def transaction_tables(self) -> Any:
        """
        Select the transaction tables on the page.

        ``//*[@id='txHistDiv']/table`` only matched a table that is a direct
        child of the div, so a page that wraps each account's table in a
        container yielded nothing at all. Descendant tables are matched
        instead, restricted to those holding no table of their own: a table
        wrapping another is layout, and counting both reads every row twice --
        once on its own and once through the wrapper's ``.//tbody/tr``.
        :return: The table selectors, in page order
        :rtype: parsel.SelectorList
        """

        return self.selector.xpath(query="//*[@id='txHistDiv']//table[not(.//table)]")

    @staticmethod
    def _text(node: Any) -> str:
        """
        Read all the text under a node with its whitespace collapsed.
        :param node: Any selector
        :return: The text, possibly empty
        :rtype: str
        """

        return " ".join("".join(node.xpath(query=".//text()").getall()).split())

    @staticmethod
    def _caption(table: Any) -> str | None:
        """
        Read a table's caption with its whitespace collapsed.
        :param table: One table selector
        :return: The caption, or None when it has none
        :rtype: str | None
        """

        texts: list[str] = table.xpath(query=".//caption//text()").getall()

        return " ".join("".join(texts).split()) or None

    @staticmethod
    def _header_row(table: Any) -> Any:
        """
        Find the row a table uses as its header when it has no ``thead``.

        Returned rather than just its text because the row loop has to skip it:
        a row of ``th`` reading "Processed Traded Type..." is a header, and
        mistaking it for a section heading would stamp the column names onto
        every transaction beneath it as though they named an account.
        :param table: One table selector
        :return: The header row selector, or None
        """

        if table.xpath(query=".//thead//th"):
            return None

        for row in table.xpath(query=".//tbody/tr"):
            if row.xpath(query="./th") and not row.xpath(query="./td"):
                return row

        return None

    def _header_cells(self, table: Any) -> list[str]:
        """
        Read a transaction table's header row, wherever it put it.

        Some tables use ``thead``; some open ``tbody`` with a row of ``th``.
        Either is a header; neither is a transaction.
        :param table: One table selector
        :return: The header texts, in column order
        :rtype: list[str]
        """

        headers: list[str] = [
            self._text(node=cell) for cell in table.xpath(query=".//thead//th")
        ]

        if headers:
            return headers

        row: Any = self._header_row(table=table)

        if row is None:
            return []

        return [self._text(node=cell) for cell in row.xpath(query="./th")]

    @staticmethod
    def _row_account_attribute(row: Any) -> str | None:
        """
        Look for an account named in the row's markup rather than its text.

        A ``data-account-number`` on the ``tr``, an account id on a cell, a
        ``title`` spelling out whose row it is -- issue #36 lists this as one of
        the three places the attribution could be hiding. Attribute *names* are
        matched rather than enumerated, so a spelling nobody predicted still
        works.
        :param row: One row selector
        :return: The account text, or None
        :rtype: str | None
        """

        elements: list[Any] = [row, *row.xpath(query="./td")]

        for element in elements:
            attributes: dict[str, str] = element.attrib

            for name, value in attributes.items():
                lowered: str = name.lower()

                if ("account" in lowered or "beneficiary" in lowered) and value.strip():
                    return " ".join(value.split())

        # Only once no attribute names an account outright. A title is the
        # weakest of the three -- it is as likely to read "Click to expand" as
        # a beneficiary's name -- but it is read off the cells as well as the
        # row, because a page that labels one cell will not have labelled the
        # row too.
        for element in elements:
            title: str = element.attrib.get("title", "")

            if title.strip():
                return " ".join(title.split())

        return None

    def transaction_data(self) -> list[dict[str, Any]]:
        """
        Parse the transaction tables from https://www.schwab529plan.com

        One dictionary per movement. Alongside the six fields the sheet has
        always shown, a row carries whatever the page said about which account
        it belongs to -- see issue #36, which exists because the one rendering
        anybody has looked at says nothing at all:

        - ``Table`` is the table's position, which pairs a row with an account
          the same way ``investment_data()`` pairs a holding, when the page
          renders one table per beneficiary.
        - ``Title`` is the table's caption.
        - ``Section`` is the most recent heading row above this one, carried
          down until the next heading.
        - ``Account`` is an account named on the row itself, by a column or by
          an attribute.

        All four may be None. ``Schwab529Module.attribute_transactions()``
        decides what, if anything, they are worth.
        :return: List of transaction dictionaries, in page order
        :rtype: list[dict[str, Any]]
        """

        transaction_data: list[dict[str, Any]] = []

        for index, table in enumerate(iterable=self.transaction_tables()):
            columns: dict[str, int] = column_map(
                headers=self._header_cells(table=table)
            )

            shared: dict[str, Any] = {
                "Table": index,
                "Title": self._caption(table=table),
            }

            header_row: Any = self._header_row(table=table)
            header_element: Any = None if header_row is None else header_row.root
            section: str | None = None

            for row in table.xpath(query=".//tbody/tr"):
                if row.root is header_element:
                    continue

                heading: str | None = self._heading_text(row=row)

                if heading is not None:
                    # A "Beneficiary A -- Account 1234" banner above the rows it
                    # applies to. Carried down rather than stored as a movement
                    # of zero dollars, which is what it became before.
                    section = heading or None
                    continue

                # Single slash: a nested table inside this row would otherwise
                # contribute its cells to this transaction.
                cells: list[str] = [
                    self._text(node=cell) for cell in row.xpath(query="./td")
                ]

                if not any(cells):
                    # A spacer row inside the body.
                    continue

                transaction_data.append(
                    {
                        **shared,
                        "Section": section,
                        "Account": self._cell(
                            cells=cells, columns=columns, name="Account"
                        )
                        or self._row_account_attribute(row=row),
                        "Processed": self._cell(
                            cells=cells, columns=columns, name="Processed", position=0
                        ),
                        "Traded": self._cell(
                            cells=cells, columns=columns, name="Traded", position=1
                        ),
                        "Type": self._cell(
                            cells=cells, columns=columns, name="Type", position=2
                        ),
                        "Units": self._cell(
                            cells=cells, columns=columns, name="Units", position=3
                        ),
                        "Price": self._cell(
                            cells=cells, columns=columns, name="Price", position=4
                        ),
                        "Value": self._cell(
                            cells=cells, columns=columns, name="Value", position=5
                        ),
                    }
                )

        return transaction_data

    def _heading_text(self, row: Any) -> str | None:
        """
        Read a row that groups the rows beneath it rather than being one.

        Two shapes: a row made only of ``th``, and a single cell spanning the
        table. A ``th`` used as a row stub alongside real ``td`` cells is not a
        heading -- that row is a transaction with a label on it.
        :param row: One row selector
        :return: The heading text when the row is one, otherwise None. The text
            may be empty, which still means "this is not a transaction".
        :rtype: str | None
        """

        cells: list[Any] = row.xpath(query="./td")

        if row.xpath(query="./th") and not cells:
            return self._text(node=row)

        if len(cells) == 1 and cells[0].attrib.get("colspan"):
            return self._text(node=row)

        return None

    @staticmethod
    def _cell(
        cells: list[str],
        columns: dict[str, int],
        name: str,
        position: int | None = None,
    ) -> str | None:
        """
        Read one field off a row, by header when the table has one and by
        position when it does not.
        :param cells: The row's cell texts, in column order
        :param columns: Field name to column index, empty when unmapped
        :param name: The field being read
        :param position: The column this field has always occupied, when it has
            one. Account has none: a table without a header has no account
            column to fall back to.
        :return: The cell text, or None
        :rtype: str | None
        """

        index: int | None = columns.get(name, position if not columns else None)

        if index is None or index >= len(cells):
            return None

        return cells[index] or None

    def transaction_structure(self) -> list[dict[str, Any]]:
        """
        Describe the shape of the transaction markup without reading its values.

        Issue #36's blocking unknown is what a multi-beneficiary ``txHistDiv``
        actually renders, and nobody has one to look at. This reports enough to
        answer that from a single live run: how many tables there are, what
        their columns are called, and what attribute names the rows carry.

        Captions and column headers are included because they are the answer --
        a column headed "Account" is the whole question. Cell text is not: the
        dates and amounts in the body would tell an operator nothing they do not
        already know and do not belong in a diagnostic.
        :return: One description per table, in page order
        :rtype: list[dict[str, Any]]
        """

        structure: list[dict[str, Any]] = []

        for index, table in enumerate(iterable=self.transaction_tables()):
            widths: set[int] = set()
            attributes: set[str] = set()

            rows: list[Any] = table.xpath(query=".//tbody/tr")

            for row in rows:
                cells: list[Any] = row.xpath(query="./td")
                widths.add(len(cells))
                attributes.update(row.attrib)

                for cell in cells:
                    attributes.update(cell.attrib)

            structure.append(
                {
                    "Table": index,
                    "Caption": self._caption(table=table),
                    "Headers": self._header_cells(table=table),
                    "Rows": len(rows),
                    "Widths": sorted(widths),
                    "Attributes": sorted(attributes),
                }
            )

        return structure

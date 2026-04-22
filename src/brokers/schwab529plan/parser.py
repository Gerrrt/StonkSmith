"""
Parse data downloaded from https://www.schwab529plan.com
"""

from typing import Any

import parsel


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

        beneficiary_data: list[dict[str, str | None]] = []

        for beneficiary in self.selector.xpath(
            query="/html/body/div/div/div[1]/div/div/div[1]/h2"
        ):
            beneficiary_data.append(
                {
                    "Title": beneficiary.xpath(query=".//text()").get(),
                    "Name": beneficiary.xpath(query=".//span[1]/text()").get(),
                    "Account": beneficiary.xpath(query=".//span[2]/text()").get(),
                }
            )

        return beneficiary_data

    def balance_data(self) -> list[dict[str, str | None]]:
        """
        Parse data downloaded from https://www.schwab529plan.com
        :return: List of balance data dictionaries
        """

        balance_data: list[dict[str, str | None]] = []

        for balance in self.selector.xpath(
            query="/html/body/div/div/div[1]/div/div/div[2]/h2"
        ):
            balance_data.append(
                {
                    "Title": balance.xpath(query=".//text()").get(),
                    "Amount": balance.xpath(query=".//span[1]/text()").get(),
                    "Date": balance.xpath(query=".//span[2]/text()").get(),
                }
            )

        return balance_data

    def investment_data(self) -> list[dict[str, str | None]]:
        """
        Parse data downloaded from https://www.schwab529plan.com
        :return: List of investment data dictionaries
        """

        investment_data: list[dict[str, str | None]] = []

        for investment in self.selector.xpath(
            query="/html/body/div/div/div[1]/div/div/table"
        ):
            investment_data.append(
                {
                    "Title": investment.xpath(query=".//caption/text()").get(),
                    "Fund Code": investment.xpath(
                        query=".//tbody/tr/td[1]/text()"
                    ).get(),
                    "Fund": investment.xpath(query=".//tbody/tr/td[2]/text()").get(),
                    "Units": investment.xpath(query=".//tbody/tr/td[3]/text()").get(),
                    "Price": investment.xpath(query=".//tbody/tr/td[4]/text()").get(),
                    "Current Value": investment.xpath(
                        query=".//tbody/tr/td[5]/text()"
                    ).get(),
                    "Total Assets": investment.xpath(
                        query=".//tfoot/tr[1]/td/text()"
                    ).get(),
                    "Principal": investment.xpath(
                        query=".//tfoot/tr[2]/td/text()"
                    ).get(),
                    "Earnings": investment.xpath(
                        query=".//tfoot/tr[3]/td/text()"
                    ).get(),
                }
            )

        return investment_data

    def transaction_data(self) -> list[dict[str, str | None]]:
        """
        Parse data downloaded from https://www.schwab529plan.com
        :return: List of transaction data dictionaries
        """

        transaction_data: list[dict[str, str | None]] = []

        for transaction in self.selector.xpath(
            query="//*[@id='txHistDiv']/table/tbody/tr"
        ):
            transaction_data.append(
                {
                    "Processed": transaction.xpath(query=".//td[1]/text()").get(),
                    "Traded": transaction.xpath(query=".//td[2]/text()").get(),
                    "Type": transaction.xpath(query=".//td[3]/text()").get(),
                    "Units": transaction.xpath(query=".//td[4]/text()").get(),
                    "Price": transaction.xpath(query=".//td[5]/text()").get(),
                    "Value": transaction.xpath(query=".//td[6]/text()").get(),
                }
            )

        return transaction_data

"""
Parse data downloaded from https://www.schwab529plan.com
"""

from parsel import Selector  # ty:ignore[unresolved-import]


class Parser:
    def __init__(self, response):
        self.response = response
        self.selector = Selector(response.text)

    def beneficiary_data(self):
        beneficiary_data = []

        for beneficiary in self.selector.xpath(
            "/html/body/div/div/div[1]/div/div/div[1]/h2"
        ):
            beneficiary_data.append(
                {
                    "Title": beneficiary.xpath(".//text()").get(),
                    "Name": beneficiary.xpath(".//span[1]/text()").get(),
                    "Account": beneficiary.xpath(".//span[2]/text()").get(),
                }
            )

        return beneficiary_data

    def balance_data(self):
        balance_data = []

        for balance in self.selector.xpath(
            "html/body/div/div/div[1]/div/div/div[2]/h2"
        ):
            balance_data.append(
                {
                    "Title": balance.xpath(".//text()").get(),
                    "Amount": balance.xpath(".//span[1]/text()").get(),
                    "Data": balance.xpath(".//span[2]/text()").get(),
                }
            )

        return balance_data

    def investment_data(self):
        investment_data = []

        for investment in self.selector.xpath(
            "/html/body/div/div/div[1]/div/div/table"
        ):
            investment_data.append(
                {
                    "Title": investment.xpath(".//caption/text()").get(),
                    "Fund Code": investment.xpath(".//tbody/tr/td[1]/text()").get(),
                    "Fund": investment.xpath(".//tbody/tr/td[2]/text()").get(),
                    "Units": investment.xpath(".//tbody/tr/td[3]/text()").get(),
                    "Price": investment.xpath(".//tbody/tr/td[4]/text()").get(),
                    "Current Value": investment.xpath(".//tbody/tr/td[5]/text()").get(),
                    "Total Assets": investment.xpath(".//tfoot/tr[1]/td/text()").get(),
                    "Principal": investment.xpath(".//tfoot/tr[2]/td/text()").get(),
                    "Earnings": investment.xpath(".//tfoot/tr[3]/td/text()").get(),
                }
            )

        return investment_data

    def transaction_data(self):
        transaction_data = []

        for transaction in self.selector.xpath("//*[@id='txHistDiv']/table/tbody/tr"):
            transaction_data.append(
                {
                    "Processed": transaction.xpath(".//td[1]/text()").get(),
                    "Traded": transaction.xpath(".//td[2]/text()").get(),
                    "Type": transaction.xpath(".//td[3]/text()").get(),
                    "Units": transaction.xpath(".//td[4]/text()").get(),
                    "Price": transaction.xpath(".//td[5]/text()").get(),
                    "Value": transaction.xpath(".//td[6]/text()").get(),
                }
            )

        return transaction_data

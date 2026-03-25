"""
Save account data from https://www.schwab529.com/ into Google Sheets.
"""

import gspread


class Saver:
    """Save account data from https://www.schwab529.com/"""

    def __init__(self, token_filename):
        self.transaction_data = None
        self.investment_data = None
        self.balance_data = None
        self.beneficiary_data = None
        self.token_filename = token_filename

    def save_beneficiary(self, beneficiary_data):
        self.beneficiary_data = beneficiary_data

        gc = gspread.oauth("self.token_filename")
        sh = gc.open("Investment Account Scrapes")
        worksheet = sh.worksheet("529 Plan")
        worksheet.clear()
        worksheet.update([["Title", "Name", "Account"]], "B2:D2")

        for account in self.beneficiary_data:
            worksheet.update(
                [[account["Title"], account["Name"], account["Account"]]], "B3:D3"
            )

        print(f"Beneficiary data saved to ({worksheet.title}")

    def save_balance(self, balance_data):
        self.balance_data = balance_data

        gc = gspread.oauth("self.token_filename")
        sh = gc.open("Investment Account Scrapes")
        worksheet = sh.worksheet("529 Plan")
        worksheet.update([["Title", "Amount", "Date"]], "G2:I2")

        for account in self.balance_data:
            worksheet.update(
                [[account["Title"], account["Amount"], account["Date"]]], "G3:I3"
            )

        print(f"Balance data saved to ({worksheet.title}")

    def save_investment(self, investment_data):
        self.investment_data = investment_data

        gc = gspread.oauth("self.token_filename")
        sh = gc.open("Investment Account Scrapes")
        worksheet = sh.worksheet("529 Plan")
        worksheet.update(
            [
                [
                    "Fund Code",
                    "Fund",
                    "Units",
                    "Price",
                    "Value",
                    "Total Assets",
                    "Principal",
                    "Earnings",
                ]
            ],
            "B9:I9",
        )

        for account in self.investment_data:
            worksheet.update(
                [
                    [
                        account["Fund Code"],
                        account["Fund"],
                        account["Units"],
                        account["Price"],
                        account["Value"],
                        account["Total Assets"],
                        account["Principal"],
                        account["Earnings"],
                    ]
                ],
                "B10:I10",
            )

        print(f"Investment data saved to ({worksheet.title}")

    def save_transactions(self, transaction_data):
        self.transaction_data = transaction_data

        gc = gspread.oauth("self.token_filename")
        sh = gc.open("Investment Account Scrapes")
        worksheet = sh.worksheet("529 Plan")
        worksheet.update(
            [["Processed", "Traded", "Type", "Units", "Price", "Value"]], "C16:H16"
        )

        for account in self.transaction_data:
            worksheet.append_rows(
                [
                    [
                        account["Processed"],
                        account["Traded"],
                        account["Type"],
                        account["Units"],
                        account["Price"],
                        account["Value"],
                    ]
                ],
                table_range="C17:H17",
            )

        print(f"Transaction data saved to ({worksheet.title}")

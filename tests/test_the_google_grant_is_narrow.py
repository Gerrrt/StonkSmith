# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""What StonkSmith asks Google for, and that it does not quietly ask for more.

``gspread.oauth()`` defaults to ``spreadsheets`` **plus full ``drive``**, and
that default was what StonkSmith shipped: the refresh token cached in
``~/.config/gspread/authorized_user.json`` reached every file in the operator's
Drive rather than the one book this tool writes. SECURITY.md carried it as an
open item for months.

It was there for exactly one call. ``Client.open(title)`` is a Drive
``files.list`` search, and it was the only Drive request in the codebase --
everything past it (``worksheet``, ``add_worksheet``, ``del_worksheet``, every
read and write) goes to sheets.googleapis.com. So opening by id removes the
reason for the scope rather than merely trimming it.

Two things make this file necessary rather than nice.

The first is that a scope is invisible at runtime. Nothing fails, nothing logs,
and a token consented too widely works *better* than a narrow one -- so no test
that merely exercises the sheet path can tell the difference, and a future edit
adding ``drive`` back to make some lookup convenient would go unremarked. The
assertion therefore reads the ``scopes=`` argument itself. Asserting that
``oauth`` was called, which is the obvious version, passes on the old code.

The second is the fallback that is deliberately absent. ``open_spreadsheet``
refuses when no id is configured instead of searching by name, because searching
by name is what needs Drive: a fallback would put the whole risk back for anyone
who had not set the option, which is everyone on the day it ships.
"""

import unittest
from unittest.mock import MagicMock, patch

from config_isolation import UserConfigMixin
from gspread_isolation import STUB_SPREADSHEET_ID, GspreadConfigMixin
from stonksmith.helpers.sheets import (
    SHEETS_ONLY_SCOPES,
    SheetsUnavailable,
    open_spreadsheet,
)

#: The scope that would undo this. Spelled out rather than derived, so that a
#: change to SHEETS_ONLY_SCOPES cannot make the assertion agree with itself.
DRIVE = "https://www.googleapis.com/auth/drive"

SPREADSHEETS = "https://www.googleapis.com/auth/spreadsheets"


class RequestedScopeTests(GspreadConfigMixin, unittest.TestCase):
    """The argument, not the call."""

    def _scopes_asked_for(self) -> list[str]:
        client = MagicMock()

        with patch(
            "stonksmith.helpers.sheets.gspread.oauth", return_value=client
        ) as oauth:
            open_spreadsheet()

        self.assertEqual(oauth.call_count, 1)

        return list(oauth.call_args.kwargs["scopes"])

    def test_the_scope_is_asked_for_rather_than_defaulted(self) -> None:
        """The default is the wide pair, so omitting the argument is the bug.

        This is the assertion that fails on the original code: it called
        ``gspread.oauth()`` with nothing at all, and gspread filled in
        ``spreadsheets`` and ``drive``.
        """

        client = MagicMock()

        with patch(
            "stonksmith.helpers.sheets.gspread.oauth", return_value=client
        ) as oauth:
            open_spreadsheet()

        self.assertIn(
            "scopes",
            oauth.call_args.kwargs,
            "gspread.oauth() was called without scopes, so it defaulted to "
            "spreadsheets plus full drive",
        )

    def test_drive_is_not_among_them(self) -> None:
        asked: list[str] = self._scopes_asked_for()

        for scope in asked:
            with self.subTest(scope=scope):
                self.assertNotIn(
                    "drive",
                    scope,
                    "a Drive scope is back; the token now reaches files this "
                    "tool does not write",
                )

    def test_it_is_exactly_the_one_scope(self) -> None:
        # Not "drive is absent" alone: that passes on a request for every other
        # scope Google offers.
        self.assertEqual(self._scopes_asked_for(), [SPREADSHEETS])

    def test_the_constant_says_the_same_thing(self) -> None:
        self.assertNotIn(DRIVE, SHEETS_ONLY_SCOPES)
        self.assertEqual(tuple(SHEETS_ONLY_SCOPES), (SPREADSHEETS,))


class NoFallbackTests(UserConfigMixin, unittest.TestCase):
    """An unset id refuses, and refusing is the security control.

    Not GspreadConfigMixin: that supplies an id, which is the whole thing this
    class needs absent.
    """

    config_body = "[STONKSMITH]\nworkspace = default\n"

    def test_an_unset_id_refuses(self) -> None:
        with (
            patch("stonksmith.helpers.sheets.gspread.oauth") as oauth,
            self.assertRaises(SheetsUnavailable),
        ):
            open_spreadsheet()

        # It must refuse *before* authorizing. A refusal that happens after
        # gspread.oauth() has already run has consented a token on the way to
        # failing, which is the outcome this is meant to prevent.
        oauth.assert_not_called()

    def test_the_refusal_names_the_setting_to_fix(self) -> None:
        with (
            patch("stonksmith.helpers.sheets.gspread.oauth"),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_spreadsheet()

        message = str(caught.exception)
        self.assertIn("spreadsheet_id", message)
        self.assertIn("[SHEETS]", message)

    def test_it_does_not_fall_back_to_a_lookup_by_name(self) -> None:
        """The fallback that would have been the kind thing to do.

        Searching by title is a Drive call, so a fallback would re-request the
        scope for everyone who had not yet set the option -- that is, everyone,
        on the day this ships.
        """

        client = MagicMock()

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable),
        ):
            open_spreadsheet()

        client.open.assert_not_called()


class ConfiguredIdTests(GspreadConfigMixin, unittest.TestCase):
    def test_the_configured_id_is_what_gets_opened(self) -> None:
        client = MagicMock()

        with patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client):
            open_spreadsheet()

        client.open_by_key.assert_called_once_with(STUB_SPREADSHEET_ID)

    def test_the_book_is_never_looked_up_by_name(self) -> None:
        # The only Drive request there ever was.
        client = MagicMock()

        with patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client):
            open_spreadsheet()

        client.open.assert_not_called()
        client.list_spreadsheet_files.assert_not_called()


if __name__ == "__main__":
    unittest.main()

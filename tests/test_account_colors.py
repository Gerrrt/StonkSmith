"""Whose account a row is, at a glance, without colour carrying the fact.

A household's accounts are not a flat list. Three people and a joint pair own
twelve accounts between them, and reading "Mekenna Brokerage" against "Mekenna
IRA" against "Garrett Brokerage" is work the eye should not have to do at half
past six in the morning.

So each row carries a dot in the owner's colour. **The colour is redundant with
the name beside it, deliberately.** The name already says whose account it is, so
a reader who cannot distinguish the dots loses nothing -- a red-green dashboard is
unreadable to about one man in twelve, and this is a scanning aid rather than
information. Anything that made colour the only difference between two rows would
be the failure this arrangement exists to avoid.

Two rules do the work and both are pinned here.

**First match wins**, because the match is a substring: "Joint" and "Garrett" can
both be true of one account, so the order in the config is what decides. That is
why the palette travels as ordered pairs rather than a mapping -- a dict would
preserve the order in practice and document nothing about depending on it.

**An unknown colour is refused, not passed through.** The value reaches an HTML
class attribute and a config file is not a stylesheet.
"""

import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import owner_color
from stonksmith.etc.config import ACCOUNT_COLORS, get_account_colors

PALETTE: list[tuple[str, str]] = [
    ("Garrett", "green"),
    ("Mekenna", "pink"),
    ("Ezekiel", "blue"),
    ("Joint", "yellow"),
]


class OneLineCoversEveryAccountAPersonHolds(unittest.TestCase):
    def test_a_substring_matches_every_account_of_that_owner(self) -> None:
        # The reason the match is a substring rather than exact: one line has to
        # cover an IRA, a brokerage and a 401(k) without naming each.
        for name in ("Garrett 401(k)", "Garrett IRA", "Garrett Brokerage"):
            with self.subTest(name=name):
                self.assertEqual(owner_color(name=name, palette=PALETTE), "green")

    def test_case_does_not_have_to_match(self) -> None:
        self.assertEqual(owner_color(name="GARRETT IRA", palette=PALETTE), "green")

    def test_each_owner_gets_their_own(self) -> None:
        self.assertEqual(owner_color(name="Mekenna IRA", palette=PALETTE), "pink")
        self.assertEqual(owner_color(name="Ezekiel 529", palette=PALETTE), "blue")
        self.assertEqual(
            owner_color(name="Joint Brokerage (Ally)", palette=PALETTE), "yellow"
        )

    def test_an_unclaimed_account_gets_no_colour(self) -> None:
        # Empty rather than a default. A dot on an account with no owner declared
        # reads as an owner the reader has forgotten, not as a config line they
        # have not written.
        self.assertEqual(owner_color(name="Some Trust", palette=PALETTE), "")

    def test_an_empty_palette_colours_nothing(self) -> None:
        self.assertEqual(owner_color(name="Garrett IRA", palette=[]), "")


class TheFirstMatchWins(unittest.TestCase):
    def test_order_decides_when_two_lines_could_both_match(self) -> None:
        # "Garrett Joint Brokerage" contains both. Whichever line is written
        # first is the answer, and that is the whole reason the palette is an
        # ordered sequence rather than a mapping.
        joint_first = [("Joint", "yellow"), ("Garrett", "green")]
        garrett_first = [("Garrett", "green"), ("Joint", "yellow")]
        name = "Garrett Joint Brokerage"

        self.assertEqual(owner_color(name=name, palette=joint_first), "yellow")
        self.assertEqual(owner_color(name=name, palette=garrett_first), "green")


class TheConfigRefusesWhatIsNotAColour(UserConfigMixin, unittest.TestCase):
    config_body: str = (
        "[ACCOUNTS]\n"
        "colors =\n"
        "    Garrett = green\n"
        "    Mekenna = PINK\n"
        "    Ezekiel = chartreuse\n"
        "    Joint = red; } body { display:none\n"
        "    a line with no separator\n"
    )

    def setUp(self) -> None:
        super().setUp()
        self.pairs, self.refused = get_account_colors()

    def test_the_good_lines_survive_in_order(self) -> None:
        self.assertEqual(self.pairs, [("Garrett", "green"), ("Mekenna", "pink")])

    def test_a_colour_name_may_be_written_in_any_case(self) -> None:
        self.assertEqual(dict(self.pairs)["Mekenna"], "pink")

    def test_an_unknown_colour_is_refused_rather_than_passed_through(self) -> None:
        # "chartreuse" is a perfectly good CSS colour and not one of ours. It is
        # refused because the closed set is what makes interpolating the value
        # into a class attribute safe at all.
        self.assertIn("Ezekiel = chartreuse", self.refused)

    def test_a_line_that_would_inject_markup_is_refused(self) -> None:
        # The reason the set is closed rather than "any word". This value lands
        # in `class="dot {color}"`, and a config file is not a stylesheet.
        self.assertTrue(
            any("display:none" in line for line in self.refused),
            "a stylesheet fragment was accepted as a colour name",
        )

    def test_a_line_with_no_separator_is_refused(self) -> None:
        self.assertIn("a line with no separator", self.refused)

    def test_every_shipped_colour_is_in_the_closed_set(self) -> None:
        # The set and the CSS have to agree: a colour accepted here with no rule
        # in the stylesheet renders an invisible dot, which looks like the
        # feature silently not working.
        from stonksmith.etc.brief_html import STYLE

        for color in ACCOUNT_COLORS:
            with self.subTest(color=color):
                self.assertIn(f".dot.{color}", STYLE)


if __name__ == "__main__":
    unittest.main()

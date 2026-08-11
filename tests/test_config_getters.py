# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
The config getters, where text a human typed becomes a typed value.

This is the layer furthest upstream, and the one where a wrong answer is quiet.
A getter that falls back to its default when it should have parsed, or that reads
a typo as zero, does not raise and does not warn -- it hands the run a plausible
number, and the run completes and reports success on it. The same shape as the
falsy-filter bugs these tests were written alongside: "0" and "" are real answers
here, and only a test says so.

So each case below pins a value *and* the reason that value rather than the
obvious alternative. Where the alternative is a crash, the test says which input
produced it, because every one of them came from a config file somebody could
plausibly write.

Normalization of the SnapTrade labels is deliberately not tested here. It happens
at the comparison site, in modules.snaptrade_module.normalize_label, and
tests/test_snaptrade_module.py already covers case, spacing and the separator.
What is tested here is the split: this getter returns the labels as written.
"""

import inspect
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import etc.config
from etc.config import (
    DEFAULT_DFAS_PAY_URL,
    DEFAULT_HOST_INFO_COLORS,
    DEFAULT_TSP_PRICE_URL,
    get_audit_mode,
    get_host_info_colors,
    get_log_mode,
    get_reveal_chars,
    get_snaptrade_client_id,
    get_snaptrade_excluded_accounts,
    get_tsp_basd,
    get_tsp_contribution_day,
    get_tsp_contributions,
    get_tsp_fund,
    get_tsp_pay_table_url,
    get_tsp_price_url,
    get_tsp_rank,
    get_tsp_units,
    get_workspace,
    process_secret,
)


@contextmanager
def config_of(body: str) -> Iterator[None]:
    """
    Point etc.config at a throwaway config file holding exactly ``body``.

    A temp directory rather than a fixture file, because every case here needs
    different contents. Nothing touches $HOME, which
    tests/test_suite_does_not_touch_home.py checks for the suite as a whole.
    :param body: The config file contents to read
    """

    with tempfile.TemporaryDirectory() as home:
        path = Path(home) / "stonksmith.conf"
        path.write_text(data=body)

        with patch.object(etc.config, "user_cfg_path", path):
            # The merged config lives in a process global, so patching the path
            # without dropping the cache reads whatever an earlier test loaded --
            # and leaks this body to whatever runs next.
            etc.config.reset_config_cache()

            try:
                yield

            finally:
                etc.config.reset_config_cache()


def section(name: str, **options: str) -> str:
    """
    A one-section config body, for the many cases that need nothing else.
    :param name: The section name, which ConfigParser treats case-sensitively
    :param options: Option names and their raw values
    :return: The file contents
    :rtype: str
    """

    lines: list[str] = [f"[{name}]"]
    lines.extend(f"{option} = {value}" for option, value in options.items())

    return "\n".join(lines) + "\n"


class WorkspaceTests(unittest.TestCase):
    """The workspace names a directory, so a surprise here misplaces every db."""

    def test_a_configured_workspace_is_used(self) -> None:
        with config_of(section("STONKSMITH", workspace="mine")):
            self.assertEqual(get_workspace(), "mine")

    def test_an_unset_workspace_is_default(self) -> None:
        with config_of(section("STONKSMITH")):
            self.assertEqual(get_workspace(), "default")

    def test_surrounding_space_is_not_part_of_the_name(self) -> None:
        # ConfigParser strips values itself, so "  mine  " is "mine" and not a
        # directory with spaces in its name.
        with config_of(section("STONKSMITH", workspace="   mine   ")):
            self.assertEqual(get_workspace(), "mine")


class AuditModeTests(unittest.TestCase):
    """audit_mode decides whether a secret may be shown, so it must not guess."""

    def test_the_shipped_false_is_read_as_false(self) -> None:
        # The reason this getter uses getboolean and not get(): "False" is a
        # non-empty string, so a plain get() would make the shipped default
        # enable audit mode rather than disable it.
        with config_of(section("STONKSMITH", audit_mode="False")):
            self.assertFalse(get_audit_mode())

    def test_the_spellings_configparser_accepts_all_enable_it(self) -> None:
        for written in ("true", "True", "yes", "on", "1"):
            with (
                self.subTest(written=written),
                config_of(section("STONKSMITH", audit_mode=written)),
            ):
                self.assertTrue(get_audit_mode())

    def test_an_unreadable_value_reveals_nothing_rather_than_raising(self) -> None:
        # getboolean raises on anything it does not recognise. Left uncaught,
        # "audit_mode = maybe" took down every command that displays a
        # credential -- and a value that is not a boolean is certainly not
        # permission to print a secret.
        with config_of(section("STONKSMITH", audit_mode="maybe")):
            self.assertFalse(get_audit_mode())

    def test_an_absent_option_reveals_nothing(self) -> None:
        with config_of(section("STONKSMITH")):
            self.assertFalse(get_audit_mode())


class LogModeTests(unittest.TestCase):
    """log_mode reads the same way audit_mode does, including when it cannot."""

    def test_a_configured_value_is_read(self) -> None:
        with config_of(section("STONKSMITH", log_mode="True")):
            self.assertTrue(get_log_mode())

    def test_an_unreadable_value_is_off_rather_than_raising(self) -> None:
        with config_of(section("STONKSMITH", log_mode="sometimes")):
            self.assertFalse(get_log_mode())


class RevealCharsTests(unittest.TestCase):
    """How many characters of a secret may be shown, as a slice index."""

    def test_a_count_is_read_as_a_number(self) -> None:
        with config_of(section("STONKSMITH", reveal_chars_of_pwd="4")):
            self.assertEqual(get_reveal_chars(), 4)

    def test_the_shipped_false_reveals_nothing(self) -> None:
        # The shipped default is literally "reveal_chars_of_pwd = False", which
        # is not an int -- so for a stock install the exception path *is* the
        # default path, and it has to mean zero.
        with config_of(section("STONKSMITH", reveal_chars_of_pwd="False")):
            self.assertEqual(get_reveal_chars(), 0)

    def test_an_unreadable_count_reveals_nothing(self) -> None:
        with config_of(section("STONKSMITH", reveal_chars_of_pwd="four")):
            self.assertEqual(get_reveal_chars(), 0)

    def test_a_negative_count_reveals_nothing(self) -> None:
        # A negative is not a shorter prefix: text[:-3] returns all *but* the
        # last three characters, so -3 on a short secret shows nearly all of it.
        # The getter promises a non-negative count and now keeps that promise.
        with config_of(section("STONKSMITH", reveal_chars_of_pwd="-3")):
            self.assertEqual(get_reveal_chars(), 0)


class ProcessSecretTests(unittest.TestCase):
    """What the two settings above actually govern, end to end."""

    def test_audit_mode_off_masks_completely(self) -> None:
        body = section("STONKSMITH", audit_mode="False", reveal_chars_of_pwd="4")

        with config_of(body):
            self.assertEqual(process_secret(text="hunter2"), "*" * 8)

    def test_audit_mode_on_reveals_only_the_configured_prefix(self) -> None:
        body = section("STONKSMITH", audit_mode="True", reveal_chars_of_pwd="4")

        with config_of(body):
            masked = process_secret(text="hunter2")

        self.assertTrue(masked.startswith("hunt"))
        self.assertNotIn("hunter2", masked)

    def test_audit_mode_on_with_no_reveal_still_masks_completely(self) -> None:
        # Both settings have to agree before anything is shown; audit mode alone
        # is not a reveal.
        body = section("STONKSMITH", audit_mode="True", reveal_chars_of_pwd="0")

        with config_of(body):
            self.assertEqual(process_secret(text="hunter2"), "*" * 8)

    def test_the_mask_does_not_report_the_length(self) -> None:
        # A fixed eight stars, so a long password and a short one look alike.
        with config_of(section("STONKSMITH", audit_mode="False")):
            short = process_secret(text="ab")
            long = process_secret(text="a" * 64)

        self.assertEqual(short, long)


class HostInfoColorsTests(unittest.TestCase):
    """Four color names, read from a Python literal, falling back on anything else."""

    def test_the_shipped_tuple_literal_becomes_a_list(self) -> None:
        # The shipped value is a tuple while the built-in fallback is a list, so
        # the getter has to return the same type either way.
        written = '("green", "red", "yellow", "cyan")'

        with config_of(section("STONKSMITH", host_info_colors=written)):
            self.assertEqual(get_host_info_colors(), ["green", "red", "yellow", "cyan"])

    def test_a_list_literal_is_read_too(self) -> None:
        written = '["cyan", "magenta", "white", "blue"]'

        with config_of(section("STONKSMITH", host_info_colors=written)):
            self.assertEqual(
                get_host_info_colors(), ["cyan", "magenta", "white", "blue"]
            )

    def test_the_wrong_number_of_colors_falls_back(self) -> None:
        with config_of(section("STONKSMITH", host_info_colors='("green", "red")')):
            self.assertEqual(get_host_info_colors(), list(DEFAULT_HOST_INFO_COLORS))

    def test_text_that_is_not_a_literal_falls_back(self) -> None:
        # Bare "green, red, yellow, cyan" is what somebody writes who has not
        # noticed the quotes, and it is not a literal at all.
        with config_of(section("STONKSMITH", host_info_colors="green, red")):
            self.assertEqual(get_host_info_colors(), list(DEFAULT_HOST_INFO_COLORS))

    def test_a_literal_with_no_length_falls_back_rather_than_raising(self) -> None:
        # "host_info_colors = 5" parses perfectly well as a literal, so
        # literal_eval returns 5 and len() is what fails. A getter documented to
        # fall back on anything malformed must not raise TypeError instead.
        with config_of(section("STONKSMITH", host_info_colors="5")):
            self.assertEqual(get_host_info_colors(), list(DEFAULT_HOST_INFO_COLORS))

    def test_falling_back_is_reported_rather_than_silent(self) -> None:
        with (
            config_of(section("STONKSMITH", host_info_colors='("green", "red")')),
            patch.object(etc.config.stonksmith_logger, "error") as error,
        ):
            get_host_info_colors()

        self.assertTrue(error.called, "a config that was ignored must say so")


class SnapTradeClientIdTests(unittest.TestCase):
    """Half of a personal-tier identity, and not a secret."""

    def test_the_id_is_read_and_stripped(self) -> None:
        with config_of(section("SNAPTRADE", clientid="  PERS-ABC  ")):
            self.assertEqual(get_snaptrade_client_id(), "PERS-ABC")

    def test_either_spelling_of_the_option_resolves(self) -> None:
        # ConfigParser lower-cases option names on both write and lookup, so the
        # getter's "clientId" finds the shipped "clientid".
        for written in ("clientid", "clientId", "CLIENTID"):
            with (
                self.subTest(written=written),
                config_of(section("SNAPTRADE", **{written: "PERS-ABC"})),
            ):
                self.assertEqual(get_snaptrade_client_id(), "PERS-ABC")

    def test_an_unset_id_is_empty(self) -> None:
        with config_of(section("SNAPTRADE")):
            self.assertEqual(get_snaptrade_client_id(), "")


class SnapTradeExcludedAccountsTests(unittest.TestCase):
    """One label per line. An exclusion that stops matching restores a double count."""

    def test_indented_lines_become_one_label_each(self) -> None:
        body = (
            "[SNAPTRADE]\n"
            "exclude_accounts =\n"
            "    Schwab / Ezekiel 529 Plan\n"
            "    Fidelity / Individual\n"
        )

        with config_of(body):
            self.assertEqual(
                get_snaptrade_excluded_accounts(),
                ["Schwab / Ezekiel 529 Plan", "Fidelity / Individual"],
            )

    def test_the_indentation_is_not_part_of_the_label(self) -> None:
        # The indent is what makes it a continuation line in INI, so it is
        # syntax rather than content -- but it survives into the value, and a
        # label carrying four leading spaces matches nothing.
        body = "[SNAPTRADE]\nexclude_accounts =\n        Schwab / Ezekiel 529 Plan   \n"

        with config_of(body):
            self.assertEqual(
                get_snaptrade_excluded_accounts(), ["Schwab / Ezekiel 529 Plan"]
            )

    def test_blank_lines_between_labels_are_dropped(self) -> None:
        body = (
            "[SNAPTRADE]\n"
            "exclude_accounts =\n"
            "    Schwab / Ezekiel 529 Plan\n"
            "\n"
            "    Fidelity / Individual\n"
        )

        with config_of(body):
            self.assertEqual(len(get_snaptrade_excluded_accounts()), 2)

    def test_an_empty_setting_excludes_nothing_rather_than_one_blank(self) -> None:
        # [""] would be a label that matches nothing but is still a label, and
        # the count of exclusions is reported. Empty means empty.
        with config_of(section("SNAPTRADE", exclude_accounts="")):
            self.assertEqual(get_snaptrade_excluded_accounts(), [])

    def test_a_single_label_on_the_option_line_works(self) -> None:
        # Documented as one per line, indented -- but writing the only one
        # inline is the obvious shorthand and has to mean the same thing.
        written = "Schwab / Ezekiel 529 Plan"

        with config_of(section("SNAPTRADE", exclude_accounts=written)):
            self.assertEqual(get_snaptrade_excluded_accounts(), [written])

    def test_the_labels_are_returned_as_written(self) -> None:
        # Normalization belongs to the comparison, in
        # modules.snaptrade_module.normalize_label, so that both sides get the
        # same treatment. This getter must not case-fold on its own: doing it
        # here would normalize the config half only.
        written = "SCHWAB/Ezekiel 529 Plan"

        with config_of(section("SNAPTRADE", exclude_accounts=written)):
            self.assertEqual(get_snaptrade_excluded_accounts(), [written])


class TspUnitsTests(unittest.TestCase):
    """Units and the date they were true, which always travel together."""

    def test_units_and_their_date_are_both_returned(self) -> None:
        body = section("TSP", units="302.116", units_as_of="2026-06-30")

        with config_of(body):
            self.assertEqual(get_tsp_units(), (302.116, "2026-06-30"))

    def test_unset_units_are_none(self) -> None:
        with config_of(section("TSP", units="", units_as_of="")):
            self.assertEqual(get_tsp_units(), (None, ""))

    def test_zero_units_are_zero_and_not_unset(self) -> None:
        # A closed account really does hold nothing, and "0" is the honest way
        # to say so. Reading it as None would call a real answer missing.
        with config_of(section("TSP", units="0", units_as_of="2026-06-30")):
            self.assertEqual(get_tsp_units(), (0.0, "2026-06-30"))

    def test_a_typo_is_unset_rather_than_zero(self) -> None:
        # The failure this getter exists to avoid: 0.0 would value the whole
        # account at nothing and look like a real answer, where None makes the
        # broker say it has no unit count.
        with config_of(section("TSP", units="12o4", units_as_of="2026-06-30")):
            units, as_of = get_tsp_units()

        self.assertIsNone(units)
        self.assertEqual(as_of, "2026-06-30", "the date survives an unreadable count")


class TspContributionsTests(unittest.TestCase):
    """Two percentages of basic pay, each readable or not on its own."""

    def test_both_percentages_are_read(self) -> None:
        body = section("TSP", member_contribution="5", agency_contribution="5")

        with config_of(body):
            self.assertEqual(get_tsp_contributions(), (5.0, 5.0))

    def test_a_percent_sign_may_be_written(self) -> None:
        # The getter strips a trailing "%" precisely because a member writing a
        # percentage writes one. That was unreachable while the config was read
        # with interpolation on: ConfigParser took the "%" for the start of a
        # "%(name)s" reference and raised before the getter saw the value.
        body = section("TSP", member_contribution="5%", agency_contribution="1.5%")

        with config_of(body):
            self.assertEqual(get_tsp_contributions(), (5.0, 1.5))

    def test_zero_is_a_percentage_and_not_unset(self) -> None:
        # An agency that matches nothing is a real arrangement to describe.
        body = section("TSP", member_contribution="0", agency_contribution="0")

        with config_of(body):
            self.assertEqual(get_tsp_contributions(), (0.0, 0.0))

    def test_unset_percentages_are_none(self) -> None:
        with config_of(section("TSP", member_contribution="")):
            self.assertEqual(get_tsp_contributions(), (None, None))

    def test_an_unreadable_percentage_does_not_take_the_other_with_it(self) -> None:
        body = section("TSP", member_contribution="five", agency_contribution="5")

        with config_of(body):
            self.assertEqual(get_tsp_contributions(), (None, 5.0))

    def test_a_typo_is_unset_rather_than_zero(self) -> None:
        # Same rule as units: 0.0 would say "contributed nothing", which values
        # the accrual at zero and reads as a real answer.
        with config_of(section("TSP", member_contribution="5.0.0")):
            member, _ = get_tsp_contributions()

        self.assertIsNone(member)

    def test_the_getter_does_not_require_all_four_keys(self) -> None:
        # The README asks for all four or none, but that is the broker's rule to
        # report on: a getter that blanked a configured percentage because rank
        # was missing would hide what the file actually says.
        with config_of(section("TSP", member_contribution="5")):
            self.assertEqual(get_tsp_contributions(), (5.0, None))
            self.assertEqual(get_tsp_rank(), "")


class TspContributionDayTests(unittest.TestCase):
    """Which day the money lands, since that is the day whose price it buys at."""

    def test_a_day_is_read_as_a_number(self) -> None:
        with config_of(section("TSP", contribution_day="15")):
            self.assertEqual(get_tsp_contribution_day(), 15)

    def test_the_ends_of_the_range_are_accepted(self) -> None:
        for day in ("1", "31"):
            with (
                self.subTest(day=day),
                config_of(section("TSP", contribution_day=day)),
            ):
                self.assertEqual(get_tsp_contribution_day(), int(day))

    def test_thirty_one_is_kept_rather_than_refused(self) -> None:
        # A day past the end of a short month is clamped by the caller, so 31
        # stays usable in February instead of being rejected here.
        with config_of(section("TSP", contribution_day="31")):
            self.assertIsNotNone(get_tsp_contribution_day())

    def test_unset_means_the_last_day_of_the_month(self) -> None:
        # Expressed as None: the getter does not know the month, so naming the
        # last day is the accrual's job.
        with config_of(section("TSP", contribution_day="")):
            self.assertIsNone(get_tsp_contribution_day())

    def test_a_day_outside_the_range_is_unset(self) -> None:
        for day in ("0", "32", "-1"):
            with (
                self.subTest(day=day),
                config_of(section("TSP", contribution_day=day)),
            ):
                self.assertIsNone(get_tsp_contribution_day())

    def test_an_unreadable_day_is_unset(self) -> None:
        with config_of(section("TSP", contribution_day="last")):
            self.assertIsNone(get_tsp_contribution_day())


class TspUrlTests(unittest.TestCase):
    """Both published URLs: blank counts as unset, not as "download nothing"."""

    def test_a_configured_price_url_wins(self) -> None:
        with config_of(section("TSP", price_url="https://example.invalid/moved.csv")):
            self.assertEqual(get_tsp_price_url(), "https://example.invalid/moved.csv")

    def test_a_blank_price_url_falls_back_to_the_published_one(self) -> None:
        # Every install predating the default carries a literal "price_url ="
        # line, and get_config() backfills only *absent* options -- so blank has
        # to be what triggers the fallback, not absence.
        with config_of(section("TSP", price_url="")):
            self.assertEqual(get_tsp_price_url(), DEFAULT_TSP_PRICE_URL)

    def test_a_configured_pay_table_url_wins(self) -> None:
        with config_of(section("TSP", pay_table_url="https://example.invalid/pay/")):
            self.assertEqual(get_tsp_pay_table_url(), "https://example.invalid/pay/")

    def test_a_blank_pay_table_url_falls_back_to_the_published_one(self) -> None:
        with config_of(section("TSP", pay_table_url="")):
            self.assertEqual(get_tsp_pay_table_url(), DEFAULT_DFAS_PAY_URL)


class TspTextSettingsTests(unittest.TestCase):
    """fund, rank and basd, which are handed on as written rather than validated."""

    def test_each_is_read_and_stripped(self) -> None:
        body = section("TSP", fund="  L 2060  ", rank="  E-7  ", basd=" 2016-03-14 ")

        with config_of(body):
            self.assertEqual(get_tsp_fund(), "L 2060")
            self.assertEqual(get_tsp_rank(), "E-7")
            self.assertEqual(get_tsp_basd(), "2016-03-14")

    def test_each_is_empty_when_unset(self) -> None:
        with config_of(section("TSP", fund="", rank="", basd="")):
            self.assertEqual(get_tsp_fund(), "")
            self.assertEqual(get_tsp_rank(), "")
            self.assertEqual(get_tsp_basd(), "")

    def test_an_unusable_rank_is_returned_rather_than_blanked(self) -> None:
        # helpers.dfas.normalize_grade owns what a grade may look like. A getter
        # that quietly returned "" for "Sergeant" would leave the run reporting
        # that no rank was configured when one plainly was.
        with config_of(section("TSP", rank="Sergeant")):
            self.assertEqual(get_tsp_rank(), "Sergeant")

    def test_a_basd_stays_a_string(self) -> None:
        # Kept unparsed so a caller can say "Unreadable basd 'Jan 5 2019';
        # expected YYYY-MM-DD". None could not tell a typo from an empty line.
        with config_of(section("TSP", basd="Jan 5 2019")):
            self.assertEqual(get_tsp_basd(), "Jan 5 2019")


class ShippedDefaultsTests(unittest.TestCase):
    """Whatever the getters promise, the config the tool ships has to satisfy it."""

    @staticmethod
    def _getters() -> list[tuple[str, Callable[[], object]]]:
        """Every public getter that takes no arguments, found rather than listed."""

        found: list[tuple[str, Callable[[], object]]] = []

        for name, function in inspect.getmembers(etc.config, inspect.isfunction):
            if not name.startswith("get_") or name == "get_config":
                continue

            if inspect.signature(function).parameters:
                continue

            found.append((name, function))

        return found

    def test_every_getter_reads_the_shipped_defaults_without_raising(self) -> None:
        # The cheapest guard against a default nobody can read: three of the
        # four bugs these tests were written against were a getter raising on a
        # value rather than returning a wrong one, and a shipped default that
        # trips one would break every install on first run.
        body = etc.config.default_cfg_path.read_text()

        for name, getter in self._getters():
            with self.subTest(getter=name), config_of(body):
                getter()

    def test_the_sweep_actually_found_the_getters(self) -> None:
        # Guards the test above against silently passing on an empty list if the
        # naming convention ever changes.
        names = [name for name, _ in self._getters()]

        self.assertIn("get_tsp_units", names)
        self.assertGreaterEqual(len(names), 14, names)

    def test_the_defaults_are_the_published_urls(self) -> None:
        self.assertEqual(
            DEFAULT_TSP_PRICE_URL, "https://www.tsp.gov/data/fund-price-history.csv"
        )
        self.assertTrue(DEFAULT_DFAS_PAY_URL.startswith("https://www.dfas.mil/"))


class ConfigCacheTests(unittest.TestCase):
    """The merge is cached in a process global, which is what tests fight."""

    def test_a_rewritten_file_is_picked_up_after_a_reset(self) -> None:
        with config_of(section("STONKSMITH", workspace="first")):
            self.assertEqual(get_workspace(), "first")

        with config_of(section("STONKSMITH", workspace="second")):
            self.assertEqual(get_workspace(), "second")

    def test_reading_a_missing_file_creates_nothing(self) -> None:
        # setup_tool() owns creating the config, so a missing file means the
        # tool has not been set up yet and reading must not be what creates it.
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "stonksmith.conf"

            with patch.object(etc.config, "user_cfg_path", path):
                etc.config.reset_config_cache()

                try:
                    self.assertEqual(get_workspace(), "default")

                finally:
                    etc.config.reset_config_cache()

            self.assertFalse(path.exists(), "reading config must not create the file")


if __name__ == "__main__":
    unittest.main()

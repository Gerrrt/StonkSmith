"""The mark from the README, on the page, without breaking either promise.

Two constraints meet here and pull opposite ways.

**The brief is one self-contained file.** It has to render from a `file://` URL
with no server and nothing beside it -- that is what lets it be opened at 06:30,
moved, or mailed. An `<img src="logo.svg">` would be a broken icon the moment
the page left the directory it was written in, so the mark is inlined.

**There is one logo, not two.** Embedding the markup as a string constant would
put a second copy in the renderer, and a repository that draws its mark from two
places is one where they diverge and nobody notices until they are seen side by
side. So the file lives in the package -- shipped by the same rule that ships
`stonksmith.conf` -- and both the README and this page point at it.

The accessibility handling is the part worth pinning. The file names itself:
`role="img"`, an `aria-label` and a `<title>`, all correct on GitHub where the
mark stands alone. Beside the word "StonkSmith" they are wrong -- a screen reader
announces the name twice and reads the heading as "StonkSmith StonkSmith morning
brief" -- so the inlined copy is stripped to decoration.
"""

import datetime as dt
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief
from stonksmith.etc.brief_html import STYLE, logo, render
from stonksmith.etc.paths import etc_path
from stonksmith.etc.portfolio import Portfolio

NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


class TheMarkIsShippedOnceAndReadFromThere(unittest.TestCase):
    def test_the_logo_travels_with_the_package(self) -> None:
        # Beside stonksmith.conf, and shipped by the same rule: the wheel
        # declares `packages = ["src/stonksmith"]`, which carries the directory
        # rather than only its .py files. A logo left in docs/ would be absent
        # from every installed copy.
        self.assertTrue((etc_path / "logo.svg").is_file())

    def test_the_readme_points_at_that_same_file(self) -> None:
        # The whole argument for moving it. Two copies would drift, and the
        # drift is invisible until somebody sees both at once.
        readme: str = (Path(__file__).resolve().parent.parent / "README.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("src/stonksmith/etc/logo.svg", readme)


class TheInlinedCopyIsDecoration(unittest.TestCase):
    def setUp(self) -> None:
        self.mark: str = logo()

    def test_it_is_hidden_from_the_accessibility_tree(self) -> None:
        self.assertIn('aria-hidden="true"', self.mark)

    def test_it_no_longer_names_itself(self) -> None:
        # All three are right in the file and wrong here, next to the wordmark.
        self.assertNotIn("<title>", self.mark)
        self.assertNotIn("aria-label", self.mark)
        self.assertNotIn('role="img"', self.mark)

    def test_the_file_still_names_itself_for_github(self) -> None:
        # The stripping is a property of the inlined copy, not of the asset. On
        # GitHub the mark stands alone and has to carry its own name.
        source: str = (etc_path / "logo.svg").read_text(encoding="utf-8")

        self.assertIn("<title>StonkSmith</title>", source)
        self.assertIn('aria-label="StonkSmith"', source)

    def test_the_page_sizes_it_rather_than_the_file(self) -> None:
        # The file carries 128x128 so it renders standalone. Left in, those win
        # against the stylesheet and the badge arrives four times too big.
        #
        # Checked on the <svg> tag alone. The panel behind the drawing is also
        # 128 wide, in viewBox units, and has to stay -- asserting against the
        # whole string would demand the mark be dismantled to pass.
        root = re.match(pattern=r"<svg[^>]*>", string=self.mark)

        assert root is not None
        self.assertNotIn('width="128"', root.group(0))
        self.assertNotIn('height="128"', root.group(0))
        self.assertIn('viewBox="0 0 128 128"', root.group(0))
        self.assertIn(".mark {", STYLE)

    def test_the_drawing_survives_the_stripping(self) -> None:
        # The point of all the removal is that only the metadata goes. A mark
        # stripped to nothing would satisfy every assertion above.
        self.assertIn("<svg", self.mark)
        self.assertIn("<polyline", self.mark)
        self.assertGreater(self.mark.count("<path"), 4)


class ThePageStaysSelfContained(UserConfigMixin, unittest.TestCase):
    def _page(self) -> str:
        return render(
            brief=build_brief(
                portfolio=Portfolio(), baseline=None, today=dt.date(2026, 8, 14)
            ),
            now=NOW,
        )

    def test_the_mark_is_in_the_markup_not_linked(self) -> None:
        page: str = self._page()

        self.assertIn('<svg class="mark"', page)
        self.assertNotIn("logo.svg", page)

    def test_the_heading_reads_once(self) -> None:
        # What the stripping is for, checked at the level a reader meets it:
        # the text of the heading, with the drawing taken out.
        page: str = self._page()
        head = re.search(pattern=r"<h1>(.*?)</h1>", string=page, flags=re.S)

        assert head is not None
        words: str = re.sub(
            pattern=r"<svg.*?</svg>", repl="", string=head.group(1), flags=re.S
        )

        self.assertEqual(words.strip(), "StonkSmith · morning brief")

    def test_an_undecodable_mark_costs_the_badge_and_not_the_page(self) -> None:
        # UnicodeDecodeError is a ValueError, not an OSError, so a logo replaced
        # by a PNG that kept the name -- or truncated mid-write -- escaped the
        # handler and took the whole brief down for a decorative asset.
        with tempfile.TemporaryDirectory() as where:
            (Path(where) / "logo.svg").write_bytes(b"\xff\xfe<svg/>")

            with patch("stonksmith.etc.paths.etc_path", Path(where)):
                self.assertEqual(logo(), "")

                self.assertIn("StonkSmith · morning brief", self._page())

    def test_a_missing_mark_costs_the_badge_and_not_the_page(self) -> None:
        # The brief renders every morning unattended. A logo that could not be
        # read is a cosmetic loss, and taking the page down over it would trade
        # the whole feature for an icon.
        with patch(
            "stonksmith.etc.paths.etc_path", Path("/nonexistent-stonksmith-etc")
        ):
            self.assertEqual(logo(), "")

            page: str = self._page()

        self.assertIn("StonkSmith · morning brief", page)
        self.assertNotIn('<svg class="mark"', page)


if __name__ == "__main__":
    unittest.main()

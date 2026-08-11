"""Every link between the README and docs/ has to resolve.

The README used to carry the whole manual -- 1,428 lines, of which the Usage
section was 1,184. Splitting it into docs/brokers.md, docs/database.md and
docs/sheet.md moved the detail somewhere it can be read, and it moved every
cross-reference with it.

That is the risk this file exists for. Three records in docs/ name their summary
by section title -- live-verification.md cites the paragraph under *Project
Structure*, ally-transactions.md cites the end of *What an Ally run writes down*,
scheduling.md cites *When two brokers can reach the same account*. Those pointers
are load-bearing: each record says "change a row here and change it there in the
same pass", and a pointer into a section that no longer exists silently retires
that instruction. Nothing would report it. A link into a moved heading renders as
ordinary text and lands the reader at the top of a file, which looks like a
document that simply did not have the answer.

tests/test_live_verification_tally.py made the same trade one file over, for the
same reason: its docstring notes that the instruction to update the count "was
the only thing holding the two together", and that "an instruction is not a
mechanism". A pointer is not a mechanism either.

So every relative markdown link in the README and in docs/ is resolved here --
the file it names must exist, and any #fragment must match a heading in that
file. What this cannot check is whether the prose on the other end still says the
right thing; live-verification.md is explicit that this half stays human.
"""

import re
import unittest
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The files whose links are checked. The README plus every record and reference
#: chapter beside it -- these are the ones that cite each other.
SOURCES: tuple[Path, ...] = (REPO / "README.md", *sorted((REPO / "docs").glob("*.md")))

#: An inline markdown link, `[text](target)`. Reference-style links and bare URLs
#: are not matched: neither is used in these files, and a pattern that guessed at
#: them would report on prose rather than on links.
LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")

#: An `src=` or `href=` on raw HTML, which markdown permits and the README's
#: header block is built out of. Its logo `<img>` and its whole table of contents
#: are HTML, so a check that read only markdown links would leave the most
#: visible reference on the page -- the mark itself -- unverified.
HTML_REF = re.compile(r"(?:src|href)=\"(?P<target>[^\"]+)\"")

#: A setext-free ATX heading, which is the only kind these files use.
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)

#: An explicit HTML anchor, `<a id="readme-top">`. A link may name one of these
#: as legitimately as it names a heading, and the back-to-top link at the foot of
#: every section names exactly this one.
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"(?P<anchor>[^\"]+)\"")

#: Fenced code blocks. Headings and links are matched after these are removed, so
#: a shell comment at the start of a line is never mistaken for a heading and an
#: illustrated path is never mistaken for a link.
#:
#: The leading whitespace is not decoration. A fence indented under a list item
#: is still a fence -- docs/live-verification.md has one, three spaces in, under
#: step 5 of *The sheet* -- and anchoring at column 0 left its contents to be
#: scanned as prose. That block happens to hold neither a link nor a heading, so
#: nothing was misread; the next one to hold an example path would have been
#: reported as a broken link that no reader could see.
FENCE = re.compile(r"^[ \t]*```.*?^[ \t]*```", re.MULTILINE | re.DOTALL)

#: Characters GitHub drops when it slugs a heading. Emoji shortcodes are the case
#: worth naming: `## :wrench: Features` anchors as `wrench-features`, so a slugger
#: that kept the colons would fail every heading in the README and read as a
#: broken link rather than as a broken test.
PUNCTUATION = re.compile(r"[^\w\- ]", re.UNICODE)


def slug(title: str) -> str:
    """Render a heading the way GitHub renders it into an anchor.

    Lowercase, drop punctuation, collapse whitespace to single hyphens. Inline
    markdown is stripped first, since `## The sheet is *output*` anchors on the
    words rather than on the asterisks.

    :param title: The heading text, without its leading hashes
    :return: The fragment that links to it
    :rtype: str
    """

    text: str = re.sub(pattern=r"[`*_]", repl="", string=title)
    text = PUNCTUATION.sub(repl="", string=text.lower())

    return "-".join(text.split())


@cache
def anchors_of(path: Path) -> frozenset[str]:
    """Every fragment a link into this file may name.

    Cached on the path. Fragments cluster -- the README alone points into
    docs/brokers.md six times -- and the uncached version re-read and re-slugged
    the whole file for each one.

    :param path: The markdown file to read
    :return: The slugs of its headings, plus any explicit HTML anchor
    :rtype: frozenset[str]
    """

    body: str = FENCE.sub(repl="", string=path.read_text(encoding="utf-8"))

    return frozenset(
        [slug(title=match.group("title")) for match in HEADING.finditer(body)]
        + [match.group("anchor") for match in HTML_ANCHOR.finditer(body)]
    )


def references_of(path: Path) -> list[str]:
    """Every link target in a file, markdown and HTML alike.

    :param path: The markdown file to read
    :return: The raw targets, in the order they appear
    :rtype: list[str]
    """

    body: str = FENCE.sub(repl="", string=path.read_text(encoding="utf-8"))

    return [match.group("target") for match in LINK.finditer(body)] + [
        match.group("target") for match in HTML_REF.finditer(body)
    ]


class DocCrossReferences(unittest.TestCase):
    """Relative links between the README and docs/ resolve, fragments included."""

    def test_every_relative_link_names_a_file_that_exists(self) -> None:
        for source in SOURCES:
            for target in references_of(path=source):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue

                path: Path = (source.parent / target.split("#", 1)[0]).resolve()

                with self.subTest(source=source.name, target=target):
                    # Inside the repository, not merely somewhere on the disk.
                    # resolve() follows `../` as far as it is told to, so a link
                    # that climbed out of the tree would be checked against
                    # whatever happens to sit at that path on this machine --
                    # which passes here and is a broken link for every reader who
                    # is not running the suite.
                    self.assertTrue(
                        path.is_relative_to(REPO),
                        f"{source.name} links to {target}, which resolves outside "
                        f"the repository to {path}.",
                    )
                    self.assertTrue(
                        path.is_file(),
                        f"{source.name} links to {target}, which is not a file. "
                        "A link that moved with its section has to move here too.",
                    )

    def test_every_fragment_names_a_heading_that_exists(self) -> None:
        for source in SOURCES:
            for target in references_of(path=source):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue

                if "#" not in target:
                    continue

                relative, fragment = target.split("#", 1)

                if not fragment:
                    continue

                path: Path = (
                    source if not relative else (source.parent / relative).resolve()
                )

                if not path.is_relative_to(REPO) or not path.is_file():
                    # Reported by the test above; not worth failing twice.
                    continue

                with self.subTest(source=source.name, target=target):
                    self.assertIn(
                        fragment,
                        anchors_of(path=path),
                        f"{source.name} links to {target}, but {path.name} has no "
                        "heading with that anchor. A renamed or moved heading "
                        "leaves the link rendering as text.",
                    )

    def test_a_fence_is_stripped_whether_or_not_it_is_indented(self) -> None:
        # The stripper is what keeps an illustration from being read as a claim,
        # so its own blind spot is worth pinning rather than leaving to the
        # documents that happen to exist today. A fence indented under a list
        # item is the case that was missed.
        document: str = (
            "# Title\n\n"
            "- A step:\n\n"
            "   ```bash\n"
            "   cat [notes](does-not-exist.md)\n"
            "   ```\n\n"
            "```bash\n"
            "cat [more](also-missing.md)\n"
            "```\n"
        )

        stripped: str = FENCE.sub(repl="", string=document)

        self.assertEqual(
            [],
            [match.group("target") for match in LINK.finditer(stripped)],
            "A path inside a code block is an illustration, not a link.",
        )

    def test_the_split_chapters_are_reachable_from_the_readme(self) -> None:
        # The three files the manual moved into. A README that stopped linking
        # one of them would leave several hundred lines of documentation in the
        # repository and unreachable from its front page, which is the failure
        # the split was meant to avoid rather than to cause.
        readme: str = (REPO / "README.md").read_text(encoding="utf-8")

        for chapter in ("brokers", "database", "sheet"):
            with self.subTest(chapter=chapter):
                self.assertIn(
                    f"docs/{chapter}.md",
                    readme,
                    f"The README does not link docs/{chapter}.md.",
                )


if __name__ == "__main__":
    unittest.main()

# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""src/ says :param, not Args:. The two styles do not mix in one tree.

Six files had drifted to Google style -- 37 ``Args:`` blocks and 31 ``Returns:``
-- against 483 ``:param`` lines everywhere else. Neither form is better; having
both means every reader works out which file they are in before they can read the
docstring, and every writer copies whichever example they happened to open.

Ruff cannot say this. ``D`` is deliberately unselected -- 1500-odd findings whose
payoff is presentational, per the comment in pyproject.toml -- and its ``DOC``
rules, which do parse these sections, are preview-gated as well as unselected.
The one setting that sounds like it would help, ``[tool.ruff.lint.pydocstyle]
convention``, is inert with ``D`` off: running ruff with and without it produces
identical output. It would also be mislabelled, since its three values are
``pep257``, ``google`` and ``numpy``, and the style here is Sphinx/reST, which is
none of them.

So the rule is written down in CONTRIBUTING.md, and this is what makes it hold --
the same arrangement as tests/test_doc_cross_references.py, which exists because
"keep the links current" is not a mechanism either.

Deliberately narrow. It asks only that no docstring carries a Google section
header, not that every argument has a ``:param``: the latter would demand 483
lines of churn and would fight the many one-line docstrings that are complete as
they are.
"""

import ast
import re
import unittest
from pathlib import Path

from package_tree import PACKAGE, REPO

#: The section headers Google-style docstrings use. Matched on a line of its own,
#: so prose ending in a colon is not a false positive -- and checked against the
#: whole of src/, where there are none today.
GOOGLE_SECTION = re.compile(
    r"^\s*(Args|Arguments|Returns|Yields|Raises|Attributes|Example|Examples|Note|Notes):\s*$"
)

#: A Sphinx field, capturing its indent so a continuation line can be compared
#: against it.
FIELD = re.compile(r"^(\s*):(?:param|return|rtype|raises|type)\b")


def docstrings() -> list[tuple[Path, int, str]]:
    """
    Every docstring in the shipped package, with where it is.
    :return: (path, line number, docstring) for each
    """

    found: list[tuple[Path, int, str]] = []

    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(source=path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(
                node,
                ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            ):
                continue

            # clean=False: the raw text, because a rule about layout cannot be
            # asked of a version with the layout normalised out of it.
            text: str | None = ast.get_docstring(node=node, clean=False)

            if text:
                line: int = getattr(node.body[0], "lineno", 1)
                found.append((path, line, text))

    return found


class DocstringStyleTests(unittest.TestCase):
    def test_no_docstring_uses_a_google_section_header(self) -> None:
        offenders: list[str] = [
            f"{path.relative_to(REPO)}:{line}: {stripped}"
            for path, line, text in docstrings()
            for stripped in (
                candidate.strip()
                for candidate in text.splitlines()
                if GOOGLE_SECTION.match(candidate)
            )
        ]

        self.assertEqual(
            offenders,
            [],
            "these use a Google section header; this package writes Sphinx "
            "fields (:param, :return, :rtype, :raises) -- see CONTRIBUTING.md:\n"
            + "\n".join(offenders),
        )

    def test_a_wrapped_field_indents_its_continuation(self) -> None:
        # `:param x: ...` continued on the next line indents that line under the
        # field, the way brokerloader.py and helpers/schwab529plan.py do. A
        # continuation at the same column reads as a new paragraph and hides
        # where one field ends and the next begins.
        #
        # A house-style rule, not a reST one. These docstrings are not valid reST
        # field lists in the first place -- the syntax wants a blank line before
        # the list and this project's does not have one, in all 407 of them -- so
        # nothing here is claiming Sphinx would render them.
        offenders: list[str] = []

        for path, line, text in docstrings():
            body: list[str] = text.splitlines()
            field_indent: int | None = None

            for offset, raw in enumerate(body):
                match = FIELD.match(raw)

                if match:
                    field_indent = len(match.group(1))
                    continue

                if field_indent is None or not raw.strip():
                    field_indent = None
                    continue

                if len(raw) - len(raw.lstrip()) <= field_indent:
                    offenders.append(
                        f"{path.relative_to(REPO)}:{line + offset}: {raw.strip()[:60]}"
                    )
                    field_indent = None

        self.assertEqual(
            offenders,
            [],
            "these continue a :param/:return onto a line that is not indented "
            "under it:\n" + "\n".join(offenders),
        )

    def test_the_package_has_docstrings_to_check(self) -> None:
        # Without this the assertion above passes on a walk that found nothing,
        # which is the failure mode tests/package_tree.py exists to describe: a
        # path anchor that stops resolving takes the assertions with it and says
        # nothing while doing so.
        self.assertGreater(len(docstrings()), 400)

    def test_the_pattern_matches_a_section_and_not_prose(self) -> None:
        # A unit test on the regex, because a pattern that silently stopped
        # matching would leave the test above asserting nothing.
        for header in ("    Args:", "Returns:", "        Raises:"):
            with self.subTest(line=header):
                self.assertTrue(GOOGLE_SECTION.match(header))

        for prose in (
            "    Note that the caller owns this:",
            "    :param broker: the one to switch to",
            "    Args: inline, not a section",
            "    See docs/brokers.md for what a broker is",
        ):
            with self.subTest(line=prose):
                self.assertIsNone(GOOGLE_SECTION.match(prose))


if __name__ == "__main__":
    unittest.main()

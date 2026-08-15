"""The operator's own numbers do not belong in a public repository.

This project explains itself with worked examples, and for a long time those
examples used the figures from the workspace they were written against. Between
them they published a household's holdings -- a 529's principal, a 401k's cost, a
TSP unit count and statement, brokerage balances, a margin loan, a portfolio
total -- alongside family names, an employer and an account number.

They were replaced with representative equivalents. This is what stops them
coming back, because the way they came back would be entirely reasonable: a
future run against a live workspace, pasted into a docstring to show what the
output looks like, is exactly how they got here the first time.

**The forbidden values are stored as hashes**, which is not decoration. A guard
listing the literals would republish, in the file whose whole purpose is to keep
them out, everything the scrub removed. So this hashes what it finds and
compares digests: it can say *that* a scrubbed value is present without the
comparison itself being a copy of one.

The cost of that is a failure message which cannot quote what it matched. It
names the file, the line and the token, which is enough -- and the token is by
definition already visible in the file being complained about.
"""

import hashlib
import re
import subprocess
import unittest
from pathlib import Path

#: sha256, first sixteen hex characters, of each scrubbed literal: the real
#: amounts, unit counts, family names, employer and account number that were
#: removed from the tree. Numbers are hashed as written without separators;
#: words are hashed lower-cased.
HASHES: frozenset[str] = frozenset(
    {
        "01d7a0fbfd9da5f3",
        "01e7b98d248b0d8c",
        "08a11c6d4d712884",
        "0aba65d5d096f5f7",
        "10c0e14fa4cddca0",
        "1716fc241dfe0838",
        "1971aa6509c97535",
        "28eed3f355b0cddc",
        "2bc1cda22d25f0cc",
        "30674e39cbffa062",
        "337f0f77bfab0cee",
        "3de6875640b5fe3e",
        "4430775eac6b7f78",
        "45f9f30ab2ab1262",
        "530eab41e8ba99ce",
        "554c6ead0415077d",
        "63780c958d017bb1",
        "6d3c1dedfe523392",
        "7257f4e6aae6f389",
        "77b5a3b4f8d68ebc",
        "7aa29b6454d34736",
        "7b4105292ce8bfa7",
        "8b30394e5b4b58c6",
        "8d66fd60687da00a",
        "8e3c09d810b191e2",
        "8fa5cfee5873bba5",
        "986231da67a5a276",
        "986e17fa4d364206",
        "9962a89c72cd01a7",
        "9d8f1cef12f0d058",
        "9e1793a75f7dbb31",
        "9fbf261b62c1d7c0",
        "a71165bd92211681",
        "a7eebf1367b4f4d4",
        "aa0cc066049bec79",
        "b13cf1dbe7a7b6bb",
        "b96aa2766ed1a84d",
        "be79b22979691c91",
        "c06333245c366d22",
        "c08435a895d93a97",
        "c3148e853205e511",
        "ca3b05eb6af1293a",
        "cdcdba4575077f6e",
        "d32abcb64a687fa7",
        "da2a26d2b7909b74",
        "e4dc8e1c4b8f0c5d",
        "ed086d23252b60d9",
        "f2ab3d1d1f22e208",
        "f7f33e9b6d966936",
        "f995a1cee69919f0",
        "fabb00107f5e2482",
        "fde6b16e142f259c",
    }
)

#: The same amounts written without cents, checked only against figures the
#: text groups with separators. A bare digit run cannot be trusted for these:
#: "24.6710" is a published fund price and contains "6710", which is also an
#: account balance that was scrubbed. One is a leak and one is a coincidence,
#: and only the comma tells them apart.
AMOUNTS: frozenset[str] = frozenset(
    {
        "0adf361d5464132e",
        "0bab82e57d7d4333",
        "1f87635aff05d8cf",
        "267dab634f08cce7",
        "2c1f3f5f6523af84",
        "3ea77fc339263dd3",
        "41b241da37235677",
        "42b4fb473bacce2d",
        "4458fdbe322e2b97",
        "49fdfc988e29f9ff",
        "525cfd02ce6f836c",
        "530f967e2a24e5ab",
        "533099ac357e5586",
        "58070c528ac8e387",
        "66bcc9be3a5a1be4",
        "726ec906a90da1f1",
        "7a98c22ae38c33c9",
        "7e62ce15499878ca",
        "7f6876b4d50d8f82",
        "857770863b781856",
        "8e2937f1645ff833",
        "90bbc9533a02213f",
        "c68a66c5c914b0c5",
        "dd94edf8b08f16a4",
        "e8ff748e5a934745",
    }
)

#: Text the tree carries but does not author. `uv.lock` is a wall of hex that
#: will collide with something eventually, and the DFAS fixture is published
#: federal pay data whose figures are supposed to be exact. `pyproject.toml`
#: names an employer only in the trove classifier every package that runs on
#: Windows carries, which is a platform declaration rather than whose 401k
#: this is.
EXEMPT: frozenset[str] = frozenset(
    {
        "uv.lock",
        "pyproject.toml",
        "tests/dfas_basic_pay_em.html",
        "tests/test_no_operator_figures.py",
    }
)

#: What is worth hashing out of a line. A money-shaped number keeps its
#: separators stripped, since "1,303.68" and "1303.68" are the same figure
#: written twice.
#:
#: TOKEN is deliberately broader than "a word": an account suffix is bare
#: digits with no decimal point and a full account number starts with one, so
#: a pattern anchored on a letter saw neither. Over-matching costs nothing
#: here -- everything is hashed and only an exact hit is reported -- while
#: under-matching is a guard that passes on the thing it was written for.
NUMBER: re.Pattern[str] = re.compile(pattern=r"\d[\d,]*\.\d+")

#: A whole-dollar amount written with separators. TOKEN cannot see one --
#: the commas break "45,000" into runs too short to match -- and NUMBER wants
#: a decimal point, so a figure quoted without cents fell between them. That
#: is how amounts are written in prose, which is where they get pasted.
GROUPED: re.Pattern[str] = re.compile(pattern=r"\d{1,3}(?:,\d{3})+")

TOKEN: re.Pattern[str] = re.compile(pattern=r"[A-Za-z0-9]{4,}")


def digest(token: str) -> str:
    """
    The comparison form of one token.
    :param token: A number or word lifted out of a line
    :return: The first sixteen hex characters of its sha256
    :rtype: str
    """

    return hashlib.sha256(token.encode()).hexdigest()[:16]


def root() -> Path:
    """
    The checkout this test lives in.
    :return: The repository root
    :rtype: Path
    """

    return Path(__file__).resolve().parent.parent


def tracked() -> list[Path]:
    """
    Every file git is carrying, which is the set that gets published.

    Asked of git rather than walked, so that anything ignored -- a local
    workspace, a rendered brief, a virtualenv -- is out of scope by construction
    rather than by an exclusion list that has to be maintained.
    :return: The tracked paths, exemptions removed
    :rtype: list[Path]
    """

    try:
        # Tracked files *and* untracked ones git would not ignore. Tracked alone
        # is the set that is already published, and scanning only that makes the
        # check useless exactly when it is needed: a brand new file full of real
        # figures is invisible until the commit that publishes it, so the guard
        # goes green locally and fails in CI after the leak is in a commit
        # message. That happened, on the commit that added this comment's
        # sibling test file.
        listed: str = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            check=True,
            cwd=root(),
        ).stdout

    # Raised rather than allowed out as a CalledProcessError from a
    # subprocess the reader has no reason to know about. This check exists
    # to stop failing open, so the one case where it cannot check anything
    # has to say that in the terms of what it guards -- and has to fail
    # rather than skip, because a skipped scan and a clean scan are the
    # same green tick.
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        raise AssertionError(
            "cannot list tracked files, so nothing was scanned for the "
            f"operator's own figures: git is unavailable or this is not a "
            f"checkout ({e})"
        ) from e

    return [
        root() / name
        for name in listed.splitlines()
        if name
        and name not in EXEMPT
        and name.endswith(
            (".py", ".md", ".txt", ".conf", ".sh", ".plist", ".cron", ".toml")
        )
    ]


class TheTreeCarriesNobodysRealFigures(unittest.TestCase):
    def test_no_scrubbed_value_has_come_back(self) -> None:
        found: list[str] = []

        for path in tracked():
            try:
                text: str = path.read_text(encoding="utf-8")

            # A tracked file that is not decodable text is not one this can
            # check, and is not a place a pasted figure lands.
            except UnicodeDecodeError, OSError:
                continue

            for number, line in enumerate(text.splitlines(), start=1):
                tokens = [m.replace(",", "") for m in NUMBER.findall(line)]
                tokens += [m.lower() for m in TOKEN.findall(line)]

                grouped = [m.replace(",", "") for m in GROUPED.findall(line)]

                found.extend(
                    f"{path.relative_to(root())}:{number} carries {token!r}"
                    for token in tokens
                    if digest(token=token) in HASHES
                )
                found.extend(
                    f"{path.relative_to(root())}:{number} carries {token!r}"
                    for token in grouped
                    if digest(token=token) in AMOUNTS
                )

        self.assertEqual(
            found,
            [],
            "the operator's own figures are back in the tree:\n  " + "\n  ".join(found),
        )

    def test_the_guard_would_notice(self) -> None:
        # A hashed denylist fails open in the one way that matters: get the
        # hashing wrong and it passes forever while checking nothing. So one
        # known-forbidden token is put through the same function the scan uses.
        self.assertIn(digest(token="microsoft"), HASHES)
        self.assertNotIn(digest(token="acme"), HASHES)

    def test_it_is_looking_at_a_real_file_list(self) -> None:
        # The other way it fails open: `git ls-files` returning nothing, in a
        # checkout or a sandbox where git is unhappy, scans an empty set and
        # reports success.
        self.assertGreater(len(tracked()), 50)


if __name__ == "__main__":
    unittest.main()

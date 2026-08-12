# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""What a tag has to be true of before it becomes a release.

Publishing is the one thing here that cannot be taken back. A version number on
PyPI is spent whether or not the artifact under it was right, so the checks that
matter run before the upload rather than after -- and the ones that can be
checked without a tag at all belong here, where they fail on the pull request
instead of on the tag.

The release workflow enforces two of these itself, against the tagged tree. They
are duplicated rather than delegated: a workflow step is only exercised by
tagging, which is exactly the moment nobody wants to discover that the step was
wrong. These run on every push.

Not covered here, because nothing local can: whether the PyPI trusted publisher
is configured. That lives in project settings on pypi.org, and the first tag is
what finds out.
"""

import re
import tomllib
import unittest

from package_tree import PACKAGE, REPO

CHANGELOG = REPO / "CHANGELOG.md"
PYPROJECT = REPO / "pyproject.toml"
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

#: A Keep a Changelog release heading: `## [1.2.3] - 2026-08-12`.
RELEASE_HEADING = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\]", re.MULTILINE)


def config() -> dict:
    with PYPROJECT.open(mode="rb") as f:
        return tomllib.load(f)


def declared_version() -> str:
    return str(object=config()["project"]["version"])


class ChangelogTests(unittest.TestCase):
    def test_the_declared_version_has_an_entry(self) -> None:
        # The release notes point at the changelog, so a version with no section
        # ships a release whose notes are a link to nothing. The workflow makes
        # the same check against the tagged tree -- an re.search for this exact
        # heading -- and refuses to publish without it.
        versions: list[str] = RELEASE_HEADING.findall(
            string=CHANGELOG.read_text(encoding="utf-8")
        )

        self.assertIn(
            declared_version(),
            versions,
            f"CHANGELOG.md has no '## [{declared_version()}]' section; found "
            f"{versions or 'none'}",
        )

    def test_the_newest_entry_is_the_declared_version(self) -> None:
        # Ordering, not just presence. A changelog whose top entry is older than
        # the version about to ship means somebody bumped pyproject.toml and
        # wrote the notes under the previous heading.
        versions: list[str] = RELEASE_HEADING.findall(
            string=CHANGELOG.read_text(encoding="utf-8")
        )

        self.assertTrue(versions, "CHANGELOG.md has no release sections at all")
        self.assertEqual(
            versions[0],
            declared_version(),
            "the newest CHANGELOG.md section is not the version in "
            "pyproject.toml; a new release goes above the old ones",
        )

    def test_it_keeps_an_unreleased_heading(self) -> None:
        # Where the next change goes. Without it the next person either edits a
        # released section -- rewriting history somebody may have read -- or
        # writes nothing.
        self.assertIn(
            "## [Unreleased]",
            CHANGELOG.read_text(encoding="utf-8"),
            "CHANGELOG.md needs an Unreleased heading to write the next change under",
        )


class PackageMetadataTests(unittest.TestCase):
    def test_the_metadata_pypi_shows_is_present(self) -> None:
        project = config()["project"]

        for field in ("license", "authors", "keywords", "classifiers", "urls"):
            with self.subTest(field=field):
                self.assertIn(field, project, f"[project] has no {field}")

    def test_the_typed_classifier_has_a_marker_behind_it(self) -> None:
        # A downstream type checker ignores annotations from a package with no
        # py.typed, so the classifier alone tells the reader one thing and the
        # tooling another. Either both or neither.
        project = config()["project"]
        claims_typed: bool = "Typing :: Typed" in project.get("classifiers", [])
        has_marker: bool = (PACKAGE / "py.typed").is_file()

        self.assertEqual(
            claims_typed,
            has_marker,
            "the Typing :: Typed classifier and src/stonksmith/py.typed have to "
            "agree; one without the other is a claim with nothing behind it",
        )

    def test_the_declared_python_matches_the_classifier(self) -> None:
        # requires-python is what pip enforces; the classifier is what the page
        # says. They drift in the direction of the page being wrong.
        project = config()["project"]
        requires: str = project["requires-python"]
        floor: str = requires.lstrip(">=~^ ")

        self.assertIn(
            f"Programming Language :: Python :: {floor}",
            project["classifiers"],
            f"requires-python is {requires} but no classifier names {floor}",
        )


class ReleaseWorkflowTests(unittest.TestCase):
    """The workflow is only exercised by tagging, which is too late to find out."""

    def setUp(self) -> None:
        self.text: str = WORKFLOW.read_text(encoding="utf-8")

    def test_it_only_fires_on_a_version_tag(self) -> None:
        self.assertIn('tags: [ "v*" ]', self.text)
        self.assertNotIn(
            "workflow_dispatch",
            self.text,
            "a release that can be fired by hand against an arbitrary ref is one "
            "whose contents cannot be reconstructed from the tag",
        )

    def test_it_compares_the_tag_against_the_declared_version(self) -> None:
        # The check this whole file exists around: the tag is the only place a
        # second copy of the version can appear, since pyproject.toml is
        # single-sourced and tests/test_version_single_source.py keeps it that way.
        self.assertIn("GITHUB_REF_NAME#v", self.text)
        self.assertIn('if [ "$tag" != "$declared" ]', self.text)

    def test_the_changelog_check_escapes_the_version(self) -> None:
        # A version is mostly dots, and a dot in a regex matches anything -- so
        # `grep "^## \[0.1.0\]"` accepts a heading reading `## [0x1x0]`, which
        # was measured rather than supposed. The gate that decides whether a
        # release has notes should match the heading it names and nothing else.
        self.assertIn(
            "re.escape(version)",
            self.text,
            "the changelog gate has to escape the version before matching it",
        )

    def test_it_reads_pyproject_without_asking_the_locale(self) -> None:
        # read_text() with no encoding takes the runner's locale. TOML is UTF-8
        # whatever that happens to be, and a release workflow is a bad place to
        # find out they differ.
        #
        # Asserted positively: naming the one form that is right outlasts a list
        # of the forms that are wrong, and this started as the latter.
        self.assertIn(
            'open("rb")',
            self.text,
            "read pyproject.toml as a binary handle and let tomllib decode it",
        )
        self.assertIn("tomllib.load(f)", self.text)

    def test_publishing_asks_for_no_more_than_it_needs(self) -> None:
        # id-token: write is what makes trusted publishing work without an API
        # token in repository secrets. contents: write creates the release. The
        # build job, which runs project code, gets neither.
        self.assertIn("id-token: write", self.text)
        self.assertIn("contents: read", self.text)

    def test_every_action_is_pinned_to_a_commit(self) -> None:
        # Same reasoning as ci.yml: a tag is a pointer its owner can move, and
        # whatever it lands on runs here with a PyPI identity in scope.
        unpinned: list[str] = [
            line.strip()
            for line in self.text.splitlines()
            if "uses:" in line and not re.search(r"@[0-9a-f]{40}\b", line)
        ]

        self.assertEqual(unpinned, [], f"not pinned to a commit: {unpinned}")


if __name__ == "__main__":
    unittest.main()

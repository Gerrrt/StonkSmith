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

import yaml

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
    """The workflow is only exercised by tagging, which is too late to find out.

    Parsed rather than grepped. Every assertion here began as a substring check
    against the file, and the permissions one was the proof that this is not the
    same thing: it asserted that ``id-token: write`` appeared *somewhere*, while
    the comment above it claimed the build job did not have it. Granting the
    build job that exact permission left the test green.
    """

    def setUp(self) -> None:
        self.text: str = WORKFLOW.read_text(encoding="utf-8")
        self.workflow: dict = yaml.safe_load(stream=self.text)
        self.jobs: dict = self.workflow["jobs"]

    def triggers(self) -> dict:
        """
        What the workflow runs on.

        YAML 1.1 reads a bare ``on`` as the boolean true, so the key this parses
        out is ``True`` rather than the string. Quoting it in the file would fix
        that and make the file worse to read, so it is handled here.
        :return: The ``on:`` mapping
        """

        return self.workflow.get("on") or self.workflow[True]

    def test_it_only_fires_on_a_version_tag(self) -> None:
        self.assertEqual(self.triggers(), {"push": {"tags": ["v*"]}})

    def test_nothing_can_fire_it_by_hand(self) -> None:
        # A release firable against an arbitrary ref is one whose contents
        # cannot be reconstructed from the tag afterwards.
        self.assertNotIn("workflow_dispatch", self.triggers())

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

    def test_every_error_annotation_goes_to_stdout(self) -> None:
        # A ::error:: is only reliably read off stdout, and sys.exit(message)
        # writes to stderr -- so a gate spelled that way still fails the step
        # but with nothing saying why, which is the half that matters when the
        # thing that stopped is a release.
        stderr_bound: list[str] = [
            line.strip()
            for line in self.text.splitlines()
            if "::error::" in line and "sys.exit(" in line
        ]

        self.assertEqual(
            stderr_bound,
            [],
            f"these would annotate nothing: {stderr_bound}",
        )

    def test_the_build_job_holds_no_publishing_rights(self) -> None:
        # The one that matters. The build job checks out the tag and runs
        # project code -- the tests, the lint, the build backend -- so it is the
        # job an attacker reaches first, and it must not be able to publish
        # anything or write to the repository.
        self.assertEqual(self.jobs["build"]["permissions"], {"contents": "read"})

    def test_only_the_publish_job_can_mint_an_identity(self) -> None:
        # id-token: write is what trades an OIDC token for a PyPI upload, which
        # is why there is no API token in repository secrets. contents: write
        # creates the release. Both belong to the job that does nothing but move
        # an already-built artifact.
        self.assertEqual(
            self.jobs["publish"]["permissions"],
            {"id-token": "write", "contents": "write"},
        )

        for name, job in self.jobs.items():
            if name == "publish":
                continue

            with self.subTest(job=name):
                self.assertNotIn("id-token", job.get("permissions", {}))

    def test_publishing_waits_for_the_gates(self) -> None:
        # Without needs:, the two jobs run at once and a tag whose tests fail is
        # on PyPI before anyone knows.
        self.assertEqual(self.jobs["publish"]["needs"], "build")

    def test_every_job_states_its_permissions(self) -> None:
        # A job with no permissions block inherits the repository default, which
        # on an older repository is write on every scope.
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertIn("permissions", job, f"{name} inherits the default token")

    def test_the_preflight_twine_is_pinned(self) -> None:
        # The pre-flight check has to be run with the same twine the upload
        # uses, or it is not checking the upload. Unpinned it resolved to
        # whatever was newest while the publish action used its own bundled
        # copy, and the two disagreed about the same wheel -- `twine check
        # --strict` passed, and the upload refused it as "'2.5' is not a valid
        # metadata version". That cost a tag.
        #
        # Only the pin is asserted. Which version it should be lives in a
        # comment beside it, because the answer is in another repository's
        # requirements file and nothing here can read it.
        commands: list[str] = [
            step["run"]
            for job in self.jobs.values()
            for step in job["steps"]
            if "run" in step
        ]
        checks: list[str] = [c for c in commands if "twine check" in c]

        self.assertTrue(checks, "nothing runs twine check")

        # The trailing (?!\S) is the part that does the work. Without it the
        # pattern matches a prefix, so `twine==7.0.*` satisfies it while leaving
        # every patch release free -- which is the drift this exists to stop.
        # The number of components is deliberately not fixed: the action pins
        # twine to 7.0.0 and packaging to 26.2, and under PEP 440 a release
        # segment may be as long as it likes.
        #
        # packaging is checked too because packaging is what decides. twine
        # hands it the metadata and its table of valid versions is where the
        # rejection came from; pinning only twine leaves the deciding half free.
        for command in checks:
            for package in ("twine", "packaging"):
                with self.subTest(package=package):
                    self.assertRegex(
                        command,
                        rf"--with {package}==\d+(?:\.\d+)*(?!\S)",
                        f"pin {package} to the exact version "
                        "gh-action-pypi-publish bundles",
                    )

    def test_every_action_is_pinned_to_a_commit(self) -> None:
        # Same reasoning as ci.yml: a tag is a pointer its owner can move, and
        # whatever it lands on runs here with a PyPI identity in scope.
        unpinned: list[str] = [
            uses
            for job in self.jobs.values()
            for step in job["steps"]
            if (uses := step.get("uses")) and not re.search(r"@[0-9a-f]{40}$", uses)
        ]

        self.assertEqual(unpinned, [], f"not pinned to a commit: {unpinned}")


if __name__ == "__main__":
    unittest.main()

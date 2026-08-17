# Contributing

This is a personal project. Contributions may open up later; in the meantime
this is what the conventions are, mostly so that they are written down somewhere
other than in the commit log.

## The gates

All four have to pass, and CI runs exactly these:

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest -q --cov --cov-fail-under=87
```

The coverage flags are not optional. Without them the suite passes locally and
fails in CI, which is the least useful place to find out. The floor is the
measured baseline rounded down, not a target — raise it when the real number
moves, and never lower it to make CI pass.

`uv run pytest -q -n auto` is the fast version while working. Run the single-
process form before pushing; a test that only passes under `-n auto` is a test
with a shared-state problem.

## Verify the test fails without its fix

This is the one that matters, and the reason this file exists.

A test that passes is not evidence. A test that passes because it asserts
something already true, or globs a directory that no longer exists, or checks a
value both before and after a change that never happened, will pass forever and
protect nothing. This project has shipped all three.

So: stash the change under `src/`, run the one test file, and watch it fail.
Quote the failure in the commit body. If it does not fail, the test is not
testing what you think, and finding that out takes a minute now or an incident
later.

A worked example is `tests/test_legacy_import_names.py`, whose docstring names
the three tests that exist specifically because the obvious implementation passes
the other four.

## Commits

Descriptive prose, not Conventional Commits. Capitalised, no trailing period,
around 60–70 characters. Often — not always — two clauses joined by ", and",
where the second names the secondary thing the change also did.

```
Dispose the engine when the database shuts down, and drop the warning filter
Stop shadowing the builtin TimeoutError, and cap complexity where it already is
Write the sheet once a night, not once a broker
```

The body is the deliverable, and it follows a shape you can read straight off
`git log`:

1. what was broken
2. why it was invisible — what passed, or printed nothing, while it was wrong
3. the fix
4. why not the obvious alternative
5. which test makes the claim real, and what it does when the fix is reverted

Not every commit needs all five. A commit that needs none of them is usually two
commits.

Branch names are the commit subject paraphrased, lowercase and hyphenated:
`the-lint-floor-and-a-coverage-number`, `one-sheet-write-a-night`. PRs are
squash-merged, so `(#NNN)` is appended for you — do not type it.

## Tests

`unittest.TestCase` throughout. There is a pytest-fixture path in
`tests/conftest.py` for new tests that want it, but the mixins are the right
answer for a `TestCase` and are not going away.

- **`tests/` is flat, and must never gain an `__init__.py`.** The helpers next
  door are imported by bare name, which works because `conftest.py` puts that
  directory on `sys.path`; an `__init__.py` breaks it in a way that looks like
  the helpers vanishing. The docstring at the top of `conftest.py` explains it.
- **The filename names the invariant, not the unit.**
  `test_suite_does_not_touch_home.py`, `test_no_import_side_effects.py`,
  `test_version_single_source.py`. If the name would be `test_<module>.py`, ask
  what property of that module is actually being pinned.
- **The module docstring states the invariant and names the bug the file
  prevents.** These read as records of something that went wrong, because that
  is what most of them are.
- **`if __name__ == "__main__": unittest.main()` goes at the end**, where it can
  see every test in the file.

Five isolation helpers, and using the wrong one is how a test ends up writing to
your real home directory:

| helper | when |
| --- | --- |
| `home_isolation` | any subprocess that could touch `$HOME` |
| `config_isolation` | any test whose code path reaches a config getter |
| `keyring_isolation` | any test that opens a broker database — not just credential tests, because `migrate_plaintext_secrets()` runs on every open |
| `gspread_isolation` | any test that reaches `open_spreadsheet()` — patching `gspread.oauth` keeps it off the network but not off your real `~/.config/gspread` |
| `package_tree` | any path anchor into the source tree |

`tests/test_suite_does_not_touch_home.py` re-runs the whole suite under a
throwaway `$HOME` and compares `~/.stonksmith` and `~/.config/gspread` — contents
*and* modes — so getting this wrong fails the build rather than quietly editing
your config. The modes are in there because contents alone missed a real escape:
a chmod changes no bytes.

In `package_tree`, `SRC` is a `sys.path` entry and `PACKAGE` is where files live.
They are different names because they are different things; a file anchor always
wants `PACKAGE`.

## Things that are settled

These have reasons written where they are configured. Changing one means
arguing with the comment, which is fine — reopening it without reading it is not.

- **Never add an ignore to `filterwarnings = ["error"]`.** That single entry is
  what makes an unclosed SQLite connection fatal rather than invisible. An ignore
  added back would not be quieting a known problem; it would be hiding the next
  one.
- **A new ruff rule group has to be already clean on `src/` before it is
  adopted.** The ratchet is rules that cost nothing to keep, not a backlog.
- **`max-complexity = 12` is a ceiling at the worst function that exists**, not a
  target. It cannot be met by accident and stops anything new being worse.
  `tests/test_the_complexity_ceiling_is_one_number.py` fails if this number and
  `pyproject.toml` part company, which they had.
- **Docstrings are Sphinx**: `:param:`, `:return:`, `:rtype:`, `:raises:`. Not
  Google-style `Args:` blocks. `tests/test_docstring_style.py` enforces the
  distinction. Ruff's `D` and `ANN` rules are deliberately off — see the comment
  in `pyproject.toml` for why.
- **The version lives in `pyproject.toml` and nowhere else.** `--version` reads
  it off the installed distribution, so bumping it is one edit plus `uv sync`.
  `tests/test_version_single_source.py` fails if the two part company.

## Releasing

A release is a version bump, a changelog entry and a tag. Nothing else is by
hand — the tag is what publishes.

1. Bump `version` in `pyproject.toml`. It lives there and nowhere else.
2. Move the `Unreleased` entries under a new `## [x.y.z] - YYYY-MM-DD` heading in
   `CHANGELOG.md`, and add the two link definitions at the bottom.
3. `uv sync`, then run the gates. `tests/test_release_contract.py` is the one
   that fails if steps 1 and 2 disagree.
4. Merge that as an ordinary pull request.
5. Tag the merge commit on `main` and push the tag:

   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

`.github/workflows/release.yml` then re-runs every gate against the tagged tree,
builds the sdist and wheel, publishes to PyPI, and creates the GitHub release
with the artifacts attached. It refuses before building anything if the tag and
`pyproject.toml` disagree, or if the changelog has no section for that version.

Two things worth knowing before you tag:

- **The tag is the release.** There is no `workflow_dispatch`, deliberately: a
  release that can be fired by hand against an arbitrary ref is one whose
  contents cannot be reconstructed from the tag afterwards.
- **PyPI is one-way.** A version number is spent whether or not what went under
  it was right — you cannot re-upload it, only yank it and burn another. That is
  why every check runs before the upload, and why the PyPI step goes before the
  GitHub release rather than after.

Tags matching `v*` are protected by a ruleset: they cannot be deleted or moved
once pushed. If you tagged the wrong commit, the fix is a new version, not a
moved tag.

## Docs

Files under `docs/` are records, and each names the section of the README that
summarises it. Change a claim in one and change its summary in the same pass.
`tests/test_doc_cross_references.py` will tell you a link went stale; it cannot
tell you the prose stopped being true.

## Adding a broker or a module

Read [the project structure](README.md#project-structure) for what a broker
package is and how `BrokerLoader` finds it, and
[`docs/modules.md`](docs/modules.md) for what a module is handed and what it must
return. `src/stonksmith/modules/example.py` is the annotated template.

First question for any "add broker X": **is X already reachable through
SnapTrade?** If so it is an operator action, not a code change — no new broker,
module, database or tab. Vanguard is the standing example.

## Security

Do not open a public issue for anything that would let someone reach an account,
a token or a database. [`SECURITY.md`](SECURITY.md) has the reporting route and
the current posture.

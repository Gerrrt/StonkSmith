# Changelog

Notable changes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. This project follows [Semantic Versioning](https://semver.org/).

The version lives in `pyproject.toml` and nowhere else; a release is that number
plus a matching `v`-prefixed tag, and the release workflow refuses to publish if
the two disagree.

## [Unreleased]

## [0.1.1] - 2026-08-12

No change to the tool. `v0.1.0` was tagged and published nothing: the release
workflow pinned a version of `gh-action-pypi-publish` whose bundled `twine`
predates core metadata 2.5, which is what this project's build produces, so the
upload was refused before it started. Nothing reached PyPI and no release was
created, and the tag is left in place rather than moved — a tag that shipped
nothing is a more useful record than one that quietly points somewhere else.

### Fixed

- The release workflow's pre-flight `twine check` ran with whatever `twine` was
  newest while the upload used the action's own older copy, so the two disagreed
  about the same wheel and the check passed on something the upload rejected. It
  is pinned to the version the action bundles, and a test refuses to let it float
  again.

## [0.1.0] - 2026-08-12

First tagged release. The project existed for 127 merged pull requests before
this point without a version anyone could refer to, so this entry describes the
state rather than the journey — the individual changes are in the commit log,
which is written to be read.

### Added

- Five brokers, in three shapes. `schwab529plan` posts a form and parses the
  response; `fidelity` and `ally` drive a real browser, attaching over CDP to one
  the operator signed into; `snaptrade` and `tsp` are API-backed. A directory
  containing `broker.py` *is* a broker — that is how they are discovered, from
  the package and from `~/.stonksmith/brokers`.
- Per-broker SQLite databases holding accounts, snapshots, holdings and
  transactions, and a Google Sheets dashboard built from them.
- `stonksmith` and `stonksmithdb` console scripts.
- Scheduling as a macOS LaunchAgent, because `cron` cannot reach the login
  keychain.

### Security

- Secrets live in the OS keyring, never in SQLite. Databases predating that split
  are migrated on first open. See [SECURITY.md](SECURITY.md) for what that
  migration does *not* do.
- Everything StonkSmith writes is owner-only — databases, config, run logs, page
  captures, the saved browser session, the Playwright trace, the Chromium profile
  and gspread's stored Google credentials. Best-effort: a filesystem without
  POSIX modes is not a supported reason to fail a run.
- Network calls logged for diagnostics have their query strings dropped and their
  id-shaped path segments masked.

### Notes

- Requires Python 3.14.
- The package installs one top-level name, `stonksmith`. It previously installed
  six — `main`, `etc`, `helpers`, `modules`, `loaders`, `brokers` — straight into
  `site-packages`. A broker or module written against those still loads, with a
  `DeprecationWarning`; that shim is removed in 1.0.

[Unreleased]: https://github.com/Gerrrt/StonkSmith/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.1
[0.1.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.0

# Changelog

Notable changes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. This project follows [Semantic Versioning](https://semver.org/).

The version lives in `pyproject.toml` and nowhere else; a release is that number
plus a matching `v`-prefixed tag, and the release workflow refuses to publish if
the two disagree.

## [Unreleased]

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

[Unreleased]: https://github.com/Gerrrt/StonkSmith/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.0

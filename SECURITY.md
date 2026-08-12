# Security

StonkSmith signs into real brokerage accounts and writes what it finds to disk.
This describes what it protects, how, and — at least as usefully — what it does
not.

Everything here is a statement about the code as it stands, not an aspiration. If
something below stops being true, that is a bug in this file.

## Supported versions

| Version | Supported |
| --- | --- |
| `main` (latest commit) | Yes |
| anything else | No |

One row, because there is nothing else to put in it. The version in
`pyproject.toml` reads `0.1.0`, there are no tags, no releases and no PyPI
package. "Upgrade" means `git pull && uv sync`.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab on this
repository, then **Report a vulnerability**. The report stays private until
there is something to say publicly.

Please do not open a public issue for anything that would let someone else reach
an account, a token or a database.

There is no security mailbox and no PGP key. That is deliberate — an address and
a key are two more things to keep working, and for a single-maintainer project
they tend to rot faster than they get used.

## What is protected, and how

**Secrets are never in the database.** The `credentials` table holds a username
and a `keyring_key`; the secret itself lives in the OS credential store —
Keychain on macOS, Secret Service on Linux, Credential Locker on Windows —
under the service name `stonksmith` and the key `<broker>:<username>`. See
`src/stonksmith/etc/secrets.py`.

**Databases written before that split are migrated on first open.** Each
plaintext password moves into the keyring and the column is cleared in place.
See the accepted risk below about what "in place" does and does not mean.

**Everything StonkSmith writes is owner-only** — `0600` for files, `0700` for
directories. That covers the account databases, the config, the run log, page
captures and screenshots, the saved browser session, the Playwright trace, the
Chromium profile directory, and gspread's stored Google credentials.

The directory modes are the load-bearing half: `~/.stonksmith/playwright` holds
files StonkSmith does not write — Playwright saves the trace, Chromium populates
the profile, and the CDP profile is created by a command StonkSmith only prints.
A directory that cannot be traversed covers all of them without having to know
they exist.

**These modes are best-effort.** `src/stonksmith/etc/permissions.py` suppresses
`OSError`, so on a filesystem without POSIX permissions — a Windows volume, a
network mount, some container binds — the chmod silently does nothing and the run
carries on. That is a deliberate trade: a tool that refuses to record a balance
because it could not set a mode is worse than one that records it. It does mean
these are a hardening measure and not a guarantee.

**Logged network calls are redacted.** `endpoint_of()`, `query_shape()`,
`size_suffix()` and `error_shape()` in `src/stonksmith/etc/browser_connection.py`
drop query strings, mask path segments that look like ids or tokens, report
response sizes from the header rather than by reading the body, and print only
keys plus values that look like machine-readable codes. `names_a_code()` matches
whole words specifically so that `passcode` never reaches a log.

**Secrets shown on screen are masked.** `process_secret()` returns eight
asterisks unless *both* audit mode is on and a positive reveal count is set, and
`get_audit_mode()` returns `False` on a malformed value rather than raising —
anything that is not a boolean is not permission to reveal a secret.

## Accepted risks

Each of these is known, and each is here because the alternative was worse or
was not available.

### A migrated database is not a scrubbed one

`migrate_plaintext_secrets()` runs `UPDATE credentials SET password = NULL`. It
does not `VACUUM`, so the old plaintext can survive in freed pages until SQLite
reuses them.

*If it matters to you:* `sqlite3 <workspace>/<broker>.db 'VACUUM;'`, or start a
fresh workspace.

### `-p` on the command line

A password passed as an argument is in your shell history and readable by any
process on the machine through `ps`. Use `add creds` in `stonksmithdb` plus
`-id`. The same applies to the `-p <file>` form, which reads a plaintext file you
maintain.

### A CDP browser is drivable by anything local

`--browser cdp` requires Chrome started with `--remote-debugging-port`. While
that port is open, any local process can drive the signed-in session. StonkSmith
cannot authenticate that channel — nothing can; that is what the protocol is.

*Mitigation:* close the window when the run finishes.

### The Google grant is wider than it needs to be

`gspread.oauth()` requests full `spreadsheets` and `drive` scopes, not the
file-scoped `drive.file`. So the token in
`~/.config/gspread/authorized_user.json` reaches the operator's entire Drive,
not just the one spreadsheet StonkSmith writes. That is gspread's default rather
than a StonkSmith decision, and narrowing it means passing `scopes=` and deleting
`authorized_user.json` to re-consent. It is an open item, not a settled one.

StonkSmith tightens the mode on that file and the directory holding it, but the
scope is what it is.

### The scheduled run holds keychain access

macOS `cron` cannot reach the login keychain, so the supported schedule is a
LaunchAgent bootstrapped into the GUI session — which means a process with
keychain access lives in the logged-in session. See `docs/scheduling.md`.

The shipped LaunchAgent also appends forever to `/tmp/stonksmith-nightly.log`,
which is a shared directory, and that log carries account names and balances.
Point `StandardOutPath` somewhere under `$HOME` if that matters to you.

### Captures and screenshots are not redacted

The redaction above applies to the response log. A page capture is the raw
signed-in page: account numbers, balances, and whatever 2FA context was on
screen. They are `0600`, and `docs/live-verification.md` invites you to quote one
in an issue — read it before you do.

## Automation and bot detection

StonkSmith uses `playwright-stealth`, passes
`--disable-blink-features=AutomationControlled`, and sends a browser User-Agent
to `dfas.mil` rather than identifying itself. Two brokers cannot be reached any
other way; one of them refuses an automated login outright, which is why the
human types the password and StonkSmith attaches afterwards.

This is stated plainly because a public repository that ships evasion and does
not mention it is worse than one that does. Automating a login may conflict with
a brokerage's terms of service. It is your account and your call.

## Supply chain

In place:

- GitHub Actions are pinned to commit SHAs, not tags, with the reasoning in
  `.github/workflows/ci.yml`. Dependabot keeps the pin and its human-readable
  comment in step.
- Dependabot covers `uv` and `github-actions` weekly, grouping minor and patch
  updates and leaving majors separate.
- `uv.lock` is committed and carries a `sha256` for every artifact; CI installs
  with `uv sync --locked`, so a CI install is hash-verified.
- The CI workflow requests `contents: read` and nothing else.
- `tests/test_dependency_hygiene.py` fails if two installed distributions claim
  the same top-level import name. It exists because that happened: `playwright-sm`
  shipped its own `playwright_stealth/`, macOS and Linux CI resolved different
  copies, and the type check and the test suite disagreed across platforms for
  days.

Not in place, and worth knowing: there is no secret scanning, no dependency
vulnerability audit, and no CodeQL. Dependabot's *security* updates are on, but
those only fire once an advisory exists.

The published wheel pins nothing — `pyproject.toml` uses open `>=` ranges. The
hash pinning above applies to this repository's own environment, not to anyone
installing the package.

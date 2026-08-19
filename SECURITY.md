# Security

StonkSmith signs into real brokerage accounts and writes what it finds to disk.
This describes what it protects, how, and — at least as usefully — what it does
not.

Everything here is a statement about the code as it stands, not an aspiration. If
something below stops being true, that is a bug in this file.

## Supported versions

| Version | Supported |
| --- | --- |
| the latest release | Yes |
| `main` | Yes |
| any earlier release | No |

Two rows and no more. This is a single-maintainer project: fixes land on `main`
and go out in the next release, and there is no branch on which an older version
gets patched. If you are on an earlier release, the upgrade *is* the fix.

Releases are on [PyPI](https://pypi.org/p/stonksmith) and as GitHub releases,
built from a tag by `.github/workflows/release.yml` — which refuses to publish
when the tag and `pyproject.toml` disagree about the version. Running from a
clone is equally supported; there "upgrade" means `git pull && uv sync`.

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
plaintext password moves into the keyring, the column is cleared, and the
database is then rebuilt with a `VACUUM` so the cleared bytes do not stay behind
in a freed page. The rebuild runs only when a migration actually moved
something — it is a whole-file rewrite, and the migration happens once in a
database's life. `vacuum` in `stonksmithdb` runs it on demand for a workspace
that migrated before this existed. See the accepted risk below for what the
rebuild does and does not reach.

**StonkSmith asks Google for Sheets access and nothing else.** `gspread.oauth()`
defaults to full `spreadsheets` **plus** `drive`, and that default is what this
tool used to ship — so the refresh token in
`~/.config/gspread/authorized_user.json` reached every file in the operator's
Drive rather than the one book being written.

Drive was there for exactly one call. `Client.open(title)` is a Drive
`files.list` search, and it was the only Drive request in the codebase;
everything past it goes to `sheets.googleapis.com`. StonkSmith now opens the
book by id — `[SHEETS] spreadsheet_id` in `~/.stonksmith/stonksmith.conf` — which
removes the reason for the scope rather than trimming it.

Not `drive.file`, which earlier versions of this file named as the target.
`drive.file` grants per-file access to files *the app itself created* or the user
picked through the Google Picker, and a command-line tool cannot show a Picker —
so a spreadsheet made by hand in the browser is unreachable under it, even by id.
Dropping Drive outright is both narrower and workable.

There is deliberately **no fallback** to looking the book up by name when the id
is unset: the fallback would re-request the Drive scope, which is the entire
thing being removed. An unset id is an error that names the setting.

`spreadsheets` is still account-wide over Sheets. This is narrower than it was;
it is not narrow. **An existing `authorized_user.json` still carries the old
wide grant** — Google does not narrow a token in place, so until it is deleted
and re-consented nothing has changed for that install:

```bash
rm ~/.config/gspread/authorized_user.json
```

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

### A vacuumed database is not a scrubbed disk

`migrate_plaintext_secrets()` clears the legacy `password` column and then
rebuilds the database with a `VACUUM`, because clearing a column is not the same
as removing what was in it: SQLite marks the old cell free inside its page and
moves on. That is measured rather than assumed — at ten credentials the cleared
password was still greppable in the file in fifteen runs out of fifteen. At one
credential it was greppable in none of them, since a single row's page is
rewritten in place, so the exposure needs more than one credential to exist at
all.

The rebuild reaches the database file. **Three things it does not reach:**

- **The rollback journal.** SQLite's default journal mode writes the pre-`UPDATE`
  page image — plaintext included — to `<broker>.db-journal`, which is deleted
  rather than overwritten on commit. Confirmed by reading one mid-transaction.
- **The temporary copy `VACUUM` itself writes**, which is a full copy of the
  database at whatever mode the system temp directory gives it. StonkSmith
  tightens what it creates; this file is SQLite's.
- **The filesystem blocks** the old pages occupied. On an SSD those outlive the
  file by whatever the drive decides.

So this shrank from "the plaintext is in your database" to "the plaintext may be
in free space on your disk". That is a real reduction and it is not a scrub.

*If it matters to you:* full-disk encryption is the control that covers the
residue; a fresh workspace on an encrypted volume is the belt-and-braces answer.

*If you migrated before this shipped:* the automatic rebuild only runs when a
migration actually moves a secret, and yours already did — so it will never fire
again for you. Run `vacuum` in `stonksmithdb`, which rebuilds every database in
the workspace. That is what it is for.

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
installing the package. That is the ordinary trade a library makes and is worth
naming rather than leaving to be discovered: `pip install stonksmith` resolves
its dependencies fresh, and what it resolves to is not what CI tested.

Uploads use PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/)
rather than a long-lived API token, so there is no publishing credential in
repository secrets to leak or rotate. The workflow mints a short-lived OIDC token
scoped to one repository, one workflow file and one environment; the job that
holds it does nothing but download an already-built artifact and upload it.

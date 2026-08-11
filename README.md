# :hammer: StonkSmith

_Absolutely no day-trading._

Forge your financial data into a single source of truth. **StonkSmith**
scrapes, aggregates, and syncs your investment accounts into a unified
Google Sheets Dashboard.

---

## :rocket: Overview

StonkSmith is a Python-based tool designed to:

- :eye: Scrape data from multiple investment accounts
- :jigsaw: Aggregate holdings, balances, and performance
- :chart: Sync everything into a single Google Sheets dashboard
- :brain: Provide a centralized view of your net worth

No more bouncing between your squad of applications that are meant for
specific accounts because there isn't any current app that _just works_ for
all the accounts you own.

**ONE SHEET TO RULE THEM ALL!**

---

## :wrench: Features

- [x] Multi-broker support (Fidelity, Schwab and anything else via SnapTrade,
      plus Ally Invest and Schwab 529 scrapers, and TSP from public data, for
      what SnapTrade does not cover)
- [x] Automatic data scraping (requests + Playwright)
- [x] Google Sheets sync
- [x] CLI commands for automation
- [x] Credentials stored in the OS keyring
- [x] Account history: numeric balances, holdings and transactions over time
- [ ] More brokers. Vanguard needs no code at all; link it through SnapTrade.
- [x] Net worth tracking over time
- [x] Asset allocation breakdown
- [x] Scheduling (cron), for the brokers that run unattended — three of five,
      plus Ally in a reduced mode. Fidelity is replaced by SnapTrade, not
      scheduled

---

## :bricks: Project Structure

```text
StonkSmith/
|--- src/
|    |--- main.py            # CLI entry point
|    |--- etc/               # config, logging, connection, shells, paths,
|    |                       #   records, database, the canonical row shape
|    |                       #   and the one thing that writes it to a sheet
|    |--- brokers/           # one package per broker (broker.py + helpers)
|    |--- modules/           # per-broker scrape/sync modules
|    |--- loaders/           # dynamic broker and module loading
|    |--- helpers/           # db, sheets, logging helpers
|--- docs/                # the reference chapters this file summarises,
|                         #   live verification, what a schedule can carry,
|                         #   and what was decided against
|--- scripts/             # one-off setup and probe scripts
|--- tests/
|--- pyproject.toml
```

Each broker is one package. `brokers/<name>/broker.py` holds the login class and
publishes it as `Broker`, alongside `database.py`, `db_navigator.py`,
`broker_args.py` and any `parser.py`. A directory containing
`broker.py` *is* a broker — that is how `BrokerLoader` discovers them, scanning
`src/brokers/` first and then `~/.stonksmith/brokers/`. Everything except
`broker.py` is optional; a broker without `database.py` and `db_navigator.py` is
listed as "incomplete" by `stonksmithdb`. A broker that *raises* while loading is
reported by name and skipped — it registers no subparser and is simply
unavailable for that run, so a half-finished broker under
`~/.stonksmith/brokers/` never takes the rest of the tool down with it.

Brokers come in three shapes. A **scraper** posts a form and reads the response,
and subclasses `Connection`: Schwab 529. A **browser-backed** broker has a login
guarded by bot detection, a session worth keeping between runs, and a page that
only exists after JavaScript has run; it subclasses `BrowserConnection`, which
owns the whole Playwright lifecycle: Fidelity and Ally. An **API-backed** broker
has no login at all — its key lives in config and the OS keyring — and
subclasses `ApiConnection`: SnapTrade, and TSP, which holds no key either
because the data it reads is published.

**Not every claim here rests on a live run.** Green tests say the code does what
it was written to do, which is not the same as saying the site still looks the
way it did when the parser was written. Ally and TSP have both been run against
the real thing, and the sheet has been read back off a real spreadsheet; two
claims are still open, both waiting on data rather than on effort — whether the
`Transactions` tab holds every movement or only the newest five hundred, and
whether the `Net Worth` series carries across brokers that scraped on different
days. [`docs/live-verification.md`](docs/live-verification.md) is the record of
which is which, claim by claim, and this paragraph summarises it rather than
being maintained beside it.

---

## :wheel: Installation

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Gerrrt/stonksmith.git
cd stonksmith
uv sync
```

Fidelity and Ally drive a real browser, so install the Playwright runtime:

```bash
uv run playwright install firefox
```

Run that again after any `uv sync` that moves Playwright. Each release pins a
new browser revision, so an already-installed Firefox stops satisfying it and
the next run fails with `Could not start browser`, naming an executable that is
not there.

---

## :pizza: Usage

```bash
uv run stonksmith --help
```

List the modules available for a broker:

```bash
uv run stonksmith schwab529plan -L
```

Run a module against an account:

```bash
uv run stonksmith schwab529plan -M schwab529plan -u <username> -p <password>
```

Or use a credential stored in the database instead of passing it on the
command line:

```bash
uv run stonksmith schwab529plan -M schwab529plan -id 1
```

### Output

A run reports what it did. That is the default and it used to not be: every
progress line — including the yellow `[!]` warnings — logs at `INFO`, and the
default level was `ERROR`, so a sync could read a statement, write the snapshot
to the database and update the Google Sheet while printing nothing but a
progress bar. Success and doing nothing at all looked identical.

| Flag | Shows |
| --- | --- |
| *(none)* | What the run did, and anything that went wrong. |
| `--quiet` | Failures only. This is what an unattended run wants. |
| `--verbose` | Same as the default, but wins over `--quiet` — useful for seeing inside a wrapper script that hardcodes it. |
| `--debug` | Everything, including internals. |

All four work on either side of the broker name.

### Exit codes

The exit status reflects what the run actually did, so a cron entry, systemd
timer or CI step can tell whether the sync worked.

| Code | Meaning |
| --- | --- |
| `0` | The run did its work. A Google Sheets failure *after* the balances reached the database is still a success — the data is saved, and the log says the dashboard was not updated. |
| `1` | The run did not complete: unknown broker or module, could not connect or log in, a module reported it did nothing, only some of the requested modules loaded, or nothing reached the database. |
| `130` | Interrupted (128 + SIGINT). Distinct from `1` so a scheduler can page on a real failure and shrug at a human pressing Ctrl-C. |

A partial module load still runs the modules that did load — partial data beats
none — but reports `1` rather than claiming success.

### Scheduling

**The five brokers do not schedule alike, and two of them do not schedule at
all.** That is the part a crontab cannot tell you, and getting it wrong is
expensive in a specific way: a cron job that errors every night gets muted, and
after that the portfolio has stopped updating with nothing to say so.

| Broker | On a schedule |
| --- | --- |
| `tsp` | Yes. No credential in the daily path |
| `snaptrade` | Yes, until the connection expires — a browser step every few weeks |
| `schwab529plan` | Yes. A form post with a stored credential |
| `ally` | `--from-prices` only, which reprices a stale unit count rather than scraping |
| `fidelity` | No. Link it through SnapTrade instead |

Weekdays after the close, one process per broker — `broker` is a positional
subcommand, so there is no `--all` — staggered, because two runs inside the same
UTC second collapse into one snapshot:

```cron
PATH=/usr/local/bin:/usr/bin:/bin

30 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith tsp -M tsp --quiet
35 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith snaptrade -M snaptrade --quiet
40 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith schwab529plan -M schwab529plan -id 1 --quiet
45 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith ally -M ally --from-prices --quiet
50 18 * * 1-5  cd ~/StonkSmith && uv run stonksmithdb sheet
```

**There is no `fidelity` line, and the `ally` line is not a scrape.** Ally
honours no restored session, so `--from-prices` values the account from today's
published close and *the units the last signed-in run recorded* — exact
arithmetic on a number that goes quietly wrong the moment a deposit lands. It
says so on every account it values, and a schedule that mails only on failure
will never show anybody that line. Re-run `--manual-login` after a deposit; the
schedule cannot, and will not ask.

The sheet goes last, and it reports: `stonksmithdb sheet` exits `0` when the tabs
were rewritten and `1` when the sheet was unreachable, a tab refused, or a broker
database could not be read — a total short by a whole broker being the failure
that must not be quiet.

[`docs/scheduling.md`](docs/scheduling.md) is the record: what each broker can
do unattended, what `--from-prices` is and is not, and which of these claims a
live run has actually settled. This section summarises it rather than being
maintained beside it.

---

## :package: Brokers

Five brokers, and they do not work alike — one needs you to sign in by hand
every time, one needs no credential at all. What each needs and what a run of it
does is [`docs/brokers.md`](docs/brokers.md); this table is the index into it.

| Broker | Shape | What it needs from you |
| --- | --- | --- |
| [Fidelity](docs/brokers.md#fidelity) | Browser | A manual sign-in once; the session is reused until it expires. Or link it through SnapTrade and skip the browser |
| [Ally Invest](docs/brokers.md#ally-invest) | Browser | A manual sign-in **every** scrape — Ally honours no restored session. `--from-prices` revalues between scrapes with no browser at all |
| [SnapTrade](docs/brokers.md#snaptrade) | API | A free Personal API key, and one browser step per brokerage every few weeks. Covers Schwab, Fidelity, Vanguard and the rest through one key |
| [Schwab 529](docs/brokers.md#schwab-529) | Scraper | A stored credential. A form post and two page reads — no browser, nothing to expire |
| [TSP](docs/brokers.md#tsp) | API | Nothing daily. Share prices are published; units come from a quarterly statement or a config line |

**Adding a brokerage SnapTrade covers is an operator action, not a code change**
— no new broker, module, database or tab. Vanguard is the standing example.

Which of these can run unattended, and what changes when they do, is
[`docs/scheduling.md`](docs/scheduling.md), summarised above.

---

## :floppy_disk: Where the data goes

Every broker writes to its own SQLite file at
`~/.stonksmith/workspaces/<workspace>/<broker>.db`, holding four tables:
`accounts`, `account_snapshots`, `holdings` and `transactions`. Money is stored
as a number with the source's own text kept beside it, so a site that changes
its formatting costs you a parse rather than the record.

Browse and manage it from the shell:

```bash
uv run stonksmithdb
```

The tables, the columns, the shell's commands and what a migration does on open
are [`docs/database.md`](docs/database.md).

---

## :bar_chart: The sheet

**StonkSmith owns five tabs and refuses to touch anything else.** `Accounts`,
`Holdings`, `Transactions`, `Net Worth` and `Dashboard` are created on the first
sync and rewritten in full every run — so anything of your own goes on a tab of
your own, and pulls across with a formula.

That is a refusal rather than a convention. Each tab's first cell carries a
banner; before clearing, StonkSmith reads it back. A tab carrying the banner is
its own, an empty tab is adopted, and a tab with anything else on it is refused
by name with nothing written. The run still exits `0` — the scrape reached the
database before the sheet was touched.

Rebuild the tabs from the databases at any time, with no login anywhere:

```bash
uv run stonksmithdb sheet
```

What each tab promises, why the dashboard has to be constructed rather than
read, and what `verify` checks that a successful sync cannot show are
[`docs/sheet.md`](docs/sheet.md).

---

## :key: Module Credential Access

During module execution (`on_login`), credentials are available from both
`context` and `connection`:

- Active authenticated credential:
  - `context.active_username`
  - `context.active_password`
- Raw CLI-provided credential lists:
  - `context.cli_usernames`
  - `context.cli_passwords`
- Backward-compatible connection fields:
  - `connection.username`
  - `connection.password`

Example:

```python
def on_login(self, context, connection):
    user = context.active_username or connection.username
    if not user:
        context.log.fail("No authenticated user found")
        return False
    context.log.success(f"Running module for {user}")
```

### What a module returns

Return `False` if the module did no work — it could not reach the service, found
nothing to sync, or wrote nothing. StonkSmith exits `1` when any module returns
`False`, which is how a scheduled run detects a failure instead of reporting
success and moving on.

Returning `None` or `True` means the module did its job. `None` is the original
signature and still means success, so a module written before this contract
needs no change. Only the exact value `False` is read as failure — returning a
count of `0`, or an empty string, counts as success, so return a real `bool` if
you mean one.

---

## :lock: Security Note

This project handles sensitive financial data.

Current safeguards:

- **Secrets live in the OS keyring** (Keychain on macOS, Secret Service on
  Linux, Credential Locker on Windows). The SQLite database stores only a
  reference such as `schwab529plan:alice`, never the secret itself.
- `show creds` masks secrets. Set `audit_mode` and `reveal_chars_of_pwd` in
  `~/.stonksmith/stonksmith.conf` to reveal a short prefix when you need to
  tell two credentials apart.
- `export creds` writes the keyring reference, never the secret.
- Databases created before this change are migrated automatically on first
  open: each plaintext password moves into the keyring and the column is
  cleared in place.

Passing `-p` on the command line still exposes the secret to your shell
history and process list. Prefer `add creds` in `stonksmithdb` plus `-id`.

Never commit credentials to source control.

---

## :brain: Vision

Think of StonkSmith as your own personal financial command center.

The goal is to evolve this into a modular, extensible tool that:

- Scales with your life as you gain wealth
- Supports new platforms easily
- Gives you total visibility and control

---

## :handshake: Contributing

This is currently a personal project, but contributions may open up in the
future.

Before opening a PR, run what CI runs:

```bash
uv run ruff check &&
uv run ruff format --check &&
uv run ty check &&
uv run pytest -q
```

---

## :newspaper: License

MIT License

Do what you want, just give credit.

---

## :trumpet: Author

Built by someone who got tired of checking five different apps just to
answer the simple question of: _"How much money do I actually have?"_

---

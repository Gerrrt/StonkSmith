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
      plus a Schwab 529 scraper for what SnapTrade does not cover)
- [x] Automatic data scraping (requests + Playwright)
- [x] Google Sheets sync
- [x] CLI commands for automation
- [x] Credentials stored in the OS keyring
- [x] Account history: numeric balances, holdings and transactions over time
- [ ] More brokers: TSP and Ally both need a scraper — neither is one of the
      brokerages SnapTrade covers. Vanguard needs no code at all; link it.
- [ ] Net worth tracking over time
- [ ] Asset allocation breakdown
- [ ] Scheduling (cron / background jobs)

---

## :bricks: Project Structure

```text
StonkSmith/
|--- src/
|    |--- main.py            # CLI entry point
|    |--- etc/               # config, logging, connection, shells, paths
|    |--- brokers/           # one package per broker (broker.py + helpers)
|    |--- modules/           # per-broker scrape/sync modules
|    |--- loaders/           # dynamic broker and module loading
|    |--- helpers/           # db, sheets, logging helpers
|--- scripts/             # one-off setup and probe scripts
|--- tests/
|--- pyproject.toml
```

Each broker is one package. `brokers/<name>/broker.py` holds the login class and
publishes it as `Broker`, alongside `database.py`, `db_navigator.py`,
`broker_args.py` and any `parser.py` / `saver.py`. A directory containing
`broker.py` *is* a broker — that is how `BrokerLoader` discovers them, scanning
`src/brokers/` first and then `~/.stonksmith/brokers/`. Everything except
`broker.py` is optional; a broker without `database.py` and `db_navigator.py` is
listed as "incomplete" by `stonksmithdb`.

Brokers come in two shapes. A **scraper** has a username, a password and a login
step, and subclasses `Connection`: Schwab 529 and Fidelity. An **API-backed**
broker has none of those — its key lives in config and the OS keyring, and there
is nothing to log into — and subclasses `ApiConnection` instead: SnapTrade.

---

## :wheel: Installation

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Gerrrt/stonksmith.git
cd stonksmith
uv sync
```

Fidelity drives a real browser, so install the Playwright runtime once:

```bash
uv run playwright install firefox
```

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

### Fidelity

Fidelity fronts its login with Akamai Bot Manager and ThreatMetrix, which reject
a scripted sign-in before the form renders. Sign in yourself once; StonkSmith
reuses the session afterwards:

```bash
uv run stonksmith fidelity -M fidelity --manual-login
```

A browser window opens. Sign in as normal, including 2FA. Once the portfolio
summary loads, StonkSmith takes over, saves the session, and scrapes. Later runs
reuse the saved session and only prompt again when it expires.

`--manual-login` implies `--headed` and needs no stored credential.

Fidelity's bot protection refuses the login page to any browser that automation
launched, before credentials are ever entered. The way through is to attach to a
Chrome you started yourself:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.stonksmith/playwright/cdp-profile" \
  "https://digital.fidelity.com/prgw/digital/signin/retail"
```

Chrome opens the sign-in page itself; StonkSmith deliberately never drives an
attached browser before you are signed in. Doing so trips Fidelity's bot sensor
and flags that Chrome profile, after which even a manual sign-in is refused --
the fix then is a fresh `--user-data-dir`, since the flag is per profile.

Sign in to Fidelity in that window, then:

```bash
uv run stonksmith --verbose fidelity -M fidelity --browser cdp
```

StonkSmith attaches, reuses the tab you signed in on, and never closes your
browser. The profile persists, so later runs skip the sign-in. Chrome 136 and
later refuse `--remote-debugging-port` on the default profile, which is why the
dedicated `--user-data-dir` is required.

`--cdp-url` points at a different endpoint; StonkSmith prints the exact launch
command if nothing is listening.

### Other browser modes

Fidelity's bot protection may refuse to render the login form to Playwright's
bundled Firefox at all. If the browser shows *"Sorry, we can't complete this
action right now"*, try a Chromium-family browser with a persistent profile:

```bash
uv run playwright install chrome
uv run stonksmith fidelity -M fidelity --manual-login --browser chrome
```

`--browser chrome` drives the real Google Chrome binary, which fingerprints
better than bundled builds; `--browser chromium` uses Playwright's own build.
Both keep their profile in `~/.stonksmith/playwright/chrome-profile`, so cookies
and history accumulate between runs. `--profile-dir` points elsewhere.

### SnapTrade

SnapTrade is an aggregator: link a brokerage once through its Connection Portal
and StonkSmith reads every linked account through a single key, with no browser
and no stored password. One `snaptrade` broker covers all of them.

Setup is once, and interactive. Get a free Personal API key from
[SnapTrade](https://snaptrade.com), then:

```bash
export SNAPTRADE_CLIENT_ID='PERS-...'
```

```bash
read -rs SNAPTRADE_CONSUMER_KEY && export SNAPTRADE_CONSUMER_KEY
```

```bash
uv run python scripts/snaptrade_register.py store
```

A personal key is those two values and nothing else. There is no `userId` or
`userSecret` to find: SnapTrade's docs say to *"omit userId and userSecret when
making API requests; SnapTrade resolves the user from the Personal API key"*,
and *"do not call Register user for Personal API key authentication"*. Trying
anyway returns a 403 reading *"Authentication credentials were not provided"*,
because `registerUser` and `listUsers` accept only commercial keys and the SDK
sends no auth at all for a mode an endpoint does not offer.

`store` writes the consumer key to the OS keyring and prints the line to paste
into the `[SNAPTRADE]` section of `~/.stonksmith/stonksmith.conf`. Then link a
brokerage, if you have not already:

```bash
uv run python scripts/snaptrade_register.py link
```

Open the URL it prints — it signs in as you and expires in about five minutes —
and connect Schwab, Fidelity or anything else SnapTrade supports. Check what is
linked at any time with `scripts/snaptrade_register.py status`, which prints
connection health and account names but never balances.

#### Adding a second brokerage

Linking Schwab alongside Fidelity adds **no** broker, **no** module, **no**
database and **no** worksheet tab. One `snaptrade` broker, one `snaptrade.db`,
one `SnapTrade` sheet; the `Brokerage` column tells them apart. Anything
SnapTrade covers is an operator action rather than a code change.

```bash
uv run python scripts/snaptrade_register.py link --broker SCHWAB
```

`--broker` preselects the brokerage on the portal screen. It is a convenience,
not a filter — you can connect anything from the same URL.

Connections are created read-only. StonkSmith reads balances, positions and
activities and never places an order, so a trade connection would grant a
permission it never uses; Schwab is one of the brokerages that offers both.
`--connection-type trade-if-available` is there for a brokerage that offers
nothing narrower. The grant is fixed when the connection is created, so
downgrading one that already has trade means deleting it and linking again.

**Adding a brokerage needs no flag beyond `--broker`. Repairing one you already
have needs `--reconnect <connection-id>`**, from `status`. SnapTrade de-dupes:
a plain `link` for a brokerage already connected hands back the existing
connection unchanged, which looks exactly like success.

Right after linking, the first sync may correctly skip the new accounts —
SnapTrade's initial holdings sync is not instant, and an account with no
finished sync has no balance worth recording. `status` shows a timestamp
instead of `never` once it lands. That is the guard working, not a bug.

Then sync, after creating a `SnapTrade` tab in the dashboard spreadsheet:

```bash
uv run stonksmith snaptrade -M snaptrade
```

Accounts are skipped, loudly, when they cannot be trusted: a disabled connection
(SnapTrade keeps serving its last cached balance rather than reporting an
error), holdings that have not synced in `--max-age-days` (default 3), closed,
archived or paper accounts, and liabilities such as credit cards. Override with
`--allow-stale` and `--include-liabilities`.

For each account that survives, StonkSmith also reads its positions and its
recent transactions. Both calls are per account, so both are bounded and both
fail soft: `--history-days` (default 90) sets the transaction window,
`--no-positions` skips the positions call entirely, and an account whose
positions or transactions cannot be read is reported while its balance is still
recorded. An account returning zero positions is normal rather than a failure —
a brokerage that pre-aggregates, such as a Schwab-held 529, gives SnapTrade a
balance and nothing to break it down with.

Connections expire after a few weeks and re-authorising is a browser step —
`scripts/snaptrade_register.py link` again. Until then the sync is unattended.

`scripts/snaptrade_coverage.py` lists every brokerage SnapTrade supports.

Manage stored credentials and scraped balances:

```bash
uv run stonksmithdb
```

Inside that shell: `broker schwab529plan`, then `add creds <username>`,
`show creds`, `show accounts`, `export creds <file>`, `back`, `exit`.
SnapTrade stores no credentials there; its keys live in the config file and the
keyring, so `add creds` points at the setup script instead.

### What is stored

Each broker gets its own SQLite file at
`~/.stonksmith/workspaces/<workspace>/<broker>.db`, holding four tables:

| Table | One row per | Holds |
| --- | --- | --- |
| `accounts` | account, ever | broker, brokerage, display name, beneficiary, kind |
| `account_snapshots` | account per run | a **numeric** value, its currency, the source's own as-of date, and the text the source printed |
| `holdings` | position per snapshot | fund code or ticker, name, units, price, value, principal, earnings, cost basis |
| `transactions` | movement | processed and traded dates, type, units, price, value |

Two things about that shape are deliberate:

**Money is a number, and the original text is kept beside it.** `daily +/-` is
not a field any broker reports -- it is the difference between two consecutive
snapshots, which needs arithmetic. Keeping `raw_value` as well means a source
that changes its formatting costs you a parse, not the record.

**Sources fill different columns.** A scraped 529 fund table gives a fund code,
principal and earnings; a SnapTrade position gives a ticker and a cost basis; a
pre-aggregated account gives a balance and no positions at all. Every column a
source might not have is nullable, and an account with zero holdings is a fact
about the account rather than a failed scrape.

Browse it from the shell:

```text
show accounts                  the accounts this broker knows
show snapshots [<account id>]  what each was worth, over time
show holdings [<snapshot id>]  the positions behind a snapshot
show transactions [<account>]  recorded movements
show deltas                    the change between consecutive snapshots
export <category> <file>       any of the above, as CSV
```

Google Sheets is a view of this, not the other way round. Each tab is cleared
and rewritten from what the database holds, so what you see there is what
`stonksmithdb` reports.

**Upgrading an existing database.** Databases written before account history
have a single `accounts` table of per-run rows with a text balance. Opening one
migrates it: the old table is renamed to `accounts_legacy_v1` and **kept**, and
every row is replayed as a snapshot with its balance parsed into a number.
Accounts keep the same identity they had, so existing history continues rather
than starting over. It runs once and reports how many rows it moved.

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

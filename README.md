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

- [x] Multi-broker support (Schwab 529, Fidelity, and anything via SnapTrade)
- [x] Automatic data scraping (requests + Playwright)
- [x] Google Sheets sync
- [x] CLI commands for automation
- [x] Credentials stored in the OS keyring
- [ ] More brokers (Vanguard, TSP, Ally, ...)
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
uv run python scripts/snaptrade_register.py users
```

A userId is not issued by SnapTrade — you choose it. `users` lists the ones that
already exist under your key, and flags which have a secret in your keyring. A
userSecret is shown once, at registration, and cannot be read back, so a user
whose secret you do not hold cannot be adopted: register a new one and re-link.

```bash
uv run python scripts/snaptrade_register.py register --user-id <name>
```

That creates a SnapTrade user, writes both secrets to the OS keyring, and prints
the two lines to paste into the `[SNAPTRADE]` section of
`~/.stonksmith/stonksmith.conf`. Then link a brokerage:

```bash
uv run python scripts/snaptrade_register.py link
```

Open the URL it prints — it signs in as you and expires in about five minutes —
and connect Schwab, Fidelity or anything else SnapTrade supports. Check what is
linked at any time with `scripts/snaptrade_register.py status`, which prints
connection health and account names but never balances.

Then sync, after creating a `SnapTrade` tab in the dashboard spreadsheet:

```bash
uv run stonksmith snaptrade -M snaptrade
```

Accounts are skipped, loudly, when they cannot be trusted: a disabled connection
(SnapTrade keeps serving its last cached balance rather than reporting an
error), holdings that have not synced in `--max-age-days` (default 3), closed,
archived or paper accounts, and liabilities such as credit cards. Override with
`--allow-stale` and `--include-liabilities`.

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
        return
    context.log.success(f"Running module for {user}")
```

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

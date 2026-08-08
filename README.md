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
- [ ] Net worth tracking over time
- [ ] Asset allocation breakdown
- [ ] Scheduling (cron / background jobs)

---

## :bricks: Project Structure

```text
StonkSmith/
|--- src/
|    |--- main.py            # CLI entry point
|    |--- etc/               # config, logging, connection, shells, paths,
|    |                       #   records, database, the canonical row shape
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

Not every broker has been run against a real account. **Ally now has** — its
sign-in, holdings parse and database write are verified, and its session was
found not to survive between runs at all, so it needs `--manual-login` every
time. TSP has in part: its parsers, its arithmetic and its price download are
verified against real data, but its database write and its worksheet are not. Green tests say the
code does what it was written to do, which is not the same as saying the site
still looks the way it did when the parser was written.
`docs/live-verification.md` records which claims stand on an observed run and
gives the procedure for the rest.

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

### Ally Invest

**Ally Invest has no login of its own.** ally.com signs you in to Ally *Bank* at
`secure.ally.com`, and the investing site is reached by clicking through from
the bank dashboard — `live.invest.ally.com` is handed a session, it never asks
for one. So there is no way to point StonkSmith at an Ally Invest login page,
and the sign-in is always yours to perform:

```bash
uv run stonksmith ally -M ally --manual-login
```

A browser window opens at `secure.ally.com`. Sign in, **then click through to
your investment account** — StonkSmith is still waiting at the bank dashboard
and will not touch the page until `live.invest.ally.com` loads. It then saves
the session, and reports whether the save succeeded — the intent being that
Ally would remember a device once it had seen one, so later runs could skip the
sign-in until the session expired.

**That last part does not hold, and `--manual-login` is required every run.**
Settled over nine runs against a real account: Ally refuses a restored session
however it is stored. The saved jar is not the problem — it carries `jwt`,
`refreshToken`, `csrf-token`, `tksid` and `Ally-CIAM-Token` — but on the next
run either the investing site or the bank answers `401`, the app calls
`auth/anonymous_invoke`, and the page renders signed out. Firefox with
`storage_state`, Firefox with IndexedDB included, and a persistent Chrome
profile were all tried, and all three were refused.

So Ally cannot run unattended, and no amount of stored state changes that. The
scrape itself is proven — sign-in, holdings, the account rail, the
bank/brokerage split and the database write all work on every one of those
runs. `docs/live-verification.md` has the full evidence.

Ally runs Akamai, Dynatrace and Transmit on that login page, so the same
attach-to-your-own-Chrome path Fidelity documents above applies here, pointed at
the bank:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.stonksmith/playwright/cdp-profile" \
  "https://secure.ally.com/"

uv run stonksmith --verbose ally -M ally --browser cdp
```

Ally shows one account's positions at a time. StonkSmith reads the sidebar as
well as the table, so every investment account gets a balance, but only the
account currently selected gets its holdings — it says so per account when
there is more than one. Select another account in the browser and re-run to
store its positions too. Ally *Bank* deposit accounts appear in the same
sidebar; they are reported as skipped rather than filed under a brokerage.

All of that is built and tested against a signed-in page captured once and
committed redacted as `tests/ally_holdings.html` — one account state, one
investment account, one holding, one deposit account. Reconciling a masked
sidebar number like `...0847` against a full `3LD20847`, and everything that
happens when there is more than one investment account, has never met a real
page. Treat this section as what the code is written to do until a live run
says otherwise.

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

#### When two brokers can reach the same account

SnapTrade covers whole brokerages, so it will happily report an account a
dedicated broker already scrapes — a Schwab-held 529 that `schwab529plan`
covers, or the Fidelity accounts behind the `fidelity` scraper. Both sources
write, into two databases and two tabs. Nothing here adds the tabs together, so
no stored data is wrong; a dashboard total that sums them counts that money
twice and says nothing.

Pick one owner per account. Where SnapTrade is the better source — Fidelity,
which it takes from attended to unattended — simply stop running the other
broker. Where the scraper is better, because it captures more than a balance,
name the account in the `[SNAPTRADE]` section of `~/.stonksmith/stonksmith.conf`:

```ini
[SNAPTRADE]
exclude_accounts =
    Schwab / Ezekiel 529 Plan
```

One `Brokerage / Account` label per line, indented, as the sync prints them.
Case, extra spaces and the spacing around the `/` do not matter, so
`Schwab/Ezekiel 529 Plan` works too. The rest of the punctuation does, and so
does the brokerage half — excluding one brokerage's account never silently
drops another's of the same name. Exclusions are per account rather than per brokerage: only one of five
Schwab accounts overlaps here, and dropping the other four to fix it would be
worse than the double count.

`--exclude 'Brokerage / Account'` does the same for one run and adds to the
config rather than replacing it. The config is the right home for a standing
overlap — a run from cron has nobody to remember the flag. Every excluded
account is reported, like every other skip.

**This setting is permanent, not a workaround.** The reasonable-sounding hope is
that a single reader over all the databases would make it unnecessary — that it
could recognise the duplicate and drop one. It cannot, and the reason is
structural rather than a missing feature. `account_key` is unique *within* one
broker's database and means nothing outside it: the same Schwab-held 529 is
`Schwab - Ezekiel 529 Plan` to SnapTrade and `Ezekiel` to the `schwab529plan`
scraper. Different key, different external id, different display name, and
nothing stored anywhere links the two. Any reader opening both files sees two
unrelated accounts and would total them exactly as two tabs do.

Which broker owns which account is a fact about **your** setup that no amount of
scraped data contains. This config is where you state it, and it stays.

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

### TSP

**The Thrift Savings Plan needs no login at all.** TSP computes a balance the
same way every day — units held times that fund's share price — and it publishes
the share prices as a public file. So the daily path has no credential in it,
nothing to expire, and nothing to re-authorise. A run cannot fail because a
session went stale, which is the failure mode that makes the usual aggregators
give up on this account and show nothing.

```bash
uv run stonksmith tsp -M tsp
```

Units are the half TSP does not publish, because they are the account's own
state. They come from a quarterly statement — or from a balance you read off
the site, see below — and they only move on a transaction:

```bash
uv run stonksmith tsp -M tsp -o STATEMENT=~/Downloads/statement.pdf
```

That reads `Closing Units` straight off the statement and remembers the period
it closed on. Between statements, put the same number in the config once:

```ini
[TSP]
fund = L 2060
units = 302.116
units_as_of = 2026-06-30
```

Those three keys are the whole setup. Unless a run is given prices to read,
it downloads them from tsp.gov itself, so there is nothing else to configure
and nothing to fill in before the first run works. `price_url` exists in the
`[TSP]` section for the day TSP moves that file — leave it blank and the
published URL is used.

`--units` and `--units-as-of` override the config for a single run, and
`--prices` reads a share price file already on disk instead of downloading one
— useful when the machine cannot reach tsp.gov.

That download has been run for real: tsp.gov serves the file to a non-browser
client, but only to one that sends a User-Agent starting `Mozilla/5.0` and
carrying a second `product/version` token, which is what ships. A refusal comes
back as a `403` and is reported as a refusal, pointing at `--prices`; a block
page served with a `200` parses to no rows and is reported as such, rather than
valuing the account at nothing.

**You do not have to wait for a statement.** The TSP site states a balance and
the date it is true for, and never states a unit count — but a balance *is*
units × that day's price, so the division inverts it exactly:

```bash
uv run stonksmith tsp -M tsp --balance 7810.84 --balance-as-of 2026-08-05
```

```text
Balance $7,810.84 on 2026-08-05 at $24.7344 (2026-08-05) = 315.7885 units
Store it: [TSP] units = 315.7885, units_as_of = 2026-08-05
```

So any moment spent logged in is worth a fresh unit count, and the two numbers
on the dashboard are all it takes. The derived count is what belongs in the
config — the balance itself is deliberately not a config key, because it is
true for exactly one day and storing it would leave a value that silently rots.

A balance is converted against the price on or before its date, since TSP does
not revalue on a weekend or a holiday. If the price file is too old to cover
the balance's date, the run says so and refuses rather than dividing by a stale
price and inventing a unit count.

**Every mark says how old its unit count is.** A value carried on a
three-month-old count is still exact arithmetic, but it is missing every
contribution since, and the number itself gives no sign of that. So the run
prints which input supplied the units and what date they were true, and warns
once the count is old enough to have missed a contribution. The error is
bounded by one contribution, it corrects itself at the next statement, and it
is stated rather than hidden — which is the whole reason this broker values the
account instead of refusing to.

Sheets needs a `TSP` tab in the dashboard spreadsheet, created by hand as every
broker's tab is. Without it the run prints `TSP mark saved locally; the
dashboard was not updated.` and still exits 0 — the database write has already
happened, and Sheets is a view of it. That message means the tab is missing,
not that the broker failed.

The statement reader, the price parser and the arithmetic are all verified
against real files, and the mark has been checked against what the site itself
reports. The database write and the worksheet have not been run;
`docs/live-verification.md` has the procedure and one trap worth knowing about
first — a statement's fund is read and logged but not carried into the mark,
so a statement for one fund with another configured values the wrong one.

Manage stored credentials and scraped balances:

```bash
uv run stonksmithdb
```

Inside that shell: `broker schwab529plan`, then `add creds <username>`,
`show creds`, `show accounts`, `export creds <file>`, `delete creds <id>`,
`delete snapshot <id>`, `back`, `exit`.
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
delete snapshot <snapshot id>  remove one wrong mark and its holdings
```

`delete snapshot` is there because a wrong mark does not correct itself. The
next sync writes a row *beside* it, not over it — snapshots record what was
observed when — so a placeholder run verbatim off a command line, or a value
computed from mismatched inputs, stays a data point in every chart until it is
removed. It takes one id at a time, and it leaves the account alone: deleting
that would cascade away the real history and let the next run recreate the
account beside itself.

Google Sheets is a view of this, not the other way round. Each tab is cleared
and rewritten from what the database holds, so what you see there is what
`stonksmithdb` reports. That has a consequence worth stating outright — see
[The sheet is output](#the-sheet-is-output) below.

**Upgrading an existing database.** Databases written before account history
have a single `accounts` table of per-run rows with a text balance. Opening one
migrates it: the old table is renamed to `accounts_legacy_v1` and **kept**, and
every row is replayed as a snapshot with its balance parsed into a number.
Accounts keep the same identity they had, so existing history continues rather
than starting over. It runs once and reports how many rows it moved.

### The sheet is output

**Broker tabs are machine-owned. Nothing hand-written ever lives on one.**

Every saver calls `worksheet.clear()` before it writes. That is correct
behaviour — the tab is a rendering of the database, and a stale row left behind
would be a number that no longer has a source. But it means a note, an
override, a formula or a column you added to a broker tab is gone at the next
sync. Not flagged, not backed up, not recoverable: the sync had no idea it was
there, so it reports success, because from its side nothing went wrong.

This is written down rather than left as a convention because that is the worst
shape a failure can take — silent, total, and indistinguishable from things
working.

So: the five broker tabs (`Fidelity`, `SnapTrade`, `TSP`, `Ally`, `529 Plan`)
are output. They are allowed to stay ugly. Anything you want to keep — your own
notes, targets, allocations, a chart, arithmetic of your own — goes on a tab
StonkSmith never opens, and pulls what it needs across with a formula. A tab is
only ever touched if some broker names it, so any tab you invent is safe.

### What a tab may promise

Those five tabs each grew their own layout, and nothing shared a column:
`Balance` in one tab and `Value` in another named the same thing, while
`Synced`, `Price date` and `Units as of` were three answers to one question. A
formula pointing at `SnapTrade!D:D` broke the day a column moved.

`src/etc/portfolio.py` settles that. It reads every broker database in the
workspace and produces two row shapes, shared across all brokers:

**Accounts** — one row per account. Summing `Value` gives the portfolio total.

| # | Column | |
| --- | --- | --- |
| 1 | `Broker` | which StonkSmith broker produced it |
| 2 | `Source` | the brokerage behind it, for an aggregator; the broker otherwise |
| 3 | `Account` | the display name — free to change, and not identity |
| 4 | `Account Key` | the stable identity. Key formulas on this |
| 5 | `Kind` | `529`, `INVESTMENT`, `LOC`, whatever the source calls it |
| 6 | `Beneficiary` | 529 plans have one; most accounts do not |
| 7 | `Value` | |
| 8 | `Currency` | |
| 9 | `As Of` | the date **the source** says the value is for |
| 10 | `Scraped At` | when the run happened |

**Holdings** — one row per position behind each account's newest snapshot. The
first four columns are the same, so the two join on `Broker` + `Account Key`.

| # | Column | |
| --- | --- | --- |
| 1-4 | `Broker`, `Source`, `Account`, `Account Key` | as above |
| 5 | `Symbol` | the ticker, or the fund code for sources without tickers |
| 6 | `Name` | |
| 7-10 | `Units`, `Price`, `Value`, `Cost Basis` | |
| 11-12 | `Principal`, `Earnings` | 529 plans report growth separately |
| 13-15 | `Currency`, `As Of`, `Scraped At` | |

Three rules make that a contract rather than a list:

- **Columns are append-only.** A new one goes on the end, never in the middle.
  Everything reading these addresses a column by position, so inserting one
  silently repoints every formula at its neighbour. A test pins both tuples
  exactly, so that change fails in CI instead of in your spreadsheet.
- **One name per meaning.** `Value` is what things are worth, everywhere.
  `As Of` is the source's own date and `Scraped At` is when the run happened —
  two different facts, and a source that never says the first is common.
- **Money and quantities are numbers, not text.** No `"$1,234.56"` in a cell
  you then cannot add up. Formatting is the cell's job. A value the source never
  gave stays empty rather than becoming `0`, because an account that reported no
  number is not an account worth nothing.

**Two shapes rather than one flat table**, because an account's value and the
sum of its positions are different numbers — uninvested cash sits in the balance
and in no holding. One table doing both would understate every account holding
cash while looking like it totalled correctly.

Nothing writes these to the sheet yet; the shape is settled first, because
formatting is cheap to redo and a column contract is not.

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

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
|    |                       #   and the one thing that writes it to a sheet
|    |--- brokers/           # one package per broker (broker.py + helpers)
|    |--- modules/           # per-broker scrape/sync modules
|    |--- loaders/           # dynamic broker and module loading
|    |--- helpers/           # db, sheets, logging helpers
|--- docs/                # live verification, and what was decided against
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

Not every broker has been run against a real account. **Ally now has** — its
sign-in hand-off, holdings parse, masked-number reconciliation, bank/brokerage
split and database write were all exercised across nine live runs, and its
session was found not to survive between runs at all, so it needs
`--manual-login` every time it scrapes — `--from-prices` values it between
scrapes without one; the published price feed behind that flag has been
contacted, but the flag's own path has not been run. Those runs saw one account
state, though, so anything plural about an Ally account is still inference. TSP
has in part: its statement and share-price parsers, the mark's arithmetic and
its price download are verified against real data, but its database write, the
sheet it feeds, the contribution accrual and everything touching the DFAS pay
table are not. Green tests say the code does what it was written to do, which
is not the same as saying the site still looks the way it did when the parser
was written.
`docs/live-verification.md` records which claims stand on an observed run and
gives the procedure for the rest — it is the record, and this paragraph
summarises it rather than being maintained beside it.

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

**That last part does not hold, and `--manual-login` is required every time Ally
is scraped.**
Settled over nine runs against a real account: Ally refuses a restored session
however it is stored. The saved jar is not the problem — it carries `jwt`,
`refreshToken`, `csrf-token`, `tksid` and `Ally-CIAM-Token` — but on the next
run either the investing site or the bank answers `401`, the app calls
`auth/anonymous_invoke`, and the page renders signed out. Firefox with
`storage_state`, Firefox with IndexedDB included, and a persistent Chrome
profile were all tried, and all three were refused.

So the *scrape* cannot run unattended, and no amount of stored state changes
that. The scrape itself is proven — sign-in, holdings, the account rail, the
bank/brokerage split and the database write all work on every one of those
runs. `docs/live-verification.md` has the full evidence.

**But a daily number does not need a scrape.** Units only change when a deposit
lands, and a published price needs no login — so `--from-prices` multiplies the
units the last signed-in run recorded by today's close, opening no browser and
signing in to nothing:

```bash
uv run stonksmith ally -M ally --from-prices
```

```text
[+] Valuing from published prices; no sign-in needed.
[+] Individual (...0847): 123.519 SWPPX x $19.88 (2026-08-06) = $2,455.56
[*] Individual (...0847): priced at 2026-08-06; units as recorded 2026-08-07 20:40:18. Re-run with --manual-login after a deposit.
```

It reads the units out of the database, not out of config, so **a signed-in run
has to have happened first**. Against an empty database it refuses rather than
valuing the account at nothing:

```text
[-] No holdings on record to value. Run with --manual-login once so a signed-in run can record the units.
```

The mark is dated by the *price*, not by the run — and by the oldest price
across the account, since one fund priced this morning and another not since
Thursday makes a Thursday total. That date lands in `as_of`, which no other Ally
path fills. The units' own age is the half that goes quietly wrong: a deposit
adds units this run cannot see, so the total drifts low and keeps drifting until
somebody signs in again. The run says so on every account, which is what the
second line above is for, and the date it names is the holding's own: a scrape
stamps each position with the moment its units were read, and repricing carries
that stamp through rather than replacing it. So the units' age is a stored fact
that stops where the last sign-in did, not one inferred from the newest snapshot
— which, since these runs write snapshots too, would otherwise report the units
a day old however old they really were.

Two things it does not do. It does not touch the sheet — only a scrape syncs, so
`stonksmithdb`'s `sheet` command is what refreshes the tabs afterwards. And it
does not notice new accounts, since it values what is already on record.

#### What an Ally run writes down

Every Ally run that opens a browser leaves a response log in
`~/.stonksmith/logs/`:

```text
[*] Recorded 25 data call(s) and 1 refusal(s) to ~/.stonksmith/logs/ally-data-calls-20260809-041200.log
```

```text
401 https://live.invest.ally.com/api/session/checkSession (49 bytes) {keys: redirectUrl}
```

**That line is real. The next one is not** — it is the shape the open question
turns on, written out so it can be recognised if it ever appears:

```text
200 https://live.invest.ally.com/api/account/<id>/activity ?endDate&jwt&pageSize&startDate (18422 bytes)
```

**No activity endpoint has ever been observed.** Five endpoints have, across
every run so far, and all five are session, auth and account-roster plumbing. So
that second line illustrates the format rather than evidencing a feed — which
matters, because "a log shows an activity endpoint" is the first of the three
conditions that would reopen the question of Ally transactions, and this page's
own example must not be mistakable for the thing that fires it.

**Endpoints and parameter *names*; never values, bodies or headers.** A route
called `activity` says nothing on its own. The same route taking `startDate` and
`endDate` says it is a windowed history feed — which is the question worth
answering, and answering it costs nothing, because a parameter name is a fact
about the endpoint while its value is a fact about you. Long path segments stay
masked as `<id>` and query values never appear, so the lines paste into an issue
as they are.

It used to record only on failure, and only when *not* attached — so the
`--browser cdp` path recommended above wrote nothing at all, and a run that
worked threw away everything it had seen. One live session was observed making
twenty-five successful data calls and all that survives of it is the number.
Now it is armed before either path and written on every exit, including the ones
that end by raising or by giving up at the sign-in.

This is what makes Ally's unanswered questions answerable without a dedicated
investigation: whether an activity endpoint exists, whether it takes a date
range, and whether it is per-account are all readable off an ordinary run you
were doing anyway.

**Whether Ally gets a transactions producer is a decision, and it has been
made.** Not now: no aggregator covers Ally Invest, no activity endpoint has ever
been seen, a fetch would need a human sign-in every time, and the one job it
would do — telling you the stored units went stale — costs the sign-in that
would have refreshed them. `docs/ally-transactions.md` has the reasoning and the
three things that would reopen it. This log is the first of them.

**Ally is the only broker that records.** Saving is generic — it happens in
`BrowserConnection.teardown()`, so nothing has to remember it — but a connection
writes a log only if it armed the recorder first, and Ally is the only one that
does. Fidelity opens a browser and leaves no log. That is a one-line call away
should Fidelity ever need the same treatment, and it is deliberately not made
until it does: recording is only worth its clutter where there is a question
outstanding.

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

All of that has met a real page. The parse, the account rail, the reconciliation
of a masked sidebar number like `...0847` against a full `3LD20847`, and the
bank/brokerage split were each exercised on every one of those nine runs. But
they were nine runs against **one account state** — one investment account, one
holding, one deposit account — and `tests/ally_holdings.html`, the signed-in page
captured once and committed redacted, is a redaction of that same state rather
than a second one. So everything that happens when there is more than one
investment account is still what the code is written to do rather than what it
has been seen to do. `docs/live-verification.md` says which is which.

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
database and **no** worksheet tab. One `snaptrade` broker, one `snaptrade.db`;
on the sheet the `Source` column tells them apart. Anything SnapTrade covers is
an operator action rather than a code change.

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

Then sync:

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
write, into two databases and onto the `Accounts` tab twice. No stored data is
wrong — but the tab now has a total on it, and that total counts the money twice
and says nothing.

That is materially worse than it was. The two brokers used to write separate
tabs, so double-counting took a deliberate act of addition. One `Accounts` tab
adds them by default, which moves `exclude_accounts` from advisable to
necessary.

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

**Or close the gap, if you are in uniform.** The missing contributions are not
unknowable: DFAS publishes basic pay per pay grade and time in service, so a
grade, a service date and two percentages are enough to say what each month
since the last statement bought. Four more optional keys:

```ini
[TSP]
rank = E-7
basd = 2016-03-14
member_contribution = 5
agency_contribution = 5
```

`rank` is the pay grade, not the title — `E-7`, `O-3`, `W-2`, or `O-3E` for an
officer with over four years of enlisted or warrant service. `basd` is the Basic
Active Service Date, and time in service is counted from it *to the day*, which
matters because the pay bands are crossed on an anniversary and a member who
crosses one mid-quarter is paid at two rates over it. Both percentages are of
monthly basic pay. Fill in all four or none.

```text
E-7 at Over 10: $5,300.40 basic pay per month
  2026-04-30: E-7 Over 10 $5,300.40 x 10% = $530.04 at $23.1290 (2026-04-30) = 22.916685 units
  2026-05-31: E-7 Over 10 $5,300.40 x 10% = $530.04 at $24.2845 (2026-05-29) = 21.826268 units
  2026-06-30: E-7 Over 10 $5,300.40 x 10% = $530.04 at $24.2990 (2026-06-30) = 21.813243 units
  2026-07-31: E-7 Over 10 $5,300.40 x 10% = $530.04 at $24.0756 (2026-07-31) = 22.015651 units
Contributions since 2026-03-31: 4 month(s), $2,120.16 at 5% member + 5% agency = 88.571847 estimated units
L 2060: 315.7885 anchored + 88.571847 estimated = 404.360347 units x $24.7344 (2026-08-05) = $10,001.61
```

Each month is priced on its own posting date — the last day of the month unless
`contribution_day` says otherwise — against the published price on or before it,
because TSP does not revalue on a weekend. The run prints its working so the
figures can be checked against a pay table and an LES, and the estimate is
stored as **its own holding**, so "how much of this is a guess" is answerable
from the database and the dashboard rather than only from a log line.

Each of the two rows carries its own `Units As Of`: the anchored one is dated to
the statement, the estimate to the last contribution it could price. They are
different facts about different days, and before that column existed there was
nowhere to say so.

It is an estimate, and it is bounded in the same way the stale count was. It
assumes contributions come out of basic pay alone — not special, incentive or
bonus pay — and it does not know about the IRS elective deferral limit, so a
member who reaches the annual cap will be over-accrued until the next statement
resets the anchor. `--no-accrual` values the anchored count on its own for a run
that must be exact arithmetic with no estimate in it.

Anything that stops an estimate being made costs the estimate and not the run:
a half-filled config, a rank that is not a pay grade, an unreadable service
date, a grade DFAS publishes no rate for, or a refused download all report
themselves and leave the anchored mark exactly as it was. The pay table is
cached under `~/.stonksmith` for the rest of the year, since DFAS changes it
every January. `--pay-table` reads a page saved by hand, the way `--prices`
does. Unlike the share price download, **this one has not been run against
dfas.mil for real** — see `docs/live-verification.md`.

Sheets needs no tab prepared: StonkSmith creates `Accounts`, `Holdings`,
`Transactions` and `Dashboard` itself on the first sync. If the sheet cannot be written at all — no
spreadsheet, no authorization, or a tab that turns out not to be StonkSmith's —
the run prints `TSP mark saved locally; the dashboard was not updated.` and still
exits 0, because the database write has already happened and Sheets is a view of
it. That message is about the sheet, not about the broker.

The statement reader, the price parser and the arithmetic are all verified
against real files, and the mark has been checked against what the site itself
reports. The database write and the sheet have not been run;
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
| `holdings` | position per snapshot | fund code or ticker, name, units, price, value, principal, earnings, cost basis, and the unit count's own as-of date where a source dates its quantity apart from its value |
| `transactions` | movement | processed and traded dates, type, symbol, description, units, price, value, currency, the source's own id where it has one, when StonkSmith first saw it, the key it is deduplicated on, and the value's original text |

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
export <category> <file>       any of the above, as CSV — all of it
delete snapshot <snapshot id>  remove one wrong mark and its holdings
```

**`show` is a screenful; `export` is the whole table.** `show` prints the newest
hundred snapshots or five hundred movements and then says so, naming `export` —
printing fifty thousand rows into a terminal helps nobody, but a table that
stops without mentioning it is a different problem. `export` takes no limit at
all and reports how many rows it wrote:

```
schwab529plan > export transactions ~/tx.csv
[+] Exported 2043 transactions to ~/tx.csv
```

That count is not decoration. A CSV that stopped early looks exactly like a
complete one, and nothing reading it afterwards can tell — which is the same
failure the `Transactions` tab exists to avoid, in a file instead of a tab.

**It is fewer columns as well as fewer rows.** `show transactions` leaves out
three of them and says which three and where to get them. Everything else the
`Transactions` tab shows, `show` shows too, and `export` writes all fifteen:

```
schwab529plan > show transactions
[!] Description, Natural Key, Raw Value are too wide for a terminal and not
    shown; 'export transactions <file>' includes them.
```

All three are dropped for width, and nothing here truncates a cell: `Description`
is free text a source wrote and can be a whole sentence, `Natural Key` is a whole
row's text pipe-joined, and `Raw Value` is whatever the source printed.

**The last two are also the two the `Transactions` tab does not have**, and that
is deliberate in both places. `Natural Key` is the key a movement is
deduplicated on and `Raw Value` is the value's text before anything parsed it;
together they are how you tell a row that is genuinely new from one whose key
moved because a source changed its date format. That is a debugging question, so
it belongs in a CSV you pulled to answer it and not on a tab you read your
portfolio from. The key is stored as legible text rather than as a hash for
exactly this, and that choice only pays for itself if something can show it to
you.

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

It is a floor rather than a ceiling: every column a tab shows has to be reachable
from `stonksmithdb`, and `stonksmithdb` may carry columns no tab wants. The two
above are the whole of that today. The shell is where you go to ask why the
database holds what it holds; the sheet is where you go to read what it holds.

**Upgrading an existing database.** Databases written before account history
have a single `accounts` table of per-run rows with a text balance. Opening one
migrates it: the old table is renamed to `accounts_legacy_v1` and **kept**, and
every row is replayed as a snapshot with its balance parsed into a number.
Accounts keep the same identity they had, so existing history continues rather
than starting over. It runs once and reports how many rows it moved.

A second migration adds `holdings.units_as_of` to a database written before that
column existed, and moves TSP's unit dates into it from `holdings.raw_value`,
where they used to ride. Both halves happen in one transaction, so a database is
never left with the column and without the dates. The original text is kept
rather than cleared, on the same principle as the renamed table above, and a
value that does not read as a date — which is what `raw_value` holds for every
broker other than TSP — is left exactly where it is. It reports only when it
actually moved something.

Adding the column is not optional on the writing side: a snapshot write names
every column it has, so a database that missed the migration would fail its next
sync outright rather than quietly storing less.

### The sheet is output

**StonkSmith owns five tabs, and refuses to touch anything else.**

The five are `Accounts`, `Holdings`, `Transactions`, `Net Worth` and
`Dashboard`. They are
created on the first sync if they are not there — you no longer add tabs by
hand — and each is cleared and rewritten in full every run. A note, an override, a formula or a
column you add to one of them is gone at the next sync.

That used to be a convention, which is not what stops a sync from clearing a tab
you kept notes on. It is now a refusal. The first cell of each tab carries a
banner saying what the tab is, and **before clearing, StonkSmith reads that cell
back.** A tab that carries the banner is its own. A tab that is empty is adopted.
A tab with anything else on it is refused by name and nothing is written:

```
[-] Google Sheets sync skipped: Tab 'Holdings' holds something StonkSmith did
    not write, so it was left untouched and nothing was synced. StonkSmith
    rewrites this tab from scratch every run and would have lost whatever is on
    it. Move your work to a tab of your own, empty this one to hand it over, or
    delete it and let the next sync recreate it.
```

The run still exits 0. The scrape is already in the database by the time the
sheet is written, so a refusal is a report and not a failure — the same as Sheets
being unreachable.

The check is deliberately not just "is the first cell blank". Every tab
StonkSmith used to write left the first cell blank and started its headers on row
2, so a blank first cell is exactly the shape a leftover layout has — and exactly
the shape your own tab has if you started below the top row. When the first cell
does not carry the banner, the whole tab is read before anything is decided. That
costs one extra request, on the first sync of a tab and no other.

So: anything you want to keep — notes, targets, allocations, a chart, arithmetic
of your own — goes on a tab of your own, and pulls what it needs across with a
formula. Only those five names are ever opened, so any other tab is safe, and
one you name `Accounts` by accident is refused rather than eaten.

**Formatting survives.** `clear()` empties values, not number formats. Format the
`Value` column as currency once and every sync keeps it.

**A sync is workspace-wide.** Running one broker rewrites every broker's rows,
because every tab is rendered from every database in the workspace rather
than from the run that happened to trigger them. Reading a database also applies
any pending migrations to it, so syncing one broker upgrades the rest — see
[Upgrading an existing database](#what-is-stored) above.

#### The five old tabs

`Fidelity`, `SnapTrade`, `TSP`, `Ally` and `529 Plan` are no longer written or
read. They are frozen at whatever the last sync left on them.

StonkSmith will not delete them, on principle: it does not touch tabs it did not
write this way, and a change that opened by deleting five tabs would break that
promise on its first day. Delete them yourself once you have moved anything off
them you want.

One thing left the sheet with them and has since come back. **529 transactions
went**, because the row contract had two shapes, accounts and holdings, and no
transaction shape — and inventing one on the way out would have repeated the
mistake the contract was written to fix. So the shape was argued about on its
own and written on its own, and `Transactions` is now the third of them,
carrying every broker's movements rather than one tab's block.

Restoring the block would have been the smaller change and the wrong one, for a
reason worth stating: the reader it would have been built on stops at five
hundred rows. `get_transactions()` takes a `limit` because it backs a shell
command a human is scrolling, and a tab rendered from it would have shown the
newest five hundred movements and said nothing about the rest — a number that
looks complete with the missing part invisible, on a tab whose whole purpose is
history. The unlimited read came first, and the tab came after it.

Ally's `Total G/L` and `Today's G/L` went too, and stayed gone: they were never
stored, so losing them from the sheet is just what "the sheet is a view of the
database" means.

TSP's `Units as of` was the other one, and it came back — as `Units As Of`,
column 16, backed by a `holdings.units_as_of` of its own. It went in the first
place because it *was* stored, only in `holdings.raw_value`, which means "the
value exactly as the source wrote it" for every other broker. That was two
meanings in one column, and a column nothing read back, so the date was kept and
invisible at the same time. The contrast with the Ally columns is the point: a
fact the database does not hold cannot earn a column, and one it does hold
eventually will.

#### Refreshing without scraping

```
$ uv run stonksmithdb
stonksmithdb (default) > sheet
[*] Refreshed: 6 accounts, 23 holdings, 412 movements from ally, fidelity, snaptrade, tsp.
```

Rebuilds all five tabs from the current workspace's databases, with no login
anywhere. This is what to reach for after a refused tab or a "the dashboard was
not updated" line: the sheet is a view of the databases, so it can be rebuilt
from them alone, and re-scraping Ally or Fidelity to fix a spreadsheet means
sitting at a sign-in page for no reason.

### What a tab may promise

Those five tabs each grew their own layout, and nothing shared a column:
`Balance` in one tab and `Value` in another named the same thing, while
`Synced`, `Price date` and `Units as of` were three answers to one question. A
formula pointing at `SnapTrade!D:D` broke the day a column moved.

`src/etc/portfolio.py` settles that. It reads every broker database in the
workspace and produces four row shapes, shared across all brokers:

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
| 13-15 | `Currency`, `As Of`, `Scraped At` | `As Of` is the account's — when the position's *value* is true |
| 16 | `Units As Of` | when the *unit count* was true, for a source that dates the two apart |

**Transactions** — one row per movement, across every broker. Not per snapshot:
a movement is recorded once, keyed so a re-scrape of an overlapping window
contributes only what is new, and kept. Same first four columns again.

| # | Column | |
| --- | --- | --- |
| 1-4 | `Broker`, `Source`, `Account`, `Account Key` | as above |
| 5 | `Type` | `Contribution`, `BUY`, `DIVIDEND` — whatever the source calls it |
| 6-7 | `Symbol`, `Description` | filled by sources that have them; a scraped 529 table has neither |
| 8-11 | `Units`, `Price`, `Value`, `Currency` | |
| 12 | `Processed On` | the settlement date |
| 13 | `Traded On` | the trade date — a different fact, routinely days apart |
| 14 | `First Seen` | when StonkSmith first observed this movement |
| 15 | `External Id` | the source's own transaction id, where it has one |

**This tab carries the whole history, deliberately.** Every other tab is bounded
by the size of your portfolio; this one grows forever, which is exactly why it
is written in full rather than windowed. A tab whose purpose is history, showing
the newest few hundred rows with nothing saying so, would be worse than not
having one. The read behind it takes no `limit` for that reason, and
`stonksmithdb`'s `sheet` line reports the count so a short write is visible.

**Net Worth** — one row per account per date, which is what a chart of your net
worth over time is made of. Same first four columns again.

| # | Column | |
| --- | --- | --- |
| 1-4 | `Broker`, `Source`, `Account`, `Account Key` | as above |
| 5 | `Date` | the date this row stands on — not a claim by any source |
| 6-7 | `Value`, `Currency` | |
| 8 | `Basis` | `observed` if the value was read on that date, `carried` if it was carried onto it |
| 9 | `Observed On` | the date the value *was* read for. Equal to `Date` when observed |
| 10 | `As Of` | what the source itself said, blank when it said nothing |
| 11 | `Scraped At` | the run that took that reading |

#### Why this tab has to be constructed rather than read

The other three tabs each render what some source said. This one renders what
your portfolio was worth on a date, and no source ever says that — because
**your brokers do not scrape on the same day.** Ally needs a manual sign-in and
may go a week. TSP runs unattended. SnapTrade runs whenever you run it.

So the obvious construction is wrong. Group the stored snapshots by date and
total them, and a date on which only TSP ran holds only TSP's money. Chart it
and you get a portfolio that repeatedly collapses and recovers — every number in
it real, the shape of it fiction, and nothing about it looking like a bug.

Instead each account's last known value is carried forward onto every later
date, so every point totals the same set of accounts. That is the honest
construction, and it is also partly made up, which is why three things are true
of it:

- **A carried value says it was carried.** `Basis` is `observed` or `carried` on
  every row, and `Observed On` says how far back the carry reached. This is the
  same argument `As Of` and `Scraped At` already settle: a point that is nine
  parts observed and one part carried forward is not the same fact as one where
  everything was read that day, and a chart rendering them identically asserts a
  precision it does not have. The dashboard's net worth band totals the two
  separately for exactly that reason — stack them and you can see how much of
  each point is a reading.
- **A carry does not reach forever.** Past **30 days** an account drops out of
  the series rather than persisting at a stale value. Crossing a weekend is not
  crossing a quarter. Thirty rather than the dashboard's seven-day staleness
  threshold, deliberately: seven is right for "should a human look at this" and
  wrong for "may this still be counted", because Ally routinely goes longer than
  a week and a seven-day horizon would drop a live account and restore it a run
  later — reintroducing the collapse as the fix for it.
- **An account that did not exist yet is absent, not zero.** No row is emitted
  for a date before that account's first reading. Zero and absent are different,
  and an account opened in March did not spend February being worth nothing.

A snapshot the source gave no number for is not a reading either: it cannot be
carried, and it does not reset a carry that is already running, so the account
keeps the last number anything actually knew. And the dates on this tab are the
ones something was actually read on — not every day on the calendar. A point
exists because a broker ran, so the tab grows with the number of runs rather
than with the passage of time, and nothing here invents a date any more than it
invents a value.

**This tab grows forever too**, for both of `Transactions`' reasons and one of
its own: a series whose oldest points have silently fallen off the end is a
chart of a shorter history than the one you have.

Three rules make that a contract rather than a list:

- **Columns are append-only.** A new one goes on the end, never in the middle.
  Everything reading these addresses a column by position, so inserting one
  silently repoints every formula at its neighbour. A test pins all four tuples
  exactly, so that change fails in CI instead of in your spreadsheet.
- **One name per meaning.** `Value` is what things are worth, everywhere.
  `As Of` is the source's own date and `Scraped At` is when the run happened —
  two different facts, and a source that never says the first is common.

  `Units As Of` reads like a fourth answer to that question and is not. `Synced`
  and `Price date` were other brokers' *names* for the fact `As Of` already
  carries, so they stay abolished. A TSP position is a quarterly unit count times
  today's share price: its value is as of one date and its quantity as of
  another, weeks apart, and no single column can say both. Two meanings, so two
  names — which is the rule rather than an exception to it.

  A movement's two dates are the same argument one view along. `Processed On`
  and `Traded On` are settlement and trade, and neither is "the date the source
  says the *value* is for", so neither borrows `As Of`. `First Seen` is its own
  name for the same reason rather than a third `Scraped At`: that one moves
  every sync, because those rows are rewritten every run, while the run that
  first saw a movement never changes.

  The series makes the same distinction a third time, and needs three columns to
  do it. `Date` is the date a row stands on, which on a carried row is a date the
  source said nothing whatever about — it belongs to whichever *other* broker ran
  that day. `Observed On` is the date the value was actually read for. `As Of` is
  still what the source itself claimed, and stays blank when it claimed nothing,
  which is how you tell `Observed On` falling back to the run clock from
  `Observed On` repeating a real source date. And `Basis` is not `Cost Basis`
  with a word dropped: one is what was paid for a position, the other is whether
  a number is a reading or a carry. Neither name appears in the other's tuple.
- **Money and quantities are numbers, not text.** No `"$1,234.56"` in a cell
  you then cannot add up. Formatting is the cell's job. A value the source never
  gave stays empty rather than becoming `0`, because an account that reported no
  number is not an account worth nothing.

**Separate shapes rather than one flat table**, because an account's value and
the sum of its positions are different numbers — uninvested cash sits in the
balance and in no holding. One table doing both would understate every account
holding cash while looking like it totalled correctly. Movements are the third
because they are a *log* rather than current state: the other two are "what is
true now" and are replaced every run, while a movement happened once and stays.
The series is the fourth because it is neither — it is the only one of them no
source ever stated, assembled across brokers that do not report together.

**Dates on the transactions tab are normalized on the way out, not on the way
in.** SnapTrade reports ISO; the 529 scraper's table says `12/30/2025`, and that
text is what its deduplication key is built from — so rewriting it at the
scraper would make every already-stored row look new. Two formats in one column
sort wrong, `12/30/2025` landing above `01/15/2026`, which is a tab that looks
ordered and is not. So the stored text stays exactly as the source wrote it and
the *view* renders `YYYY-MM-DD`. A date nothing can parse is passed through
unchanged rather than blanked.

**A movement the source gives no id is keyed on its own content**, and identical
rows in one window are numbered so that two genuine $50 contributions on one day
stay two rows rather than collapsing into one. The numbering counts content
rather than position, so a window that comes back reversed or newest-first
stores exactly what an in-order one would — sorting it first would buy nothing
and would shift every key already written.

What it does need is that a same-content group arrives *whole* in one window.
Fetched one per window, the second $50 contribution is byte-identical to a
re-scrape of the first, and gets skipped. Nothing keyed on content alone can
separate those two cases, so the rule is to never duplicate and the split window
is what that costs. Both current sources fetch a date window whole and the key
carries both dates, so a same-day group cannot straddle one; a paginated source
that could cut through the middle of one is where a real id stops being optional.
SnapTrade already supplies one, which is why only the 529 scraper's rows are
keyed this way at all.

`src/etc/portfolio_sheet.py` is the only thing that writes them: one read of the
workspace, one authorization, four tabs. Values go up raw, so a number arrives
as a number — and so an account whose display name begins with `=` stays a name
instead of becoming a formula the spreadsheet runs.

#### What the dashboard shows

`Dashboard` is formulas over `Accounts!`, `Holdings!` and `Transactions!` ranges
rather than a fourth copy of the data. That is where the append-only rule stops being a slogan:
a formula addresses a column by its position, so a column added at the end costs
nothing and a column inserted in the middle would repoint every one of them at
its neighbour. None of them contains a typed column letter — every reference is
derived from the tuples above, so the letters cannot drift away from the contract.

- **Total (USD)**, summed on the `Currency` column rather than over every `Value`.
  `Portfolio.total()` refuses to add a dollar to a euro; the sheet must not do
  quietly what the code declines to do loudly. **Other currencies present** names
  whatever the total therefore left out.
- **Total as read**, the same number computed in Python over the databases,
  sitting beside the one Sheets computed over the cells. They disagree only if
  the write was truncated or a row failed to land, which is otherwise invisible.
- **Accounts** and **Holdings**, counted on `Account Key` rather than `Account`:
  the key is never blank, a display name can be.
- **Holdings total** and **In accounts, not in positions** — the second is the
  money sitting in a balance and in no position, which is the whole reason there
  are two row shapes. A negative number there means something is double-counted.
- **Newest** and **oldest scrape**, and a **staleness** table of accounts whose
  `As Of` is missing or more than a week old. A number with no as-of date lies to
  you; this is where it says so.
- **Movements**, counted the same way, and **Newest movement** — the latest
  `Processed On` anywhere in the workspace. Both are sorted as text rather than
  `MAX`ed, which works only because the view normalizes those dates to ISO on
  the way out of the database; see above for why they are not normalized on the
  way in.
- Subtotals **by broker** and **by source**.
- **Not read** — one row per database that would not open, with the reason. A
  total short by a whole broker looks perfectly reasonable, so it is stated on the
  same tab as the total rather than only in the run's output.

If every database fails to read, nothing is written at all. Clearing the tabs
there would replace a correct sheet with a blank one and report success for it.

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

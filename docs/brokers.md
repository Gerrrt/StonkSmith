# Brokers

What each of the five brokers needs from you, and what a run of it does.

**This is a reference chapter, not a record.** It describes how the brokers work
today and changes whenever they do. The three files beside it are records — they
settle a question once and are cited rather than restated:
[`live-verification.md`](live-verification.md) for which of the claims below a
live run has actually settled, [`scheduling.md`](scheduling.md) for what each
broker can do unattended, and
[`ally-transactions.md`](ally-transactions.md) for why Ally stores no
transactions. Where this file summarises one of them, it says so and links.

The *Brokers* table in [the README](../README.md#brokers) is the index
into this file, and
[*Project structure*](../README.md#project-structure) there explains the
three shapes a broker comes in — scraper, browser-backed, API-backed — and which
base class each one gets.

---

## Fidelity

> [!WARNING]
> **The `fidelity` broker is deprecated and will be removed in StonkSmith 1.0.**
> Link Fidelity through [SnapTrade](#snaptrade) instead — one API key, no browser,
> no bot detection, and it runs unattended, which this never has.
>
> It still works and every run prints a notice saying this. But it was never once
> run against the real site: all five of its claims in
> [`live-verification.md`](live-verification.md) were withdrawn on 2026-08-17
> rather than settled, because a broker nobody should use is not worth the sitting
> it would take to verify. Everything below is the state of the code, not
> something anyone has watched work lately.
>
> Already using it? Link Fidelity through SnapTrade, stop running `fidelity`, and
> move its database out of the workspace — the accounts are otherwise counted
> twice. See [*When two brokers can reach the same
> account*](#when-two-brokers-can-reach-the-same-account).

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

## Other browser modes

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

## Ally Invest

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
runs. [`live-verification.md`](live-verification.md) has the full evidence.

**But a daily number does not need a scrape.** Units only change when a deposit
lands, and a published price needs no login — so `--from-prices` multiplies the
units the last signed-in run recorded by today's close, opening no browser and
signing in to nothing:

```bash
uv run stonksmith ally -M ally --from-prices
```

```text
[+] Valuing from published prices; no sign-in needed.
[+] Individual (...1234): 125.000 SWPPX x $19.88 (2026-08-06) = $2,485.00
[*] Individual (...1234): priced at 2026-08-06; units as recorded 2026-08-07 20:40:18. Re-run with --manual-login after a deposit.
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

This is the Ally path a schedule can run, and the only one — see *Scheduling*
above, and [`scheduling.md`](scheduling.md) for what it means to run it nightly.

### What an Ally run writes down

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
would have refreshed them. [`ally-transactions.md`](ally-transactions.md) has the reasoning and the
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
of a masked sidebar number like `...1234` against a full `3LD21234`, and the
bank/brokerage split were each exercised on every one of those nine runs. But
they were nine runs against **one account state** — one investment account, one
holding, one deposit account — and `tests/ally_holdings.html`, the signed-in page
captured once and committed redacted, is a redaction of that same state rather
than a second one. So everything that happens when there is more than one
investment account is still what the code is written to do rather than what it
has been seen to do. [`live-verification.md`](live-verification.md) says which is which.

## SnapTrade

SnapTrade is an aggregator: link a brokerage once through its Connection Portal
and StonkSmith reads every linked account through a single key, with no browser
and no stored password. One `snaptrade` broker covers all of them.

### An account is its positions plus its cash

**Not the balance SnapTrade reports for it**, and that is a correction rather
than a preference. Two facts drove it, both measured against the live API on
2026-08-14.

**The reported total is a day stale.** Balances arrive with the account listing,
from `list_user_accounts` — which SnapTrade's own documentation describes as
serving *"Daily data regardless of the customer's plan… cached and refreshed once
a day"*, and points elsewhere for real-time. The consequence turned out to be
exact rather than approximate: the live balance for one IRA read `5000.00` and
for another `900.00`, and those were precisely the position values StonkSmith had
recorded for them the day before, to the cent. Every balance in the workspace was
one sync behind. The *delta* survived that untouched, since both ends shifted
together, but the level did not — and the Net Worth series is built on levels.

**Positions are not the whole account either.** `get_all_account_positions`
returns securities and never mentions cash, which is routinely negative. One
brokerage account here holds $3,500.00 of a single fund against cash of
**-$800.00**, left by an overdraft transfer out to a checking account. SnapTrade's
own total says $2,700.00; summing its positions says $3,500.00. Both endpoints are
correct and neither is the account.

So the sync fetches `get_user_account_balance` per account and stores positions
plus cash. That reconciles exactly with what SnapTrade's total eventually says,
and it is live on both halves.

Three cases fall back to the reported total, and each is one where computing the
value would be *wrong* rather than merely unavailable:

- **The positions fetch failed.** A failure and an empty account look identical
  afterwards, which is why the fetch reports whether it read as well as what —
  computing from an unread list prices a brokerage account at its cash alone.
- **The account reports no positions at all.** A brokerage that pre-aggregates,
  such as a Schwab-held 529, gives a balance and nothing to sum.
- **Cash could not be read.** The securities alone omit a margin loan, which
  overstates the account by the size of the debt.

`tests/test_snaptrade_account_value.py` pins all six cases.

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

### Adding a second brokerage

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

### When two brokers can reach the same account

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
    Schwab / Beneficiary A 529 Plan
```

One `Brokerage / Account` label per line, indented, as the sync prints them.
Case, extra spaces and the spacing around the `/` do not matter, so
`Schwab/Beneficiary A 529 Plan` works too. The rest of the punctuation does,
and so does the brokerage half — excluding one brokerage's account never
silently drops another's of the same name. Exclusions are per account rather
than per brokerage: only one of five Schwab accounts overlaps here, and
dropping the other four to fix it would be worse than the double count.

`--exclude 'Brokerage / Account'` does the same for one run and adds to the
config rather than replacing it. The config is the right home for a standing
overlap — a run from cron has nobody to remember the flag. Every excluded
account is reported, like every other skip.

### Neither remedy touches what is already on disk

**Both of the above stop a broker *writing*. Neither removes a row it has
already written, and the sheet renders rows rather than runs.**
`load_workspace()` ends in `read_databases(sorted(directory.glob("*.db")))`, so
every database in the workspace is read every time, whether or not its broker
has run this year. There is no exclusion at that layer at all — the one in
config is a filter inside the SnapTrade sync.

So both halves of the advice above have a second step:

- **Stopping the scraper freezes its accounts, it does not retire them.** They
  keep appearing on the `Accounts` tab at whatever they were last worth, and
  keep being added into the total, indefinitely. Because nothing refreshes them
  they also stop having a defensible `As Of`, which is what makes
  `stonksmithdb stale` the place this shows up first.
- **`exclude_accounts` is not retroactive.** An account SnapTrade synced before
  the line was added keeps the rows from those runs. The exclusion is honoured
  from then on, which reads exactly like the problem being solved while the old
  rows go on being counted. `delete account <id>` is the second half of that,
  and the order matters — see below.

Retiring a broker properly means taking its database out of the workspace. Move
it rather than deleting it — it is the only copy of that history:

```bash
mkdir -p ~/.stonksmith/retired
mv ~/.stonksmith/workspaces/default/fidelity.db ~/.stonksmith/retired/
uv run stonksmithdb sheet && uv run stonksmithdb stale
```

Check first what only that database holds. A scraper often reached accounts the
aggregator does not — closed ones, or ones outside its coverage — and moving the
file drops those too. `stonksmithdb`, `broker <name>`, `show accounts` is the
list to read before deciding.

### The database comes back, and that is not the move failing

The very next command says so, which is alarming in the moment and worth
knowing in advance:

```text
    [!] Initializing FIDELITY database
[*] Refreshed: 12 accounts, 10 holdings, 11 movements from ally, fidelity, schwab529plan, snaptrade, tsp.
```

`initialize_db()` creates an empty database for every broker that ships a
`database.py`, so those files exist again after the next `stonksmithdb` run.
**Nothing is restored with them.** The file is empty, the accounts are gone, and
the totals and the staleness report are gone with them — which is exactly what
the move was for. Do not run the move again.

It does this in the `default` workspace and nowhere else, whatever workspace is
configured — the path is fixed rather than read from config. So retire a broker
on any other workspace and the file simply stays gone, and the paragraph above
does not apply to you. Worth knowing mainly so that two machines behaving
differently reads as the workspace it is rather than as one of them being
broken.

The name stays in that source list for the same reason it appeared in the first
place: the list names the databases that were *read*, not the ones that had
anything in them, so an empty database is a database that was read. It is on the
sheet as well as on the line above. Nothing in the config or on the command line
takes a bundled broker's name off it — deleting its package from the
installation would, and that is not a supported operation — and there is no
reason to want one badly enough to make an empty database read as a failure: an
empty database that should *not* be empty is a broker whose run wrote nothing,
and that has to stay loud.

**So the file's absence is not the thing to check, because the file will not be
absent.** The account count and `stonksmithdb stale` are. Against the workspace
this section was written from, retiring one scraper that SnapTrade had come to
cover moved both at once:

```text
before   [*] Freshness in 'default': 17 accounts, nothing older than 2026-08-04 (7 days).
         [-] 5 of 17 accounts are stale.
after    [*] Freshness in 'default': 12 accounts, nothing older than 2026-08-04 (7 days).
         [+] 0 of 12 accounts are stale.
```

Five accounts left the workspace and the five stale ones went with them, because
they were the same five: nothing had refreshed them since the broker stopped
running, which is what retiring a broker without retiring its data looks like
from the outside.

**A single stranded account is a smaller move, and it takes two steps.** Moving
the database out is right when a whole broker is being retired; it is the wrong
shape for one account inside a file whose other accounts are all still syncing
into it correctly. For that:

1. **Stop the source reporting it** — for SnapTrade, the `exclude_accounts` line
   above. This is what makes the second step stick.
2. **Remove what the earlier runs wrote**, in `stonksmithdb` under
   `broker <name>`, with the id read off `show accounts`:

```text
stonksmithdb (snaptrade) > delete account 1
    [+] Deleted account 1 (Schwab - Beneficiary A 529 Plan) and 31 snapshot(s)
    [!] This does not stop the account coming back. The next sync recreates
whatever its broker still reports -- for SnapTrade, add it to [SNAPTRADE]
exclude_accounts first.
```

(Representative figures, not a real account.)

**The order is the whole of it.** Delete without excluding first and the next
sync returns the account under a fresh id, so the deletion has cost you its
history and changed nothing. That is why the command prints the warning on every
run rather than trusting this page to have been read — and it is why accounts
were not deletable for so long. The original refusal was that the next run would
recreate them, which is still true of every account a broker is still returning.
`exclude_accounts` is what makes one account an exception to it.

It reports by name and counts what it took because it cascades: the account's
snapshots, the holdings behind them and its transactions all go, and there is no
undo. Read the name back before believing you typed the right id.

**This setting is permanent, not a workaround.** The reasonable-sounding hope is
that a single reader over all the databases would make it unnecessary — that it
could recognise the duplicate and drop one. It cannot, and the reason is
structural rather than a missing feature. `account_key` is unique *within* one
broker's database and means nothing outside it: the same Schwab-held 529 is
`Schwab - Beneficiary A 529 Plan` to SnapTrade and `Beneficiary A` to the
`schwab529plan` scraper. Different key, different external id, different
display name, and nothing stored anywhere links the two. Any reader opening
both files sees two unrelated accounts and would total them exactly as two
tabs do.

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

## Schwab 529

**The one broker that needs no browser and no API key.** Schwab's 529 aggregator
accepts a form post, so the whole run is a session, a login and two page reads —
no Playwright, no session to keep, and nothing to re-authorise. It is the
cheapest broker here to run on a schedule.

Pass the credential on the command line:

```bash
uv run stonksmith schwab529plan -M schwab529plan -u <username> -p <password>
```

Or, better, store it once and refer to it by id — `-p` leaves the password in
your shell history and in the process list:

```bash
uv run stonksmithdb        # broker schwab529plan, then: add creds <username>
uv run stonksmith schwab529plan -M schwab529plan -id 1
```

The broker deliberately declares no flags of its own. `--account` and `--site`
used to be there and nothing ever read them, so passing either did nothing at
all; `broker_args.py` says the next one goes in alongside the code that consumes
it.

A run reads the overview page for accounts and holdings, then the activity page
for movements. Three things about that parse are worth knowing:

**Columns are found by their headers, not by position.** `TRANSACTION_COLUMNS`
in `src/stonksmith/helpers/schwab529plan.py` maps each of the six canonical fields to the
spellings a page might print — `Processed` also answers to *process date* and
*settlement date*. A page that grows a seventh column shifts nothing, which is
the failure a positional read has and does not report.

**A movement is attributed to an account or to nothing.** `match_account()`
tries three rules in order: an exact match on normalised text, a shared trailing
run of digits — Schwab masks its numbers, so `...4321` has to reconcile against
`XXXX4321` — and finally a candidate name inside the hint, as in *Contributions
for Beneficiary A*. A hint matching two accounts is a collision rather than an
attribution and returns nothing, because a wrong answer here is
indistinguishable from a right one afterwards.

**Dates are stored as the source wrote them and normalised on the way out.** The
529 scraper stores `12/30/2025` where SnapTrade stores ISO, so the `Transactions`
tab is where the two have to agree — see [`sheet.md`](sheet.md).

`transaction_from_row()` here is one of only two transaction producers in `src/`;
the other is SnapTrade's. [`ally-transactions.md`](ally-transactions.md) explains
why there is no third.

## TSP

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
uv run stonksmith tsp -M tsp --balance 8409.71 --balance-as-of 2026-08-05
```

```text
Balance $8,409.71 on 2026-08-05 at $24.7344 (2026-08-05) = 340.0006 units
Store it: [TSP] units = 340.0006, units_as_of = 2026-08-05
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
L 2060: 340.0006 anchored + 88.571847 estimated = 428.572447 units x $24.7344 (2026-08-05) = $10,600.48
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
themselves and leave the anchored mark exactly as it was. So does a page whose
columns stop lining up with its own headings — rates are matched from the right,
so a column grown after the last one would shift every figure by one band and
hand back a real published rate for the wrong seniority. That is the one failure
here that would otherwise look like an answer, so the accrual is dropped rather
than priced on it. `--show-pay-table` prints the whole parsed grid, grades down
and years of service across, for checking the parser against the published page
rather than against the single rate a run happens to need. The pay table is
cached under `~/.stonksmith` for the rest of the year, since DFAS changes it
every January. `--pay-table` reads a page saved by hand, the way `--prices`
does, and remains the fallback: dfas.mil fingerprints its callers, so a download
that works today can stop. **It has been run against dfas.mil for real** — see
[`live-verification.md`](live-verification.md).

Sheets needs no tab prepared: StonkSmith creates `Accounts`, `Holdings`,
`Transactions` and `Dashboard` itself on the first sync. If the sheet cannot be written at all — no
spreadsheet, no authorization, or a tab that turns out not to be StonkSmith's —
the run prints `TSP mark saved locally; the dashboard was not updated.` and still
exits 0, because the database write has already happened and Sheets is a view of
it. That message is about the sheet, not about the broker.

The statement reader, the price parser and the arithmetic are all verified
against real files, and the mark has been checked against what the site itself
reports. The database write has been run, against a real `tsp.db` and against
one written before the `units_as_of` column existed. The sheet has been run too: on
2026-08-10 it was built from real databases, read back tab by tab, checked by eye
where a read could not reach, made to refuse a tab it did not own, and rebuilt
from nothing after the four tabs it then had were deleted. `Net Worth` came after all
of that, and one run on 2026-08-11 made it, wrote it and read it back, ten checks
passing; a run on 2026-08-15 then walked the series itself across nine dates, on a
workspace whose brokers really had reported on different days, and the account count grew
or held on every one of them. What is left
there is the claim eighteen movements cannot put — that a tab holds every movement rather
than the newest five hundred — which is tracked on its own as #141.
[`live-verification.md`](live-verification.md) has the
procedure, those runs written up, and one trap worth knowing about first — a
statement naming a different fund from your config is refused, but one whose
fund cannot be read at all is still priced with the configured fund.

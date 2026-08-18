# Live verification

Green tests say the code does what it was written to do. They do not say the site
still looks the way it looked when the parser was written, that a session survives
a process exit, or that a URL still serves what it served last quarter. Only a run
against the real thing says that.

This file records which broker claims have been observed against a live account and
which have not, and gives the procedure for closing the gap. It is meant to be worked
through, not read.

**This file is the record.** Three places summarise it — the paragraph under
[*Project structure*](../README.md#project-structure) in the README, the end of
[*Ally Invest*](brokers.md#ally-invest) and the opening of [`sheet.md`](sheet.md) — and
all three are derived from the table below rather than maintained alongside it. Change a
row here and change those there in the same pass; do not edit them on their own.

**A failed step here is information, not a defect.** Session persistence and an
unattended price download are load-bearing for the claim that a broker runs daily
without a human. If one does not hold, the right response is to say so in the
summaries named above rather than to leave the claim standing. Each step below therefore says what *either*
outcome would mean.

---

## Where each claim stands

**`Observed live` means StonkSmith itself was run, start to finish, against the real
thing** — the live site for a broker that has one, or a real file as its source
published or issued it for a broker that does not. What does *not* count is a copy
captured once and committed under `tests/`, however real the data inside it: a
fixture is replayed, and replaying shows the parser has not changed rather than that
the source has not. That is what the `Rests on` column is for, and a capture and a
run are not the same evidence. A row can also be settled the other way: **Run, and it
cannot** is an observation, not a gap.

*As of 2026-08-17: 33 of 38 claims have been settled by a live run — 31 confirmed,
2 disproved. 0 of those were settled more than six months before that date, and 0
carry no date at all. The remaining 5 rest on evidence no run here has produced: a
broker with the transaction volume to put the question, a SnapTrade connection that
has actually lapsed, an account whose holdings have actually gone stale, a 529
with more than one beneficiary on it, and a transaction read followed across more
than one page of the real API. They are not alike, and the three kinds are worth
telling apart. Three need a condition to occur rather than a run to be made: a lapsed
connection, stale holdings and a second beneficiary, none of which any amount of
sitting down at the machine produces. The transaction volume is a kind of its own —
nothing has to happen, but enough has to accumulate, and at nine movements in five days
that is a wait rather than an afternoon. The last is the only one that is anybody's
to-do. Following pages wanted volume too until `--page-size` landed; now it wants a page
size asked for and a machine holding the credentials, which is a run somebody makes. Two rows left this list on 2026-08-15 and
are worth telling apart: the allocation blocks only ever needed a run made after the
check existed, while the carried series needed a workspace to become the ordinary state
of a real one, which took waiting rather than doing. Five more left it on 2026-08-17 by being
withdrawn rather than settled, which is a third way off this list and is explained
below.*

**A settled claim does not stay settled, and the dates are why.** This file opens by
saying green tests cannot tell you the site still looks the way it did. A run has the
same problem one day later: it proves what the site was, and it proves less about what
the site is with every week that passes. A table of `Yes` with no dates on it reads as
finished work, which is the one thing it is not — so every settled row now carries the
date of the run that settled it, and **a claim settled more than six months ago should
be read as due for a re-run rather than as done.**

**Two rows arrived here carrying no date, and both were bounded rather than guessed.**
*TSP — statement parser* and *TSP — the mark, and the balance inversion* each cited a
real run without saying when it happened, which left them unageable — the same
objection this file makes to a balance with no as-of date. Neither could be re-run to
find out, so each was dated from the commits either side: the code it exercises landed
on 2026-08-06 and the claim was recorded settled on 2026-08-07, which puts the run in
a one-day window. **The earlier bound is the one taken**, because an interval read the
other way makes a claim look fresher than it is, and this column exists to stop
exactly that. Both cells say so, so a reader can see the date is inferred rather than
observed.

`not recorded` stays a legal value for the next row that needs it. A run whose date
nobody wrote down is a thing that will happen again, and the column has to be able to
say so rather than tempt somebody into a plausible number.

**The count above dates itself for the same reason.** It says what was true on a
stated day rather than what is true now, so a reader who arrives a year later can see
that the summary is a year old instead of trusting it. That is also what keeps
`tests/test_live_verification_tally.py` honest: it checks the arithmetic *against the
stated date*, never against today, so the suite cannot go red purely because time
passed. A test that fails on an untouched repository is one that gets muted, and this
project has already written down what muting costs — see
[`scheduling.md`](scheduling.md). Bump the date when you record a result, and the
count comes with it.

**Five `fidelity` rows were withdrawn on 2026-08-17, and withdrawn is not settled.**
They asked whether the `fidelity` broker's sign-in, scrape, session and database
write still work against the real site. Nobody ever ran it, and now nobody will: the
broker was deprecated that day for removal in 1.0, because Fidelity reaches the
workspace through SnapTrade and nothing here recommends the scraper. A row is a
question somebody intends to answer, and these stopped being that.

**The broker still ships.** `stonksmith fidelity` runs until 1.0 and prints a notice
saying so, and its ten test files are still in the suite. So this is not a case of
the rows describing code that is gone — it is the narrower and more awkward one of
code that is still here and deliberately unverified. Anyone who runs it is running
something no live check stands behind, which is the whole reason the deprecation
names a replacement rather than just a date.

That is stated here rather than left to an absence, on the same reasoning that put
the five rows in to begin with: an absent row reads as nothing to say instead of
nothing observed, and this file has already implied otherwise once by leaving a gap
where a claim belonged. When the broker goes at 1.0, this paragraph goes with it.

The Fidelity *accounts* SnapTrade reaches are settled, and they always were a
different claim: SnapTrade asks an API for a balance, while the `fidelity` broker
drove a browser past Akamai Bot Manager and ThreatMetrix to scrape a summary page.
Nothing about the first ever said the second worked — which is why removing the
scraper costs this table no coverage it had.

`tests/test_live_verification_tally.py` derives the five numbers in the count above
from the table below
and fails if this sentence disagrees with them. It exists because this paragraph said
nineteen for four commits after the table reached twenty rows: the instruction to update
it lives under *Recording a result*, and an instruction is not a mechanism.

| Claim | Rests on | Observed live | Settled on |
| --- | --- | --- | --- |
| Ally — sign-in hand-off to `live.invest.ally.com` | Nine runs against a real account, 2026-08-07; unit tests over the URL predicate | Yes | 2026-08-07 |
| Ally — holdings, totals and sidebar parse | The same nine runs; `tests/ally_holdings.html` is one redacted DOM from that same account | Yes | 2026-08-07 |
| Ally — masked sidebar number matches the full one | The same nine runs; `masked_matches("...0111", "1AB20111")` in unit tests | Yes | 2026-08-07 |
| Ally — Ally Bank deposit accounts skipped, not filed as brokerage | The same nine runs | Yes | 2026-08-07 |
| Ally — database write | The same nine runs, which wrote to a real `ally.db`; the unit tests behind this only ever write to a fake one. The `units_as_of` stamp on each holding postdates those runs and has not been written to a real one | Yes | 2026-08-07 |
| Ally — one row per account across runs | Two signed-in runs on 2026-08-10, 21:57:58 and 22:03:26, written up below: `show accounts` held at one row while `show snapshots` went 26 → 27 → 28 | Yes | 2026-08-10 |
| Ally — valuing from published prices without a login | Three price runs on 2026-08-10 against a real account with no sign-in, written up under step 6: the price date reached `as_of`, and the units' stamp held at `22:03:26` across snapshots 29, 30 and 31 while the newest snapshot's own time moved under it | Yes | 2026-08-10 |
| Ally — the published price feed answers | A real request on 2026-08-09, written up below: 200 and 3,612 bytes of JSON for one symbol, read by `daily_closes()` into 23 dated closes | Yes | 2026-08-09 |
| Ally — session survives to the next run | Nine runs, both browsers, both persistence models | **Run, and it cannot** — see below | 2026-08-07 |
| TSP — statement parser | Real statements, read as issued through `-o STATEMENT=`. The run itself was never dated; the date below is bounded by the commits either side of it — the reader landed in `4f1b2b1` on 2026-08-06 and the claim was recorded settled in `123af7e` on 2026-08-07, so the earlier bound is taken | Yes, against real files | 2026-08-06 |
| TSP — share price parser | The published file as fetched on 2026-08-07 (#48); `tests/tsp_prices.csv` is a slice of it kept as a fixture | Yes, against real files | 2026-08-07 |
| TSP — the mark, and the balance inversion | Checked against what the site itself reports: `0bc6668` carries a balance and date read off it, `--balance 8409.71 --balance-as-of 2026-08-05`. Bounded the same way as the row above — inversion landed 2026-08-06, recorded settled 2026-08-07 | Yes | 2026-08-06 |
| TSP — share price download | A real request on 2026-08-07 written up in #48, and again unattended on 2026-08-10 (#116): 200 and 555,142 bytes, fetched by the run itself rather than by hand | Yes | 2026-08-10 |
| TSP — DFAS pay table parse | All four published pages, parsed as served: the enlisted one on 2026-08-10 (#116) into all nine grades, and the officer, prior-service and warrant pages on 2026-08-11 (#118) into O-1..O-10, O-1E..O-3E and W-1..W-5. Every fixture in `tests/` is now a served page; the enlisted reconstruction read **zero** grades off the real one, and the prior-service reconstruction's rates were invented outright | Yes | 2026-08-11 |
| TSP — DFAS pay table download | Real requests through `fetch_pay_table`: the enlisted page unattended on 2026-08-10 (#116), 200 and 116,257 bytes, and the other three on 2026-08-11 (#118), 200 each. The 2026-08-07 and 2026-08-09 refusals were real but were never about the User-Agent — see below | Yes | 2026-08-11 |
| TSP — the contribution accrual | A live run on 2026-08-10 (#116) over the published price file and the DFAS page, both fetched by the run; all six months recomputed independently and matched on every field | Yes | 2026-08-10 |
| TSP — database write | Five runs on 2026-08-10 (#116) into a real `tsp.db`, four dates on one snapshot and the holdings summing to its value exactly; plus a genuine pre-migration database, migrated on open | Yes | 2026-08-10 |
| The sheet — the machine-owned tabs | All four checks, against the four tabs then defined, against the real spreadsheet on 2026-08-10 and written up below. `verify tabs` settled the first three: the banner on all four tabs, row 2 against all three column contracts with `Holdings` ending at `P`, money back as a number, and the dashboard's two totals equal. Check 4 was then done by eye — of 16 accounts, 7 had a blank `As Of` and all 7 appeared in the staleness panel, so an undated account is surfaced rather than counted at face value. The creation half followed: the four tabs were deleted and `sheet` run again, which had `ensure_worksheet` make all four and `claim()` adopt them empty before writing — reported as working rather than transcribed, so there is no output quoted for it | Yes | 2026-08-10 |
| The sheet — the whole transaction history reaching a tab | `verify tabs` on 2026-08-10 confirmed the tab's 9 movements against the 9 the databases hold, every date normalized and each account newest-first, and on 2026-08-15 it confirmed 18 against 18. Nothing was dropped at either size; five hundred is where the question starts, so this row needs a workspace with the rows rather than a longer sitting — the count has grown by nine in five days, which is the rate that makes it a wait rather than an afternoon. `verify volume` supplies its own rows instead, and was run against the real spreadsheet on 2026-08-15: both requests landed, all 2,500 rows came back, and the first and last row of each write sat in the cell it was addressed to. That settles the second-chunked-write half and cannot settle this one — the window it would have to find is upstream of the write, and rows the check supplies itself enter below it | No | — |
| The sheet — refusing a tab it does not own | Run on 2026-08-10 against the real `Holdings` tab: a defaced first cell refused, then text below a blank first cell refused, then a restoring sync. `verify guard` got all three of `claim()`'s answers, empty-tab adoption included. One part is not observable this way — that a refusal leaves no tab freshly written beside a stale one rests on claim-before-write and its unit test, since a run whose data is unchanged cannot tell a rewritten tab from an untouched one | Yes | 2026-08-10 |
| The sheet — the fifth tab, `Net Worth`, created, written and read back | `sheet` then `verify tabs` on 2026-08-11 against the real spreadsheet, quoted below: the banner line counted five tabs and the eleven-column contract came back off the real tab, ending at `K`. Ten checks, all passing, the two render assertions unmarked for the first time on a sheet written that morning. That same run created the tab — four machine-owned tabs stood on 2026-08-10, no `sheet` ran in between, five carried the banner after — so `ensure_worksheet` made it and `claim()` adopted it empty, which is the half no read can show | Yes | 2026-08-11 |
| The sheet — every allocation block adding up to the total it is a share of | `verify tabs` on 2026-08-15 against the real spreadsheet, the first run since the check was written: all three blocks were drawn and all three read back — account kind, position, and asset class — which is why that run counts thirteen checks where 2026-08-11 counted ten. The asset class line appearing at all is the config half, since it is drawn only when `asset_classes` is set. The refusal state was not seen and cannot be arranged; it needs positions exceeding balances, which check 8 says in advance is the expected outcome. Unit tests over a fake spreadsheet, `tests/test_portfolio_sheet_readback.py`, cover the wrong sum, the wrong share, and a refusal not being mistaken for either | Yes | 2026-08-15 |
| The sheet — the account series carried across brokers that scraped on different days | A run on 2026-08-15 against a workspace whose six brokers entered the series twelve days apart and fell silent for up to six days inside it, quoted below: 78 rows off the real `Net Worth` tab, over nine dates, for twelve accounts. The account count per date ran `1, 7, 7, 9, 9, 11, 11, 11, 12` and never fell, where the observed-only count falls three times — so the carry-forward ran. Every row read `observed` or `carried`, the 17 carried ones dating `Observed On` before their `Date`; the eleven accounts that joined after the first date have no row on any date before they did, and no row is a zero. The thirty-day horizon is untouched by it — the longest silence there is six days — and that half still rests on `tests/test_net_worth_history.py`, alongside `tests/test_portfolio_sheet_workspace.py` over two real databases on disk | Yes | 2026-08-15 |
| SnapTrade — a personal API key reaches the API | Four runs on 2026-08-11 against a real account, written up below. `verify_access` listed the connections and every run proceeded on the key alone — no userId, no userSecret, no browser | Yes | 2026-08-11 |
| SnapTrade — accounts and balances reach the database | The same four runs, into a real `snaptrade.db`: snapshots 168–199, eight accounts per run, each carrying an `As Of` of 2026-08-11 | Yes | 2026-08-11 |
| SnapTrade — positions reach the database | The `Holdings` tab went from 2 rows to 9 between the `--no-positions` run and the full one that followed, both on 2026-08-11 — the seven are SnapTrade's, and the two that survived the first run are other brokers' | Yes | 2026-08-11 |
| SnapTrade — transactions reach the database | The same pair of runs took movements from 9 to 10. **One movement, which is not a test of the pagination behind it** — that half is the row below, and it is why this one is settled at a size rather than settled | Yes, at one movement | 2026-08-11 |
| SnapTrade — the transaction read follows pages to exhaustion | Unit tests over the fake client in `tests/test_snaptrade_broker.py`, and nothing else. SnapTrade serves a thousand rows to a request, so no real run has ever filled a second page and neither the loop nor its 20-page backstop has run against the API. `--page-size` makes both askable without waiting for the volume — the run is what has not happened | No | — |
| SnapTrade — a liability is skipped, not filed as an asset | All four runs skipped `Chase / CREDIT CARD` by name, reporting `it is a liability (LOC)`, against a real card carrying a real negative balance | Yes | 2026-08-11 |
| SnapTrade — `exclude_accounts` drops an account another broker owns | All four runs skipped the Schwab-held 529 by name, reporting `excluded, because another broker covers it`, with the label matched out of the config | Yes | 2026-08-11 |
| SnapTrade — one row per account across runs | Four runs inside five minutes: `show accounts` held at nine rows while `show snapshots` went 168 → 199, eight per run | Yes | 2026-08-11 |
| SnapTrade — a disabled connection is skipped rather than served its last balance | Unit tests over a fabricated disabled connection. No connection has lapsed here, and this cannot be staged — it needs a real expiry, which is the one thing a longer sitting does eventually produce | No | — |
| SnapTrade — the holdings freshness guard fires | Unit tests over fabricated sync timestamps. Every real account was synced the same day, so `--max-age-days` has never had anything to reject | No | — |
| SnapTrade — an exclusion added after a sync removes what was already written | Read off the same runs, and it does not: the 529 excluded on all four still has its account row and its pre-exclusion snapshots in `snaptrade.db`, and they still render | **Run, and it cannot** — see below | 2026-08-11 |
| Schwab 529 — the form post signs in with a stored credential | A run on 2026-08-11 against the live aggregator, by credential id rather than by password on the command line: `Login successful` | Yes | 2026-08-11 |
| Schwab 529 — the overview page parses into an account and its holdings | The same run: one holding added to the workspace, `Holdings` 9 → 10 | Yes | 2026-08-11 |
| Schwab 529 — the activity page parses into movements | The same run: one movement added, `Transactions` 10 → 11 | Yes | 2026-08-11 |
| Schwab 529 — a hint naming one of several beneficiaries is attributed to the right one | Unit tests over `match_account()`'s three rules and its collision case. The live account has a single beneficiary, so the rule that picks between them has never been asked a real question | No | — |

The Ally rows are the ones worth reading twice. Those nine runs were nine runs against
*one account state*: one investment account, one holding, one deposit account. So the
parse has met a live site, but only ever that shape of it. Every plural case — a
second brokerage account, a second position, an account with no holdings — is still
inference, and `tests/ally_holdings.html` is a redaction of that same single state
rather than a second witness to it.

---

## Ally

Seven steps. The whole sequence needs one signed-in browser session and about ten
minutes — except step 6, which deliberately needs no session at all, and most of which
has to be run on a later day than step 1 to mean anything. Its refusal half needs not
even that, and has been run. An eighth check sits after them, unnumbered because it is
not part of the sequence and needs nothing whatsoever.

The `[+]`, `[!]`, `[*]` and `[-]` prefixes below are what the logger prints for
success, highlight, display and failure respectively. Quoted strings are copied from
the source, so if one does not appear verbatim, either the step failed or the message
has been edited since this was written.

### 1. The sign-in completes and the hand-off is respected

Install the browser runtime first — and again after any `uv sync` that moves
Playwright, since each release pins a new browser revision and the previously
installed one no longer satisfies it:

```bash
uv run playwright install firefox
```

Skipping it gives a `Could not start browser for Ally` failure naming a Firefox
executable that is not there, followed by Playwright's own banner suggesting a bare
`playwright install` — which needs the `uv run` prefix here or it installs against
the wrong environment. That failure is the runtime being absent, not the broker; the
run reports it and exits rather than raising.

```bash
uv run stonksmith ally -M ally --manual-login
```

A browser window opens at `secure.ally.com`. Before signing in, confirm the run has
printed a `[!]` line ending in:

```
Taking over once live.invest.ally.com loads (waiting up to 5 minutes).
```

That sentence is appended to a longer instruction whose wording depends on whether
the browser was launched or attached to over CDP, so match on the tail rather than
on the whole line.

Now sign in **and click through to your investment account**. StonkSmith must not
touch the page until the host is `live.invest.ally.com` — not merely a bank URL that
mentions it. Watch for it staying put while you are still on the bank dashboard;
that waiting is the behaviour under test.

Then one of:

```
[+] Signed in. Session saved; later runs reuse it until it expires.
[!] Signed in, but the session could not be saved -- the next run will ask you to sign in again.
```

**If it times out** the run writes the page it was looking at:
`~/.stonksmith/logs/ally-manual-login-timeout-<UTC stamp>.html` and a `.png` beside
it. Open the HTML and look for `#allyNavLogOut`. Present means the URL predicate is
right and the signed-in selector is wrong; absent means the hand-off never happened.
A trace also lands at `~/.stonksmith/playwright/Ally_trace.zip`.

### 2. The session does not persist

**This was the step that decided whether the broker is usable daily, and it has an
answer.** Settled 2026-08-07 across nine runs, both browsers, both persistence
models: Ally cannot reuse a session. What follows is the evidence, not a procedure to
repeat.

What is saved is not the problem. `~/.stonksmith/playwright/Ally.json` holds a
well-stocked jar -- `jwt`, `refreshToken`, `csrf-token` and `tksid` for
`.invest.ally.com`, `Ally-CIAM-Token` for `.ally.com`, and a `users` key in
localStorage for the investing origin. `save_session()` writes it, mode `0600`, every
time.

What happens on the next run is that Ally refuses it and the app signs itself out:

```
401 https://live.invest.ally.com/api/session/checkSession (49 bytes) {keys: redirectUrl}
401 https://secure.ally.com/acs/.../auth/login (464 bytes) {codes: error_code=4001}
```

One or the other -- the refusal alternates between the investing host and the bank,
with different bodies, and any claim about which one is "the" cause was wrong twice
before this was understood. What does not vary: something answers 401, the app then
calls `auth/anonymous_invoke`, and the shell renders with an empty `<sidebar>`. After
a manual sign-in the same endpoints answer 200, which is what makes the comparison
conclusive rather than suggestive.

Three mechanisms were tried:

- **Firefox with `storage_state`** (the default). Refused.
- **Firefox with `storage_state(indexed_db=True)`.** Device-binding SDKs keep their
  identity in IndexedDB and `storage_state()` omits it unless asked, so this was the
  best remaining theory. Refused.
- **`--browser chrome`, a persistent profile directory.** Refused, and differently:
  the holdings URL does not reach the investing host at all, landing on
  `www.ally.com`.

The page captures cannot show any of this, which is why it took nine runs. Three of
them are identical to within one byte -- 758551, 758550, 758550 -- including one taken
from a session that made 25 successful data calls. A session Ally renders for and one
it does not produce the same markup, so the difference only ever existed in the
network log.

**Those twenty-five calls are gone, and that is the reason the recorder changed.**
The write-up kept the count because the count was all the log printed: reporting ran
only from `capture_page()`, which fires after something has already failed, and the
recorder was armed only on the non-attached path -- so `--browser cdp`, the browser
this section recommends, recorded nothing at all. Every Ally run that opens a browser
now writes `~/.stonksmith/logs/ally-data-calls-<stamp>.log` on the way out, whatever
the outcome, and each line carries the endpoint's parameter *names* alongside its
status and size. Values, bodies and headers are still never read. A future run of this
procedure should therefore attach that file rather than a number.

Ally is the only broker that arms the recorder, so a Fidelity run still leaves
nothing. Saving is generic and needs no per-broker wiring; arming is one call, and
worth adding there only if Fidelity acquires a question of its own.

**The outcome: the Ally scrape cannot run unattended.** `--manual-login` on every
scrape is the correct description, and both the README's
[*Brokers*](../README.md#brokers) table and
[`brokers.md`](brokers.md#ally-invest) say so. This is not a defect to fix
in StonkSmith; nothing StonkSmith stores reconstitutes a session Ally will honour.

What does run unattended is `--from-prices`, which values the account from published
closes and the units the last signed-in run recorded — no browser, no sign-in. That is
a different claim from any of the ones settled here, so it has rows of its own in the
table above — opened at `No`, and settled by step 6 rather than by any of the nine.

What *is* proven, every one of those nine runs: the sign-in flow, the holdings parse,
the account rail, the bank/brokerage split and the database write. The scrape works.
It is only the unattended part that does not.

**A schedule is built on that distinction, and it adds no row here.**
`docs/scheduling.md` records which of the five brokers a cron entry can run with nobody
watching — a different question from whether a parser still matches a live site, and one
this file does not answer. It makes no new claim about a live run either. Everything it
leans on is already in the table above: the `--from-prices` path and the price feed
behind it, TSP's rows, and — since 2026-08-11 — SnapTrade's and Schwab 529's, which
used to be an absence a schedule was leaning on and are now rows with runs behind
them. This paragraph names those rows and no longer repeats their verdicts,
because restating a status in a second place is maintaining it twice and disagreeing at
the first change — which is what happened to the copies that used to stand right here.
That file cites the rows; this table stays the count. Step 6 below is what settled the
one a schedule leans on hardest.

**What the recorder is being read for is written down elsewhere.** Ally's open questions
are about endpoints nobody has seen -- whether an activity feed exists, whether it is
per-account, whether it takes a date window -- and the decision those answers feed is
recorded in `docs/ally-transactions.md`, along with the two other conditions that would
reopen it. A run that turns up an activity route belongs in *that* file. This one records
which claims *StonkSmith* makes have been settled by a live run; what Ally's site offers is
a fact about Ally, and filing it here as a claim would mean counting a question in the tally
above.


### 3. The masked number reconciles against a real account

Any successful run exercises this. The sidebar says `...1234`; the page heading says
something like `3LD21234`. Confirm the run reports one row per account and did not
invent an extra:

```
[+] Found N investment account(s)
```

Then check what was stored:

```bash
uv run stonksmithdb
broker ally
show accounts
```

The `Account` column should read `<nickname> (...1234)` — the *masked* form — and the
full number should be alongside it. Both routes into a row, sidebar and heading, are
supposed to agree on that one identity; if a single account shows up twice, once with
a balance and once with positions, they did not.

This logic has met a real account, but exactly one. Ally account numbers are
alphanumeric, which is why the comparison upper-cases both sides. A number with a
lowercase letter or an unexpected separator is exactly the case that neither that
account nor the fixture can rule out.

### 4. More than one investment account

Needs two or more brokerage accounts, so skip if you only have one — and say so
rather than ticking it.

With the second account **not** selected in the browser, run and confirm three
things at once:

- every investment account has a balance
- only the selected one has holdings
- the run says so, once per unselected account:

```
[!] <label>: recording the balance the sidebar shows. Its positions are not on this page -- select the account in the browser and re-run to store them.
```

Then check in `stonksmithdb` that the unselected account's `Total G/L` and
`Today's G/L` are empty rather than carrying the selected account's figures. Those
are headline numbers for the account on screen; copied across, they read as fact.

Now select the other account in the browser, re-run, and confirm its positions land
without the first account losing its own.

### 5. Ally Bank deposit accounts are skipped, not filed as brokerage

Any run where a deposit account is in the sidebar:

```
[*] Skipping <label>: it is an Ally Bank <kind> account, not an Ally Invest one.
```

Then confirm `show accounts` has no row for it. The kind is read from the `<li>`
class with `-account` stripped, so a class Ally has since renamed would show up here
as a *missing* skip line and a bank balance filed under a brokerage — which is why
the skip announces itself rather than happening quietly.

### 6. The account values from published prices, with no browser at all

Four things to establish, and they do not cost the same. **Two of them cost nothing** —
that the run refuses a database with no units on record, and that it opens no browser
doing it — and both have been run; they are written up first for that reason. The two
that remain are about what happens when there *are* units, so they need step 1 to have
run first. **All four have now been run**, on 2026-08-10 — though the fourth took three
price runs rather than one, for a reason worth reading before repeating this: the first
of them could not ask the question, and was what made asking it possible.

#### The half that needs nothing, run 2026-08-10

Against a database with no Ally holdings on record, the run must refuse rather than
value nothing:

```
[-] No holdings on record to value. Run with --manual-login once so a signed-in run can record the units.
```

A number here instead of a refusal would be the finding — it would mean the run had
invented units rather than read them. That is the failure that matters more than the
success, and until now it had only ever been met by a `MagicMock`.

Run against a throwaway home, so a fresh `ally.db` is the whole of the database state.
`$HOME` is the only input to the path StonkSmith derives — no flag or variable
overrides it — so redirecting it relocates the entire tree:

```bash
SCRATCH=$(mktemp -d)
HOME=$SCRATCH USERPROFILE=$SCRATCH \
  PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
  uv run stonksmith ally -M ally --from-prices
```

```text
Broker:  Ally    [!] Kicking off broker flow
Broker:  Ally    [+] Valuing from published prices; no sign-in needed.
Module:  Ally    [!] Starting Ally sync for: published prices
Module:  Ally    [-] No holdings on record to value. Run with --manual-login once so a signed-in run can record the units.

exit=1
```

Both quoted lines appeared verbatim, and the run left `accounts`, `account_snapshots`
and `holdings` all at zero rows — a refusal that had already written a row would be a
worse fault than the invented number this is checking for. Repeating the command
against the same home changed none of that.

**No browser opened, and the filesystem is what says so.** First-run setup creates
`~/.stonksmith/playwright/` whatever the run does, so the directory existing proves
nothing; what it *contains* does. After the price run it was empty. The control is the
same command with the flag removed:

```text
Broker:  Ally    [-] Could not start browser for Ally: BrowserType.launch: Executable
                     doesn't exist at /opt/pw-browsers/firefox-1482/firefox/firefox
```

— and that run left `Ally.json` behind in the same directory. So the two branches are
distinguishable on disk and not merely in the log: the scrape branch reached
`BrowserType.launch` and got as far as writing session state, and the price branch
returned before either. A price run that opened a window would have to explain the file.

`tests/test_ally_from_prices_cli.py` now runs exactly this and reads the same four
things back, so the strings quoted above stay true to the source rather than to the day
they were copied.

#### The half that needed step 1, run 2026-08-10

Step 1 ran twice that evening — the two runs written up under *Every broker* below —
leaving the account's units on record at `2026-08-10 22:03:26`. The price run followed
a minute later:

```bash
uv run stonksmith ally -M ally --from-prices
```

```text
Broker:  Ally    [+] Valuing from published prices; no sign-in needed.
Module:  Ally    [!] Starting Ally sync for: published prices
Module:  Ally    [+] Individual (...1234): 125.000 SWPPX x $20.00 (2026-08-07) = $2,500.00
Module:  Ally         [*] Individual (...1234): priced at 2026-08-07; units as recorded 2026-08-10 22:03:26. Re-run with --manual-login after a deposit.
Module:  Ally    [+] Ally valued from published prices.
```

`show snapshots` gained one row, and it is the **only row in the table with an `as_of`
at all** — the twenty-eight scraped snapshots preceding it leave that column empty:

```text
| 29 | Individual (...1234) | 2026-08-07 | 2026-08-10 22:04:27 | $2,500.00 | USD |
| 28 | Individual (...1234) |            | 2026-08-10 22:03:26 | $2,500.00 | USD |
| 27 | Individual (...1234) |            | 2026-08-10 21:57:58 | $2,500.00 | USD |
```

That is the check: the value is dated by the source it came from, 2026-08-07, and not
by the run that wrote it, 2026-08-10 22:04:27. An `as_of` echoing the run date would
have meant the price date never reached the column.

`show holdings 29` carries step 1's unit count and step 1's stamp:

```text
| Individual (...1234) | SWPPX | Schwab S&P 500 Index | 125.000 | $20.00 | $2,500.00 | ... | 2026-08-10 22:03:26 |
```

The 125.000 is step 1's count by construction rather than by comparison — the price
path reads units from the database and has no way to fetch them — so what this row
shows is that repricing carried them through without disturbing them. `Units As Of`
reads `22:03:26`, the sign-in's stamp, not the price run's `22:04:27`. Three dates, all
different and each meaning what it says: the price is Friday's, the units were read at
22:03:26, the row was written at 22:04:27.

**The value is corroborated, which was not something this step asked for.** 125.000 ×
$20.00 = $2,500.00, and the two signed-in runs minutes earlier had independently
recorded $2,500.00 from Ally's own page. The published-price arithmetic and the
broker's own number agree to the cent, on the same units, by two paths that share no
code. Worth recording because a valuing path can be perfectly self-consistent and still
be wrong about the world.

#### The stamp holds still: three price runs, 2026-08-10

A date that advances to the previous price run is the failure this exists to catch:
these runs write snapshots, so an age inferred from the newest snapshot reports the
units a day old however old they are — drifting younger while the units drift older,
and reading as fact the whole way.

**The first price run could not ask this, which is why it took three.**
`value_from_prices` takes the stamp from the holdings it read, falling back to the
account's last-seen time only when no row carries one. At 22:04:27 those two agreed:
the newest snapshot was 28, scraped `22:03:26`, and the holdings' stamp was also
`22:03:26`. A run reading the stamp and a run inferring it from the newest snapshot
would have printed the identical line. That check did not fail — it was not yet
askable.

Writing snapshot 29 is what made it askable, by putting a timestamp on the newest
snapshot that the units never had. Two more price runs followed, **30 and 31** — 29 is
shown with them because it is what they each read, not because it is one of the two:

```text
| 31 | Individual (...1234) | 2026-08-07 | 2026-08-10 22:29:44 | $2,500.00 | USD |
| 30 | Individual (...1234) | 2026-08-07 | 2026-08-10 22:27:17 | $2,500.00 | USD |
| 29 | Individual (...1234) | 2026-08-07 | 2026-08-10 22:04:27 | $2,500.00 | USD |
```

Each of the two ran with a newest snapshot whose `scraped_at` was **not** `22:03:26` —
29's `22:04:27` for the first, 30's `22:27:17` for the second — and each printed:

```text
[*] Individual (...1234): priced at 2026-08-07; units as recorded 2026-08-10 22:03:26.
```

`22:03:26`, not the newest snapshot's time. That is the discriminator firing: a run
inferring the age from the snapshot it could see had a different number available to
print and did not print it.

And the stamp survived being written, which is the half that would start the drift.
`show holdings 30`:

```text
| Individual (...1234) | SWPPX | Schwab S&P 500 Index | 125.000 | $20.00 | $2,500.00 | ... | 2026-08-10 22:03:26 |
```

So the stamp passed through three consecutive price snapshots — 29, 30, 31 — without
moving, each hop being a fresh chance to restamp it with the run's own clock. Reading
it correctly once and then storing it wrong would have looked identical at the console
and drifted anyway; it is the stored value that had to be checked, and it holds.

**Same day, and that limits one thing.** All three ran on 2026-08-10 against a price
still dated 2026-08-07, so the price date never advanced during the test. That does not
weaken what was shown — the divergence the check turns on was between the stamp and the
snapshot, not between two price dates — but a later-day run remains the only way to
watch `as_of` move forward while `Units As Of` stays put. Worth doing, no longer
load-bearing.

`show accounts` was not captured alongside these runs. It would have closed off the
fallback path by observation as well as by reading, and is the one thing a repeat should
add.

Worth knowing before ticking this: the sheet is **not** synced by a price run, so an
unchanged `Holdings` tab is expected rather than a failure. Run `sheet` in
`stonksmithdb` to refresh it — see *The sheet* below.

**What this settles.** All four, and the row *Ally — valuing from published prices
without a login* moves to `Yes`. The path refuses units it has no record of; it reaches
that refusal without starting a browser; given units it values them, dating the value
by the price rather than by the run; and the units' own stamp holds still across three
consecutive price runs rather than drifting toward the newest snapshot.

The row was held at `No` through the first of those runs, on the ground that a check
which cannot be asked has not been answered. That was the right call and it cost one
evening's patience: the run that made the check askable was the same run that would
have been mistaken for settling it.

What is **not** settled is anything plural. One account, one holding, one price date.
The four checks are about a path, and they are met; an account with a second position
would be asking a different question, and no run here has asked it.

### 7. Re-running does not duplicate accounts

Covered by the shared step below.

### The price feed, on its own

Not one of the seven. This one needs no session, no account and no credential — it asks
only whether the thing step 6 divides by is still there — so it is the one check on this
page anybody can run, and it was run on 2026-08-09:

```bash
curl -sS -A "Mozilla/5.0 (compatible; stonksmith/0.1.0; +https://github.com/Gerrrt/StonkSmith)" \
  -o chart.json -w '%{http_code} %{size_download} %{content_type}\n' \
  "https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1mo"
```

That URL and that User-Agent are `QUOTE_URL` and `QUOTE_USER_AGENT` in
`src/stonksmith/modules/ally_module.py`, copied rather than approximated — the feed's answer is
allowed to depend on who asks.

```text
200 3612 application/json;charset=utf-8
```

**A 200 is half the claim.** The other half is that `daily_closes()` in
`src/stonksmith/helpers/quotes.py` can still read what came back, which is a different question and
the one that a silent change of shape would fail. Against that payload it returned 23
dated closes, 2026-07-08 to 2026-08-07, and two specific things held:

- `meta.gmtoffset` was present, and `-14400`. That field is what dates a bar to a
  calendar day, and the module's own docstring says reading the timestamps as UTC
  instead would agree for a US market and quietly disagree for one that does not. It is
  only a documented hazard while the feed keeps sending it.
- `close_on(prices=..., day=2026-08-09)` returned `(2026-08-07, 773.26)`. The 9th was a
  Sunday, so this is the weekend fallback working against live data — Friday's close,
  returned *dated as Friday* rather than presented as Sunday's.

**What this settles, and what it does not.** It settles the row *Ally — the published
price feed answers*, whose gap was that no real request had ever been recorded. It did
not settle *Ally — valuing from published prices without a login*, which is step 6 and
needs a real `ally.db` behind it. One symbol was asked for here, and an ETF rather than
anything an account holds; a feed that answered for `SPY` and not for some particular
fund would still have failed step 6, which is why the two are separate rows rather than
one.

That particular worry has since been answered from the other side: step 6's runs on
2026-08-10 priced `SWPPX`, a mutual fund actually held, and the feed returned a dated
close for it. That row is now `Yes` — see step 6.

---

## TSP

Six steps. No credential is involved at any point.

### 1. A statement gives up its units

```bash
uv run stonksmith tsp -M tsp -o STATEMENT=<your statement>
```

Both PDF and text are accepted. Expect:

```
[+] Statement: <n> units of <fund> as of <period end>
```

**Check that a fund is named on that line at all.** A statement whose fund disagrees
with `[TSP] fund` is now refused outright rather than priced with the configured one,
so the case that used to produce a confident, wrong number fails loudly instead. The
guard cannot fire when the statement's fund did not parse, though — then `<fund>` is
missing from that line and the mark is priced with whatever is configured. See
*Known traps* below.

If your statement covers more than one fund, only the first is read. Confirm which
one that was before trusting the mark.

### 2. The balance inversion agrees with the statement

Take the balance and date your statement closes on, and put them through the other
path:

```bash
uv run stonksmith tsp -M tsp --balance <closing balance> --balance-as-of <period end>
```

```
[+] Balance $X on <date> at $Y (<price date>) = <n> units
[*] Store it: [TSP] units = <n>, units_as_of = <date>
```

That unit count should match what step 1 read off the same statement, to rounding.
The two paths share no code — one reads a printed number, the other divides — so
agreement is a real cross-check, and disagreement localises immediately: if the price
date is not the balance date, the balance fell on a weekend or a holiday and was
struck at the previous published price, which is correct.

A gap of more than four days between the balance date and the newest usable price is
refused rather than warned about. A refusal costs one correction; a silent division
by a stale price writes a wrong unit count into config, where it persists.

### 3. The mark reaches the database with both dates

```bash
uv run stonksmith tsp -M tsp
```

```
[+] <fund> at $<price> as of <price date>
[+] <fund>: <n> units x $<price> (<price date>) = $<value>
```

Then:

```bash
uv run stonksmithdb
broker tsp
show snapshots
```

`as_of` must be the **price** date and `scraped_at` the run time. They diverge
whenever the run lands on a weekend or before the day's price publishes — run on a
Sunday to see it, since that is the case collapsing them would get wrong.

A third date is stored on the holding, in `holdings.units_as_of`: the date the *unit
count* was true. A TSP mark is a unit count times a share price and the two are true
as of different days, so a stored mark that carries only one of them cannot be audited
later. `show holdings` displays it, and so does the `Holdings` tab.

Confirm the two dates differ, and that `show holdings` reports the unit date under
`Units As Of` rather than repeating the price date — that divergence is the whole
reason this broker exists. Confirming the *tab* agrees with the shell belongs to
*The sheet* below, which is the one procedure on this page needing a Google credential
and therefore not one of these five steps.

With the contribution keys filled in (step 6) there are **two** holding rows, not one:
the anchored count, dated to the statement, and the estimate, dated to the last
contribution it could price. They must sum to the snapshot's `value` — check that
they do, because a total that does not add up is the one way this could be wrong
while every individual number looks right.

**Run on 2026-08-10, and it holds.** Five runs, each at least a second apart, into a
real `~/.stonksmith/workspaces/default/tsp.db`. The unit count, grade and service date
below were chosen rather than taken from anyone's statement — no TSP account is
involved, and none is needed, because the claim is about what the writer stores and
not about whose number it stores. Everything the run *fetched* was live: the price
file from tsp.gov and the pay table from dfas.mil, in the same run, with no `--prices`
and no `--pay-table`.

```
$ uv run stonksmith tsp -M tsp
[+] L 2060 at $24.8659 as of 2026-08-07
[+] E-7 at Over 12: $5,591.70 basic pay per month
[+] L 2060: 340.000 anchored + 142.173804 estimated = 482.173804 units
    x $24.8659 (2026-08-07) = $11,387.66
```

`show snapshots`, after five runs:

```
| ID | Account    | As Of      | Scraped             | Value      |
| 5  | TSP L 2060 | 2026-08-07 | 2026-08-10 03:51:54 | $12,599.33 |
| 4  | TSP L 2060 | 2026-08-07 | 2026-08-10 03:50:37 | $11,387.66 |
| 3  | TSP L 2060 | 2026-08-07 | 2026-08-10 03:50:34 | $7,852.38  |
| 2  | TSP L 2060 | 2026-08-07 | 2026-08-10 03:50:30 | $11,387.66 |
| 1  | TSP L 2060 | 2026-08-07 | 2026-08-10 03:50:03 | $11,387.66 |
```

Five snapshots, one `accounts` row, five distinct `scraped_at` values. `As Of` is
Friday's price and `Scraped` is Monday's run, on every row — the divergence, without
needing a Sunday: 2026-08-10 was a Monday and the newest published price was still
Friday the 7th.

**Four dates, not three.** The snapshot carries two and each holding carries its own:

```
| Name                                              | Units      | Units As Of |
| L 2060                                            | 340.000    | 2026-01-31  |
| L 2060 (estimated contributions since 2026-01-31) | 142.173804 | 2026-07-31  |
```

The anchored row is dated to the statement, the estimate to the last contribution it
could price — 2026-07-31, which is neither the run date nor the price date. A mark
that stated only one of these four could not be audited later, which is the whole
reason this broker stores them separately.

**And they sum.** This is the check worth doing carefully, so here is the number
rather than the word:

```
holdings:        7853.4402  +  3534.2171  =  11387.657286813865
snapshot.value:                              11387.657286813865
residual:                                    0.0
```

Exactly zero, on all five snapshots. Worth saying that this is not true by
construction: the snapshot computes `(units + accrued) * price` while the two holdings
store `units * price` and `accrued * price` separately, so these are different
floating-point expressions that happen to agree to the bit. A residual around 1e-12
would have been just as much a pass; anything at the cent scale would have meant the
two disagree about what `value` means.

The `--no-accrual` run is snapshot 3, and it is what makes the sum check mean
something: **one** holding row, `$7,852.38`, no estimate. If the writer were producing
the two rows by splitting a total rather than by pricing two separate counts, the sum
would agree no matter what and this control would not differ.

One check only a real database can make: open an existing `tsp.db` — one written before
`holdings.units_as_of` existed — and confirm that marks stored back then show a `Units
As Of` too. Those dates were migrated out of `holdings.raw_value`, and no test can
prove that against your file.

**Done on 2026-08-10, against a database that really was written before the column
existed.** Not a hand-built one — the point of the check is the file, so the file was
produced by checking out `88a5ef4^` (the commit before *Give a holding's unit count a
date of its own*) into a worktree and running it under its own `HOME`. That is
worth the trouble: a database assembled by hand is a guess about what the old code
wrote, and a guess is what the migration is already making.

What that run left behind, read straight out of SQLite:

```
holdings columns: ... currency, raw_value          <- no units_as_of
holding:          name='C Fund' units=100 raw_value='2026-01-31'
```

The date is sitting in `raw_value`, which for every other broker means "the value
exactly as the source wrote it". Then the same file, opened once by current code —
opening is all it takes, since `BrokerDatabase.__init__` runs the migration:

```
[+] Moved 1 unit date(s) for tsp out of raw_value into units_as_of.
    The original text is kept.

| Account    | Name   | Units | Price   | Value      | Units As Of |
| TSP C Fund | C Fund | 100   | $124.93 | $12,493.14 | 2026-01-31  |
```

A `Units As Of` on a row written before there was a column to put it in. Three things
were checked past that headline: `raw_value` still reads `2026-01-31`, so nothing was
destroyed to make the move; the column exists afterwards; and a **second** open prints
no migration line at all, so it is idempotent rather than merely working once.

### 4. The staleness warning fires, and stays quiet

The threshold is 40 days: beyond that the unit count has almost certainly missed a
contribution, since TSP posts at least monthly.

Deliberately old:

```bash
uv run stonksmith tsp -M tsp --units-as-of 2020-01-01
```

```
[!] Unit count is from 2020-01-01 (N days). TSP posts contributions at least monthly, so this mark is probably short by one or more of them. Import a newer statement with -o STATEMENT=<path> to reset it.
```

Fresh — today's date:

```bash
uv run stonksmith tsp -M tsp --units-as-of <today>
```

```
[*] Unit count from <source>, true as of <today>.
```

The warning must come *before* the value, not after. Saying how old a number is only
helps if it is said before the number is read.

### 5. The DFAS pay table downloads at all

**Settled on 2026-08-10, and the premise this step carried for three days was wrong.**
It read: "This is the one step here that could not be attempted", dfas.mil "answered
every request with a 403 — every User-Agent tried", and **re-running this from a third
hosted environment will not help.** The refusals were real and the control that came
with them was sound. The conclusion drawn from them was not.

It was never about the User-Agent. Three things are needed together, and none of them
is sufficient alone:

```text
requests, browser UA + navigation headers          -> 403
requests, session defaults cleared, stock TLS ctx  -> 403
curl --http1.1, browser UA + navigation headers    -> 403
curl --http2,   browser UA + navigation headers    -> 200
httpx, honest stonksmith UA, headers or not        -> 403
httpx, no User-Agent at all                        -> 403
httpx, browser UA, no navigation headers           -> 403
httpx, browser UA + navigation headers             -> 200, 116,257 bytes
```

The client's TLS/ALPN fingerprint, a browser's User-Agent and a browser's `Sec-Fetch-*`
navigation headers. Every earlier attempt varied the second of those while holding the
first fixed, and requests cannot change the first at all: urllib3 pins its own cipher
list, and no header, cleared default or stock `ssl` context moves it. So the pay table —
and only the pay table — now goes out through httpx. tsp.gov and every other broker keep
the requests session and keep being told truthfully who is calling.

**The lesson worth keeping is not the header list.** It is that "a third environment
will not help" was an inference presented as a finding, in a document whose whole
purpose is to keep those apart. Two blocked networks and a control ruled out *a local
proxy*. They never ruled out the request shape, because the request shape had only been
varied along one axis.

The base URL was stale too: DFAS moved the tables to `MilitaryMembers` and answers the
old `Military-Members` path with a 301.

Unattended, through `fetch_pay_table`, no flag:

```
[+] E-7 at Over 12: $5,591.70 basic pay per month
```

#### And the parser did not read it

This is the part the reconstruction was hiding, and it is why the second half of this
step said to do it **either way**.

`tests/dfas_basic_pay_em.html` was a reconstruction: right about every rate — all 44
cells it carried match the real page exactly — and wrong about the markup in two ways.
Against the page DFAS actually serves, the parser returned **zero grades**, while
passing every test.

* The band headings are stacked over a line break, `<b>Over</b><br/>10`, which reads
  back as `Over10` and matched no label. No header row meant no table, and
  `basic_pay_table` skips a table whose header it cannot find — so a page of perfectly
  good rates parsed to `{}`.
* `E-9(Notes 2 & 3)` and `E-1(Notes 4 & 5)` carry footnote markers in the Pay Grade
  column, and `normalize_grade` refused both. That one does not fail; it drops exactly
  those two grades and says nothing, which reads as "DFAS publishes no rate for your
  grade". A senior enlisted member accrues nothing and the run still prints as though
  it worked.

Both are fixed, and the fixture is now the served page trimmed to its two tables and
otherwise byte-for-byte — **do not reflow it, the whitespace is the fixture.** It parses
to all nine enlisted grades, with E-9's low bands still absent rather than zero.

A number that is merely *plausible* was the failure mode to watch for, and it is now
guarded rather than only named. The columns are matched from the right, so a table with
an unexpected trailing column shifts every rate by one band — which reads as a member
paid at the wrong seniority, not as a parse error, and looks entirely like an answer.
`alignment_faults()` refuses such a page and drops the accrual rather than pricing on
it; `missing_upper_table()` reports a page that yielded nothing past `Over 18`. Both ask
the question of the page itself, because a test cannot ask it of a shape nobody serves.

#### The other three pages, 2026-08-11

DFAS publishes four, and only the enlisted one had been read. The officer and warrant
pages had no fixture at all, and the prior-service fixture was a reconstruction whose
**dollar figures were invented outright** — its own header said not to quote it as pay.
All three were fetched through the same client the run uses, 200 each, and all three
now sit in `tests/` as served:

```text
CO      200   127,403 bytes   O-1 .. O-10
CO_FE   200    91,801 bytes   O-1E .. O-3E
WO      200    97,027 bytes   W-1 .. W-5
```

The parser read every grade on every page, with no alignment fault and both halves
present. Two things only the full set could show:

* **DFAS does not mark up its own four pages alike.** The officer pages write
  `<b>Over 10</b>` on one line; the enlisted and warrant pages stack it over a line
  break. Matching a heading with its spacing removed is what makes both spellings the
  same column — a fix that would have looked over-general with one page in hand.
* **The officer page footnotes every grade**, `O-10 (Note 4)` through
  `O-1 (Notes 5, 6 & 7)`, not two of them. Read literally it yields no grades at all,
  where the same bug cost the enlisted page its top and bottom rows.

And the prior-service page prints the **literal word `blank`** in every cell with no
rate, where the other three leave the cell empty:

```html
<td ...> blank</td>   <td ...> blank</td>   <td ...>7,382.70</td>
```

The columns are all present — `2 or less` through `Over 18` in the header, as
everywhere else — but no prior-service rate exists below `Over 4`, because these rates
protect a new officer who already has four years' service. Nothing downstream notices:
`to_number()` returns `None` for `blank` exactly as it does for an empty cell, and an
absent band is what both mean. That is luck rather than design, so a test pins it —
treating a non-empty cell as a published figure would put the string `blank` where a
rate belongs, on the one page that writes it.

None of that could have come from the reconstruction, which had no such cells and
invented the figures around them.

**What this does not settle.** It was run from a hosted environment, so it says nothing
about a home connection beyond the obvious — a network that was refused before is
answering now, given the right client. And DFAS is fingerprinting; what works today is
not a guarantee. If this starts returning 403 again, `--pay-table` with a page saved
from a browser is still the fallback, and the failure message still says so.

### 6. The contribution accrual is arithmetic, not a guess

The accrual is the broker's one estimate, so it is the one number that has to be shown
its working. Settled on 2026-08-10 by the same run as step 3 — prices and pay table
both fetched live, nothing replayed:

```
[*]   2026-02-28: E-7 Over 10 $5,300.40 x 10% = $530.04 at $22.4956 (2026-02-27) = 23.561941 units
[*]   2026-03-31: E-7 Over 10 $5,300.40 x 10% = $530.04 at $21.0565 (2026-03-31) = 25.172275 units
[*]   2026-04-30: E-7 Over 12 $5,591.70 x 10% = $559.17 at $23.1290 (2026-04-30) = 24.176143 units
[*]   2026-05-31: E-7 Over 12 $5,591.70 x 10% = $559.17 at $24.2845 (2026-05-29) = 23.025798 units
[*]   2026-06-30: E-7 Over 12 $5,591.70 x 10% = $559.17 at $24.2990 (2026-06-30) = 23.012058 units
[*]   2026-07-31: E-7 Over 12 $5,591.70 x 10% = $559.17 at $24.0756 (2026-07-31) = 23.225589 units
[+] Contributions since 2026-01-31: 6 month(s), $3,296.76 at 5% member + 5% agency
    = 142.173804 estimated units
```

Every one of those six months was then recomputed **outside the run's code path** —
posting dates re-derived, pay looked up, dollars multiplied, units divided — and
compared field by field: posting date, band, basic pay, dollars, price, price date and
units. All six matched on all seven. Checking only the unit total would have accepted
two errors that cancel.

Four things in that transcript are the reason it was set up the way it was, and each
would pass vacuously under a lazier choice of inputs:

1. **Nothing is counted twice.** The anchor is `2026-01-31`, itself a month-end and so
   itself a posting-date-shaped date. It does not appear in the six. `posting_dates` is
   `start < when <= end`, strictly after, because the contribution that produced the
   anchored count is already *in* the anchored count. An anchor mid-month would never
   have tested this.
2. **The band is recomputed every month, not once.** The service date is 2014-04-20, so
   the twelve-year anniversary falls on 2026-04-20 — inside the window. February and
   March price at `Over 10` and `$5,300.40`; April onward at `Over 12` and `$5,591.70`.
   A window that sat inside one band would agree with a single lookup done once.
3. **The weekend fallback fires inside the accrual.** 2026-02-28 was a Saturday and
   2026-05-31 a Sunday; both priced at the preceding Friday and, crucially, *dated* as
   that Friday — `(2026-02-27)` and `(2026-05-29)`. The other four price on the day.
   Contributions post to a calendar day and the market does not, so this is not an edge
   case, it is two months in six.
4. **The estimate is dated to what it covers.** `units_as_of` on the estimate row is
   `2026-07-31` — the last contribution that could be priced — not the run date and not
   the price date. A month that cannot be priced is left out and said, rather than
   silently valued at zero.

The rates' own effective date is read rather than assumed, and an accrual reaching back
past it says so:

```
$ uv run stonksmith tsp -M tsp --units 340.000 --units-as-of 2025-11-30
[!] 1 of 8 contribution(s) posted before the pay table took effect on 2026-01-01,
    so they are priced at rates that came in after them.
```

(Both flags: `--units-as-of` is only read alongside `--units`.)

**What this does not settle.** The unit count, grade, service date and percentages were
chosen, not read off anyone's LES — so this says the arithmetic is right, not that it
matches any particular member's account. It models neither the IRS deferral limit nor a
mid-year change of grade or contribution rate; a member who hits the cap in November
will be over-estimated for the rest of the year. And the whole estimate rests on
contributions posting monthly, which is the assumption the 40-day staleness warning in
step 5 exists to keep honest.

---

## Fidelity

Five steps, and the only broker here whose whole procedure depends on getting past
something that is actively trying to stop it. Nothing below has been run: every
Fidelity row in the table above rests on unit tests, and unit tests cannot tell you
whether Akamai still refuses the same browsers it refused when this was written.

**What it needs.** A real Fidelity login with 2FA to hand, and a Chrome you can start
yourself for step 2. No stored credential: `--manual-login` needs none, and the CDP
path needs none either.

**Run steps 1 and 2 on different days if you can.** Both establish a session, and a
session established twice in ten minutes says nothing about step 4, which is the one
that matters most.

### 1. The manual sign-in hands off, and the summary is reached

```bash
uv run stonksmith fidelity -M fidelity --manual-login
```

A browser opens. Sign in yourself, 2FA included. Expect:

```
[*] Starting Fidelity sync for: <username>
[*] Found <n> account(s)
[+] Fidelity sync complete.
```

**The hand-off is the claim, not the sign-in.** You signing in proves nothing about
StonkSmith; what this settles is that it waits, recognises the portfolio summary when
it renders, and takes over without navigating first. `--manual-login` implies
`--headed` and needs no credential, so a prompt for one means the flag did not take.

If it reports finding accounts but the count is wrong, that is step 3, not this one.

### 2. Attaching to a browser you started yourself

Start Chrome with the dedicated profile the chapter names, sign in to Fidelity in that
window, then:

```bash
uv run stonksmith --verbose fidelity -M fidelity --browser cdp
```

**StonkSmith must not navigate before you are signed in.** That is the part worth
watching: `brokers.md` records that driving an attached browser before sign-in trips
the bot sensor and flags the Chrome profile permanently, after which even a manual
sign-in is refused and the fix is a fresh `--user-data-dir`. So this check has a cost
when it fails, and a flagged profile is the evidence rather than a stack trace.

If nothing is listening on the debugging port, StonkSmith prints the exact launch
command. That path needs no Fidelity account and can be checked in a second — it is
the cheapest half of this step and settles none of it.

### 3. Account names, numbers and balances parse

From either run above, against what fidelity.com shows you:

- **Every account on the summary is present**, and the count on the `Found <n>` line
  matches what you can see. A run that finds none captures the page instead — the
  path is printed, and `capture_page(reason="no-accounts")` writes HTML and a
  screenshot to `~/.stonksmith/logs` with owner-only permissions. **Attach that
  capture to the issue.** It is the artefact that lets the selector be fixed without
  another sign-in, and `ACCOUNT_BALANCE_SELECTORS` is a one-entry tuple, so a class
  rename is the whole failure.
- **The balance is a number.** Fidelity writes it for screen readers, as
  `", balance:  $1,234.56"`, and `clean_money()` pulls the amount out of that
  sentence. A balance stored as the whole sentence is this check failing quietly:
  the row exists, the account is named, and the money is text.

### 4. The session survives to the next run

The claim that separates Fidelity from Ally, and the reason both are in this file.
`brokers.md` says later runs reuse the saved session and only prompt again when it
expires. Ally's equivalent claim is settled as **Run, and it cannot**.

On a later day, with no browser of your own open:

```bash
uv run stonksmith fidelity -M fidelity
```

Reaching the summary with no sign-in confirms it. A sign-in page instead means the
session did not survive, and *that is a result*: it would make Fidelity unschedulable
for the same reason Ally is, and `docs/scheduling.md` already says Fidelity is
replaced by SnapTrade rather than scheduled — so a failure here confirms the
recommendation rather than breaking anything.

Record which it was, and how long after step 1. "It expired" and "it never persisted"
are different findings, and only the gap between the runs tells them apart.

### 5. The database write

```bash
uv run stonksmithdb
broker fidelity
show accounts
show snapshots
```

One row per account, a snapshot per run, and the balances matching step 3. The
generic form of this is *Every broker* below, and it applies here unchanged.

---

## SnapTrade

Four runs on 2026-08-11, against a real personal key with four brokerages linked —
Schwab, Fidelity, Chase and Interactive Brokers — covering ten accounts. Two of them
were skipped by rules that exist to skip them, and the eight that remained were written
on every run.

```text
[-] Skipped Chase / CREDIT CARD: it is a liability (LOC). Pass --include-liabilities to sync it.
[-] Skipped Schwab / <the 529>: excluded, because another broker covers it.
[+] Syncing 8 account(s)
```

Both skips are the interesting half. The card is a real line of credit carrying a real
negative balance, so `LIABILITY_CATEGORIES` was matched against the thing it was written
for rather than against a fixture; filing it as an asset would have moved the total by
the balance twice over. The 529 exclusion matched a label out of the config against the
label the sync builds, which is the one place `normalize_label()` earns its keep on real
strings rather than on invented ones.

**The four runs are what settle the repeat behaviour.** They landed at 17:05:08,
17:06:05, 17:09:16 and 17:09:36; `show accounts` held at nine rows throughout while
`show snapshots` went 168 → 199, eight per run. Nine rather than eight because the
excluded 529 is still there — see below.

**Positions and transactions were separated on purpose.** The first run carried
`--no-positions --history-days 0`, the second neither:

| After | Accounts | Holdings | Movements |
| --- | --- | --- | --- |
| `--no-positions --history-days 0` | 17 | 2 | 9 |
| the full run | 17 | 9 | 10 |

So the positions call is worth seven rows here and the transactions call one. The two
holdings that survived the first run are other brokers'; SnapTrade contributed none,
which is the flag doing exactly what it says and is why it now carries a warning. **One
movement is not a test of the pagination behind it.** The follow-to-exhaustion loop and
its 20-page backstop are unexercised against the API, and they were going to stay that
way: SnapTrade serves a thousand rows to a request, so the volume that would fill a
second page is volume no workspace here is going to reach. `--page-size` removes the
wait rather than the gap. The loop is now askable of the real API at any size you name,
which turns this from something to wait for into something to run — and nobody has run
it. The procedure is below.

### Following the pages, at a size asked for

**Not run.** This is the procedure for the row above, written when `--page-size` landed
rather than after a run, so that making the run is a sitting rather than a rediscovery.

**Why a flag and not a wait.** `fetch_activities()` asks for a page, keeps what came
back, and asks again until the pagination block reports itself exhausted or twenty
requests have gone out. SnapTrade's own default is a thousand rows to a request, and no
account here has held a thousand movements in ninety days — so every real run this broker
has made took one request and stopped, and the loop around it has only ever turned against
the fake client in `tests/test_snaptrade_broker.py`. That is the evidence this file opens
by saying does not count. `--page-size` supplies the smallness rather than waiting for the
bigness, which is the move [`verify volume`](sheet.md) makes for the sheet and for the
same reason.

**It has to be asked for by name.** Omitted, the flag is left out of the request
altogether and the server's default decides, so an ordinary run sends what it sent before
the argument existed. That is deliberate: a small default would make every nightly run pay
for a check whose answer does not change between runs.

Three things to observe, and they are three runs rather than one.

#### 1. The loop does not stop at the first page

Needs an account holding **between 2 and 20 movements** in the window — more than one, so
there is a second page to follow, and fewer than twenty-one, so the cap in step 2 is not
what ends the read.

Ask for one row a page and `N` movements should cost `N` requests: the live API returns
the envelope with a real `total` — checked against it on 2026-08-17 — so the read ends on
`offset >= total` rather than on the short-page test. That short-page test is the
defensive path, for the SDK versions that unwrap the envelope and hand back no total at
all, and this run does not reach it.

**Run the paged one first, and the ordinary one second. That order is the check.** The
database deduplicates, so the second run writes only what the first one missed — and if
the small-page read dropped movements, the full-sized read behind it puts them back and
the count moves. Run them the other way round and the paged read has nothing left to fail
to find, so the two agree about nothing.

```bash
uv run stonksmith snaptrade --no-sheet --history-days 90 --page-size 1
uv run stonksmith snaptrade --no-sheet --history-days 90
```

**What settles it** is the movement count standing still across the second run. At a page
size below the number of movements in the window, that is only possible if the loop asked
for the second page and every page after it. Record the count before, between and after,
and the window — a pass with no numbers under it is the state this document exists to end.

**Read the count off `read_workspace()`, never off `show transactions`.** That is
`get_transactions`, whose `limit=500` `broker_db.py` says "would report the newest five
hundred movements as though they were all of them", which is why it "cannot back a sheet".
Comparing a read that windows against another read that windows is how this check passes
for the wrong reason — [#141](https://github.com/Gerrrt/StonkSmith/issues/141) records the
sheet's procedure telling people to do exactly that until it was corrected. `verify tabs`
reports that count on its movement line and is the one place it is already printed — it
counts against `read_workspace()` for exactly this reason, which `_count_case()` in
`portfolio_sheet.py` says in as many words.

**If the two counts disagree,** that is this row settled the other way rather than a failed
step, and it is the more interesting outcome by some distance: a small page size losing
rows means the loop stops early, and every full-sized run this broker has ever made was a
single request that never had the chance to show it.

#### 2. The backstop fires, and says it stopped short

`page_limit` is 20 and is not exposed as a flag, so twenty requests is the ceiling. At one
row a page that is **twenty-one movements** in the window — reached by widening
`--history-days` until some account holds that many, which is a far smaller number than
the five hundred [#141](https://github.com/Gerrrt/StonkSmith/issues/141) is waiting on and
is the reason this row is a run rather than a wait.

Expect the account and the cap, both named:

```text
    [-] Stopped reading transactions for account <id> at the 20-page cap. Some movements were not read; narrow the window with --history-days, or raise the page size, and run again.
```

**What settles it is that line appearing at all.** A capped read and a complete read are
indistinguishable from the return value — which is the whole reason the message was
added — so a run that reads twenty-one movements at one row a page and says nothing is
this step failing, not passing. Record the movement count as well: the read is *supposed*
to come back short here, and a step whose expected outcome is a short read has to say how
short.

#### 3. A page size the API would refuse is refused before the wire

```bash
uv run stonksmith snaptrade --page-size 0
```

```text
stonksmith snaptrade: error: argument --page-size: page size must be at least 1, not 0
```

Exit `2`, from `argparse`, before anything is asked of the network. Zero is the value worth
naming because it does not simply fail: it passes `page_size is not None`, so `limit=0`
would reach the wire against a schema whose stated minimum is 1, and `len(rows) <
page_size` can never be true against it — so a read carrying no total would run to the
twenty-page cap instead of stopping. `positive_page_size()` in
`brokers/snaptrade/broker_args.py` is where it stops instead.

This step costs no API call and needs no credential, so unlike the two above it can be run
anywhere. It was run on 2026-08-17 and the output above is what it printed — which settles
nothing in the table, because the row is about the loop and this is about the parser in
front of it.

### What an exclusion does not do

`exclude_accounts` was added *after* SnapTrade had already synced the 529, and the rows
from those earlier runs are still in `snaptrade.db` — account row and snapshots both. All
four runs above skipped it correctly, and the account still renders on the tab at its
last-synced value.

That is the row settled the other way. The exclusion is a filter inside the sync; it has
no reach into what a previous sync wrote, and nothing at the portfolio layer filters
anything, because `load_workspace()` reads every database in the workspace. So an
overlap resolved after the fact stays double-counted, and reads exactly like an overlap
that was resolved. [`brokers.md`](brokers.md#neither-remedy-touches-what-is-already-on-disk)
carries the consequence and what to do instead.

The row stays settled the other way, because it is a claim about `exclude_accounts`
and that has not changed. What has is that the stranded rows are now removable:
`delete account <id>` in the broker sub-shell takes the account and cascades its
snapshots, holdings and transactions away. It is the second half of an operation
whose first half is the exclusion — the deletion only sticks because the source
has been made to stop reporting the account — so it settles the consequence
rather than this row. Nothing here has been run against the real `snaptrade.db`,
so no claim is opened for it; the command's own behaviour is covered by
`tests/test_delete_account.py` against a real SQLite file.

Three rows stay `No`, and the third is not like the other two. A disabled connection needs
a connection to actually lapse — SnapTrade goes on serving its last cached balance rather
than erroring, which is the whole reason the guard exists and the reason it cannot be
staged. The freshness guard needs holdings that have actually gone stale; every real
account here had synced that morning, so `--max-age-days` has never been handed anything
to reject. Neither is waiting on effort, and no amount of sitting at the machine produces
either.

The pagination row is waiting on effort, and only on effort. It used to belong with the
other two — it wanted a thousand movements, which this workspace was not going to grow —
and `--page-size` is what moved it, by letting the size be asked for instead of waited
for. So it is the one `No` in this section that somebody can turn into a `Yes` on an
afternoon, and the procedure above is written for whoever has the credentials to do it.

---

## Schwab 529

One run on 2026-08-11 against the live aggregator, by stored credential id rather than
by password on the command line:

```text
[!] Attempting login for <username>
[+] Login successful for <username>
[!] Starting Schwab529 sync
[!] Updating local broker database...
```

The form post is the whole login — no browser, no session to keep, nothing to
re-authorise — and it worked against the real site with a credential read out of the
keyring. That is the claim this broker's place in the scheduling table rested on, and it
rested on how the code was built until this run.

The parse added one holding and one movement to the workspace, taking it from 9 holdings
and 10 movements to 10 and 11. Small numbers, and they settle the two parses at exactly
that size: the overview page yielded an account and its holding, the activity page a
movement, both from pages served that morning.

**What one beneficiary cannot settle** is the rule for telling several apart.
`match_account()` tries an exact match, then a shared trailing run of digits, then a
candidate name inside the hint, and returns nothing on a collision — and a page with one
beneficiary on it never reaches the second or third rule, let alone the collision. That
row stays `No` and needs a second beneficiary rather than a second sitting.

---

## The sheet

Eight checks and a refusal, and it sits outside the broker sections because the sheet is
not any broker's. One `sheet` run reads every database in the workspace, so the tabs it
writes are as much Fidelity's and SnapTrade's as TSP's, and the three *The sheet — …*
rows in the table above, and the *account series* row beside them, settle for all of
them at once. This procedure lived under *TSP*
until it was moved here, because TSP was the broker it happened to be written against.

**This is the one procedure on this page that needs a credential, and the account it
needs is not a broker's.** No sign-in to anything StonkSmith scrapes, no browser it
drives. It is also the only one here that writes anywhere but a local database.

**What it needs.** An OAuth client `gspread.oauth()` can authorize — a Desktop-app
client ID with **both** the Sheets and the Drive API enabled, saved as
`~/.config/gspread/credentials.json`, the path `GSPREAD_CONFIG_DIR` in
`src/stonksmith/helpers/sheets.py` names — and a spreadsheet called `Investment Account Scrapes` in
that Google account or shared with it. That name is `SPREADSHEET_NAME` in the same file
and nothing reads it from config. Then a workspace with at least one broker database
already in it, and for check 5 specifically, a broker with a long transaction history
rather than a fresh one — for the windowing half of it, which is the half `verify volume`
cannot supply its own rows for.

**If a token is already cached, expect the first attempt to fail on authorization.** A
first run with none authorizes in a browser and is fine; it is the returning one that
breaks, and a client left in Google's *Testing* publishing status expires its refresh
token after seven days, so returning is the common case. A token that has expired or been
revoked comes back as `invalid_grant`, and the fix is one line — delete
`~/.config/gspread/authorized_user.json` and run `sheet` again, which reauthorizes in a
browser. `credentials.json` stays.

The program says that now. It did not when this was first run, which is why it is written
down here: the branch an expired token actually reaches is the lazy refresh on the first
API call, and that one reported the failure with no fix attached at all, while the branch
that *did* carry advice blamed a deleted OAuth client and sent you to the console for a
new client ID. Those are two different failures with two different fixes, and
`tests/test_sheets_errors_and_labels.py` now holds them apart — `invalid_grant` gets the
one file to delete, `deleted_client` gets the new client, and an unrecognised failure gets
the cheap fix first and the expensive one as the fallback.

**What it costs.** `sheet` clears and rewrites all five machine-owned tabs, and the
refusal at the end has you deface the `Holdings` tab on purpose and hand it back
afterwards. So this runs against a spreadsheet you are willing to have rewritten, which
in practice means the real one. That is the whole reason these four rows are still `No`
while others are settled: nothing in the procedure is difficult, but it needs a Google
account and a database with real rows in it, and neither is available to anything
holding only this repository.

No tab needs creating: StonkSmith makes `Accounts`, `Holdings`, `Transactions`,
`Net Worth` and `Dashboard` on the first sync. Nor does this need a scrape — the sheet is a view of the
databases, so it can be built from them alone:

```
$ uv run stonksmithdb
stonksmithdb (default) > sheet
[*] Refreshed: 6 accounts, 23 holdings, 412 movements from ally, fidelity, snaptrade, tsp.
```

A workspace where one database will not open reports it and syncs the rest, one line per
broker: `[-] Not on the sheet: <name> could not be read (<reason>).` If *every* database
fails, the sheet is left as it was rather than emptied and the run says so instead of
printing a count — clearing the tabs there would replace a correct sheet with a blank
one and report success for doing it.

Seven things to confirm on the tabs themselves, none of which a unit test can see.
**`verify tabs` now does most of it**, by reading the tabs back:

```
stonksmithdb (default) > verify tabs
[*] Reading the four tabs back from 'Investment Account Scrapes'.
[+] All 4 tabs carry the banner in A1
[+] Accounts row 2 is the column contract, ending at J
[+] Holdings row 2 is the column contract, ending at P
[+] Transactions row 2 is the column contract, ending at O
[+] Transactions holds all 9 movements the databases have
[+] Every Processed On is YYYY-MM-DD
[+] Processed On runs newest-first within each account
[+] Accounts Value is a number, not text (assertion unconfirmed against real Sheets)
[+] The dashboard's two totals agree (assertion unconfirmed against real Sheets)
[*] All 9 checks behaved, against real Sheets rather than a stub. Two things they cannot cover are still in docs/live-verification.md: a refusal aborting the whole sync, and an absent value arriving as an empty cell.
```

That is a real session, 2026-08-10, against the real spreadsheet, **quoted as it came out** —
which is why it does not match what you will see today. Two things changed *because* of it:
the last two lines no longer carry `(assertion unconfirmed against real Sheets)`, and the
summary now names only the gap belonging to the half that ran, so a `verify tabs` run does not
mention the refusal.

**Those markers coming off is the interesting part.** Seven of the nine checks compare strings
and cannot be wrong
about the API. The other two ask what a rendered cell comes back *as*, which was an
assumption about gspread that no unit test could settle — so they said so, and a `[-]` on
either would have been ambiguous between a wrong sheet and a wrong check. The pass resolved
it in both directions at once: had `unformatted` returned display text, every money cell
would have been rejected as text, and a formula arriving as its own source would have failed
`float()` into "could not read both". Neither happened, so the sheet is right *and* the two
assertions are.

There are ten checks now, not nine: `Net Worth` is a fifth machine-owned tab with a column
contract of its own, so the banner line counts five and a tenth line reads its row 2 back.
That tenth check has been run, on 2026-08-11, against the same real spreadsheet:

```
stonksmithdb (default) > sheet
[*] Refreshed: 16 accounts, 9 holdings, 9 movements from ally, fidelity, schwab529plan, snaptrade, tsp.
stonksmithdb (default) > verify tabs
[*] Reading the tabs back from 'Investment Account Scrapes'.
[+] All 5 tabs carry the banner in A1
[+] Accounts row 2 is the column contract, ending at J
[+] Holdings row 2 is the column contract, ending at P
[+] Transactions row 2 is the column contract, ending at O
[+] Net Worth row 2 is the column contract, ending at K
[+] Transactions holds all 9 movements the databases have
[+] Every Processed On is YYYY-MM-DD
[+] Processed On runs newest-first within each account
[+] Accounts Value is a number, not text
[+] The dashboard's two totals agree
[*] All 10 checks behaved, against real Sheets rather than a stub. One thing it cannot cover is still in docs/live-verification.md: an absent value arriving as an empty cell.
```

Also quoted as it came out. Three things in it are worth reading rather than skimming past.
The banner line counts **five**, so `Net Worth` was written and carries the banner. `Net Worth
row 2 ... ending at K` is the eleven-column contract read back off the real tab, which is the
check that did not exist in August. And the last two lines arrive **unmarked** — the markers
came off in code after 2026-08-10, and this is the first run since to put that to the test on
a sheet written from scratch that morning.

**It settles the tab, and not the series.** Everything above is one read of one tab. Checks 6
and 7 below are arithmetic across dates and a question about rows that are *absent*, and no
column contract read back can reach either. They stayed outstanding until 2026-08-15, when a
workspace that had been running unattended for a fortnight finally had brokers entering the
series twelve days apart and going quiet for up to six days inside it; that run is quoted
under *Nine dates, twelve accounts* below.

**This run also made the tab, which is the creation half of check 1.** The spreadsheet carried
four machine-owned tabs on 2026-08-10, no `sheet` run happened between then and this one, and
afterwards there are five carrying the banner — so `ensure_worksheet` created `Net Worth` here
and `claim()` adopted it empty before writing.

That is three facts rather than a quoted line, and it is worth saying which kind of evidence
it is. A tab that was created and a tab that was already there read back identically, so no
`verify tabs` output could show this; what settles it is that the tab did not exist before the
run and did after. The same holds for the four tabs on 2026-08-10, whose creation half is
recorded above as reported rather than transcribed. If it turns out a run did happen in
between, this paragraph is the one that was wrong.

**Check 4 is not in that list, and could not have been.** It is a question about a formula's
behaviour rather than about a cell's contents, so a read cannot answer it: an empty cell and
an empty string come back the same, as `""` or a short row. It stays an eyeball check, and it
is the reason this section still asks you to look — though not for the reason it used to give.
See check 4 below.

The eight checks, and which of them `verify tabs` settles:

1. **The first cell of every tab carries the machine-owned banner** — *settled, 2026-08-10,
   by `verify tabs`, and the creation half separately: the four tabs then defined were
   deleted and `sheet` run again, which made them and adopted them empty before writing.
   `Net Worth` came later and got both halves on 2026-08-11, in one run that made it
   and then read it back.* All five,
   `Dashboard` included, since a banner cannot be read back off a tab that was never
   created. On the four that carry columns, row 2 is the column contract exactly as
   `src/stonksmith/etc/portfolio.py` spells it; the dashboard has no such row, and its labels run
   down the summary column instead. `Holdings` is the one worth counting: sixteen
   columns, ending at `P`, `Units As Of` — `HOLDING_COLUMNS` in that same file. A tab
   still ending at `O` after a sync is a visible sign the sync did not run, and TSP is
   the broker where the price date and the unit date visibly differ. `Net Worth` is
   eleven, ending at `K`, and its absence altogether is that same signal one change
   later.
2. **Money is a number, not text.** *Settled, 2026-08-10, by `verify tabs`.* By eye, if you
   want it twice: a currency cell should right-align on its own and accept a number format.
   If it left-aligns, something is writing strings again.
3. **The dashboard's `Total (USD)` equals its `Total as read`.** *Settled, 2026-08-10, by
   `verify tabs`, which finds them by label rather than by row so a reordered summary fails
   here instead of comparing the wrong two cells.* Those are the same
   number computed by Sheets and by Python; a disagreement means the write was
   truncated, and it is the only signal that would say so.
4. **An account with no date is surfaced, not silently counted at full value.**
   **Done, 2026-08-10: 7 of 7.** *One look at the Dashboard.* Find an account on `Accounts`
   whose `As Of` is blank — its source gave no date — and confirm it appears in the
   **staleness panel**, which starts at `J2` and runs `J:M` under the headers
   `Broker | Account | As Of | Scraped At`. Of 16 accounts, 7 had a blank `As Of` and all 7
   were listed. If every account in the workspace has an `As Of`, this cannot be exercised at
   all, and *that* is the result: say so rather than ticking it.

   Expect more rows in the panel than undated accounts, and do not read that as a failure:
   the QUERY also lists accounts merely older than the cutoff. Being empty is the ambiguous
   outcome — the formula is wrapped in `IFERROR(..., "")`, so an error renders as blank
   rather than as `#REF!`.

   The panel is the whole of the mechanism. `_bands()` selects accounts
   `where Account Key is not null and (As Of is null or As Of < '<cutoff>')`, and `As Of`
   appears in no other dashboard formula — so an undated account being listed there is the
   only thing standing between it and being counted at face value.

   **This check used to describe something else, and that something never existed.** It
   said the dashboard counted undated accounts by subtracting a count of `As Of` values
   from `Accounts`, and that the fix for a wrong figure was `COUNTIF(...,"<>")`. There has
   never been such a figure: the dashboard's three `COUNTA`s are all on `Account Key`
   columns, and every commit that has touched `portfolio_sheet.py` was checked — including
   `5ab8386`, which wrote this check, and which already had the staleness QUERY. So the
   instruction pointed at a cell nobody could find and a formula nobody could edit.

   **A consequence worth keeping:** the empty-cell-versus-empty-string distinction the old
   wording turned on is currently *inert*. A truly empty cell is caught by `As Of is null`;
   an empty string is not null, but `"" < '<cutoff>'` is true, because the column holds text
   and not dates — which the RAW write guarantees, and which the module docstring explains
   at length. Either way the account is listed, so no figure on the dashboard changes
   between the two, and there is nothing to observe. That stops being true the day a
   `COUNTA` or `COUNTIF` lands on `As Of`: such a formula would count an empty string and
   report zero undated accounts on a tab that visibly has them. Bring the check back then.
   (The `<` arm rests on how QUERY treats an empty string in a text column, which nothing
   here exercises — reasoning, not an observation.)
5. **`Transactions` holds every movement, not the newest five hundred.** Two questions
   that used to be run together, and only one of them needs a big workspace.

   *Did every row land* is answerable at any size, but **not against
   `show transactions`** — that is `get_transactions`, and `broker_db.py` says of its
   `limit=500` that it "would report the newest five hundred movements as though they
   were all of them," which is why it "cannot back a sheet." Comparing an uncapped
   write against a capped read is how this check passes for the wrong reason. Count the
   rows in the database instead, which is what the sheet is built from:

   ```bash
   sqlite3 ~/.stonksmith/workspaces/default/<broker>.db \
     'SELECT COUNT(*) FROM transactions;'
   ```

   *Is there a window at five hundred* is the question that needs the rows, and no
   workspace under that number can put it — a tab that had silently windowed would
   agree with everything.

   *Does a second chunked write reach Sheets at all* used to need the rows too, and
   no longer does. **`verify volume` asks it**, and it is the same move as `verify
   guard`: `write_rows()` decides on the rows and the contract it is handed, not on
   where they came from, so it can be sent `CHUNK_ROWS + 500` synthetic rows on a tab
   made for the purpose and removed afterwards. It has to be named — bare `verify`
   does not run it — and it refuses a size that would fit in one request, since that
   would pass without asking anything.

   ```
   $ uv run stonksmithdb verify volume
   [*] Making the tab 'StonkSmith volume check' in 'Investment Account Scrapes', writing 2500 rows to it as two requests, reading them back, and deleting it again. No other tab is opened.
   [+] All 2500 rows came back off the tab
   [+] The 4 rows at the edges of the 2 writes are the ones sent there
   [+] The throwaway tab was removed
   [*] All 3 checks behaved, against real Sheets rather than a stub. One thing it cannot cover is still in docs/live-verification.md: whether the real Transactions tab windows, which is upstream of the write and needs a broker with the movements.
   ```

   **Run, and it holds: 2026-08-15, against the real spreadsheet, quoted as it came
   out.** Two thousand five hundred rows went up as two requests and two thousand
   five hundred came back, with the first and last row of each write in the cell it
   was addressed to. So `write_rows()` past `CHUNK_ROWS` is no longer an assumption
   about the API.

   **This block replaced one written from the test double, and the two were
   identical.** That is worth saying plainly rather than quietly deleting, because
   the tempting reading of it is the wrong one. It does not show the double was
   evidence — the whole argument of this page is that a double is a replay, and a
   replay agreeing with itself is not news. What it shows is the ordinary case: the
   run was needed precisely because agreement could not be known in advance, and had
   the two disagreed the double would have been the thing that was wrong. Predicting
   the output correctly is not the same as having observed it, and only the second
   moved this paragraph.

   It is also the scripted form rather than the shell prompt the other blocks on this
   page show. `verify` takes words after the command name and exits `1` on a finding,
   which is the form worth quoting for something a schedule might one day run.

   What a failure reads like is worth knowing before you need it, and this one has
   not been seen against real Sheets — it is the mutation from
   `tests/test_portfolio_sheet_volume.py`, and it is labelled because the block above
   used to carry the same caveat. A second request landing one row low keeps the
   count and moves the boundary:

   ```
   [+] All 2500 rows came back off the tab
   [-] The 4 rows at the edges of the 2 writes are the ones sent there
       Expected in place: row 2003 holds nothing, not write-2-row-2003
   ```

   The marker names the request it belonged to and the sheet row it was addressed
   to, so that line is read rather than worked out — and the count agreeing above it
   is the point: every row arrived, and a check that only counted would have called
   this clean.

   **What it settled and what it did not.** It settled the write: two requests
   landed, and the first and last row of each was in the place it was sent to
   — which a count alone cannot say, since a chunk at the wrong range leaves the
   right number of rows in the wrong cells. It settled nothing about the real
   `Transactions` tab. Those rows come from `read_workspace()`, and synthetic ones
   enter below it, so a window between the databases and the cells was untouched by
   the run passing. **That half still needs the movements, and this row stays `No`
   until it has them** — a passing volume check is not a partial `Yes` here, because
   the two halves are not two degrees of the same question.

   Check the dates too: the 529 scraper stores `12/30/2025` and SnapTrade
   stores ISO, so the tab is where they must both read `YYYY-MM-DD`, sorted
   newest-first within each account. A `12/30/2025` reaching a cell means the
   normalization was skipped, and the tab's order is then wrong wherever a December
   row sits above a January one.
6. **`Net Worth` totals the same set of accounts on every date.** *`verify tabs` reads
   this tab's column contract back with the other three and settles nothing else about
   it — the carry-forward is arithmetic across dates, and no read of one tab can check
   it.* Pivot `Value` by
   `Date` on the tab, or read the dashboard's net worth band, and walk the account
   count down the dates. It may only ever grow — an account joins the series at its
   first reading and leaves it only after thirty days of silence — so a count that
   drops and recovers between two adjacent dates means the carry-forward is not
   running and the chart is drawing scrape timing rather than money. This needs a
   workspace whose brokers genuinely did not all run on the same day, which is the
   ordinary state of a real one and not of a freshly built one: run `sheet` against a
   workspace where Ally last went a week ago and TSP ran this morning.

   **Run, and it holds: 2026-08-15**, against a workspace of that shape, walked
   below. Nine dates, and the count went `1, 7, 7, 9, 9, 11, 11, 11, 12` — it grew four
   times, held four, and never fell. The observed-only count over the same dates is
   `1, 7, 6, 2, 3, 10, 11, 11, 10`, which falls three times: that gap is the
   carry-forward, and it is what the check exists to see. **The thirty-day horizon was
   not exercised** — the longest silence in that workspace is six days, so this settles
   the carry and not its expiry.
7. **Carried rows are visibly carried, and no row is a back-filled zero.** *The other
   check no command makes, and for a different reason than check 4: a row that is
   absent cannot be read back, so the thing being checked is what is not there.* Every
   row
   reads `observed` or `carried` in `Basis` and never blank; a `carried` row's
   `Observed On` is older than its `Date`, and an `observed` row's is equal to it.
   Then look at the earliest dates: an account whose first reading came later must
   have *no row at all* before it, rather than a row worth `0`. A zero there would
   total correctly and be a lie about an account that did not exist yet.

   **Run, and it holds: 2026-08-15**, off the same 78 rows. Every one reads `observed`
   or `carried` and none is blank; all 17 `carried` rows date `Observed On` before their
   `Date` and all 61 `observed` rows date it equal. Eleven of the twelve accounts joined
   after the first date, on four later dates, and the last of them joined on the ninth
   with eight dates behind it — none has a row before the date it joined on, and none
   has a zero standing where one would be. The absence is the finding, and it is the
   half no `verify` can reach.

8. **Every allocation block adds up to the total it is a share of.** *`verify tabs`
   reads this, and until recently nothing did.* Each block ends with a `Slices sum to`
   row — the sheet's own arithmetic over the cells it wrote — and the check reads that
   row back: the values must come to `Total (USD)` to the cent, and the shares to `1`.
   Both blocks that are always drawn are checked, and the asset class block as well
   whenever `asset_classes` is configured, which is why the check consults the same
   config the sync did rather than inferring from the tab. An absent block and a block
   that failed to write look identical otherwise.

   The row was there from the beginning and was read by nobody, which is the failure
   this file exists for: a block whose shares came to `0.8` would have been written,
   reported as a success, and agreed with by every other check above. What settles this
   row is a run where all three states are seen — a correct sheet passing, and, if the
   workspace ever produces one, a refusal passing as the block working rather than
   failing. A refusal cannot be arranged on demand; it needs positions exceeding
   balances, so seeing only the passing state is the expected outcome and worth saying
   so rather than leaving the row ambiguous.

   **Run, and it holds: 2026-08-15**, in the same `verify tabs` quoted below. All three
   blocks were drawn and all three read back — `The account kind allocation adds up`,
   `The position allocation adds up`, `The asset class allocation adds up` — which is
   why that run counts thirteen checks where 2026-08-11 counted ten. The asset class
   line appearing at all is the config half working: it is drawn only when
   `asset_classes` is set, and a check that inferred from the tab could not tell that
   from a block that failed to write. The refusal state was not seen, as expected.

**Then the refusal, which is the point of the whole thing — and it goes last.** A
refused tab means nothing is synced at all, so doing this first would leave the eight
checks above reading a sheet the run never wrote.

Most of it no longer needs a deface. `verify guard` asks `claim()` all three of its
questions on a tab it creates and removes, so the guard meets real Sheets without a real tab
being touched:

```
stonksmithdb (default) > verify guard
[*] Making the tab 'StonkSmith ownership check' in 'Investment Account Scrapes', asking the guard about it, and deleting it again. No other tab is opened.
[+] A defaced first cell is refused
[+] Text below a blank first cell is refused
[+] A wholly empty tab is adopted
[+] The throwaway tab was removed
[*] All 4 checks behaved, against real Sheets rather than a stub. Two things they cannot cover are still in docs/live-verification.md: a refusal aborting the whole sync, and an absent value arriving as an empty cell.
```

Also a real session, the same day, also quoted as it came out: today that last line names only
the abort, since the empty-cell gap belongs to `verify tabs` and this run was the guard half.
Bare `verify` runs both halves, tabs first, and names both.

The third case is the one that had never been reached before: both 2026-08-10 syncs found the
banner in `A1` and answered on the first read, so nothing had exercised the branch that
decides whether an *empty* tab can be handed over. It can.

That works because `claim()` decides on what a tab *holds*, not on what it is called —
`MACHINE_OWNED_TABS` only picks which tabs a sync claims. The third case is the one
neither 2026-08-10 run reached: both had the banner in `A1`, so `claim()` answered on its
first read and never took the branch that decides whether an empty tab can be handed over.
A `[-]` line is the finding, and an adoption where a refusal was due is the expensive one.

**It does not retire the manual step.** What `verify` cannot show is that a refusal stops
the *whole* sync rather than leaving one tab freshly written beside a stale one — that is
`refresh()` claiming every tab before clearing any, and the scratch tab is not one of the
four. So the deface below is still worth doing, and it was, on 2026-08-10: both paths refused
against the real `Holdings` tab, which is what moved this row to `Yes`.

That leaves one part of it observed by structure rather than by a run, and this is the honest
limit of the exercise. A refusal aborting before any tab is written means `Accounts` should be
untouched — but a workspace whose data has not changed cannot show the difference, because a
rewritten `Accounts` and an untouched one hold the same rows. It rests on the claim loop
running before any write and on `test_nothing_is_written_when_a_tab_is_refused`. Do the deface
on a day the numbers moved and it becomes observable; otherwise the run cannot put the
question, in the same way nine movements cannot put the windowing one.

By this point `Holdings` exists and carries the banner, and Sheets will not let a second
tab take a name already in use — so the move is to make the tab that is there look
hand-written rather than to bring in a new one. Type something of your own over `A1`,
replacing the banner, and run `sheet` again:

```
[-] Tab 'Holdings' holds something StonkSmith did not write, so it was left
    untouched and nothing was synced. StonkSmith rewrites this tab from scratch
    every run and would have lost whatever is on it. Move your work to a tab of
    your own, empty this one to hand it over, or delete it and let the next sync
    recreate it.
```

Then the subtler path, which is the one actually worth exercising: clear `A1` and leave
your text somewhere below it instead. A blank first cell is exactly the shape a leftover
layout has, and exactly the shape a tab someone started on row 3 has, so `claim()` reads
the whole tab before deciding rather than adopting it on the strength of an empty corner.
The same refusal should come back. An adoption here — a sync that went ahead — is the
finding, and it is the expensive one, because that is the shape a person's own tab has.

Either way, confirm your text is still there, and that `Accounts` was **not** rewritten
either — every tab is claimed before any of them is cleared, so a refusal costs nothing
rather than leaving one tab fresh beside a stale one. To get the sheet back afterwards,
empty that tab or delete it and run `sheet` once more; an empty tab is adopted, which is
the third way out the message offers.

**What this settles.** Six rows, and each check belongs to exactly one of them.

*The sheet — the machine-owned tabs* is checks 1 through 4: the banner on all of them and
the column contract on the ones that have one, money arriving as a number, the
dashboard's two totals agreeing, and an account with no date being surfaced rather than
counted at face value. Those are four ways for a tab StonkSmith owns to be written wrongly
while looking written. There is a fifth thing this section opens by asserting — that
StonkSmith *makes* the tabs — which a spreadsheet already holding them cannot show;
that was settled on its own, by deleting the four then defined and running `sheet` again.
Anyone re-running against an established spreadsheet is back to observing the write and not
the creation, so delete them, or point at a fresh spreadsheet, to see that half.

That run predates `Net Worth`, so the row it settles is the four tabs it read. The fifth
tab's banner, its column contract and its creation all belong to the row below, which is
why widening this one to five would have quietly turned a settled row into a claim about a
tab nothing has ever written.

*The sheet — the whole transaction history reaching a tab* is check 5 alone, and it has a
wrong way to pass: agreement with `show transactions` confirms nothing, at any size,
because that reader stops where the question starts. Counting the database settles whether
every row landed; only a workspace past five hundred settles whether there is a window.
The date half of the check belongs to this row too, and needs no volume at all.

The second chunked write used to be listed here as a third thing needing volume. It is not
one: `verify volume` sends the rows itself, and that run happened on 2026-08-15 and passed.
The row stays `No` all the same, which is the part worth reading rather than skimming past —
the window is upstream of the write, so nothing sending its own rows can reach it, and a
check that passed says nothing either way about the question this row asks.

*The sheet — the fifth tab, `Net Worth`, created, written and read back* is what checks 1
through 3 reach on the fifth tab, and it was settled on 2026-08-11: one run made the tab,
wrote it, counted five banners and read the eleven-column contract back off it.

*The sheet — the account series carried across brokers that scraped on different days* is
checks 6 and 7, and splitting it off from the row above is the point rather than
bookkeeping. The tab existing and being shaped right is a read; the series being *true* is
arithmetic across dates, and the 2026-08-11 run confirmed the first while touching none of
the second. It was also the one row here that no amount of care with a fresh spreadsheet
could settle: it needed a workspace whose brokers really did run on different days, because
a workspace where they all ran this morning produces a one-date series that passes both
checks by having nothing to carry. **Settled on 2026-08-15**, when one had been running
unattended long enough to be that — and the reasoning above is why the row could not have
been ticked before then rather than an excuse for it having taken four days.

*The sheet — every allocation block adding up to the total it is a share of* is check 8,
and it is the odd one here: the row was outstanding not because the evidence was hard to
get but because the check reading it was younger than every run on this page. It needed
nothing but the next `verify tabs`, which is why it settled on 2026-08-15 alongside a row
that had been waiting on the calendar. Worth telling those two apart when reading the
count above — a row can be outstanding because nobody has got round to it, and that is a
different thing from one that cannot be asked yet.

*The sheet — refusing a tab it does not own* is the refusal, and what marks it out is that
the question could be put on the day: the row still outstanding waits on a workspace nobody
here has, and this one only ever waited on somebody willing to deface a tab. It is not the
only row that could come back settled the other way — a `Transactions` tab found holding
five hundred of six hundred movements would be that too — but it is the one where asking
costs nothing but nerve. A sync that went ahead and ate your text is not a failed check; it
is that row observed as **Run, and it cannot** be relied on. Write it up that way, and say
which tab. `verify` covers `claim()`'s three answers and not the
abort, so a clean `verify` and no deface leaves this row where it is.

Then *Recording a result* below, which is where the asymmetry it warns about actually
bites: one `sheet` run touches all six of these rows, and the refusal is the only one
that writes itself up. The 2026-08-15 run is that warning working — it was made for the
carried series and settled the allocation blocks on the way past, and the second row would
have been easy to leave unrecorded because nothing about it failed.

### Run twice, on 2026-08-10

The sync itself worked, on the second attempt — the first died on the expired token
described above. Having deleted the cached token, the run reauthorized first:

```
stonksmithdb (default) > sheet
Please visit this URL to authorize this application: https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=<elided>&redirect_uri=http%3A%2F%2Flocalhost%3A<port>%2F&scope=...auth%2Fspreadsheets+...auth%2Fdrive&state=<elided>&code_challenge=<elided>&code_challenge_method=S256&access_type=offline
[*] Refreshed: 16 accounts, 9 holdings, 9 movements from ally, fidelity, schwab529plan, snaptrade, tsp.
```

The client ID, the callback port and the PKCE parameters are elided; the two scopes are
not, because which scopes are asked for is the part worth checking against
*What it needs* above. Then again, deliberately, because a second run settles something
the first cannot:

```
stonksmithdb (default) > sheet
[*] Refreshed: 16 accounts, 9 holdings, 9 movements from ally, fidelity, schwab529plan, snaptrade, tsp.
```

Same counts, same five brokers, and **no authorization line the second time** — which is
the signature of the new token being cached and working rather than of nothing happening.
That absence is why both transcripts are quoted in full rather than trimmed to the
`Refreshed:` line: it is evidence, and a trimmed pair would have looked identical.

**What the first line establishes on its own**, before anybody opens the spreadsheet:
authorization succeeded, `Investment Account Scrapes` was found, all four tabs were
ensured, **`claim()` accepted all four before any of them was cleared**, and three
`write_rows()` calls plus the dashboard completed against real Sheets. Five broker
databases opened, and no `[-] Not on the sheet:` line means none was skipped. So the
machinery — the authorization, the four-tab claim, the chunked RAW write — has now met
the real thing rather than a `MagicMock`.

**What the second run adds is the banner round-trip**, and it is worth spelling out,
because it does not follow from the counts being the same. `refresh()` opens fresh
worksheet handles every time, and `claim()` remembers its answer on the handle rather
than in the module, so a second run cannot inherit the first one's verdict: it has to
read `A1` again, over the network, on all four tabs. By then those tabs were not empty —
the first run had filled them — so the blank-`A1` path was not available either, since
`claim()` answers a blank first cell by reading the whole tab and refusing it if anything
is there. The only way all four could be accepted a second time is if `A1` came back
holding exactly `BANNER`, after `.strip()`.

That rules out the failure which would be worst to find late. A banner that Sheets stored
differently from how it was sent — truncated, re-quoted, whitespace-folded, or turned into
something `USER_ENTERED` would have parsed — would make StonkSmith refuse its own four
tabs on every subsequent run, permanently, with a message blaming data the user never
wrote. It is the one way the safety property could invert into a total lockout, and it is
now ruled out against real Sheets rather than against a stub that returns whatever it was
handed.

Two runs also make the view idempotent in practice and not just by construction: the
counts held, so the second sync neither appended to the tabs nor drifted from the
databases it reads.

**All four rows are still `No`, for four different reasons** — the fourth trivially, in
that *the account series* postdates these runs and was not written by them at all. A write that returns says
nothing about how the values *render*, and rendering is exactly what checks 2 through 4
are for: money can arrive as text, the dashboard's two totals can disagree, and an absent
value can arrive as an empty string, all through a RAW upload that reports success.
Nobody looked, so *five machine-owned tabs* stands unsettled. The refusal was never run,
and the accept path succeeding four times says nothing about the refuse path — which is
the one whose failure costs somebody their work. And 9 movements cannot settle
*the whole transaction history reaching a tab* at all: the reader stops at 500, so a tab
that had silently windowed would have agreed with the shell exactly.

**What would finish it.** Running twice was the cheapest evidence available and it is
spent; what is left needs eyes or a deliberate act. Open the spreadsheet once for the
column contract and checks 2 through 4, and *five machine-owned tabs* is done — that is
one sitting, and the banner half of check 1 is already behind you. Then the refusal, which
needs the deface and is the only one of the four that can be settled the other way. The
transaction row is the odd one out: it needs a workspace with a few hundred movements at
least, and past 2,000 to put a second chunked write in front of Sheets, so it waits on a
broker rather than on an afternoon.

### The verification run, the same day

Most of that was then done, in one sitting: a sync, `verify tabs`, `verify guard`, and the
deface. Both transcripts are quoted in the section above, and the `[-]` lines from the deface
are the refusal message verbatim. **Everything behaved.**

*The sheet — refusing a tab it does not own* moves to **`Yes`**. Both paths refused against
the real `Holdings` tab — the banner typed over, then the subtler one with `A1` cleared and
text left on row 3 — and a third sync, after the tab was emptied, returned the same 16
accounts, 9 holdings and 9 movements. `verify guard` had already got all three of `claim()`'s
answers, empty-tab adoption included.

**Three of the four tab checks are settled**, and the two that had been marked as resting on
an assumption were settled in both directions at once, which is the part worth keeping. Had
the unformatted read returned display text, every money cell would have been rejected as
text; had a formula arrived as its own source, `float()` would have failed into "could not
read both". Neither happened, so the sheet is right *and* those two checks are — and the
marker came off in the same pass. It is worth being clear that this is what a marked
assertion is for: it made a pass mean something specific rather than merely reassuring.

**The four things this run left over, and where each ended up.** Two were closed the same
day; the other two are not laziness.

- *Check 4.* **Done later the same day, and it passed 7 of 7** — see the check itself, which
  had to be rewritten first, because it described a formula that has never existed. Of 16
  accounts, 7 had a blank `As Of` and every one of them appeared in the staleness panel.
- *The tabs' creation.* **Also done, and it worked.** The four were deleted and `sheet` run
  again, so `ensure_worksheet` took its `WorksheetNotFound` branch four times, `claim()`
  adopted four empty tabs, and the sync wrote into them. It is the one item here reported as
  working rather than transcribed, so nothing is quoted for it — the failure it rules out is
  loud, a `Could not create a tab named ...` line and no sync at all.
- *The whole-sync abort.* Covered above — a workspace whose data has not moved cannot tell a
  rewritten `Accounts` from an untouched one, so it rests on the claim loop preceding every
  write and on `test_nothing_is_written_when_a_tab_is_refused`.
- *The window at five hundred.* 9 movements on the day. Unchanged, and unchangeable from here.

The look was taken and the four tabs were deleted and remade, so *four machine-owned tabs* is
settled too, and **the sheet had one row left**: *the whole transaction history reaching a tab*,
waiting on a broker rather than on anybody's afternoon. Nine movements cannot put a question
about five hundred, and no amount of care could change that — it needs a workspace with the
rows, ideally past 2,000 so a second chunked write meets Sheets at all. It has an issue of its
own, #141, because a row blocked on data volume should not hold a finished investigation open;
#115 closed on everything above.

**That count has since grown and the row has not moved**, which is worth stating here rather
than leaving a reader to reconcile 9 against the 18 in the next section. The figures in this
write-up are the 2026-08-10 run's own and stay as they were recorded; the workspace has kept
scraping since, and 18 movements is no closer to putting a question about five hundred than 9
was. `verify volume` settled the second chunked write on 2026-08-15 by sending its own rows,
and that is a different question from this one — see check 5.

### Nine dates, twelve accounts, on 2026-08-15

Checks 6 and 7 waited on a workspace rather than on an afternoon, and #149 was filed rather
than done for that reason. The wait ended by itself: a fortnight of unattended runs left one
where SnapTrade had gone quiet for six days and come back with two accounts more than it left
with, the 529 had a six-day gap of its own, Ally and the 529 both stopped a day before the
last date while TSP and the manual broker ran to the end, and Fidelity had never produced a
snapshot at all. First readings span twelve days; the longest silence in it is six. Nothing
about it was arranged.

**It is worth being exact about what "different days" turned out to mean here**, because the
tempting summary is wrong. The brokers' *last* readings are only a day apart — 08-13 against
08-14 — so a workspace described as "Ally last went a week ago" is not what arrived. What
makes this one carry is the middle: brokers entering the series twelve days apart, and gaps of
up to six days inside it where a broker reported nothing while others did. That is enough to
put both checks, and a run that only stopped one broker for a week would have put less.

```
$ uv run stonksmithdb sheet
[*] Refreshed: 12 accounts, 13 holdings, 18 movements from ally, fidelity, manual, schwab529plan, snaptrade, tsp.
$ uv run stonksmithdb verify tabs
[*] Reading the tabs back from 'Investment Account Scrapes'.
[+] All 5 tabs carry the banner in A1
[+] Accounts row 2 is the column contract, ending at J
[+] Holdings row 2 is the column contract, ending at P
[+] Transactions row 2 is the column contract, ending at O
[+] Net Worth row 2 is the column contract, ending at K
[+] Transactions holds all 18 movements the databases have
[+] Every Processed On is YYYY-MM-DD
[+] Processed On runs newest-first within each account
[+] Accounts Value is a number, not text
[+] The dashboard's two totals agree
[+] The account kind allocation adds up
[+] The position allocation adds up
[+] The asset class allocation adds up
[*] All 13 checks behaved, against real Sheets rather than a stub. One thing it cannot cover is still in docs/live-verification.md: an absent value arriving as an empty cell.
```

Quoted as it came out, in the scripted form. **Thirteen checks, not ten** — the three
allocation lines are new since 2026-08-11 and are check 8, which is why that row moves in this
pass too.

Neither of those thirteen is check 6 or check 7, which is the whole point of the row. Those
were put to the tab afterwards, by reading all 78 rows back off `Net Worth` and walking them.
The expectation was computed separately, in SQL over the six broker databases, so that a fault
in `net_worth_history` could not appear on both sides of the comparison — the count below
agreed with it on all nine dates, and 78 rows against 78.

**Check 6, the count down the dates.** The two middle columns are the split the `Basis` column
records; only their sum is the claim.

| Date | `observed` | `carried` | accounts | against the date before |
| --- | --- | --- | --- | --- |
| 2026-08-02 | 1 | 0 | 1 | first date |
| 2026-08-04 | 7 | 0 | 7 | grew |
| 2026-08-05 | 6 | 1 | 7 | held |
| 2026-08-07 | 2 | 7 | 9 | grew |
| 2026-08-10 | 3 | 6 | 9 | held |
| 2026-08-11 | 10 | 1 | 11 | grew |
| 2026-08-12 | 11 | 0 | 11 | held |
| 2026-08-13 | 11 | 0 | 11 | held |
| 2026-08-14 | 10 | 2 | 12 | grew |

**Read the `observed` column on its own and it falls three times** — 7 to 6, 6 to 2, 11 to 10.
That column is what the chart would have drawn without the carry-forward, and the fall from
six to two between 2026-08-05 and 2026-08-07 is most of a portfolio disappearing and coming
back because two brokers reported that day and the rest did not. The `accounts` column never
falls: it grew four times, held four, and fell none. That is the failure this design exists to
prevent, seen not happening against real data, which is the only way it can be seen at all.

Two details worth not skimming. **The axis is the dates something was read on, not a
calendar** — there is no row for 08-03, 08-06, 08-08 or 08-09, because nothing reported on
them, and a series that filled them in would be inventing readings. And **the last date is
2026-08-14, not the day of the run**: every broker's newest reading is dated the day before by
the source itself, so a series dated 08-15 would be claiming a freshness nothing had.

**Check 7, the basis and the absences.** Of the 78 rows, all 78 read `observed` or `carried`
and none is blank; the 17 `carried` rows all date `Observed On` before their `Date`, and the
61 `observed` rows all date it equal. Eleven of the twelve accounts joined the series after
the first date, and the count of rows standing before each on a date it had not yet reported:

| joined on | accounts | earlier dates | rows on them |
| --- | --- | --- | --- |
| 2026-08-02 | 1 | 0 | 0 |
| 2026-08-04 | 6 | 1 | 0 |
| 2026-08-07 | 2 | 3 | 0 |
| 2026-08-11 | 2 | 5 | 0 |
| 2026-08-14 | 1 | 8 | 0 |

Zero throughout, and no row anywhere on the tab holds a `0` or an empty `Value`. The account
in the last line is the one that makes this check worth making: it first reported on the ninth
date, and there are eight dates it could have been back-filled onto with a zero that totalled
correctly and said an account existed when it did not. Fidelity, which has no snapshots at
all, contributes no rows rather than a flat line at nothing.

**What this run could not settle.** The thirty-day horizon. The longest silence in this
workspace is six days, so every gap here is inside the window and nothing was dropped for
being stale — the carry was exercised and its expiry was not. That half still rests on
`test_the_horizon_is_exactly_carry_days_and_inclusive`, and a workspace that would put the
question is one where a broker has been dead for a month, which is a condition to wait for
rather than a run to make. The row is settled on what the checks ask; this is the part it
does not reach.

**Checked again on 2026-08-16, and it still cannot be put.**

```bash
uv run stonksmithdb stale 30
```

```
[*] Freshness in 'default': 12 accounts, nothing older than 2026-07-17 (30 days).
[+] 0 of 12 accounts are stale.
```

Twelve accounts and none past thirty days — nor past seven, which is the dashboard's own
question and the tighter one: bare `stale` reports the same zero against a 2026-08-09
cutoff. The six brokers' newest readings are two and three days old, and the oldest reading
anywhere in the workspace is 2026-08-02, so the whole history is fourteen days long. (`stale`
reads databases and nothing else — no login, no Sheets, no network — though opening one
applies any pending migrations, so even this read can upgrade a file on disk.)

**The arithmetic is worth writing down rather than re-deriving.** An expiry needs both
halves: a broker silent for thirty-one days *and* an axis that reaches past it. The axis
holds only dates something was read on, so a broker that stops takes the second half with it
unless the others keep running. The earliest date this workspace could therefore show an
expiry is 2026-09-13 — and only if a broker stops today while the rest carry on. All six ran
within the last three days, so the real date is later than that. Fidelity is still not the
candidate it looks like: no snapshots at all, so it never enters the series and has nothing
to expire.

---

## Every broker: two runs, two snapshots, one account

Run any broker twice, **leaving at least a second between the two runs**, then:

```bash
uv run stonksmithdb
broker <name>
show accounts     # unchanged row count
show snapshots    # one more row than before
```

Accounts are keyed on `(broker, account_key)`, so a second run updates the existing
row rather than adding one. Snapshots are keyed on `(account_id, scraped_at)`, so
each run adds one.

The second-apart instruction is not incidental — see below.

### Run against Ally, 2026-08-10

Two signed-in runs, 21:57:58 and 22:03:26 — five and a half minutes apart, which is
clear of the same-second trap by a margin that leaves nothing to argue about.

`show accounts` after both: one row, the same row.

```text
| 1 | | Individual (...1234) | | INVESTMENT | 2026-08-10 22:03:26 |
```

Its `Last Seen` moved 21:57:58 → 22:03:26, which is the upsert being visible rather
than merely assumed: the row was written twice and there is still one of it. A second
row would have meant `(broker, account_key)` was not holding.

`show snapshots` went from 26 rows to 27 to 28, one per run, ids 27 and 28 carrying the
two timestamps. So the two keys behave differently on the same pair of runs — accounts
updated in place, snapshots appended — which is the whole of the claim.

Both runs read one investment account and skipped the same Ally Bank savings account,
and both wrote $2,500.00.

**This does not make anything plural true.** One account, one holding, one deposit
account skipped — the same single state the nine earlier runs saw. That the row count
held at one is evidence about the key, not about the account list, and a second
brokerage account remains the only thing that would settle the plural reading. It is
recorded here so the next reader does not take a passing row-count check for one.

---

## Known traps

Two things can make a step above fail for a reason that has nothing to do with the
claim being tested. Both are properties of the current design, recorded here so a
run is not misread. Neither is fixed by this document.

**Two runs inside the same second produce one snapshot.** `scraped_at` is stamped to
the second in UTC, and it is half the snapshot's unique key, so a second run in the
same second upserts the first rather than appending. TSP in particular is fast enough
to hit this — it has no login and, once the price file is fetched, very little to do.
Leave a second between runs. If two snapshots do not appear despite that, the finding
is real.

**A TSP statement whose fund cannot be read is priced with the configured one.** This
trap used to be much larger, and the larger version is fixed: `units_for` now compares
the statement's own fund against `[TSP] fund` and **refuses the run outright** when
both are present and different, rather than valuing `L 2060` units at `C Fund`'s price
on the strength of two adjacent log lines.

What is left is the narrow case. `same_fund` treats an *unnamed* side as matching
anything, deliberately — a statement whose fund did not parse has already lost that
information, and refusing a perfectly good unit count over a detail the file never
carried would cost more than it saves. So a statement StonkSmith cannot name is still
priced with whatever `[TSP] fund` says, silently. The line to check is the one that
reports what the statement gave up: if it names no fund, the guard did not run, and
only you can say whether the configured fund is the right one.

---

## Recording a result

**Date it.** The row's `Settled on` cell takes the day the run happened, and the
`As of` date above the table moves to that day in the same edit. Both are checked, so
a result recorded without them is a failing test rather than a sentence nobody
re-reads — which is the whole reason the count is derived rather than typed. A run
that settles a row whose date was `not recorded` fixes that row for good.

Add the observation to the table at the top, and to the issue tracking the run. Write
down what was returned, not just whether it passed — the #48 write-up is the model:
status, headers, sizes, and the exact conditions under which the thing did and did not
work. A "yes" with nothing behind it is the state this document exists to end.

**Record the claims that passed, not only the one that failed.** A single run settles
several rows at once, and the failure is the one that writes itself up — it demands a
post-mortem, and the successes are merely the run working. That asymmetry is how the
table and the README come apart: #83 was five claims settled in one sitting, one of
them written into the table and four of them left in prose. Update every row the run
touched before closing the issue, and bring the count above the table into line — that
last part is now checked, so a row settled without it is a failing test rather than a
sentence nobody re-reads.

Then change the three summaries named at the top of this file in the same pass,
whichever way it went. **That half is still yours**: `tests/test_doc_cross_references.py`
checks that the links between these files still resolve, but no test can tell whether a
paragraph of prose still summarises the table correctly, only whether the arithmetic
above it does. A claim that has been
disproved and left standing is worse than one that was never checked, because the next
reader has no way to tell them apart — and a claim that has been *proved* and left
reading as unchecked sends them off to redo a run that has already been done.

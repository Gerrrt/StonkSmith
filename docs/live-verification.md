# Live verification

Green tests say the code does what it was written to do. They do not say the site
still looks the way it looked when the parser was written, that a session survives
a process exit, or that a URL still serves what it served last quarter. Only a run
against the real thing says that.

This file records which broker claims have been observed against a live account and
which have not, and gives the procedure for closing the gap. It is meant to be worked
through, not read.

**This file is the record.** The README summarises it in two places — the paragraph
under *Project Structure* and the end of the *Ally Invest* section — and both are
derived from the table below rather than maintained alongside it. Change a row here
and change those there in the same pass; do not edit them on their own.

**A failed step here is information, not a defect.** Session persistence and an
unattended price download are load-bearing for the claim that a broker runs daily
without a human. If one does not hold, the right response is to say so in the README
rather than to leave the claim standing. Each step below therefore says what *either*
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

*11 of 20 claims have been settled by a live run — 10 confirmed, 1 disproved. The
remaining 9 rest on unit tests or on fixtures.*

`tests/test_live_verification_tally.py` derives those five numbers from the table below
and fails if this sentence disagrees with them. It exists because this paragraph said
nineteen for four commits after the table reached twenty rows: the instruction to update
it lives under *Recording a result*, and an instruction is not a mechanism.

| Claim | Rests on | Observed live |
| --- | --- | --- |
| Ally — sign-in hand-off to `live.invest.ally.com` | Nine runs against a real account, 2026-08-07; unit tests over the URL predicate | Yes |
| Ally — holdings, totals and sidebar parse | The same nine runs; `tests/ally_holdings.html` is one redacted DOM from that same account | Yes |
| Ally — masked sidebar number matches the full one | The same nine runs; `masked_matches("...0111", "1AB20111")` in unit tests | Yes |
| Ally — Ally Bank deposit accounts skipped, not filed as brokerage | The same nine runs | Yes |
| Ally — database write | The same nine runs, which wrote to a real `ally.db`; the unit tests behind this only ever write to a fake one. The `units_as_of` stamp on each holding postdates those runs and has not been written to a real one | Yes |
| Ally — one row per account across runs | `uq_accounts_broker_key`; the row count was never checked across those runs | No |
| Ally — valuing from published prices without a login | Unit tests over a fake DB and a canned payload, `tests/test_ally_from_prices.py` | No |
| Ally — the published price feed answers | A real request on 2026-08-09, written up below: 200 and 3,612 bytes of JSON for one symbol, read by `daily_closes()` into 23 dated closes | Yes |
| Ally — session survives to the next run | Nine runs, both browsers, both persistence models | **Run, and it cannot** — see below |
| TSP — statement parser | Real statements, read as issued through `-o STATEMENT=` | Yes, against real files |
| TSP — share price parser | The published file as fetched on 2026-08-07 (#48); `tests/tsp_prices.csv` is a slice of it kept as a fixture | Yes, against real files |
| TSP — the mark, and the balance inversion | Checked against what the site itself reports | Yes |
| TSP — share price download | A real request on 2026-08-07; response written up in #48 | Yes |
| TSP — DFAS pay table parse | `tests/dfas_basic_pay_em.html`, a **reconstruction** of the live page | No |
| TSP — DFAS pay table download | Unit tests with a mocked session; dfas.mil refused two unrelated hosted environments, 2026-08-07 and 2026-08-09, and tsp.gov answered from both | No |
| TSP — the contribution accrual | Unit tests over the parsed price file and pay table | No |
| TSP — database write | Unit tests with a mocked DB | No |
| The sheet — four machine-owned tabs | Unit tests with a faked spreadsheet | No |
| The sheet — the whole transaction history reaching a tab | Unit tests with a faked spreadsheet | No |
| The sheet — refusing a tab it does not own | Unit tests with a faked spreadsheet | No |

The Ally rows are the ones worth reading twice. Those nine runs were nine runs against
*one account state*: one investment account, one holding, one deposit account. So the
parse has met a live site, but only ever that shape of it. Every plural case — a
second brokerage account, a second position, an account with no holdings — is still
inference, and `tests/ally_holdings.html` is a redaction of that same single state
rather than a second witness to it.

---

## Ally

Seven steps. The whole sequence needs one signed-in browser session and about ten
minutes — except step 6, which deliberately needs no session at all and has to be run
on a later day than step 1 to mean anything. An eighth check sits after them, unnumbered
because it is not part of the sequence and needs nothing whatsoever.

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
scrape is the correct description, and the README says so. This is not a defect to fix
in StonkSmith; nothing StonkSmith stores reconstitutes a session Ally will honour.

What does run unattended is `--from-prices`, which values the account from published
closes and the units the last signed-in run recorded — no browser, no sign-in. That is
a different claim from any of the ones settled here, so it has rows of its own in the
table above, and they start at `No`.

What *is* proven, every one of those nine runs: the sign-in flow, the holdings parse,
the account rail, the bank/brokerage split and the database write. The scrape works.
It is only the unattended part that does not.

**What the recorder is being read for is written down elsewhere.** Ally's open questions
are about endpoints nobody has seen -- whether an activity feed exists, whether it is
per-account, whether it takes a date window -- and the decision those answers feed is
recorded in `docs/ally-transactions.md`, along with the two other conditions that would
reopen it. A run that turns up an activity route belongs in *that* file. This one records
which claims *StonkSmith* makes have been settled by a live run; what Ally's site offers is
a fact about Ally, and filing it here as a claim would mean counting a question in the tally
above.


### 3. The masked number reconciles against a real account

Any successful run exercises this. The sidebar says `...0847`; the page heading says
something like `3LD20847`. Confirm the run reports one row per account and did not
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

The `Account` column should read `<nickname> (...0847)` — the *masked* form — and the
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

Needs step 1 to have run first, since the units come out of the database. Then, on any
later day:

```bash
uv run stonksmith ally -M ally --from-prices
```

```
[+] Valuing from published prices; no sign-in needed.
[+] <label>: <units> <symbol> x <price> (<price date>) = <value>
[*] <label>: priced at <price date>; units as recorded <stamp>. Re-run with --manual-login after a deposit.
```

**No browser window should open.** That is most of the claim: this path returns before
Playwright starts and before the preflight request to the bank, so a run that opens a
window has taken the scrape branch instead.

Three things to check in `stonksmithdb` afterwards. `show snapshots` should have one
more row, and its `as_of` should carry the **price** date rather than being empty — this
is the only Ally path that fills that column, so an empty `as_of` here means the value
was dated by the run. `show holdings` should show the same unit count step 1 recorded,
unchanged: this run reprices units, it does not rediscover them. And its `Units As Of`
should carry **step 1's** date, not this run's — that is the scrape stamping the moment
its units were read, and the price run carrying the stamp through rather than
replacing it.

Then run it a **second** time, and check `Units As Of` again. It must not have moved.
A date that advances to the previous price run is the failure this step exists to
catch: these runs write snapshots, so an age inferred from the newest snapshot reports
the units a day old however old they are — drifting younger while the units drift
older, and reading as fact the whole way. An unchanged date is the units' age still
being the last sign-in's.

Then the failure that matters more than the success. Against a database with no Ally
holdings on record:

```
[-] No holdings on record to value. Run with --manual-login once so a signed-in run can record the units.
```

A number here instead of a refusal would be the finding — it would mean the run had
invented units rather than read them.

Worth knowing before ticking this: the sheet is **not** synced by a price run, so an
unchanged `Holdings` tab is expected rather than a failure. Run `sheet` in
`stonksmithdb` to refresh it — see *The sheet* below.

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
`src/modules/ally_module.py`, copied rather than approximated — the feed's answer is
allowed to depend on who asks.

```text
200 3612 application/json;charset=utf-8
```

**A 200 is half the claim.** The other half is that `daily_closes()` in
`src/helpers/quotes.py` can still read what came back, which is a different question and
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
price feed answers*, whose gap was that no real request had ever been recorded. It does
not settle *Ally — valuing from published prices without a login*, which is step 6, needs
a real `ally.db` behind it, and stays `No`. One symbol was asked for, and an ETF rather
than anything an account here holds; a feed that answers for `SPY` and not for some
particular fund would still fail step 6, which is the reason the two are separate rows
rather than one.

---

## TSP

Five steps. No credential is involved at any point.

### 1. A statement gives up its units

```bash
uv run stonksmith tsp -M tsp -o STATEMENT=<your statement>
```

Both PDF and text are accepted. Expect:

```
[+] Statement: <n> units of <fund> as of <period end>
```

**Check that the fund named on that line is the fund named on the next one.** The
statement's fund is read and logged, but the mark is priced with the `fund` from your
`[TSP]` config — so a statement for one fund with another configured produces a
confident, wrong number, and the two log lines are the only signal. See *Known traps*
below.

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

With the contribution keys filled in (step 5) there are **two** holding rows, not one:
the anchored count, dated to the statement, and the estimate, dated to the last
contribution it could price. They must sum to the snapshot's `value` — check that
they do, because a total that does not add up is the one way this could be wrong
while every individual number looks right.

One check only a real database can make: open an existing `tsp.db` — one written before
`holdings.units_as_of` existed — and confirm that marks stored back then show a `Units
As Of` too. Those dates were migrated out of `holdings.raw_value`, and no test can
prove that against your file.

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

**This is the one step here that could not be attempted.** dfas.mil sits behind Akamai
and answered every request from the development environment with a 403 and an "Access
Denied" page — every User-Agent tried, including the one tsp.gov accepts, and
`web.archive.org` was refused too. So the parser is written against
`tests/dfas_basic_pay_em.html`, which is a *reconstruction* of the live page's
structure and not a saved response. Everything downstream of the parse is verified;
the parse itself is verified against a shape that was read off the real page by eye.

**Retried on 2026-08-09 from an unrelated hosted environment, with a control, and
refused again:**

```text
GET https://www.dfas.mil/Military-Members/payentitlements/Pay-Tables/Basic-Pay/EM/
-> 403, 455 bytes, text/html, Akamai "Access Denied"
   Reference #18.8c623017.1786311998.2342bc08

GET https://www.tsp.gov/data/fund-price-history.csv?startdate=...&enddate=...
-> 200, 555,142 bytes            (same egress, same User-Agent, same minute)
```

The control is the part worth keeping. Without it, a 403 is equally well explained by a
local proxy, and the first write-up — "refused every request from the development
environment" — reads as a fact about one box. Another `.gov` host answering from the same
place in the same minute rules that out: the refusal is DFAS's, it tracks the network
rather than the request, and **re-running this from a third hosted environment will not
help.** That is worth one line here because it is the cheap thing to try next and it is
already known not to work.

**What this does not say.** Two blocked cloud networks are not evidence about a home
connection, so the README's TSP setup claim is left exactly as it stands. Only a run from
a machine that is not in a data centre can qualify it, and that run is still the first
half of this step.

Two things to establish, in order.

First, that the page can be fetched from a machine that DFAS will talk to:

```bash
uv run stonksmith tsp -M tsp
```

```
[+] E-7 at Over 10: $5,300.40 basic pay per month
```

If instead it prints `The enlisted members pay table returned HTTP 403. dfas.mil
refused the request...`, then this download is not unattended, and the README claim
that four config keys are the whole setup needs the same qualification `--prices`
carries. Say so there rather than leaving it standing.

Second — and worth doing **either way** — that the parser reads the real markup:

1. Open <https://www.dfas.mil/Military-Members/payentitlements/Pay-Tables/Basic-Pay/EM/>
   in a browser and save the page as HTML.
2. Run against it: `uv run stonksmith tsp -M tsp --pay-table ~/Downloads/EM.html`
3. Check the printed basic pay against the figure in that grade's row and time-in-service
   column on the page itself.

If step 3 disagrees, the reconstruction differs from DFAS's markup in a way the tests
cannot see. **Replace `tests/dfas_basic_pay_em.html` with the saved page** — trimmed of
anything but the tables — and the fixture stops being a reconstruction. That is the
single highest-value thing anyone with access to dfas.mil can do for this feature.

A number that is merely *plausible* is the failure mode to watch for here. The columns
are matched from the right, so a table with an unexpected trailing column would shift
every rate by one band — which reads as a member being paid at the wrong seniority, not
as a parse error, and looks entirely like an answer.

---

## The sheet

Five checks and a refusal, and it sits outside both broker sections because the sheet is
not any broker's. One `sheet` run reads every database in the workspace, so the tabs it
writes are as much Fidelity's and SnapTrade's as TSP's, and the three *The sheet — …*
rows in the table above settle for all of them at once. This procedure lived under *TSP*
until it was moved here, because TSP was the broker it happened to be written against.

**This is the one procedure on this page that needs a credential, and the account it
needs is not a broker's.** No sign-in to anything StonkSmith scrapes, no browser it
drives. It is also the only one here that writes anywhere but a local database.

**What it needs.** An OAuth client `gspread.oauth()` can authorize — a Desktop-app
client ID with **both** the Sheets and the Drive API enabled, saved as
`~/.config/gspread/credentials.json`, the path `GSPREAD_CONFIG_DIR` in
`src/helpers/sheets.py` names — and a spreadsheet called `Investment Account Scrapes` in
that Google account or shared with it. That name is `SPREADSHEET_NAME` in the same file
and nothing reads it from config. Then a workspace with at least one broker database
already in it, and for check 5 specifically, a broker with a long transaction history
rather than a fresh one.

**What it costs.** `sheet` clears and rewrites all four machine-owned tabs, and the
refusal at the end has you deface the `Holdings` tab on purpose and hand it back
afterwards. So this runs against a spreadsheet you are willing to have rewritten, which
in practice means the real one. That is the whole reason these three rows are still `No`
while others are settled: nothing in the procedure is difficult, but it needs a Google
account and a database with real rows in it, and neither is available to anything
holding only this repository.

No tab needs creating: StonkSmith makes `Accounts`, `Holdings`, `Transactions` and
`Dashboard` on the first sync. Nor does this need a scrape — the sheet is a view of the
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

Five things to confirm on the tabs themselves, none of which a unit test can see:

1. **The first cell of every tab carries the machine-owned banner** — all four,
   `Dashboard` included, since a banner cannot be read back off a tab that was never
   created. On the three that carry columns, row 2 is the column contract exactly as
   `src/etc/portfolio.py` spells it; the dashboard has no such row, and its labels run
   down the summary column instead. `Holdings` is the one worth counting: sixteen
   columns, ending at `P`, `Units As Of` — `HOLDING_COLUMNS` in that same file. A tab
   still ending at `O` after a sync is a visible sign the sync did not run, and TSP is
   the broker where the price date and the unit date visibly differ.
2. **Money is a number, not text.** A currency cell should right-align on its own and
   accept a number format. If it left-aligns, something is writing strings again.
3. **The dashboard's `Total (USD)` equals its `Total as read`.** Those are the same
   number computed by Sheets and by Python; a disagreement means the write was
   truncated, and it is the only signal that would say so.
4. **Empty cells are genuinely empty.** `Accounts` minus the count of `As Of` values
   is how the dashboard counts accounts whose source never gave a date, and it relies
   on an absent value arriving as an empty cell rather than as an empty string that
   `COUNTA` still counts. If that figure reads 0 where the tab visibly has blank
   `As Of` cells, the formula needs `COUNTIF(...,"<>")` instead.
5. **`Transactions` holds every movement, not the newest five hundred.** Compare the
   count on the line above against `show transactions` inside a broker shell, and do
   it against a broker with a long history rather than a fresh one — five hundred is
   the number the shell reader stops at, and a tab that silently agreed with it would
   look entirely correct. Past 2,000 movements it is also the only thing that puts a
   second write in front of real Sheets, since `write_rows()` sends `CHUNK_ROWS` rows
   at a time. Check the dates too: the 529 scraper stores `12/30/2025` and SnapTrade
   stores ISO, so the tab is where they must both read `YYYY-MM-DD`, sorted
   newest-first within each account. A `12/30/2025` reaching a cell means the
   normalization was skipped, and the tab's order is then wrong wherever a December
   row sits above a January one.

**Then the refusal, which is the point of the whole thing — and it goes last.** A
refused tab means nothing is synced at all, so doing this first would leave the five
checks above reading a sheet the run never wrote.

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

**What this settles.** Three rows, and each check belongs to exactly one of them.

*The sheet — four machine-owned tabs* is checks 1 through 4: the banner on all four and
the column contract on the three that have one, money arriving as a number, the
dashboard's two totals agreeing, and an absent value arriving as an empty cell rather
than an empty string. Those are four ways for a tab StonkSmith owns to be written wrongly
while looking written. One caveat: a spreadsheet whose four tabs already exist observes
the write but never the *creation* this section opens by asserting — delete the four, or
point at a fresh spreadsheet, to see that half too.

*The sheet — the whole transaction history reaching a tab* is check 5 alone, and it has a
wrong way to pass. Against a broker holding fewer than five hundred movements, agreement
with `show transactions` confirms nothing at all, because that is where the shell reader
itself stops. The date half of the check belongs to this row too.

*The sheet — refusing a tab it does not own* is the refusal, and it is the only one of
the three that can be settled the other way. A sync that went ahead and ate your text is
not a failed check; it is that row observed as **Run, and it cannot** be relied on. Write
it up that way, and say which tab.

Then *Recording a result* below, which is where the asymmetry it warns about actually
bites: one `sheet` run touches all three of these rows, and the refusal is the only one
that writes itself up.

---

## Both brokers: two runs, two snapshots, one account

Run either broker twice, **leaving at least a second between the two runs**, then:

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

**A TSP statement's fund is read, logged, and then discarded.** `-o STATEMENT=` yields
a unit count and the statement's own fund name, but only the count is carried forward;
the mark is priced and labelled with the `fund` configured in `[TSP]`. Point an
`L 2060` statement at a config saying `C Fund` and it will value `L 2060` units at
`C Fund`'s share price, with no warning beyond two adjacent log lines naming different
funds. This matters here because the statement step can be ticked while the resulting
mark is wrong. Check the two lines agree.

---

## Recording a result

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

Then change the README in the same pass, whichever way it went. **That half is still
yours**: no test can tell whether a paragraph of prose still summarises the table
correctly, only whether the arithmetic above it does. A claim that has been
disproved and left standing is worse than one that was never checked, because the next
reader has no way to tell them apart — and a claim that has been *proved* and left
reading as unchecked sends them off to redo a run that has already been done.

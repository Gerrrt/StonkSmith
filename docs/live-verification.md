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

*15 of 20 claims have been settled by a live run — 14 confirmed, 1 disproved. The
remaining 5 rest on unit tests or on fixtures.*

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
| TSP — share price download | A real request on 2026-08-07 written up in #48, and again unattended on 2026-08-10 (#116): 200 and 555,142 bytes, fetched by the run itself rather than by hand | Yes |
| TSP — DFAS pay table parse | The live page, parsed on 2026-08-10 (#116) into all nine enlisted grades; `tests/dfas_basic_pay_em.html` is now that page rather than a reconstruction, and the reconstruction read **zero** grades off it | Yes |
| TSP — DFAS pay table download | A real request on 2026-08-10 (#116): 200 and 116,257 bytes, unattended, through `fetch_pay_table`. The 2026-08-07 and 2026-08-09 refusals were real but were never about the User-Agent — see below | Yes |
| TSP — the contribution accrual | A live run on 2026-08-10 (#116) over the published price file and the DFAS page, both fetched by the run; all six months recomputed independently and matched on every field | Yes |
| TSP — database write | Five runs on 2026-08-10 (#116) into a real `tsp.db`, four dates on one snapshot and the holdings summing to its value exactly; plus a genuine pre-migration database, migrated on open | Yes |
| The sheet — four machine-owned tabs | One real run on 2026-08-10 wrote all four tabs from five databases, so `claim()` and `write_rows()` have met real Sheets; nobody then opened the spreadsheet, and the four checks on how the values render are exactly the ones a successful write does not answer | No |
| The sheet — the whole transaction history reaching a tab | The same run, which wrote 9 movements. The shell reader stops at 500, so a workspace this size cannot put the question at all — this row needs a different workspace rather than a longer sitting | No |
| The sheet — refusing a tab it does not own | Unit tests with a faked spreadsheet. The 2026-08-10 run claimed all four tabs successfully, which exercises `claim()`'s accept path only; the refusal is the path that matters and it stayed untouched | No |

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
[+] L 2060: 315.789 anchored + 142.173804 estimated = 457.962804 units
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
| L 2060                                            | 315.789    | 2026-01-31  |
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

A number that is merely *plausible* remains the failure mode to watch for. The columns
are matched from the right, so a table with an unexpected trailing column would shift
every rate by one band — which reads as a member being paid at the wrong seniority, not
as a parse error, and looks entirely like an answer.

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
$ uv run stonksmith tsp -M tsp --units 315.789 --units-as-of 2025-11-30
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

**If a token is already cached, expect the first attempt to fail on authorization — and
do not believe what it tells you to do about it.** A first run with none authorizes in a
browser and is fine; it is the returning one that breaks, and a client left in Google's
*Testing* publishing status expires its refresh token after seven days, so returning is
the common case. A token that has expired or been revoked comes back as
`invalid_grant`, and the fix is one line — delete
`~/.config/gspread/authorized_user.json` and run `sheet` again, which reauthorizes in a
browser. `credentials.json` stays. This is worth writing down here because the program
will not tell you: `open_spreadsheet()` has two authorization branches, and the one an
expired token actually reaches — the lazy refresh on the first API call — raises
`Google authorization failed (...)` and stops, carrying none of the fix. The other
branch, which does carry a fix, says `invalid_grant` means the OAuth client no longer
exists and sends you off to create a new client ID. That is the remedy for
`deleted_client`; for an expired token it is wrong and costs an afternoon.

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

### Run once, on 2026-08-10

The sync itself worked, on the second attempt — the first died on the expired token
described above. What came back:

```
[*] Refreshed: 16 accounts, 9 holdings, 9 movements from ally, fidelity, schwab529plan, snaptrade, tsp.
```

**What that line establishes on its own**, before anybody opens the spreadsheet:
authorization succeeded, `Investment Account Scrapes` was found, all four tabs were
ensured, **`claim()` accepted all four before any of them was cleared**, and three
`write_rows()` calls plus the dashboard completed against real Sheets. Five broker
databases opened, and no `[-] Not on the sheet:` line means none was skipped. So the
machinery — the authorization, the four-tab claim, the chunked RAW write — has now met
the real thing rather than a `MagicMock`.

**All three rows are still `No`, for three different reasons.** A write that returns says
nothing about how the values *render*, and rendering is exactly what checks 2 through 4
are for: money can arrive as text, the dashboard's two totals can disagree, and an absent
value can arrive as an empty string, all through a RAW upload that reports success.
Nobody looked, so *four machine-owned tabs* stands unsettled. The refusal was never run,
and the accept path succeeding four times says nothing about the refuse path — which is
the one whose failure costs somebody their work. And 9 movements cannot settle
*the whole transaction history reaching a tab* at all: the reader stops at 500, so a tab
that had silently windowed would have agreed with the shell exactly.

**What would finish it, cheapest first.** Run `sheet` **twice** — the second run's
`claim()` has to read back the banner the first one wrote, so four accepts on a second
run prove `A1` carries the banner and round-trips, with nothing opened by hand. Then open
the spreadsheet once for checks 1 through 4, which is all *four machine-owned tabs* still
needs. Then the refusal, which needs the deliberate deface. The transaction row is the
odd one out: it needs a workspace with a few hundred movements at least, and past 2,000
to put a second chunked write in front of Sheets, so it waits on a broker rather than on
an afternoon.

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

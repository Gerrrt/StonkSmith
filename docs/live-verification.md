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

*19 of 20 claims have been settled by a live run — 18 confirmed, 1 disproved. The
remaining 1 rests on evidence no run here can produce: a broker with the transaction
volume to put the question.*

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
| Ally — one row per account across runs | Two signed-in runs on 2026-08-10, 21:57:58 and 22:03:26, written up below: `show accounts` held at one row while `show snapshots` went 26 → 27 → 28 | Yes |
| Ally — valuing from published prices without a login | Three price runs on 2026-08-10 against a real account with no sign-in, written up under step 6: the price date reached `as_of`, and the units' stamp held at `22:03:26` across snapshots 29, 30 and 31 while the newest snapshot's own time moved under it | Yes |
| Ally — the published price feed answers | A real request on 2026-08-09, written up below: 200 and 3,612 bytes of JSON for one symbol, read by `daily_closes()` into 23 dated closes | Yes |
| Ally — session survives to the next run | Nine runs, both browsers, both persistence models | **Run, and it cannot** — see below |
| TSP — statement parser | Real statements, read as issued through `-o STATEMENT=` | Yes, against real files |
| TSP — share price parser | The published file as fetched on 2026-08-07 (#48); `tests/tsp_prices.csv` is a slice of it kept as a fixture | Yes, against real files |
| TSP — the mark, and the balance inversion | Checked against what the site itself reports | Yes |
| TSP — share price download | A real request on 2026-08-07 written up in #48, and again unattended on 2026-08-10 (#116): 200 and 555,142 bytes, fetched by the run itself rather than by hand | Yes |
| TSP — DFAS pay table parse | All four published pages, parsed as served: the enlisted one on 2026-08-10 (#116) into all nine grades, and the officer, prior-service and warrant pages on 2026-08-11 (#118) into O-1..O-10, O-1E..O-3E and W-1..W-5. Every fixture in `tests/` is now a served page; the enlisted reconstruction read **zero** grades off the real one, and the prior-service reconstruction's rates were invented outright | Yes |
| TSP — DFAS pay table download | Real requests through `fetch_pay_table`: the enlisted page unattended on 2026-08-10 (#116), 200 and 116,257 bytes, and the other three on 2026-08-11 (#118), 200 each. The 2026-08-07 and 2026-08-09 refusals were real but were never about the User-Agent — see below | Yes |
| TSP — the contribution accrual | A live run on 2026-08-10 (#116) over the published price file and the DFAS page, both fetched by the run; all six months recomputed independently and matched on every field | Yes |
| TSP — database write | Five runs on 2026-08-10 (#116) into a real `tsp.db`, four dates on one snapshot and the holdings summing to its value exactly; plus a genuine pre-migration database, migrated on open | Yes |
| The sheet — four machine-owned tabs | All four checks, against the real spreadsheet on 2026-08-10 and written up below. `verify tabs` settled the first three: the banner on all four tabs, row 2 against all three column contracts with `Holdings` ending at `P`, money back as a number, and the dashboard's two totals equal. Check 4 was then done by eye — of 16 accounts, 7 had a blank `As Of` and all 7 appeared in the staleness panel, so an undated account is surfaced rather than counted at face value. The creation half followed: the four tabs were deleted and `sheet` run again, which had `ensure_worksheet` make all four and `claim()` adopt them empty before writing — reported as working rather than transcribed, so there is no output quoted for it | Yes |
| The sheet — the whole transaction history reaching a tab | `verify tabs` on 2026-08-10 confirmed the tab's 9 movements against the 9 the databases hold, every date normalized and each account newest-first. Nothing was dropped at this size; five hundred is where the question starts, so this row needs a workspace with the rows rather than a longer sitting | No |
| The sheet — refusing a tab it does not own | Run on 2026-08-10 against the real `Holdings` tab: a defaced first cell refused, then text below a blank first cell refused, then a restoring sync. `verify guard` got all three of `claim()`'s answers, empty-tab adoption included. One part is not observable this way — that a refusal leaves no tab freshly written beside a stale one rests on claim-before-write and its unit test, since a run whose data is unchanged cannot tell a rewritten tab from an untouched one | Yes |

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

Step 1 ran twice that evening — the two runs written up under *Both brokers* below —
leaving the account's units on record at `2026-08-10 22:03:26`. The price run followed
a minute later:

```bash
uv run stonksmith ally -M ally --from-prices
```

```text
Broker:  Ally    [+] Valuing from published prices; no sign-in needed.
Module:  Ally    [!] Starting Ally sync for: published prices
Module:  Ally    [+] Individual (...0847): 123.519 SWPPX x $20.00 (2026-08-07) = $2,470.38
Module:  Ally         [*] Individual (...0847): priced at 2026-08-07; units as recorded 2026-08-10 22:03:26. Re-run with --manual-login after a deposit.
Module:  Ally    [+] Ally valued from published prices.
```

`show snapshots` gained one row, and it is the **only row in the table with an `as_of`
at all** — the twenty-eight scraped snapshots preceding it leave that column empty:

```text
| 29 | Individual (...0847) | 2026-08-07 | 2026-08-10 22:04:27 | $2,470.38 | USD |
| 28 | Individual (...0847) |            | 2026-08-10 22:03:26 | $2,470.38 | USD |
| 27 | Individual (...0847) |            | 2026-08-10 21:57:58 | $2,470.38 | USD |
```

That is the check: the value is dated by the source it came from, 2026-08-07, and not
by the run that wrote it, 2026-08-10 22:04:27. An `as_of` echoing the run date would
have meant the price date never reached the column.

`show holdings 29` carries step 1's unit count and step 1's stamp:

```text
| Individual (...0847) | SWPPX | Schwab S&P 500 Index | 123.519 | $20.00 | $2,470.38 | ... | 2026-08-10 22:03:26 |
```

The 123.519 is step 1's count by construction rather than by comparison — the price
path reads units from the database and has no way to fetch them — so what this row
shows is that repricing carried them through without disturbing them. `Units As Of`
reads `22:03:26`, the sign-in's stamp, not the price run's `22:04:27`. Three dates, all
different and each meaning what it says: the price is Friday's, the units were read at
22:03:26, the row was written at 22:04:27.

**The value is corroborated, which was not something this step asked for.** 123.519 ×
$20.00 = $2,470.38, and the two signed-in runs minutes earlier had independently
recorded $2,470.38 from Ally's own page. The published-price arithmetic and the
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
| 31 | Individual (...0847) | 2026-08-07 | 2026-08-10 22:29:44 | $2,470.38 | USD |
| 30 | Individual (...0847) | 2026-08-07 | 2026-08-10 22:27:17 | $2,470.38 | USD |
| 29 | Individual (...0847) | 2026-08-07 | 2026-08-10 22:04:27 | $2,470.38 | USD |
```

Each of the two ran with a newest snapshot whose `scraped_at` was **not** `22:03:26` —
29's `22:04:27` for the first, 30's `22:27:17` for the second — and each printed:

```text
[*] Individual (...0847): priced at 2026-08-07; units as recorded 2026-08-10 22:03:26.
```

`22:03:26`, not the newest snapshot's time. That is the discriminator firing: a run
inferring the age from the snapshot it could see had a different number available to
print and did not print it.

And the stamp survived being written, which is the half that would start the drift.
`show holdings 30`:

```text
| Individual (...0847) | SWPPX | Schwab S&P 500 Index | 123.519 | $20.00 | $2,470.38 | ... | 2026-08-10 22:03:26 |
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

Five things to confirm on the tabs themselves, none of which a unit test can see.
**`verify tabs` now does most of it**, by reading the four tabs back:

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

**Check 4 is not in that list, and could not have been.** It is a question about a formula's
behaviour rather than about a cell's contents, so a read cannot answer it: an empty cell and
an empty string come back the same, as `""` or a short row. It stays an eyeball check, and it
is the reason this section still asks you to look — though not for the reason it used to give.
See check 4 below.

The five checks, and which of them `verify tabs` settles:

1. **The first cell of every tab carries the machine-owned banner** — *settled, 2026-08-10,
   by `verify tabs`, and the creation half separately: the four tabs were deleted and `sheet`
   run again, which made them and adopted them empty before writing.* All four,
   `Dashboard` included, since a banner cannot be read back off a tab that was never
   created. On the three that carry columns, row 2 is the column contract exactly as
   `src/etc/portfolio.py` spells it; the dashboard has no such row, and its labels run
   down the summary column instead. `Holdings` is the one worth counting: sixteen
   columns, ending at `P`, `Units As Of` — `HOLDING_COLUMNS` in that same file. A tab
   still ending at `O` after a sync is a visible sign the sync did not run, and TSP is
   the broker where the price date and the unit date visibly differ.
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
   agree with everything. Past 2,000 movements is also the only thing that puts a
   second write in front of real Sheets, since `write_rows()` sends `CHUNK_ROWS` rows
   at a time.

   Check the dates too: the 529 scraper stores `12/30/2025` and SnapTrade
   stores ISO, so the tab is where they must both read `YYYY-MM-DD`, sorted
   newest-first within each account. A `12/30/2025` reaching a cell means the
   normalization was skipped, and the tab's order is then wrong wherever a December
   row sits above a January one.

**Then the refusal, which is the point of the whole thing — and it goes last.** A
refused tab means nothing is synced at all, so doing this first would leave the five
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

**What this settles.** Three rows, and each check belongs to exactly one of them.

*The sheet — four machine-owned tabs* is checks 1 through 4: the banner on all four and
the column contract on the three that have one, money arriving as a number, the
dashboard's two totals agreeing, and an account with no date being surfaced rather than
counted at face value. Those are four ways for a tab StonkSmith owns to be written wrongly
while looking written. There is a fifth thing this section opens by asserting — that
StonkSmith *makes* the four tabs — which a spreadsheet already holding them cannot show;
that was settled on its own, by deleting the four and running `sheet` again. Anyone
re-running against an established spreadsheet is back to observing the write and not the
creation, so delete the four, or point at a fresh spreadsheet, to see that half.

*The sheet — the whole transaction history reaching a tab* is check 5 alone, and it has a
wrong way to pass: agreement with `show transactions` confirms nothing, at any size,
because that reader stops where the question starts. Counting the database settles whether
every row landed; only a workspace past five hundred settles whether there is a window,
and only one past 2,000 puts a second chunked write in front of Sheets. The date half of
the check belongs to this row too, and needs no volume at all.

*The sheet — refusing a tab it does not own* is the refusal, and it is the only one of
the three that can be settled the other way. A sync that went ahead and ate your text is
not a failed check; it is that row observed as **Run, and it cannot** be relied on. Write
it up that way, and say which tab. `verify` covers `claim()`'s three answers and not the
abort, so a clean `verify` and no deface leaves this row where it is.

Then *Recording a result* below, which is where the asymmetry it warns about actually
bites: one `sheet` run touches all three of these rows, and the refusal is the only one
that writes itself up.

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

**All three rows are still `No`, for three different reasons.** A write that returns says
nothing about how the values *render*, and rendering is exactly what checks 2 through 4
are for: money can arrive as text, the dashboard's two totals can disagree, and an absent
value can arrive as an empty string, all through a RAW upload that reports success.
Nobody looked, so *four machine-owned tabs* stands unsettled. The refusal was never run,
and the accept path succeeding four times says nothing about the refuse path — which is
the one whose failure costs somebody their work. And 9 movements cannot settle
*the whole transaction history reaching a tab* at all: the reader stops at 500, so a tab
that had silently windowed would have agreed with the shell exactly.

**What would finish it.** Running twice was the cheapest evidence available and it is
spent; what is left needs eyes or a deliberate act. Open the spreadsheet once for the
column contract and checks 2 through 4, and *four machine-owned tabs* is done — that is
one sitting, and the banner half of check 1 is already behind you. Then the refusal, which
needs the deface and is the only one of the three that can be settled the other way. The
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
- *The window at five hundred.* 9 movements. Unchanged, and unchangeable from here.

The look was taken and the four tabs were deleted and remade, so *four machine-owned tabs* is
settled too, and **the sheet has one row left**: *the whole transaction history reaching a tab*,
waiting on a broker rather than on anybody's afternoon. Nine movements cannot put a question
about five hundred, and no amount of care here changes that — it needs a workspace with the
rows, ideally past 2,000 so a second chunked write meets Sheets at all. It has an issue of its
own, #141, because a row blocked on data volume should not hold a finished investigation open;
#115 closed on everything above.

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

### Run against Ally, 2026-08-10

Two signed-in runs, 21:57:58 and 22:03:26 — five and a half minutes apart, which is
clear of the same-second trap by a margin that leaves nothing to argue about.

`show accounts` after both: one row, the same row.

```text
| 1 | | Individual (...0847) | | INVESTMENT | 2026-08-10 22:03:26 |
```

Its `Last Seen` moved 21:57:58 → 22:03:26, which is the upsert being visible rather
than merely assumed: the row was written twice and there is still one of it. A second
row would have meant `(broker, account_key)` was not holding.

`show snapshots` went from 26 rows to 27 to 28, one per run, ids 27 and 28 carrying the
two timestamps. So the two keys behave differently on the same pair of runs — accounts
updated in place, snapshots appended — which is the whole of the claim.

Both runs read one investment account and skipped the same Ally Bank savings account,
and both wrote $2,470.38.

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

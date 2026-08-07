# Live verification

Green tests say the code does what it was written to do. They do not say the site
still looks the way it looked when the parser was written, that a session survives
a process exit, or that a URL still serves what it served last quarter. Only a run
against the real thing says that.

This file records which broker claims have been observed against a live account and
which have not, and gives the procedure for closing the gap. It is meant to be worked
through, not read.

**A failed step here is information, not a defect.** Session persistence and an
unattended price download are load-bearing for the claim that a broker runs daily
without a human. If one does not hold, the right response is to say so in the README
rather than to leave the claim standing. Each step below therefore says what *either*
outcome would mean.

---

## Where each claim stands

| Claim | Rests on | Observed live |
| --- | --- | --- |
| Ally — holdings, totals and sidebar parse | One signed-in DOM, redacted to `tests/ally_holdings.html` | No |
| Ally — sign-in hand-off to `live.invest.ally.com` | Unit tests over a URL predicate | No |
| Ally — session survives to the next run | `save_session()` writing `~/.stonksmith/playwright/Ally.json` | **Run, and it failed** — see below |
| Ally — masked sidebar number matches the full one | `masked_matches("...0111", "1AB20111")` against the fixture | No |
| Ally — one row per account across runs | `uq_accounts_broker_key` | No |
| TSP — statement parser | Real statement layouts | Yes, against real files |
| TSP — share price parser | A real slice of the published file, `tests/tsp_prices.csv` | Yes, against real files |
| TSP — the mark, and the balance inversion | Checked against what the site itself reports | Yes |
| TSP — share price download | A real request on 2026-08-07; response written up in #48 | Yes |
| TSP — database write | Unit tests with a mocked DB | No |
| TSP — `TSP` worksheet | Unit tests with a stubbed saver | No |

The Ally parser row is the one worth reading twice. It is proven against *one snapshot
of one account state*: one investment account, one holding, one deposit account. Every
plural case — a second brokerage account, a second position, an account with no
holdings — is inference.

---

## Ally

Six steps. The whole sequence needs one signed-in browser session and about ten
minutes.

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

### 2. The session persists

**This is the step that decides whether the broker is usable daily.** Let the first
run finish, then:

```bash
uv run stonksmith ally -M ally
```

Note: no `--manual-login`. Look for:

```
[+] Reusing the saved Ally session; no sign-in needed.
```

**This has been run, and it failed.** First observation, 2026-08-07: the sign-in
completed and `Ally.json` was written with real data, and the next run did not reuse
it. It fell through to the five-minute interactive wait and timed out. Twice.

Why was not knowable from the output. `session_is_live()` had four rejection paths
and none of them said anything — the capture that did land came from the manual-login
timeout five minutes later, showing the bank login screen nobody had filled in rather
than the page the session check actually rejected. One cause has since been found and
fixed: the check read the page the instant `goto()` returned, before Angular had
rendered the log-out control it requires, so a live session read as a dead one. The
rejections now name themselves and the undecidable one leaves a capture.

That fix may not be the whole story, so the step still has to be run. If it asks you
to sign in again, check whether `~/.stonksmith/playwright/Ally.json` exists and is
larger than `{}`; it should be mode `0600`. Four outcomes:

- **No file.** `save_session()` never wrote. A defect.
- **Reused.** Re-run once more the next day. A session that survives a process exit
  but not a night is still not a daily broker.
- **`... loaded but never rendered a log-out control ...`** — the run is on the
  investing host and the session is not being honoured, or the markup moved. Open the
  `ally-session-check-*.html` capture it leaves in `~/.stonksmith/logs/` and look for
  `allyNavLogOut`. Present means the markup moved and the selector needs updating;
  absent means Ally did not honour the saved session.
- **`... landed on secure.ally.com, showing the bank's sign-in form.`** — the session
  is gone, not mis-detected. Note that `storage_state()` captures cookies and
  localStorage but never `sessionStorage`, and Ally hands the investing site a token
  from the bank, which is exactly what a single-page app parks there.

If it is the last one, **the honest outcome is that Ally cannot run unattended**,
`--manual-login` on every run is the correct description, and the README says so
rather than the claim being left standing. That is the point of running this.

One variable to hold still while diagnosing: the run that *writes* the session is
headed, because `--manual-login` forces it, while the run that *reuses* it is
headless. Adding `--headed` to the reuse run is the cheapest way to watch where it
actually lands.

`--browser chromium` and `--browser cdp` persist differently — a user-data directory
rather than a storage-state file — so a result on one does not carry to the others.
The default is Firefox; verify that first, since it is what an unattended run uses.

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

This logic has only ever seen the pasted DOM. Ally account numbers are alphanumeric,
which is why the comparison upper-cases both sides. A real number with a lowercase
letter or an unexpected separator is exactly the case the fixture cannot rule out.

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

### 6. Re-running does not duplicate accounts

Covered by the shared step below.

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

A third date is stored on the holding: the date the *unit count* was true. A TSP mark
is a unit count times a share price and the two are true as of different days, so a
stored mark that carries only one of them cannot be audited later.

### 4. The `TSP` worksheet

**Create a tab named `TSP` in the `Investment Account Scrapes` spreadsheet first.**
No broker creates its own tab. Without it the run prints:

```
[+] TSP mark saved locally; the dashboard was not updated.
```

and still exits 0, because the database write already succeeded and Sheets is a view
of it. That message is the tab being absent, not the broker failing.

With the tab present, confirm the row carries `Units as of` and `Price date` as
separate columns — both dates, travelling with the number.

### 5. The staleness warning fires, and stays quiet

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

If a claim turns out to be false, change the README in the same pass. A claim that has
been disproved and left standing is worse than one that was never checked, because the
next reader has no way to tell them apart.

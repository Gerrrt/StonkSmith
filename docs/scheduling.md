# Scheduling

Everything cron needs has been in the tree for a while. A failed run exits non-zero,
`--quiet` says only what went wrong, and `exclude_accounts` lives in config rather than
in a flag precisely because a run from cron has nobody to remember one. What was missing
is the part that cannot be inferred from any of that: **the five brokers do not schedule
alike, and two of them do not schedule at all.**

That gap is the whole reason this file exists. A scheduling section that lists five
brokers and quietly fails on two is worse than no scheduling section, because the failure
is not loud once and then over. It is loud every night, and a cron job that errors every
night gets muted — after which the portfolio has stopped updating and nothing says so.
The muting is the bug, and it is caused by the documentation rather than by the code.

**This file is the record.** The README summarises it in one place — the
[*Scheduling*](../README.md#scheduling) section under *Usage* — and that summary is
derived from here rather than maintained
beside it. Change what a broker can do unattended here, and change it there in the same
pass.

**And this file is about what a schedule can carry, not about whether a parser works.**
`docs/live-verification.md` records which of StonkSmith's claims a live run has settled.
This one records which of them a run with no human in front of it can make at all. The
two overlap at exactly one row and it is called out below, but they answer different
questions and a claim proven in one is not proven in the other.

---

## What a schedule already had

Three things, none of them added for this and all of them load-bearing:

- **A failed run exits non-zero.** `1` when a module reported it did nothing, could not
  log in, or never reached the database; `130` for an interrupt, kept distinct so a
  scheduler can page on a real failure and shrug at Ctrl-C. The
  [*Exit codes*](../README.md#exit-codes) table in the README is the reference.
- **`--quiet` reports failures only.** Which is what an unattended run wants: cron mails
  on output, so a run that says nothing when it worked is a run that only mails when it
  did not.
- **`exclude_accounts` is config, not a flag.** A standing overlap between two brokers
  that can both reach one account has to be stated once, somewhere a scheduled run reads
  it without being told.

What no amount of that settles is which brokers can run with nobody watching.

---

## The five, and what each can do unattended

| Broker | On a schedule | Why |
| --- | --- | --- |
| `tsp` | Yes | No credential in the daily path. Units are config, prices are a public file |
| `snaptrade` | Yes, until the connection expires | An API key, and a browser step every few weeks to renew it |
| `schwab529plan` | Yes | Posts a form with a stored credential. No browser, no bot detection, no session to keep |
| `ally` | `--from-prices` only, and it is not a scrape | Ally honours no restored session, so a scrape needs a human every time |
| `fidelity` | No — replace it with SnapTrade | Browser-backed behind bot detection and 2FA |

The first three are the uninteresting rows, and they are uninteresting on purpose: put
them in a crontab and they work. The last two are the reason this file is longer than the
table.

### SnapTrade expires, and that is not a failure

Connections lapse after a few weeks and re-authorising is a browser step —
`scripts/snaptrade_register.py link` again. Between renewals the sync is unattended, and
when the connection goes the run reports it and exits non-zero, so the schedule surfaces
it the same way it surfaces anything else.

Worth knowing rather than discovering: a disabled connection does not error at the API.
SnapTrade keeps serving its last cached balance. StonkSmith skips those accounts loudly
rather than recording a stale number as a fresh one, which is why an expiry shows up as
accounts going missing from a run rather than as a connection error.

---

## Ally on a schedule is a different thing from Ally

This is the entry that has to be read rather than skimmed, because the flag that makes
Ally schedulable does not do what scheduling the other brokers does.

**The scrape cannot be scheduled.** Settled across nine live runs, both browsers, both
persistence models: Ally refuses a restored session however it is stored. The saved jar is
not the problem — it carries every token the site issues — but the next run is answered
`401`, the app calls `auth/anonymous_invoke`, and the page renders signed out. Firefox with
`storage_state`, Firefox with IndexedDB included, and a persistent Chrome profile were all
tried and all three were refused. `docs/live-verification.md` has the evidence.

That is a property of Ally's auth rather than a defect in StonkSmith. Nothing StonkSmith
stores reconstitutes a session Ally will honour, so there is no version of this that a
future commit fixes.

**What can be scheduled is `--from-prices`, and it is a repriced stale unit count rather
than a fresh scrape.** It opens no browser and signs in to nothing. It multiplies the
units *the last signed-in run recorded* by today's published close:

```bash
uv run stonksmith ally -M ally --from-prices --quiet
```

Both halves of that sentence matter. The price is today's. The units are as old as the
last time a human signed in, and they are wrong the moment a deposit lands — the total
drifts low and keeps drifting, silently, until somebody signs in again. The arithmetic
stays exact the whole time, which is what makes it dangerous: nothing about the number
looks stale.

So the run says so itself, on every account it values:

```text
[*] Individual (...0847): priced at 2026-08-06; units as recorded 2026-08-07 20:40:18. Re-run with --manual-login after a deposit.
```

That line is not decoration and it is not a warning about a rare case. It is the standing
description of what a scheduled Ally run produces. A schedule that mails only on failure
will never show it to anybody, which is the argument for reading it here instead.

Three more things it does not do:

- **It does not seed itself.** Against a database no signed-in run has written, it refuses
  rather than valuing the account at nothing. Run `--manual-login` once first.
- **It does not touch the sheet.** Only a scrape syncs, so the sheet step below is what
  makes a priced run visible.
- **It does not notice new accounts.** It values what is already on record.

**So Ally has two paths and they are not interchangeable.** The scheduled one keeps a
number approximately right between sign-ins. The manual one is the only thing that makes
it right. Put a recurring reminder to run `--manual-login` wherever deposits are already
tracked; the schedule cannot do it and will not ask.

---

## Fidelity is not scheduled, it is replaced

Fidelity fronts its login with Akamai Bot Manager and ThreatMetrix, which reject a
scripted sign-in before the form renders, and 2FA sits behind that. `--manual-login` is
the documented way in, and it is a human at a browser by construction.

The answer is not to schedule the scraper. It is to stop running it: SnapTrade covers
Fidelity, and it is exactly what takes the account from attended to unattended.
[*When two brokers can reach the same account*](brokers.md#when-two-brokers-can-reach-the-same-account)
is the procedure.

One thing to get right while switching, because it is the failure that looks like success:
if both the `fidelity` scraper and SnapTrade run, both write, and the `Accounts` tab holds
the money twice. The tab has a total on it, and that total is wrong in the direction that
looks good. Pick one owner — for Fidelity that is SnapTrade — and drop the other from the
schedule.

**Dropping it from the schedule is half the job, and the half that does not fix the
total.** The sheet reads every database in the workspace rather than every broker that
ran, so a retired scraper keeps contributing its last values forever — the accounts stay
on the tab, stay in the total, and stop having an `As Of` anyone can defend. A crontab
with no `fidelity` line and a `fidelity.db` still in the workspace double-counts exactly
as much as one that runs it nightly. The database has to leave the workspace;
[*Neither remedy touches what is already on
disk*](brokers.md#neither-remedy-touches-what-is-already-on-disk) is the procedure, and
`stonksmithdb stale` is where the leftovers announce themselves.

---

## A worked crontab

Four things this shape respects, all of them consequences of how the tool works rather
than preferences:

- **The broker is a positional subcommand**, so one process runs one broker. There is no
  `--all`. N brokers is N lines.
- **Two runs inside the same UTC second collapse to one snapshot**, because `scraped_at`
  is stamped to the second and is half the snapshot's key. Stagger the entries; do not
  fire them together. TSP in particular is fast enough to matter.
- **The sheet goes last**, after every broker has written, because it renders what the
  databases hold at the moment it runs.
- **`--quiet` on every run**, so cron mails when something broke and stays silent when
  nothing did.

Markets close at 16:00 ET; these run after the close, on weekdays only.

```cron
PATH=/usr/local/bin:/usr/bin:/bin

30 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith tsp -M tsp --quiet
35 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith snaptrade -M snaptrade --quiet
40 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith schwab529plan -M schwab529plan -id 1 --quiet
45 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith ally -M ally --from-prices --quiet
50 18 * * 1-5  cd ~/StonkSmith && uv run stonksmithdb sheet
55 18 * * 1-5  cd ~/StonkSmith && uv run stonksmithdb stale
```

**There is no `fidelity` line, and that is the point of the file.** There is an `ally`
line and it is `--from-prices`, which is a repriced stale unit count. Neither absence is
an oversight to be corrected by adding a sixth entry.

`PATH` is set because cron's is short and `uv` usually is not on it. `cd` because the
project is a `uv` workspace and `uv run` resolves it from the working directory.

**Check that `PATH` actually contains `uv` before trusting a night of it.** The three
directories above are the usual system ones, and uv's own installer does not use any of
them — it puts the binary in `~/.local/bin`. `which uv` says where yours is; add that
directory, written out in full, because cron does not expand `~` or `$HOME` in a `PATH`
assignment and a literal `$HOME/.local/bin` is simply a directory that is not there. A
`PATH` without `uv` on it fails every entry the same way, on the first night.

**And check the `cd`, because `~/StonkSmith` above is a guess.** This file cannot know
where you keep the repository — the author of it does not keep it there — and a `cd` that
fails takes its entry with it, through the `&&`. So a wrong path fails every entry the
same way and on the same first night as a wrong `PATH`, while looking nothing like it in
the mail. From inside the checkout,
`sed -i '' "/^[0-9]/ s|cd ~/StonkSmith|cd $PWD|" scripts/stonksmith.cron` rewrites all
six; drop the `''` on GNU sed. The `/^[0-9]/` restricts it to the entries, which are the
only lines beginning with a minute — without it the command also rewrites the comment in
that file which documents the command, and the instruction destroys itself the first time
anybody follows it. Both of these are loud failures rather than quiet ones, which is the
good version of wrong — but neither is worth learning from a week of cron mail.

That same schedule is committed as [`scripts/stonksmith.cron`](../scripts/stonksmith.cron),
commented, so it can be pasted into `crontab -e` rather than retyped. Paste it; do not
run `crontab scripts/stonksmith.cron` unless you mean to replace your whole crontab.

### Before the first night

Every line above is a no-op, or a nightly failure, until its broker is set up. None of
this is new — it is [`brokers.md`](brokers.md) read in the order a crontab needs it —
but a schedule is exactly where a half-finished setup stops being visible, because the
run that would have told you is the one `--quiet` silenced.

- **`tsp`** — `fund`, `units` and `units_as_of` filled in under `[TSP]`, or the run has
  no unit count and values nothing. The four DFAS keys are optional and go in together
  or not at all.
- **`snaptrade`** — `clientid` in config, the consumer key in the keyring, and a linked
  connection. `scripts/snaptrade_register.py status` is the check.
- **`schwab529plan`** — the credential actually stored, and `-id 1` actually being its
  id. `uv run stonksmithdb`, broker `schwab529plan`, then `add creds`.
- **`ally`** — **a `--manual-login` run must have happened first.** This is the one that
  bites, because `--from-prices` reads units out of the database: against one no
  signed-in run has written it refuses and exits `1`, so an unseeded install fails every
  night rather than once.
- **the sheet** — the spreadsheet reachable and authorized. It creates its own tabs.

And two standing facts a schedule cannot state for itself. Where one account is
reachable by two brokers — a Schwab-held 529 that `schwab529plan` scrapes and SnapTrade
also reports — `exclude_accounts` has to name it, or the `Accounts` tab holds the money
twice; see [*When two brokers can reach the same
account*](brokers.md#when-two-brokers-can-reach-the-same-account). And a SnapTrade
connection expires every few weeks, which surfaces as accounts quietly going missing
from a run rather than as an error.

### The sheet step reports

`stonksmithdb sheet` runs the one command and exits: `0` when the tabs were rewritten, `1`
when the sheet could not be reached, when a tab refused to be written, or when a broker
database could not be read. That last one is a success that produces a wrong total — the
sheet renders, missing a whole broker's money — so it is reported as a failure rather than
as a good night.

The interactive shell is unchanged; `uv run stonksmithdb` with no arguments still opens
it.

### The freshness step is the one that catches silence

Every line above reports when it *breaks*. None of them reports when it stops
happening, and this file opens by saying why that matters: a job that errors every night
gets muted, and a muted job looks exactly like a job that is fine.

The design makes it quieter still. The `Net Worth` series carries an account's last value
forward for thirty days, and the `ally --from-prices` line reprices a unit count that a
signed-in run recorded — possibly weeks ago. So a broker can go dark and the totals keep
moving, the chart stays smooth, and every entry above exits `0`.

`stonksmithdb stale` is the entry that asks the other question. It reads the databases
and nothing else — no login, no Sheets, no network — and exits `1` when any account's
`As Of` is missing, unreadable, or older than seven days:

```
$ uv run stonksmithdb stale
[*] Freshness in 'default': 16 accounts, nothing older than 2026-08-04 (7 days).
[-] tsp / TSP L 2060: as of 2026-01-31, 192 days old.
[-] 1 of 16 accounts are stale.
```

A day count overrides the window: `stonksmithdb stale 30` for a workspace whose brokers
genuinely report monthly. Zero is legal and means "must have reported today"; a negative
count is refused, because it puts the cutoff in the future and would call this morning's
scrape stale.

**It runs last, after the sheet**, for the reason the sheet runs last: it reports on what
the databases hold at the moment it runs, and every entry above changes that.

Three things it counts as stale, and the third is the one worth knowing about:

- **No `As Of` at all.** A number with no date attached is a claim about no particular
  day.
- **An `As Of` older than the window.** The ordinary case.
- **An `As Of` nothing could parse.** A parser that stopped matching its source can leave
  text where a date belongs, and text sorts *above* every real date — so the broken
  account would otherwise read as the freshest one you own. The dashboard's staleness
  panel has this hole, because a Sheets `QUERY` compares strings; the check does not.

  This covers dates that merely *look* right as well as obvious rubbish. `2026-13-45` is
  the right shape and is not a day, and comparing it as text puts it above any cutoff —
  so a check that only matched the pattern would call it fresh. A padded ` 2026-08-10 `
  is reported too rather than quietly trimmed: nothing trims it on the tab either, so
  accepting it here would have the panel call that account stale while this called it
  fresh, and the two agreeing is the point.

### What the mail will look like

`--quiet` lowers the log level. It does not suppress the progress bar, which is written to
the console rather than through the logger, so a run that worked can still put a line of
bar into cron's output. Redirect stdout per entry if that matters; the exit status is the
part that carries the meaning.

---

## What a scheduled run has, and has not, been observed doing

The honest summary, and it is shorter than the section above deserves.

**`docs/live-verification.md` adds no row for any of this, on purpose.** Scheduling makes
no new claim about a live site — it makes claims about brokers whose rows either already
exist there or were never opened. Adding rows would restate them in a second place and put
the two out of step at the first change.

What that file already says, and what it means here:

- **`Ally — valuing from published prices without a login` stands at `Yes`.** It read
  `No` when this file was written, and the sharpest thing this section used to say —
  that the one scheduled path recommended for Ally was the one path not verified — is no
  longer true. It was run end to end on 2026-08-10, three times, against a real account
  with nobody signed in. Two of those findings are what a crontab actually rests on. It
  opens no browser, and the filesystem says so rather than the log: the same command
  with the flag removed left session state behind, and these runs left the directory
  empty. And against a database with no units on record it refuses and exits `1` instead
  of valuing nothing — so a fresh machine, or a lost `ally.db`, mails you rather than
  quietly reporting a smaller portfolio. **`Ally — one row per account across runs`
  settled `Yes` alongside it**, which is the other thing a nightly entry leans on:
  repeated runs added snapshots without adding accounts.
  None of that makes the units any fresher, and the same runs are what pin the opposite.
  The units' stamp held at the last sign-in's time across all three while the newest
  snapshot's own time moved under it. The staleness this file leads with is therefore
  real, does not drift younger as the snapshots accumulate, and is reported by nothing
  except the line the run prints on every account it values.
- **TSP's whole unattended path is confirmed live.** The share price download, the DFAS
  pay table's download *and* its parse, the contribution accrual and the database write
  were all run without a human on 2026-08-10, and every one of those rows now reads `Yes`.
  This is the row a crontab can lean on hardest. One thing to carry into it anyway: DFAS
  fingerprints its callers, and that file says plainly that what works today is not a
  guarantee. A refused pay table reports itself and leaves the anchored mark exactly as it
  was — it stalls the accrual rather than corrupting the number — but the way back is
  `--pay-table` with a page saved from a browser, which is a human. A schedule that starts
  mailing about the pay table is asking for that, not for a retry.
- **`snaptrade` and `schwab529plan` were run for real on 2026-08-11, and their place in
  the table above no longer rests on how they are built.** Four SnapTrade runs settled
  the key reaching the API, accounts and balances and positions reaching the database,
  the liability and exclusion skips firing against a real card and a real overlap, and
  nine account rows holding steady while snapshots went 168 → 199. One Schwab 529 run
  settled the form-post login, both parses and the write. What those runs did *not*
  settle is worth carrying into a crontab as much as what they did: SnapTrade's
  transaction path has been exercised at one movement, so the pagination behind it has
  not been exercised at all, and neither the disabled-connection skip nor the freshness
  guard has ever had a real case to fire on. Those two wait on a connection lapsing
  rather than on anybody running anything.

None of that argues against scheduling them. It argues for reading the first week of cron
mail rather than assuming silence means success — and for knowing that the first lapsed
SnapTrade connection will be the first time that path runs anywhere but in a unit test.

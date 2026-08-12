# The sheet

The five tabs StonkSmith owns, what each one promises, and why the dashboard has
to be constructed rather than read.

**This is a reference chapter, not a record.** It describes the sheet as it is
today. [`live-verification.md`](live-verification.md) is the record of which of
these tabs a live run has read back against a real spreadsheet, and which three
claims *about the sheet* are still open — a broker with the transaction volume to
put the question, a workspace whose brokers scraped on different days, and a run
of `verify tabs` since the allocation blocks acquired a check that reads them.
That file also carries a gap that is not about the sheet: the `fidelity` broker
has never been run against the real thing at all.

Every row here is rendered from the databases described in
[`database.md`](database.md). The sheet holds nothing the databases do not.

---

## The sheet is output

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
[Upgrading an existing database](database.md#what-is-stored).

### The five old tabs

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

### Refreshing without scraping

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

Words after the command name run as one command and then exit, which is the form
a schedule calls:

```bash
uv run stonksmithdb sheet
```

It exits `0` when the tabs were rewritten and `1` when the sheet could not be
reached, a tab refused to be written, or a broker database could not be read.
That last one renders a sheet whose total is short by a whole broker, which is a
wrong number rather than a stale one, so it is reported as a failure rather than
as a good night. Piping into the shell has always worked, but it exits `0`
however the command went — and a scheduled step that cannot fail is one that
stops working silently.

`verify`, beside it, checks what a successful sync cannot show. Two halves, and
either can be run alone:

`verify tabs` reads the machine-owned tabs back. A write that returned says the request
was accepted, not that the values arrived as the kind of thing they were meant to be —
so this checks the banner on all five, row 2 against the column contract on the
four that have one, the movement count against the databases, that every
`Processed On` is `YYYY-MM-DD` and sorted newest-first within its account, that
money came back as a number rather than as text, and that the dashboard's two
totals agree. The last two used to be marked as resting on an assumption about
what a rendered cell returns; the 2026-08-10 run settled that, since a wrong
assumption would have failed rather than passed quietly.

`verify guard` creates one scratch tab and asks the ownership check whether a
defaced first cell is refused, whether text below a blank one is refused, and
whether a wholly empty tab is adopted, then deletes the tab again. No tab the sync
writes is opened, and a tab of that name which already exists stops the run rather
than being adopted.

`verify` takes the same scripted form and the same statuses: `1` when a check did
not behave, and `1` when a half could not be run at all. Not reaching the sheet
says nothing about the guard, and "nothing known" must not exit the way "checked
and clean" does.

Two things neither half covers: that a refusal aborts the *whole* sync, and that an
absent value arrived as an empty cell rather than an empty string — read back, those
two are the same value, so only a formula's behaviour tells them apart.
[`live-verification.md`](live-verification.md) has both steps.

## What a tab may promise

Those five tabs each grew their own layout, and nothing shared a column:
`Balance` in one tab and `Value` in another named the same thing, while
`Synced`, `Price date` and `Units as of` were three answers to one question. A
formula pointing at `SnapTrade!D:D` broke the day a column moved.

`src/stonksmith/etc/portfolio.py` settles that. It reads every broker database in the
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

### Why this tab has to be constructed rather than read

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

`src/stonksmith/etc/portfolio_sheet.py` is the only thing that writes them: one read of the
workspace, one authorization, five tabs. Values go up raw, so a number arrives
as a number — and so an account whose display name begins with `=` stays a name
instead of becoming a formula the spreadsheet runs.

### What the dashboard shows

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
- An allocation **by account kind** — `529`, `INVESTMENT`, `LOC`, whatever the
  source calls it. It is the one breakdown that costs nothing: `Kind` is already
  on every account row, and because the slices are account balances they include
  the uninvested cash and add up to **Total (USD)** exactly.
- An allocation **by position**, which is the one with the honesty problem.
  Holdings do not sum to the portfolio, so a share of the holdings subtotal
  renders a portfolio that is 30% cash as fully invested — every slice
  overstated, and the numbers still adding to 100%. So **Cash and uninvested** is
  a named slice, pointing at the very cell **In accounts, not in positions**
  already publishes rather than subtracting a second time, and every share
  divides by **Total (USD)**. Every block says so in its header instead of
  leaving the base to be inferred, and every one closes with **Slices sum to** —
  the sheet's own arithmetic over the cells it wrote, where a wrong base shows up
  as a share column that does not come to 1.
- An allocation **by asset class**, and only if you asked for one. No source
  supplies a class: a ticker, a fund code and a TSP fund is all any of them gives,
  and those are the same field — `Symbol` — which is what makes one hand-kept
  table enough to cover all five brokers. So the mapping is yours, one
  `SYMBOL = Class` per line under `asset_classes` in
  `~/.stonksmith/stonksmith.conf`, and the block groups by what it says rather
  than deriving a class from a ticker. Symbols are matched **exactly** as the
  source spells them, so a line that matches nothing classifies nothing — which
  looks identical to having written no line at all, and is therefore reported by
  the run. Anything held and unlisted lands in one **(unclassified)** slice
  rather than being dropped, cash is a named slice here for the same reason it is
  above, and with no mapping at all the block is not drawn: one 100%
  "(unclassified)" wedge is not a breakdown. Sector and region stay absent for
  the reason class used to be — nothing states them, and no lookup has been added
  to ask.
- When that gap goes negative — a position counted twice — the position block
  refuses to draw and says by how much, instead of rendering a negative wedge
  with every other share inflated to make room for it. The class block refuses
  with it: it is the same money grouped a second way, so a version of it that
  drew alone would be the same lie with better manners. The account-kind block
  cannot have the problem and still draws.
- **Not read** — one row per database that would not open, with the reason. A
  total short by a whole broker looks perfectly reasonable, so it is stated on the
  same tab as the total rather than only in the run's output.

If every database fails to read, nothing is written at all. Clearing the tabs
there would replace a correct sheet with a blank one and report success for it.


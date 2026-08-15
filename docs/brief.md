# The morning brief

The databases have always known what changed overnight and nothing ever asked them.

The sheet shows what is true now. `stale` reports what has stopped moving. Neither
answers the question a person actually opens a dashboard with — *what moved since I last
looked* — and neither is a thing that turns up on its own. Until this existed, keeping
up with the portfolio meant remembering to open a spreadsheet and comparing numbers by
eye against a memory of yesterday's.

`stonksmithdb brief` reads the databases, renders one self-contained HTML file, and opens
it. A LaunchAgent runs it at 06:30 on weekdays, so the remembering is the part that got
automated.

**The README summarises this file** in the [*The morning brief*](../README.md#the-morning-brief)
section under *Usage*, and that summary is derived from here rather than maintained
beside it. Change a claim here and change it there in the same pass.

---

## What it reads, and what it never touches

No login, no browser, no network. It opens the same SQLite files `sheet` and `stale` do,
through the same single read path — `read_workspace()` in `etc/portfolio.py` — and writes
one HTML file and one small JSON file. That is what makes it cheap enough to schedule
every morning rather than occasionally, and it is why it cannot fail in any of the ways a
broker can.

The dividend figures look like an exception and are the argument for the rule. They come
from a price feed, which is why the fetch is a *different command* — `stonksmithdb
dividends`, run beside the scrapes — leaving a cache file the brief reads the way it reads
the baseline. When that cache is missing or old the brief still renders, and says so.

It deliberately does **not** scrape. At 06:30 the market is shut, TSP has not published,
and the two browser-backed brokers want a human at a sign-in page. The brief reports on
the previous evening's run — see [`docs/scheduling.md`](scheduling.md) — so a morning
where it says *no new scrape* is reporting a failure of the nightly agent, not of itself.

## The number at the top

**The headline total is built on the Net Worth series, not on any per-broker read.** This
is the one design constraint the feature has, and everything else follows from it.

`BrokerDatabase.get_daily_change()` exists and looks like the right tool. It is not: it
computes a `LAG` over one broker's snapshots, and summing five of those re-creates exactly
the bug `net_worth_history()` was written to prevent. Brokers do not scrape on the same
day — TSP runs unattended every weekday, Ally needs a manual sign-in and routinely goes a
week — so a date on which only TSP ran carries TSP's movement and four brokers' worth of
silence. The silence reads as a fall. The portfolio appears to lose an entire account
overnight, recover the next day, and nothing anywhere reports an error.

The series already carries each account's last known value forward onto every observed
date, so that **every date sums the same set of accounts**. That is the only axis on which
two dates can honestly be subtracted, so it is the only one the brief uses.
[`docs/sheet.md`](sheet.md) covers the series itself; the rule that matters here is the
consequence.

### Which is why the page says how much of it was read

Counting the carried accounts is what makes the total right. Saying so is what makes it
honest, and those are separate claims.

On a night when only TSP ran, "▲ $1,500" is a real movement for one account and a carried
number for four. Presented as a portfolio move it asserts a precision the reading does not
have. So the headline always carries its basis:

> 1 of 5 accounts were read on 2026-08-13; 4 carried an older value forward. The change
> above is what those readings moved, not what the whole portfolio did.

and on a morning when everything ran, it says that instead. A caveat printed every day is
one nobody reads by the end of the week, which would make it useless on the morning it
means something.

The same distinction runs through the mover tables, where a row whose newer value was
carried wears a `carried` pill, and through the sparkline, where only the dates something
was actually read on get a dot. A stretch of carried dates is a straight line drawn
between two readings, and marking the readings is what stops the line claiming to be a
measurement along its whole length.

## What it is worth, and what it cost

The headline answers *what moved since I last looked*. The tiles under it answer a
different question — *what have I made since I bought it* — and that one depends on a
field most sources here do not report.

**Cost basis is the fault line.** SnapTrade states one. An employer 401k, TSP and a
scraped 529 do not, and every figure that divides by it is therefore absent for those
positions: purchase price, gain, growth, yield on cost, the win/loss flag. They render as
a dash.

The tempting bug is to let an absent cost become `0.0`. It does not raise, it does not
look wrong, and it reports a holding that has made exactly nothing as though somebody had
checked — next to what is often the largest number on the page. So absent stays absent all
the way to the screen, and where a total *is* summed over the subset that has a cost, the
tile says so:

> Portfolio Gain $ — ▲ $2,089.89
> across 9 of 12 positions; 3 report no cost basis

Same reasoning as the observed/carried split one section up. A real number about part of a
portfolio, presented as the portfolio's number, is the failure this project keeps finding.

### Portfolio Value is the account total, not the sum of the positions

Those are different numbers and both are correct. Accounts include whatever is sitting
uninvested in a settlement balance and in no holding; positions do not. `Portfolio` has
carried `total()` and `invested()` apart for exactly this reason.

The tile reports the account total, so it agrees with the headline directly above it, and
names the remainder rather than hiding it — *"12 holdings, plus $369.50 not in any
position"*. A page carrying two figures a few inches apart, both fairly called "portfolio
value", is one the reader has to reconcile by hand.

Dividend **yield**, by contrast, divides by the position total: a yield is what the
holdings pay on the holdings, and including idle cash would report a portfolio yielding
less the more of it is waiting to be invested.

The difference between the two is cash, exactly — the SnapTrade sync computes an account's
value as its positions plus its cash balance, so the gap is that cash by construction rather
than a residue of two numbers struck at different times. See
[`docs/brokers.md`](brokers.md) for why it is computed rather than taken from the total
SnapTrade reports.

**Negative is a debt, not a discrepancy.** A brokerage account worth less than the fund
inside it has money borrowed against it — an overdraft transfer out, or a margin loan — and
the tile names it: *"12 holdings, less $800.00 borrowed against them"*. This read "positions
total $1,036.22 more than the account balances" while the value came from SnapTrade's
daily-cached total, and back then that wording was the honest one: two numbers genuinely
did disagree. They no longer can.

### Two dividend figures, and they are not the same claim

**Indicated Income** is what the holdings would pay over a year at today's positions:
each fund's trailing per-share distributions, times the units held. A forecast.

**Received** is money that actually arrived — trailing twelve months of `DIVIDEND` /
`DISTRIBUTION` rows, cut on the source's own `processed_on` rather than on `first_seen`,
because a workspace rebuilt this morning saw every movement today and a window cut on the
watermark would admit everything or nothing.

The tile shows the forecast and states the received figure underneath it, in that order
and never merged. The reason for the order is uncomfortable but honest: **received is
`$0.00` in this workspace and always has been.** These brokers report contributions and
transfers and do not itemise a distribution, so the money is real and simply never appears
as a movement. A tile that reads zero every morning is one nobody looks at, and it was not
even wrong. The reason they are never merged is the same fact from the other side: a
forecast printed under a heading that means *money that landed in an account* is a lie the
reader has no way to catch.

So the tile reads:

```
Indicated Income   $240.00   a year at today's holdings, across 9 of 13 positions;
                             nothing received in the log yet
```

**Indicated Yield is divided by the holdings it knows, not by the portfolio.** Two thirds
of a real workspace can sit in a 401k, a TSP fund and a 529, none of which has a public
ticker. Dividing nine known funds' income by all thirteen positions' value reports `0.29%`
where the answer for what is actually known is `1.33%`, and nothing in the number tells
the reader which they were given. The coverage travels with the figure, on the same rule
the priced/unpriced gain split follows:

```
Indicated Yield      1.33%   over $18,000.00 of holdings with a published dividend
```

Where the feed answered for nothing at all, both tiles show `—` and say **"no holding has
a published dividend"**. A dash rather than `0.00%`, because a yield of zero is a claim
about the holdings and an empty cache is a claim about the cache.

#### Where the per-share figures come from

`stonksmithdb dividends` — the only command in the tool that reaches a price feed on
purpose. It asks the same chart endpoint the prices come from, with `&events=div`, so one
request answers both and the two can never disagree about which symbol they describe.

It runs **beside the scrapes, not beside the brief**, and that is the whole reason it is a
separate command. The brief's contract is no login, no browser, no network; a dividend
figure it had to fetch would trade that away for a number. The cache lands at
`~/.stonksmith/dividends.json` at `0600` — a per-share amount is public on its own, but
the *set* of symbols asked about is the list of everything the household holds.

What is stored is **dividends per share, never an income**. A per-share amount stays true
however many units are held; a stored income would be wrong the moment a share was bought.

Two distinctions the cache keeps that a simpler one would lose:

- **A fund that pays nothing is not a symbol the feed never heard of.** Both come to
  `0.0`. Only the first is a fact about money — the second is a ticker like `FCASH` that
  the feed answers with a 404. The record carries `found` separately, and an unanswered
  symbol produces no figure rather than a zero one.
- **A partial year says so.** A fund listed four months ago has paid four months of
  dividends, and reporting that sum as an annual figure understates its yield by two
  thirds. The coverage is measured from the oldest payment actually inside the window, so
  a fund that has paid once, last month, covers a month.

**A failed fetch keeps the figure it already had, with its own date.** The refresh rebuilds
the whole file in one pass, so this is not automatic — it is the difference between one
rate-limited night costing nothing and one rate-limited night erasing every yield the brief
can report. A rate limit, an HTML block page and a genuine 404 all arrive at the caller
identically, and only the last is a fact about the symbol, so none of them is allowed to
overwrite a good figure.

The date matters as much as the figure. A carried number restamped with today's date would
make the staleness warning blind, because the file is written every night whether or not
anything was fetched — so each symbol carries the day *its own* figure was fetched, the
staleness check reads the oldest of those, and the command names every symbol it carried:

```
[-] Could not refresh SWPPX (…); keeping the figure from 2026-08-01
[-] 1 of those are older figures kept because the feed could not be reached: SWPPX
```

A run that carried everything is a refresh that has stopped refreshing, and it looks
identical to a good run in the counts alone.

**Only the feed's own failures are carried.** The handler catches a network error and a
payload this cannot use, and nothing else — so a bug in StonkSmith ends the run non-zero
and the nightly script reports the night. Caught, it would have been filed as "kept the
earlier figure" and cached as a success, and the brief would have rendered perfectly every
morning off code that had stopped working. A broad catch in front of a fallback hides
strictly more than one in front of a zero.

### The holdings table

Every position, not the top movers — the difference between *what changed* and *what do I
own*. A position that has not moved is absent from one and belongs in the other.

Columns follow the operator's own sheet: Symbol, Shares, Purchase, Price, Cost, Market
Value, Day, Gain, Growth, Trend, W/L. Two notes on the ends of it:

- **Day** is the move between this position's last two readings, from the holdings history
  rather than the account series. With the opening-bell agent running there are two
  readings most weekdays, so it is an intraday move as often as an overnight one.
- **Trend** is a per-position sparkline over that same history. It needs
  `read_workspace(with_history=True)`, which is off by default and which only the brief
  asks for: it is one row per position per snapshot, an order of magnitude more than the
  current positions, and the sheet sync would otherwise pay for it on every broker run.
- **W/L** is three-valued. A position with no cost basis is neither a win nor a loss, and
  defaulting it to "L" would flag every 401k, TSP and 529 holding as losing money.

A position whose *unit count* moved since the last brief carries a note under its symbol.
That is the one thing the old position-movers list said that this table does not: a row
whose value rose on an unchanged count was repriced by the market, and one whose count rose
was bought. Only the second is an event.

Every row carries a dot in its owner's colour, from `[ACCOUNTS] colors` — one line
per person covers every account they hold, matched as a substring of the display name
with the first line winning. **The colour is redundant with the name beside it by
design:** the name already says whose account it is, so the page reads correctly in
monochrome and to a colourblind reader. Colour names come from a closed set, because the
value lands in an HTML class attribute and a config file is not a stylesheet.

A position worth less than `[BRIEF] min_position` loses its row — a settlement account
leaves a few cents of a sweep fund beside a real holding, and it renders as a full row
with a dash in every derived column. **Display only:** the portfolio value, the invested
figure and the cash line all still count it, and the number hidden is stated under the
table. A row removed from a page is a presentation choice; a dollar removed from a total
is a lie.

A symbol links to its quote page, where it has one. Only something that looks like a
public ticker — one to five ASCII letters — is linked, which keeps a link off `Q4R7`
(a 401k fund code), `70310` (a 529 portfolio number) and `L 2060` (a TSP fund). Those are
real holdings with nothing public to point at, and **a link that 404s is worse than no
link**: the reader has to click it to find that out, once a morning, until they stop
trusting any of them.

ASCII specifically, because `str.isalpha()` is true of Cyrillic and full-width characters
and a symbol arrives off a scraped page. Between that and `[BRIEF] fund_link` refusing any
template that is not `https://`, there is nothing left to put in an `href` that was not
five letters to begin with.

Every row names the account holding it, always. The same fund is routinely held in several
accounts — one workspace has SWPPX in four — and a table showing the symbol alone renders
those as identical rows with different numbers, with no way to tell which is which.

The **Industry** column has no equivalent here. No source StonkSmith reads states a sector,
so the nearest thing is the `[ALLOCATION] asset_classes` table — declare symbols there and
they join the account name under each holding.

## Accounts you can see but cannot scrape

Some accounts have no API, no scrapeable page and no export — a plan portal that shows a
balance and a fund and offers nothing else, whose only way out is a transfer that has not
opened. Leaving one out makes every total short by its value while looking complete, and
unlike a broker that breaks, nothing ever says so.

The `manual` broker values those from a unit count you supply and a price the market
publishes:

```ini
[MANUAL]
accounts =
    Sam Trump | SPYM | 2.000000 | 2026-08-10 | 150.00
```

```bash
uv run stonksmith manual -M manual
```

**What is stored is a unit count, never a balance**, and that is the whole design. The
`[TSP]` config comment states the rule in one line: *a balance is true for one day, so
storing it would leave a value that silently rots*. Units move only when money goes in or
out, so an account nobody is funding has a count that stays exactly right while a published
price does the moving. A hardcoded balance would be correct the morning it was typed and
wrong every morning after — and because it feeds the Net Worth series, it would draw a flat
line through that slice of the portfolio while looking entirely like data.

To turn a balance into a unit count, divide it by that day's close — a balance is units ×
price, so the division inverts it exactly. Where the account lists its purchases, deriving
the count from those is better still: each buy is an exact amount on a known date, so the
result is reproducible and the fifth field can carry what was paid, which makes the account
report a real gain rather than the dash every cost-less holding shows.

Five fields: `Name | SYMBOL | units | units_as_of | cost_basis`, the last optional. The
symbol is whatever the chart feed knows the fund by — the same feed Ally's `--from-prices`
reprices against, deliberately, since two brokers pricing the same fund from two sources
would disagree about it on the same day.

Three things it will not do:

- **It never writes a value it did not compute.** A symbol with no published close is
  skipped and reported, not written at zero — a zero is a number rather than an error, and
  the series would carry it forward for thirty days.
- **`as_of` is the price date**, not the run's clock and not the unit date. That is what
  makes a manual account age visibly beside scraped ones: a stale price shows up in
  `stale` exactly as a stale scrape does.
- **It records no transactions.** A movement is money changing hands and this observes
  none — it prices a count. Writing the deposits that produced the count would be inventing
  a log from a configuration line, and the brief would report them as new movements.

What it costs: a contribution nobody types in leaves the mark short by exactly that
contribution — bounded, and self-correcting the moment the count is updated. `units_as_of`
rides on every mark so a reader can judge how much room that leaves.

## Calling accounts what you call them

Brokers name accounts for their own screens. "ACME CORPORATION SAVINGS PLUS 401(K)
PLAN" and "Individual (...1234)" are both correct and neither is what you call the account
at half past six in the morning.

```ini
[ACCOUNTS]
aliases =
    tsp / TSP L 2060 = Alex 401(k)
    ally / Individual (...1234) = Joint Brokerage (Ally)
```

The left-hand side is the `Source / Account` label the run prints — the same spelling
`[SNAPTRADE] exclude_accounts` matches on, through the same normalizer, so a label copied
from one option works in the other and case or spacing need not match.

**Nothing stored changes.** This is applied on the way out of the databases, so the sheet
and the brief say the same thing, and the identity every join and every baseline keys on
(`account_key`) is untouched — which is what makes an alias safe to add tonight and remove
tomorrow without orphaning a row.

A line matching no account is reported by the run. That is how a broker renaming an account
surfaces: the alias stops landing and the account quietly reverts to the broker's wording,
which is the outcome the alias was added to prevent. Note that the check has to allow for
the aliases having *already been applied* by the time it looks — otherwise every working
alias reports as broken, every morning.

## Since when

**The baseline is the last brief you were shown, not the last scrape.**

The stateless version — compare the two newest dates on the axis — answers a different
question, and on most days the two agree. On a Monday they do not: the stateless form
reports Friday-to-Monday as a flat carry and the weekend never appears. On a morning you
skip the email it is worse, because the run it would have been compared against has
itself become the next baseline, and that day's movement is gone from every brief that
will ever be rendered.

So `~/.stonksmith/brief_baseline.json` records what the last brief showed: the date it
reported on, what the portfolio totalled, every position's value and unit count, and a
high-water mark of `transactions.first_seen`.

### The rule that is easy to get wrong

**The baseline advances only when the newest date on the axis actually moved.**

A morning where the nightly run did not land has nothing new to report. Advancing the
baseline there records "the reader has seen up to here" about data they were already
shown — and discards the still-pending comparison against the run before it. That
movement then appears in no brief at all: not this one, because nothing is newer than the
baseline, and not the next one, because the baseline has moved past it.

A day's movement, erased by the act of looking at a screen that said there wasn't any.
Nothing errors and every subsequent number is individually correct.

So a stalled morning holds the baseline and says so out loud:

```
[*] Baseline held: nothing has been scraped since it was taken, so the next brief
    still reports the movement this one could not.
```

`stonksmithdb brief peek` is the same rule made available on purpose, for looking a second
time in one day without consuming the comparison.

### Why the transaction filter is a watermark and not a clock

New movements are the ones whose `first_seen` is above the stored mark. `first_seen` is
the run that saw a movement *first* and never moves again, because a re-scrape of an
overlapping window conflicts on the natural key and does nothing. `scraped_at` — which the
account and holding views sort on — moves every sync, so filtering on it would re-report
the same dividend every morning for as long as it stayed in the scraped window.

The mark is taken from the same column it filters, rather than from the wall clock the
brief was rendered at. Comparing a timestamp this process generated against one the
database wrote would make correctness depend on the two agreeing about format and timezone
forever.

## Running it

```bash
uv run stonksmithdb brief
```

| Form | What it does |
| --- | --- |
| `brief` | Render, open, and advance the baseline if the axis moved. The morning ritual |
| `brief peek` | Render and open without advancing. For looking again later in the day |
| `brief --no-open` | Render only, and print where. What a scripted caller wants |

The dividend figures come from a cache that a separate command fills:

```bash
uv run stonksmithdb dividends
```

This is the one that reaches the network. Run it beside the scrapes — the nightly script
already does — not beside the brief. It asks only about symbols that look like public
tickers, so a 401k fund code costs nothing, and it exits `0` even when the feed refuses a
symbol: an unanswered ticker is recorded as unanswered rather than as a fund paying
nothing.

It exits `1` when a broker's database would not open — the same escalation `sheet` makes,
and for the same reason: that is not a stale total, it is one missing a broker's money.
The brief is still written and still opened in that case, carrying the warning at the top
of the page, because a page saying the total is short by a broker is worth more than no
page and is the only place somebody who is not reading a log will see it.

## Where it goes

| Path | What |
| --- | --- |
| `~/.stonksmith/reports/<YYYY-MM-DD>.html` | One rendered brief per day it ran |
| `~/.stonksmith/brief_baseline.json` | What the last brief was shown |

Both are written `0600` inside a `0700` directory, on the same reasoning as the databases:
the rendered page states the portfolio total, every account's value and every position
behind them, which is the same information the databases hold and rather more concentrated.

Reports are pruned to `keep_days` on each write, counted by file rather than by date — the
brief only runs on the days it is scheduled, so "the last 90 files" and "the last 90 days"
are different windows, and a weekday-only agent keeping 90 *days* would hold about 64
briefs while claiming a quarter. `keep_days = 0` keeps everything, which is a real answer:
the rendered files are the only record of what you were actually shown on a given morning,
and once the baseline has moved past a date nothing can reconstruct it.

## Configuring it

```ini
[BRIEF]
open_browser = True
keep_days = 90
movers = 8
```

`movers` is a cutoff on a **ranking** rather than a threshold — the largest moves by
dollar, capped at that many rows — and the choice is worth recording because two
alternatives both looked reasonable.

A **dollar floor** (`abs(delta) > 50`) keeps a rounding wiggle on the largest account off
the page, and hides a four percent day on the smallest one. Where a single 401k is two
thirds of the money, one floor cannot be right for both ends of the book. A **percentage
floor** (`abs(pct) > 0.005`) inverts that and makes a cash account holding twelve dollars
the loudest row every morning; it also has nothing to say about an account that arrived
since the baseline, whose percentage is undefined because there is no denominator.

A ranking has no threshold to be wrong about, shows the same number of rows every day —
which is what makes it readable at half past six — and stays right as the portfolio grows.

What it costs is that it can drop a real mover, so the page says how many: *"4 more
accounts moved by less, and did not fit."* A list that ends at eight without comment
reports the eighth as the smallest thing that moved, and the reader cannot tell a quiet
morning from a truncated one — the same quiet truncation `get_transactions` is documented
as unable to back a sheet with.

The allocation block is drawn only when `[ALLOCATION] asset_classes` declares something,
on the same rule the sheet's block follows — a breakdown that is one 100% `(unclassified)`
slice tells a reader nothing, and an empty card takes up the space a reader scans.

## Scheduling it

Three agents now share a weekday, and on Pacific time they land like this:

| Local | Agent | What it does |
| --- | --- | --- |
| 06:30 | `com.stonksmith.morning` | renders the brief on last night's close |
| 06:35 | `com.stonksmith.open` | scrapes, five minutes after the 06:30 ET open |
| 18:30 | `com.stonksmith.nightly` | scrapes, after TSP has published |

**The five minutes between the first two are load-bearing.** The brief reads every database
in the workspace and the opening run writes them; fired together, the brief reports on a
workspace caught mid-write — some brokers updated, some not, and a headline delta assembled
across the seam. It would not error and it would not look wrong. Brief first is also
correct on its own terms, since a morning brief reports on last night's close, which is
exactly what the databases hold until the opening scrape touches them.
`tests/test_open_agent.py` pins the ordering.

**The close run stays at 18:30 rather than moving to the 13:00 bell**, and that is not
laziness about the schedule. TSP publishes the day's share prices in the evening, so a
13:00 Pacific run would record yesterday's price as today's — every day, with nothing
saying so. `scripts/stonksmith.cron:120` is the record for the 18:30 choice, and the same
test refuses a close run earlier than 17:00.

Installed the same way as the nightly pair:

```bash
mkdir -p ~/Library/LaunchAgents
sed "s|/PATH/TO/StonkSmith|$PWD|; s|^\(.*<string>\)/usr/local/bin|\1$(dirname "$(command -v uv)"):/usr/local/bin|" \
    scripts/com.stonksmith.morning.plist > ~/Library/LaunchAgents/com.stonksmith.morning.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.stonksmith.morning.plist
```

`gui/$(id -u)` matters twice over for this one. It is what lets a LaunchAgent read the
login keychain, which is why the nightly agent needs it, and this one additionally has to
open a browser — which an agent outside the GUI session has no display to do. Bootstrapped
into a system domain it would write a brief every morning and show it to nobody.

`StartCalendarInterval` fires on wake if the machine was asleep at the time, which cron
does not. A laptop shut at 06:30 is the ordinary case rather than the exception.

To run it now rather than waiting for the morning:

```bash
launchctl kickstart -p gui/$(id -u)/com.stonksmith.morning
```

Weekdays only, because the nightly run is weekdays: a Saturday brief would report a
carried-forward flat line by construction — a page saying nothing happened, on a day
nothing could have.

## What is deliberately not here

No drilldown, no date-range picker, no server. The brief is a snapshot, which is what a
glance at half past six wants; the databases and the sheet are where a question that needs
following up gets answered.

No email. It was the first plan and browser auto-open replaced it, which removed the SMTP
credential entirely and, just as usefully, removed email's rendering constraints — Gmail
strips inline SVG and most of modern CSS, so the sparkline would have had to become a
table of coloured cells and the page would have had to be built twice.

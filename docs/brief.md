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

`movers` is a cutoff on a ranking rather than a threshold: accounts and positions are
ordered by the size of the move in dollars, and this is how many rows the page has room
for.

The allocation block is drawn only when `[ALLOCATION] asset_classes` declares something,
on the same rule the sheet's block follows — a breakdown that is one 100% `(unclassified)`
slice tells a reader nothing, and an empty card takes up the space a reader scans.

## Scheduling it

`scripts/com.stonksmith.morning.plist` and `scripts/stonksmith-morning.sh`, installed the
same way as the nightly pair:

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

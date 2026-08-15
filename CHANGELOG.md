# Changelog

Notable changes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. This project follows [Semantic Versioning](https://semver.org/).

The version lives in `pyproject.toml` and nowhere else; a release is that number
plus a matching `v`-prefixed tag, and the release workflow refuses to publish if
the two disagree.

## [Unreleased]

### Added

- **`verify volume`**, a third check beside `verify tabs` and `verify guard`.
  `Transactions` is written in full on purpose, and past `CHUNK_ROWS` that write
  goes up as more than one request — which no workspace here is long enough to
  put in front of real Sheets. So this sends its own: `CHUNK_ROWS + 500` synthetic
  rows through the same `write_rows()`, to a scratch tab it makes and deletes,
  read back for the count and for the first and last row of each write. A
  chunk at the wrong range leaves the right number of rows in the wrong cells, so
  the count alone would agree with it. It has to be asked for by name, and it
  refuses a size that would fit in one request. Run against the real spreadsheet
  on 2026-08-15 and it holds: both requests landed and every row came back. It
  does not settle whether the real tab windows — those rows come from
  `read_workspace()` and these enter below it; see check 5 in
  [`docs/live-verification.md`](docs/live-verification.md).
- **The morning brief.** `stonksmithdb brief` reads the databases — no login, no
  browser, no network — renders one self-contained HTML page to
  `~/.stonksmith/reports/<date>.html` and opens it. A LaunchAgent at 06:30 on
  weekdays (`scripts/com.stonksmith.morning.plist`) is what makes it a reminder
  rather than a file. Net worth and its overnight change, account and position
  movers, movements recorded since the last brief, asset-class drift and the
  staleness list, in that order. See [`docs/brief.md`](docs/brief.md).
- The brief's headline is built on the Net Worth series rather than on
  `get_daily_change()`, so a night when only one broker ran is not a fall — and
  the page states how many accounts were read on the date it reports and how many
  carried an older value onto it, because a delta over four carried readings is
  not a portfolio move.
- The brief compares against the last brief you were shown rather than the last
  scrape, recorded in `~/.stonksmith/brief_baseline.json`. Monday's brief covers
  the weekend. A brief with no new scrape to report **holds** its baseline rather
  than advancing it, which is what stops a skipped morning from erasing a day's
  movement from every brief that will ever be rendered; `brief peek` renders
  without advancing.
- `[BRIEF]` config section: `open_browser`, `keep_days`, `movers`. Reports and the
  baseline are written owner-only inside an owner-only directory, on the same
  reasoning as the databases — a rendered brief states the portfolio total and
  every account behind it.
- **Performance in the brief.** A six-tile summary — Portfolio Value, Gain $,
  Gain %, Yearly Dividend Income, Dividend Yield, Win / Loss — and a full
  holdings table with Shares, Purchase, Price, Cost, Market Value, Day, Gain,
  Growth, a per-position trend sparkline and a W/L flag. Replaces the position
  movers list: that answered "what changed", and the table answers "what do I
  own", which is not a longer version of the same question.
- A figure whose source reported nothing renders as a dash rather than zero.
  Cost basis is the fault line — SnapTrade states one, a 401k, TSP and a scraped
  529 do not — so purchase price, gain, growth, yield on cost and the win/loss
  flag are absent on those rows, and the Gain tile states how many positions it
  was summed over. An absent cost becoming `0.0` would report a holding that had
  made exactly nothing, beside what is often the largest number on the page.
- The Portfolio Value tile reports the **account** total, matching the headline
  above it, and names the uninvested remainder ("plus $369.50 not in any
  position") instead of quietly summing the positions to a different number.
  Dividend yield still divides by the position total, because a yield is what
  the holdings pay on the holdings.
- Dividend income is trailing-twelve-month `DIVIDEND` / `DISTRIBUTION` rows from
  the transaction log, cut on the source's `processed_on` rather than on
  `first_seen`. A log that has never carried a dividend reports "no dividends in
  the transaction log" rather than a 0.00% yield, and a log younger than a year
  says how many days it covers.
- **`stonksmithdb dividends`**, and Indicated Income / Indicated Yield beside the
  received figures. The received tiles read `$0.00` on this workspace and always
  had: these brokers report contributions and transfers and never itemise a
  distribution, so the money is real and simply never appears as a movement. The
  indicated figures come from the same chart endpoint the prices do, asked with
  `&events=div` so one request answers both and the two can never disagree about
  which symbol they describe.
- That fetch is a **separate command run beside the scrapes**, not part of the
  brief. "No login, no browser, no network" is what makes the brief cheap enough
  to schedule every morning and what stops it failing the way a broker can; a
  figure it had to fetch would trade that away for a number. The cache lands at
  `~/.stonksmith/dividends.json`, owner-only — a per-share amount is public, the
  list of symbols asked about is everything the household holds.
- What is cached is **dividends per share, never an income**: a per-share amount
  stays true however many units are held, and a stored income would be wrong by
  the next trade. An indicated figure never overwrites the received one, because
  a forecast under a heading meaning *money that arrived* is a lie with nothing
  to catch it.
- The indicated yield divides by **the holdings it has figures for**, and states
  their count and value. Two thirds of a real workspace can sit in a 401k, a TSP
  fund and a 529, none of which has a public ticker; dividing nine known funds'
  income by all thirteen positions reports 0.29% where the answer is 1.33%.
- A symbol the feed has never heard of is recorded as unanswered rather than as
  a fund paying nothing — both come to `0.0`, and only one is a fact about money.
  A fund listed part-way through the year reports how many days of payments its
  figure stands on, measured from its oldest payment rather than the window edge.
- `BrokerDatabase.get_holdings_history()` and `read_holdings_history()`, which
  stand to the current-positions reads exactly as `get_account_history()` stands
  to `get_current_accounts()` — the same columns with the newest-snapshot
  restriction lifted. Behind `read_workspace(with_history=True)`, off by default:
  it is one row per position per snapshot and only the brief's trend wants it.
- **A `manual` broker**, for accounts you can see but cannot scrape — a plan
  portal with no API, no scrapeable page and no export. Configured in `[MANUAL]`
  as `Name | SYMBOL | units | units_as_of | cost_basis`, valued every run as the
  unit count times a published close from the same feed Ally's `--from-prices`
  uses. No credential, so it schedules like TSP.
- That broker stores a **unit count, never a balance**, on the rule the `[TSP]`
  comment already states: a balance is true for one day and would silently rot,
  while units move only when money does. A symbol with no published close is
  skipped and reported rather than written at zero, `as_of` is the price date so
  the account ages visibly in `stale`, and no transactions are recorded — the
  deposits that produced the count are not movements this module observed.
- **`[ACCOUNTS] aliases`** — call an account what you call it. Applied on the way
  out of the databases so the sheet and the brief agree, keyed on the same
  `Source / Account` label `exclude_accounts` matches and through the same
  normalizer, so a label copied between the two settings works. Nothing stored
  changes: `account_key` is untouched, which is what makes an alias safe to add
  and remove without orphaning history. A line matching no account is reported,
  since a broker renaming an account otherwise reverts it silently.
- `normalize_label()` moved from `modules.snaptrade_module` to `etc.portfolio`.
  Two settings now identify an account by the same label and a rule evaluated in
  two places is two chances for them to disagree about the same row.
- **`delete account <id>`** in the broker shell, with `delete_account()` behind
  it. Accounts were deliberately not deletable, on the argument that the next run
  would recreate them anyway — true until `exclude_accounts` arranges the
  silence, and the command prints that caveat every time rather than letting a
  deletion look permanent. It reports the name and snapshot count of what it
  removed, because it cascades and there is no undo.
- The holdings table names the account on every row. The same fund is routinely
  held in several accounts, and the symbol alone renders those as identical rows
  with different numbers.
- When positions total *more* than the account balances, the Portfolio Value
  tile says so instead of reporting a negative quantity of uninvested cash.
  SnapTrade states a balance and a set of positions and they disagree on every
  account of a real workspace; that is a fact about the source, not arithmetic
  to hide.
- **A second scrape every weekday.** `scripts/com.stonksmith.open.plist` and
  `scripts/stonksmith-open.sh` run at 06:35 local, five minutes after the 06:30
  Pacific open and five minutes after the brief — the brief reads every database
  and the opening run writes them, so firing them together would report on a
  workspace caught mid-write. Ten scrapes a week. The close run stays at 18:30
  rather than moving to the 13:00 bell because TSP publishes in the evening, and
  an afternoon run would record yesterday's share price as today's every day
  with nothing saying so.

### Fixed

- **One unreachable night erased every dividend figure.** `dividends` rebuilds
  the cache in a single pass and wrote `found=False` over any symbol it could not
  fetch, so a rate limit, an HTML block page or a dropped connection cost the
  brief its whole yield — and the result was indistinguishable from a portfolio
  holding nothing that pays, which is the reading `found` exists to prevent. A
  failed fetch now keeps the figure it already had. A good fetch still overwrites,
  including a fetch that legitimately returns zero.
- The refresh catches `requests.RequestException` and `QuotesUnavailable` rather
  than every exception. The carry above is what makes the difference matter: a
  bug in the parsing would have been caught, reported as "kept the earlier
  figure" and cached as a success, so the brief would render perfectly every
  morning off code that had stopped working. A broad catch in front of a
  fallback hides strictly more than one in front of a zero. Anything else now
  ends the run non-zero, which is what the nightly script's `status=1` rests on.
- Carried figures keep **their own fetch date** rather than being restamped, and
  the staleness warning reads the oldest of those rather than the file's write
  date — which moves every night whether or not anything was fetched, and would
  have reported month-old numbers as refreshed today. The run names every symbol
  it carried, because a run that carried all of them is a refresh that has
  stopped refreshing and looks identical in the counts alone.
- `dividend_events()` read the exchange offset unguarded while guarding the line
  below it, so a payload whose `meta` was present and null raised `AttributeError`
  out of a function documented to raise `QuotesUnavailable` — the exception its
  caller catches by name to decide whether a symbol has a quote page. Guarded as
  `daily_closes()` guards the same read.
- `read_cache()` guarded only the JSON parse, so a `paid` entry that was not a
  mapping raised out of the comprehension past it and failed the morning the
  docstring promises it cannot fail. The guard now covers the whole read.
- **Every SnapTrade balance was a day stale.** Balances came from
  `list_user_accounts`, which SnapTrade documents as serving daily-cached data.
  The lag was exact rather than approximate: today's reported balance was
  measurably the previous sync's position value, to the cent, on two independent
  accounts. The daily *change* was unaffected — both ends shifted together — but
  every level was, and the Net Worth series is built on levels.
- **An account's cash was invisible, including when it was negative.**
  `get_all_account_positions` returns securities only. One account here holds
  $3,500.00 of a fund against **-$800.00** of cash from an overdraft transfer,
  so SnapTrade's total said $2,700.00 and summing the positions said $3,500.00 —
  a third of the account, unexplained. The sync now reads
  `get_user_account_balance` per account and stores positions plus cash, which
  is live on both halves and reconciles exactly. It falls back to the reported
  total when positions could not be read, when the account reports none, or when
  cash could not be read — each a case where computing would be wrong rather
  than merely unavailable.
- The brief's Portfolio Value tile now names that difference for what it is:
  "plus $X in cash", or "less $X borrowed against them". It previously read
  "positions total $X more than the account balances", which was the honest
  wording while the value came from a cached total and is not any more.

### Changed

- A broker package needs only `broker.py`. `BrokerLoader` supplies
  `BrokerDatabase` and `BrokerNavigator` when a broker ships no `database.py` or
  `db_navigator.py`, which is what all five bundled brokers now do — nine files
  deleted, and a broker written by hand under `~/.stonksmith/brokers` is one file
  rather than three. A broker that ships one of those files and gets it wrong is
  still reported rather than defaulted.
- `stonksmithdb` no longer calls a broker "incomplete". A package with only
  `broker.py` is complete; what it may lack is a database in the current
  workspace, which is a different thing and the one an operator can act on.
- `max-complexity` lowered from 16 to 12, splitting `error_shape`, `to_amount`,
  `main` and Ally's `on_login`.

## [0.1.1] - 2026-08-12

No change to the tool. `v0.1.0` was tagged and published nothing: the release
workflow pinned a version of `gh-action-pypi-publish` whose bundled `twine`
predates core metadata 2.5, which is what this project's build produces, so the
upload was refused before it started. Nothing reached PyPI and no release was
created, and the tag is left in place rather than moved — a tag that shipped
nothing is a more useful record than one that quietly points somewhere else.

### Fixed

- The release workflow's pre-flight `twine check` ran with whatever `twine` was
  newest while the upload used the action's own older copy, so the two disagreed
  about the same wheel and the check passed on something the upload rejected. It
  is pinned to the version the action bundles, and a test refuses to let it float
  again.

## [0.1.0] - 2026-08-12

First tagged release. The project existed for 127 merged pull requests before
this point without a version anyone could refer to, so this entry describes the
state rather than the journey — the individual changes are in the commit log,
which is written to be read.

### Added

- Five brokers, in three shapes. `schwab529plan` posts a form and parses the
  response; `fidelity` and `ally` drive a real browser, attaching over CDP to one
  the operator signed into; `snaptrade` and `tsp` are API-backed. A directory
  containing `broker.py` *is* a broker — that is how they are discovered, from
  the package and from `~/.stonksmith/brokers`.
- Per-broker SQLite databases holding accounts, snapshots, holdings and
  transactions, and a Google Sheets dashboard built from them.
- `stonksmith` and `stonksmithdb` console scripts.
- Scheduling as a macOS LaunchAgent, because `cron` cannot reach the login
  keychain.

### Security

- Secrets live in the OS keyring, never in SQLite. Databases predating that split
  are migrated on first open. See [SECURITY.md](SECURITY.md) for what that
  migration does *not* do.
- Everything StonkSmith writes is owner-only — databases, config, run logs, page
  captures, the saved browser session, the Playwright trace, the Chromium profile
  and gspread's stored Google credentials. Best-effort: a filesystem without
  POSIX modes is not a supported reason to fail a run.
- Network calls logged for diagnostics have their query strings dropped and their
  id-shaped path segments masked.

### Notes

- Requires Python 3.14.
- The package installs one top-level name, `stonksmith`. It previously installed
  six — `main`, `etc`, `helpers`, `modules`, `loaders`, `brokers` — straight into
  `site-packages`. A broker or module written against those still loads, with a
  `DeprecationWarning`; that shim is removed in 1.0.

[Unreleased]: https://github.com/Gerrrt/StonkSmith/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.1
[0.1.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.0

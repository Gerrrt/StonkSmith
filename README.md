<!-- Back to top anchor -->

<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<div align="center"><nobr>

[![CI][ci-shield]][ci-url]<!--
-->[![PyPI][pypi-shield]][pypi-url]<!--
-->[![Python][python-badge-shield]][python-url]<!--
-->[![Last Commit][lastcommit-shield]][lastcommit-url]<!--
-->[![Stargazers][stars-shield]][stars-url]<!--
-->[![Issues][issues-shield]][issues-url]<!--
-->[![MIT License][license-shield]][license-url]

</nobr></div>

<!-- PROJECT HEADER -->
<br />
<div align="center">
  <img src="src/stonksmith/etc/logo.svg" alt="StonkSmith" width="88" height="88">

  <h1 align="center">StonkSmith</h1>

  <p align="center">
    One sheet to rule them all. <em>“how much money do I actually have?”</em>
    <br />
    <a href="#usage"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/Gerrrt/StonkSmith/issues/new">Report Bug</a>
    &middot;
    <a href="https://github.com/Gerrrt/StonkSmith/issues/new">Request Feature</a>
  </p>
</div>

```console
$ uv run stonksmith --help
usage: stonksmith [-h] [--verbose] [--debug] [--quiet] [--no-sheet]
                  [--version]
                  {ally,manual,schwab529plan,snaptrade,tsp} ...

==================================================
__ _               _     __           _ _   _
/ _\ |_ ___  _ __ | | __/ _\_ __ ___ (_) |_| |__
\ \| __/ _ \| '_ \| |/ /\ \| '_ ` _ \| | __| '__
_\ \ || (_) | | | |   < _\ \ | | | | | | |_| | | |
\__/\__\___/|_| |_|_|\_\___/_| |_| |_|_|\__|_| |_|

==================================================
        Aggregate everything in one dashboard
        Written by: @Gerrrt

Version : 0.5.0
Codename: Ford Prefect

Brokers:
  Available Brokers

  {ally,manual,schwab529plan,snaptrade,tsp}
    ally                Brokerage accounts at https://live.invest.ally.com
    manual              Accounts you can see but cannot scrape, valued from published prices
    schwab529plan       College Savings Account at https://www.schwab529plan.com
    snaptrade           Every brokerage connected through https://snaptrade.com
    tsp                 Thrift Savings Plan, valued from published share prices
```

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#project-structure">Project structure</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#brokers">Brokers</a></li>
        <li><a href="#output">Output</a></li>
        <li><a href="#exit-codes">Exit codes</a></li>
        <li><a href="#where-the-data-goes">Where the data goes</a></li>
        <li><a href="#the-sheet">The sheet</a></li>
        <li><a href="#scheduling">Scheduling</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#security">Security</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->

## About The Project

**StonkSmith forges your financial data into a single source of truth.** It
scrapes, aggregates and syncs your investment accounts into one Google Sheets
dashboard — holdings, balances, transactions, net worth over time and an asset
allocation breakdown, all rendered from databases it owns rather than from
whichever app happened to be open.

_Absolutely no day-trading._

No more bouncing between a squad of applications each meant for one account,
because no current app _just works_ for all the accounts you own. Think of it as
a personal financial command center: it scales with your life as you gain
wealth, takes new platforms without ceremony, and answers the one question those
five apps between them will not.

**ONE SHEET TO RULE THEM ALL!**

### Project structure

```text
StonkSmith/
|--- src/
|    |--- stonksmith/        # the one name this project installs
|         |--- main.py       # CLI entry point
|         |--- etc/          # config, logging, connection, shells, paths,
|         |                  #   records, database, the canonical row shape
|         |                  #   and the one thing that writes it to a sheet
|         |--- brokers/      # one package per broker (broker.py + helpers)
|         |--- modules/      # per-broker scrape/sync modules
|         |--- loaders/      # dynamic broker and module loading
|         |--- helpers/      # db, sheets, logging helpers
|--- docs/                # the reference chapters this file summarises,
|                         #   live verification, what a schedule can carry,
|                         #   and what was decided against
|--- scripts/             # one-off setup and probe scripts
|--- tests/
|--- pyproject.toml
```

Everything lives under `stonksmith/` so that the wheel installs exactly one
importable name. It used to install six — `main`, `etc`, `helpers`, `modules`,
`loaders`, `brokers` — straight into `site-packages`, where any of them could
collide with an unrelated package in the same environment.

Each broker is one package. `brokers/<name>/broker.py` holds the login class and
publishes it as `Broker`, optionally alongside `broker_args.py` and any
`parser.py`. A directory containing `broker.py` *is* a broker — that is how
`BrokerLoader` discovers them, scanning `src/stonksmith/brokers/` first and then
`~/.stonksmith/brokers/`.

**`broker.py` is the only file a broker needs.** Without a `database.py` it gets
`BrokerDatabase`, and without a `db_navigator.py` it gets `BrokerNavigator` —
which is what every bundled broker now takes, SnapTrade's navigator aside. A
broker that *does* ship one and gets it wrong is reported rather than quietly
given the default: the file exists because somebody meant something by it.

A broker that *raises* while loading is
reported by name and skipped — it registers no subparser and is simply
unavailable for that run, so a half-finished broker under
`~/.stonksmith/brokers/` never takes the rest of the tool down with it.

Your own brokers and modules import from `stonksmith.` — see
[what to import](docs/modules.md#what-to-import). The pre-namespace names
(`etc`, `helpers`, `modules`, `loaders`, `brokers`) were accepted under
deprecation until 1.0 and are not any more; a file still on them is reported by
name and skipped for that run.

Brokers come in three shapes. A **scraper** posts a form and reads the response,
and subclasses `Connection`: Schwab 529. A **browser-backed** broker has a login
guarded by bot detection, a session worth keeping between runs, and a page that
only exists after JavaScript has run; it subclasses `BrowserConnection`, which
owns the whole Playwright lifecycle: Ally. An **API-backed** broker
has no login at all — its key lives in config and the OS keyring — and
subclasses `ApiConnection`: SnapTrade, and TSP, which holds no key either
because the data it reads is published.

What a module is handed and what it must return is
[`docs/modules.md`](docs/modules.md); `src/stonksmith/modules/example.py` is the annotated
template.

> [!NOTE]
> **Not every claim here rests on a live run.** Green tests say the code does
> what it was written to do, which is not the same as saying the site still
> looks the way it did when the parser was written. Every broker has been run
> against the real thing, and the sheet has been read
> back off a real spreadsheet; four claims are still open, and **none of them is
> anybody's to-do** — each waits on the world rather than on effort. Two wait on
> data: whether the `Transactions` tab holds every movement or only the newest
> five hundred, and whether a 529 with more than one beneficiary attributes its
> movements to the right one. Two wait on a condition occurring at all: a
> SnapTrade connection lapsing, and an account's holdings going stale. The most
> recent runnable row was the Google grant, narrowed to Sheets access alone —
> a claim about what Google accepts rather than about what this code does, so
> nothing but a consent screen could answer it. It was read on 2026-08-20, the
> day the row appeared: the screen named Sheets and never mentioned Drive, and
> the token written back records one scope where the token it replaced recorded
> two. The runnable row before that — whether SnapTrade's transaction read goes
> past its first page — was run on 2026-08-18 and settled both ways round: at one
> row a page the loop made one request per movement, and past twenty pages it
> stopped and said so.
>
> **That sentence became true by subtraction as much as by running anything.**
> The `fidelity` broker was the standing exception — never run against the real
> site, its five claims withdrawn rather than settled — and it was removed at
> 1.0 rather than verified. Fidelity accounts reach StonkSmith through SnapTrade
> and *are* settled, but that is an API answering rather than a browser getting
> past bot detection, and it always was a different claim.
> [`docs/live-verification.md`](docs/live-verification.md) is the record,
> claim by claim, and this note summarises it rather than being maintained
> beside it.

### Built With

[![Python][python-shield]][python-url]
[![uv][uv-shield]][uv-url]
[![Playwright][playwright-shield]][playwright-url]
[![SQLAlchemy][sqlalchemy-shield]][sqlalchemy-url]
[![Google Sheets][sheets-shield]][sheets-url]
[![SnapTrade][snaptrade-shield]][snaptrade-url]
[![Rich][rich-shield]][rich-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->

## Getting Started

### Prerequisites

Python 3.14 and [uv][uv-url]. Ally drives a real browser, so it alone needs the
Playwright runtime; the other four brokers need nothing beyond the install
below.

### Installation

From PyPI, which gets you the two console scripts and nothing else:

```bash
uv tool install stonksmith
```

Or from a clone, which is what you want to change anything:

```bash
git clone https://github.com/Gerrrt/StonkSmith.git
cd StonkSmith
uv sync
```

Both are supported and both stay current — see
[Supported versions](SECURITY.md#supported-versions). Every command below is
written for the clone, so drop the `uv run` if you installed the tool.

Then, if you intend to use Ally:

```bash
uv run playwright install firefox
```

Run that again after any `uv sync` that moves Playwright. Each release pins a
new browser revision, so an already-installed Firefox stops satisfying it and
the next run fails with `Could not start browser`, naming an executable that is
not there.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE -->

## Usage

List the modules available for a broker:

```bash
uv run stonksmith schwab529plan -L
```

Run a module against an account:

```bash
uv run stonksmith schwab529plan -M schwab529plan -u <username> -p <password>
```

Or use a credential stored in the database instead of passing it on the
command line:

```bash
uv run stonksmith schwab529plan -M schwab529plan -id 1
```

### Brokers

Five brokers ship, and they do not work alike — one needs you to sign in by
hand every time, one needs no credential at all. Four of them have a chapter in
[`docs/brokers.md`](docs/brokers.md) saying what they need and what a run does,
and this table is the index into it. The fifth is `manual`, which has no login
to describe: it values accounts you can see but cannot scrape, from a unit count
you state in the config and a published price.

| Broker | Shape | What it needs from you |
| --- | --- | --- |
| [Ally Invest](docs/brokers.md#ally-invest) | Browser | A manual sign-in **every** scrape — Ally honours no restored session. `--from-prices` revalues between scrapes with no browser at all |
| [SnapTrade](docs/brokers.md#snaptrade) | API | A free Personal API key, and one browser step per brokerage every few weeks. Covers Schwab, Fidelity, Vanguard and the rest through one key |
| [Schwab 529](docs/brokers.md#schwab-529) | Scraper | A stored credential. A form post and two page reads — no browser, nothing to expire |
| [TSP](docs/brokers.md#tsp) | API | Nothing daily. Share prices are published; units come from a quarterly statement or a config line |

**Adding a brokerage SnapTrade covers is an operator action, not a code change**
— no new broker, module, database or tab. Vanguard is the standing example.

### Output

A run reports what it did. That is the default and it used to not be: every
progress line — including the yellow `[!]` warnings — logs at `INFO`, and the
default level was `ERROR`, so a sync could read a statement, write the snapshot
to the database and update the Google Sheet while printing nothing but a
progress bar. Success and doing nothing at all looked identical.

| Flag | Shows |
| --- | --- |
| *(none)* | What the run did, and anything that went wrong. |
| `--quiet` | Failures only. This is what an unattended run wants. |
| `--verbose` | Same as the default, but wins over `--quiet` — useful for seeing inside a wrapper script that hardcodes it. |
| `--debug` | Everything, including internals. |

All four work on either side of the broker name.

### Exit codes

The exit status reflects what the run actually did, so a cron entry, systemd
timer or CI step can tell whether the sync worked.

| Code | Meaning |
| --- | --- |
| `0` | The run did its work. A Google Sheets failure *after* the balances reached the database is still a success — the data is saved, and the log says the dashboard was not updated. |
| `1` | The run did not complete: unknown broker or module, could not connect or log in, a module reported it did nothing, only some of the requested modules loaded, or nothing reached the database. |
| `130` | Interrupted (128 + SIGINT). Distinct from `1` so a scheduler can page on a real failure and shrug at a human pressing Ctrl-C. |

`stonksmithdb <command>` reports the same way: `0` when the command did its work,
`1` when it did not. For `stale` that means `1` when any account has gone stale
or a database would not open — a status a crontab can act on, for the one failure
none of the codes above can catch, because nothing broke.

A partial module load still runs the modules that did load — partial data beats
none — but reports `1` rather than claiming success.

### Where the data goes

Every broker writes to its own SQLite file at
`~/.stonksmith/workspaces/<workspace>/<broker>.db`, holding four tables:
`accounts`, `account_snapshots`, `holdings` and `transactions`. Money is stored
as a number with the source's own text kept beside it, so a site that changes
its formatting costs you a parse rather than the record.

Browse and manage it from the shell:

```bash
uv run stonksmithdb
```

The tables, the columns, the shell's commands and what a migration does on open
are [`docs/database.md`](docs/database.md).

Ask whether anything has quietly stopped updating — no login, no network:

```bash
uv run stonksmithdb stale
```

It exits `1` when any account's as-of date is missing, unreadable or more than a
week old. That is the one question a schedule cannot otherwise ask: every other
step reports when it *breaks*, and none reports when it stops happening.

### The sheet

**StonkSmith owns five tabs and refuses to touch anything else.** `Accounts`,
`Holdings`, `Transactions`, `Net Worth` and `Dashboard` are created on the first
sync and rewritten in full every run — so anything of your own goes on a tab of
your own, and pulls across with a formula.

That is a refusal rather than a convention. Each tab's first cell carries a
banner; before clearing, StonkSmith reads it back. A tab carrying the banner is
its own, an empty tab is adopted, and a tab with anything else on it is refused
by name with nothing written. The run still exits `0` — the scrape reached the
database before the sheet was touched.

Rebuild the tabs from the databases at any time, with no login anywhere:

```bash
uv run stonksmithdb sheet
```

What each tab promises, why the dashboard has to be constructed rather than
read, and what `verify` checks that a successful sync cannot show are
[`docs/sheet.md`](docs/sheet.md).

### The morning brief

**One page that says what changed while you weren't looking, and turns up on its
own.** The sheet shows what is true now and `stale` reports what has stopped
moving; neither answers the question you actually open a dashboard with, and
neither arrives without being asked for.

```bash
uv run stonksmithdb brief
```

It reads the databases — no login, no browser, no network — renders one
self-contained HTML file to `~/.stonksmith/reports/`, and opens it. A LaunchAgent
at 06:30 on weekdays is what makes it a reminder rather than a file.

It carries a net-worth headline with the overnight change, a six-tile portfolio
summary, every holding with its cost, gain and trend, movements recorded since
you last looked, asset-class drift, and anything that has gone stale.

Three things about it are worth knowing before you read one.

**The headline is built on the Net Worth series, so a broker that did not run is
not a fall** — and the page says how much of the number was actually read this
morning rather than carried forward from the last time that account was seen. A
night when only TSP ran produces a real movement for one account and a carried
value for the rest, and the brief will tell you so directly under the total.

**"Since when" is the last brief you were shown, not the last scrape.** Monday's
brief covers the weekend, and a morning you skip is still covered by the next
one — because a brief with nothing new to report deliberately does not advance
its own baseline. Use `brief peek` to look a second time in one day without
consuming that comparison.

**A figure nobody reported stays a dash.** Cost basis is the fault line: SnapTrade
states one and a 401k, TSP and a scraped 529 do not, so purchase price, gain,
growth and the win/loss flag are absent on those rows rather than zero. Where a
total *is* summed over the positions that have a cost, the tile says which — *"across
9 of 12 positions; 3 report no cost basis"*.

Accounts appear under the names you give them, not the ones brokers print, via
`[ACCOUNTS] aliases` — a display name applied on the way out of the databases, so
the sheet and the brief agree and nothing stored is renamed.

Both files it writes are owner-only; old reports are pruned to `[BRIEF] keep_days`.
The whole design, the rule that keeps a skipped morning from erasing a day's
movement, and how to install the agent are [`docs/brief.md`](docs/brief.md).

### Scheduling

**The five brokers do not schedule alike, and one of them does not schedule
at all.** That is the part a crontab cannot tell you, and getting it wrong is
expensive in a specific way: a cron job that errors every night gets muted, and
after that the portfolio has stopped updating with nothing to say so.

| Broker | On a schedule |
| --- | --- |
| `tsp` | Yes. No credential in the daily path |
| `snaptrade` | Yes, until the connection expires — a browser step every few weeks |
| `schwab529plan` | Yes. A form post with a stored credential |
| `ally` | `--from-prices` only, which reprices a stale unit count rather than scraping |
| `manual` | Yes. Nothing to log in to — a configured unit count at a published price |

Weekdays after the close, one process per broker — `broker` is a positional
subcommand, so there is no `--all` — staggered, because two runs inside the same
UTC second collapse into one snapshot:

```cron
PATH=/usr/local/bin:/usr/bin:/bin

30 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith tsp -M tsp --quiet
35 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith snaptrade -M snaptrade --quiet
40 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith schwab529plan -M schwab529plan -id 1 --quiet
45 18 * * 1-5  cd ~/StonkSmith && uv run stonksmith ally -M ally --from-prices --quiet
50 18 * * 1-5  cd ~/StonkSmith && uv run stonksmithdb sheet
```

> [!WARNING]
> **The `ally` line is not a scrape.** Ally
> honours no restored session, so `--from-prices` values the account from
> today's published close and *the units the last signed-in run recorded* —
> exact arithmetic on a number that goes quietly wrong the moment a deposit
> lands. It says so on every account it values, and a schedule that mails only
> on failure will never show anybody that line. Re-run `--manual-login` after a
> deposit; the schedule cannot, and will not ask.

The sheet goes last, and it reports: `stonksmithdb sheet` exits `0` when the tabs
were rewritten and `1` when the sheet was unreachable, a tab refused, or a broker
database could not be read — a total short by a whole broker being the failure
that must not be quiet.

That schedule is committed as
[`scripts/stonksmith.cron`](scripts/stonksmith.cron), commented and ready to
paste into `crontab -e`. Every line in it is a no-op or a nightly failure until
its broker is set up — Ally in particular refuses and exits `1` until a
`--manual-login` run has recorded some units — so read *Before the first night*
before installing it.

[`docs/scheduling.md`](docs/scheduling.md) is the record: what each broker can
do unattended, what `--from-prices` is and is not, what has to be true before
the first night, and which of these claims a live run has actually settled.
This section summarises it rather than being maintained beside it.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->

## Roadmap

- [x] Multi-broker support (Fidelity, Schwab and anything else via SnapTrade,
      plus Ally Invest and Schwab 529 scrapers, and TSP from public data, for
      what SnapTrade does not cover)
- [x] Automatic data scraping (requests + Playwright)
- [x] Google Sheets sync
- [x] CLI commands for automation
- [x] Credentials stored in the OS keyring
- [x] Account history: numeric balances, holdings and transactions over time
- [x] Net worth tracking over time
- [x] Asset allocation breakdown — by account kind and by position, both free
      from what the databases already hold, plus by asset class from a mapping
      you keep in `~/.stonksmith/stonksmith.conf`. Sector and region are still
      absent: nothing states them and nothing here guesses
- [x] Scheduling (cron), for the brokers that run unattended — four of five,
      plus Ally in a reduced mode. The one that could never be scheduled was
      `fidelity`, behind bot detection and 2FA; it was removed at 1.0 and those
      accounts reach the workspace through SnapTrade instead
- [x] A morning brief that turns up on its own — one self-contained page
      rendered from the databases alone, no login, browser or network, opened by
      a LaunchAgent at 06:30 on weekdays. It compares against the last brief you
      were shown rather than the last scrape, so a morning you skip is covered by
      the next one, and a figure no source reported stays a dash rather than
      becoming a zero ([the design](docs/brief.md))
- [ ] More brokers. Vanguard needs no code at all; link it through SnapTrade
- [ ] Settle whether the `Transactions` tab windows at five hundred rows
      ([#141][issue-141]) — blocked on a broker with the movement volume
- [x] Settle whether the `Net Worth` series carries across brokers
      ([#149][issue-149]) — walked across nine dates on 2026-08-15
- [x] Settle whether SnapTrade's transaction read follows pages to exhaustion —
      run against the real API on 2026-08-18 at `--page-size 1`, where each
      movement cost its own request and the 20-page backstop stopped a 37-movement
      read at 20 and said so
- [ ] Settle whether an account leaves the series after thirty days of silence
      ([the record](docs/live-verification.md)) — the half [#149][issue-149]
      could not reach, blocked on a broker that actually stopped for a month

See the [open issues][issues-url] for a full list of proposed features (and
known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- SECURITY -->

## Security

This project handles sensitive financial data.

Current safeguards:

- **Secrets live in the OS keyring** (Keychain on macOS, Secret Service on
  Linux, Credential Locker on Windows). The SQLite database stores only a
  reference such as `schwab529plan:alice`, never the secret itself.
- `show creds` masks secrets. Set `audit_mode` and `reveal_chars_of_pwd` in
  `~/.stonksmith/stonksmith.conf` to reveal a short prefix when you need to
  tell two credentials apart.
- `export creds` writes the keyring reference, never the secret.
- Databases created before this change are migrated automatically on first
  open: each plaintext password moves into the keyring, the column is cleared,
  and the database is rebuilt with a `VACUUM` so the cleared bytes do not stay
  behind in a freed page. `vacuum` in `stonksmithdb` runs that rebuild on
  demand, for a workspace that migrated before it existed.

- **Everything StonkSmith writes is owner-only** — `0600` for files, `0700` for
  the directories under `~/.stonksmith`. That covers the databases, the config,
  the run log, page captures, the saved browser session and the Playwright
  trace.

> [!IMPORTANT]
> Passing `-p` on the command line still exposes the secret to your shell
> history and process list. Prefer `add creds` in `stonksmithdb` plus `-id`.
> Never commit credentials to source control.

[`SECURITY.md`](SECURITY.md) is the full account, including the risks this
project accepts rather than solves — the CDP debugging port, and what a rebuilt
database still leaves on the disk around it — and how to report a vulnerability.
The Google grant used to be on that list and is not any more: StonkSmith opens
the sheet by id and asks for Sheets access alone, where it used to ask for that
plus your whole Drive.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->

## Contributing

This is currently a personal project, but contributions may open up in the
future.

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the gates, the commit and branch
conventions, the test house rules, and the handful of settings whose reasons are
worth reading before changing them. The four gates are:

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest -q --cov --cov-fail-under=90
```

The version lives in `pyproject.toml` and nowhere else. `--version` and the
banner read it off the installed distribution, so bumping it is one edit
followed by `uv sync` — and `tests/test_version_single_source.py` fails if the
two ever part company. The codename beside it in `src/stonksmith/etc/cli.py` is the one
piece still written by hand, because nothing can derive one.

**The badge at the top is a third reading of that number, and it is deliberately
not the same one.** It reports what PyPI has published, so between a version bump
landing on `main` and the tag that publishes it, the badge reads one release
behind `pyproject.toml`. That is the badge answering the question a badge is for —
what you can install — rather than going stale. The Python badge beside it is read
off the published classifiers for the same reason: both are derived, so neither is
a copy anybody has to remember to update.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->

## Contact

Garrett Allen — [@Gerrrt](https://github.com/Gerrrt)

Project Link: [https://github.com/Gerrrt/StonkSmith](https://github.com/Gerrrt/StonkSmith)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ACKNOWLEDGMENTS -->

## Acknowledgments

The three sources StonkSmith reads that it did not have to build:

- [SnapTrade][snaptrade-url] — one key covering the brokerages that would
  otherwise each need a scraper
- [TSP][tsp-url] — publishes its share prices, which is what lets that broker
  run with no credential at all
- [DFAS][dfas-url] — publishes the military pay tables behind the TSP
  contribution accrual

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->

[ci-shield]: https://img.shields.io/github/actions/workflow/status/Gerrrt/StonkSmith/ci.yml?branch=main&style=plastic&logo=githubactions&logoColor=white&label=CI
[ci-url]: https://github.com/Gerrrt/StonkSmith/actions/workflows/ci.yml
[pypi-shield]: https://img.shields.io/pypi/v/stonksmith?style=plastic&logo=pypi&logoColor=white
[pypi-url]: https://pypi.org/project/stonksmith/
[python-badge-shield]: https://img.shields.io/pypi/pyversions/stonksmith?style=plastic&logo=python&logoColor=white
[lastcommit-shield]: https://img.shields.io/github/last-commit/Gerrrt/StonkSmith?style=plastic&logo=github
[lastcommit-url]: https://github.com/Gerrrt/StonkSmith/commits/main
[stars-shield]: https://img.shields.io/github/stars/Gerrrt/StonkSmith?style=plastic&logo=github
[stars-url]: https://github.com/Gerrrt/StonkSmith/stargazers
[issues-shield]: https://img.shields.io/github/issues/Gerrrt/StonkSmith?style=plastic&logo=github
[issues-url]: https://github.com/Gerrrt/StonkSmith/issues
[issue-141]: https://github.com/Gerrrt/StonkSmith/issues/141
[issue-149]: https://github.com/Gerrrt/StonkSmith/issues/149
[license-shield]: https://img.shields.io/github/license/Gerrrt/StonkSmith?style=plastic
[license-url]: https://github.com/Gerrrt/StonkSmith/blob/main/LICENSE
[python-shield]: https://img.shields.io/badge/Python-3776AB?style=plastic&logo=python&logoColor=white
[python-url]: https://www.python.org
[uv-shield]: https://img.shields.io/badge/uv-DE5FE9?style=plastic&logo=uv&logoColor=white
[uv-url]: https://docs.astral.sh/uv/
[playwright-shield]: https://img.shields.io/badge/Playwright-2EAD33?style=plastic&logo=playwright&logoColor=white
[playwright-url]: https://playwright.dev
[sqlalchemy-shield]: https://img.shields.io/badge/SQLAlchemy-D71F00?style=plastic&logo=sqlalchemy&logoColor=white
[sqlalchemy-url]: https://www.sqlalchemy.org
[sheets-shield]: https://img.shields.io/badge/Google_Sheets-34A853?style=plastic&logo=googlesheets&logoColor=white
[sheets-url]: https://developers.google.com/sheets/api
[snaptrade-shield]: https://img.shields.io/badge/SnapTrade-1A1A1A?style=plastic
[snaptrade-url]: https://snaptrade.com
[rich-shield]: https://img.shields.io/badge/Rich-000000?style=plastic
[rich-url]: https://rich.readthedocs.io
[tsp-url]: https://www.tsp.gov
[dfas-url]: https://www.dfas.mil

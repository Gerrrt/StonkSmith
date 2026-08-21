# Changelog

Notable changes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. This project follows [Semantic Versioning](https://semver.org/).

The version lives in `pyproject.toml` and nowhere else; a release is that number
plus a matching `v`-prefixed tag, and the release workflow refuses to publish if
the two disagree.

## [Unreleased]

### Removed

- **The `fidelity` broker is gone.** Deprecated in 0.3.0 and removed here, which
  is what 1.0 is for. Fidelity accounts reach the workspace through SnapTrade —
  an API key rather than a browser driven past Akamai Bot Manager and
  ThreatMetrix — and that route runs unattended, which the scraper never did.
  The broker was never once run against the real site: its five claims in
  `docs/live-verification.md` were withdrawn rather than settled, so removing it
  costs that record no coverage it had.
- **`stonksmith fidelity` is no longer a subcommand**, and `--help` no longer
  lists it. A `~/.stonksmith/brokers/fidelity/` of your own is still discovered
  and still runs; nothing about this removal touches brokers you wrote.
- **The pre-namespace import names no longer resolve.** Before 0.1.0 the package
  installed `etc`, `helpers`, `modules`, `loaders` and `brokers` straight into
  `site-packages`, and a shim aliased those names back for as long as one of your
  own files was executing. It has done that under a `DeprecationWarning` since
  0.1.0, and 1.0 is the release it named. **This is a breaking change for anyone
  whose broker or module still says `from etc.context import Context`.** The fix
  is the prefix — `from stonksmith.etc.context import Context` — and nothing else
  about the contract has moved.
- **A file still on the old names is reported by name and skipped, not fatal.**
  The rest of the run continues and every other broker and module still loads.
  The report exists because `ModuleNotFoundError: No module named 'etc'` on its
  own reads as a broken Python rather than as two imports that need a prefix.
  One consequence goes away with the shim: the alias was scoped to the load, so
  an `import etc.config` inside `on_login()` used to fail where the same import
  at the top of the file worked. Both now behave the same.
- **An existing `fidelity.db` is not removed, and is still read.**
  `read_workspace()` globs `*.db` and does not ask which brokers still ship, so
  the accounts in it keep appearing on the `Accounts` tab, keep counting toward
  the total, and keep showing in the `Refreshed: … from …` source list. What
  changes is that `initialize_db()` no longer recreates it — so unlike a bundled
  broker's database, once you move it out it stays out. See *Neither remedy
  touches what is already on disk* in `docs/brokers.md`. Anyone who linked
  Fidelity through SnapTrade and left the old database in place has been
  double-counting since they switched; this is the release that makes the fix
  permanent.

### Changed

- **The coverage floor is 89 → 90.** The measured baseline is 90.93%, and the
  floor is that rounded down. Worth saying which way the number was earned:
  removing code usually flatters coverage rather than improving it, and
  `brokers/fidelity/broker.py` went at 59% covered, which on its own would have
  raised the average while leaving the shared browser lifecycle it exercised at
  71%. That coverage was re-based onto Ally first, so the figure is the smaller
  tree actually being tested rather than the larger one being averaged.

### Fixed

- **Three broker packages documented a `saver.py` that does not exist.**
  `brokers/__init__.py`, `brokers/ally/`, `brokers/snaptrade/`, `brokers/tsp/`
  and `brokers/schwab529plan/` all named it, and three of them gave "the module
  imports `brokers.<name>.saver` on every run" as the *reason* their class is
  exported lazily. Nothing imports it and no such file is in the tree. The lazy
  export is still right — Playwright and the SnapTrade SDK are the real weight —
  but the justification named a mechanism that was not there. Found while
  removing the broker, which is the only reason these docstrings were read.
- **`docs/brokers.md` described `initialize_db()` wrongly**, and it was the
  sentence explaining why a retired broker's database reappears. It said the
  function "creates an empty database for every broker that ships a
  `database.py`". It walks every broker `BrokerLoader` discovers, and no bundled
  broker ships a `database.py` at all — `database_class()` falls back to
  `BrokerDatabase` for all of them. The stated filter did not exist.

- **The codename convention is a gate rather than a comment, because 0.5.0
  proved a comment does not run.** `CODENAME` moves with the minor version, and
  the only statement of that rule was the paragraph beside the value it governs.
  0.5.0 shipped reusing 0.4.0's "Ford Prefect" with every check green: the
  release gates compare the README's copy of the banner against `CODENAME`, so
  the two agree with each other whatever `CODENAME` says, and nothing compared it
  against the release before it.
- **A rule about movement needs two values, and there was only ever one.** The
  comment said outright that a codename "is not derivable from anything — there
  is nothing to read it out of", which was true of the current name and quietly
  also true of every earlier one: the only record of them was the literal inside
  each tag. `tests/test_version_single_source.py` now holds that history —
  recovered by reading `etc/cli.py` out of `v0.1.0` through `v0.5.0` rather than
  from memory — and checks the current minor against it.
- **Reuse is caught wherever it happens, not only between neighbours.** Going
  back to a name from two series ago is the same defect as not moving at all, and
  a check comparing adjacent pairs would pass it. A release that genuinely means
  to keep the previous name records the series in `SKIPPED_THE_MOVE` and says
  why, which is the deliberate act the gate exists to force.
- **The exception list cannot become a way to silence the gate.** An entry has to
  describe a reuse that actually happened; one naming a series that was later
  given a fresh name is a suppression with nothing under it, and fails. 0.5 is
  the only entry, recorded rather than repaired — 0.5.0 is on PyPI under that
  name, and a version number is spent whether or not what went under it was right.
- **The names alliterate, and that is now checked too.** Forrest Gump, Ferris
  Bueller, Fox Mulder and Ford Prefect are four for four, which is past
  coincidence — but four names are few enough that the pattern lived entirely in
  whoever picked the last one, and the person picking the next one is not
  guaranteed to be them. This is the half with no natural moment to be noticed: a
  codename that failed to move is visibly the old name, while one that moved and
  broke the pattern looks right from every angle except this.
- **Pinned as the letter rather than as "they all agree with each other."** The
  weaker rule is satisfied by the whole set migrating to G, which is not this
  convention — it is a different one that happens to be self-consistent, and it
  would pass on the very release that abandoned this one. Rewriting all four
  names to G fails six checks; under the weaker rule it fails none.
- Every assertion was checked against the break it claims to catch: a minor bump
  with no entry, an adjacent reuse, a non-adjacent reuse, a stale suppression, a
  name that moves but breaks the pattern, and — the one that matters — dropping
  `0.5` from the exception list, which fails. The suite passes because the reuse
  is recorded, not because the check is inert.

## [0.5.0] - 2026-08-20

### Security

- **StonkSmith no longer asks Google for access to your Drive.** `gspread.oauth()`
  defaults to full `spreadsheets` *plus* `drive`, and that default is what shipped —
  so the refresh token in `~/.config/gspread/authorized_user.json` reached every
  file in the operator's Drive rather than the one book being written. It was an
  open item in `SECURITY.md` rather than a settled one.
- **Drive was there for exactly one call.** `Client.open(title)` is a Drive
  `files.list` search, and it was the only Drive request in the codebase —
  `worksheet`, `add_worksheet`, `del_worksheet` and every read and write past it
  go to `sheets.googleapis.com`. So the book is now opened by id, from
  `[SHEETS] spreadsheet_id`, which removes the reason for the scope rather than
  trimming it. `open_by_key()` makes no request at all, so nothing replaces the
  one that went away.
- **Not `drive.file`, which `SECURITY.md` had named as the target.** That grants
  per-file access to files the app *itself created* or the user picked through the
  Google Picker, and a command-line tool cannot show a Picker — so a spreadsheet
  made by hand in a browser is unreachable under it, even by id. Closing the item
  that way would have meant creating a fresh book and migrating the history into
  it. Dropping Drive outright is both narrower and workable.
- **An unset id refuses rather than falling back to a lookup by name.** The
  fallback is the kind-looking option and it would have put the whole risk back:
  searching by title is the Drive call, so anyone who had not yet set the option —
  that is, everyone, on the day this ships — would have gone on consenting the wide
  grant. The refusal names the setting and happens *before* `gspread.oauth()` is
  called, so it cannot consent a token on its way to failing.
- **Upgrading needs `~/.config/gspread/authorized_user.json` deleted.** Google does
  not narrow a grant in place: a token consented under the old scopes keeps them
  until it is replaced, so an install that skips this keeps the wide grant and
  every other check still passes. `credentials.json` stays.
- `spreadsheets` is still account-wide over Sheets. This is narrower than it was
  and it is not narrow, and `SECURITY.md` now says so in those words rather than
  implying the item closed further than it did.

- **Clearing a password column does not remove the password, and now a `VACUUM`
  does.** `migrate_plaintext_secrets()` moves a legacy plaintext secret into the
  keyring and runs `UPDATE credentials SET password = NULL`. SQLite marks the old
  cell free inside its page and moves on, so the bytes stay in the file. It was
  written down as an accepted risk and never measured; it has been measured now.
  At ten credentials the cleared password was still greppable in the database in
  **fifteen runs out of fifteen**. At one credential it was greppable in none of
  them — a single row's page is rewritten in place — which is why the test that
  makes this claim uses ten rows and says so: a one-row fixture asserts something
  already true and passes with the fix reverted.
- **The rebuild runs only when a migration moved something.** It is called from
  `__init__`, so an unguarded `VACUUM` would rewrite every database on every
  open. A migration that finds legacy plaintext happens once in a database's
  life. `VACUUM` cannot run inside a transaction, which usually makes this
  awkward from SQLAlchemy — here the engine is already built with
  `isolation_level="AUTOCOMMIT"`, so a bare execute is outside one and the code
  says so, because the reader's instinct is that it cannot be.

### Added

- **`[SHEETS] spreadsheet_id` in `~/.stonksmith/stonksmith.conf`**, which is how
  the book is now identified. `SPREADSHEET_NAME` in `helpers/sheets.py` survives as
  the label errors print and is no longer how anything is found.
- **A live-verification row that opened and closed inside the same day.** A scope
  is invisible at runtime — a token consented too widely works *better* than a
  narrow one — and the suite authorizes against a `MagicMock`, which accepts
  anything. So no test could say Google accepts the narrowed grant; only a consent
  screen read by a person could, and one was read on 2026-08-20. Drive was absent
  from it, the sync completed against a book opened by id, and a deleted tab was
  recreated through `add_worksheet` — the operation with the best claim on Drive
  and the one a read-only check would miss.
- **The evidence is two files rather than a remembered screen.** The grant cached
  on 2026-08-18 recorded its own `scopes` as `spreadsheets` and `drive`; the one
  this run wrote records `spreadsheets` alone, with the string `drive` absent
  entirely and an mtime belonging to the run rather than to the older grant. That
  last part is what says the token was replaced instead of refreshed — a surviving
  wide token is the one failure mode that looks like success from every other
  angle, which is why the procedure now prescribes reading the written token and
  its timestamp alongside the consent URL. `docs/live-verification.md` goes to 35
  of 39 settled and 4 outstanding, and the bullet above about nothing on that list
  being anybody's to-do — false for the hours this row was open — is true again.
- `tests/test_the_google_grant_is_narrow.py` asserts on the `scopes=` argument
  itself rather than on `oauth` having been called — the obvious version of that
  test passes on the old code. Every test in the file was checked against a
  behaviour-reverted `sheets.py`: five fail on the scope and the id, three more on
  a refusal replaced with the title-lookup fallback.

- **`vacuum` in `stonksmithdb`, which is the half that reaches the databases
  that have the problem.** The automatic rebuild fires when a migration moves a
  secret, and a workspace migrated before that rebuild existed already moved
  its secrets — so the guard will never be true for it again, and it is exactly
  the workspace still carrying the cleared bytes. Nothing but an explicit run
  reaches it. Every database in the workspace rather than a named one: an
  operator asking this question does not know which file the plaintext is in,
  and making them guess is how a workspace ends up half done.
- A database that cannot be rebuilt is reported and the sweep carries on, but
  the run exits `1`. A scrub that skipped a file and exited `0` reads downstream
  as a workspace that has been scrubbed.
- **The report says "rebuilt" before it says a size.** A small database is
  already one page and reclaims nothing measurable while still having had every
  freed page rewritten, so `reclaimed 0 bytes` on its own reads as "nothing
  happened" — the opposite of what just happened. Verified end to end against a
  throwaway workspace: a 2,297,856-byte database came back 8,192 bytes with the
  plaintext gone, and a one-page database reported `rebuilt, same size` having
  also lost it.
- The command is named in the shell's own intro. This is the defect
  `tests/test_shell_advertises_what_it_runs.py` was written about — `delete
  account` shipped working and invisible — and that file derives its check from
  `DELETERS`, which covers the broker sub-shells and not the top level.

### Documentation

- **`SECURITY.md`'s *A migrated database is not a scrubbed one* is now *A
  vacuumed database is not a scrubbed disk*, and it shrank rather than closed.**
  The rebuild reaches the database file. It does not reach the rollback journal,
  which carries the pre-`UPDATE` page image — plaintext included — to
  `<broker>.db-journal` and deletes rather than overwrites it on commit
  (confirmed by reading one mid-transaction); the temporary full copy `VACUUM`
  itself writes at the temp directory's mode; or the filesystem blocks the old
  pages occupied. The honest statement is that this went from "the plaintext is
  in your database" to "the plaintext may be in free space on your disk".

- **The pagination claim is settled, and `--page-size` is what settled it.** 0.4.0
  shipped the flag saying in as many words that "the live run this was written for
  has **not** been made". It was made on 2026-08-18, against the real API, and both
  halves came back the way the code says they should. Over a ninety-day window at
  one row a page, one account's 3 movements cost 3 requests and another's 6 cost 6,
  each returning exactly the rows the server's own page size returns in a single
  request. Over a year, an account holding 37 movements came back with 20 after
  20 requests — the backstop — short by 17, naming itself and the cap on the way
  out. `docs/live-verification.md` goes to 34 of 38 settled and 4 outstanding.
- **The procedure that shipped with the flag could not have settled it, and the
  record now says so above the result.** It prescribed running paged, then
  full-sized, and watching the movement count stand still, on the reasoning that a
  paged read which dropped rows would have them put back by the full-sized read
  behind it. Transactions dedupe on `(account_id, natural_key)` with
  `on_conflict_do_nothing`, and the workspace already held every movement in the
  window — so neither run writes anything either way, and the count stands still
  identically whether the loop follows pages or stops dead at the first one. It was
  run as written anyway and is recorded with its numbers, labelled as proving
  nothing. This is the same wrong-reason pass [#141](https://github.com/Gerrrt/StonkSmith/issues/141)
  records, reached from the other side: there a windowed read was compared against
  a windowed read, here a deduplicated write against a deduplicated write.
- **Counting the requests is what the claim is actually about**, so the procedure
  now says to count them at the SDK boundary rather than to count rows in a
  database. At `page_size=1` a window of N movements must cost N requests, and
  nothing about what is already stored enters into it.
- **The section's commands were missing `-M snaptrade`** and stopped at `No module
  specified` having done nothing. A procedure whose first command does not run is
  one the next person debugs instead of following.
- **Nothing left on the outstanding list is anybody's to-do**, which is new and is
  now stated in both the record and the README note. The four that remain wait on
  the world: transaction volume accumulating, a connection lapsing, holdings going
  stale, and a 529 with a second beneficiary.

## [0.4.0] - 2026-08-17

### Added

- **`--page-size` on the `snaptrade` broker**, which exists to make the
  pagination above it reachable. `fetch_activities()` follows pages to
  exhaustion, and SnapTrade serves a thousand transactions to a request — so no
  account in this workspace has ever filled a second page, and that loop has
  only ever run against the fake client in `tests/test_snaptrade_broker.py`.
  That is precisely the evidence [`docs/live-verification.md`](docs/live-verification.md)
  opens by saying does not count, and its own SnapTrade row says so in bold: the
  transactions claim is settled *at one movement*, with the 20-page backstop and
  the follow-to-exhaustion loop unexercised. Asking the real API for small pages
  is what lets the real loop run — the same move `verify volume` makes for the
  sheet, one release earlier, for the same reason.
- The flag is omitted from the request rather than defaulted, so an ordinary run
  sends the request it sent before the argument existed and the server's own
  default keeps deciding.
- **A page size below 1 is refused by the parser.** SnapTrade's schema puts the
  minimum at 1, and zero is the value worth naming because it does not simply
  fail: it passes the "was one asked for" test, so `limit=0` reaches the wire,
  and the short-page check that ends a read carrying no total can never be true
  against it — so that read follows pages until the cap stops it. Refused at the
  parser rather than inside `fetch_activities()`, whose caller reports a failed
  fetch as the brokerage having failed and carries on.

### Fixed

- **A page size would have truncated a read that came back without a pagination
  block.** `as_page_rows()` tolerates two shapes because some SDK versions unwrap
  the envelope, and an unwrapped one carries no `total` — on which the loop
  broke. That is right at the default page size, where one response is the whole
  answer, and wrong the moment a size is asked for: a *full* page and no total is
  the shape of there being more, so breaking there would drop the rest silently,
  which is the exact failure the pagination exists to prevent. With a page size
  asked for, the loop now continues on a full page and stops on a short one.
  Verified against the live API on 2026-08-17 that the real endpoint does return
  the envelope, `{"data": [...], "pagination": {"offset", "limit", "total"}}`, so
  this is the defensive path rather than the ordinary one.
- **The backstop now says it stopped short.** `page_limit` exists because "an
  infinite loop against a paid API is worse than a short read that says so" —
  said by the docstring, and until now by nothing else. A capped read and a
  complete read are indistinguishable from the return value, so hitting the cap
  logs the account and the cap and tells the operator to narrow the window.

> The live run this was written for has **not** been made. The flag makes the
> claim settleable; it does not settle it, and no row in
> `docs/live-verification.md` reads `Yes` because of it.

### Documentation

- **The pagination claim has its own row, because it was hiding inside a settled
  one.** `SnapTrade — transactions reach the database` reads `Yes, at one
  movement`, and `tests/test_live_verification_tally.py` counts any verdict
  starting `Yes` as confirmed — so the bolded caveat about the
  follow-to-exhaustion loop was invisible to the count, and to the reader the
  count exists to save from counting. The table goes from 37 claims to 38 and
  from 4 outstanding to 5. The settled count is unchanged at 33, because nothing
  was settled.
- **The sentence saying the loop would stay unexercised "until an account trades
  enough to need a second page" was made false by `--page-size`, and is gone.**
  It stood in [`docs/live-verification.md`](docs/live-verification.md) and, in
  another form, in the SnapTrade paragraph of
  [`docs/scheduling.md`](docs/scheduling.md), which grouped the pagination with
  two gaps that really do wait on the world. This one waits on an operator, and
  that is the distinction the new row buys.
- **A procedure for the run**, in the *SnapTrade* section, which until now was
  the one broker section with no numbered steps at all: what to pass, why a page
  size below the movement count is the whole trick, why the paged run has to go
  first, what the 20-page cap prints when it fires, and what either outcome would
  mean. It also names the branch a live run *cannot* reach — the short-page arm
  needs a response carrying no `total`, and the live endpoint carries one.
- **`--page-size` is documented in the reference chapter**, beside
  `--history-days` and `--no-positions` in
  [`docs/brokers.md`](docs/brokers.md), where it shipped with no entry at all.
  The README's verification note now counts five open claims rather than four.

## [0.3.0] - 2026-08-17

### Deprecated

- **The `fidelity` broker, removed in 1.0.** Fidelity reaches the workspace
  through SnapTrade — one API key, no browser, no bot detection, and it runs
  unattended, which the scraper never has. Nothing here recommended the scraper
  already: `scripts/stonksmith.cron` ships with no `fidelity` line, the
  scheduling tables answer "No", and `docs/scheduling.md` has a section titled
  *Fidelity is not scheduled, it is replaced*. It still runs and its ten test
  files are still in the suite; every run now prints a notice naming the removal
  version and the replacement, and `stonksmith --help` leads its line with
  `(deprecated)`.
- The notice is emitted as a `DeprecationWarning` **and** logged at ERROR level,
  for the reason `loaders/_legacy_names.py` gives about the other deprecation
  this project carries: `DeprecationWarning` is invisible under Python's default
  filters outside `__main__`, so a run from cron would otherwise get no signal at
  all. The warning is raised inside `suppress(DeprecationWarning)` — under
  `-W error` an unsuppressed one is caught by the blanket `except Exception`
  around module execution and reported as the broker having failed to load,
  which would make the notice break the thing it describes.
- **Five claims withdrawn from [`docs/live-verification.md`](docs/live-verification.md),
  which is not the same as settling them.** The `fidelity` broker was never once
  run against the real site, and a broker on a removal path will never get the
  sitting, so its rows were removed rather than left reading `No` forever. The
  table goes from 42 claims to 37 and from 9 outstanding to 4; the settled count
  is unchanged at 33, because none of the five ever was. The paragraph above the
  table says all of this, including that the broker still ships — a reader who
  found a working subcommand with no rows would otherwise conclude the table was
  merely incomplete.

### Fixed

- The `stonksmith --help` transcript in the README had drifted from what the
  package prints: it was missing `--no-sheet` and the `manual` broker. Corrected
  in the same pass, since the deprecation edits that block anyway.
- **Two lines of that transcript are now held to their single sources.** It
  quotes the version and the codename, and nothing compared either against
  `pyproject.toml` or `CODENAME` — the comment beside `CODENAME` said outright
  that the copy "goes stale silently". `tests/test_version_single_source.py`
  now fails if they part company, which is the same file that already explains
  which copies of the version exist and which are deliberately left alone. It
  matches whole lines and refuses a second line carrying either label, because
  a substring check would pass on the stale duplicate it exists to catch. The
  rest of the transcript is still maintained by hand.

## [0.2.0] - 2026-08-16

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
  `main` and Ally's `on_login`. `CONTRIBUTING.md` went on saying 16 through that
  change — under *Things that are settled*, the heading whose purpose is to be
  trusted without re-derivation — so it now says 12, and
  `tests/test_the_complexity_ceiling_is_one_number.py` reads the ceiling off
  `pyproject.toml` and fails if either the bullet or the comment above the
  setting disagrees with it. The instruction to keep them in step was the only
  thing holding them together, and an instruction is not a mechanism.
- **The coverage floor raised from 87 to 89**, the measured baseline of 89.57%
  rounded down. `CONTRIBUTING.md` has always said to raise it when the real
  number moves; the baseline had climbed 1.9 points since the floor was set, so
  the ratchet had two and a half points of slack in it and coverage could have
  fallen that far without a red build. The floor is stated in four files — both
  workflows run it, and `CONTRIBUTING.md` and `README.md` quote the gates for a
  contributor to paste — so `tests/test_the_coverage_floor_is_one_number.py`
  now reads all four and fails if they disagree, and checks the baseline in
  `ci.yml`'s comment against the floor derived from it. The markdown copies are
  the ones worth a mechanism: they look executable, and nothing ran them.

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

[Unreleased]: https://github.com/Gerrrt/StonkSmith/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.5.0
[0.4.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.4.0
[0.3.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.3.0
[0.2.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.2.0
[0.1.1]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.1
[0.1.0]: https://github.com/Gerrrt/StonkSmith/releases/tag/v0.1.0

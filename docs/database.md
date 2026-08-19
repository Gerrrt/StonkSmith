# Where the data goes

The `stonksmithdb` shell, and the four tables every broker's database holds.

**This is a reference chapter, not a record.** It describes the storage layer as
it is today. [`live-verification.md`](live-verification.md) is the record of
which of these writes a live run has actually observed.

The sheet is a view of what is described here, and never a source for it —
[`sheet.md`](sheet.md).

---

## The shell

Manage stored credentials and scraped balances:

```bash
uv run stonksmithdb
```

Inside that shell: `broker schwab529plan`, then `add creds <username>`,
`show creds`, `show accounts`, `export creds <file>`, `delete creds <id>`,
`delete snapshot <id>`, `delete account <id>`, `back`, `exit`.
SnapTrade stores no credentials there; its keys live in the config file and the
keyring, so `add creds` points at the setup script instead — and its own shell
lists `delete snapshot` and `delete account` but not `delete creds`, for the
same reason.

At the top level, four commands read the workspace rather than a broker:
`sheet` rewrites the Google Sheet from these databases, `verify [tabs|guard]`
reads it back, `stale [days]` reports accounts nothing has refreshed lately
and exits `1` if any turn up, and `vacuum` rebuilds every database in the
workspace. All four also run as `stonksmithdb <command>` without entering the
shell, which is what a crontab calls — see
[*The freshness step*](scheduling.md#the-freshness-step-is-the-one-that-catches-silence)
for why `stale` exists.

### `vacuum`, and why it is not on the schedule

`vacuum` rewrites each `<broker>.db` so the pages freed by past deletes stop
carrying what was deleted. It is a maintenance command, not a nightly one: a
whole-file rewrite every night would cost real time for nothing most nights.

The reason it exists is narrower than "reclaim space". Clearing a column does
not remove what was in it — SQLite marks the old cell free inside its page and
moves on — so a database migrated off plaintext passwords could still have them
greppable in the file. `migrate_plaintext_secrets()` now rebuilds automatically
when it moves a secret, but it moves one *once*: a workspace migrated before
that existed will never trigger it again, and is exactly the workspace that
still has the bytes. This command is the only thing that reaches it.

Every database in the workspace, not a named one — an operator running this does
not know which file the plaintext is in. A database that cannot be rebuilt is
reported and the sweep carries on, but the run exits `1`, because a scrub that
skipped a file and exited `0` reads downstream as a workspace that has been
scrubbed. What a rebuild does *not* reach is in
[`SECURITY.md`](../SECURITY.md) and is worth reading before relying on it.

## What is stored

Each broker gets its own SQLite file at
`~/.stonksmith/workspaces/<workspace>/<broker>.db`, holding four tables:

| Table | One row per | Holds |
| --- | --- | --- |
| `accounts` | account, ever | broker, brokerage, display name, beneficiary, kind |
| `account_snapshots` | account per run | a **numeric** value, its currency, the source's own as-of date, and the text the source printed |
| `holdings` | position per snapshot | fund code or ticker, name, units, price, value, principal, earnings, cost basis, and the unit count's own as-of date where a source dates its quantity apart from its value |
| `transactions` | movement | processed and traded dates, type, symbol, description, units, price, value, currency, the source's own id where it has one, when StonkSmith first saw it, the key it is deduplicated on, and the value's original text |

Two things about that shape are deliberate:

**Money is a number, and the original text is kept beside it.** `daily +/-` is
not a field any broker reports -- it is the difference between two consecutive
snapshots, which needs arithmetic. Keeping `raw_value` as well means a source
that changes its formatting costs you a parse, not the record.

**Sources fill different columns.** A scraped 529 fund table gives a fund code,
principal and earnings; a SnapTrade position gives a ticker and a cost basis; a
pre-aggregated account gives a balance and no positions at all. Every column a
source might not have is nullable, and an account with zero holdings is a fact
about the account rather than a failed scrape.

Browse it from the shell:

```text
show accounts                  the accounts this broker knows
show snapshots [<account id>]  what each was worth, over time
show holdings [<snapshot id>]  the positions behind a snapshot
show transactions [<account>]  recorded movements
show deltas                    the change between consecutive snapshots
export <category> <file>       any of the above, as CSV — all of it
delete snapshot <snapshot id>  remove one wrong mark and its holdings
delete account <account id>    remove an account and everything under it
```

**`show` is a screenful; `export` is the whole table.** `show` prints the newest
hundred snapshots or five hundred movements and then says so, naming `export` —
printing fifty thousand rows into a terminal helps nobody, but a table that
stops without mentioning it is a different problem. `export` takes no limit at
all and reports how many rows it wrote:

```
schwab529plan > export transactions ~/tx.csv
[+] Exported 2043 transactions to ~/tx.csv
```

That count is not decoration. A CSV that stopped early looks exactly like a
complete one, and nothing reading it afterwards can tell — which is the same
failure the `Transactions` tab exists to avoid, in a file instead of a tab.

**It is fewer columns as well as fewer rows.** `show transactions` leaves out
three of them and says which three and where to get them. Everything else the
`Transactions` tab shows, `show` shows too, and `export` writes all fifteen:

```
schwab529plan > show transactions
[!] Description, Natural Key, Raw Value are too wide for a terminal and not
    shown; 'export transactions <file>' includes them.
```

All three are dropped for width, and nothing here truncates a cell: `Description`
is free text a source wrote and can be a whole sentence, `Natural Key` is a whole
row's text pipe-joined, and `Raw Value` is whatever the source printed.

**The last two are also the two the `Transactions` tab does not have**, and that
is deliberate in both places. `Natural Key` is the key a movement is
deduplicated on and `Raw Value` is the value's text before anything parsed it;
together they are how you tell a row that is genuinely new from one whose key
moved because a source changed its date format. That is a debugging question, so
it belongs in a CSV you pulled to answer it and not on a tab you read your
portfolio from. The key is stored as legible text rather than as a hash for
exactly this, and that choice only pays for itself if something can show it to
you.

`delete snapshot` is there because a wrong mark does not correct itself. The
next sync writes a row *beside* it, not over it — snapshots record what was
observed when — so a placeholder run verbatim off a command line, or a value
computed from mismatched inputs, stays a data point in every chart until it is
removed. It takes one id at a time, and it leaves the account alone: deleting
that would cascade away the real history and let the next run recreate the
account beside itself.

**`delete account` is the other question, and a broader answer.** A wrong mark
is a good account's bad row; this is for an account that should not be in the
database at all — the case that arises when two brokers reach the same money and
one of them is the wrong one to be counting it. Everything under it goes:
snapshots, the holdings behind them, and the account's transactions, through
`ON DELETE CASCADE`. There is no undo, so it reports the account by name and
says how many snapshots it took, which is the only check on having typed the id
from the right row of `show accounts`.

It is also only ever half of an operation. **The next sync recreates any account
its broker still returns**, so the source has to be made to stop reporting it
first — for SnapTrade that is `[SNAPTRADE] exclude_accounts`. Delete first and
the account is back by morning, which is why the shell prints that caveat on
every deletion rather than leaving it here. See
[*Neither remedy touches what is already on disk*](brokers.md#neither-remedy-touches-what-is-already-on-disk)
for the procedure and when to reach for it.

Google Sheets is a view of this, not the other way round. Each tab is cleared
and rewritten from what the database holds, so what you see there is what
`stonksmithdb` reports. That has a consequence worth stating outright — see
[The sheet is output](sheet.md#the-sheet-is-output).

It is a floor rather than a ceiling: every column a tab shows has to be reachable
from `stonksmithdb`, and `stonksmithdb` may carry columns no tab wants. The two
above are the whole of that today. The shell is where you go to ask why the
database holds what it holds; the sheet is where you go to read what it holds.

**Upgrading an existing database.** Databases written before account history
have a single `accounts` table of per-run rows with a text balance. Opening one
migrates it: the old table is renamed to `accounts_legacy_v1` and **kept**, and
every row is replayed as a snapshot with its balance parsed into a number.
Accounts keep the same identity they had, so existing history continues rather
than starting over. It runs once and reports how many rows it moved.

A second migration adds `holdings.units_as_of` to a database written before that
column existed, and moves TSP's unit dates into it from `holdings.raw_value`,
where they used to ride. Both halves happen in one transaction, so a database is
never left with the column and without the dates. The original text is kept
rather than cleared, on the same principle as the renamed table above, and a
value that does not read as a date — which is what `raw_value` holds for every
broker other than TSP — is left exactly where it is. It reports only when it
actually moved something.

Adding the column is not optional on the writing side: a snapshot write names
every column it has, so a database that missed the migration would fail its next
sync outright rather than quietly storing less.


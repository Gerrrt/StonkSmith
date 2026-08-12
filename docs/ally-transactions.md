# Ally transactions

A feature that was built leaves a trace of itself everywhere — a function that can carry a
docstring, a column that explains itself, a flag with a help string. A feature that was
*not* built leaves nothing at all, so the reasoning either lives somewhere on purpose or it
gets re-derived by the next person to notice the gap. #89 assumed Ally writes transactions;
it does not, and after investigation it should stay that way for now.

**This file is the record.** One place summarises it — the end of
[*What an Ally run writes down*](brokers.md#what-an-ally-run-writes-down) — and
that paragraph is derived from here rather than maintained
beside it. Unlike the summaries `docs/live-verification.md` governs, this one is not
continuous: it states a decision that either stands or is reopened, so it changes exactly
once, on the day one of the conditions below fires.

**And this file is about Ally, not about StonkSmith.** `docs/live-verification.md` records
which of StonkSmith's own claims a live run has settled — that a parser works, that a write
lands, that a session persists. What Ally's site does or does not offer is a different kind
of fact, and it belongs here. Keeping that line straight is what stops two files in `docs/`
from becoming one file written twice.

---

## What exists today

**Nothing on the sheet side is blocking.** Two producers construct a `Transaction`:
`transaction_from_row()` in `src/stonksmith/helpers/schwab529plan.py`, and `activity_transaction()` in
`src/stonksmith/modules/snaptrade_module.py`. Those are the only two in `src/`.

The `Transactions` tab branches on no broker at all. `src/stonksmith/etc/portfolio_sheet.py` writes
`portfolio.transactions` whole, and `src/stonksmith/etc/portfolio.py` builds those rows out of whatever
the workspace databases hold, filling `broker`, `source` and `account` from the account join.
An Ally producer would appear on the tab the day one was written, with no change to the sheet
code and no new column.

So the reason this was not built is not a plumbing reason. Everything downstream of a
`Transaction` is already broker-agnostic and already proven by the two producers that exist.
The reasons are all upstream, and there are four of them.

---

## Why it was not built

**There is no second source.** `scripts/snaptrade_coverage.py` asks the authoritative
`/brokerages` endpoint what SnapTrade actually covers, and the 2026-08-05 run recorded in its
docstring found **no Ally Invest at all**. That matters more than it looks: SnapTrade is
exactly what takes Fidelity from attended to unattended, as
[*When two brokers can reach the same account*](brokers.md#when-two-brokers-can-reach-the-same-account)
describes. For Ally that route does not exist, so there is no
aggregator to fall back to and no path to transactions that does not go through the scraper.

**No activity endpoint has ever been observed.** `src/stonksmith/modules/ally_module.py` navigates one
URL — `https://live.invest.ally.com/accounts/holdings-balances` — and reads the rendered DOM;
the only other address the integration drives is `secure.ally.com`, for the sign-in in
`src/stonksmith/brokers/ally/broker.py`. Five Ally endpoints have ever been recorded from a live run:
`api/session/checkSession`, the bank's `auth/login`, `auth/anonymous_invoke`, `auth/logout`
and `api/account/get`. All five are session, auth and account-roster plumbing. Nothing in
`src/`, in `docs/`, in the README or in the captured fixtures names an activity, history or
orders route — `tests/ally_holdings.html`'s only link attribute is `href="#"`, so there is
not even a navigation target to work backwards from. Building a parser is the cheap half of
this; the expensive half is finding out what to parse.

**It could never run unattended.** Settled across nine live runs, both browsers, both
persistence models: Ally honours no restored session. `docs/live-verification.md` has the
evidence and records the conclusion as a property of Ally's auth rather than a defect here —
*"nothing StonkSmith stores reconstitutes a session Ally will honour."* Any transactions
fetch rides the same cookie jar as the holdings scrape, so it inherits that whole. A human
signs in, every time, or nothing is fetched.

**And the main value is circular.** The one job Ally transactions would do that nothing else
does is tell you when the stored unit count went stale. `--from-prices` values the account
between scrapes by multiplying recorded units by today's close, and units only move when a
deposit lands — which is why every per-account line it prints ends the same way:

```text
[*] Individual (...0847): priced at 2026-08-06; units as recorded 2026-08-07 20:40:18. Re-run with --manual-login after a deposit.
```

But the only way to fetch the transactions that would replace that guess with a fact is to
perform the manual login — which would have refreshed the units anyway, and rewritten the
stamp on the way past. The thing that would tell you to sign in costs a sign-in.

What survives all four is record-keeping: Ally movements sitting on the tab beside the 529
and SnapTrade ones, so the history is whole rather than partial. That is a real thing to
want. It is also a modest one, and it would be paid for with discovery against a live
signed-in account.

---

## What was done instead

#99 made the response recorder produce that discovery evidence out of ordinary runs, at no
extra cost and with nothing new to remember:

- **armed before the CDP branch**, in `src/stonksmith/brokers/ally/broker.py`, so `--browser cdp`
  records at all — it previously recorded nothing, and it is the path
  [`brokers.md`](brokers.md) recommends
- **written on every exit**, from `BrowserConnection.teardown()` to
  `~/.stonksmith/logs/ally-data-calls-<stamp>.log`, rather than only after a failure
- **carrying each endpoint's parameter names**, via `query_shape()` in
  `src/stonksmith/etc/browser_connection.py`, with values, bodies and headers still never read

That last point is what makes the log answer the question rather than merely restate it. A
route called `activity` says nothing on its own; the same route taking `startDate` and
`endDate` is a windowed history feed, and a parameter name is a fact about the endpoint
while its value is a fact about you.

So reopening this decision needs no dedicated investigation. It needs a run somebody was
doing anyway, and then five minutes reading a file.

---

## What would reopen it

Revisit if any one of these becomes true. Until one does, this is closed on purpose.

### 1. A log shows an activity endpoint

**The check.** After any run that opened a browser:

```bash
grep -Ei 'activity|history|orders|transaction' ~/.stonksmith/logs/ally-data-calls-*.log
```

A hit settles the whole discovery question at once — that a feed exists, whether it is
per-account, and whether it takes a date window are all readable off the one line.

**Match against your log, not against the documented one.** The sample line in
[*What an Ally run writes down*](brokers.md#what-an-ally-run-writes-down) is an illustration
of the format, written out so a real one can be recognised.
It is not a capture, and mistaking it for one would fire this condition on evidence that
does not exist.

**What would remain.** A parser over the response shape, a flag or an unconditional fetch in
`ally_module.py`, and `Transaction` rows — plus the keying question in *What it would
inherit* below, which is not optional.

### 2. SnapTrade adds Ally Invest

**The check.**

```bash
uv run --with snaptrade-python-sdk python scripts/snaptrade_coverage.py
```

It reads credentials from `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY` in the
environment, lists integrations only, and touches no account — its own docstring says how to
export them without putting the key in `argv`. Read the `--- what issue #21 asked ---`
block. Today the `ally` row prints `NOT SUPPORTED -- needs a scraper`.

**What would remain.** Nothing Ally-specific. `snaptrade_module.py` already builds
transactions, and SnapTrade supplies the source's own ids, so this is a link in the
Connection Portal rather than code — and it is strictly better than scraping on both of the
counts that matter here: it runs unattended, and it is keyed on a real id rather than on
content. It would also make the Ally scraper the redundant one for those accounts; see *When
two brokers can reach the same account* for how to pick an owner.

### 3. Ally starts honouring a restored session

**The check.** `docs/live-verification.md`, the *Ally* section, step 2 — re-run the procedure
that file records as settled, and attach the data-calls log rather than a count.

**What would remain.** More than transactions. That row is the unattended answer for the
whole broker, so a change there is written up in
[`live-verification.md`](live-verification.md) first and changes
[the Ally chapter](brokers.md#ally-invest) with it. The transactions question sits downstream of it
and still needs condition 1 as well: a session that persists is no use against an endpoint
nobody has found.

Whichever one fires, change this file and the paragraph that summarises it in the same
pass, and say which run settled it. A condition that has come true and been left reading as
open sends the next reader off to re-derive an answer that already exists, which is the exact
state this file was written to end.

---

## What it would inherit

**A scraped Ally producer would supply no `external_id`,** exactly as the 529 scraper
supplies none, so its rows would be keyed on their own content by `natural_keys()` in
`src/stonksmith/etc/broker_db.py`. That function's own docstring states where content keying stops: a
same-content group has to arrive whole in one window, because two $50 contributions on one
day, fetched one per window, are byte-identical to the same contribution fetched twice — and
with nothing but the row's own text the two cannot be told apart. The scheme picks a side and
never duplicates.

Both current producers fetch a date window whole, so a same-day group cannot straddle one.
**A paginated activity feed is precisely the case that cannot promise that** — which is why
`pageSize`, in the illustrated line [`brokers.md`](brokers.md) shows, is not idle detail. The endpoint that
would reopen this decision may be the same endpoint that makes a derived key insufficient.

So "only a parser and a flag remain" is optimistic by one decision, and the decision is
whether a producer that cannot name its own rows should be writing them.

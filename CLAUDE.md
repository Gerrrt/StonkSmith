# Working on StonkSmith

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the contract — gates, commit shape, test
conventions, and the things that are settled. This file is for what has actually
misled someone while working here.

## The list-valued config options are multi-line, and `grep` reads them wrong

Eight options in `~/.stonksmith/stonksmith.conf` take **one entry per line**, as
indented continuation lines beneath a bare key:

```ini
[SNAPTRADE]
exclude_accounts =
    Schwab / Beneficiary A 529 Plan
    Fidelity / EXAMPLE ESPP PLAN
```

`configparser` joins those continuations into one value, and the getters split it
with `raw.splitlines()`. So the key line carries nothing, and the entries live on
lines that do not mention the key at all.

**That makes `grep exclude_accounts` actively misleading**, not merely incomplete
— it prints `exclude_accounts =` and stops, which reads as a setting that exists
and is empty. The conclusion "the exclusion is not in place" follows naturally
and is wrong. This has already happened once, against a live workspace, while
deciding whether an account was safe to delete.

Read them through the parser instead, which is the same thing the code does:

```bash
python3 -c "
import configparser, pathlib
c = configparser.ConfigParser()
c.read(pathlib.Path.home() / '.stonksmith/stonksmith.conf')
print(repr(c.get('SNAPTRADE', 'exclude_accounts', fallback='')))"
```

Better still, call the getter in `stonksmith.etc.config` — each returns the
parsed list, already stripped of blank lines:

| Option | Getter |
| --- | --- |
| `[SNAPTRADE] exclude_accounts` | `get_snaptrade_excluded_accounts()` |
| `[ACCOUNTS] aliases` | `get_account_aliases()` |
| `[ACCOUNTS] cost_basis` | `get_account_costs()` |
| `[ACCOUNTS] colors` | `get_account_colors()` |
| `[ALLOCATION] asset_classes` | `get_asset_classes()` |
| `[ALLOCATION] targets` | `get_allocation_targets()` |
| `[FEES] expense_ratios` | `get_expense_ratios()` |
| `[MANUAL] accounts` | `get_manual_accounts()` |

Option and getter names are worth reading off the source rather than guessing.
The aliases setting is `[ACCOUNTS] aliases`, not `[SNAPTRADE] account_aliases`,
and the getter is `get_account_costs()` for an option called `cost_basis` — a
grep for a name that does not exist returns the same silence as a setting that
is genuinely absent, which is how the mistake above compounds.

## The config holds secrets, so do not print it wholesale

`[SNAPTRADE] clientId` is in there, and the file is owner-only for that reason.
When answering a question about one setting, print that setting — not the
section, and never the file.

## `0 accounts` in a database is not always a failure

A retired broker's database is recreated empty by `initialize_db()` on the next
run, so a bundled broker that no longer runs shows `0 accounts` forever and still
appears in the `Refreshed: … from …` source list. `fidelity.db` is the standing
example — Fidelity reaches the workspace through SnapTrade now.

An empty database that *should* have rows is a broker whose run wrote nothing,
which has to stay loud. The two look identical from the outside, so check which
one you are looking at before reporting either. See
[*The database comes back*](docs/brokers.md#the-database-comes-back-and-that-is-not-the-move-failing).

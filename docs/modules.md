# Writing a module

What a module is handed, and what it is expected to give back.

**This is a reference chapter, not a record.** It describes the module contract
as it is today. A broker's own shape — what it logs into and what it reads —
is [`brokers.md`](brokers.md); where a module's output ends up is
[`database.md`](database.md) and [`sheet.md`](sheet.md).

`src/stonksmith/modules/example.py` is the annotated template, and is deliberately exempt
from some lint rules because its unused arguments are the point.

---

## What to import

Everything StonkSmith exposes lives under `stonksmith.`:

```python
from stonksmith.etc.connection import Connection
from stonksmith.etc.context import Context
```

**The old top-level names still work, and will stop working at 1.0.** Before the
package had a namespace it installed `etc`, `helpers`, `modules`, `loaders` and
`brokers` directly into `site-packages`, and modules were written against those:

```python
from etc.connection import Connection  # deprecated
from etc.context import Context  # deprecated
```

A file under `~/.stonksmith/modules` or `~/.stonksmith/brokers` that says this
still loads. StonkSmith aliases the old names for as long as it is executing your
file, logs which name it aliased, and raises a `DeprecationWarning`. Change the
imports when convenient; nothing else about the contract has moved.

One limit worth knowing, because it is not obvious: the alias exists only while
your file is being *loaded*. A top-level `import etc.config` is fine — the name it
binds is the real module and keeps working for the life of the run. The same
import written inside `on_login()` runs later, after the alias is gone, and raises
`ModuleNotFoundError`. Import at the top of the file, as the template does.

---

## Credential access

During module execution (`on_login`), credentials are available from both
`context` and `connection`:

- Active authenticated credential:
  - `context.active_username`
  - `context.active_password`
- Raw CLI-provided credential lists:
  - `context.cli_usernames`
  - `context.cli_passwords`
- Backward-compatible connection fields:
  - `connection.username`
  - `connection.password`

Example:

```python
def on_login(self, context, connection):
    user = context.active_username or connection.username
    if not user:
        context.log.fail("No authenticated user found")
        return False
    context.log.success(f"Running module for {user}")
```

Secrets themselves live in the OS keyring rather than in the database — see
*Security* in [the README](../README.md#security) for what is stored where.

---

## What a module returns

Return `False` if the module did no work — it could not reach the service, found
nothing to sync, or wrote nothing. StonkSmith exits `1` when any module returns
`False`, which is how a scheduled run detects a failure instead of reporting
success and moving on.

Returning `None` or `True` means the module did its job. `None` is the original
signature and still means success, so a module written before this contract
needs no change. Only the exact value `False` is read as failure — returning a
count of `0`, or an empty string, counts as success, so return a real `bool` if
you mean one.

The exit codes those returns produce are tabulated in
[the README](../README.md#exit-codes).

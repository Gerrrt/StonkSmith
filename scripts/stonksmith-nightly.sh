#!/bin/sh
# The nightly run, as one script, for launchd.
#
# scripts/stonksmith.cron is the same schedule for cron. Both exist because on
# macOS cron is the wrong one: two of these six steps read a secret from the
# login keychain, and a cron job runs outside the GUI session, where that
# keychain is not visible. The secret comes back empty rather than erroring, so
# SnapTrade reports no consumer key and Schwab 529 fails a login as though the
# password were wrong. A LaunchAgent bootstrapped into the GUI session can read
# it. docs/scheduling.md has the whole story.
#
# Two things fall out of being a script rather than six crontab lines.
#
#   The steps run in sequence, so "the sheet after every broker, the freshness
#   check after the sheet" is what actually happens rather than what staggered
#   minutes imply. There is nothing to stagger, and no way for two runs to land
#   in the same second and collapse into one snapshot.
#
#   Which is also how the --no-sheet flags below were found. Every broker
#   rewrites the whole sheet when it finishes, so this ran five full rewrites in
#   about thirty seconds and Google refused the last one -- the only one that
#   needed to happen -- for exceeding the write quota per minute. Staggered
#   crontab entries hid that by spacing the waste out. The brokers now skip it
#   and the sheet entry renders all of them once.
#
#   It finds its own checkout. The crontab has to name a path and guess wrong;
#   this one starts from where the script lives, so it is right wherever the
#   repository is cloned.
#
# A failing step does not stop the ones after it -- a broker that cannot log in
# should not cost you the sheet. The script exits non-zero if any step did, so
# launchd and the log see a failure even when it was the second of six.

set -u

# Resolved in steps, each one checked, rather than as one nested substitution.
# `cd ""` *succeeds* and stays where it was, so a substitution that came back
# empty would not trip `|| exit 1` -- it would leave the run in whatever
# directory launchd started it in, which is `/` for an agent, and `uv run` there
# resolves some other project or none at all. No `--` on dirname or cd either:
# $0 is an absolute path in every context this runs in, and BSD and GNU do not
# agree about accepting it.
script_dir=$(dirname "$0")
[ -n "$script_dir" ] || exit 1

repo=$(CDPATH= cd "$script_dir/.." && pwd)
[ -n "$repo" ] || exit 1

cd "$repo" || exit 1

# The check a wrong answer above cannot survive. Cheaper than discovering it
# from six identical `uv run` failures.
if [ ! -f pyproject.toml ]; then
    echo "Not a StonkSmith checkout: no pyproject.toml in $repo" >&2
    exit 1
fi

# 1 for any failure, rather than the failing step's own code. The exit codes
# this aggregates are 1 for a real failure and 130 for an interrupt, and the
# tool's contract is that a scheduler pages on 1 and shrugs at 130 -- so taking
# the larger of them would let an interrupted step mask a broken one and report
# the night as nothing to worry about. A run where anything failed is a run to
# look at.
status=0

run() {
    echo "--- $* "
    "$@" || status=1
}

run uv run stonksmith tsp -M tsp --no-sheet --quiet
run uv run stonksmith snaptrade -M snaptrade --no-sheet --quiet
run uv run stonksmith schwab529plan -M schwab529plan -id 1 --no-sheet --quiet
run uv run stonksmith ally -M ally --from-prices --no-sheet --quiet
run uv run stonksmithdb sheet
run uv run stonksmithdb stale

exit "$status"

#!/bin/sh
# The opening-bell run, as one script, for launchd.
#
# The third agent. scripts/stonksmith-nightly.sh scrapes after the close and
# scripts/stonksmith-morning.sh renders the brief; this one takes a second mark
# shortly after the market opens, so the databases carry an intraday point
# rather than one reading a day.
#
# It fires at 06:35 local, which is five minutes after the 06:30 ET open on
# Pacific -- and five minutes after the brief, deliberately. The brief reads
# every database in the workspace and this writes them, so overlapping them
# would have the brief reporting a workspace caught mid-write. Brief first is
# also the right order on its own terms: a morning brief reports on last night's
# close, which is exactly what it has before this runs.
#
# ---------------------------------------------------------------------------
# WHAT ACTUALLY MOVES AT THE OPEN, WHICH IS NOT ALL FOUR
#
# Worth knowing before reading anything into a 06:35 snapshot:
#
#   snaptrade      Real. A live API call returning current positions, so this
#                  is the entry that makes the opening run worth having.
#
#   tsp            Not yet. TSP publishes the day's share prices in the
#                  evening -- which is the whole reason the nightly run sits at
#                  18:30 -- so at 06:35 the newest published price is
#                  yesterday's. This records it again under a new scraped_at.
#                  Not wrong: the mark carries yesterday's as_of and says so.
#                  Just not new.
#
#   schwab529plan  Not yet, for the same reason. Unit values post after the
#                  close.
#
#   ally           Not yet. --from-prices multiplies a recorded unit count by
#                  the published close, and today's close does not exist at
#                  06:35, so it reprices against yesterday's.
#
# All four run anyway rather than snaptrade alone. A schedule that quietly
# scrapes a subset is a schedule somebody later reads as complete, and the three
# above cost one duplicate row each and report their own as_of honestly. What
# they must not do is leave a reader thinking the 06:35 TSP number is a morning
# price, which is what this comment is for.
#
# ---------------------------------------------------------------------------
# No `stonksmithdb stale` here, unlike the nightly run. That check exists to
# catch a broker that has gone silent, and nothing can have gone stale in the
# twelve hours since the evening run made exactly the same check. Running it
# twice a day would double the alarm without doubling what it can detect, and an
# alarm that fires more often than it has news is the one that gets muted --
# which is the failure docs/scheduling.md opens by naming.

set -u

# Resolved in steps, each one checked, rather than as one nested substitution.
# `cd ""` *succeeds* and stays where it was, so a substitution that came back
# empty would not trip `|| exit 1` -- it would leave the run in whatever
# directory launchd started it in, which is `/` for an agent, and `uv run` there
# resolves some other project or none at all.
script_dir=$(dirname "$0")
[ -n "$script_dir" ] || exit 1

repo=$(CDPATH= cd "$script_dir/.." && pwd)
[ -n "$repo" ] || exit 1

cd "$repo" || exit 1

# The check a wrong answer above cannot survive.
if [ ! -f pyproject.toml ]; then
    echo "Not a StonkSmith checkout: no pyproject.toml in $repo" >&2
    exit 1
fi

# 1 for any failure, rather than the failing step's own code -- the nightly
# runner's reasoning, unchanged: a scheduler pages on 1 and shrugs at 130, so
# taking the larger would let an interrupted step mask a broken one.
status=0

run() {
    echo "--- $* "
    "$@" || status=1
}

# --no-sheet on every broker and one sheet write at the end, for the reason the
# nightly runner records: each broker rewrites the whole sheet when it finishes,
# so four back-to-back runs spent the per-minute write quota and Google refused
# the last one -- the only one that needed to happen.
run uv run stonksmith tsp -M tsp --no-sheet --quiet
run uv run stonksmith snaptrade -M snaptrade --no-sheet --quiet
run uv run stonksmith schwab529plan -M schwab529plan -id 1 --no-sheet --quiet
run uv run stonksmith ally -M ally --from-prices --no-sheet --quiet
run uv run stonksmithdb sheet

exit "$status"

#!/bin/sh
# The morning brief, as one script, for launchd.
#
# The other half of scripts/stonksmith-nightly.sh, and deliberately not part of
# it. That one scrapes at 18:30 and this one reports at 06:30, because the two
# answer to different clocks: a scrape has to happen after the market closes and
# after TSP publishes, and a reminder has to happen when somebody is there to
# read it. Folding the brief into the nightly run would render it twelve hours
# before anyone opens a laptop, at which point it is a file rather than a
# reminder.
#
# This does not scrape, and that is the point rather than a limitation. At half
# past six the market is shut, TSP has not published, and the browser-backed
# brokers want a human at a sign-in page. `stonksmithdb brief` reads the
# databases and nothing else -- no login, no network -- so it cannot fail in any
# of the ways a broker can, and it takes about a second.
#
# It must run in the GUI session for a second reason on top of the keychain one
# that governs the nightly agent: a LaunchAgent outside that session has no
# browser to open and no display to open it on, so the brief would be written
# every morning and shown to nobody. See docs/scheduling.md.

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

# The check a wrong answer above cannot survive. Cheaper than discovering it
# from a `uv run` failure that names something else.
if [ ! -f pyproject.toml ]; then
    echo "Not a StonkSmith checkout: no pyproject.toml in $repo" >&2
    exit 1
fi

echo "--- uv run stonksmithdb brief"

# One step, so its exit status is the script's. `brief` exits non-zero when a
# broker's database would not open -- the brief is still written and still
# opened in that case, carrying the same warning at the top of the page, so the
# failure is visible to the reader as well as to launchd.
uv run stonksmithdb brief

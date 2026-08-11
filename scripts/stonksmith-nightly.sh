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
#   It finds its own checkout. The crontab has to name a path and guess wrong;
#   this one starts from where the script lives, so it is right wherever the
#   repository is cloned.
#
# A failing step does not stop the ones after it -- a broker that cannot log in
# should not cost you the sheet. The exit status is the worst of them, so
# launchd and the log see a failure even when it was the second of six.

set -u

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)" || exit 1

status=0

run() {
    echo "--- $* "
    "$@" || status=1
}

run uv run stonksmith tsp -M tsp --quiet
run uv run stonksmith snaptrade -M snaptrade --quiet
run uv run stonksmith schwab529plan -M schwab529plan -id 1 --quiet
run uv run stonksmith ally -M ally --from-prices --quiet
run uv run stonksmithdb sheet
run uv run stonksmithdb stale

exit "$status"

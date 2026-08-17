"""
Defines the command line arguments for the SnapTrade broker module.
"""

from argparse import (
    ArgumentParser,
    _SubParsersAction,  # pyright: ignore
)

#: SnapTrade refreshes holdings once a day by design, so a one-day ceiling would
#: flag healthy accounts on most runs and train the operator into passing
#: --allow-stale permanently -- which would leave every genuinely stale account
#: syncing unnoticed, the one thing the check exists to prevent. A disabled
#: connection is skipped regardless of this flag.
DEFAULT_MAX_AGE_DAYS = 3

#: How far back to ask for transactions. Bounded rather than "everything",
#: because the activities endpoint is per account and paginated: an unbounded
#: window means N accounts times however many pages of history each has, on
#: every run, to re-fetch movements the database already deduplicated. Ninety
#: days comfortably covers the gap left by any realistic missed run.
DEFAULT_HISTORY_DAYS = 90


def broker_args(
    subparsers: _SubParsersAction[ArgumentParser],
    std_parser: ArgumentParser,
    module_parser: ArgumentParser,
) -> _SubParsersAction[ArgumentParser]:
    """
    Add SnapTrade-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the SnapTrade parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    parser: ArgumentParser = subparsers.add_parser(
        name="snaptrade",
        help="Every brokerage connected through https://snaptrade.com",
        parents=[std_parser, module_parser],
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing. All three are read by modules/snaptrade_module.
    group = parser.add_argument_group(title="SnapTrade Options")

    group.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=(
            "Skip an account whose holdings last synced more than this many "
            f"days ago (default: {DEFAULT_MAX_AGE_DAYS})"
        ),
    )

    group.add_argument(
        "--allow-stale",
        action="store_true",
        help="Sync accounts that failed the freshness check anyway, marking them",
    )

    group.add_argument(
        "--include-liabilities",
        action="store_true",
        help="Also sync credit cards and other lines of credit, which carry "
        "negative balances",
    )

    group.add_argument(
        "--history-days",
        type=int,
        default=DEFAULT_HISTORY_DAYS,
        help=(
            "How far back to fetch transactions for each account "
            f"(default: {DEFAULT_HISTORY_DAYS}). 0 skips transactions entirely."
        ),
    )

    group.add_argument(
        "--page-size",
        type=int,
        default=None,
        help=(
            "How many transactions to ask for per request (default: the "
            "server's own, which is 1000). Lower it to make the pagination "
            "follow real pages -- at the default no account here fills a second"
        ),
    )

    group.add_argument(
        "--no-positions",
        action="store_true",
        help=(
            "Skip the per-account positions call, syncing balances only. The "
            "snapshot this writes therefore holds no positions, and the "
            "Holdings tab renders the newest snapshot -- so this empties the "
            "tab of everything SnapTrade contributes until a full run follows. "
            "Fine once; not a flag to put in a crontab"
        ),
    )

    group.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="'BROKERAGE / ACCOUNT'",
        help=(
            "Do not sync this account, because another broker already covers "
            "it; repeatable. Use the label the sync prints, e.g. "
            "'Schwab / Beneficiary A 529 Plan'. Adds to exclude_accounts in the "
            "[SNAPTRADE] section of the config, which is the better place for "
            "a standing overlap since a cron run has nobody to remember it"
        ),
    )

    return subparsers

# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
The morning brief as one HTML file that depends on nothing.

No template engine. The whole page is a handful of f-strings, which is not
minimalism for its own sake: a template engine would be a new runtime dependency
carried by every install of a scraper, to render one page whose structure is
fixed and known here. etc.portfolio_sheet builds a far larger artefact the same
way.

Self-contained in the strict sense -- no stylesheet, font, script or image is
fetched. The file is opened from disk by a LaunchAgent at half past six, and a
page that reaches the network to look right is a page that looks broken on the
morning the network is not there yet.

**Everything interpolated is escaped.** Account names, symbols and transaction
descriptions all arrive from scraped pages: they are the least trusted strings in
the project, they are attacker-influenced in the ordinary case of a brokerage
letting somebody nickname an account, and this file is opened in a browser. The
sheet writes the same values as RAW cell contents, where markup is inert; here it
is not, so every one of them goes through escape() and the tests pin it.

Two facts drive the visual design rather than taste. The delta may be built on
carried values, so the observed/carried split is rendered beside the headline
where it cannot be missed instead of in a footnote. And direction is never
carried by colour alone -- every rise and fall also carries an arrow, because a
red-green dashboard is unreadable to about one man in twelve.
"""

import datetime as dt
from collections.abc import Iterable
from html import escape

from stonksmith.etc.brief import (
    UNCLASSIFIED,
    Allocation,
    Brief,
    BriefState,
    Movement,
    Performance,
    Position,
)
from stonksmith.etc.portfolio import OBSERVED, TransactionRow

#: The sparkline's coordinate space. Rendered at width 100% with a non-scaling
#: stroke, so the viewBox is the drawing's own geometry and not a pixel size.
CHART_WIDTH: int = 720
CHART_HEIGHT: int = 132

#: How much vertical room the line is given inside that box, leaving the rest as
#: padding. A series drawn edge to edge clips its own stroke at the extremes.
CHART_INSET: int = 10

STYLE: str = """
:root {
  color-scheme: light dark;
  --bg: #f6f7f9;
  --card: #ffffff;
  --ink: #16181d;
  --dim: #62666e;
  --line: #e3e5e9;
  --up: #0a7c42;
  --down: #b3261e;
  --warn-bg: #fff4e5;
  --warn-ink: #7a4100;
  --warn-line: #f0c48a;
  --accent: #3b5bdb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131417;
    --card: #1c1e23;
    --ink: #e8eaed;
    --dim: #9aa0a8;
    --line: #2c2f36;
    --up: #4ade80;
    --down: #f87171;
    --warn-bg: #2e2210;
    --warn-ink: #fbbf24;
    --warn-line: #6b4c14;
    --accent: #8da2fb;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1.25rem 4rem;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 0.95rem; font-weight: 600; letter-spacing: 0.08em;
     text-transform: uppercase; color: var(--dim); margin: 0 0 1.25rem; }
h2 { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em;
     text-transform: uppercase; color: var(--dim); margin: 0 0 0.75rem; }
section { background: var(--card); border: 1px solid var(--line);
          border-radius: 14px; padding: 1.25rem 1.4rem; margin-bottom: 1rem; }
.total { font-size: 2.9rem; font-weight: 650; letter-spacing: -0.02em;
         font-variant-numeric: tabular-nums; margin: 0; }
.delta { font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--dim); }
.note { color: var(--dim); font-size: 0.85rem; margin: 0.4rem 0 0; }
.banner { background: var(--warn-bg); color: var(--warn-ink);
          border: 1px solid var(--warn-line); border-radius: 14px;
          padding: 0.9rem 1.2rem; margin-bottom: 1rem; font-weight: 600; }
.banner p { margin: 0.35rem 0 0; font-weight: 400; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th { text-align: left; font-size: 0.72rem; letter-spacing: 0.07em;
     text-transform: uppercase; color: var(--dim); font-weight: 600;
     padding: 0 0.55rem 0.5rem; border-bottom: 1px solid var(--line); }
td { padding: 0.55rem; border-bottom: 1px solid var(--line); }
/* Horizontal padding on the cells, not only vertical. Without it the numeric
   columns butt against each other and render as one string -- "$26.00$5,845.93"
   reads as a single figure, which on a money table is worse than ugly. The
   first and last cells lose their outer padding so the table still lines up
   with the section's own edges. */
tr > *:first-child { padding-left: 0; }
tr > *:last-child { padding-right: 0; }
tr:last-child td { border-bottom: 0; }
td.num, th.num { text-align: right; white-space: nowrap; }
.who { font-weight: 550; }
.broker { color: var(--dim); font-size: 0.8rem; }
.carried { color: var(--dim); font-size: 0.72rem; font-weight: 500;
           border: 1px solid var(--line); border-radius: 999px;
           padding: 0.05rem 0.45rem; margin-left: 0.4rem; white-space: nowrap; }
.bar { height: 6px; border-radius: 999px; background: var(--accent); }
.empty { color: var(--dim); margin: 0; }
.tiles { display: grid; gap: 0.9rem;
         grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
.tile { border: 1px solid var(--line); border-radius: 12px; padding: 0.9rem 1rem; }
.tile .cap { font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase;
             color: var(--dim); font-weight: 600; }
.tile .fig { font-size: 1.55rem; font-weight: 640; letter-spacing: -0.01em;
             font-variant-numeric: tabular-nums; margin-top: 0.2rem; }
.tile .sub { font-size: 0.72rem; color: var(--dim); margin-top: 0.15rem; }
/* The holdings table is wider than a phone and must scroll inside its own box
   rather than making the page scroll sideways. */
.scroll { overflow-x: auto; }
.scroll table { min-width: 46rem; }
.spark { display: block; }
.wl { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; }
footer { color: var(--dim); font-size: 0.78rem; text-align: center;
         margin-top: 1.5rem; }
"""


def money(value: float | None, currency: str = "USD") -> str:
    """
    A number as money, or a dash where there is no number.

    A dash rather than "$0.00" for an absent value, on the rule the row shapes
    already keep: a source that reported nothing is not a source that reported
    zero, and the one place that distinction must survive is the screen a person
    reads.
    :param value: The amount
    :param currency: Its currency, for the symbol
    :return: The rendered amount
    :rtype: str
    """

    if value is None:
        return "—"

    sign: str = "$" if currency == "USD" else f"{currency} "

    return f"{sign}{value:,.2f}"


def signed(value: float, currency: str = "USD") -> str:
    """
    A move as money, with the arrow that carries its direction without colour.
    :param value: The move
    :param currency: Its currency
    :return: The rendered move
    :rtype: str
    """

    if not value:
        return f"± {money(value=0.0, currency=currency)}"

    arrow: str = "▲" if value > 0 else "▼"

    return f"{arrow} {money(value=abs(value), currency=currency)}"


def percent(value: float | None) -> str:
    """
    A fraction as a percentage, or empty where there is no denominator.
    :param value: The fraction
    :return: The rendered percentage, or ""
    :rtype: str
    """

    if value is None:
        return ""

    return f"{value * 100:+.2f}%"


def direction(value: float) -> str:
    """
    Which class a number should wear.
    :param value: The move
    :return: "up", "down" or "flat"
    :rtype: str
    """

    if value > 0:
        return "up"

    return "down" if value < 0 else "flat"


def sparkline(points: Iterable[tuple[str, float, bool]]) -> str:
    """
    The trailing series as an inline SVG, or nothing when there is no shape.

    Two points are the fewest that can make a line; one produces a chart of a
    single dot that reads as a flat portfolio rather than as a portfolio nobody
    has measured twice. Nothing is drawn in that case, which is the honest
    rendering of "there is no series yet".

    Observed dates get a dot and carried ones do not. A stretch of carried dates
    is a straight segment drawn between two readings, and marking where the
    readings actually are is what stops the line from claiming to be a
    measurement along its whole length.
    :param points: (date, total, observed), oldest first
    :return: The SVG, or "" when there is nothing to draw
    :rtype: str
    """

    series: list[tuple[str, float, bool]] = list(points)

    if len(series) < 2:
        return ""

    values: list[float] = [total for _, total, _ in series]
    low: float = min(values)
    high: float = max(values)

    # A flat series has no range to scale into, and dividing by it would put
    # every point at infinity. Drawn down the middle instead, which is what a
    # portfolio that has not moved actually looks like.
    span: float = (high - low) or 1.0
    floor: int = CHART_HEIGHT - CHART_INSET
    room: int = CHART_HEIGHT - (CHART_INSET * 2)
    step: float = CHART_WIDTH / (len(series) - 1)

    spots: list[tuple[float, float]] = [
        (index * step, floor - ((total - low) / span) * room)
        for index, (_, total, _) in enumerate(series)
    ]
    line: str = " ".join(f"{x:.1f},{y:.1f}" for x, y in spots)
    area: str = f"0,{CHART_HEIGHT} {line} {CHART_WIDTH},{CHART_HEIGHT}"

    dots: str = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--accent)"/>'
        for (x, y), (_, _, seen) in zip(spots, series, strict=True)
        if seen
    )

    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" width="100%" '
        f'height="{CHART_HEIGHT}" preserveAspectRatio="none" role="img" '
        f'aria-label="Portfolio value over the last {len(series)} readings">'
        f'<polygon points="{area}" fill="var(--accent)" opacity="0.12"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--accent)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"/>{dots}</svg>'
    )


def mini(values: Iterable[float], width: int = 96, height: int = 24) -> str:
    """
    A position's value series, small enough to sit in a table cell.

    Separate from sparkline() rather than a parameter on it. That one draws the
    portfolio and carries an area fill, observed/carried dots and an accessible
    label; this is a row-height glyph where all three would be noise, and at
    twenty-four pixels the dots would touch. Same refusal to draw from one
    point, for the same reason: a single dot on a flat axis reads as a position
    that has not moved rather than one nobody has measured twice.
    :param values: The value series, oldest first
    :param width: The drawing width
    :param height: The drawing height
    :return: The SVG, or "" when there is nothing to draw
    :rtype: str
    """

    series: list[float] = list(values)

    if len(series) < 2:
        return ""

    low: float = min(series)
    span: float = (max(series) - low) or 1.0
    step: float = width / (len(series) - 1)
    inset: int = 3

    points: str = " ".join(
        f"{index * step:.1f},"
        f"{height - inset - ((value - low) / span) * (height - inset * 2):.1f}"
        for index, value in enumerate(series)
    )

    # Coloured by where it ended relative to where it started, which is the one
    # thing a glyph this size can honestly say.
    tone: str = "var(--up)" if series[-1] >= series[0] else "var(--down)"

    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{tone}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _tile(caption: str, figure: str, sub: str = "", tone: str = "") -> str:
    """
    One statistic, captioned.
    :param caption: What it is
    :param figure: The number
    :param sub: A qualifier under it, where one is owed
    :param tone: An optional "up"/"down" class for the figure
    :return: The tile
    :rtype: str
    """

    note: str = f'<div class="sub">{escape(s=sub)}</div>' if sub else ""

    return (
        f'<div class="tile"><div class="cap">{escape(s=caption)}</div>'
        f'<div class="fig {tone}">{escape(s=figure)}</div>{note}</div>'
    )


def _tiles(brief: Brief) -> str:
    """
    The six-tile summary, and the qualifiers that keep it from overclaiming.

    Two of these tiles are routinely built from part of the portfolio, and both
    say so underneath rather than in a footnote:

    Gain is summed over the positions whose source stated a cost basis. On a
    workspace where SnapTrade reports one and TSP and the 529 do not, that is a
    real gain on a real subset presented beside a total that covers everything --
    so the tile states how many positions it stands on.

    Dividend income is a trailing year of the transaction log, and a log younger
    than a year yields a number that is not a year's income. The tile names the
    span it actually covers, which is the only way to tell a low yield from a
    short history.
    :param brief: What this morning has to say
    :return: The section
    :rtype: str
    """

    money_of: Performance = brief.performance
    tone: str = "" if money_of.gain is None else direction(value=money_of.gain)

    partial: str = (
        f"across {money_of.priced} of {money_of.holdings} positions; "
        f"{money_of.unpriced} report no cost basis"
        if money_of.unpriced
        else f"across all {money_of.holdings} positions"
    )

    # Three different sentences, because "$0.00" has three different causes here
    # and only one of them is a fact about the portfolio. No dividend rows at all
    # means the transaction log has never carried one -- which is what a
    # workspace of contributions and transfers looks like, and is not a portfolio
    # that pays nothing.
    if not money_of.dividends_seen:
        span = "no dividends in the transaction log"
    elif money_of.dividend_days < 300:
        span = f"only {money_of.dividend_days} days of log so far"
    else:
        span = "trailing twelve months"

    # What the accounts are worth, minus what the positions account for, which
    # is cash -- and now exactly cash rather than approximately it. The SnapTrade
    # sync computes an account's value as its positions plus its cash balance, so
    # this difference is that cash by construction instead of a residue of two
    # numbers struck at different times.
    #
    # **Negative is a debt, not a discrepancy.** This read "positions total
    # $1,036.22 more than the account balances" while the value came from
    # SnapTrade's daily-cached total, and the honest reading then was that two
    # numbers disagreed. They no longer can: a brokerage account worth less than
    # the fund inside it has money borrowed against it -- an overdraft transfer
    # out, or a margin loan -- and naming it as one is the difference between a
    # reader checking their broker and a reader ignoring a caveat.
    cash: float = money_of.value - money_of.invested
    holds: str = f"{money_of.holdings} holdings"

    if round(cash, 2) > 0:
        holds = f"{holds}, plus {money(value=cash, currency=money_of.currency)} in cash"
    elif round(cash, 2) < 0:
        holds = (
            f"{holds}, less "
            f"{money(value=abs(cash), currency=money_of.currency)} borrowed "
            f"against them"
        )

    return (
        f'<section><h2>Portfolio</h2><div class="tiles">'
        f"{
            _tile(
                caption='Portfolio Value',
                figure=money(value=money_of.value, currency=money_of.currency),
                sub=holds,
            )
        }"
        f"{
            _tile(
                caption='Portfolio Gain $',
                figure='—'
                if money_of.gain is None
                else signed(value=money_of.gain, currency=money_of.currency),
                sub=partial,
                tone=tone,
            )
        }"
        f"{
            _tile(
                caption='Portfolio Gain %',
                figure=percent(value=money_of.growth) or '—',
                sub='' if money_of.growth is None else 'since purchase',
                tone=tone,
            )
        }"
        f"{
            _tile(
                caption='Yearly Dividend Income',
                figure=money(
                    value=money_of.dividend_income, currency=money_of.currency
                ),
                sub=span,
            )
        }"
        f"{
            _tile(
                caption='Portfolio Dividend Yield',
                # A dash rather than 0.00% when nothing was found. A yield of
                # zero is a claim about the holdings; no dividend rows at all is
                # a claim about the log, and the tile beside this one is already
                # making the second.
                figure=(
                    percent(value=money_of.dividend_yield).lstrip('+') or '—'
                    if money_of.dividends_seen
                    else '—'
                ),
                sub=(
                    'income over what the positions are worth'
                    if money_of.dividends_seen
                    else 'nothing to compute it from'
                ),
            )
        }"
        f"{
            _tile(
                caption='Win / Loss',
                figure=money(value=money_of.total_win, currency=money_of.currency),
                sub=f'against {
                    money(value=abs(money_of.total_loss), currency=money_of.currency)
                } of losses',
            )
        }"
        f"</div></section>"
    )


def _banner(brief: Brief) -> str:
    """
    The warning strip, drawn only when something is actually wrong.

    Absent on a healthy morning rather than rendered green and reassuring. A
    banner that is always there is one nobody reads, which would make it useless
    on the morning it says something.
    :param brief: What this morning has to say
    :return: The banner, or ""
    :rtype: str
    """

    if brief.state is BriefState.DEGRADED:
        missing: str = "".join(
            f"<p>{escape(s=name)} could not be read: {escape(s=reason)}</p>"
            for name, reason in brief.unreadable
        )

        return (
            f'<div class="banner">⚠ The total below is short by at least one '
            f"broker.{missing}</div>"
        )

    if brief.state is BriefState.NO_NEW_SCRAPE:
        return (
            f'<div class="banner">⚠ No new scrape since '
            f"{escape(s=brief.since)}.<p>The nightly run has not landed, so "
            f"nothing below has moved since the last brief. This morning is not "
            f"counted as read.</p></div>"
        )

    return ""


def _headline(brief: Brief) -> str:
    """
    The number the whole page exists to show, and what it is standing on.

    The observed/carried split sits directly under it rather than in a footnote.
    A delta computed over four carried accounts and one reading is a statement
    about the one broker that ran, and the difference between that and a whole
    portfolio moving is the difference this brief is obliged to make visible.
    :param brief: What this morning has to say
    :return: The headline section
    :rtype: str
    """

    total: str = money(value=brief.total, currency=brief.currency)

    if brief.state is BriefState.FIRST:
        change: str = '<span class="delta flat">first brief — nothing to compare</span>'
    else:
        pct: str = percent(value=brief.pct)
        change = (
            f'<span class="delta {direction(value=brief.delta)}">'
            f"{escape(s=signed(value=brief.delta, currency=brief.currency))}"
            f"{f' ({pct})' if pct else ''}</span>"
        )

    accounts: int = brief.observed + brief.carried
    noun: str = "account" if accounts == 1 else "accounts"

    if brief.carried:
        basis: str = (
            f"{brief.observed} of {accounts} {noun} were read on "
            f"{escape(s=brief.as_of)}; {brief.carried} carried an older value "
            f"forward. The change above is what those readings moved, not what "
            f"the whole portfolio did."
        )
    elif accounts == 1:
        # Spelled out rather than run through the plural helper. "All 1 accounts"
        # is the tell that a number was pasted into a sentence nobody read back,
        # and this line sits directly under the headline figure.
        basis = f"The one account was read on {escape(s=brief.as_of)}."
    elif accounts:
        basis = f"All {accounts} accounts were read on {escape(s=brief.as_of)}."
    else:
        basis = "No account has been read yet."

    window: str = (
        f" since {escape(s=brief.since)}"
        if brief.since and brief.state is not BriefState.FIRST
        else ""
    )

    return (
        f"<section><h2>Net worth{window}</h2>"
        f'<p class="total">{escape(s=total)}</p>{change}'
        f'<p class="note">{basis}</p>'
        f"{sparkline(points=brief.series)}</section>"
    )


def _dropped(count: int) -> str:
    """
    The line saying how many movers the cap left out.

    Absent when it left out none, which is every ordinary morning. Present when
    it did, because a ranking that ends at eight without comment reports the
    eighth as the smallest thing that moved -- and the reader has no way to tell
    a quiet day from a truncated one.
    :param count: How many moved but did not fit
    :return: The line, or ""
    :rtype: str
    """

    if count <= 0:
        return ""

    moved: str = "account" if count == 1 else "accounts"

    return f'<p class="note">{count} more {moved} moved by less, and did not fit.</p>'


def _movers(
    title: str,
    moves: Iterable[Movement],
    currency: str,
    empty: str,
    dropped: int = 0,
) -> str:
    """
    One mover table, or a sentence saying why there is none.

    The sentence matters as much as the table. An empty section reads as "nothing
    moved", and on a first brief or a stalled morning the truth is "nothing could
    be compared" -- which is a different thing and the one worth acting on.
    :param title: The section heading
    :param moves: The movements to render, in order
    :param currency: The currency they are in
    :param empty: What to say when there are none
    :return: The section
    :rtype: str
    """

    rows: list[Movement] = list(moves)

    if not rows:
        return (
            f"<section><h2>{escape(s=title)}</h2>"
            f'<p class="empty">{escape(s=empty)}</p></section>'
        )

    body: str = "".join(
        f"<tr><td>"
        f'<span class="who">{escape(s=move.label)}</span>'
        f"{_basis(move=move)}"
        f'<div class="broker">{escape(s=move.broker)}'
        f"{_units(move=move)}</div></td>"
        f'<td class="num">{escape(s=money(value=move.after, currency=currency))}</td>'
        f'<td class="num {direction(value=move.delta)}">'
        f"{escape(s=signed(value=move.delta, currency=currency))}</td>"
        f'<td class="num {direction(value=move.delta)}">'
        f"{escape(s=percent(value=move.pct)) or '—'}</td></tr>"
        for move in rows
    )

    return (
        f"<section><h2>{escape(s=title)}</h2><table>"
        f'<tr><th>Name</th><th class="num">Value</th>'
        f'<th class="num">Change</th><th class="num">%</th></tr>'
        f"{body}</table>{_dropped(count=dropped)}</section>"
    )


def _basis(move: Movement) -> str:
    """
    The pill that marks a row whose newer number nobody read.

    On the row rather than in a legend. A reader scanning four movers should not
    have to hold "the third one is carried" in their head to read the fourth --
    and a legend is the first thing that stops being read.
    :param move: The movement
    :return: The pill, or "" for an observed row
    :rtype: str
    """

    if move.basis == OBSERVED:
        return ""

    return '<span class="carried">carried</span>'


def _units(move: Movement) -> str:
    """
    The note that says a position's quantity moved, where it did.

    Rendered only when units actually changed, because that is the line between
    a position the market repriced and one that was bought or sold. A "0 units"
    note on every repriced row would bury the handful of rows that are events.
    :param move: The movement
    :return: The note, or ""
    :rtype: str
    """

    if move.units_delta is None:
        return ""

    return f" · {move.units_delta:+,.4f} units"


def _units_of(value: float | None) -> str:
    """
    A share count, at the precision a fractional-share world needs.
    :param value: The count
    :return: The rendered count, or a dash
    :rtype: str
    """

    return "—" if value is None else f"{value:,.3f}"


def _holdings(rows: Iterable[Position]) -> str:
    """
    Every position held, laid out the way the operator's own sheet lays them out.

    The whole book rather than the top movers, which is the difference between
    this and the mover tables above it. Those answer "what changed"; this answers
    "what do I own", and the second question is not a longer version of the
    first -- a position that has not moved is absent from one and belongs in the
    other.

    A dash wherever the source gave nothing, never a zero. That is most of the
    table for TSP and the scraped 529: no cost basis means no purchase price, no
    gain, no growth and no yield on cost, and six columns of 0.00 across those
    rows would read as a portfolio that has made exactly nothing rather than one
    whose cost nobody recorded.
    :param rows: Every position, largest first
    :return: The section
    :rtype: str
    """

    held: list[Position] = list(rows)

    if not held:
        return (
            '<section><h2>Holdings</h2><p class="empty">'
            "no positions recorded yet</p></section>"
        )

    body: str = "".join(
        f"<tr><td>"
        f'<span class="who">{escape(s=row.symbol)}</span>'
        f'<div class="broker">{escape(s=_under(row=row))}'
        f"{_bought(row=row)}</div></td>"
        f'<td class="num">{escape(s=_units_of(value=row.units))}</td>'
        f'<td class="num">{
            escape(s=money(value=row.purchase_price, currency=row.currency))
        }</td>'
        f'<td class="num">{
            escape(s=money(value=row.price, currency=row.currency))
        }</td>'
        f'<td class="num">{
            escape(s=money(value=row.cost_basis, currency=row.currency))
        }</td>'
        f'<td class="num">{
            escape(s=money(value=row.value, currency=row.currency))
        }</td>'
        f'<td class="num {_tone(value=row.day_change)}">'
        f"{escape(s=percent(value=row.day_change)) or '—'}</td>"
        f'<td class="num {_tone(value=row.gain)}">'
        f"{
            '—'
            if row.gain is None
            else escape(s=signed(value=row.gain, currency=row.currency))
        }</td>"
        f'<td class="num {_tone(value=row.growth)}">'
        f"{escape(s=percent(value=row.growth)) or '—'}</td>"
        f'<td class="num">{mini(values=row.trend)}</td>'
        f'<td class="num wl {_win_class(row=row)}">{_win_label(row=row)}</td></tr>'
        for row in held
    )

    return (
        f'<section><h2>Holdings</h2><div class="scroll"><table>'
        f'<tr><th>Symbol</th><th class="num">Shares</th>'
        f'<th class="num">Purchase</th><th class="num">Price</th>'
        f'<th class="num">Cost</th><th class="num">Market Value</th>'
        f'<th class="num">Day</th><th class="num">Gain</th>'
        f'<th class="num">Growth</th><th class="num">Trend</th>'
        f'<th class="num">W/L</th></tr>'
        f"{body}</table></div></section>"
    )


def _bought(row: Position) -> str:
    """
    The note that says a position's quantity moved since the last brief.

    The one thing the position movers list said that this table does not. A row
    whose value rose on an unchanged count was repriced by the market; one whose
    count rose was bought, and only the second is an event. Rendered only when
    it happened, so an ordinary morning carries no note.
    :param row: The position
    :return: The note, or ""
    :rtype: str
    """

    if row.units_delta is None:
        return ""

    return f" · {row.units_delta:+,.4f} units"


def _under(row: Position) -> str:
    """
    The line under a symbol: which account holds it, and its class where declared.

    The account **always**, which is the half that was learned rather than
    designed. The same fund is routinely held in four accounts -- SWPPX appears
    under a joint brokerage, two individual ones and a child's -- and a table
    that shows the symbol alone renders those as four identical rows with
    different numbers. The reader cannot tell which is which, and the column that
    would say is the one the source is most reliable about.

    The asset class joins it when one is declared, rather than replacing it.
    "(unclassified)" repeated down the whole table is every row stating the same
    non-fact, so that case falls back to the account on its own.
    :param row: The position
    :return: The subtitle
    :rtype: str
    """

    account: str = row.account or row.broker

    if row.asset_class == UNCLASSIFIED:
        return account

    return f"{account} · {row.asset_class}"


def _tone(value: float | None) -> str:
    """
    Which class a possibly-absent number should wear.

    "flat" rather than "up" for an absent one. direction() reads None as falsy
    and would colour it green, which is the wrong half of a red-green pair to
    default to when the answer is that nobody knows.
    :param value: The number
    :return: "up", "down" or "flat"
    :rtype: str
    """

    return "flat" if value is None else direction(value=value)


def _win_label(row: Position) -> str:
    """
    The sheet's W/L flag, with a third answer it does not have.
    :param row: The position
    :return: "W", "L" or a dash
    :rtype: str
    """

    if row.winning is None:
        return "—"

    return "W" if row.winning else "L"


def _win_class(row: Position) -> str:
    """
    How to colour that flag.
    :param row: The position
    :return: "up", "down" or "flat"
    :rtype: str
    """

    if row.winning is None:
        return "flat"

    return "up" if row.winning else "down"


def _transactions(rows: Iterable[TransactionRow]) -> str:
    """
    Everything recorded since the last brief.
    :param rows: The new movements, newest first
    :return: The section
    :rtype: str
    """

    movements: list[TransactionRow] = list(rows)

    if not movements:
        return ""

    body: str = "".join(
        f"<tr><td>{escape(s=row.processed_on or row.traded_on or '')}</td>"
        f'<td><span class="who">{escape(s=row.tx_type or "movement")}</span>'
        f'<div class="broker">{_detail(row=row)}</div></td>'
        f'<td class="num">{escape(s=money(value=row.value, currency=row.currency))}'
        f"</td></tr>"
        for row in movements
    )

    return (
        f"<section><h2>New since the last brief</h2><table>"
        f'<tr><th>Date</th><th>What</th><th class="num">Amount</th></tr>'
        f"{body}</table></section>"
    )


def _detail(row: TransactionRow) -> str:
    """
    Which account a movement was against, and what it was in.

    Joined rather than interpolated around a fixed separator. A scraped 529
    supplies neither a symbol nor a description -- both blank is the ordinary
    case for it, not an error -- and a hardcoded "·" leaves that row ending in a
    dangling separator, which reads as a field that failed to render.
    :param row: The movement
    :return: The subtitle
    :rtype: str
    """

    parts: list[str] = [
        escape(s=part) for part in (row.account, row.symbol or row.description) if part
    ]

    return " · ".join(parts)


def _allocation(rows: Iterable[Allocation]) -> str:
    """
    The asset-class breakdown, with what each slice was before.
    :param rows: The breakdown, largest first
    :return: The section, or "" when nothing is classified
    :rtype: str
    """

    classes: list[Allocation] = list(rows)

    if not classes:
        return ""

    body: str = "".join(
        f'<tr><td><span class="who">{escape(s=entry.label)}</span>'
        f'<div class="bar" style="width:{entry.share * 100:.1f}%"></div></td>'
        f'<td class="num">{escape(s=money(value=entry.value))}</td>'
        f'<td class="num">{entry.share * 100:.1f}%</td>'
        f'<td class="num">{_drift(entry=entry)}</td></tr>'
        for entry in classes
    )

    return (
        f"<section><h2>Allocation</h2><table>"
        f'<tr><th>Class</th><th class="num">Value</th>'
        f'<th class="num">Share</th><th class="num">Drift</th></tr>'
        f"{body}</table></section>"
    )


def _drift(entry: Allocation) -> str:
    """
    How far one class has moved from the share it held at the baseline.
    :param entry: The class
    :return: The drift in percentage points, or a dash
    :rtype: str
    """

    if entry.was is None:
        return "—"

    # Percentage *points*, not a percentage of a percentage. A class going from
    # 20% to 22% has drifted two points and risen by ten percent of itself, and
    # the two numbers invite opposite conclusions about the same move.
    return f"{(entry.share - entry.was) * 100:+.1f} pp"


def _stale(rows: Iterable[tuple[str, str]]) -> str:
    """
    Every account that cannot be shown to be fresh.
    :param rows: (account, reason) pairs
    :return: The section, or "" when everything is fresh
    :rtype: str
    """

    accounts: list[tuple[str, str]] = list(rows)

    if not accounts:
        return ""

    body: str = "".join(
        f'<tr><td><span class="who">{escape(s=name)}</span></td>'
        f"<td>{escape(s=reason)}</td></tr>"
        for name, reason in accounts
    )

    return (
        f"<section><h2>Not fresh</h2><table>"
        f"<tr><th>Account</th><th>Why</th></tr>{body}</table></section>"
    )


def render(brief: Brief, now: dt.datetime) -> str:
    """
    The whole brief as one HTML document.
    :param brief: What this morning has to say
    :param now: When it was rendered, for the footer
    :return: The document
    :rtype: str
    """

    compared: str = (
        "nothing to compare against yet"
        if brief.state is BriefState.FIRST
        else "no account moved since the last brief"
    )

    # Built as a list rather than interpolated inline. Every one of these is a
    # call that may return "", and a section that renders to nothing must leave
    # nothing behind rather than an empty card -- which is what a page assembled
    # out of one long f-string quietly produces.
    body: list[str] = [
        _banner(brief=brief),
        _headline(brief=brief),
        _tiles(brief=brief),
        _movers(
            title="Accounts",
            moves=brief.account_movers,
            currency=brief.currency,
            empty=compared,
            dropped=brief.account_movers_dropped,
        ),
        # The full book rather than the position movers this used to carry. The
        # mover list answered "what changed" and the headline above already does
        # that for the portfolio; a reader who wants to know what they own was
        # being shown a filtered subset of it.
        _holdings(rows=brief.positions),
        _transactions(rows=brief.new_transactions),
        _allocation(rows=brief.allocation),
        _stale(rows=brief.stale),
    ]

    stamp: str = now.strftime("%A %d %B %Y, %H:%M")
    title: str = escape(s=brief.as_of or "no readings")

    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>StonkSmith — {title}</title>"
        f"<style>{STYLE}</style></head><body><main>"
        f"<h1>StonkSmith · morning brief</h1>"
        f"{''.join(part for part in body if part)}"
        f"<footer>Rendered {escape(s=stamp)} from the databases, "
        f"not from a broker.</footer>"
        f"</main></body></html>"
    )

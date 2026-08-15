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
import re
from collections.abc import Iterable
from html import escape

from stonksmith.etc.brief import (
    UNCLASSIFIED,
    Allocation,
    Brief,
    BriefState,
    Concentration,
    Movement,
    Performance,
    Position,
)
from stonksmith.etc.config import get_drift_band
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
/* Wider than a reading column on purpose. This page is mostly an eleven
   column money table, and 60rem forced it into its own horizontal
   scrollbar on a full-size screen -- which hides the rightmost columns
   behind a gesture at exactly the moment somebody is skimming. */
main { max-width: 78rem; margin: 0 auto; }
h1 { font-size: 0.95rem; font-weight: 600; letter-spacing: 0.08em;
     text-transform: uppercase; color: var(--dim); margin: 0 0 1.25rem;
     display: flex; align-items: center; gap: 0.6rem; }
/* The mark from the README, inlined. Sized here rather than in the file, so one
   SVG can render at 88px on GitHub and as a badge on this page. */
.mark { width: 1.9rem; height: 1.9rem; flex: none; border-radius: 0.42rem; }
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
     padding: 0 0.45rem 0.5rem; border-bottom: 1px solid var(--line); }
td { padding: 0.5rem 0.45rem; border-bottom: 1px solid var(--line); }
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
   rather than making the page scroll sideways. The box stays: a phone cannot
   be widened into. What changed is that the desktop no longer needs it. */
.scroll { overflow-x: auto; }
.scroll table { min-width: 52rem; }
.spark { display: block; }
/* The chart's own axes. A grid so the scale sits beside the plot and the
   dates under it, without either overlapping the line. */
.chart { display: grid; grid-template-columns: auto 1fr;
         column-gap: 0.6rem; margin-top: 0.9rem; }
.chart svg { grid-column: 2; }
.scale { grid-column: 1; display: flex; flex-direction: column;
         justify-content: space-between; font-size: 0.7rem; color: var(--dim);
         font-variant-numeric: tabular-nums; text-align: right;
         padding: 0.1rem 0; white-space: nowrap; }
.dates { grid-column: 2; display: flex; justify-content: space-between;
         font-size: 0.7rem; color: var(--dim); margin-top: 0.25rem;
         font-variant-numeric: tabular-nums; }
.wl { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; }
/* A linked symbol still reads as the symbol. Underlined only on hover, because
   twelve underlined rows is a page that looks like a link farm rather than a
   holdings table. */
a.sym { color: inherit; text-decoration: none; border-bottom: 1px dotted var(--line); }
a.sym:hover { border-bottom-color: currentColor; }
/* Whose account a row belongs to. Redundant with the name beside it by design:
   colour is a scanning aid here, never the only thing carrying the fact, so the
   page still reads correctly in monochrome or to a colourblind reader. */
.dot { display: inline-block; width: 0.5rem; height: 0.5rem; border-radius: 50%;
       margin-right: 0.45rem; vertical-align: 0.05rem; flex: none; }
.dot.green  { background: #16a34a; }
.dot.pink   { background: #db2777; }
.dot.blue   { background: #2563eb; }
.dot.yellow { background: #ca8a04; }
.dot.orange { background: #ea580c; }
.dot.purple { background: #7c3aed; }
.dot.grey   { background: #6b7280; }
@media (prefers-color-scheme: dark) {
  .dot.green  { background: #4ade80; }
  .dot.pink   { background: #f472b6; }
  .dot.blue   { background: #60a5fa; }
  .dot.yellow { background: #facc15; }
  .dot.orange { background: #fb923c; }
  .dot.purple { background: #a78bfa; }
  .dot.grey   { background: #9ca3af; }
}
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


def _brief_money(value: float) -> str:
    """
    An axis label: whole dollars, grouped, no cents.

    Cents on an axis are noise -- the point of the label is the order of
    magnitude the line is drawn against, and a chart spanning tens of
    thousands does not become clearer for two more digits.
    :param value: The amount
    :return: The label
    :rtype: str
    """

    return f"${value:,.0f}"


def logo() -> str:
    """
    The StonkSmith mark, inlined.

    Read from the package rather than embedded as a string constant here, so
    the README and the brief render the same file and there is no second copy
    to drift. Inlined rather than referenced, because a brief is one
    self-contained file that has to render from a `file://` URL with no server
    and no assets beside it -- an `<img src>` would be a broken icon the moment
    the page were moved or mailed.

    Returns "" on any failure. A missing mark costs the page its badge; it must
    not cost the page.
    :return: The SVG markup, or "" when it cannot be read
    :rtype: str
    """

    from stonksmith.etc.paths import etc_path

    try:
        mark: str = (etc_path / "logo.svg").read_text(encoding="utf-8")

    # UnicodeDecodeError as well as OSError. It is a ValueError, not an OSError,
    # so a logo file that is not valid UTF-8 -- truncated, or replaced with a
    # PNG that kept the name -- escaped this handler and took the whole morning
    # brief down for a decorative asset.
    except OSError, UnicodeDecodeError:
        return ""

    # The file carries its own 128x128 so it renders standalone on GitHub. Here
    # the CSS decides the size, and leaving those attributes in would win
    # against it.
    mark = re.sub(pattern=r'\s(?:width|height)="128"', repl="", string=mark, count=2)
    mark = re.sub(pattern=r"<!--.*?-->", repl="", string=mark, flags=re.S)

    # Decorative here, and hidden from the accessibility tree accordingly. The
    # file names itself -- role="img", an aria-label and a <title> -- which is
    # right on GitHub where the mark stands alone, and wrong beside the word
    # "StonkSmith": a screen reader would announce the name twice and read the
    # heading as "StonkSmith StonkSmith morning brief".
    mark = re.sub(pattern=r"<title>.*?</title>", repl="", string=mark, flags=re.S)
    mark = re.sub(pattern=r'\s(?:role|aria-label)="[^"]*"', repl="", string=mark)
    mark = re.sub(pattern=r"\s*\n\s*", repl="", string=mark)

    return mark.replace("<svg ", '<svg class="mark" aria-hidden="true" ', 1)


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

    # Labelled in HTML around the SVG rather than with <text> inside it. The
    # chart is drawn with preserveAspectRatio="none" so it can stretch to the
    # page width, and anything inside it stretches too -- a value label would
    # come out horizontally smeared by however wide the reader's window is.
    #
    # Unlabelled, this was a line with no scale on either axis: it showed that
    # something rose without saying from what, to what, or over how long, which
    # is a shape rather than a chart. The four corners now carry the range it is
    # actually drawn against.
    first: str = series[0][0]
    last: str = series[-1][0]

    return (
        f'<div class="chart">'
        f'<div class="scale">'
        f"<span>{escape(s=_brief_money(value=high))}</span>"
        f"<span>{escape(s=_brief_money(value=low))}</span>"
        f"</div>"
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" width="100%" '
        f'height="{CHART_HEIGHT}" preserveAspectRatio="none" role="img" '
        f'aria-label="Portfolio value from {escape(s=_brief_money(value=low))} '
        f"to {escape(s=_brief_money(value=high))} between {escape(s=first)} "
        f'and {escape(s=last)}, over {len(series)} readings">'
        f'<polygon points="{area}" fill="var(--accent)" opacity="0.12"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--accent)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"/>{dots}</svg>'
        f'<div class="dates"><span>{escape(s=first)}</span>'
        f"<span>{escape(s=last)}</span></div>"
        f"</div>"
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


def _fee_note(money_of: Performance) -> str:
    """
    What the fee figure stands on, and the two ways it can stand on nothing.

    Three cases rather than two, because the obvious pair conflates them. A
    portfolio where nothing has a declared ratio and one where the declared
    holdings are worth zero produce the same missing rate, and saying "no
    holding has a declared expense ratio" in the second contradicts the count
    the tile is already carrying.
    :param money_of: The portfolio summary
    :return: The line under the figure
    :rtype: str
    """

    if not money_of.fee_over:
        return "no holding has a declared expense ratio"

    if money_of.fee_ratio is None:
        # Declared, and worth nothing to charge a rate on. Rare, and the reason
        # it is stated rather than folded into the case above: the count and the
        # sentence must not disagree.
        return (
            f"across {money_of.fee_over} of {money_of.holdings} positions, "
            "which are worth nothing to charge a rate against"
        )

    return (
        f"a year at {money_of.fee_ratio:.3f}% of "
        + money(value=money_of.fee_value, currency=money_of.currency)
        + f", across {money_of.fee_over} of {money_of.holdings} positions"
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

    # Indicated rather than received, because received is $0 on a workspace
    # whose brokers do not itemise dividends -- and a tile reading zero every
    # morning is one nobody looks at. The received figure rides underneath, so
    # the two are never conflated: one is a forecast of a year at the current
    # positions, the other is money that arrived.
    forecast: str = (
        money(value=money_of.indicated_income, currency=money_of.currency)
        if money_of.indicated_over
        else "—"
    )
    over: str = (
        f"a year at today's holdings, across {money_of.indicated_over} of "
        f"{money_of.holdings} positions"
        if money_of.indicated_over
        else "no holding has a published dividend"
    )
    received: str = (
        f"; {money(value=money_of.dividend_income, currency=money_of.currency)} "
        "received in the log"
        if money_of.dividends_seen
        else "; nothing received in the log yet"
    )

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
    # Says how many are *shown* when they differ, because they routinely do:
    # a cash sweep of eight cents is a real holding and is filtered out of the
    # table by min_position. A reader who counts the rows and finds one fewer
    # than this number is owed the reconciliation here, next to the figure
    # that raised it, rather than in a note under the table.
    holds: str = f"{money_of.holdings} holdings"

    shown: int = len(brief.positions)

    if shown != money_of.holdings:
        # No truthiness guard on `shown`. Zero is the case that most needs
        # saying: every position filtered out leaves a count above an empty
        # table, which reads as data that failed to load rather than as a
        # deliberate floor. The largest discrepancy was the one being skipped.
        holds = f"{money_of.holdings} holdings, {shown} shown below"

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
                caption='Indicated Income',
                figure=forecast,
                sub=over + received,
            )
        }"
        f"{
            _tile(
                caption='Indicated Yield',
                # A dash rather than 0.00% when nothing was found. A yield of
                # zero is a claim about the holdings; no dividend rows at all is
                # a claim about the log, and the tile beside this one is already
                # making the second.
                figure=(
                    percent(value=money_of.indicated_yield).lstrip('+') or '—'
                    if money_of.indicated_over
                    else '—'
                ),
                sub=(
                    'over '
                    + money(value=money_of.indicated_value, currency=money_of.currency)
                    + ' of holdings with a published dividend'
                    if money_of.indicated_over
                    else 'nothing to compute it from'
                ),
            )
        }"
        f"{
            _tile(
                caption='Fund Fees',
                # The money, not the rate, as the figure. A rate of 0.08% reads
                # as nothing; the same fact as an annual sum in dollars is a
                # number somebody can weigh against what it buys.
                figure=(
                    money(value=money_of.fee_cost, currency=money_of.currency)
                    if money_of.fee_over
                    else '—'
                ),
                sub=_fee_note(money_of=money_of),
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
    :param dropped: How many moved but did not fit under the ``[BRIEF] movers``
        cap, counted by build_brief rather than derived here -- ``moves`` has
        already been truncated by the time it arrives, so this is the only way
        the table can know it is not the whole list. Zero renders no line at all,
        which is every ordinary morning
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
        f'{_owner_dot(color=move.color)}<span class="who">{escape(s=move.label)}</span>'
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


def _symbol(row: Position) -> str:
    """
    A holding's symbol, linked to its quote page where it has one.

    Plain text otherwise, and that is most of the interesting cases: a 401k fund
    code, a 529 portfolio number and a TSP fund are real holdings with nothing
    public to point at. An unlinked symbol looks exactly like an unlinkable one,
    which is true and is better than a link that 404s -- a reader has to click
    the second to learn it was worthless.

    The href is escaped like everything else here, though the value cannot carry
    anything to escape: etc.brief only builds a URL from one to five ASCII
    letters, and etc.config refuses a template that is not https. Escaped anyway,
    because "the input is already constrained" is the sentence that precedes
    every injection.
    :param row: The position
    :return: The symbol, linked or not
    :rtype: str
    """

    name: str = escape(s=row.symbol)

    if not row.url:
        return f'<span class="who">{name}</span>'

    return (
        f'<a class="sym who" href="{escape(s=row.url)}" '
        f'target="_blank" rel="noopener noreferrer">{name}</a>'
    )


def _owner_dot(color: str) -> str:
    """
    The dot that says whose account a row is.

    Empty for a row nothing claimed, rather than a default colour: a dot on an
    account with no owner declared reads as an owner the reader has forgotten,
    not as a config line they have not written.

    The colour is validated in etc.config against a closed set before it reaches
    here, which is what makes interpolating it into a class attribute safe -- a
    config file is not a stylesheet, and this value comes from one.
    :param color: A colour name, or ""
    :return: The dot, or ""
    :rtype: str
    """

    if not color:
        return ""

    return f'<span class="dot {escape(s=color)}"></span>'


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


def _hidden(count: int) -> str:
    """
    The line saying how many positions were too small to show.
    :param count: How many were hidden
    :return: The line, or ""
    :rtype: str
    """

    if count <= 0:
        return ""

    held: str = "position" if count == 1 else "positions"

    return (
        f'<p class="note">{count} smaller {held} not shown, '
        f"and still counted in every total above.</p>"
    )


def _units_of(value: float | None) -> str:
    """
    A share count, at the precision a fractional-share world needs.
    :param value: The count
    :return: The rendered count, or a dash
    :rtype: str
    """

    return "—" if value is None else f"{value:,.3f}"


def _holdings(rows: Iterable[Position], hidden: int = 0) -> str:
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
    :param hidden: How many were held but too small to earn a row, stated under
        the table -- they are still in every total, so this is the only place a
        reader would learn the table is not the whole book
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
        f"{_owner_dot(color=row.color)}{_symbol(row=row)}"
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
        f"{body}</table></div>{_hidden(count=hidden)}</section>"
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


def _allocation(rows: Iterable[Allocation], focus: Concentration, band: float) -> str:
    """
    The asset-class breakdown, with what each slice was before.
    :param rows: The breakdown, largest first
    :param focus: The largest single position and account
    :param band: How far a class may sit from target unremarked
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
        f'<td class="num">{_target(entry=entry)}</td>'
        f'<td class="num">{_off(entry=entry, band=band)}</td>'
        f'<td class="num">{_drift(entry=entry)}</td></tr>'
        for entry in classes
    )

    return (
        f"<section><h2>Allocation</h2><table>"
        f'<tr><th>Class</th><th class="num">Value</th>'
        f'<th class="num">Share</th><th class="num">Target</th>'
        f'<th class="num">Off target</th><th class="num">Drift</th></tr>'
        f"{body}</table>{_concentration(entry=focus)}</section>"
    )


def _target(entry: Allocation) -> str:
    """
    The share a class is meant to hold.
    :param entry: The class
    :return: The target, or a dash where none was declared
    :rtype: str
    """

    return "—" if entry.target is None else f"{entry.target:.0f}%"


def _off(entry: Allocation, band: float) -> str:
    """
    How far a class sits from its target, and whether that is worth saying.

    Stated as a distance, never as an instruction. What to do about a gap is a
    decision this page has no business making; what it can do is measure one.

    Outside the band the figure is marked, and the mark is a word rather than a
    colour alone -- "off" reads the same to somebody who cannot distinguish the
    two tones this page would otherwise rely on.
    :param entry: The class
    :param band: How many points a class may sit from target unremarked
    :return: The gap in percentage points, or a dash
    :rtype: str
    """

    if entry.off is None:
        return "—"

    if abs(entry.off) <= band:
        return f'<span class="flat">{entry.off:+.1f} pp</span>'

    tone: str = "up" if entry.off > 0 else "down"

    return f'<span class="{tone}">{entry.off:+.1f} pp <b class="wl">OFF</b></span>'


def _concentration(entry: Concentration) -> str:
    """
    What share of the money rides on one position and one account.

    Under the class table on purpose: a breakdown that looks evenly split can
    still have most of its money in a single fund, and a reader who has just
    read the classes is exactly the reader about to conclude otherwise.
    :param entry: The two largest
    :return: The line, or "" when there is nothing to rank
    :rtype: str
    """

    if not entry.holding and not entry.account:
        return ""

    parts: list[str] = []

    if entry.holding:
        parts.append(
            f"{entry.holding_share * 100:.1f}% of the positions is "
            f"{escape(s=entry.holding)}"
        )

    if entry.account:
        parts.append(
            f"{entry.account_share * 100:.1f}% of the money is in "
            f"{escape(s=entry.account)}"
        )

    return f'<p class="note">{"; ".join(parts)}.</p>'


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
        _holdings(rows=brief.positions, hidden=brief.positions_hidden),
        _transactions(rows=brief.new_transactions),
        _allocation(
            rows=brief.allocation,
            focus=brief.concentration,
            band=get_drift_band(),
        ),
        _stale(rows=brief.stale),
    ]

    stamp: str = now.strftime("%A %d %B %Y, %H:%M")
    title: str = escape(s=brief.as_of or "no readings")
    brand: str = logo()

    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>StonkSmith — {title}</title>"
        f"<style>{STYLE}</style></head><body><main>"
        f"<h1>{brand}StonkSmith · morning brief</h1>"
        f"{''.join(part for part in body if part)}"
        f"<footer>Rendered {escape(s=stamp)} from the databases, "
        f"not from a broker.</footer>"
        f"</main></body></html>"
    )

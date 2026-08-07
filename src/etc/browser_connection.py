# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Base class for brokers that scrape through a real browser.

StonkSmith has three broker shapes, not two. ``Connection`` covers a site that
answers ``requests`` -- Schwab529 posts a form and reads the response.
``ApiConnection`` covers a broker with no login at all. Between them sits the
one that needs an actual browser: a login guarded by bot detection, a session
worth keeping between runs, and a page that only exists after JavaScript has
run.

Fidelity was the first of those and, for a while, the only one, so all of it
lived in ``brokers/fidelity/broker.py``. None of the following is about
Fidelity:

* starting Firefox against a saved ``storage_state``, or a Chromium-family
  browser against a persistent profile directory
* attaching over CDP to a browser the operator started and signed into
  themselves, and never closing a window StonkSmith did not open
* writing the session back on the way out, so a device-trust cookie survives
  and the next run is a returning browser rather than a new one
* capturing the page when a selector breaks, chmod 0600, because that markup is
  a signed-in brokerage session

Ally needs every one of those and shares none of Fidelity's URLs, markers or
2FA flow. Copying the file would mean two divergent copies of the CDP-attach
reasoning, which is subtle enough that the comments explaining it are load
bearing -- ``attached`` is set before validation specifically so an error path
cannot close the operator's window, and that is the kind of detail a second
copy loses.

What a subclass owes this class:

* ``profile_name`` and ``browser_slug``, which name its files
* ``login_url``, used by the reachability preflight and in the CDP hint
* a ``login()`` that knows what an authenticated page looks like

What it inherits is everything above, plus ``create_conn_obj()`` and
``teardown()`` already wired into ``broker_flow()``.
"""

import contextlib
import json
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Response as PlaywrightResponse,
)
from playwright_stealth import Stealth
from requests import Response
from requests.exceptions import RequestException

from etc.connection import Connection
from etc.paths import logs_path, playwright_path

#: Playwright raises TargetClosedError when the browser goes away mid-call, but
#: that class is not exported from playwright.sync_api -- only from a private
#: module. It subclasses the public Error, so it is identified by message.
BROWSER_CLOSED_TEXT = "has been closed"

#: A response at or above this status is worth reporting when a page comes up
#: empty. 4xx and 5xx only: the redirects below it are how single-page apps
#: normally hand a session around.
FAILED_RESPONSE_FLOOR = 400

#: How many distinct failures to report. A blocked page can fail dozens of
#: requests for one reason, and the first few name it.
FAILED_RESPONSE_LIMIT = 12

#: Request types a single-page app uses to fetch its data, as opposed to the
#: scripts and images that make up its shell. A shell that loads while none of
#: these run is a different bug from one whose data calls all come back empty.
DATA_RESOURCE_TYPES = frozenset({"xhr", "fetch"})

#: How many distinct data-call lines to report. Set high on purpose. The first
#: version capped this at 20 and hid the finding it existed to produce: a failed
#: session check made 22 calls, the page that worked made 66, the first 20 were
#: identical, and the entire difference sat inside "... and 46 more".
#:
#: A line is a status, a redacted endpoint and a size, so one endpoint answering
#: at two sizes is two lines -- deliberately, since that comparison is the point.
#: Identical repeats still collapse, which is what keeps a polled endpoint from
#: filling the log.
DATA_RESPONSE_LIMIT = 100

#: Path segments at least this long are account ids, session ids or tokens
#: rather than route names, and are masked before anything is logged.
ID_SEGMENT_LENGTH = 20

#: Largest refused response worth opening. An error body is a sentence and a
#: code; anything larger is a page or a payload and is not read.
ERROR_BODY_LIMIT = 4096

#: What a machine-readable reason looks like: SESSION_EXPIRED, INVALID_TOKEN,
#: DEVICE_NOT_RECOGNIZED. Values matching this are quoted; everything else in
#: the body is described by its key alone and never printed, because a refusal
#: can carry a name, an email or a masked account beside its reason.
REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{2,40}$")

#: A refusal that answers with somewhere to go is describing the fix. Ally's
#: invest session check refuses a restored session with a 49-byte body holding
#: one key, redirectUrl, and where it points is the whole question -- so these
#: are reported, through the same redaction as any other URL.
REDIRECT_VALUE = re.compile(r"^https?://", re.IGNORECASE)

#: --browser values mapped to Playwright channels. "chromium" is the bundled
#: build; "chrome" is the real Google Chrome binary, which fingerprints much
#: better but has to be installed separately.
CHROMIUM_CHANNELS: dict[str, str | None] = {
    "chromium": None,
    "chrome": "chrome",
}

#: Default CDP endpoint. Chrome must be started with --remote-debugging-port,
#: and since Chrome 136 it refuses to expose that on the default profile, so a
#: dedicated --user-data-dir is required too.
CDP_DEFAULT_URL = "http://127.0.0.1:9222"

#: Where the CDP profile lives when StonkSmith prints the launch command.
CDP_PROFILE_DIRNAME = "cdp-profile"


def browser_was_closed(error: Exception) -> bool:
    """
    Whether a Playwright error means the browser went away.
    :param error: The raised Playwright error
    :return: True when the target was closed
    :rtype: bool
    """

    return BROWSER_CLOSED_TEXT in str(object=error)


def endpoint_of(url: str) -> str:
    """
    A URL reduced to something safe to log and useful to compare.

    Two things are dropped. The query string, because Ally's query strings
    carry the jwt and the account id and these lines are meant to be pasted
    into an issue. And any path segment long enough to be an id rather than a
    route name, both for the same reason and so that twenty polls of one
    endpoint under twenty account ids collapse to one line instead of filling
    the log.
    :param url: The full request URL
    :return: scheme://host/path with long segments masked
    :rtype: str
    """

    split = urlparse(url=url)
    segments: list[str] = [
        "<id>" if len(segment) >= ID_SEGMENT_LENGTH else segment
        for segment in split.path.split(sep="/")
    ]

    return f"{split.scheme}://{split.netloc}{'/'.join(segments)}"


def size_suffix(response: PlaywrightResponse) -> str:
    """
    How big the response was, when the site says so.

    A 200 is not evidence the call returned anything. Ally's session check and
    its account list both answer 200 to a session that renders nothing, so the
    status alone cannot separate "the site accepted this session" from "the
    site accepted it and handed back nobody" -- but four hundred bytes against
    forty can.

    Read from the content-length header rather than by fetching the body. The
    body would mean account numbers and balances in a log, and reading it
    inside a response handler stalls on the streaming endpoints Ally polls.
    :param response: The Playwright response
    :return: " (N bytes)", or "" when the header is absent or not a number
    :rtype: str
    """

    # Best-effort: a header read on a response whose page has gone away must
    # not take the diagnostic down with it.
    try:
        length: str | None = response.header_value(name="content-length")

    except Exception:
        return ""

    if length is None:
        return ""

    # int() rather than isdigit(), which rejects the surrounding whitespace a
    # header is allowed to carry.
    try:
        size = int(length.strip())

    except ValueError:
        return ""

    return f" ({size} bytes)"


def error_shape(response: PlaywrightResponse) -> str:
    """
    Why a refused request was refused, without printing what it refused.

    A 401 is a fact; the reason inside it is the diagnosis. Ally answers a
    restored session with 401 on the bank's auth endpoint and then falls back
    to an anonymous one, and whether that 401 says the session expired or the
    device is unrecognised decides whether there is anything to fix.

    Only keys are printed, plus values that look like machine-readable codes.
    A refusal can carry a name, an email or a masked account number beside its
    reason, and none of that belongs in a log meant to be pasted into an issue.

    Read only for refused responses, only when the body is small enough to be
    an error rather than a page, and never for the streaming endpoints -- a
    body read inside a response handler blocks until the response completes.
    :param response: The Playwright response
    :return: " {keys: a, b | codes: SESSION_EXPIRED}", or "" when unreadable
    :rtype: str
    """

    if response.status < FAILED_RESPONSE_FLOOR:
        return ""

    try:
        kind: str | None = response.header_value(name="content-type")
        length: str | None = response.header_value(name="content-length")

        if kind is None or "json" not in kind.lower():
            return ""

        if length is None or not length.strip().isdigit():
            return ""

        if int(length.strip()) > ERROR_BODY_LIMIT:
            return ""

        payload: object = json.loads(s=response.body())

    except Exception:
        # Best-effort throughout: an unreadable refusal is still worth its
        # status line, and nothing here may raise out of an event handler.
        return ""

    if not isinstance(payload, dict):
        return ""

    keys: list[str] = [str(object=k) for k in payload]
    codes: list[str] = []
    targets: list[str] = []

    for value in payload.values():
        if not isinstance(value, str):
            continue

        if REASON_CODE.match(string=value):
            codes.append(value)

        # Through endpoint_of, not raw: a handoff URL carries its token in the
        # query, and where it points is answered by the host and path alone.
        elif REDIRECT_VALUE.match(string=value):
            targets.append(endpoint_of(url=value))

    parts: list[str] = [f"keys: {', '.join(keys)}"] if keys else []

    if codes:
        parts.append(f"codes: {', '.join(codes)}")

    if targets:
        parts.append(f"points to: {', '.join(targets)}")

    return f" {{{' | '.join(parts)}}}" if parts else ""


def restrict(path: Path) -> None:
    """
    Make a captured file owner-readable only.

    Captures are raw markup from a signed-in brokerage session and can contain
    account numbers, balances, and 2FA context. Default permissions follow the
    process umask, which is commonly world-readable.
    :param path: The file to restrict
    """

    # Best-effort: a filesystem without POSIX permissions must not turn a
    # diagnostic capture into a failure.
    with contextlib.suppress(OSError):
        path.chmod(mode=0o600)


class BrowserConnection(Connection):
    """
    A broker whose login needs a real browser.

    Subclasses set the two names below and implement their own ``login()``.
    Everything to do with starting, attaching to, persisting and tearing down a
    browser is handled here.
    """

    #: Stem for the storage-state and trace files under ~/.stonksmith/playwright.
    #: Capitalized where a broker already shipped it that way: changing it
    #: orphans the saved session and silently costs the operator their
    #: device-trust cookie.
    profile_name: ClassVar[str] = "browser"

    #: Prefix for page captures under the logs directory, and for the trace
    #: name. Lowercase, because it ends up in a filename next to a timestamp.
    browser_slug: ClassVar[str] = "browser"

    def __init__(self) -> None:
        super().__init__()
        self.login_url: str = ""
        self.profile_path: Path = playwright_path / f"{self.profile_name}.json"
        self.trace_path: Path = playwright_path / f"{self.profile_name}_trace.zip"

        # Leave language/user-agent/vendor untouched so the session looks like
        # the real browser. playwright-stealth 2.x keeps a default *_override
        # for each of these and warns when the evasion is disabled while its
        # override is still set; the override is unused in that case, and the
        # library types it as non-Optional, so the warning is what gets muted.
        with warnings.catch_warnings():
            warnings.filterwarnings(action="ignore", message=".*_override.*")
            self.stealth = Stealth(
                navigator_languages=False,
                navigator_user_agent=False,
                navigator_vendor=False,
            )

        # The browser is NOT started here. Launching it from __init__ meant that
        # even `--list-modules` spawned one, and the instance had no owner
        # responsible for closing it. broker_flow() starts it instead, and
        # teardown() always closes it.
        #
        # True once a Chromium-family persistent profile is in use: that
        # directory holds the cookies, so no storage_state file is written.
        self.persistent_profile: bool = False
        # True when attached to a browser somebody else started. Nothing we did
        # not create gets closed.
        self.attached: bool = False
        self.tracing_started: bool = False
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

        # Filled by watch_responses(), reported by capture_page(). A saved
        # page says what rendered; these say what the page asked for and what
        # came back, which is the difference between markup that moved, a
        # request that was refused, and a call that was never made.
        self.failed_responses: list[str] = []
        self.data_responses: list[str] = []

        # Endpoint -> the distinct "status (size)" answers it gave. One run
        # holds a session the site would not render for and, after a manual
        # sign-in, one it would; this is what an endpoint answered in each.
        self.endpoint_answers: dict[str, list[str]] = {}
        self.watching_responses: bool = False

    def create_conn_obj(self) -> bool:
        """
        Check the site answers, then start the browser.

        The plain HTTP preflight is cheap and separates "the site is down or
        unreachable" from "the browser would not start", which otherwise arrive
        as the same opaque failure several seconds later.
        :return: True when the browser is ready
        :rtype: bool
        """

        try:
            response: Response = self.session.get(url=self.login_url, timeout=10)

            if not response.ok:
                # broker_flow() does not log a generic connection failure, so
                # this path has to report itself.
                self.logger.fail(
                    msg=(
                        f"{self.broker} sign-in page returned HTTP "
                        f"{response.status_code}."
                    )
                )
                return False

        except RequestException as e:
            self.logger.fail(msg=f"Could not connect to {self.broker}: {e}")
            return False

        try:
            self.getDriver()

        except Exception as e:
            self.logger.fail(msg=f"Could not start browser for {self.broker}: {e}")
            self.teardown()
            return False

        return True

    def getDriver(self) -> None:
        """
        Start or attach to a browser, then apply stealth to the live page.
        :raises RuntimeError: on an unknown --browser, or no resulting context
        """

        self.playwright = sync_playwright().start()

        # --headed exists so the login flow (and its 2FA prompt) can be
        # watched. --manual-login requires it: nobody can sign in to a window
        # they cannot see.
        headed: bool = bool(
            getattr(self.args, "headed", False)
            or getattr(self.args, "manual_login", False)
        )
        browser_name: str = str(object=getattr(self.args, "browser", "firefox"))

        if browser_name == "firefox":
            self.start_firefox(headed=headed)

        elif browser_name == "cdp":
            self.attach_over_cdp()

        elif browser_name in CHROMIUM_CHANNELS:
            self.start_chromium(headed=headed, channel=CHROMIUM_CHANNELS[browser_name])

        else:
            # argparse choices cover the CLI, but a stale config or a
            # programmatic caller deserves a message, not a KeyError.
            known: str = ", ".join(["firefox", "cdp", *CHROMIUM_CHANNELS])
            raise RuntimeError(
                f"Unknown browser {browser_name!r}; choose one of: {known}"
            )

        if self.context is None:
            raise RuntimeError(f"{browser_name} did not produce a browser context")

        try:
            self.context.tracing.start(
                name=f"{self.browser_slug}_trace", screenshots=True, snapshots=True
            )

        except PlaywrightError as e:
            # Tracing is a diagnostic, not a requirement, and a context we
            # attached to rather than created may not support it.
            self.tracing_started = False
            self.logger.highlight(msg=f"Tracing unavailable: {e}")

        else:
            self.tracing_started = True

        self.stealth.apply_stealth_sync(self.active_page)

    def start_firefox(self, headed: bool) -> None:
        """
        Launch bundled Firefox with the saved storage state.
        :param headed: Whether to show the window
        """

        if not self.profile_path.exists():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(
                file=str(object=self.profile_path), mode="w", encoding="utf-8"
            ) as f:
                json.dump(obj={}, fp=f)

        assert self.playwright is not None
        self.browser = self.playwright.firefox.launch(
            headless=not headed,
            args=["--disable-webgl", "--disable-software-rasterizer"],
        )

        self.context = self.browser.new_context(storage_state=self.profile_path)
        self.page = self.context.new_page()

    def start_chromium(self, headed: bool, channel: str | None) -> None:
        """
        Launch a Chromium-family browser against a persistent profile
        directory.

        A persistent profile keeps cookies, history and local storage on disk
        between runs, so the browser presents as one that has been used before
        rather than a fresh install. ``channel="chrome"`` uses the real Google
        Chrome binary, which fingerprints far better than bundled Chromium --
        but it has to be installed.
        :param headed: Whether to show the window
        :param channel: Playwright browser channel, or None for bundled Chromium
        :raises RuntimeError: if the requested channel is not installed
        """

        profile_dir: Path = self.chrome_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)

        assert self.playwright is not None

        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(object=profile_dir),
                channel=channel,
                headless=not headed,
                # The single most-checked automation tell.
                args=["--disable-blink-features=AutomationControlled"],
            )

        except PlaywrightError as e:
            # Playwright words this two ways: "Executable doesn't exist at ..."
            # for a bundled build, "Chromium distribution 'chrome' is not found
            # at ..." for a channel. Both then suggest `playwright install`.
            if not any(
                phrase in str(object=e).lower()
                for phrase in ("executable doesn't exist", "is not found at")
            ):
                raise

            # Playwright downloads browsers separately, and `playwright install
            # firefox` does not bring Chromium along. Name the exact command.
            install: str = "chrome" if channel else "chromium"
            raise RuntimeError(
                f"The {install} browser is not installed. Run "
                f"`uv run playwright install {install}` and try again"
                + (
                    ", or pass --browser chromium to use the bundled build."
                    if channel
                    else "."
                )
            ) from e

        # A persistent context owns its browser; there is no separate handle.
        self.browser = None
        self.persistent_profile = True
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )

    def attach_over_cdp(self) -> None:
        """
        Attach to a browser the operator started and signed into themselves.

        Bot protection refuses the login page to a browser that automation
        launched, before any credentials are entered. Attaching instead of
        launching sidesteps that: the page load and the sign-in happen in an
        ordinary browsing session, and StonkSmith only connects afterwards to
        read the DOM.
        :raises RuntimeError: if nothing is listening, or no context is open
        """

        endpoint: str = str(
            object=getattr(self.args, "cdp_url", None) or CDP_DEFAULT_URL
        )

        assert self.playwright is not None

        try:
            self.browser = self.playwright.chromium.connect_over_cdp(endpoint)

        except Exception as e:
            raise RuntimeError(
                f"Nothing is listening for CDP on {endpoint}. Start Chrome with "
                f"remote debugging first:\n\n    {self.cdp_launch_command()}\n\n"
                f"then sign in to {self.broker} in that window and re-run."
            ) from e

        # Set before any further validation. create_conn_obj() calls teardown()
        # when this method raises, and teardown closes self.browser unless it
        # knows the session is attached -- which would shut the operator's
        # window on the error paths below.
        self.attached = True
        # The operator's own profile is the cookie store.
        self.persistent_profile = True

        if not self.browser.contexts:
            raise RuntimeError(
                "Attached, but that Chrome has no open window. Open a tab and "
                f"sign in to {self.broker}, then re-run."
            )

        # Reuse the existing context: it holds the cookies from the operator's
        # sign-in. A new context would start empty and defeat the whole point.
        self.context = self.browser.contexts[0]
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )

    def cdp_launch_command(self) -> str:
        """
        The command that starts Chrome with remote debugging enabled.

        Chrome 136 and later refuse --remote-debugging-port on the default
        profile, so this names a dedicated one. Signing in there once is enough:
        the profile persists.
        :return: A shell command
        :rtype: str
        """

        profile: Path = playwright_path / CDP_PROFILE_DIRNAME
        port: int = (
            urlparse(
                url=str(object=getattr(self.args, "cdp_url", None) or CDP_DEFAULT_URL)
            ).port
            or 9222
        )

        return (
            '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
            f"--remote-debugging-port={port} "
            f'--user-data-dir="{profile}" '
            f'"{self.login_url}"'
        )

    def chrome_profile_dir(self) -> Path:
        """
        Where the persistent Chromium profile lives.

        Defaults to a directory StonkSmith owns. --profile-dir can point at
        another one, including a real browser profile -- at the cost of that
        browser needing to be closed while StonkSmith runs.
        :return: The user-data directory
        :rtype: Path
        """

        override = getattr(self.args, "profile_dir", None)

        if override:
            return Path(override).expanduser()

        return playwright_path / "chrome-profile"

    @property
    def active_page(self) -> Page:
        """
        The live Playwright page, guaranteed non-None.
        :return: The current page
        :rtype: Page
        :raises RuntimeError: if the browser has not been started
        """

        if self.page is None:
            raise RuntimeError(
                "Browser not started: create_conn_obj() must run before login."
            )

        return self.page

    def page_body(self) -> str | None:
        """
        The current page's markup, lowercased.
        :return: The body, or None if the page could not be read
        :rtype: str | None
        """

        try:
            return self.active_page.content().lower()

        except PlaywrightError:
            return None

    def save_session(self) -> bool:
        """
        Persist cookies and local storage so the next run is a returning
        browser rather than a brand-new one.

        A context created from ``storage_state`` does not write the state back
        on its own, so without this every run starts with an empty jar. That
        defeats a "don't ask me again on this device" checkbox -- the trust
        cookie it sets is discarded on exit -- and makes each login look like a
        new device.
        :return: True if the session was written
        :rtype: bool
        """

        if self.context is None:
            return False

        if self.persistent_profile:
            # Cookies already live in the profile directory. Writing
            # storage_state as well would leave a Chromium jar behind that the
            # next Firefox run would load as if it were its own.
            return True

        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            # indexed_db, because cookies and local storage are not the whole
            # session. Ally's saved cookies authenticate fine -- a restored run
            # gets 200 from api/session/checkSession and 759 bytes of real
            # accounts from api/account/get -- and then the page calls
            # auth/logout on itself and renders nobody. What it cannot find is
            # the device Transmit bound the session to, and device-binding SDKs
            # keep that in IndexedDB, the one store storage_state leaves out by
            # default.
            self.context.storage_state(
                path=str(object=self.profile_path), indexed_db=True
            )
            # Session cookies: owner-readable only.
            restrict(path=self.profile_path)

        except Exception as e:
            self.logger.fail(msg=f"Could not save the browser session: {e}")
            return False

        return True

    def watch_responses(self) -> None:
        """
        Start recording what the page asked for and what came back.

        A saved page answers "what rendered". It cannot answer "why nothing
        did", because a single-page app that is signed out, blocked by a bot
        filter, or pointed at an account it cannot see all render the same
        empty shell -- the difference is in the XHRs behind it, which never
        reach the markup.

        Two lists, because "nothing was refused" turned out not to be an
        answer on its own. A shell that renders while its data calls come back
        200-and-empty is a session the site accepts but treats as nobody; a
        shell that renders having made no data calls at all is a router or a
        guard that never ran. Both show zero failures, need opposite fixes, and
        are told apart only by whether the calls happened.

        Installs once per page. See ``endpoint_of()`` for what is dropped
        before anything is recorded.
        :return: None
        :rtype: None
        """

        if self.watching_responses or self.page is None:
            return

        def note(response: PlaywrightResponse) -> None:
            endpoint: str = endpoint_of(url=response.url)

            # Deduplicated: one endpoint retried twenty times is one fact, and
            # the retries would push everything else off the end.
            if response.status >= FAILED_RESPONSE_FLOOR:
                line: str = (
                    f"{response.status} {endpoint}"
                    f"{size_suffix(response=response)}"
                    f"{error_shape(response=response)}"
                )
                if line not in self.failed_responses:
                    self.failed_responses.append(line)

            # Scripts, styles and images are the shell arriving; they say
            # nothing about whether the app went looking for data.
            if response.request.resource_type in DATA_RESOURCE_TYPES:
                answer: str = f"{response.status}{size_suffix(response=response)}"
                call: str = (
                    f"{response.status} {endpoint}{size_suffix(response=response)}"
                )

                if call not in self.data_responses:
                    self.data_responses.append(call)

                seen: list[str] = self.endpoint_answers.setdefault(endpoint, [])
                if answer not in seen:
                    seen.append(answer)

        self.page.on("response", note)
        self.watching_responses = True

    def report_responses(self) -> None:
        """
        Log whatever ``watch_responses()`` collected.

        Both halves are reported even when empty, and the empty cases are
        stated rather than left as silence: "nothing was refused" and "nothing
        was asked for" are findings, and a blank log reads as a diagnostic that
        was never wired up.
        :return: None
        :rtype: None
        """

        if not self.watching_responses:
            return

        self._report_lines(
            lines=self.failed_responses,
            limit=FAILED_RESPONSE_LIMIT,
            some="request(s) were refused:",
            none="No request failed while the page was loading.",
        )
        self._report_lines(
            lines=self.data_responses,
            limit=DATA_RESPONSE_LIMIT,
            some="data call(s) were made:",
            none="The page made no data calls at all.",
        )

    def report_answer_changes(self) -> None:
        """
        Endpoints that answered differently at different points in the run.

        A run that signs in partway through has held two sessions, and the
        recorder outlives the sign-in, so it saw both. Where a status would
        separate them the failure log already says so; where none of the calls
        fail, the only thing left is what came back -- one endpoint answering
        at two sizes is the site treating the two sessions differently, which
        a page capture cannot show when the markup is identical either way.

        Silent when nothing differs: an endpoint that answered the same
        throughout is not evidence, and listing every call again would bury the
        few that are. See the caller for why a given broker wants this.
        :return: None
        :rtype: None
        """

        changed: dict[str, list[str]] = {
            endpoint: answers
            for endpoint, answers in self.endpoint_answers.items()
            if len(answers) > 1
        }

        if not changed:
            return

        self.logger.fail(
            msg=(
                f"{len(changed)} endpoint(s) answered differently before and "
                f"after signing in:"
            )
        )

        shown: list[tuple[str, list[str]]] = list(changed.items())[:DATA_RESPONSE_LIMIT]

        for endpoint, answers in shown:
            self.logger.fail(msg=f"    {endpoint}")
            self.logger.fail(msg=f"        {' then '.join(answers)}")

        # Truncation that does not announce itself reads as the whole story --
        # which is the exact fault that hid this finding the first time round.
        if len(changed) > len(shown):
            self.logger.fail(msg=f"    ... and {len(changed) - len(shown)} more")

    def _report_lines(self, lines: list[str], limit: int, some: str, none: str) -> None:
        """
        Log one capped, self-describing list of recorded responses.
        :param lines: The recorded lines
        :param limit: How many to print before summarising the rest
        :param some: Headline when there is something to show, after the count
        :param none: The whole message when the list is empty
        :return: None
        :rtype: None
        """

        if not lines:
            self.logger.fail(msg=none)
            return

        shown: list[str] = lines[:limit]
        self.logger.fail(msg=f"{len(lines)} {some}")

        for line in shown:
            self.logger.fail(msg=f"    {line}")

        # Truncation that does not announce itself reads as the whole story.
        if len(lines) > len(shown):
            self.logger.fail(msg=f"    ... and {len(lines) - len(shown)} more")

    def capture_page(self, reason: str) -> Path | None:
        """
        Save the current page so selectors can be fixed against real markup.

        Writes the HTML, and a screenshot when possible, from wherever the run
        got stuck -- including inside the login flow, which a module-level
        diagnostic cannot reach because modules only run *after* a successful
        login.
        :param reason: Short slug describing why the capture happened
        :return: Path to the saved HTML, or None if nothing could be captured
        :rtype: Path | None
        """

        if self.page is None:
            return None

        stamp: str = datetime.now(tz=UTC).strftime(format="%Y%m%d-%H%M%S")
        target: Path = logs_path / f"{self.browser_slug}-{reason}-{stamp}.html"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data=self.active_page.content(), encoding="utf-8")
            restrict(path=target)

        except Exception as e:
            self.logger.fail(msg=f"Could not capture the page: {e}")
            return None

        self.logger.fail(msg=f"Saved the page markup to {target}")

        try:
            shot: Path = target.with_suffix(suffix=".png")
            self.active_page.screenshot(path=str(object=shot))
            restrict(path=shot)
            self.logger.fail(msg=f"Saved a screenshot to {shot}")

        except Exception:
            # A screenshot is a nice-to-have; the HTML is what matters.
            pass

        # Alongside the markup, not instead of it: an empty page, the calls it
        # made, and the ones that came back refused are only diagnostic
        # together -- and the absence of any of the three is itself a reading.
        self.report_responses()

        return target

    def teardown(self) -> None:
        """
        Stop tracing and shut down the browser and Playwright driver.

        Called by Connection.__call__ on every exit path. Without this, each run
        leaves an orphaned browser process and a running Playwright driver.
        """

        if self.context is not None:
            # Save before closing: cookies set during this run (including any
            # device-trust cookie) are lost otherwise.
            self.save_session()

            if self.tracing_started:
                try:
                    self.context.tracing.stop(path=str(object=self.trace_path))

                except Exception as e:
                    self.logger.fail(msg=f"Could not write Playwright trace: {e}")

            # Never close a window the operator opened.
            if not self.attached:
                self.context.close()

            self.context = None

        # A persistent context owns its browser, so self.browser is None there
        # and closing the context above already shut the browser down. An
        # attached browser belongs to the operator: disconnecting happens when
        # playwright stops, and closing it would shut their window.
        if self.browser is not None:
            if not self.attached:
                self.browser.close()

            self.browser = None

        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

        self.page = None

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
from playwright_stealth import Stealth
from requests import Response
from requests.exceptions import RequestException

from etc.connection import Connection
from etc.paths import logs_path, playwright_path

#: Playwright raises TargetClosedError when the browser goes away mid-call, but
#: that class is not exported from playwright.sync_api -- only from a private
#: module. It subclasses the public Error, so it is identified by message.
BROWSER_CLOSED_TEXT = "has been closed"

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
            self.context.storage_state(path=str(object=self.profile_path))
            # Session cookies: owner-readable only.
            restrict(path=self.profile_path)

        except Exception as e:
            self.logger.fail(msg=f"Could not save the browser session: {e}")
            return False

        return True

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

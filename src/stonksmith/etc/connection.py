"""
Attempt connection
"""

import argparse
from argparse import Namespace
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, cast

import requests

from etc.context import BrokerDbProtocol, Context
from etc.logger import StonkSmithAdapter, stonksmith_logger

sem = BoundedSemaphore()
global_failed_logins = 0
user_failed_logins: dict[str, int] = {}


class Connection:
    """
    Initialize empty state. Logic triggered by __call__.
    """

    def __init__(self) -> None:
        # broker/name are overridden by every subclass, but they are defined here
        # so the base class and etc.runner (which reads broker_obj.name) never
        # depend on a subclass remembering to set them.
        self.broker: str = "Unknown"
        self.name: str = "Unknown"
        # CLI flag names this broker allows call_cmd_args() to dispatch to
        # same-named methods. Empty by default: opt in explicitly.
        self.cmd_actions: tuple[str, ...] = ()
        self.module: list[Any] = []
        self.args: Namespace | None = None
        self.db: BrokerDbProtocol | None = None
        self.hostname: str | None = None
        self.password: str = ""
        self.username: str = ""
        self.failed_logins: int = 0
        self.logger: StonkSmithAdapter = stonksmith_logger
        self.session = requests.Session()

    def __call__(
        self, args: Namespace, db: BrokerDbProtocol, host: str | None = None
    ) -> bool:
        """
        Entry point for ThreadPoolExecutor.

        Reports an outcome rather than raising. This is a thread-pool target, so
        an exception is only ever seen by whoever calls ``future.result()`` --
        and the commonest failures, ``create_conn_obj()`` and ``login()``
        returning False, are not exceptions and never will be. Splitting the
        signal across returns and raises would make every caller handle both.
        :param args:
        :param db:
        :param host:
        :return: False when the run produced nothing -- could not connect, could
                 not log in, raised, or a module reported it did no work
        :rtype: bool
        """

        self.args = args
        self.db = db
        self.hostname = host
        ok: bool = True

        try:
            # `is not False`, not `bool(...)`: a broker installed under
            # ~/.stonksmith/brokers may still override broker_flow() with the
            # older `-> None` signature, where None has always meant "finished".
            ok = self.broker_flow() is not False

        except Exception as e:
            self.logger.exception(msg=f"Exception on {host or 'local'}: {e}")
            ok = False

        finally:
            try:
                self.teardown()

            except Exception as e:
                self.logger.exception(msg=f"Teardown failed for {self.broker!r}: {e}")

            self.session.close()

        return ok

    def teardown(self) -> None:
        """
        Release broker-owned resources at the end of a run.

        Subclasses that own external resources (browsers, drivers, sockets)
        must override this. ``__call__`` always invokes it, including on the
        error path.
        """

    @staticmethod
    def broker_args(
        std_parser: argparse.ArgumentParser, module_parser: argparse.ArgumentParser
    ) -> None:
        """
        Passed arguments related to brokerage
        :param std_parser:
        :type std_parser:
        :param module_parser:
        :type module_parser:
        :return:
        :rtype:
        """

        return

    def broker_logger(self) -> None:
        """
        Logger for broker_flow
        """

    def create_conn_obj(self) -> bool:
        """
        Create connection object.

        Implementations that return False must report why -- broker_flow()
        deliberately stays quiet so a specific message is not followed by a
        vaguer duplicate.
        :return: bool
        :rtype:
        """

        return True

    def plaintext_login(self, username: str, password: str) -> bool:
        """
        Attempt plaintext login
        :param username:
        :type username:
        :param password:
        :type password:
        :return: bool
        :rtype:
        """

        return False

    def broker_flow(self) -> bool:
        """
        Brokerage login flow
        :return: True when the run did its work; False when it could not
                 connect, could not log in, or a module reported it did nothing
        :rtype: bool
        """

        self.broker_logger()
        self.logger.highlight(msg="Kicking off broker flow")

        # Previously this was a single `if ... and ...` with no else, so a run
        # that could not connect or could not log in simply ended -- and every
        # progress message here is INFO, which the default log level hides. The
        # result was a run that printed nothing at all.
        #
        # Neither branch logs here: create_conn_obj() and login() each own
        # reporting their own failure, so adding a generic message would print
        # a second, vaguer line for the same problem.
        if not self.create_conn_obj():
            return False

        if not self.login():
            return False

        if self.module:
            return self.call_modules()

        # call_cmd_args() dispatches broker actions rather than running a sync,
        # so there is no per-action outcome to report -- and main() cannot reach
        # this branch anyway, since a run with no --module exits before here.
        self.call_cmd_args()

        return True

    def call_cmd_args(self) -> None:
        """
        Invoke broker actions named by CLI flags.

        Only names a broker explicitly advertises in ``cmd_actions`` are
        dispatched. Previously this called getattr(self, k) for *any* truthy
        argument, so a future flag named e.g. --login or --parse-credentials
        would silently invoke the same-named method.
        :return:
        :rtype:
        """

        allowed: frozenset[str] = frozenset(getattr(self, "cmd_actions", ()))

        if not allowed:
            return

        for k, v in vars(self.args).items():
            if not v or k not in allowed:
                continue

            method = getattr(self, k, None)
            if callable(method):
                self.logger.highlight(msg=f"Calling {k}()")
                method()

    def call_modules(self) -> bool:
        """
        Pass active session to broker module.

        A module says it did nothing by returning ``False``. Anything else --
        including ``None``, which is what every module written before this
        contract returns -- counts as success, so modules installed under
        ~/.stonksmith/modules keep working untouched. Only the exact value
        False is read as failure: a module returning a count of 0 is reporting
        success, not emptiness.
        :return: True when every module did its work
        :rtype: bool
        """

        ok: bool = True

        for module in self.module:
            if self.db is None or self.args is None:
                # Nothing ran, and nothing was said about it. That is a failed
                # run rather than a successful empty one.
                return False

            module_logger = StonkSmithAdapter(
                extra={
                    "module_name": module.name.capitalize(),
                    "host": self.hostname,
                },
                logger=self.logger.logger,
            )

            context = Context(
                db=self.db,
                logger=module_logger,
                args=self.args,
                active_username=self.username or None,
                active_password=self.password or None,
            )
            show_module_markers: bool = bool(
                getattr(self.args, "module_run_markers", False)
            )

            if show_module_markers:
                module_logger.highlight(
                    msg=(
                        f"[*] Running module {getattr(module, 'name', 'unknown')} "
                        f"for {self.username or 'unknown user'}"
                    )
                )

            if hasattr(module, "on_login"):
                module_ok: bool = True

                try:
                    module_ok = module.on_login(context, self) is not False
                except Exception as e:
                    module_logger.exception(
                        msg=(
                            f"Module {getattr(module, 'name', 'unknown')} failed "
                            f"for {self.username or 'unknown user'}: {e}"
                        )
                    )
                    module_ok = False

                # Recorded, not short-circuited: the remaining modules still run.
                ok = ok and module_ok

                if show_module_markers:
                    # This said "[+] Completed" even for a module that had just
                    # raised two lines above it.
                    module_logger.highlight(
                        msg=(
                            f"{'[+] Completed' if module_ok else '[-] Gave up on'} "
                            f"module {getattr(module, 'name', 'unknown')} "
                            f"for {self.username or 'unknown user'}"
                        )
                    )

        return ok

    def inc_failed_logins(self, username: str) -> None:
        """
        Increment failed logins
        :param username:
        :type username:
        :return:
        :rtype:
        """

        global global_failed_logins

        if username not in user_failed_logins:
            user_failed_logins[username] = 0

        user_failed_logins[username] += 1
        global_failed_logins += 1
        self.failed_logins += 1

    def over_fail_limit(self, username: str) -> bool:
        """
        Over the limit of allowed failed logins
        :param username:
        :type username:
        :return:
        :rtype:
        """

        if global_failed_logins >= getattr(self.args, "gfail_limit", 999):
            return True

        if self.failed_logins >= getattr(self.args, "fail_limit", 999):
            return True

        return bool(
            username in user_failed_logins
            and user_failed_logins[username] >= getattr(self.args, "ufail_limit", 999)
        )

    def query_db_creds(
        self,
    ) -> tuple[list[str], list[bool], list[str], list[str], list[None]]:
        """
        Query db credentials
        :return:
        :rtype:
        """

        u: list[str] = []
        o: list[bool] = []
        s: list[str] = []
        t: list[str] = []
        d: list[None] = []
        creds: list[tuple[Any, ...]] = []

        if self.args is None or self.db is None:
            return u, o, s, t, d

        for cred_id in self.args.cred_id:
            if str(object=cred_id).lower() == "all":
                found = self.db.get_credentials()
            else:
                found = self.db.get_credentials(filter_term=(cred_id))

            if not found:
                if str(object=cred_id).lower() == "all":
                    self.logger.fail(msg="No credentials stored in the database.")
                else:
                    self.logger.fail(
                        msg=f"No credential in the database with id {cred_id}"
                    )

            creds.extend(found)

        for cred in creds:
            cred_len: int = len(cred)
            if cred_len < 4:
                self.logger.error(
                    msg=f"Skipping malformed credential row (len={cred_len})"
                )
                continue

            if cred_len > 5:
                self.logger.highlight(
                    msg=(
                        "Credential row contains unexpected extra values "
                        f"(len={cred_len}); truncating to first 5"
                    )
                )

            normalized_cred: tuple[Any, ...] = tuple(cred[:5])

            if not normalized_cred[2]:
                # An empty secret here is a keyring lookup that came back with
                # nothing, not a credential nobody ever stored: the row exists,
                # or there would be no tuple to unpack, and get_credentials()
                # resolves the secret through the keyring and falls back to "".
                #
                # Left to itself the login proceeds with an empty password and
                # the site rejects it, which reads as a wrong password and sends
                # the reader to reset one that is fine. The common cause is
                # context rather than content -- a scheduled run on macOS cannot
                # see the login keychain, so a credential that works by hand
                # resolves to nothing here.
                self.logger.error(
                    msg=(
                        f"Credential id {normalized_cred[0]} "
                        f"({normalized_cred[1]}) resolved to an empty secret; "
                        "the row is stored but the keyring returned nothing, so "
                        "the login below will fail as though the password were "
                        "wrong. If it works by hand and only fails unattended, "
                        "see docs/scheduling.md."
                    )
                )

            u.append(normalized_cred[1])
            o.append(False)
            s.append(normalized_cred[2])
            t.append(normalized_cred[3])
            d.append(None)

        self.logger.highlight(
            msg=(
                "DB creds parsed counts "
                f"u={len(u)} o={len(o)} s={len(s)} t={len(t)} d={len(d)}"
            )
        )
        return u, o, s, t, d

    def parse_credentials(
        self,
    ) -> tuple[list[str], list[bool], list[str], list[str], list[None]]:
        """
        Parse credentials
        :return:
        :rtype:
        """

        u_final: list[str] = []
        s_final: list[str] = []

        if self.args is None:
            return (
                u_final,
                cast(list[bool], []),
                s_final,
                cast(list[str], []),
                cast(list[None], []),
            )

        for user in self.args.username:
            # A value that names a readable file is a list of usernames; one
            # that does not is a username. Path.is_file() answers False for the
            # unreadable and the malformed alike, which is the same answer
            # os.path.isfile gave, so a login name is never mistaken for a path.
            user_file = Path(user)
            if user_file.is_file():
                with user_file.open() as f:
                    u_final.extend([line.strip().split(sep="\\")[-1] for line in f])

            else:
                u_final.append(user.split("\\")[-1])

        for password in self.args.password:
            password_file = Path(password)
            if password_file.is_file():
                with password_file.open() as f:
                    s_final.extend([line.strip() for line in f])

            else:
                s_final.append(password)

        o: list[bool] = [False] * len(u_final)
        t: list[str] = ["plaintext"] * len(s_final)
        self.logger.highlight(
            msg=(
                "CLI creds parsed counts "
                f"u={len(u_final)} o={len(o)} s={len(s_final)} t={len(t)}"
            )
        )
        return u_final, o, s_final, t, [None] * len(s_final)

    def try_credentials(self, username: str, secret: str, cred_type: str) -> bool:
        """
        Try to log in with credentials
        :param username:
        :type username:
        :param secret:
        :type secret:
        :param cred_type:
        :type cred_type:
        :return:
        :rtype:
        """

        if self.over_fail_limit(username=username):
            return False

        with sem:
            if cred_type == "plaintext":
                return self.plaintext_login(username=username, password=secret)
            return False

    def login(self) -> bool:
        """
        Gather credentials and attempt login
        :return:
        :rtype:
        """

        u_list: list[str] = []
        o_list: list[bool] = []
        s_list: list[str] = []
        t_list: list[str] = []

        if getattr(self.args, "cred_id", None):
            u, o, s, t, *extra = self.query_db_creds()
            if extra:
                self.logger.highlight(
                    msg=(
                        f"query_db_creds returned {4 + len(extra)} "
                        "collections; using first 4"
                    )
                )
            u_list.extend(u)
            o_list.extend(o)
            s_list.extend(s)
            t_list.extend(t)

        if getattr(self.args, "username", None):
            u, o, s, t, *extra = self.parse_credentials()
            if extra:
                self.logger.highlight(
                    msg=(
                        f"parse_credentials returned {4 + len(extra)} "
                        "collections; using first 4"
                    )
                )
            u_list.extend(u)
            o_list.extend(o)
            s_list.extend(s)
            t_list.extend(t)

        if not u_list:
            # Reported at fail level deliberately: this is the most common
            # reason a run does nothing, and the INFO-level progress messages
            # above are hidden at the default log level.
            requested = getattr(self.args, "cred_id", None)

            if requested:
                self.logger.fail(
                    msg=(
                        f"No stored credential matched {list(requested)}. Add one "
                        f"with: stonksmithdb -> broker {self.broker.lower()} -> "
                        "add creds <username>"
                    )
                )
            else:
                self.logger.fail(
                    msg=(
                        "No credentials supplied. Pass -u and -p, or store one in "
                        "stonksmithdb and select it with -id."
                    )
                )

            return False

        # Credentials are paired positionally. zip() truncates to the shortest
        # list, so an uneven -u/-p pairing used to drop attempts silently.
        if len(u_list) != len(s_list):
            self.logger.fail(
                msg=(
                    f"Credential count mismatch: {len(u_list)} username(s) but "
                    f"{len(s_list)} secret(s). Only the first "
                    f"{min(len(u_list), len(s_list))} pair(s) will be tried."
                )
            )

        # The second column ("owned") is part of the credential-tuple contract
        # but is always False today, so nothing consumes it.
        attempted = 0
        succeeded = False

        for u, _owned, s, t in zip(u_list, o_list, s_list, t_list, strict=False):
            attempted += 1
            if self.try_credentials(username=u, secret=s, cred_type=t):
                succeeded = True
                self.username = u
                self.password = s
                if not getattr(self.args, "continue_on_success", False):
                    return True

        # With continue_on_success the loop runs to the end even after a
        # success, so the outcome has to be tracked rather than inferred from
        # falling out of the loop.
        if succeeded:
            return True

        self.logger.fail(
            msg=f"Login failed for all {attempted} credential(s) on {self.broker}."
        )
        return False

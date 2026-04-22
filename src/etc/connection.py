"""
Attempt connection
"""

import argparse
from argparse import Namespace
from os.path import isfile
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
    ) -> None:
        """
        Entry point for ThreadPoolExecutor.
        :param args:
        :param db:
        :param host:
        :return:
        """

        self.args = args
        self.db = db
        self.hostname = host

        try:
            self.broker_flow()

        except Exception as e:
            self.logger.exception(msg=f"Exception on {host or 'local'}: {e}")

        finally:
            self.session.close()

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
        Create connection object
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

    def broker_flow(self) -> None:
        """
        Brokerage login flow
        :return:
        :rtype:
        """

        self.broker_logger()
        self.logger.highlight(msg="Kicking off broker flow")
        if self.create_conn_obj() and self.login():
            if self.module:
                self.call_modules()
            else:
                self.call_cmd_args()

    def call_cmd_args(self) -> None:
        """
        Call command arguments
        :return:
        :rtype:
        """

        for k, v in vars(self.args).items():
            method = getattr(self, k, None)
            if v and callable(method):
                self.logger.highlight(msg=f"Calling {k}()")
                method()

    def call_modules(self) -> None:
        """
        Pass active session to broker module
        :return:
        :rtype:
        """

        for module in self.module:
            if self.db is None or self.args is None:
                return

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
                try:
                    module.on_login(context, self)
                except Exception as e:
                    module_logger.exception(
                        msg=(
                            f"Module {getattr(module, 'name', 'unknown')} failed "
                            f"for {self.username or 'unknown user'}: {e}"
                        )
                    )
                if show_module_markers:
                    module_logger.highlight(
                        msg=(
                            f"[+] Completed module {getattr(module, 'name', 'unknown')} "
                            f"for {self.username or 'unknown user'}"
                        )
                    )

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
                creds.extend(self.db.get_credentials())
            else:
                creds.extend(self.db.get_credentials(filter_term=(cred_id)))

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
            if isfile(path=user):
                with open(file=user) as f:
                    u_final.extend([line.strip().split(sep="\\")[-1] for line in f])

            else:
                u_final.append(user.split("\\")[-1])

        for password in self.args.password:
            if isfile(path=password):
                with open(file=password) as f:
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

    def try_credentials(
        self, username: str, owned: bool, secret: str, cred_type: str
    ) -> bool:
        """
        Try to log in with credentials
        :param username:
        :type username:
        :param owned:
        :type owned:
        :param secret:
        :type secret:
        :param cred_type:
        :type cred_type:
        :return:
        :rtype:
        """

        if self.over_fail_limit(username=username):
            return False

        if getattr(self.args, "continue_on_success", False) and owned:
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
                    msg=f"query_db_creds returned {4 + len(extra)} collections; using first 4"
                )
            u_list.extend(u)
            o_list.extend(o)
            s_list.extend(s)
            t_list.extend(t)

        if getattr(self.args, "username", None):
            u, o, s, t, *extra = self.parse_credentials()
            if extra:
                self.logger.highlight(
                    msg=f"parse_credentials returned {4 + len(extra)} collections; using first 4"
                )
            u_list.extend(u)
            o_list.extend(o)
            s_list.extend(s)
            t_list.extend(t)

        if not u_list:
            return False

        for u, o, s, t in zip(u_list, o_list, s_list, t_list):
            if self.try_credentials(username=u, owned=o, secret=s, cred_type=t):
                self.username = u
                self.password = s
                if not getattr(self.args, "continue_on_success", False):
                    return True

        return False

# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""An in-memory keyring, so tests never reach the developer's credential store.

Not named test_*: this is a helper, and pytest collecting it as a test module
would do nothing useful.

Any test that constructs a broker Database needs this, not just the credential
tests. Opening a database runs migrate_plaintext_secrets(), which moves any
legacy plaintext password it finds into whatever keyring is installed -- and on
a developer's machine that is the real one.

CI installs keyring.backends.null.Keyring via PYTHON_KEYRING_BACKEND, which
raises on every call, so tests cannot rely on the ambient backend either.
"""

import keyring
import keyring.backend


class MemoryKeyring(keyring.backend.KeyringBackend):
    """A keyring that keeps secrets in a dict and forgets them at exit."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


class MemoryKeyringMixin:
    """Swap in a memory keyring for the duration of a TestCase."""

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self._previous_keyring = keyring.get_keyring()
        self.memory_keyring = MemoryKeyring()
        keyring.set_keyring(self.memory_keyring)

    def tearDown(self) -> None:
        keyring.set_keyring(self._previous_keyring)
        super().tearDown()  # type: ignore[misc]

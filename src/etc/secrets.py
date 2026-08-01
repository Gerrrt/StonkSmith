# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Keyring-backed storage for broker secrets.

The credentials table stores a *reference* to a secret, never the secret itself.
The secret lives in the operating system's credential store (Keychain on macOS,
Secret Service on Linux, Credential Locker on Windows) and is resolved only at
the moment a login is attempted.
"""

import contextlib

import keyring
import keyring.errors

KEYRING_SERVICE = "stonksmith"


def keyring_key(broker: str, username: str) -> str:
    """
    Build the account key used to look a secret up in the OS keyring.
    :param broker: Broker name, e.g. "schwab529plan"
    :param username: Account username
    :return: The key stored in the ``keyring_key`` column
    """

    return f"{broker}:{username}"


def get_secret(key: str) -> str | None:
    """
    Read a secret out of the OS keyring.
    :param key: A key produced by :func:`keyring_key`
    :return: The secret, or None if the keyring has no entry for it
    """

    if not key:
        return None

    return keyring.get_password(KEYRING_SERVICE, key)


def set_secret(key: str, secret: str) -> None:
    """
    Write a secret into the OS keyring.
    :param key: A key produced by :func:`keyring_key`
    :param secret: The secret to store
    """

    keyring.set_password(KEYRING_SERVICE, key, secret)


def delete_secret(key: str) -> None:
    """
    Remove a secret from the OS keyring, ignoring a missing entry.
    :param key: A key produced by :func:`keyring_key`
    """

    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(KEYRING_SERVICE, key)

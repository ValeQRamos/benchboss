"""Exceptions with messages that are safe to show to the user as-is."""

from __future__ import annotations


class BenchbossError(Exception):
    """Base class: the message is meant for humans and is printed without a traceback."""

    exit_code = 1


class ConfigError(BenchbossError):
    """benchboss is not set up yet, or the config is invalid."""


class AuthError(BenchbossError):
    """Missing, expired or wrong ESPN cookies."""

    exit_code = 3


class EspnError(BenchbossError):
    """ESPN answered with an error status."""

    exit_code = 4

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"ESPN {status}: {message}")


class NetworkError(BenchbossError):
    """ESPN could not be reached."""


class WriteFailed(BenchbossError):
    """ESPN refused some or all of a write."""

    exit_code = 4


class GuardRefused(BenchbossError):
    """A lineup change failed a safety check (core/guard.py), so nothing was sent."""

    exit_code = 5


class NotConfirmed(BenchbossError):
    """A write was prepared but not sent: no --yes and no terminal to ask."""

    exit_code = 10

"""Thread-safe, local-only storage for preview/confirm evidence."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PreviewRecord(Generic[T]):
    value: T
    expires_at: float


class PreviewRegistry(Generic[T]):
    """Store opaque preview evidence without interpreting workflow policy."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._records: dict[str, PreviewRecord[T]] = {}
        self._lock = threading.RLock()

    def add(
        self,
        value: T,
        *,
        expires_at: float,
        capacity: int | None,
        prune_expired: bool = True,
    ) -> str:
        return self.add_factory(
            lambda _token: value,
            expires_at=expires_at,
            capacity=capacity,
            prune_expired=prune_expired,
        )

    def add_factory(
        self,
        value_factory: Callable[[str], T],
        *,
        expires_at: float,
        capacity: int | None,
        prune_expired: bool = True,
    ) -> str:
        with self._lock:
            now = self._clock()
            if prune_expired:
                self._records = {
                    token: record
                    for token, record in self._records.items()
                    if record.expires_at >= now
                }
            if capacity is not None and len(self._records) >= capacity:
                raise OverflowError("preview registry capacity reached")
            token = self._token_factory()
            if not isinstance(token, str) or not token or token in self._records:
                raise RuntimeError("preview token factory returned an invalid token")
            self._records[token] = PreviewRecord(value_factory(token), expires_at)
            return token

    def put(
        self,
        token: str,
        value: T,
        *,
        expires_at: float,
        capacity: int | None,
        prune_expired: bool = True,
    ) -> None:
        with self._lock:
            now = self._clock()
            if prune_expired:
                self._records = {
                    key: record
                    for key, record in self._records.items()
                    if record.expires_at >= now
                }
            if capacity is not None and len(self._records) >= capacity:
                raise OverflowError("preview registry capacity reached")
            if not isinstance(token, str) or not token or token in self._records:
                raise RuntimeError("preview token is invalid or already registered")
            self._records[token] = PreviewRecord(value, expires_at)

    def get(self, token: str) -> PreviewRecord[T] | None:
        with self._lock:
            return self._records.get(token)

    def replace(self, token: str, value: T) -> None:
        with self._lock:
            record = self._records[token]
            self._records[token] = PreviewRecord(value, record.expires_at)

    def pop(self, token: str) -> PreviewRecord[T] | None:
        with self._lock:
            return self._records.pop(token, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

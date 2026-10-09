from __future__ import annotations

import threading

import pytest

from workflow_api.preview_registry import PreviewRegistry


def test_registry_prunes_only_strictly_expired_records_before_capacity_check():
    now = [10.0]
    tokens = iter(("first", "second", "third"))
    registry = PreviewRegistry[str](clock=lambda: now[0], token_factory=lambda: next(tokens))
    assert registry.add("one", expires_at=11.0, capacity=1) == "first"
    with pytest.raises(OverflowError):
        registry.add("two", expires_at=12.0, capacity=1)
    now[0] = 11.0
    with pytest.raises(OverflowError):
        registry.add("two", expires_at=12.0, capacity=1)
    now[0] = 11.0001
    assert registry.add("two", expires_at=12.0, capacity=1) == "second"
    assert registry.get("first") is None


def test_registry_replace_preserves_expiry_and_missing_replace_fails_closed():
    registry = PreviewRegistry[str](clock=lambda: 1.0, token_factory=lambda: "token")
    registry.add("before", expires_at=5.0, capacity=2)
    registry.replace("token", "after")
    assert registry.get("token").value == "after"
    assert registry.get("token").expires_at == 5.0
    with pytest.raises(KeyError):
        registry.replace("missing", "value")


def test_registry_rejects_empty_or_replayed_factory_token():
    empty = PreviewRegistry[str](clock=lambda: 1.0, token_factory=lambda: "")
    with pytest.raises(RuntimeError):
        empty.add("value", expires_at=2.0, capacity=1)
    replay = PreviewRegistry[str](clock=lambda: 1.0, token_factory=lambda: "same")
    replay.add("one", expires_at=3.0, capacity=2)
    with pytest.raises(RuntimeError):
        replay.add("two", expires_at=3.0, capacity=2)


def test_registry_capacity_is_atomic_under_barrier_contention():
    barrier = threading.Barrier(9)
    counter = iter(range(8))
    registry = PreviewRegistry[int](
        clock=lambda: 1.0,
        token_factory=lambda: f"token-{next(counter)}",
    )
    successes: list[str] = []
    failures: list[type[BaseException]] = []

    def add(index: int) -> None:
        barrier.wait()
        try:
            successes.append(registry.add(index, expires_at=5.0, capacity=3))
        except BaseException as error:  # captured for deterministic thread assertions
            failures.append(type(error))

    threads = [threading.Thread(target=add, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert len(successes) == 3
    assert failures == [OverflowError] * 5
    assert len(registry) == 3


def test_keyed_factory_returns_raw_token_and_stores_only_derived_key():
    registry = PreviewRegistry[str](
        clock=lambda: 1.0,
        token_factory=lambda: "raw-token",
    )
    token = registry.add_factory_keyed(
        lambda raw: f"value:{raw}",
        key_factory=lambda raw: f"digest:{raw}",
        expires_at=5.0,
        capacity=2,
    )
    assert token == "raw-token"
    assert registry.get("raw-token") is None
    assert registry.get("digest:raw-token").value == "value:raw-token"


def test_keyed_factory_can_prune_at_exact_expiry_and_rejects_collision():
    now = [1.0]
    registry = PreviewRegistry[str](
        clock=lambda: now[0],
        token_factory=lambda: "same-token",
    )
    registry.add_factory_keyed(
        lambda _raw: "first",
        key_factory=lambda raw: f"digest:{raw}",
        expires_at=2.0,
        capacity=1,
        retain_at_expiry=False,
    )
    first = registry.get("digest:same-token")
    with pytest.raises(OverflowError):
        registry.add_factory_keyed(
            lambda _raw: "second",
            key_factory=lambda raw: f"digest:{raw}",
            expires_at=3.0,
            capacity=1,
            retain_at_expiry=False,
        )
    assert registry.get("digest:same-token") is first
    now[0] = 2.0
    assert registry.add_factory_keyed(
        lambda _raw: "replacement",
        key_factory=lambda raw: f"digest:{raw}",
        expires_at=3.0,
        capacity=1,
        retain_at_expiry=False,
    ) == "same-token"
    assert registry.get("digest:same-token").value == "replacement"

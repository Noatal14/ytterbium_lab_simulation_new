from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from workflow_api.zeus_confirmation import (
    RemoteRefineState,
    ZeusConfirmationCoordinator,
    ZeusConfirmationError,
)
from workflow_api.zeus_snapshot import ZeusProfile


def _coordinator(tmp_path: Path, monkeypatch, clock, token_factory):
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True)
    manifest = {
        "name": "Campaign",
        "s0_values": [1.3],
        "fixed_design": {
            "detuning_bounds_gamma": [-2.0, -0.5],
            "magnet_radius_bounds_m": [0.045, 0.052],
        },
    }
    profile = ZeusProfile.parse({
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })
    rounds = tuple({
        "round": index,
        "job_id": f"{index}[].zeus-master",
        "depends_on_job_id": None if index == 1 else f"{index - 1}[].zeus-master",
        "scheduler": {"state": "completed_success", "task_count": 3, "counts": {"queued": 0, "running": 0, "held": 0, "succeeded": 3, "failed": 0}},
    } for index in range(1, 5))
    rows = tuple({
        "s0": 1.3,
        "detuning_gamma": -1.5 + index * 0.01,
        "magnet_radius": 0.047 + index * 0.00001,
        "mean_conditional_efficiency": 0.5,
        "source": f"refine/s0_1p300000/worker{index % 3}/trials/trial_{index:04d}.json",
    } for index in range(30))
    state = RemoteRefineState("ready_to_prepare_confirmation", rounds, rows, "main")
    plan = ("mot_2d-campaign", profile, campaign, manifest, "a" * 40, {"refine": "b" * 64}, "c" * 64, "d" * 64, "e" * 64)
    selected = {"1.3": [{**row, "rank": rank} for rank, row in enumerate(rows[:5], 1)]}
    rendered = {
        "refined_candidates.json": json.dumps(selected).encode(),
        "confirmation/tasks.json": b"[]",
        "jobs/04_confirmation.pbs": b"pbs",
        "campaign.json": b"manifest",
    }

    class Transport:
        calls = 0

        def prepare(self, **payload):
            self.calls += 1
            receipt = {
                "status": "confirmation_prepared",
                "nonce": payload["nonce"],
                "chain_key": payload["chain_key"],
                "commit": payload["commit"],
                "rows_digest": payload["rows_digest"],
                "rows": [dict(row) for row in rows],
                "files": payload["confirmation_files"],
                "rounds": [dict(row) for row in rounds],
                "completed_unix_s": 1,
            }
            return RemoteRefineState("confirmation_prepared", rounds, rows, "main", receipt)

    transport = Transport()
    coordinator = ZeusConfirmationCoordinator(
        tmp_path,
        Path(sys.executable),
        Path(sys.executable),
        clock=clock,
        token_factory=token_factory,
        transport_factory=lambda _profile: transport,
    )
    monkeypatch.setattr(coordinator, "_inspect", lambda _request: (plan, state))
    monkeypatch.setattr("workflow_api.zeus_confirmation.render_confirmation_transition", lambda *_args: rendered)
    return coordinator, transport


def _request():
    return {"campaign_id": "mot_2d-campaign", "username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}


def test_confirmation_registry_preserves_session_expiry_and_idempotent_replay(tmp_path, monkeypatch):
    now = [100.0]
    coordinator, transport = _coordinator(tmp_path, monkeypatch, lambda: now[0], lambda: "token")
    assert coordinator.preview(_request(), session_id="owner")["preview_token"] == "token"
    with pytest.raises(ZeusConfirmationError) as wrong:
        coordinator.confirm({"preview_token": "token"}, session_id="other")
    assert wrong.value.code == "confirmation_invalid"
    result = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert coordinator.confirm({"preview_token": "token"}, session_id="owner") == result
    assert transport.calls == 1

    boundary_now = [1_000.0]
    boundary, boundary_transport = _coordinator(
        tmp_path / "boundary",
        monkeypatch,
        lambda: boundary_now[0],
        lambda: "boundary",
    )
    boundary.preview(_request(), session_id="owner")
    boundary_now[0] += 300
    assert boundary.confirm({"preview_token": "boundary"}, session_id="owner")["status"] == "confirmation_prepared"
    assert boundary_transport.calls == 1
    with pytest.raises(ZeusConfirmationError) as unknown:
        boundary.confirm({"preview_token": "unknown"}, session_id="owner")
    assert unknown.value.code == "confirmation_invalid"

    now[0] = 500.0
    expired, _ = _coordinator(tmp_path / "expired", monkeypatch, lambda: now[0], lambda: "expired")
    expired.preview(_request(), session_id="owner")
    now[0] += 301
    with pytest.raises(ZeusConfirmationError) as caught:
        expired.confirm({"preview_token": "expired"}, session_id="owner")
    assert caught.value.code == "confirmation_expired"


def test_confirmation_registry_preserves_unbounded_nonpruning_preview_semantics(tmp_path, monkeypatch):
    now = [100.0]
    tokens = iter(f"token-{index}" for index in range(40))
    coordinator, transport = _coordinator(tmp_path, monkeypatch, lambda: now[0], lambda: next(tokens))
    for _ in range(33):
        coordinator.preview(_request(), session_id="owner")
    now[0] += 301
    coordinator.preview(_request(), session_id="owner")
    assert len(coordinator._previews) == 34
    assert transport.calls == 0


def test_confirmation_registry_keeps_single_remote_effect_under_barrier(tmp_path, monkeypatch):
    coordinator, transport = _coordinator(tmp_path, monkeypatch, lambda: 100.0, lambda: "token")
    coordinator.preview(_request(), session_id="owner")
    barrier = threading.Barrier(5)
    results = []

    def confirm():
        barrier.wait()
        results.append(coordinator.confirm({"preview_token": "token"}, session_id="owner"))

    threads = [threading.Thread(target=confirm) for _ in range(4)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert len(results) == 4 and all(result == results[0] for result in results)
    assert transport.calls == 1

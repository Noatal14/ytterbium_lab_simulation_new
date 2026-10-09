from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from workflow_api.zeus_refinement import (
    MAX_PENDING_PREVIEWS,
    RemoteScreenState,
    ZeusRefinementCoordinator,
    ZeusRefinementError,
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
    rows = tuple({"trial": index} for index in range(51))
    state = RemoteScreenState(
        "ready_to_prepare_refinement",
        "1[].zeus-master",
        "F",
        0,
        3,
        {"queued": 0, "running": 0, "held": 0, "succeeded": 3, "failed": 0},
        rows,
        "main",
    )
    profile = ZeusProfile.parse({
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })
    plan = (
        campaign,
        manifest,
        {},
        "a" * 40,
        {"input": "b" * 64},
        {"screen": "c" * 64},
        "d" * 64,
        "e" * 64,
    )
    selected = {
        "1.3": [
            {
                "s0": 1.3,
                "detuning_gamma": -1.0 - index * 0.1,
                "magnet_radius": 0.047 + index * 0.001,
                "mean_conditional_efficiency": 0.5 - index * 0.1,
                "source": f"screen/s0_1p3/worker{index}/trials/trial_0000.json",
            }
            for index in range(3)
        ]
    }
    rendered = {
        "screening_candidates.json": json.dumps(selected).encode(),
        "refine/tasks.json": b"[]",
        **{f"jobs/03_refine_round_{index:02d}.pbs": b"pbs" for index in range(1, 5)},
        "jobs/03_submit_refinement_chain.sh": b"chain",
        "campaign.json": b"manifest",
    }

    class Transport:
        calls = 0

        def prepare(self, **_payload):
            self.calls += 1
            return RemoteScreenState(
                "refinement_prepared", state.job_id, "F", 0, 3, state.counts, rows, "main"
            )

    transport = Transport()
    coordinator = ZeusRefinementCoordinator(
        tmp_path,
        Path(sys.executable),
        Path(sys.executable),
        clock=clock,
        token_factory=token_factory,
        transport_factory=lambda _profile: transport,
    )
    monkeypatch.setattr(coordinator, "_inspect", lambda _request: ("mot_2d-campaign", profile, plan, state))
    monkeypatch.setattr("workflow_api.zeus_refinement.render_refine_transition", lambda *_args: rendered)
    return coordinator, transport


def _request():
    return {
        "campaign_id": "mot_2d-campaign",
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    }


def test_refinement_preview_registry_preserves_token_session_expiry_and_replay(tmp_path, monkeypatch):
    now = [100.0]
    coordinator, transport = _coordinator(tmp_path, monkeypatch, lambda: now[0], lambda: "fixed-token")
    preview = coordinator.preview(_request(), session_id="owner")
    assert preview["preview_token"] == "fixed-token"
    with pytest.raises(ZeusRefinementError) as wrong_session:
        coordinator.confirm({"preview_token": "fixed-token"}, session_id="other")
    assert wrong_session.value.code == "confirmation_invalid"
    result = coordinator.confirm({"preview_token": "fixed-token"}, session_id="owner")
    assert coordinator.confirm({"preview_token": "fixed-token"}, session_id="owner") == result
    assert transport.calls == 1

    now[0] = 500.0
    coordinator, _ = _coordinator(tmp_path / "expired", monkeypatch, lambda: now[0], lambda: "expired")
    coordinator.preview(_request(), session_id="owner")
    now[0] += 301
    with pytest.raises(ZeusRefinementError) as expired:
        coordinator.confirm({"preview_token": "expired"}, session_id="owner")
    assert expired.value.code == "confirmation_expired"


def test_refinement_confirmation_remains_single_effect_under_barrier(tmp_path, monkeypatch):
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


def test_refinement_preview_capacity_maps_error_and_reclaims_expired_records(tmp_path, monkeypatch):
    now = [100.0]
    sequence = iter(f"token-{index}" for index in range(MAX_PENDING_PREVIEWS + 2))
    coordinator, transport = _coordinator(
        tmp_path, monkeypatch, lambda: now[0], lambda: next(sequence)
    )
    for _ in range(MAX_PENDING_PREVIEWS):
        coordinator.preview(_request(), session_id="owner")
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    with pytest.raises(ZeusRefinementError) as full:
        coordinator.preview(_request(), session_id="owner")
    assert full.value.code == "too_many_pending_previews"
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    assert transport.calls == 0

    now[0] += 301
    reclaimed = coordinator.preview(_request(), session_id="owner")
    assert reclaimed["preview_token"] == f"token-{MAX_PENDING_PREVIEWS}"
    assert len(coordinator._previews) == 1

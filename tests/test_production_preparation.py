from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_api.mot_2d_spec import FIXED_DESIGN
from workflow_api.zeus_production import (
    RemoteSensitivityState,
    ZeusProductionCoordinator,
)
from workflow_api.zeus_snapshot import ZeusProfile
import workflow_api.zeus_production_remote as remote


def _evaluation(efficiency: float):
    return {
        "replicates": [
            {
                "zeeman_seed": 3010 + index,
                "mot_seed": 43010 + index,
                "n_input": 10_000,
                "subset_seed": 103010 + index,
                "conditional_efficiency": efficiency,
            }
            for index in range(5)
        ],
        "statistics": {
            "mean_conditional_efficiency": efficiency,
            "conditional_95_ci": [efficiency - 0.001, efficiency + 0.001],
        },
    }


class _Transport:
    def __init__(self, rows):
        self.rows = rows
        self.prepares = 0
        self.scheduler = {
            "state": "completed_success",
            "task_count": 17,
            "counts": {
                "queued": 0,
                "running": 0,
                "held": 0,
                "succeeded": 17,
                "failed": 0,
            },
            "job_id": "123[].zeus-master",
            "submission_nonce": "b" * 32,
        }
        self.receipt = None

    def inspect(self, **_payload):
        return RemoteSensitivityState(
            "production_prepared" if self.receipt else "ready_to_prepare_production",
            self.scheduler,
            tuple(self.rows),
            "main",
            self.receipt,
            self.production_plan,
        )

    def prepare(self, **payload):
        self.prepares += 1
        self.receipt = {
            "status": "production_prepared",
            "nonce": payload["nonce"],
            "transition_key": payload["transition_key"],
            "commit": "a" * 40,
            "sensitivity_submission_key": "7" * 64,
            "sensitivity_submission_nonce": "b" * 32,
            "sensitivity_job_id": "123[].zeus-master",
            "rows_digest": payload["rows_digest"],
            "rows": self.rows,
            "files": payload["production_files"],
            "scheduler": self.scheduler,
            "completed_unix_s": 1,
        }
        return self.inspect()


def test_production_preparation_is_explicit_and_freezes_twenty_tasks(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    campaign = root / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True)
    ssh = tmp_path / "ssh"
    ssh.write_text("")
    git = tmp_path / "git"
    git.write_text("")
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    manifest = {
        "kind": "mot_2d_s0_campaign",
        "name": "Campaign",
        "stage": "sensitivity",
        "s0_values": [1.3],
        "fixed_design": FIXED_DESIGN,
        "seed_roles": {"sealed_validation": list(range(3015, 3035)), "held_out_confirmation": list(range(3010, 3015))},
        "mot_seeds": {"sealed_validation": list(range(43015, 43035)), "held_out_confirmation": list(range(43010, 43015))},
        "provenance": {"git_commit": "a" * 40},
        "stages": {"sensitivity": {"tasks": 17}},
    }
    confirmation = [
        {
            "s0": 1.3,
            "candidate_index": index,
            "parameters": {"s0": 1.3, "detuning_gamma": -1.0, "magnet_radius": 0.047},
            "evaluation": _evaluation(0.02 + index * 0.0001),
        }
        for index in range(5)
    ]
    rows = [
        {
            "s0": 1.3,
            "point_index": index,
            "parameters": {"s0": 1.3, "detuning_gamma": -1.0, "magnet_radius": 0.047},
            "offsets": {"detuning_gamma": 0.0, "magnet_radius_m": 0.0},
            "evaluation": _evaluation(0.021),
        }
        for index in range(17)
    ]
    transport = _Transport(rows)
    from workflow_api.mot_2d_plan import encode_production_plan, render_production_transition
    coordinator = ZeusProductionCoordinator(
        root,
        ssh,
        git,
        clock=lambda: 1000,
        token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    base = (
        "campaign-id",
        profile,
        campaign,
        manifest,
        "a" * 40,
        {"campaign.json": "1" * 64},
        "9" * 32,
        "8" * 64,
        "7" * 64,
        "b" * 32,
        "123[].zeus-master",
    )
    monkeypatch.setattr(coordinator, "_base_plan", lambda _request: base)
    monkeypatch.setattr(
        coordinator, "_confirmation_rows", lambda _request, _base: confirmation
    )
    request = {
        "campaign_id": "campaign-id",
        "username": "tal.noa",
        "project_directory": profile.project_directory,
    }
    transport.production_plan = encode_production_plan(coordinator._remote_payload(base), render_production_transition(manifest, campaign, root, confirmation, rows), confirmation, rows)
    preview = coordinator.preview(request, session_id="owner")
    assert preview["job"]["task_count"] == 20
    assert preview["effects"]["submit_production"] is False
    assert transport.prepares == 0
    result = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert result["status"] == "production_prepared"
    assert transport.prepares == 1
    plan, _ = coordinator._inspect(request)
    tasks = json.loads(
        (
            rendered := __import__(
                "workflow_api.mot_2d_plan", fromlist=["render_production_transition"]
            ).render_production_transition(manifest, campaign, root, confirmation, rows)
        )["production/tasks.json"]
    )
    assert len(tasks) == 20 and set(plan[9]) == set(rendered)


def _qstat(count: int, *, prefix: bytes = b"") -> bytes:
    return prefix + b"".join(
        f"Job Id: 123[{index}].zeus-master\n    job_state = F\n    Exit_status = 0\n".encode()
        for index in range(count)
    )


def test_production_receiver_qstat_requires_exact_strict_children():
    snapshot = remote.scheduler_snapshot(_qstat(17), "123[].zeus-master", 17)
    assert snapshot["state"] == "completed_success"
    for malformed in (
        _qstat(16),
        _qstat(17, prefix=b"garbage\n"),
        _qstat(17) + b"garbage\n",
        _qstat(17).replace(b"    job_state = F", b"malformed", 1),
        _qstat(17) + _qstat(1),
    ):
        with pytest.raises(ValueError):
            remote.scheduler_snapshot(malformed, "123[].zeus-master", 17)


def test_production_receiver_descriptor_read_rejects_symlink(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(SystemExit):
        remote.bounded(link)


def test_production_receiver_has_no_submission_or_cancellation_primitive():
    source = (
        Path(__file__).parents[1] / "workflow_api/zeus_production_remote.py"
    ).read_text()
    assert 'sys.argv[1] not in {"inspect", "prepare"}' in source
    assert "/usr/local/bin/qsub" not in source
    assert "qdel" not in source
    assert (
        source.count('["/opt/pbs/bin/qstat", "-x", "-t", "-f", submission["job_id"]]')
        == 1
    )

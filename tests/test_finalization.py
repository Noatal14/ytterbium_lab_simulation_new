from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_api.zeus_finalization import (
    RemoteProductionState,
    ZeusFinalizationCoordinator,
)
from workflow_api.zeus_snapshot import ZeusProfile


REPOSITORY_ROOT = Path(__file__).parents[1]


def _remote_finalization_fixture(tmp_path: Path):
    """Build a small but scientifically complete sealed Production checkout."""
    from test_mot_2d_campaign_integrity import _write_portable_sealed_campaign
    from workflow_api.zeus_sensitivity_remote import canonical_digest

    root = tmp_path / "repo"
    campaign, manifest = _write_portable_sealed_campaign(root)
    generated_states = root / "data/particle_states/after_2d_mot/fixed_s0/s0_1p300000"
    canonical_states = root / "data/particle_states/after_2d_mot/final_ensemble_s0_1.3"
    canonical_states.parent.mkdir(parents=True, exist_ok=True)
    generated_states.rename(canonical_states)
    manifest.update(stage="production", name="Campaign")
    manifest["provenance"]["git_commit"] = "a" * 40
    manifest["stages"] = {"production": {"tasks": 20}}
    for record in campaign.glob("production/*/replicates/*.json"):
        payload = json.loads(record.read_text())
        payload["design"]["git_commit"] = "a" * 40
        record.write_text(json.dumps(payload))
    for metadata in canonical_states.glob("*.json"):
        payload = json.loads(metadata.read_text())
        payload["design"]["git_commit"] = "a" * 40
        metadata.write_text(json.dumps(payload))
    (campaign / "campaign.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (campaign / "final_report.json").unlink()
    (campaign / "production/s0_1p300000/summary.json").unlink()
    job = campaign / "jobs/06_production.pbs"
    job.parent.mkdir(parents=True)
    job.write_bytes(b"#!/bin/bash\n")
    relative = campaign.relative_to(root).as_posix()
    names = {
        "sensitivity_summary.json",
        "production/tasks.json",
        "jobs/06_production.pbs",
        "campaign.json",
    }
    files = {
        name: hashlib.sha256((campaign / name).read_bytes()).hexdigest()
        for name in names
    }
    rows = [{"task_index": index} for index in range(17)]
    authoritative = campaign / ".mot_ui/test_authoritative_sensitivity_rows.json"
    authoritative.parent.mkdir(parents=True, exist_ok=True)
    authoritative.write_text(json.dumps(rows), encoding="utf-8")
    transition = {
        "status": "production_prepared",
        "nonce": "b" * 32,
        "commit": "a" * 40,
        "sensitivity_submission_key": "c" * 64,
        "sensitivity_submission_nonce": "d" * 32,
        "sensitivity_job_id": "111[].zeus-master",
        "rows_digest": canonical_digest(rows),
        "rows": rows,
        "files": files,
        "scheduler": {
            "state": "completed_success",
            "task_count": 17,
            "counts": {
                "queued": 0,
                "running": 0,
                "held": 0,
                "succeeded": 17,
                "failed": 0,
            },
            "job_id": "111[].zeus-master",
            "submission_nonce": "d" * 32,
        },
        "completed_unix_s": 1,
    }
    transition["transition_key"] = canonical_digest(
        {
            "campaign": relative,
            "commit": "a" * 40,
            "sensitivity_submission_key": transition["sensitivity_submission_key"],
            "sensitivity_submission_nonce": transition["sensitivity_submission_nonce"],
            "sensitivity_job_id": transition["sensitivity_job_id"],
            "rows_digest": transition["rows_digest"],
            "files": files,
        }
    )
    transition_path = campaign / ".mot_ui/transitions/production.json"
    transition_path.parent.mkdir(parents=True)
    transition_path.write_text(json.dumps(transition), encoding="utf-8")
    transition_digest = canonical_digest(transition)
    submission = {
        "version": 1,
        "status": "submitted",
        "transition_nonce": transition["nonce"],
        "transition_digest": transition_digest,
        "pbs_sha256": files["jobs/06_production.pbs"],
        "nonce": "e" * 32,
        "job_file": f"{relative}/jobs/06_production.pbs",
        "commit": "a" * 40,
        "created_unix_s": 1,
        "job_id": "222[].zeus-master",
        "completed_unix_s": 2,
    }
    submission["submission_key"] = canonical_digest(
        {
            "campaign": relative,
            "commit": "a" * 40,
            "transition_nonce": transition["nonce"],
            "transition_digest": transition_digest,
            "files": files,
            "job_file": "jobs/06_production.pbs",
        }
    )
    submission_path = campaign / ".mot_ui/submissions/production.json"
    submission_path.parent.mkdir(parents=True)
    submission_path.write_text(json.dumps(submission), encoding="utf-8")
    return (
        root,
        campaign,
        transition_path,
        submission_path,
        {
            "campaign": relative,
            "commit": "a" * 40,
        },
    )


def _run_finalization_receiver(
    root: Path,
    operation: str,
    payload: dict,
    *,
    hook: str = "",
    qstat_override: bytes | None = None,
):
    qstat = qstat_override or "".join(
        f"Job Id: 222[{index}].zeus-master\n"
        "    job_state = F\n"
        "    Exit_status = 0\n"
        for index in range(20)
    )
    harness = "\n".join(
        [
            "import json,sys",
            "import workflow_api.zeus_finalization_remote as remote",
            "import workflow_api.mot_2d_validation as validation",
            "validation.validated_production_transition=lambda root,manifest:"
            "(json.loads((root/'sensitivity_summary.json').read_text()),"
            "json.loads((root/'production/tasks.json').read_text()))",
            "validation.validated_evaluation_outputs=lambda root,manifest,stage:"
            "json.loads((root/'.mot_ui/test_authoritative_sensitivity_rows.json').read_text())",
            f"qstat={qstat!r}" + ("" if isinstance(qstat, bytes) else ".encode()"),
            "def captured(argv,**kwargs):",
            f"    if argv[:3]==['/usr/bin/git','rev-parse','HEAD']: return 0,b'{'a' * 40}\\n',b''",
            "    if argv[:3]==['/usr/bin/git','branch','--show-current']: return 0,b'main\\n',b''",
            "    if argv[:3]==['/usr/bin/git','status','--porcelain=v1']: return 0,b'',b''",
            "    if argv[0]=='/opt/pbs/bin/qstat': return 0,qstat,b''",
            "    raise AssertionError('unexpected process: '+repr(argv))",
            "remote.run_captured=captured",
            hook,
            f"sys.argv=['receiver',{operation!r}]",
            "remote.main()",
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", harness],
        cwd=root,
        input=json.dumps(payload).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
        check=False,
    )


def _finalization_prepare_request(request: dict, preview: dict) -> dict:
    results_digest = hashlib.sha256(
        json.dumps(preview["results"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prepared = {
        **request,
        "evidence_digest": preview["evidence_digest"],
        "final_files": preview["files"],
        "results_digest": results_digest,
        "nonce": "f" * 32,
    }
    prepared["finalization_key"] = hashlib.sha256(
        json.dumps(
            {
                "campaign": request["campaign"],
                "commit": request["commit"],
                "production_submission_key": preview["production_identity"][
                    "submission_key"
                ],
                "production_submission_nonce": preview["production_identity"][
                    "submission_nonce"
                ],
                "production_job_id": preview["production_identity"]["job_id"],
                "evidence_digest": preview["evidence_digest"],
                "files": preview["files"],
                "results_digest": results_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return prepared


class _Transport:
    def __init__(self):
        self.finalizes = 0
        self.receipt = None
        self.identity = {
            "production_files": {
                "sensitivity_summary.json": "1" * 64,
                "production/tasks.json": "2" * 64,
                "jobs/06_production.pbs": "3" * 64,
                "campaign.json": "4" * 64,
            },
            "transition_nonce": "5" * 32,
            "transition_digest": "6" * 64,
            "submission_key": "7" * 64,
            "submission_nonce": "8" * 32,
            "job_id": "123[].zeus-master",
        }
        self.scheduler = {
            "state": "completed_success",
            "task_count": 20,
            "counts": {
                "queued": 0,
                "running": 0,
                "held": 0,
                "succeeded": 20,
                "failed": 0,
            },
            "job_id": "123[].zeus-master",
            "submission_nonce": "8" * 32,
        }
        self.files = {
            "production/s0_1p300000/summary.json": "9" * 64,
            "final_report.json": "a" * 64,
            "campaign.json": "b" * 64,
        }
        self.results = [
            {
                "s0": 1.3,
                "n_ensembles": 20,
                "total_input": 100,
                "total_survivors": 10,
                "recommended_parameters": {
                    "s0": 1.3,
                    "detuning_gamma": -0.9,
                    "magnet_radius": 0.046,
                },
                "prediction": {"pooled_conditional_efficiency": 0.1},
                "target_uncertainty_passes": True,
                "robustness_status": "not_established_pending_adaptive_challenger_validation",
                "near_optimality_status": "not_established_pending_domain_challenger_elimination",
                "warnings": [
                    "robust_operating_region_not_established",
                    "epsilon_near_optimality_not_established",
                ],
                "retention": "retained",
                "output_suitability": "eligible_as_3d_campaign_input",
            }
        ]

    def inspect(self, **_payload):
        return RemoteProductionState(
            "campaign_complete" if self.receipt else "ready_to_finalize",
            self.scheduler,
            "c" * 64,
            self.files,
            tuple(self.results),
            self.identity,
            "main",
            self.receipt,
        )

    def finalize(self, **payload):
        self.finalizes += 1
        self.receipt = {
            "status": "campaign_complete",
            "nonce": payload["nonce"],
            "finalization_key": payload["finalization_key"],
            "commit": "d" * 40,
            "production_submission_key": "7" * 64,
            "production_submission_nonce": "8" * 32,
            "production_job_id": "123[].zeus-master",
            "evidence_digest": "c" * 64,
            "files": self.files,
            "results_digest": payload["results_digest"],
            "results": self.results,
            "scheduler": self.scheduler,
            "completed_unix_s": 1,
        }
        return self.inspect()


def test_finalization_is_explicit_no_submission_and_replay_safe(tmp_path, monkeypatch):
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
        "name": "Campaign",
        "s0_values": [1.3],
        "stages": {},  # The local saved campaign has not advanced with Zeus.
    }
    transport = _Transport()
    coordinator = ZeusFinalizationCoordinator(
        root,
        ssh,
        git,
        clock=lambda: 1000,
        token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    monkeypatch.setattr(
        coordinator,
        "_base_plan",
        lambda _request: ("campaign-id", profile, campaign, manifest, "d" * 40),
    )
    request = {
        "campaign_id": "campaign-id",
        "username": "tal.noa",
        "project_directory": profile.project_directory,
    }
    ready_status = coordinator.status(request)
    assert ready_status["validation"]["completed_ensembles"] == 20
    assert manifest["stages"] == {}
    assert "results" not in ready_status
    preview = coordinator.preview(request, session_id="owner")
    assert preview["results"][0]["n_ensembles"] == 20
    assert preview["effects"]["submit_job"] is False
    assert transport.finalizes == 0
    first = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    second = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert first == second
    assert first["status"] == "campaign_complete"
    assert transport.finalizes == 1
    # A fresh read-only check reopens the verified report without another confirmation.
    reopened = coordinator.status(request)
    assert reopened["production"]["status"] == "campaign_complete"
    assert reopened["results"] == first["results"]
    assert transport.finalizes == 1


def test_finalization_base_plan_does_not_traverse_historical_stage_chain(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "repo"
    root.mkdir()
    campaign = root / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True)
    manifest = {
        "kind": "mot_2d_s0_campaign",
        "name": "Campaign",
        "stage": "smoke",
        "s0_values": [1.3],
        "provenance": {"git_commit": "d" * 40},
    }
    (campaign / "campaign.json").write_text(__import__("json").dumps(manifest))
    ssh = tmp_path / "ssh"
    ssh.write_text("")
    git = tmp_path / "git"
    git.write_text("")
    coordinator = ZeusFinalizationCoordinator(root, ssh, git)
    registry = __import__("workflow_api.discovery", fromlist=["RegistryEntry"])
    entry = registry.RegistryEntry(
        "campaign-id", "mot_2d", campaign / "campaign.json", campaign.relative_to(root)
    )
    monkeypatch.setattr(
        "workflow_api.zeus_finalization.build_registry",
        lambda _root: {"campaign-id": entry},
    )
    monkeypatch.setattr(
        "workflow_api.zeus_finalization.read_manifest",
        lambda _path: __import__("types").SimpleNamespace(model=manifest),
    )
    plan = coordinator._base_plan(
        {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    assert plan[0] == "campaign-id" and plan[2] == campaign


def test_finalization_receiver_inspect_is_zero_write_and_prepare_is_durable(tmp_path):
    root, campaign, _, _, request = _remote_finalization_fixture(tmp_path)
    before = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    inspected = _run_finalization_receiver(root, "inspect", request)
    assert inspected.returncode == 0, inspected.stderr.decode()
    preview = json.loads(inspected.stdout)
    assert preview["lifecycle"] == "ready_to_finalize"
    after = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before

    prepared_request = {
        **request,
        "evidence_digest": preview["evidence_digest"],
        "final_files": preview["files"],
        "results_digest": hashlib.sha256(
            json.dumps(
                preview["results"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "nonce": "f" * 32,
    }
    prepared_request["finalization_key"] = hashlib.sha256(
        json.dumps(
            {
                "campaign": request["campaign"],
                "commit": request["commit"],
                "production_submission_key": preview["production_identity"][
                    "submission_key"
                ],
                "production_submission_nonce": preview["production_identity"][
                    "submission_nonce"
                ],
                "production_job_id": preview["production_identity"]["job_id"],
                "evidence_digest": preview["evidence_digest"],
                "files": preview["files"],
                "results_digest": prepared_request["results_digest"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    completed = _run_finalization_receiver(root, "prepare", prepared_request)
    assert completed.returncode == 0, completed.stderr.decode()
    result = json.loads(completed.stdout)
    assert result["lifecycle"] == "campaign_complete"
    assert result["results"][0]["n_ensembles"] == 20
    receipt = campaign / ".mot_ui/transitions/finalization.json"
    assert receipt.is_file()
    replay = _run_finalization_receiver(root, "prepare", prepared_request)
    assert replay.returncode == 0
    assert json.loads(replay.stdout)["receipt"] == json.loads(receipt.read_text())


def test_finalization_receiver_rejects_coordinated_history_tampering(tmp_path):
    root, _, transition_path, submission_path, request = _remote_finalization_fixture(
        tmp_path
    )
    transition = json.loads(transition_path.read_text())
    transition["rows"][0]["task_index"] = 999
    from workflow_api.zeus_sensitivity_remote import canonical_digest

    transition["rows_digest"] = canonical_digest(transition["rows"])
    transition["transition_key"] = canonical_digest(
        {
            "campaign": request["campaign"],
            "commit": request["commit"],
            "sensitivity_submission_key": transition["sensitivity_submission_key"],
            "sensitivity_submission_nonce": transition["sensitivity_submission_nonce"],
            "sensitivity_job_id": transition["sensitivity_job_id"],
            "rows_digest": transition["rows_digest"],
            "files": transition["files"],
        }
    )
    transition_path.write_text(json.dumps(transition))
    submission = json.loads(submission_path.read_text())
    submission["transition_digest"] = canonical_digest(transition)
    submission["submission_key"] = canonical_digest(
        {
            "campaign": request["campaign"],
            "commit": request["commit"],
            "transition_nonce": transition["nonce"],
            "transition_digest": submission["transition_digest"],
            "files": transition["files"],
            "job_file": "jobs/06_production.pbs",
        }
    )
    submission_path.write_text(json.dumps(submission))
    rejected = _run_finalization_receiver(root, "inspect", request)
    assert rejected.returncode != 0
    assert b"production_preparation_invalid" in rejected.stdout


@pytest.mark.parametrize("attack", ["symlink", "non_utf8", "oversize"])
def test_finalization_receiver_rejects_unsafe_evidence(tmp_path, attack):
    root, campaign, _, _, request = _remote_finalization_fixture(tmp_path)
    target = campaign / "production/s0_1p300000/replicates/zeeman_seed3015.json"
    if attack == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    elif attack == "non_utf8":
        target.write_bytes(b"\xff")
    else:
        with target.open("wb") as stream:
            stream.truncate(64 * 1024**2 + 1)
    rejected = _run_finalization_receiver(root, "inspect", request)
    assert (
        rejected.returncode != 0
        or json.loads(rejected.stdout)["lifecycle"] == "outputs_invalid"
    )


def test_finalization_receiver_has_no_submission_or_scheduler_mutation():
    source = (REPOSITORY_ROOT / "workflow_api/zeus_finalization_remote.py").read_text()
    assert '"/opt/pbs/bin/qstat"' in source
    assert '"/usr/local/bin/qsub"' not in source
    assert '"/usr/local/bin/qdel"' not in source
    assert '"/usr/local/bin/qalter"' not in source


def test_finalization_receiver_pending_recovery_requires_explicit_prepare(tmp_path):
    root, campaign, _, _, request = _remote_finalization_fixture(tmp_path)
    preview = json.loads(_run_finalization_receiver(root, "inspect", request).stdout)
    prepared = _finalization_prepare_request(request, preview)
    crash_hook = "\n".join(
        [
            "original_atomic_json=remote.atomic_json",
            "def crash_receipt(path,payload):",
            "    if path.name=='finalization.json': raise RuntimeError('crash')",
            "    return original_atomic_json(path,payload)",
            "remote.atomic_json=crash_receipt",
        ]
    )
    crashed = _run_finalization_receiver(root, "prepare", prepared, hook=crash_hook)
    assert crashed.returncode != 0
    pending = campaign / ".mot_ui/transitions/finalization.pending.json"
    assert pending.is_file()
    before = pending.read_bytes()
    inspected = _run_finalization_receiver(root, "inspect", request)
    assert inspected.returncode == 0
    assert json.loads(inspected.stdout)["lifecycle"] == "ready_to_finalize"
    assert pending.read_bytes() == before
    recovered = _run_finalization_receiver(root, "prepare", prepared)
    assert recovered.returncode == 0
    assert json.loads(recovered.stdout)["lifecycle"] == "campaign_complete"
    assert not pending.exists()


def test_finalization_receiver_rejects_aba_evidence_swap(tmp_path):
    root, campaign, _, _, request = _remote_finalization_fixture(tmp_path)
    target = campaign / "production/s0_1p300000/replicates/zeeman_seed3015.json"
    relative = target.relative_to(root).as_posix()
    hook = "\n".join(
        [
            "import workflow_api.mot_2d_plan as plan",
            "from pathlib import Path",
            "original_render=plan.render_finalization",
            "def swapped_render(manifest,campaign,root):",
            f"    target=Path({relative!r})",
            "    backup=target.with_suffix('.original')",
            "    data=target.read_bytes()",
            "    target.rename(backup)",
            "    target.write_bytes(data)",
            "    try: return original_render(manifest,campaign,root)",
            "    finally:",
            "        target.unlink()",
            "        backup.rename(target)",
            "plan.render_finalization=swapped_render",
        ]
    )
    rejected = _run_finalization_receiver(root, "inspect", request, hook=hook)
    assert rejected.returncode == 0
    assert json.loads(rejected.stdout)["lifecycle"] == "outputs_invalid"


def test_finalization_receiver_rejects_non_exact_qstat_children(tmp_path):
    root, _, _, _, request = _remote_finalization_fixture(tmp_path)
    malformed = b"garbage prefix\nJob Id: 222[0].zeus-master\n"
    result = _run_finalization_receiver(
        root, "inspect", request, qstat_override=malformed
    )
    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["lifecycle"] == "status_unknown"
    assert response["scheduler"]["state"] == "unknown"

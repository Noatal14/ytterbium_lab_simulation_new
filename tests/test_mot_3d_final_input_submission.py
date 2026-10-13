import base64
import hashlib
import json
import sys

import pytest

from workflow_api.mot_3d_final_input_submission import (
    CODE_FILES,
    FILES,
    Mot3DFinalInputSubmissionCoordinator,
    Mot3DFinalInputSubmissionError,
    RemoteFinalInputSubmissionState,
)
from workflow_api import mot_3d_final_input_submission_remote as receiver
from workflow_api.mot_3d_finalist_results import expected_paths
from workflow_api.mot_3d_linear_submission import validate_linear_submission_state
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.verified_artifact_bundle import build_artifact_bundle
from workflow_api.mot_3d_final_input_submission_remote_client import (
    PinnedSshMot3DFinalInputSubmissionTransport,
)


def state(
    lifecycle="eligible", jobs=None, nonce=None, submitted=None, arrays=0, scalar=0
):
    return RemoteFinalInputSubmissionState(
        lifecycle,
        "main",
        jobs or {"zeeman": None, "mot_2d": None, "freeze": None},
        nonce,
        submitted,
        arrays,
        scalar,
    )


@pytest.mark.parametrize(
    "value,operation",
    [
        (state(), "inspect"),
        (
            state(
                "partial",
                {"zeeman": "10[].zeus-master", "mot_2d": None, "freeze": None},
                "a" * 32,
            ),
            "submit",
        ),
        (state("outcome_unknown", nonce="a" * 32), "status"),
        (
            state(
                "submitted",
                {
                    "zeeman": "10[].zeus-master",
                    "mot_2d": "11[].zeus-master",
                    "freeze": "12.zeus-master",
                },
                "a" * 32,
                1,
            ),
            "status",
        ),
        (
            state(
                "completed_success_unvalidated",
                {
                    "zeeman": "10[].zeus-master",
                    "mot_2d": "11[].zeus-master",
                    "freeze": "12.zeus-master",
                },
                "a" * 32,
                1,
                40,
                1,
            ),
            "status",
        ),
    ],
)
def test_linear_state_matrix_accepts_only_canonical_states(value, operation):
    validate_linear_submission_state(
        value, operation, error=Mot3DFinalInputSubmissionError
    )


@pytest.mark.parametrize(
    "value",
    [
        state(
            "partial",
            {"zeeman": None, "mot_2d": "11[].zeus-master", "freeze": None},
            "a" * 32,
        ),
        state(
            "submitted",
            {
                "zeeman": "10[].zeus-master",
                "mot_2d": "10[].zeus-master",
                "freeze": "12.zeus-master",
            },
            "a" * 32,
            1,
        ),
        state(
            "completed_success_unvalidated",
            {
                "zeeman": "10[].zeus-master",
                "mot_2d": "11[].zeus-master",
                "freeze": "12.zeus-master",
            },
            "a" * 32,
            1,
            39,
            1,
        ),
        state(
            "outcome_unknown",
            {
                "zeeman": "10[].zeus-master",
                "mot_2d": "11[].zeus-master",
                "freeze": "12.zeus-master",
            },
            "a" * 32,
        ),
    ],
)
def test_linear_state_matrix_rejects_gaps_duplicates_and_false_completion(value):
    with pytest.raises(Mot3DFinalInputSubmissionError, match="remote_response_invalid"):
        validate_linear_submission_state(
            value, "status", error=Mot3DFinalInputSubmissionError
        )


def test_preview_confirm_is_session_bound_deduplicated_and_truthful(tmp_path):
    ssh = tmp_path / "ssh"
    ssh.write_text("")
    git = tmp_path / "git"
    git.write_text("")
    coordinator = Mot3DFinalInputSubmissionCoordinator(
        tmp_path,
        ssh,
        git,
        clock=lambda: 100,
        token_factory=lambda: "token",
        transport_factory=lambda _p: transport,
    )
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    science = {
        "classification": "new_unopened_inputs_after_nominal_lock",
        "zeeman_seeds": list(range(3035, 3055)),
        "mot_seeds": list(range(43035, 43055)),
        "zeeman_tasks": 20,
        "mot_tasks": 20,
        "npools": 200,
        "dependency": "afterok linear chain",
        "resources": {
            "zeeman": {"ncpus": 200, "memory_gb": 64, "walltime": "08:00:00"},
            "mot_2d": {"ncpus": 200, "memory_gb": 64, "walltime": "12:00:00"},
            "freeze": {"ncpus": 1, "memory_gb": 8, "walltime": "00:30:00"},
        },
    }
    identity = {"science": science, "local_transition_receipt_sha256": "b" * 64}
    plan = (
        "campaign",
        profile,
        tmp_path,
        {"name": "campaign"},
        "a" * 40,
        identity,
        "c" * 64,
        "data/optimization/mot_3d/campaign",
    )
    eligible = state()
    submitted = state(
        "submitted",
        {
            "zeeman": "10[].zeus-master",
            "mot_2d": "11[].zeus-master",
            "freeze": "12.zeus-master",
        },
        "d" * 32,
        100,
    )

    class Transport:
        calls = 0

        def submit(self, **_payload):
            self.calls += 1
            return submitted

    transport = Transport()
    coordinator._plan = lambda _request: plan
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        eligible,
    )
    preview = coordinator.preview({}, session_id="one")
    assert [row["tasks"] for row in preview["chain"]["steps"]] == [20, 20, 1]
    with pytest.raises(Mot3DFinalInputSubmissionError, match="confirmation_invalid"):
        coordinator.confirm({"preview_token": "token"}, session_id="two")
    result = coordinator.confirm({"preview_token": "token"}, session_id="one")
    assert result["final_validation_started"] is False
    assert coordinator.confirm({"preview_token": "token"}, session_id="one") == result
    assert transport.calls == 1


def test_transport_preserves_typed_remote_preparation_failure():
    class Result:
        returncode = 20
        stdout = '{"error":"final_input_preparation_invalid"}'
        stderr = ""

    transport = object.__new__(PinnedSshMot3DFinalInputSubmissionTransport)
    transport.profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    transport.runner = type("Runner", (), {"run": lambda *_args, **_kwargs: Result()})()
    with pytest.raises(
        Mot3DFinalInputSubmissionError, match="final_input_preparation_invalid"
    ):
        transport.inspect()


def _receiver_repository(tmp_path):
    root = tmp_path / "remote"
    campaign = root / "data/optimization/mot_3d/campaign"
    transitions = campaign / ".mot_ui/transitions"
    (campaign / ".mot_ui/submissions").mkdir(parents=True)
    transitions.mkdir(parents=True)
    logical = "data/optimization/mot_3d/campaign"
    stage = {
        "classification": "new_unopened_inputs_after_nominal_lock",
        "locked_nominals": f"{logical}/selection/locked_nominals.json",
        "zeeman_seeds": list(range(3035, 3055)),
        "mot_seeds": list(range(43035, 43055)),
        "zeeman_job": f"{logical}/{receiver.JOB_PATHS['zeeman']}",
        "mot_job": f"{logical}/{receiver.JOB_PATHS['mot_2d']}",
        "freeze_job": f"{logical}/{receiver.JOB_PATHS['freeze']}",
        "input_manifest": f"{logical}/final_validation_inputs/input_manifest.json",
    }
    manifest = {
        "name": "campaign",
        "stage": "final_validation_input_generation",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "1" * 64},
        "upstream_2d_campaign": {
            "campaign_sha256": "2" * 64,
            "final_report_sha256": "3" * 64,
        },
        "design": {"timestep_evidence": {"policy_sha256": "4" * 64}},
        "stages": {"final_validation_input_generation": stage},
    }
    frozen = {"campaign.json": json.dumps(manifest, sort_keys=True).encode()}
    frozen["selection/locked_nominals.json"] = b"{}\n"
    for name, path in receiver.JOB_PATHS.items():
        frozen[path] = f"{name}-pbs\n".encode()
    for name, raw in frozen.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    selections = {}
    for family in ("angled_donut", "single_pass"):
        selections[family] = {
            "kind": "mot_3d_finalist_selection",
            "family": family,
            "candidate_count": 3,
            "candidates": [
                {"candidate_id": f"{family}_finalist_{index:02d}"}
                for index in range(1, 4)
            ],
        }
        target = campaign / f"selection/finalists/{family}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(selections[family]))
    bundle_files = {
        name: f"result-{index}".encode()
        for index, name in enumerate(expected_paths(selections))
    }
    bundle_files["finalist_selection_submission.json"] = b"submission-receipt"
    bundle_files.update(frozen)
    built = build_artifact_bundle(
        bundle_files,
        campaign="campaign",
        commit="a" * 40,
        from_stage="finalist_selection",
        to_stage="final_validation_input_generation",
        expected_paths=frozenset(bundle_files),
    )
    bundle_raw = built.packed
    bundle_sha = built.manifest["bundle_sha256"]
    bundle = dict(built.manifest)
    receipt = {
        "version": 1,
        "status": "final_validation_input_generation_prepared",
        "nonce": "9" * 32,
        "transition_key": "5" * 64,
        "commit": "a" * 40,
        "submission_key": "6" * 64,
        "identity_sha256": "7" * 64,
        "old_campaign_sha256": "8" * 64,
        "new_campaign_sha256": hashlib.sha256(frozen["campaign.json"]).hexdigest(),
        "evidence_sha256": "b" * 64,
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in bundle_files.items()
        },
        "bundle": bundle,
        "completed_unix_s": 1,
    }
    receipt_raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    (transitions / receiver.TRANSITION).write_bytes(receipt_raw)
    (
        transitions / "finalist_selection_to_final_validation_inputs.bundle.gz"
    ).write_bytes(bundle_raw)
    code_files = {}
    for name in CODE_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        code_files[name] = hashlib.sha256(name.encode()).hexdigest()
    science = receiver._expected_science(manifest)
    identity = {
        "campaign_sha256": hashlib.sha256(frozen["campaign.json"]).hexdigest(),
        "local_transition_receipt_sha256": "d" * 64,
        "transition_key": "5" * 64,
        "remote_transition_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "bundle_sha256": bundle_sha,
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in frozen.items()
        },
        "science": science,
        "physical_model_sha256": "1" * 64,
        "upstream_campaign_sha256": "2" * 64,
        "upstream_final_report_sha256": "3" * 64,
        "timestep_policy_sha256": "4" * 64,
        "code_files": code_files,
    }
    payload = {"campaign": logical, "commit": "a" * 40, "identity": identity}
    payload["submission_key"] = receiver.linear.submission_key(
        logical, "a" * 40, identity
    )
    return root, campaign, payload


def _invoke_receiver(monkeypatch, root, operation, payload, fake_run):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "receiver",
            operation,
            "tal.noa",
            "/home/tal.noa/ytterbium_lab_simulation_new",
            encoded,
        ],
    )
    monkeypatch.setattr(receiver, "run", fake_run)
    receiver.main(trusted_root_override=root)


def test_real_receiver_attests_joined_transition_and_submits_exact_chain(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _receiver_repository(tmp_path)
    before = {
        path.relative_to(campaign).as_posix(): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    calls = []
    ids = iter((b"901[].zeus-master\n", b"902[].zeus-master\n", b"903.zeus-master\n"))

    def fake_run(argv, input_data=None, limit=None):
        if argv[:2] == ["/usr/bin/git", "-C"]:
            if argv[3] == "rev-parse":
                return 0, b"a" * 40 + b"\n", b""
            if argv[3] == "branch":
                return 0, b"main\n", b""
            if argv[3] == "status":
                return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            calls.append((argv, input_data))
            return 0, next(ids), b""
        raise AssertionError(argv)

    _invoke_receiver(monkeypatch, root, "inspect", payload, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "eligible"
    assert before == {
        path.relative_to(campaign).as_posix(): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    submitted = {**payload, "nonce": "e" * 32}
    _invoke_receiver(monkeypatch, root, "submit", submitted, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert [row[0][1:] for row in calls] == [
        ["-J", "0-19:1"],
        ["-W", "depend=afterok:901[].zeus-master", "-J", "0-19:1"],
        ["-W", "depend=afterok:902[].zeus-master"],
    ]


@pytest.mark.parametrize(
    "surface",
    ["science", "code", "pbs", "transition", "bundle", "registry", "chunks"],
)
def test_real_receiver_rejects_identity_mutations_before_qsub(
    tmp_path, monkeypatch, surface
):
    root, campaign, payload = _receiver_repository(tmp_path)
    if surface == "science":
        payload["identity"]["science"]["zeeman_tasks"] = 19
    elif surface == "code":
        path = root / next(iter(CODE_FILES))
        path.write_bytes(path.read_bytes() + b"drift")
    elif surface == "pbs":
        path = campaign / receiver.JOB_PATHS["mot_2d"]
        path.write_bytes(path.read_bytes() + b"drift")
    elif surface == "transition":
        path = campaign / ".mot_ui/transitions" / receiver.TRANSITION
        path.write_bytes(path.read_bytes() + b"\n")
    elif surface == "bundle":
        path = (
            campaign
            / ".mot_ui/transitions/finalist_selection_to_final_validation_inputs.bundle.gz"
        )
        path.write_bytes(path.read_bytes() + b"drift")
    else:
        path = campaign / ".mot_ui/transitions" / receiver.TRANSITION
        receipt = json.loads(path.read_text())
        if surface == "registry":
            name, digest = receipt["files"].popitem()
            receipt["files"][f"substituted/{name.rsplit('/', 1)[-1]}"] = digest
        else:
            receipt["bundle"]["chunks"][0]["sha256"] = "f" * 64
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        payload["identity"]["remote_transition_receipt_sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        payload["submission_key"] = receiver.linear.submission_key(
            payload["campaign"], payload["commit"], payload["identity"]
        )

    def fake_run(argv, input_data=None, limit=None):
        if argv[:2] == ["/usr/bin/git", "-C"]:
            if argv[3] == "rev-parse":
                return 0, b"a" * 40 + b"\n", b""
            if argv[3] == "branch":
                return 0, b"main\n", b""
            if argv[3] == "status":
                return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            raise AssertionError("mutation reached qsub")
        raise AssertionError(argv)

    with pytest.raises(SystemExit):
        _invoke_receiver(monkeypatch, root, "inspect", payload, fake_run)

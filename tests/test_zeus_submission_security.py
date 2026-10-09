"""Adversarial tests for explicitly confirmed 2D smoke submission.

These tests use in-memory transports only.  They must never contact Zeus.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from workflow_api.mot_2d_plan import RELEVANT_FILES, build_plan, materialize
from workflow_api.mot_2d_sources import inspect_source
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.zeus_submission import (
    MAX_PENDING_PREVIEWS,
    PinnedSshSmokeSubmissionTransport,
    SubmissionRemoteState,
    ZeusSmokeSubmissionCoordinator,
    ZeusSubmissionError,
    _REMOTE_SCRIPT,
)
from workflow_api.zeus_snapshot import ZeusProfile


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository(root: Path) -> None:
    for relative in RELEVANT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    lab = root / "lab_setup/model.py"
    lab.parent.mkdir()
    lab.write_text("MODEL = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
        cwd=root,
        check=True,
    )


def _source(root: Path) -> dict[str, object]:
    directory = root / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.zeros((1, 6)))
        state.with_suffix(".json").write_text(
            json.dumps(
                {
                    "shape": [1, 6],
                    "dtype": "float64",
                    "n_survivors": 1,
                    "output_sha256": _digest(state),
                    "parameters": {
                        "seed": seed,
                        "resolved_zeeman_magnet_profile": "profile",
                        "n_initial_atoms": 50000,
                        "dt_s": 4e-5,
                    },
                    "software": {"git_commit": "source"},
                }
            ),
            encoding="utf-8",
        )
    return inspect_source(directory, root)


def _campaign(root: Path, *, s0_values: list[float] | None = None):
    _repository(root)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    plan = build_plan(
        root,
        name="Submission fixture",
        slug="submission-fixture",
        s0_values=s0_values or [1.3],
        source=_source(root),
        snapshot=RepositorySnapshot(commit),
    )
    materialize(plan)
    return plan, commit


class RecordingTransport:
    def __init__(self, state: SubmissionRemoteState | None = None):
        self.state = state or SubmissionRemoteState("eligible", branch="main")
        self.inspections: list[dict[str, object]] = []
        self.submissions: list[dict[str, object]] = []

    def inspect(self, **kwargs: object) -> SubmissionRemoteState:
        self.inspections.append(dict(kwargs))
        return self.state

    def submit(self, **kwargs: object) -> SubmissionRemoteState:
        self.submissions.append(dict(kwargs))
        if self.state.status == "submitted":
            return self.state
        nonce = kwargs["nonce"]
        return SubmissionRemoteState("submitted", "12345.zeus-master", str(nonce), submitted_unix_s=123)


def _coordinator(
    root: Path,
    transport: RecordingTransport,
    *,
    clock=lambda: 100.0,
    token_factory=None,
):
    return ZeusSmokeSubmissionCoordinator(
        root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
        clock=clock,
        token_factory=token_factory,
        transport_factory=lambda _profile: transport,
    )


def _request(campaign_id: str) -> dict[str, object]:
    return {
        "campaign_id": campaign_id,
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    }


def _code(callable_) -> str:
    with pytest.raises(ZeusSubmissionError) as caught:
        callable_()
    return caught.value.code


def test_preview_binds_exact_72_artifacts_and_regenerated_smoke_pbs(tmp_path):
    plan, commit = _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    campaign_id = __import__("workflow_api.discovery", fromlist=["build_registry"]).build_registry(tmp_path)
    campaign_id = next(iter(campaign_id))

    preview = coordinator.preview(_request(campaign_id), session_id="owner")

    assert len(transport.inspections) == 1
    inspected = transport.inspections[0]
    assert len(inspected["files"]) == 72
    assert inspected["commit"] == commit
    assert inspected["job_file"].endswith("/jobs/01_smoke.pbs")
    expected_job = plan.files["jobs/01_smoke.pbs"]
    assert inspected["files"][inspected["job_file"]] == hashlib.sha256(expected_job).hexdigest()
    assert preview["stage"]["id"] == "smoke"
    assert preview["inputs"] == {"verified_count": 72, "status": "ready"}
    assert transport.submissions == []


@pytest.mark.parametrize("mutate", ["manifest", "pbs", "input", "stage"])
def test_confirm_rechecks_manifest_pbs_inputs_and_stage_after_preview(tmp_path, mutate):
    plan, _ = _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    preview = coordinator.preview(_request(campaign_id), session_id="owner")

    if mutate == "manifest":
        (plan.destination / "campaign.json").write_text("{}\n")
    elif mutate == "pbs":
        (plan.destination / "jobs/01_smoke.pbs").write_text("#!/bin/bash\nqsub evil\n")
    elif mutate == "input":
        row = plan.manifest["input_ensembles"]["discovery"][0]
        (tmp_path / row["path"]).write_bytes(b"changed")
    else:
        manifest = json.loads((plan.destination / "campaign.json").read_text())
        manifest["stage"] = "screen"
        (plan.destination / "campaign.json").write_text(json.dumps(manifest))

    assert _code(lambda: coordinator.confirm({"preview_token": preview["preview_token"]}, session_id="owner")) in {
        "campaign_not_smoke",
        "campaign_not_canonical",
        "local_files_changed",
    }
    assert transport.submissions == []


def test_dirty_or_changed_local_commit_blocks_before_submit(tmp_path):
    _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    (tmp_path / "config.py").write_text("dirty", encoding="utf-8")

    assert _code(lambda: coordinator.confirm({"preview_token": preview["preview_token"]}, session_id="owner")) == "local_files_changed"
    assert transport.submissions == []


def test_untracked_sitecustomize_blocks_preview(tmp_path):
    _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    (tmp_path / "sitecustomize.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")

    assert _code(
        lambda: coordinator.preview(_request(campaign_id), session_id="owner")
    ) == "local_checkout_mismatch"
    assert transport.inspections == [] and transport.submissions == []


def test_untracked_python_that_could_shadow_runtime_blocks_before_submit(tmp_path):
    _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    (tmp_path / "numpy.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")

    assert _code(
        lambda: coordinator.confirm(
            {"preview_token": preview["preview_token"]}, session_id="owner"
        )
    ) == "local_files_changed"
    assert transport.submissions == []


def test_confirm_is_session_bound_idempotent_and_concurrent_at_most_once(tmp_path):
    _campaign(tmp_path)
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    token = preview["preview_token"]
    assert _code(lambda: coordinator.confirm({"preview_token": token}, session_id="other")) == "confirmation_invalid"

    results: list[object] = []
    failures: list[BaseException] = []
    barrier = threading.Barrier(9)
    def confirm() -> None:
        try:
            barrier.wait()
            results.append(coordinator.confirm({"preview_token": token}, session_id="owner"))
        except BaseException as error:  # retain concurrent failures for assertion
            failures.append(error)
    threads = [threading.Thread(target=confirm) for _ in range(8)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join()

    assert failures == []
    assert len(results) == 8 and all(row == results[0] for row in results)
    assert len(transport.submissions) == 1


def test_smoke_submission_preview_registry_boundary_expiry_and_capacity(tmp_path):
    _campaign(tmp_path)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    now = [100.0]
    tokens = iter(f"token-{index}" for index in range(MAX_PENDING_PREVIEWS + 1))
    transport = RecordingTransport()
    coordinator = _coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: next(tokens),
    )
    plan = coordinator._plan(campaign_id)
    coordinator._plan = lambda _campaign_id: plan
    coordinator._revision = lambda: (plan[2], True)
    for _ in range(MAX_PENDING_PREVIEWS):
        coordinator.preview(_request(campaign_id), session_id="owner")
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    assert _code(lambda: coordinator.preview(
        _request(campaign_id), session_id="owner")) == "too_many_pending_previews"
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    assert transport.submissions == []

    now[0] = 400.0
    assert _code(lambda: coordinator.preview(
        _request(campaign_id), session_id="owner")) == "too_many_pending_previews"
    now[0] = 401.0
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    assert preview["preview_token"] == f"token-{MAX_PENDING_PREVIEWS}"
    assert len(coordinator._previews) == 1

    assert _code(lambda: coordinator.confirm(
        {"preview_token": "missing"}, session_id="owner")) == "confirmation_invalid"
    assert _code(lambda: coordinator.confirm(
        {"preview_token": preview["preview_token"]}, session_id="other")) == "confirmation_invalid"
    now[0] = 702.0
    assert _code(lambda: coordinator.confirm(
        {"preview_token": preview["preview_token"]}, session_id="owner")) == "confirmation_expired"
    assert coordinator._previews.get(preview["preview_token"]) is None
    assert transport.submissions == []


def test_smoke_submission_exact_expiry_boundary_remains_confirmable(tmp_path):
    _campaign(tmp_path)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    now = [100.0]
    transport = RecordingTransport()
    coordinator = _coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: "boundary-token",
    )
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    now[0] = 400.0
    result = coordinator.confirm(
        {"preview_token": preview["preview_token"]}, session_id="owner")
    assert result["status"] == "submitted"
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("after_effect", [False, True])
def test_smoke_submission_ambiguous_confirm_reuses_nonce_without_second_effect(
    tmp_path, after_effect,
):
    _campaign(tmp_path)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))

    class AmbiguousTransport(RecordingTransport):
        def __init__(self):
            super().__init__()
            self.remote_effects = 0

        def submit(self, **kwargs):
            self.submissions.append(dict(kwargs))
            if after_effect and self.remote_effects == 0:
                self.remote_effects += 1
            raise ZeusSubmissionError("submission_outcome_unknown")

    transport = AmbiguousTransport()
    coordinator = _coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "ambiguous-token",
    )
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    request = {"preview_token": preview["preview_token"]}
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == "submission_outcome_unknown"
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == "submission_outcome_unknown"
    assert len(transport.submissions) == 1
    assert transport.remote_effects == (1 if after_effect else 0)
    record = coordinator._previews.get("ambiguous-token")
    assert record is not None and record.value.result is None
    assert record.value.terminal_error == "submission_outcome_unknown"
    assert record.value.nonce == transport.submissions[0]["nonce"]


@pytest.mark.parametrize("mode,code", [
    ("wrong_nonce", "already_submitted"),
    ("already_started", "smoke_already_started"),
])
def test_smoke_submission_definitive_post_invocation_error_is_terminal(
    tmp_path, mode, code,
):
    _campaign(tmp_path)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))

    class TerminalTransport(RecordingTransport):
        def submit(self, **kwargs):
            self.submissions.append(dict(kwargs))
            if mode == "already_started":
                raise ZeusSubmissionError("smoke_already_started")
            return SubmissionRemoteState(
                "submitted",
                "12345.zeus-master",
                "f" * 32,
                submitted_unix_s=123,
            )

    transport = TerminalTransport()
    coordinator = _coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "terminal-token",
    )
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    request = {"preview_token": preview["preview_token"]}
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert len(transport.submissions) == 1
    record = coordinator._previews.get("terminal-token")
    assert record is not None and record.value.terminal_error == code


@pytest.mark.parametrize("remote", [
    SubmissionRemoteState("ambiguous", nonce="0" * 32, branch="main"),
    SubmissionRemoteState("submitted", "12345.zeus-master", "1" * 32, branch="main", submitted_unix_s=123),
])
def test_preview_never_resubmits_ambiguous_or_previously_submitted_stage(tmp_path, remote):
    _campaign(tmp_path)
    transport = RecordingTransport(remote)
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))

    if remote.status == "ambiguous":
        assert _code(lambda: coordinator.preview(_request(campaign_id), session_id="owner")) == "submission_outcome_unknown"
    else:
        assert _code(lambda: coordinator.preview(_request(campaign_id), session_id="owner")) == "already_submitted"
    assert transport.submissions == []


def test_request_surface_rejects_paths_commands_and_scheduler_options(tmp_path):
    _campaign(tmp_path)
    coordinator = _coordinator(tmp_path, RecordingTransport())
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    base = _request(campaign_id)
    for extra in ({"job_file": "../../evil"}, {"command": "qdel 1"}, {"qsub_options": ["-I"]}, {"password": "secret"}):
        assert _code(lambda extra=extra: coordinator.preview({**base, **extra}, session_id="owner")) == "request_invalid"


def test_transport_receives_only_fixed_smoke_identity_and_server_nonce(tmp_path):
    _campaign(tmp_path, s0_values=[1.2, 1.3])
    transport = RecordingTransport()
    coordinator = _coordinator(tmp_path, transport)
    from workflow_api.discovery import build_registry
    campaign_id = next(iter(build_registry(tmp_path)))
    preview = coordinator.preview(_request(campaign_id), session_id="owner")
    result = coordinator.confirm({"preview_token": preview["preview_token"]}, session_id="owner")

    submitted = transport.submissions[0]
    assert submitted["job_file"].endswith("/jobs/01_smoke.pbs")
    assert len(submitted["nonce"]) == 32 and set(submitted["nonce"]) <= set("0123456789abcdef")
    assert result["status"] == "submitted"
    assert result["job_id"] == "12345.zeus-master"
    joined = repr(submitted).lower()
    assert all(forbidden not in joined for forbidden in ("qdel", "qalter", "git checkout", "git reset", "screen.pbs", "refine"))


def test_pinned_transport_uses_fixed_ssh_argv_and_no_shell(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    observed: dict[str, object] = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b'{"status":"eligible","branch":"main"}\n', b"")

    monkeypatch.setattr("workflow_api.zeus_submission.subprocess.run", run)
    transport = PinnedSshSmokeSubmissionTransport(
        root,
        Path("/usr/bin/ssh"),
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    state = transport.inspect(
        files={f"data/f{i}": "a" * 64 for i in range(72)},
        campaign="data/optimization/mot_2d/campaign",
        job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
        commit="a" * 40,
        submission_key="b" * 64,
    )

    assert state.status == "eligible"
    argv = observed["argv"]
    kwargs = observed["kwargs"]
    assert argv[0] == "/usr/bin/ssh"
    assert argv[-2] == "tal.noa@zeus.technion.ac.il"
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "BatchMode=yes" in argv and "StrictHostKeyChecking=yes" in argv
    assert "ForwardAgent=no" in argv and "ClearAllForwardings=yes" in argv
    assert all(term not in " ".join(argv[:-1]) for term in ("qsub", "qdel", "qalter"))


@pytest.mark.parametrize("job_id", [
    "12345",                         # server suffix must not be optional
    "12345[]",                       # server suffix must not be optional
    "12345[0].zeus-master",          # qsub returns a parent id, never an element
    "12345.other-server",
    "12345.zeus-master\nqdel 1",
])
def test_submit_rejects_noncanonical_qsub_job_ids(tmp_path, monkeypatch, job_id):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        "workflow_api.zeus_submission.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"status": "submitted", "job_id": job_id, "nonce": "0" * 32}).encode(),
            b"",
        ),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root,
        Path("/usr/bin/ssh"),
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    assert _code(lambda: transport.submit(
        files={f"data/f{i}": "a" * 64 for i in range(72)},
        campaign="data/optimization/mot_2d/campaign",
        job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
        commit="a" * 40,
        submission_key="b" * 64,
        nonce="0" * 32,
    )) == "submission_outcome_unknown"


def test_submit_timeout_or_malformed_output_is_ambiguous_and_never_retried(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    calls: list[object] = []
    def timeout(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, 45)
    monkeypatch.setattr("workflow_api.zeus_submission.subprocess.run", timeout)
    transport = PinnedSshSmokeSubmissionTransport(
        root,
        Path("/usr/bin/ssh"),
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    arguments = dict(
        files={f"data/f{i}": "a" * 64 for i in range(72)},
        campaign="data/optimization/mot_2d/campaign",
        job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
        commit="a" * 40,
        submission_key="b" * 64,
        nonce="0" * 32,
    )
    assert _code(lambda: transport.submit(**arguments)) == "submission_outcome_unknown"
    assert len(calls) == 1


def test_transport_rejects_extra_or_inconsistent_remote_response_fields(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    profile = ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")
    transport = PinnedSshSmokeSubmissionTransport(root, Path("/usr/bin/ssh"), profile)
    base = dict(
        files={f"data/f{i}": "a" * 64 for i in range(72)},
        campaign="data/optimization/mot_2d/campaign",
        job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
        commit="a" * 40,
        submission_key="b" * 64,
    )
    responses = [
        {"status": "eligible", "branch": "main", "extra": "not allowed"},
        {"status": "eligible", "branch": "main", "job_id": "12345.zeus-master"},
        {"status": "ambiguous", "job_id": "12345.zeus-master", "nonce": "0" * 32, "branch": "main"},
        {"status": "submitted", "job_id": "12345.zeus-master", "branch": "main"},
    ]
    for response in responses:
        monkeypatch.setattr(
            "workflow_api.zeus_submission.subprocess.run",
            lambda argv, response=response, **kwargs: subprocess.CompletedProcess(
                argv, 0, json.dumps(response).encode(), b""
            ),
        )
        assert _code(lambda: transport.inspect(**base)) == "remote_response_invalid"


@pytest.mark.parametrize("timestamp", [-1, 253402300800, 2**40])
def test_transport_rejects_unrepresentable_submission_timestamps(tmp_path, monkeypatch, timestamp):
    root = tmp_path / "repo"
    root.mkdir()
    response = {
        "status": "submitted",
        "job_id": "12345.zeus-master",
        "nonce": "0" * 32,
        "submitted_unix_s": timestamp,
    }
    monkeypatch.setattr(
        "workflow_api.zeus_submission.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, json.dumps(response).encode(), b""),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root,
        Path("/usr/bin/ssh"),
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    assert _code(lambda: transport.submit(
        files={f"data/f{i}": "a" * 64 for i in range(72)},
        campaign="data/optimization/mot_2d/campaign",
        job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
        commit="a" * 40,
        submission_key="b" * 64,
        nonce="0" * 32,
    )) == "submission_outcome_unknown"


def test_remote_receiver_contains_only_fixed_smoke_qsub_and_no_mutating_admin_commands():
    # The trusted read-only Zeus probe resolved qsub to /usr/local/bin/qsub.
    # Verified script bytes are supplied on stdin so qsub cannot reopen a
    # swapped campaign path after validation.
    assert "['/usr/local/bin/qsub','-v','MOT_UI_SUBMISSION_ID='+nonce],30,job_bytes" in _REMOTE_SCRIPT
    assert "shell=False" in _REMOTE_SCRIPT
    for forbidden in ("qdel", "qalter", "git checkout", "git reset", "submit-stage", "screen.pbs", "refine.pbs"):
        assert forbidden not in _REMOTE_SCRIPT


def _receiver_fixture(tmp_path: Path, *, qsub_body: str | None = None):
    """Build a hermetic stand-in for the fixed Zeus receiver contract."""

    fake_home = tmp_path / "home" / "tal.noa"
    project = fake_home / "ytterbium_lab_simulation_new"
    campaign = Path("data/optimization/mot_2d/campaign")
    job_file = campaign / "jobs/01_smoke.pbs"
    files: dict[str, str] = {}
    for index in range(70):
        relative = Path("data/particle_states/after_zeeman/source") / f"artifact_{index:02d}.bin"
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"artifact-{index}\n".encode())
        files[relative.as_posix()] = _digest(target)
    manifest = project / campaign / "campaign.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"stage":"smoke"}\n', encoding="utf-8")
    job = project / job_file
    job.parent.mkdir(parents=True, exist_ok=True)
    job_bytes = b"#!/bin/bash\n#PBS -N mot2d_smoke\npython -m studies.mot_2d_s0_campaign smoke\n"
    job.write_bytes(job_bytes)
    files[manifest.relative_to(project).as_posix()] = _digest(manifest)
    files[job_file.as_posix()] = _digest(job)
    assert len(files) == 72

    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
        cwd=project,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()

    qsub = tmp_path / "fake-qsub"
    calls = tmp_path / "qsub-calls"
    captured = tmp_path / "qsub-stdin"
    body = qsub_body or f'''#!/bin/sh
printf 'call\\n' >> {str(calls)!r}
cat > {str(captured)!r}
printf '12345.zeus-master\\n'
'''
    qsub.write_text(body, encoding="utf-8")
    qsub.chmod(0o700)
    script = _REMOTE_SCRIPT.replace("'/usr/local/bin/qsub'", repr(str(qsub)))
    script = script.replace(
        "home=pathlib.Path('/home')/username",
        f"home=pathlib.Path({str(fake_home)!r})",
    )
    base_request = {
        "files": files,
        "campaign": campaign.as_posix(),
        "job_file": job_file.as_posix(),
        "commit": commit,
        "submission_key": "b" * 64,
    }

    def invoke(operation: str, nonce: str | None = None) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
        request = {**base_request, "nonce": nonce}
        encoded = base64.urlsafe_b64encode(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).decode("ascii")
        result = subprocess.run(
            [sys.executable, "-c", script, operation, "tal.noa", str(project), encoded],
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return result, json.loads(result.stdout.decode("utf-8"))

    return project, campaign, job_bytes, calls, captured, invoke


def test_embedded_receiver_submits_verified_bytes_once_and_replays_receipt(tmp_path):
    project, campaign, job_bytes, calls, captured, invoke = _receiver_fixture(tmp_path)
    inspected, state = invoke("inspect")
    assert inspected.returncode == 0 and state["status"] == "eligible"

    first, state = invoke("submit", "1" * 32)
    assert first.returncode == 0
    assert state == {
        "job_id": "12345.zeus-master",
        "nonce": "1" * 32,
        "status": "submitted",
        "submitted_unix_s": state["submitted_unix_s"],
    }
    assert captured.read_bytes() == job_bytes
    assert calls.read_text(encoding="utf-8").splitlines() == ["call"]
    receipt = json.loads((project / campaign / ".workflow/submissions/smoke.json").read_text())
    assert receipt["job_id"] == "12345.zeus-master" and receipt["nonce"] == "1" * 32

    replay, replay_state = invoke("submit", "2" * 32)
    assert replay.returncode == 0
    assert replay_state["status"] == "submitted" and replay_state["nonce"] == "1" * 32
    assert calls.read_text(encoding="utf-8").splitlines() == ["call"]


@pytest.mark.parametrize(
    "qsub_body",
    [
        "#!/bin/sh\ncat >/dev/null\nexit 1\n",
        "#!/bin/sh\ncat >/dev/null\nprintf 'not-a-job-id\\n'\n",
    ],
)
def test_embedded_receiver_qsub_failure_is_durably_ambiguous(tmp_path, qsub_body):
    project, campaign, _job_bytes, _calls, _captured, invoke = _receiver_fixture(
        tmp_path, qsub_body=qsub_body
    )
    submitted, state = invoke("submit", "3" * 32)
    assert submitted.returncode != 0 and state == {"error": "submission_ambiguous"}
    pending = project / campaign / ".workflow/submissions/smoke.pending.json"
    assert pending.is_file()
    repeated, repeated_state = invoke("submit", "4" * 32)
    assert repeated.returncode != 0 and repeated_state == {"error": "submission_ambiguous"}


def test_embedded_receiver_blocks_existing_smoke_and_corrupt_records(tmp_path):
    project, campaign, _job_bytes, _calls, _captured, invoke = _receiver_fixture(tmp_path)
    (project / campaign / "smoke").mkdir()
    checked, state = invoke("inspect")
    assert checked.returncode != 0 and state == {"error": "smoke_already_started"}
    (project / campaign / "smoke").rmdir()

    records = project / campaign / ".workflow/submissions"
    records.mkdir(parents=True)
    (records / "smoke.json").symlink_to(tmp_path / "outside-record")
    checked, state = invoke("inspect")
    assert checked.returncode != 0
    assert state in (
        {"error": "remote_preparation_invalid"},
        {"error": "submission_record_invalid"},
    )


@pytest.mark.parametrize("relative", ["sitecustomize.py", "data/evil.so"])
def test_embedded_receiver_rejects_untracked_python_runtime_shadow(tmp_path, relative):
    project, _campaign, _job_bytes, _calls, _captured, invoke = _receiver_fixture(tmp_path)
    shadow = project / relative
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("not part of the reviewed runtime\n", encoding="utf-8")
    checked, state = invoke("inspect")
    assert checked.returncode != 0 and state == {"error": "remote_preparation_invalid"}


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [(1, b""), (0, b"unexpected ssh diagnostic")],
)
def test_transport_rejects_success_json_with_failed_or_noisy_ssh(
    tmp_path, monkeypatch, returncode, stderr
):
    root = tmp_path / "repo"
    root.mkdir()
    response = {
        "status": "submitted",
        "job_id": "12345.zeus-master",
        "nonce": "0" * 32,
        "submitted_unix_s": 123,
    }
    monkeypatch.setattr(
        "workflow_api.zeus_submission.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, json.dumps(response).encode(), stderr
        ),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root,
        Path("/usr/bin/ssh"),
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    assert _code(
        lambda: transport.submit(
            files={f"data/f{i}": "a" * 64 for i in range(72)},
            campaign="data/optimization/mot_2d/campaign",
            job_file="data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
            commit="a" * 40,
            submission_key="b" * 64,
            nonce="0" * 32,
        )
    ) == "submission_outcome_unknown"

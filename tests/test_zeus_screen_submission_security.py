"""Adversarial tests for explicitly confirmed Screening submission."""

from __future__ import annotations

import threading
import subprocess
import json
import subprocess
from pathlib import Path

import pytest

from workflow_api.zeus_screen_submission import (
    MAX_PENDING_PREVIEWS,
    RemoteSubmissionState,
    ZeusScreenSubmissionCoordinator,
    ZeusScreenSubmissionError,
    PinnedSshScreenSubmissionTransport,
)
from workflow_api.zeus_submission import RepositoryRevisionService
from workflow_api.zeus_snapshot import ZeusProfile


class _Transport:
    def __init__(self, status="eligible"):
        self.status = status
        self.inspections = []
        self.submissions = []

    def inspect(self, **payload):
        self.inspections.append(payload)
        if self.status == "eligible":
            return RemoteSubmissionState("eligible", branch="main",
                                         validated_smoke_job_id="111.zeus-master")
        if self.status == "submitted":
            return RemoteSubmissionState("submitted", branch="main", job_id="222[].zeus-master",
                                         nonce="1" * 32, submitted_unix_s=100)
        return RemoteSubmissionState(self.status, branch="main", nonce="1" * 32)

    def submit(self, **payload):
        self.submissions.append(payload)
        return RemoteSubmissionState("submitted", job_id="222[].zeus-master",
                                     nonce=str(payload["nonce"]), submitted_unix_s=100)


def _coordinator(
    tmp_path,
    transport,
    *,
    clock=lambda: 100.0,
    token_factory=None,
):
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True, exist_ok=True)
    manifest = {"name": "Screen fixture", "s0_values": [1.3], "stage": "smoke"}
    prepared = {f"artifact-{index}": f"{index:064x}" for index in range(72)}
    transition = {"screen/tasks.json": "1" * 64, "jobs/02_screen.pbs": "2" * 64,
                  "campaign.json": "3" * 64}
    coordinator = ZeusScreenSubmissionCoordinator(
        tmp_path, Path("/usr/bin/ssh"), Path("/usr/bin/git"), clock=clock,
        token_factory=token_factory,
        transport_factory=lambda profile: transport,
    )
    coordinator._plan = lambda campaign_id: (
        campaign, manifest, "a" * 40, dict(prepared), dict(transition), "d" * 64, "e" * 64,
    )
    coordinator._revision = lambda: ("a" * 40, True)
    return coordinator, transition


def _request():
    return {"campaign_id": "mot_2d-id", "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}


def _code(callable_):
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        callable_()
    return caught.value.code


def test_preview_is_read_only_and_truthfully_describes_only_screening(tmp_path):
    transport = _Transport()
    coordinator, _ = _coordinator(tmp_path, transport)
    preview = coordinator.preview(_request(), session_id="owner")
    assert preview["stage"]["id"] == "screen"
    assert preview["job"]["kind"] == "array" and preview["job"]["task_count"] == 3
    assert preview["effects"] == {"submit_screening": True, "submit_later_stages": False,
                                  "modify_files": False}
    assert preview["later_stages_locked"] is True
    assert transport.submissions == []


@pytest.mark.parametrize("status,code", [
    ("ambiguous", "screening_submission_outcome_unknown"),
    ("submitted", "screening_already_submitted"),
])
def test_preview_blocks_ambiguous_or_existing_submission(tmp_path, status, code):
    transport = _Transport(status)
    coordinator, _ = _coordinator(tmp_path, transport)
    assert _code(lambda: coordinator.preview(_request(), session_id="owner")) == code
    assert transport.submissions == []


def test_confirmation_is_session_bound_expires_and_rechecks_exact_plan(tmp_path):
    now = [100.0]
    transport = _Transport()
    coordinator, transition = _coordinator(tmp_path, transport, clock=lambda: now[0])
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    assert _code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="intruder")) == "confirmation_invalid"
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    coordinator._plan = lambda campaign_id: (
        campaign, {"name": "Screen fixture", "s0_values": [1.3]}, "a" * 40,
        {f"artifact-{index}": f"{index:064x}" for index in range(72)},
        {**transition, "jobs/02_screen.pbs": "9" * 64}, "d" * 64, "e" * 64,
    )
    assert _code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "local_files_changed"
    assert transport.submissions == []

    coordinator, _ = _coordinator(tmp_path, transport, clock=lambda: now[0])
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    now[0] = 401.0
    assert _code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "confirmation_expired"
    assert transport.submissions == []


def test_success_is_at_most_once_and_exactly_bound(tmp_path):
    transport = _Transport()
    coordinator, _ = _coordinator(tmp_path, transport)
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    first = coordinator.confirm(request, session_id="owner")
    second = coordinator.confirm(request, session_id="owner")
    assert first == second
    assert first["job_id"] == "222[].zeus-master"
    assert first["later_stages_locked"] is True
    assert len(transport.submissions) == 1
    assert set(transport.submissions[0]) == {
        "campaign", "commit", "prepared_files", "transition_files",
        "transition_digest", "submission_key", "nonce",
    }


def test_concurrent_confirmation_calls_remote_submit_once(tmp_path):
    transport = _Transport()
    coordinator, _ = _coordinator(tmp_path, transport)
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    results, errors = [], []
    barrier = threading.Barrier(9)
    def confirm():
        try:
            barrier.wait()
            results.append(coordinator.confirm({"preview_token": token}, session_id="owner"))
        except Exception as error: errors.append(error)
    threads = [threading.Thread(target=confirm) for _ in range(8)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join(timeout=5)
    assert errors == [] and len(results) == 8
    assert len(transport.submissions) == 1


def test_receiver_has_only_fixed_qsub_and_no_git_or_scheduler_admin_mutation():
    source = (Path(__file__).parents[1] / "workflow_api/zeus_screen_submission_remote.py").read_text()
    lowered = source.lower()
    assert '["/usr/local/bin/qsub"' in source
    assert all(command not in lowered for command in (
        "qdel", "qalter", "qhold", "qrls", "git pull", "git checkout",
        "git switch", "git reset", "git merge", "git commit", "git push",
    ))


def test_untracked_importable_code_blocks_preview(tmp_path):
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    marker = tmp_path / "tracked.txt"
    marker.write_text("frozen\n", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    commit = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    transport = _Transport()
    coordinator, _ = _coordinator(tmp_path, transport)
    original_plan = coordinator._plan
    coordinator._plan = lambda campaign_id: (
        original_plan(campaign_id)[0], original_plan(campaign_id)[1], commit,
        original_plan(campaign_id)[3], original_plan(campaign_id)[4],
        original_plan(campaign_id)[5], original_plan(campaign_id)[6],
    )
    coordinator._revision = ZeusScreenSubmissionCoordinator._revision.__get__(coordinator)
    (tmp_path / "sitecustomize.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")
    assert _code(lambda: coordinator.preview(_request(), session_id="owner")) == "local_checkout_mismatch"
    assert transport.submissions == []


def test_public_revision_service_uses_exact_read_only_git_contract(tmp_path, monkeypatch):
    calls = []
    responses = [b"a" * 40 + b"\n", b""]

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=responses.pop(0), stderr=b"")

    monkeypatch.setattr("workflow_api.zeus_submission.subprocess.run", run)
    revision = RepositoryRevisionService(tmp_path, Path("/usr/bin/git")).inspect()

    assert revision.commit == "a" * 40 and revision.clean is True
    assert [call[0][1:] for call in calls] == [
        ["rev-parse", "--verify", "HEAD^{commit}"],
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    ]
    assert all(call[1]["cwd"] == tmp_path.resolve() for call in calls)
    assert all(call[1]["stdin"] is subprocess.DEVNULL and call[1]["shell"] is False for call in calls)
    assert all(call[1]["env"] == {
        "PATH": "/usr/bin", "HOME": str(Path.home()), "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    } for call in calls)


def test_public_revision_service_rejects_symlinked_generated_artifact(tmp_path):
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"; tracked.write_text("x", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    (tmp_path / "data").mkdir(); (tmp_path / "data/result.json").symlink_to(tracked)

    assert RepositoryRevisionService(tmp_path, Path("/usr/bin/git")).inspect().clean is False


def test_screen_submission_revision_wrapper_matches_public_service(tmp_path):
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"; tracked.write_text("x", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    public = RepositoryRevisionService(tmp_path, Path("/usr/bin/git")).inspect()
    coordinator = ZeusScreenSubmissionCoordinator(tmp_path, Path("/usr/bin/ssh"), Path("/usr/bin/git"))

    assert coordinator._revision() == (public.commit, public.clean)


@pytest.mark.parametrize("state", [
    RemoteSubmissionState("submitted", job_id="222.zeus-master", nonce="1" * 32,
                          submitted_unix_s=100),
    RemoteSubmissionState("submitted", job_id="222[].zeus-master", nonce="2" * 32,
                          submitted_unix_s=100),
    RemoteSubmissionState("submitted", job_id="222[].zeus-master", nonce="1" * 32,
                          submitted_unix_s=None),
])
def test_confirmation_fails_closed_on_noncanonical_or_mismatched_receipt(tmp_path, state):
    class BadTransport(_Transport):
        def submit(self, **payload):
            self.submissions.append(payload)
            return state

    transport = BadTransport()
    coordinator, _ = _coordinator(tmp_path, transport)
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _code(lambda: coordinator.confirm(
        request, session_id="owner")) == "screening_submission_outcome_unknown"
    assert _code(lambda: coordinator.confirm(
        request, session_id="owner")) == "screening_submission_outcome_unknown"
    assert len(transport.submissions) == 1


def test_screen_submission_preview_registry_capacity_boundary_and_expired_pop(tmp_path):
    now = [100.0]
    tokens = iter(f"token-{index}" for index in range(MAX_PENDING_PREVIEWS + 1))
    transport = _Transport()
    coordinator, _ = _coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: next(tokens),
    )
    for _ in range(MAX_PENDING_PREVIEWS):
        coordinator.preview(_request(), session_id="owner")
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    assert _code(lambda: coordinator.preview(
        _request(), session_id="owner")) == "too_many_pending_previews"
    assert transport.submissions == []

    now[0] = 400.0
    assert _code(lambda: coordinator.preview(
        _request(), session_id="owner")) == "too_many_pending_previews"
    now[0] = 401.0
    preview = coordinator.preview(_request(), session_id="owner")
    assert preview["preview_token"] == f"token-{MAX_PENDING_PREVIEWS}"
    assert len(coordinator._previews) == 1
    token = preview["preview_token"]
    assert _code(lambda: coordinator.confirm(
        {"preview_token": "missing"}, session_id="owner")) == "confirmation_invalid"
    assert _code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="other")) == "confirmation_invalid"
    now[0] = 702.0
    assert _code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "confirmation_expired"
    assert coordinator._previews.get(token) is None
    assert transport.submissions == []


def test_screen_submission_exact_expiry_boundary_is_confirmable(tmp_path):
    now = [100.0]
    transport = _Transport()
    coordinator, _ = _coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: "boundary-token",
    )
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    now[0] = 400.0
    assert coordinator.confirm(
        {"preview_token": token}, session_id="owner")["status"] == "submitted"
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("code,after_effect", [
    ("screening_submission_outcome_unknown", False),
    ("screening_submission_outcome_unknown", True),
    ("screening_already_submitted", False),
    ("screening_already_started", False),
    ("screening_submission_record_invalid", False),
])
def test_screen_submission_terminal_remote_error_is_never_retried(
    tmp_path, code, after_effect,
):
    class TerminalTransport(_Transport):
        def __init__(self):
            super().__init__()
            self.remote_effects = 0

        def submit(self, **payload):
            self.submissions.append(payload)
            if after_effect:
                self.remote_effects += 1
            raise ZeusScreenSubmissionError(code)

    transport = TerminalTransport()
    coordinator, _ = _coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "terminal-token",
    )
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert len(transport.submissions) == 1
    assert transport.remote_effects == (1 if after_effect else 0)
    record = coordinator._previews.get(token)
    assert record is not None and record.value.terminal_error == code
    assert record.value.nonce == transport.submissions[0]["nonce"]


@pytest.mark.parametrize("code", [
    "zeus_host_key_untrusted",
    "zeus_authentication_required",
    "zeus_unreachable",
    "screening_submission_busy",
    "screening_not_prepared",
    "remote_preparation_invalid",
])
def test_screen_submission_pre_effect_ssh_error_remains_safely_retryable(
    tmp_path, code,
):
    class RecoveringTransport(_Transport):
        def submit(self, **payload):
            self.submissions.append(payload)
            if len(self.submissions) == 1:
                raise ZeusScreenSubmissionError(code)
            return RemoteSubmissionState(
                "submitted",
                job_id="222[].zeus-master",
                nonce=str(payload["nonce"]),
                submitted_unix_s=100,
            )

    transport = RecoveringTransport()
    coordinator, _ = _coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "retryable-token",
    )
    token = coordinator.preview(_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _code(lambda: coordinator.confirm(request, session_id="owner")) == code
    record = coordinator._previews.get(token)
    assert record is not None and record.value.terminal_error is None
    assert coordinator.confirm(request, session_id="owner")["status"] == "submitted"
    assert len(transport.submissions) == 2
    assert transport.submissions[0]["nonce"] == transport.submissions[1]["nonce"]


def test_transport_rejects_extra_fields_and_loose_types(tmp_path, monkeypatch):
    profile = ZeusProfile.parse({
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), profile,
    )
    valid = {
        "status": "submitted", "version": 1, "submission_key": "a" * 64,
        "transition_digest": "b" * 64, "nonce": "1" * 32,
        "job_file": "data/optimization/mot_2d/c/jobs/02_screen.pbs",
        "commit": "c" * 40, "created_unix_s": 100,
        "job_id": "222[].zeus-master", "completed_unix_s": 101,
    }

    def response(payload):
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=(json.dumps(payload) + "\n").encode(), stderr=b"",
        ))
        return _code(lambda: transport.submit(
            campaign="data/optimization/mot_2d/c", commit="c" * 40,
            prepared_files={}, transition_files={}, transition_digest="b" * 64,
            submission_key="a" * 64, nonce="1" * 32,
        ))

    assert response({**valid, "unexpected": True}) == "screening_submission_outcome_unknown"
    assert response({**valid, "completed_unix_s": True}) == "screening_submission_outcome_unknown"
    assert response({**valid, "job_id": "222[0].zeus-master"}) == "screening_submission_outcome_unknown"


def test_receiver_checks_trust_anchor_parent_symlinks_and_rechecks_under_lock():
    source = (Path(__file__).parents[1] / "workflow_api/zeus_screen_submission_remote.py").read_text()
    receipt_read = source.index("transition_receipt=read_json")
    assert any("no_symlinks(campaign" in line
               for line in source[:receipt_read].splitlines()[-8:])
    lock_check = source.index('if current()["status"]!="eligible"')
    qsub = source.index('["/usr/local/bin/qsub"')
    assert source.index('if any(path.name!="tasks.json"', lock_check) < qsub

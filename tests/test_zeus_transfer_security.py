"""Adversarial contract tests for review-before-write Zeus preparation."""

from __future__ import annotations

import hashlib
import io
import base64
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from workflow_api.zeus_transfer import (
    MAX_REMOTE_OUTPUT,
    PinnedSshZeusPreparationTransport,
    RemoteSnapshot,
    ZeusPreparationError,
    ZeusPreparationService,
    _REMOTE_TRANSFER_SCRIPT,
)
from workflow_api.zeus_snapshot import ZeusProfile


COMMIT = "a" * 40


class RecordingTransport:
    def __init__(self, *, artifacts=None, commit=COMMIT, clean=True):
        self.artifacts = dict(artifacts or {})
        self.commit = commit
        self.clean = clean
        self.inspections = []
        self.input_uploads = []
        self.campaign_publications = []

    def inspect(self, paths):
        self.inspections.append(paths)
        return RemoteSnapshot(self.commit, self.clean, dict(self.artifacts))

    def upload_missing_inputs(self, files, expected_commit):
        assert expected_commit == self.commit
        self.input_uploads.append(dict(files))
        self.artifacts.update({path: digest(local[0]) for path, local in files.items()})

    def publish_campaign_atomic(self, files, expected_commit):
        assert expected_commit == self.commit
        self.campaign_publications.append(dict(files))
        self.artifacts.update({path: digest(local[0]) for path, local in files.items()})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initialize_git_repository(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-qm", "initial"], check=True)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def portable_campaign(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/campaign"
    inputs = root / "data/particle_states/after_zeeman/profile"
    (campaign / "jobs").mkdir(parents=True)
    inputs.mkdir(parents=True)
    roles = {"all": []}
    for seed in range(3000, 3035):
        state = inputs / f"seed-{seed}.npy"
        metadata = inputs / f"seed-{seed}.json"
        state.write_bytes(f"state-{seed}".encode())
        metadata.write_text(json.dumps({"seed": seed}), encoding="utf-8")
        roles["all"].append({
            "zeeman_seed": seed,
            "path": state.relative_to(root).as_posix(),
            "metadata_path": metadata.relative_to(root).as_posix(),
            "sha256": digest(state),
            "metadata_sha256": digest(metadata),
        })
    manifest = {
        "kind": "mot_2d_s0_campaign",
        "stage": "smoke",
        "provenance": {"git_commit": COMMIT},
        "input_ensembles": roles,
    }
    (campaign / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")
    (campaign / "jobs/01_smoke.pbs").write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    monkeypatch.setattr("workflow_api.zeus_transfer.modern_contract", lambda *_: (True, ()))
    return root, campaign, manifest


def error_code(callable_):
    with pytest.raises(ZeusPreparationError) as caught:
        callable_()
    return caught.value.code


def test_preview_is_read_only_and_exactly_plans_70_inputs_plus_two_campaign_files(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    transport = RecordingTransport()
    preview = ZeusPreparationService(root, transport).preview(campaign, session_id="session")

    assert len(preview.files) == 72
    assert all(item.action == "upload" for item in preview.files)
    assert transport.input_uploads == []
    assert transport.campaign_publications == []
    assert len(transport.inspections) == 1
    assert tuple(sorted(item.path for item in preview.files)) == transport.inspections[0]
    assert not any(word in repr(transport.inspections).lower() for word in ("qsub", "qdel", "git reset", "simulate"))


@pytest.mark.parametrize("clean,commit", [(False, COMMIT), (True, "b" * 40)])
def test_preview_blocks_dirty_or_wrong_remote_checkout(tmp_path, monkeypatch, clean, commit):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    transport = RecordingTransport(clean=clean, commit=commit)
    service = ZeusPreparationService(root, transport)

    assert error_code(lambda: service.preview(campaign, session_id="session")) == "remote_checkout_mismatch"
    assert transport.input_uploads == []
    assert transport.campaign_publications == []


def test_existing_identical_files_are_reused_and_existing_different_input_is_blocked(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    first = RecordingTransport()
    preview = ZeusPreparationService(root, first).preview(campaign, session_id="session")
    all_hashes = {item.path: item.sha256 for item in preview.files}

    identical = RecordingTransport(artifacts=all_hashes)
    service = ZeusPreparationService(root, identical)
    reused = service.preview(campaign, session_id="session")
    result = service.confirm(reused.token, session_id="session")
    assert reused.already_prepared is True
    assert result.status == "already_prepared"
    assert result.uploaded_count == 0 and result.reused_count == 72
    assert identical.input_uploads == [] and identical.campaign_publications == []

    input_path = next(item.path for item in preview.files if "/after_zeeman/" in item.path)
    conflicting = RecordingTransport(artifacts={input_path: "f" * 64})
    assert error_code(lambda: ZeusPreparationService(root, conflicting).preview(campaign, session_id="s")) == "remote_input_conflict"
    assert conflicting.input_uploads == [] and conflicting.campaign_publications == []


def test_partial_or_different_existing_campaign_is_blocked_without_writes(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    baseline = ZeusPreparationService(root, RecordingTransport()).preview(campaign, session_id="s")
    campaign_files = [item for item in baseline.files if item.path.startswith("data/optimization/")]

    partial = RecordingTransport(artifacts={campaign_files[0].path: campaign_files[0].sha256})
    assert error_code(lambda: ZeusPreparationService(root, partial).preview(campaign, session_id="s")) == "remote_campaign_conflict"

    different = RecordingTransport(artifacts={campaign_files[0].path: "e" * 64})
    assert error_code(lambda: ZeusPreparationService(root, different).preview(campaign, session_id="s")) == "remote_campaign_conflict"
    assert partial.input_uploads == different.input_uploads == []
    assert partial.campaign_publications == different.campaign_publications == []


def test_preview_rejects_traversal_symlink_and_non_regular_input(tmp_path, monkeypatch):
    root, campaign, manifest = portable_campaign(tmp_path, monkeypatch)
    record = manifest["input_ensembles"]["all"][0]

    record["path"] = "data/particle_states/after_zeeman/../../escape.npy"
    (campaign / "campaign.json").write_text(json.dumps(manifest))
    assert error_code(lambda: ZeusPreparationService(root, RecordingTransport()).preview(campaign, session_id="s")) == "campaign_inputs_invalid"

    root, campaign, manifest = portable_campaign(tmp_path / "symlink", monkeypatch)
    record = manifest["input_ensembles"]["all"][0]
    original = root / record["path"]
    target = root / "target.npy"
    target.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(target)
    (campaign / "campaign.json").write_text(json.dumps(manifest))
    assert error_code(lambda: ZeusPreparationService(root, RecordingTransport()).preview(campaign, session_id="s")) == "campaign_inputs_invalid"

    root, campaign, manifest = portable_campaign(tmp_path / "directory", monkeypatch)
    record = manifest["input_ensembles"]["all"][0]
    original = root / record["path"]
    original.unlink()
    original.mkdir()
    (campaign / "campaign.json").write_text(json.dumps(manifest))
    assert error_code(lambda: ZeusPreparationService(root, RecordingTransport()).preview(campaign, session_id="s")) == "campaign_inputs_invalid"


def test_local_hash_or_size_change_between_preview_and_confirm_fails_closed(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    transport = RecordingTransport()
    service = ZeusPreparationService(root, transport)
    preview = service.preview(campaign, session_id="session")
    changed = root / next(item.path for item in preview.files if item.path.endswith("seed-3000.npy"))
    changed.write_bytes(b"changed-and-longer")

    assert error_code(lambda: service.confirm(preview.token, session_id="session")) in {
        "campaign_inputs_changed", "local_files_changed",
    }
    assert transport.input_uploads == [] and transport.campaign_publications == []


def test_confirmation_is_session_bound_expires_and_is_idempotent(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    now = [100.0]
    transport = RecordingTransport()
    service = ZeusPreparationService(root, transport, clock=lambda: now[0], token_lifetime=10)
    preview = service.preview(campaign, session_id="owner")
    assert error_code(lambda: service.confirm(preview.token, session_id="other")) == "confirmation_invalid"
    assert error_code(lambda: service.confirm("unknown", session_id="owner")) == "confirmation_invalid"
    now[0] = 111
    assert error_code(lambda: service.confirm(preview.token, session_id="owner")) == "confirmation_expired"
    assert transport.input_uploads == [] and transport.campaign_publications == []

    now[0] = 200
    preview = service.preview(campaign, session_id="owner")
    first = service.confirm(preview.token, session_id="owner")
    second = service.confirm(preview.token, session_id="owner")
    assert first == second
    assert len(transport.input_uploads) == 1
    assert len(transport.campaign_publications) == 1


def test_remote_response_must_be_bounded_to_requested_paths_and_valid_hashes(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    unknown = RecordingTransport(artifacts={"data/particle_states/after_zeeman/other": "a" * 64})
    invalid_hash = RecordingTransport(artifacts={"data/particle_states/after_zeeman/profile/seed-3000.npy": "not-a-hash"})

    assert error_code(lambda: ZeusPreparationService(root, unknown).preview(campaign, session_id="s")) == "remote_response_invalid"
    assert error_code(lambda: ZeusPreparationService(root, invalid_hash).preview(campaign, session_id="s")) == "remote_response_invalid"


def test_inputs_are_uploaded_before_atomic_campaign_publication(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)
    events = []

    class OrderedTransport(RecordingTransport):
        def upload_missing_inputs(self, files, expected_commit):
            events.append(("inputs", tuple(files)))
            super().upload_missing_inputs(files, expected_commit)

        def publish_campaign_atomic(self, files, expected_commit):
            events.append(("campaign", tuple(files)))
            super().publish_campaign_atomic(files, expected_commit)

    transport = OrderedTransport()
    service = ZeusPreparationService(root, transport)
    preview = service.preview(campaign, session_id="s")
    result = service.confirm(preview.token, session_id="s")

    assert [event[0] for event in events] == ["inputs", "campaign"]
    assert len(events[0][1]) == 70 and len(events[1][1]) == 2
    assert result.to_dict()["job_submitted"] is False


def test_uploaded_inputs_are_reinspected_before_campaign_publication(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)

    class CorruptingTransport(RecordingTransport):
        def upload_missing_inputs(self, files, expected_commit):
            self.input_uploads.append(dict(files))
            self.artifacts.update({path: digest(local[0]) for path, local in files.items()})
            first = next(iter(files))
            self.artifacts[first] = "0" * 64

    transport = CorruptingTransport()
    service = ZeusPreparationService(root, transport)
    preview = service.preview(campaign, session_id="s")

    assert error_code(lambda: service.confirm(preview.token, session_id="s")) == "remote_input_conflict"
    assert len(transport.inspections) >= 3  # preview, pre-write confirmation, post-upload verification
    assert transport.campaign_publications == []


def test_interrupted_input_upload_never_publishes_campaign(tmp_path, monkeypatch):
    root, campaign, _ = portable_campaign(tmp_path, monkeypatch)

    class InterruptedTransport(RecordingTransport):
        def upload_missing_inputs(self, files, expected_commit):
            super().upload_missing_inputs(files, expected_commit)
            raise OSError("connection lost")

    transport = InterruptedTransport()
    service = ZeusPreparationService(root, transport)
    preview = service.preview(campaign, session_id="s")
    with pytest.raises(OSError, match="connection lost"):
        service.confirm(preview.token, session_id="s")
    assert transport.campaign_publications == []


def test_pinned_ssh_transport_uses_fixed_argv_and_never_a_shell(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    ssh = tmp_path / "ssh"; ssh.write_text("#!/bin/sh\nexit 0\n"); ssh.chmod(0o700)
    profile = ZeusProfile(username="tal.noa", project_directory="/home/tal.noa/ytterbium_lab_simulation_new")
    observed = {}

    class Process:
        def __init__(self, argv, **kwargs):
            observed["argv"] = argv; observed["kwargs"] = kwargs
            self.stdin = io.BytesIO(); self.stdout = io.BytesIO(json.dumps({
                "git_commit": COMMIT, "clean": True, "artifacts": {},
            }).encode()); self.stderr = io.BytesIO(); self.returncode = 0
        def wait(self, timeout=None): return self.returncode
        def kill(self): self.returncode = -9

    def popen(argv, **kwargs):
        observed["argv"] = argv; observed["kwargs"] = kwargs
        return Process(argv, **kwargs)

    monkeypatch.setattr("workflow_api.zeus_transfer.subprocess.Popen", popen)
    transport = PinnedSshZeusPreparationTransport(root, ssh, profile, COMMIT)
    snapshot = transport.inspect(("data/particle_states/after_zeeman/profile/a.npy",))

    assert snapshot.git_commit == COMMIT
    assert observed["argv"][0] == str(ssh.resolve())
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"]["cwd"] == root.resolve()
    assert observed["kwargs"]["env"]["PATH"] == str(ssh.parent)
    joined = " ".join(observed["argv"])
    assert "BatchMode=yes" in joined and "PasswordAuthentication=no" in joined
    assert "ForwardAgent=no" in joined and "ClearAllForwardings=yes" in joined
    assert all(command not in joined for command in ("qsub", "qdel", "git reset", "git checkout"))


def test_pinned_ssh_transport_caps_stdout_and_rejects_malformed_schema(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    ssh = tmp_path / "ssh"; ssh.write_text("#!/bin/sh\nexit 0\n"); ssh.chmod(0o700)
    profile = ZeusProfile(username="tal.noa", project_directory="/home/tal.noa/project")
    transport = PinnedSshZeusPreparationTransport(root, ssh, profile, COMMIT)

    class Process:
        def __init__(self, output):
            self.stdin = io.BytesIO(); self.stdout = io.BytesIO(output); self.stderr = io.BytesIO(); self.returncode = 0
        def wait(self, timeout=None): return self.returncode
        def kill(self): self.returncode = -9

    monkeypatch.setattr("workflow_api.zeus_transfer.subprocess.Popen", lambda *a, **k: Process(b"x" * (MAX_REMOTE_OUTPUT + 1)))
    assert error_code(lambda: transport.inspect(())) == "remote_response_invalid"

    malformed = json.dumps({"git_commit": COMMIT, "clean": True, "artifacts": {}, "extra": 1}).encode()
    monkeypatch.setattr("workflow_api.zeus_transfer.subprocess.Popen", lambda *a, **k: Process(malformed))
    assert error_code(lambda: transport.inspect(())) == "remote_response_invalid"


def test_transport_rejects_oversize_payload_before_ssh(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    ssh = tmp_path / "ssh"; ssh.write_text("#!/bin/sh\nexit 0\n"); ssh.chmod(0o700)
    profile = ZeusProfile(username="tal.noa", project_directory="/home/tal.noa/project")
    transport = PinnedSshZeusPreparationTransport(root, ssh, profile, COMMIT)
    called = []
    monkeypatch.setattr("workflow_api.zeus_transfer.subprocess.run", lambda *a, **k: called.append(True))

    assert error_code(lambda: transport._run("inputs", (), b"x" * (128 * 1024 * 1024 + 1))) == "transfer_too_large"
    assert called == []


def test_transport_payload_is_bound_to_reviewed_digest_and_size(tmp_path):
    source = tmp_path / "source.npy"
    source.write_bytes(b"reviewed")
    reviewed = (source, digest(source), source.stat().st_size)
    source.write_bytes(b"changed-after-review")

    assert error_code(
        lambda: PinnedSshZeusPreparationTransport._payload({"data/particle_states/after_zeeman/p/source.npy": reviewed})
    ) == "local_files_changed"


@pytest.mark.skipif(sys.platform != "linux", reason="Zeus uses Linux renameat2(RENAME_NOREPLACE)")
def test_remote_receiver_atomically_publishes_complete_campaign_and_never_replaces(tmp_path):
    # Substitute only the synthetic test home. The transfer and publication code
    # remains byte-for-byte the production receiver executed through SSH.
    project = tmp_path / "home" / "tester" / "project"
    project.mkdir(parents=True)
    commit = initialize_git_repository(project)
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    paths = (
        "data/optimization/mot_2d/campaign/campaign.json",
        "data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
    )
    contents = (b'{"kind":"mot_2d_s0_campaign"}', b"#!/bin/bash\ntrue\n")
    payload = bytearray()
    for content in contents:
        payload.extend(struct.pack("!Q", len(content)))
        payload.extend(hashlib.sha256(content).hexdigest().encode("ascii"))
        payload.extend(content)
    encoded = base64.urlsafe_b64encode(json.dumps(paths).encode()).decode()
    argv = ["python3", "-c", script, "campaign", "tester", str(project), encoded, commit]

    first = subprocess.run(argv, input=bytes(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert first.returncode == 0, first.stderr.decode()
    assert json.loads(first.stdout) == {"ok": True}
    final = project / "data/optimization/mot_2d/campaign"
    assert (final / "campaign.json").read_bytes() == contents[0]
    assert (final / "jobs/01_smoke.pbs").read_bytes() == contents[1]
    assert not list(final.parent.glob(".zeus-campaign-*"))

    second = subprocess.run(argv, input=bytes(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert second.returncode == 23
    assert json.loads(second.stdout) == {"error": "target_exists"}
    assert (final / "campaign.json").read_bytes() == contents[0]


def test_remote_receiver_verifies_input_digest_and_never_replaces(tmp_path):
    project = tmp_path / "home" / "tester" / "project"
    project.mkdir(parents=True)
    commit = initialize_git_repository(project)
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    path = "data/particle_states/after_zeeman/profile/seed.npy"
    content = b"trusted ensemble bytes"
    encoded = base64.urlsafe_b64encode(json.dumps([path]).encode()).decode()

    def framed(expected_digest):
        return struct.pack("!Q", len(content)) + expected_digest.encode("ascii") + content

    argv = ["python3", "-c", script, "inputs", "tester", str(project), encoded, commit]
    wrong = subprocess.run(argv, input=framed("0" * 64), stdout=subprocess.PIPE, check=False)
    assert wrong.returncode == 24
    assert not (project / path).exists()

    correct = subprocess.run(argv, input=framed(hashlib.sha256(content).hexdigest()), stdout=subprocess.PIPE, check=False)
    assert correct.returncode == 0
    assert (project / path).read_bytes() == content

    repeated = subprocess.run(argv, input=framed(hashlib.sha256(b"different").hexdigest()), stdout=subprocess.PIPE, check=False)
    assert repeated.returncode == 23
    assert (project / path).read_bytes() == content


def test_remote_receiver_rechecks_commit_before_any_write(tmp_path):
    project = tmp_path / "home" / "tester" / "project"
    project.mkdir(parents=True)
    commit = initialize_git_repository(project)
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    path = "data/particle_states/after_zeeman/profile/seed.npy"
    content = b"trusted ensemble bytes"
    encoded = base64.urlsafe_b64encode(json.dumps([path]).encode()).decode()
    payload = struct.pack("!Q", len(content)) + hashlib.sha256(content).hexdigest().encode() + content

    result = subprocess.run(
        ["python3", "-c", script, "inputs", "tester", str(project), encoded, "0" * 40],
        input=payload, stdout=subprocess.PIPE, check=False,
    )
    assert result.returncode == 25
    assert json.loads(result.stdout) == {"error": "remote_checkout_mismatch"}
    assert not (project / path).exists()
    assert commit != "0" * 40


def test_remote_receiver_parent_fd_prevents_symlink_swap_redirection(tmp_path):
    project = tmp_path / "home" / "tester" / "project"
    profile = project / "data/particle_states/after_zeeman/profile"
    outside = tmp_path / "outside"
    profile.mkdir(parents=True)
    outside.mkdir()
    commit = initialize_git_repository(project)
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    path = "data/particle_states/after_zeeman/profile/seed.npy"
    content = b"x" * (1024 * 1024)
    encoded = base64.urlsafe_b64encode(json.dumps([path]).encode()).decode()
    process = subprocess.Popen(
        ["python3", "-c", script, "inputs", "tester", str(project), encoded, commit],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(struct.pack("!Q", len(content)) + hashlib.sha256(content).hexdigest().encode())
    process.stdin.flush()
    deadline = time.monotonic() + 5
    while not list(profile.glob(".zeus-transfer-*")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert list(profile.glob(".zeus-transfer-*")), "receiver did not open its dirfd in time"
    original = profile.with_name("profile-original")
    profile.rename(original)
    profile.symlink_to(outside, target_is_directory=True)
    process.stdin.write(content)
    process.stdin.close()
    assert process.wait(timeout=5) == 0, process.stderr.read().decode()
    assert not (outside / "seed.npy").exists()
    assert (original / "seed.npy").read_bytes() == content


def test_remote_receiver_rechecks_tracked_cleanliness_after_receiving_before_input_publish(tmp_path):
    project = tmp_path / "home" / "tester" / "project"
    project.mkdir(parents=True)
    initialize_git_repository(project)
    sentinel = project / "tracked.txt"
    sentinel.write_text("clean", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "track sentinel"], check=True)
    commit = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    path = "data/particle_states/after_zeeman/profile/seed.npy"
    content = b"x" * (1024 * 1024)
    encoded = base64.urlsafe_b64encode(json.dumps([path]).encode()).decode()
    process = subprocess.Popen(
        ["python3", "-c", script, "inputs", "tester", str(project), encoded, commit],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(struct.pack("!Q", len(content)) + hashlib.sha256(content).hexdigest().encode())
    process.stdin.flush()
    transfer_dir = project / "data/particle_states/after_zeeman/profile"
    deadline = time.monotonic() + 5
    while not list(transfer_dir.glob(".zeus-transfer-*")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert list(transfer_dir.glob(".zeus-transfer-*"))
    sentinel.write_text("dirty during transfer", encoding="utf-8")
    process.stdin.write(content)
    process.stdin.close()
    assert process.wait(timeout=5) == 25, process.stderr.read().decode()
    assert json.loads(process.stdout.read()) == {"error": "remote_checkout_mismatch"}
    assert not (project / path).exists()
    assert not list(transfer_dir.glob(".zeus-transfer-*"))


def test_remote_receiver_rechecks_head_after_receiving_before_campaign_publish(tmp_path):
    project = tmp_path / "home" / "tester" / "project"
    project.mkdir(parents=True)
    commit = initialize_git_repository(project)
    script = _REMOTE_TRANSFER_SCRIPT.replace(
        "home = pathlib.Path('/home') / username",
        "home = project.resolve().parent",
    )
    paths = (
        "data/optimization/mot_2d/campaign/campaign.json",
        "data/optimization/mot_2d/campaign/jobs/01_smoke.pbs",
    )
    contents = (b'{"kind":"mot_2d_s0_campaign"}', b"#!/bin/bash\ntrue\n")
    encoded = base64.urlsafe_b64encode(json.dumps(paths).encode()).decode()
    process = subprocess.Popen(
        ["python3", "-c", script, "campaign", "tester", str(project), encoded, commit],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    first = contents[0]
    process.stdin.write(struct.pack("!Q", len(first)) + hashlib.sha256(first).hexdigest().encode())
    process.stdin.flush()
    campaign_parent = project / "data/optimization/mot_2d"
    deadline = time.monotonic() + 5
    while not list(campaign_parent.glob(".zeus-campaign-*/.zeus-transfer-*")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert list(campaign_parent.glob(".zeus-campaign-*/.zeus-transfer-*"))
    subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-qm", "move head"], check=True)
    process.stdin.write(first)
    second = contents[1]
    process.stdin.write(struct.pack("!Q", len(second)) + hashlib.sha256(second).hexdigest().encode() + second)
    process.stdin.close()
    assert process.wait(timeout=5) == 25, process.stderr.read().decode()
    assert json.loads(process.stdout.read()) == {"error": "remote_checkout_mismatch"}
    assert not (campaign_parent / "campaign").exists()
    assert not list(campaign_parent.glob(".zeus-campaign-*"))

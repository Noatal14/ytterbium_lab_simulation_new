import hashlib
import json
import subprocess
import threading
import time
import io
from pathlib import Path

import numpy as np
import pytest

from workflow_api.mot_2d_plan import RELEVANT_FILES, build_plan, materialize, physical_model_hash, plan_from_frozen_manifest
from workflow_api.mot_2d_sources import inspect_source
from workflow_api.repository_snapshot import RepositorySnapshot, RepositorySnapshotProvider
from workflow_api.discovery import list_campaigns
from workflow_api.mutation import CreationService


class FixedSnapshots:
    def __init__(self, commit="a" * 40): self.value = RepositorySnapshot(commit)
    def capture(self): return self.value


def source(root: Path):
    directory = root / "data/particle_states/after_zeeman/source"; directory.mkdir(parents=True)
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"; np.save(state, np.zeros((1, 6)))
        digest = hashlib.sha256(state.read_bytes()).hexdigest()
        state.with_suffix(".json").write_text(json.dumps({"shape": [1, 6], "dtype": "float64", "n_survivors": 1, "output_sha256": digest, "parameters": {"seed": seed, "resolved_zeeman_magnet_profile": "profile", "n_initial_atoms": 50000, "dt_s": 4e-5}, "software": {"git_commit": "source"}}))
    return inspect_source(directory, root)


def repository(root: Path):
    for relative in RELEVANT_FILES:
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(relative)
    lab = root / "lab_setup/model.py"; lab.parent.mkdir(); lab.write_text("MODEL = 1")


def test_plan_is_pure_and_materialization_is_atomic(tmp_path):
    repository(tmp_path); frozen = source(tmp_path)
    plan = build_plan(tmp_path, name="Fixed 1.3", slug="s0_1p3", s0_values=[1.3, 1.3], source=frozen, snapshot=RepositorySnapshot("a" * 40))
    assert not plan.destination.exists()
    assert plan.s0_values == (1.3,)
    assert set(plan.files) == {"campaign.json", "jobs/01_smoke.pbs"}
    assert b"qsub" not in plan.files["jobs/01_smoke.pbs"]
    cli_plan = plan_from_frozen_manifest(repository_root=tmp_path, destination=plan.destination, manifest=plan.manifest)
    assert cli_plan.files == plan.files
    materialize(plan)
    assert (plan.destination / "campaign.json").is_file()
    assert not list(plan.destination.parent.glob(".*.creating-*"))
    record = list_campaigns(tmp_path)["campaigns"][0]
    assert record["trust"] == "trusted-current"
    assert record["stage"] == "smoke"


def test_materialize_race_creates_exactly_once(tmp_path):
    repository(tmp_path); plan = build_plan(tmp_path, name="Race", slug="race", s0_values=[1.3], source=source(tmp_path), snapshot=RepositorySnapshot("a" * 40))
    outcomes = []
    def run():
        try: materialize(plan); outcomes.append("created")
        except (FileExistsError, FileNotFoundError): outcomes.append("blocked")
    threads = [threading.Thread(target=run) for _ in range(2)]
    for item in threads: item.start()
    for item in threads: item.join()
    assert sorted(outcomes) == ["blocked", "created"]


def test_snapshot_provider_allows_only_clean_fixed_paths(tmp_path):
    repository(tmp_path)
    subprocess.run(["/usr/bin/git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["/usr/bin/git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "-c", "user.name=test", "-c", "user.email=test@example", "commit", "-m", "initial"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    provider = RepositorySnapshotProvider(tmp_path, Path("/usr/bin/git"))
    assert len(provider.capture().commit) == 40
    (tmp_path / "config.py").write_text("dirty")
    with pytest.raises(RuntimeError, match="uncommitted"):
        provider.capture()


def test_planner_is_in_clean_guard_and_physical_model_hash(tmp_path):
    repository(tmp_path)
    before, names = physical_model_hash(tmp_path)
    planner = tmp_path / "workflow_api/mot_2d_plan.py"
    assert "workflow_api/mot_2d_plan.py" in names
    planner.write_text("changed planner")
    after, _ = physical_model_hash(tmp_path)
    assert after != before
    subprocess.run(["/usr/bin/git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["/usr/bin/git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["/usr/bin/git", "-c", "user.name=test", "-c", "user.email=test@example", "commit", "-m", "initial"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    provider = RepositorySnapshotProvider(tmp_path, Path("/usr/bin/git"))
    planner.write_text("dirty planner")
    with pytest.raises(RuntimeError, match="uncommitted"):
        provider.capture()


def test_snapshot_provider_rejects_repository_execution_helpers(tmp_path):
    repository(tmp_path)
    subprocess.run(["/usr/bin/git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    (tmp_path / ".git/config").write_text("[core]\n\tfsmonitor = /tmp/unsafe\n")
    with pytest.raises(ValueError, match="unsupported helpers"):
        RepositorySnapshotProvider(tmp_path, Path("/usr/bin/git"))


def service(tmp_path):
    repository(tmp_path); selected = source(tmp_path)
    return CreationService(tmp_path, FixedSnapshots()), selected


def request(selected, slug="campaign"):
    return {"name": "Fixed s0 1.3", "slug": slug, "s0_values": [1.3, 1.3], "source_id": selected["id"]}


def test_preview_is_zero_write_confirm_is_idempotent_and_duplicate_is_blocked(tmp_path):
    creator, selected = service(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    preview = creator.preview(request(selected), "session")
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    result = creator.confirm(preview["preview_token"], "session")
    assert result["submitted_to_zeus"] is False
    assert creator.confirm(preview["preview_token"], "session") == result
    duplicate = creator.preview(request(selected, slug="different-name"), "session")
    assert duplicate["preview_token"] is None
    assert duplicate["duplicate"]["campaign_id"] == result["campaign_id"]


def test_preview_token_is_session_bound_stale_and_terminal(tmp_path):
    creator, selected = service(tmp_path)
    preview = creator.preview(request(selected), "one")
    with pytest.raises(PermissionError): creator.confirm(preview["preview_token"], "two")
    creator.snapshots.value = RepositorySnapshot("b" * 40)
    with pytest.raises(RuntimeError, match="stale"): creator.confirm(preview["preview_token"], "one")
    creator.snapshots.value = RepositorySnapshot("a" * 40)
    with pytest.raises(RuntimeError, match="no longer"): creator.confirm(preview["preview_token"], "one")


def test_expired_token_and_schema_fail_closed(tmp_path, monkeypatch):
    creator, selected = service(tmp_path)
    with pytest.raises(ValueError): creator.preview({**request(selected), "password": "secret"}, "session")
    preview = creator.preview(request(selected), "session")
    for pending in creator._pending.values(): pending.expires = time.monotonic() - 1
    with pytest.raises(PermissionError): creator.confirm(preview["preview_token"], "session")


def test_materialize_fault_leaves_no_visible_campaign(tmp_path, monkeypatch):
    repository(tmp_path)
    plan = build_plan(tmp_path, name="Fault", slug="fault", s0_values=[1.3], source=source(tmp_path), snapshot=RepositorySnapshot("a" * 40))
    monkeypatch.setattr("workflow_api.mot_2d_plan._rename_no_replace", lambda *_: (_ for _ in ()).throw(OSError("fault")))
    with pytest.raises(OSError, match="fault"): materialize(plan)
    assert not plan.destination.exists()
    assert not list(plan.destination.parent.glob(".*.creating-*"))
    assert not list(plan.destination.parent.glob("*.lock"))


def test_staged_validation_failure_never_publishes(tmp_path):
    repository(tmp_path)
    plan = build_plan(tmp_path, name="Invalid", slug="invalid", s0_values=[1.3], source=source(tmp_path), snapshot=RepositorySnapshot("a" * 40))
    with pytest.raises(RuntimeError, match="staged"):
        materialize(plan, lambda staged: (_ for _ in ()).throw(RuntimeError("staged validation failed")))
    assert not plan.destination.exists()


def test_competing_destination_is_never_replaced(tmp_path, monkeypatch):
    repository(tmp_path)
    plan = build_plan(tmp_path, name="Race", slug="external-race", s0_values=[1.3], source=source(tmp_path), snapshot=RepositorySnapshot("a" * 40))
    from workflow_api import mot_2d_plan
    original = mot_2d_plan._rename_no_replace
    def compete(staged, destination):
        destination.mkdir(); (destination / "owned-by-other-process").write_text("keep")
        original(staged, destination)
    monkeypatch.setattr(mot_2d_plan, "_rename_no_replace", compete)
    with pytest.raises(FileExistsError): materialize(plan)
    assert (plan.destination / "owned-by-other-process").read_text() == "keep"


def test_parent_fsync_failure_after_publish_is_recoverable_success(tmp_path, monkeypatch):
    repository(tmp_path)
    plan = build_plan(tmp_path, name="Durable", slug="durable", s0_values=[1.3], source=source(tmp_path), snapshot=RepositorySnapshot("a" * 40))
    from workflow_api import mot_2d_plan
    original_rename = mot_2d_plan._rename_no_replace; original_fsync = mot_2d_plan.os.fsync
    published = {"value": False}
    def rename(source_path, destination): original_rename(source_path, destination); published["value"] = True
    def fsync(descriptor):
        if published["value"]: raise OSError("post-publish fsync fault")
        return original_fsync(descriptor)
    monkeypatch.setattr(mot_2d_plan, "_rename_no_replace", rename)
    monkeypatch.setattr(mot_2d_plan.os, "fsync", fsync)
    materialize(plan)
    assert (plan.destination / "campaign.json").is_file()


def test_git_output_is_bounded_without_memory_capture(tmp_path, monkeypatch):
    repository(tmp_path)
    subprocess.run(["/usr/bin/git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    provider = RepositorySnapshotProvider(tmp_path, Path("/usr/bin/git"))
    instances = []
    class NoisyProcess:
        def __init__(self):
            self.stdout = io.BytesIO(b"x" * (2 * 1024 * 1024)); self.stderr = io.BytesIO()
            self.returncode = 0; self.killed = False; instances.append(self)
        def wait(self, timeout=None): return self.returncode
        def kill(self): self.killed = True; self.returncode = -9
    def noisy(*args, **kwargs):
        assert kwargs["stdout"] is subprocess.PIPE and kwargs["stderr"] is subprocess.PIPE
        return NoisyProcess()
    monkeypatch.setattr("workflow_api.repository_snapshot.subprocess.Popen", noisy)
    with pytest.raises(RuntimeError, match="verified safely"): provider._run(("rev-parse", "--verify", "HEAD^{commit}"))
    assert instances[0].killed
    assert instances[0].stdout.tell() <= 1024 * 1024 + 64 * 1024


def test_rate_limit_is_thread_safe(tmp_path):
    creator, _ = service(tmp_path); outcomes = []
    def attempt():
        try: creator._rate_limit("session"); outcomes.append("allowed")
        except BlockingIOError: outcomes.append("blocked")
    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert outcomes.count("allowed") == 12
    assert outcomes.count("blocked") == 8

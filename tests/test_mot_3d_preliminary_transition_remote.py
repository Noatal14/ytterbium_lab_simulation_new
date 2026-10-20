import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_api import mot_3d_preliminary_transition_remote as remote
from workflow_api import mot_3d_preliminary_submission_remote as stage2_remote
from tests.test_mot_3d_preliminary_results import _closed_fixture


def _selection(family):
    return {
        "kind": "mot_3d_discovery_candidate_selection",
        "family": family,
        "requested_candidate_count": 12,
        "selected_candidate_count": 12,
        "selection_pool_minimum_fraction": 0.55,
        "parameter_bounds": {},
        "candidates": [
            {"candidate_id": f"{family}_candidate_{index:02d}"} for index in range(12)
        ],
    }


def _harness(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    campaign = root / "data/optimization/mot_3d/campaign"
    (campaign / ".mot_ui").mkdir(parents=True)
    manifest = {
        "name": "campaign",
        "stage": "preliminary_check",
        "provenance": {"git_commit": "a" * 40},
        "design": {"screening_dt_s": 1e-5},
        "stages": {},
    }
    old = json.dumps(manifest, indent=2).encode()
    (campaign / "campaign.json").write_bytes(old)
    selections = {}
    for family in remote.FAMILIES:
        raw = json.dumps(_selection(family)).encode()
        path = campaign / f"selection/discovery/{family}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        selections[family] = json.loads(raw)
        for kind in ("array", "merge"):
            job = campaign / f"jobs/preliminary_check/{family}_{kind}.pbs"
            job.parent.mkdir(parents=True, exist_ok=True)
            job.write_bytes(f"{family}-{kind}".encode())
    results = {}
    for index, name in enumerate(remote.expected_paths(selections)):
        raw = f"result-{index}".encode()
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        results[name] = raw
    (campaign / "preliminary_check_submission.json").write_bytes(b"submission")
    jobs = {
        "angled_donut": {"array": "11[].zeus-master", "merge": "12.zeus-master"},
        "single_pass": {"array": "13[].zeus-master", "merge": "14.zeus-master"},
    }
    identity = {
        "source_files": {},
        "code_files": {},
        "stage1_receipt_sha256": "b" * 64,
        "stage1_bundle_sha256": "c" * 64,
    }
    submission_key = "d" * 64
    transition_key = remote.digest(
        {
            "campaign": "data/optimization/mot_3d/campaign",
            "commit": "a" * 40,
            "submission_key": submission_key,
            "identity": identity,
        }
    )
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": "a" * 40,
        "submission_key": submission_key,
        "transition_key": transition_key,
        "identity": identity,
    }
    generated = {
        "campaign.json": json.dumps(
            {**manifest, "stage": "refinement"}, indent=2
        ).encode(),
        **{
            name: f"generated-{index}".encode()
            for index, name in enumerate(
                sorted(remote.GENERATED_PATHS - {"campaign.json"})
            )
        },
    }
    validated = SimpleNamespace(
        summaries={family: {} for family in remote.FAMILIES},
        evidence_sha256="e" * 64,
    )

    def fake_run(argv, input_data=None, limit=0):
        if "rev-parse" in argv:
            return 0, b"a" * 40 + b"\n", b""
        if "branch" in argv:
            return 0, b"main\n", b""
        return 0, b"", b""

    monkeypatch.setattr(remote, "run", fake_run)
    monkeypatch.setattr(stage2_remote, "run", fake_run)
    monkeypatch.setattr(
        remote,
        "_identity",
        lambda *_, **__: (identity, {"campaign.json": old}),
    )
    monkeypatch.setattr(remote, "_exact_stage2", lambda *_: ({}, jobs))
    monkeypatch.setattr(
        remote, "_scheduler", lambda *_: ("completed_success_unvalidated", 6, 2)
    )
    monkeypatch.setattr(remote, "_capture", lambda *_: (manifest, results, validated))
    monkeypatch.setattr(
        remote, "render_refinement_transition", lambda *_: (generated, {})
    )
    return root, campaign, payload


def _invoke(monkeypatch, root, payload, operation):
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
    remote.main(trusted_root_override=root)


def _trusted_status_harness(tmp_path, monkeypatch):
    """Exercise main with real identity, Stage-2, qstat and science validators."""

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    manifest, selections, results, _, _ = _closed_fixture(fixture_root)
    root = tmp_path / "repository"
    campaign = root / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_bytes(manifest)
    for family, raw in selections.items():
        path = campaign / f"selection/discovery/{family}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for name, raw in results.items():
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    commit = "a" * 40
    submission_key = "d" * 64
    nonce = "9" * 32
    jobs = {
        "angled_donut": {"array": "11[].zeus-master", "merge": "12.zeus-master"},
        "single_pass": {"array": "13[].zeus-master", "merge": "14.zeus-master"},
    }
    created = 100
    submissions = campaign / ".mot_ui/submissions"
    transitions = campaign / ".mot_ui/transitions"
    submissions.mkdir(parents=True)
    transitions.mkdir()
    for family_index, family in enumerate(remote.FAMILIES):
        for kind_index, kind in enumerate(("array", "merge")):
            pbs = f"{family}-{kind}".encode()
            pbs_path = campaign / f"jobs/preliminary_check/{family}_{kind}.pbs"
            pbs_path.parent.mkdir(parents=True, exist_ok=True)
            pbs_path.write_bytes(pbs)
            order = family_index * 2 + kind_index
            row = {
                "status": "submitted",
                "submission_key": submission_key,
                "nonce": nonce,
                "commit": commit,
                "family": family,
                "kind": kind,
                "pbs_sha256": hashlib.sha256(pbs).hexdigest(),
                "depends_on": jobs[family]["array"] if kind == "merge" else None,
                "job_id": jobs[family][kind],
                "created_unix_s": created + 1 + 2 * order,
                "completed_unix_s": created + 2 + 2 * order,
            }
            (submissions / f"preliminary_check_{family}_{kind}.json").write_text(
                json.dumps(row)
            )
    submitted = created + 9
    final = {
        "version": 1,
        "status": "submitted",
        "submission_key": submission_key,
        "nonce": nonce,
        "commit": commit,
        "jobs": jobs,
        "created_unix_s": created,
        "submitted_unix_s": submitted,
    }
    (submissions / "preliminary_check.json").write_text(json.dumps(final))
    compatibility = {
        "kind": "mot_3d_selection_stage_submission",
        "stage": "preliminary_check",
        "status": "submitted",
        "dependency": "afterok",
        "submission_key": submission_key,
        "nonce": nonce,
        "commit": commit,
        "created_unix_s": created,
        "submitted_unix_s": submitted,
        "families": {
            family: {
                "array_job_id": jobs[family]["array"],
                "merge_job_id": jobs[family]["merge"],
            }
            for family in remote.FAMILIES
        },
    }
    (campaign / "preliminary_check_submission.json").write_text(
        json.dumps(compatibility)
    )
    for name in remote.CODE_PATHS:
        source = Path(name)
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    source_hashes = {
        name: hashlib.sha256((campaign / name).read_bytes()).hexdigest()
        for name in remote.SOURCE_IDENTITY_PATHS
    }
    code_hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in remote.CODE_PATHS
    }
    stage1_bundle = b"x" * 961
    (transitions / "preliminary_check.bundle.gz").write_bytes(stage1_bundle)
    stage1_bundle_hash = hashlib.sha256(stage1_bundle).hexdigest()
    from workflow_api.zeus_discovery_submission import FILES, canonical_digest
    digest_fields = ("physical_model_sha256", "source_2d_campaign_sha256",
                     "source_2d_final_report_sha256", "input_registry_sha256",
                     "timestep_policy_sha256")
    bootstrap = {
        "status": "discovery_prepared", "commit": commit, "nonce": "5" * 32,
        **{key: "6" * 64 for key in digest_fields},
        "files": {name: "7" * 64 for name in FILES}, "completed_unix_s": 80.5,
    }
    bootstrap["bootstrap_key"] = canonical_digest({
        "campaign_name": campaign.name, "commit": commit,
        **{key: bootstrap[key] for key in digest_fields},
        "files": bootstrap["files"], "nonce": bootstrap["nonce"],
    })
    (transitions / "discovery_bootstrap.json").write_text(json.dumps(bootstrap))
    discovery_key = canonical_digest({
        "campaign": campaign.relative_to(root).as_posix(), "commit": commit,
        "bootstrap_digest": canonical_digest(bootstrap),
        "bootstrap_key": bootstrap["bootstrap_key"], "bootstrap_nonce": bootstrap["nonce"],
        "files": bootstrap["files"],
    })
    assert discovery_key != submission_key
    stage1 = {
        "status": "preliminary_check_prepared",
        "nonce": "1" * 32,
        "transition_key": "2" * 64,
        "commit": commit,
        "bootstrap_digest": canonical_digest(bootstrap),
        "submission_key": discovery_key,
        "chain": {
            "angled_donut": ["21[].zeus-master", "22[].zeus-master"],
            "single_pass": [
                "23[].zeus-master",
                "24[].zeus-master",
                "25[].zeus-master",
            ],
        },
        "bundle": {
            "version": 1,
            "file_count": 961,
            "uncompressed_bytes": 961,
            "bundle_sha256": stage1_bundle_hash,
            "chunks": [{"index": 0, "size": 961, "sha256": stage1_bundle_hash}],
        },
        "completed_unix_s": 90,
    }
    stage1_raw = remote.canonical(stage1) + b"\n"
    (transitions / "preliminary_check.json").write_bytes(stage1_raw)
    identity = {
        "source_files": source_hashes,
        "code_files": code_hashes,
        "stage1_receipt_sha256": remote.digest(stage1),
        "stage1_bundle_sha256": stage1_bundle_hash,
    }
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": commit,
        "submission_key": submission_key,
        "identity": identity,
    }
    payload["transition_key"] = remote.digest(payload)

    def fake_run(argv, input_data=None, limit=0):
        if "rev-parse" in argv:
            return 0, commit.encode() + b"\n", b""
        if "branch" in argv:
            return 0, b"main\n", b""
        if "status" in argv:
            return 0, b"", b""
        job = argv[-1]
        if "[]" in job:
            prefix = job.split("[]", 1)[0]
            output = "".join(
                f"Job Id: {prefix}[{index}].zeus-master\n"
                "    job_state = F\n    Exit_status = 0\n"
                for index in range(3)
            )
        else:
            output = f"Job Id: {job}\n    job_state = F\n    Exit_status = 0\n"
        return 0, output.encode(), b""

    monkeypatch.setattr(remote, "run", fake_run)
    monkeypatch.setattr(stage2_remote, "run", fake_run)
    return root, campaign, payload


def test_inspect_is_zero_write_and_prepare_publishes_exact_registry(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    before = {path.relative_to(campaign) for path in campaign.rglob("*")}
    _invoke(monkeypatch, root, payload, "inspect")
    assert {path.relative_to(campaign) for path in campaign.rglob("*")} == before
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "ready_to_advance"

    prepared = dict(payload, nonce="1" * 32)
    _invoke(monkeypatch, root, prepared, "prepare")
    response = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert response["lifecycle"] == "refinement_prepared"
    assert response["bundle"]["file_count"] == 160
    assert json.loads((campaign / "campaign.json").read_text())["stage"] == "refinement"
    assert not (campaign / ".mot_ui/transitions/refinement.pending.json").exists()
    _invoke(monkeypatch, root, payload, "status")
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "refinement_prepared"


def test_status_crosses_real_identity_stage2_qstat_and_152_science_boundaries(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _trusted_status_harness(tmp_path, monkeypatch)
    before = {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    _invoke(monkeypatch, root, payload, "status")
    response = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert response["lifecycle"] == "ready_to_advance"
    assert response["validation"] == "valid"
    assert response["completed_array_tasks"] == 6
    assert response["completed_merge_jobs"] == 2
    after = {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "target",
    [
        "stage1_receipt",
        "stage1_bundle",
        "stage2_time",
        "stage2_dependency",
        "source",
        "code",
        "result",
    ],
)
def test_real_status_rejects_mutated_trust_evidence(
    tmp_path, monkeypatch, capsys, target
):
    root, campaign, payload = _trusted_status_harness(tmp_path, monkeypatch)
    if target == "stage1_receipt":
        path = campaign / ".mot_ui/transitions/preliminary_check.json"
        row = json.loads(path.read_text())
        row["unexpected"] = True
        path.write_text(json.dumps(row))
    elif target == "stage1_bundle":
        path = campaign / ".mot_ui/transitions/preliminary_check.bundle.gz"
        path.write_bytes(path.read_bytes() + b"x")
    elif target == "stage2_time":
        path = (
            campaign / ".mot_ui/submissions/preliminary_check_angled_donut_array.json"
        )
        row = json.loads(path.read_text())
        row["completed_unix_s"] = 999
        path.write_text(json.dumps(row))
    elif target == "stage2_dependency":
        path = (
            campaign / ".mot_ui/submissions/preliminary_check_angled_donut_merge.json"
        )
        row = json.loads(path.read_text())
        row["depends_on"] = "999[].zeus-master"
        path.write_text(json.dumps(row))
    elif target == "source":
        path = campaign / "jobs/preliminary_check/angled_donut_array.pbs"
        path.write_bytes(path.read_bytes() + b"x")
    elif target == "code":
        path = root / sorted(remote.CODE_PATHS)[0]
        path.write_bytes(path.read_bytes() + b"x")
    else:
        path = next((campaign / "preliminary_check").rglob("*.npz"))
        path.write_bytes(path.read_bytes() + b"x")
    if target == "result":
        _invoke(monkeypatch, root, payload, "status")
        response = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert response["validation"] == "scientifically_invalid"
    else:
        with pytest.raises(SystemExit):
            _invoke(monkeypatch, root, payload, "status")


def test_prepare_recovers_after_manifest_commit_boundary_without_overwrite(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    prepared = dict(payload, nonce="2" * 32)
    original = remote._replace_campaign
    calls = 0

    def crash_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemExit(91)
        return original(*args)

    monkeypatch.setattr(remote, "_replace_campaign", crash_once)
    with pytest.raises(SystemExit) as error:
        _invoke(monkeypatch, root, prepared, "prepare")
    assert error.value.code == 91
    assert (campaign / ".mot_ui/transitions/refinement.pending.json").is_file()
    monkeypatch.setattr(remote, "_replace_campaign", original)
    _invoke(monkeypatch, root, prepared, "prepare")
    assert (
        json.loads(capsys.readouterr().out.splitlines()[-1])["lifecycle"]
        == "refinement_prepared"
    )


def test_symlinked_generated_parent_is_rejected_without_external_write(
    tmp_path, monkeypatch
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (campaign / "selection/refinement").parent.mkdir(parents=True, exist_ok=True)
    (campaign / "selection/refinement").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, dict(payload, nonce="3" * 32), "prepare")
    assert not list(outside.iterdir())


def test_retrieve_rejects_tampered_bundle(tmp_path, monkeypatch, capsys):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    prepared = dict(payload, nonce="4" * 32)
    _invoke(monkeypatch, root, prepared, "prepare")
    response = json.loads(capsys.readouterr().out)
    retrieve = dict(
        payload,
        bundle_sha256=response["bundle"]["bundle_sha256"],
        chunk_index=0,
    )
    _invoke(monkeypatch, root, retrieve, "retrieve")
    chunk_response = json.loads(capsys.readouterr().out)
    chunk = base64.b64decode(chunk_response["chunk"]["content"], validate=True)
    assert hashlib.sha256(chunk).hexdigest() == chunk_response["chunk"]["sha256"]

    bundle = campaign / ".mot_ui/transitions/refinement.bundle.gz"
    bundle.write_bytes(bundle.read_bytes() + b"tamper")
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, retrieve, "retrieve")


def test_restart_finalizes_durable_pending_after_manifest_commit(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    prepared = dict(payload, nonce="5" * 32)
    original = remote._publish_bytes
    crashed = False

    def crash_before_final(parent, name, raw, *, identical_ok):
        nonlocal crashed
        if name == "refinement.json" and not crashed:
            crashed = True
            raise SystemExit(92)
        return original(parent, name, raw, identical_ok=identical_ok)

    monkeypatch.setattr(remote, "_publish_bytes", crash_before_final)
    with pytest.raises(SystemExit) as error:
        _invoke(monkeypatch, root, prepared, "prepare")
    assert error.value.code == 92
    assert json.loads((campaign / "campaign.json").read_text())["stage"] == "refinement"
    assert (campaign / ".mot_ui/transitions/refinement.pending.json").is_file()

    _invoke(monkeypatch, root, payload, "status")
    assert (
        json.loads(capsys.readouterr().out.splitlines()[-1])["lifecycle"]
        == "outcome_unknown"
    )

    monkeypatch.setattr(remote, "_publish_bytes", original)
    _invoke(monkeypatch, root, prepared, "prepare")
    assert (
        json.loads(capsys.readouterr().out.splitlines()[-1])["lifecycle"]
        == "refinement_prepared"
    )
    assert not (campaign / ".mot_ui/transitions/refinement.pending.json").exists()


def test_prepare_never_overwrites_mismatched_generated_artifact(tmp_path, monkeypatch):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    target = campaign / "selection/refinement/angled_donut.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user-owned")
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, dict(payload, nonce="6" * 32), "prepare")
    assert target.read_bytes() == b"user-owned"
    assert (
        json.loads((campaign / "campaign.json").read_text())["stage"]
        == "preliminary_check"
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "pending",
        "selection/refinement/angled_donut.json",
        "selection/refinement/single_pass.json",
        "jobs/refinement/angled_donut_array.pbs",
        "jobs/refinement/angled_donut_merge.pbs",
        "jobs/refinement/single_pass_array.pbs",
        "jobs/refinement/single_pass_merge.pbs",
        "bundle",
        "campaign",
        "final",
        "unlink",
    ],
)
def test_every_durable_publication_boundary_recovers_without_overwrite(
    tmp_path, monkeypatch, capsys, boundary
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    prepared = dict(payload, nonce="7" * 32)
    publish_bytes = remote._publish_bytes
    publish_relative = remote._publish_relative
    replace_campaign = remote._replace_campaign
    unlink = remote.unlink_at
    crashed = False

    def crash():
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit(93)

    def wrapped_publish_bytes(parent, name, raw, *, identical_ok):
        result = publish_bytes(parent, name, raw, identical_ok=identical_ok)
        if (
            (boundary == "pending" and name == "refinement.pending.json")
            or (boundary == "bundle" and name == "refinement.bundle.gz")
            or (boundary == "final" and name == "refinement.json")
        ):
            crash()
        return result

    def wrapped_publish_relative(parent, name, raw):
        result = publish_relative(parent, name, raw)
        if boundary == name:
            crash()
        return result

    def wrapped_replace_campaign(parent, old, new):
        result = replace_campaign(parent, old, new)
        if boundary == "campaign":
            crash()
        return result

    def wrapped_unlink(parent, name):
        result = unlink(parent, name)
        if boundary == "unlink" and name == "refinement.pending.json":
            crash()
        return result

    monkeypatch.setattr(remote, "_publish_bytes", wrapped_publish_bytes)
    monkeypatch.setattr(remote, "_publish_relative", wrapped_publish_relative)
    monkeypatch.setattr(remote, "_replace_campaign", wrapped_replace_campaign)
    monkeypatch.setattr(remote, "unlink_at", wrapped_unlink)
    with pytest.raises(SystemExit) as error:
        _invoke(monkeypatch, root, prepared, "prepare")
    assert error.value.code == 93

    monkeypatch.setattr(remote, "_publish_bytes", publish_bytes)
    monkeypatch.setattr(remote, "_publish_relative", publish_relative)
    monkeypatch.setattr(remote, "_replace_campaign", replace_campaign)
    monkeypatch.setattr(remote, "unlink_at", unlink)
    _invoke(monkeypatch, root, prepared, "prepare")
    response = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert response["lifecycle"] == "refinement_prepared"
    assert json.loads((campaign / "campaign.json").read_text())["stage"] == "refinement"
    assert not (campaign / ".mot_ui/transitions/refinement.pending.json").exists()


def test_unexpected_transition_entry_fails_closed_without_mutation(
    tmp_path, monkeypatch
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    transitions = campaign / ".mot_ui/transitions"
    transitions.mkdir()
    (transitions / "refinement.evil.json").write_bytes(b"{}")
    before = (campaign / "campaign.json").read_bytes()
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, payload, "status")
    assert (campaign / "campaign.json").read_bytes() == before


def test_prepare_busy_lock_has_no_publication(tmp_path, monkeypatch):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    original = remote.fcntl.flock

    def busy(fd, operation):
        if operation & remote.fcntl.LOCK_EX:
            raise BlockingIOError
        return original(fd, operation)

    monkeypatch.setattr(remote.fcntl, "flock", busy)
    before = {path.relative_to(campaign) for path in campaign.rglob("*")}
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, dict(payload, nonce="8" * 32), "prepare")
    after = {path.relative_to(campaign) for path in campaign.rglob("*")}
    assert after - before <= {
        Path(".mot_ui/transitions"),
        Path(".mot_ui/transitions/refinement.lock"),
    }
    assert (
        json.loads((campaign / "campaign.json").read_text())["stage"]
        == "preliminary_check"
    )


@pytest.mark.parametrize(
    "kind,project",
    [
        ("unknown_campaign", "/home/tal.noa/ytterbium_lab_simulation_new"),
        (None, "/home/tal.noa/ytterbium_lab_simulation_ui_acceptance"),
    ],
)
def test_untrusted_campaign_kind_is_rejected_before_transition_directory_creation(
    tmp_path, monkeypatch, capsys, kind, project
):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    path = campaign / "campaign.json"
    manifest = json.loads(path.read_bytes())
    if kind is not None:
        manifest["kind"] = kind
    path.write_text(json.dumps(manifest))
    before = {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in root.rglob("*")
        if item.is_file()
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps({**payload, "nonce": "f" * 32}).encode()
    ).decode()
    monkeypatch.setattr(
        sys, "argv", ["receiver", "prepare", "tal.noa", project, encoded]
    )
    with pytest.raises(SystemExit):
        remote.main(trusted_root_override=root)
    assert "preliminary_transition_conflict" in capsys.readouterr().out
    assert not (campaign / ".mot_ui/transitions").exists()
    after = {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in root.rglob("*")
        if item.is_file()
    }
    assert after == before

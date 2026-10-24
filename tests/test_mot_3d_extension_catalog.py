"""Extension is an inspectable terminal outcome only with recomputed evidence."""
from copy import deepcopy
import json
import shutil

import pytest

from workflow_api import discovery
from workflow_api.mot_3d_final_validation_results import validate_final_validation_result_bytes


@pytest.fixture(scope="module")
def terminal(tmp_path_factory):
    from test_mot_3d_final_validation_completion_backend import _exact14
    work = tmp_path_factory.mktemp("extension-producer")
    values = _exact14(work / "producer", extension_family="single_pass", return_values=True)
    validated = validate_final_validation_result_bytes(**values)
    files = {
        **values["job_files"], **values["input_files"], **values["result_files"],
        "selection/locked_nominals.json": values["locked_nominals_bytes"],
        "final_validation_input_generation_submission.json": values["generation_submission_bytes"],
        "final_validation_submission.json": values["submission_bytes"],
        "campaign.json": validated.campaign_bytes,
        validated.terminal_name: validated.terminal_bytes,
    }
    root = work / "repository"
    campaign = root / values["logical_campaign_root"]
    for name, raw in files.items():
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return root, campaign, json.loads(validated.campaign_bytes)


def test_normal_scientific_terminal_generator_is_inspectable_without_mutation(terminal):
    root, campaign, payload = terminal
    before = {p: p.read_bytes() for p in campaign.rglob("*") if p.is_file()}
    assert discovery._validated_3d_extension(payload, root, campaign)
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("attack", ["missing_status", "corrupt_status", "cross_outcome", "missing_seed", "corrupt_seed", "registry", "untrusted_producer", "scalar_producer", "hardlink_seed", "symlink_seed", "opposite_terminal", "opposite_terminal_symlink"])
def test_normal_terminal_validation_rejects_incomplete_or_contradictory_evidence(tmp_path, terminal, attack):
    root, campaign, payload = terminal
    target = tmp_path / campaign.relative_to(root)
    shutil.copytree(campaign, target)
    payload = deepcopy(payload)
    if attack == "missing_status":
        (target / "final_validation_status.json").unlink()
    elif attack == "corrupt_status":
        (target / "final_validation_status.json").write_text("{}")
    elif attack == "cross_outcome":
        payload["stage"] = "complete"
    elif attack == "missing_seed":
        (target / "final_validation/single_pass/seed_44001.json").unlink()
    elif attack == "corrupt_seed":
        (target / "final_validation/single_pass/seed_44001.json").write_text("{}")
    elif attack == "registry":
        payload["stages"]["final_validation_status"] = "../final_validation_status.json"
    elif attack in {"opposite_terminal", "opposite_terminal_symlink"}:
        opposite = target / "final_report.json"
        if attack == "opposite_terminal":
            opposite.write_text("{}")
        else:
            try:
                opposite.symlink_to(target / "final_validation_status.json")
            except OSError:
                pytest.skip("host does not permit symlink creation")
    elif attack in {"hardlink_seed", "symlink_seed"}:
        import os
        seed = target / "final_validation/single_pass/seed_44001.json"
        sibling = tmp_path / "seed-copy.json"
        if attack == "hardlink_seed":
            os.link(seed, sibling)
        else:
            sibling.write_bytes(seed.read_bytes())
            seed.unlink()
            try:
                seed.symlink_to(sibling)
            except OSError:
                pytest.skip("host does not permit symlink creation")
    else:
        path = target / "final_validation_inputs/input_manifest.json"
        data = json.loads(path.read_bytes())
        data["ensembles"][0]["path"] = 42 if attack == "scalar_producer" else "/elsewhere/unrelated.npy"
        path.write_text(json.dumps(data))
    try:
        valid = discovery._validated_3d_extension(payload, tmp_path, target)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        valid = False
    assert not valid


@pytest.mark.parametrize("valid", [True, False])
def test_catalog_extension_maps_final_stage_but_requires_normal_terminal_evidence(tmp_path, monkeypatch, valid):
    from test_workflow_api_server import current_3d_contract_fixture
    payload = current_3d_contract_fixture(tmp_path)
    payload["stage"] = "final_validation_extension_required"
    payload["stages"]["final_validation"] = {}
    calls = []
    monkeypatch.setattr(discovery, "_validated_3d_extension", lambda *args: calls.append(args) or valid)
    ok, errors = discovery._modern_3d_contract(payload, [
        {"stage": "dt_validation", "status": "complete"},
        {"stage": "final_validation", "status": "complete", "completed": 2, "expected": 2},
    ], tmp_path, tmp_path)
    assert bool(calls) and ok == valid
    assert ("3D precision-extension terminal evidence is invalid or incomplete" in errors) == (not valid)


def test_missing_final_stage_record_still_blocks_extension(tmp_path, monkeypatch):
    from test_workflow_api_server import current_3d_contract_fixture
    payload = current_3d_contract_fixture(tmp_path)
    payload["stage"] = "final_validation_extension_required"
    monkeypatch.setattr(discovery, "_validated_3d_extension", lambda *args: True)
    ok, errors = discovery._modern_3d_contract(payload, [{"stage": "dt_validation", "status": "complete"}], tmp_path, tmp_path)
    assert not ok and "current 3D stage record is incomplete" in errors


def test_native_adapter_stat_not_windows_path_creation_time_is_compared(terminal, monkeypatch):
    """Windows Path.stat ctime is creation time; platform adapter normalizes it."""
    from pathlib import Path
    from types import SimpleNamespace
    from workflow_api.platform_io import os as host_os
    root, campaign, payload = terminal
    original_path_stat = Path.stat
    original_native_stat = host_os.stat
    calls = []

    def creation_stat(path, *args, **kwargs):
        info = original_path_stat(path, *args, **kwargs)
        if path.is_relative_to(campaign):
            values = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
            values["st_ctime_ns"] += 123456
            return SimpleNamespace(**values)
        return info

    def native_stat(path, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            calls.append((path, kwargs["follow_symlinks"]))
        return original_native_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", creation_stat)
    monkeypatch.setattr(host_os, "stat", native_stat)
    assert discovery._validated_3d_extension(payload, root, campaign)
    assert ("campaign.json", False) in calls
    assert ("final_validation_status.json", False) in calls

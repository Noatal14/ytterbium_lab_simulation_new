"""Host path syntax never enters logical Zeus job flags or stage references."""

from copy import deepcopy
import json
from pathlib import PureWindowsPath

import pytest

from studies import mot_3d_campaign as campaign
from tests.test_mot_3d_acceptance_workload import manifest


class WindowsLogicalPath(PureWindowsPath):
    """Emulate Windows Path construction without native filesystem access."""

    def resolve(self):
        return self


def _inputs(monkeypatch):
    import studies.mot_3d.discovery.optimize as optimizer

    value = manifest()
    value["stage"] = "finalist_selection"
    value["input_directory"] = r"C:\native\physical\acceptance\source"
    value["upstream_2d_campaign"] = {
        "expected_survivor_parameters": {
            "s0": 1.3,
            "detuning_gamma": -1.0,
            "magnet_radius": 0.046,
        },
        "expected_survivor_design": {"zeeman_profile": "corrected"},
    }
    monkeypatch.setattr(
        optimizer,
        "build_profile_from_parameters",
        lambda family, parameters: ({"family": family}, parameters, {}),
    )
    summaries = {
        family: {
            "kind": "merged_mot_3d_finalist_selection",
            "family": family,
            "ranked_candidates": [
                {"candidate_id": f"{family}_{i}", "parameters": {}} for i in range(3)
            ],
        }
        for family in campaign.FAMILIES
    }
    return value, summaries


@pytest.mark.parametrize("windows_spelling", [False, True])
def test_final_input_and_validation_rendering_are_identical_on_windows(
    monkeypatch, windows_spelling
):
    value, summaries = _inputs(monkeypatch)
    original = deepcopy(value)
    root = f"data/optimization/mot_3d/ui_acceptance/{value['name']}"
    hashes = {family: "a" * 64 for family in campaign.FAMILIES}
    expected, expected_updated = campaign.render_final_validation_input_transition(
        root, value, summaries, hashes, "b" * 64
    )
    expected_final, _ = campaign.render_final_validation_transition(
        root, expected_updated
    )
    monkeypatch.setattr(campaign, "Path", WindowsLogicalPath)
    logical_root = PureWindowsPath(root) if windows_spelling else root
    actual, updated = campaign.render_final_validation_input_transition(
        logical_root, value, summaries, hashes, "b" * 64
    )
    assert actual == expected
    assert updated == expected_updated
    assert value == original  # Native physical source identities are untouched.
    assert updated["input_directory"] == r"C:\native\physical\acceptance\source"
    assert "\\" not in json.dumps(updated["stages"])
    actual_final, final_manifest = campaign.render_final_validation_transition(
        logical_root, updated
    )
    assert actual_final == expected_final
    assert "\\" not in json.dumps(final_manifest["stages"])
    assert all(
        b"\\" not in raw
        for name, raw in {**actual, **actual_final}.items()
        if name.endswith(".pbs")
    )


@pytest.mark.parametrize("stage", ["preliminary_check", "refinement", "closure"])
def test_selection_worker_flags_are_posix_even_with_windows_path_objects(
    monkeypatch, stage
):
    value = manifest()
    root = f"data/optimization/mot_3d/ui_acceptance/{value['name']}"
    selections = {
        family: PureWindowsPath(root) / "selection" / stage / f"{family}.json"
        for family in campaign.FAMILIES
    }
    expected = campaign.render_selection_stage_jobs(
        root, value, stage, selections, "refinement", 750, 61001, 62001
    )
    monkeypatch.setattr(campaign, "Path", WindowsLogicalPath)
    actual = campaign.render_selection_stage_jobs(
        PureWindowsPath(root), value, stage, selections, "refinement", 750, 61001, 62001
    )
    assert actual == expected
    assert all("\\" not in text for jobs in actual.values() for text in jobs.values())
    assert str(campaign._canonical_campaign_logical_root(PureWindowsPath(root))) == root


def test_discovery_command_flags_are_posix_with_native_windows_storage_paths(
    monkeypatch,
):
    value = manifest()
    logical = f"data/optimization/mot_3d/ui_acceptance/{value['name']}"
    monkeypatch.setattr(campaign, "Path", WindowsLogicalPath)
    rendered, smoke, rounds, _ = campaign.render_discovery_jobs(
        PureWindowsPath("C:/native/storage") / logical,
        "a" * 40,
        PureWindowsPath("C:/native/physical/inputs"),
        command_campaign=PureWindowsPath(logical),
        command_input=PureWindowsPath("data/acceptance/inputs"),
        manifest=value,
    )
    assert all("\\" not in raw for raw in rendered.values())
    assert all(isinstance(path, PureWindowsPath) for path in smoke.values())
    assert all(
        isinstance(path, PureWindowsPath) for paths in rounds.values() for path in paths
    )

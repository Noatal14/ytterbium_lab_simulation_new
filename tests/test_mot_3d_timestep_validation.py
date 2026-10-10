import json

import numpy as np
import pytest

from studies.mot_3d import timestep_validation as validation


def _manifest():
    return {
        "design": {
            "dt_validation_candidates_s": [10e-6, 5e-6, 2.5e-6, 1.25e-6, 0.625e-6],
            "dt_validation_reference_s": 0.3125e-6,
        }
    }


def test_tasks_cross_every_family_anchor_seed_and_timestep():
    tasks = validation._tasks(_manifest())
    assert len(tasks) == 2 * 3 * 5 * 6
    assert [row["task_index"] for row in tasks] == list(range(len(tasks)))
    assert {row["dt_s"] for row in tasks} == {
        10e-6, 5e-6, 2.5e-6, 1.25e-6, 0.625e-6, 0.3125e-6
    }


def test_atomic_npz_uses_requested_filename(tmp_path):
    path = tmp_path / "outcomes.npz"
    validation._atomic_npz(path, captured=np.array([True, False]))
    assert path.is_file()
    assert np.array_equal(np.load(path)["captured"], [True, False])


def test_crossed_interval_is_reproducible_and_contains_constant():
    interval = validation._crossed_interval(
        np.full((5, 20), 0.01), 0.05, np.random.default_rng(123)
    )
    assert interval == pytest.approx([0.01, 0.01])


def test_prepare_writes_full_portable_array_and_merge_jobs(tmp_path, monkeypatch):
    root = tmp_path / "campaign"
    root.mkdir()
    revision = __import__("subprocess").check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    manifest = {
        "kind": "mot_3d_campaign_v2",
        "stage": "dt_validation_required",
        "provenance": {"git_commit": revision, "physical_model_sha256": "physics"},
        "design": {
            "dt_validation_candidates_s": [10e-6, 5e-6, 2.5e-6, 1.25e-6, 0.625e-6],
            "dt_validation_reference_s": 0.3125e-6,
        },
    }
    (root / "campaign.json").write_text(json.dumps(manifest))
    monkeypatch.chdir(tmp_path)
    validation.prepare(root)
    tasks = json.loads((root / "dt_validation/tasks.json").read_text())
    assert len(tasks["tasks"]) == 180
    run_job = (root / "dt_validation/run.pbs").read_text()
    merge_job = (root / "dt_validation/merge.pbs").read_text()
    assert "#PBS -J 0-179%3" in run_job
    project_root = validation.Path(validation.__file__).resolve().parents[2]
    assert f"cd {project_root}" in run_job
    assert "RUN_TMP=" in run_job and "trap 'rm -rf" in run_job
    assert "timestep_validation merge" in merge_job


def test_sentinels_are_explicit_and_distinct():
    for family, sentinels in validation.SENTINEL_PARAMETERS.items():
        assert len(sentinels) == 3
        assert len({validation._json_sha256(row) for row in sentinels}) == 3
        assert sentinels[1]["magnetic_gradient_G_cm"] == 100.0
        assert sentinels[2]["green_s0"] < sentinels[0]["green_s0"]

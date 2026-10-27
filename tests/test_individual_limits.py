"""The UI contracts, storage and frozen-state budget share one capacity policy."""
import pytest
from workflow_api.individual_limits import (
    PARTICLE_MAXIMUM_BY_MODE, PARTICLE_MAXIMUM, SELECTED_STATE_BYTES_MAXIMUM,
    SELECTED_STATE_FILE_BYTES_MAXIMUM, particle_count_allowed, particle_policy,
)
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION
from workflow_api.zeeman_run_specification import ZEEMAN_RUN_SPECIFICATION


def test_all_family_contracts_expose_the_same_authoritative_particle_limits():
    for spec in [MOT_2D_RUN_SPECIFICATION, MOT_3D_RUN_SPECIFICATION, ZEEMAN_RUN_SPECIFICATION]:
        assert spec["particle_count"]["maximum_by_execution_mode"] == PARTICLE_MAXIMUM_BY_MODE
    assert MOT_2D_RUN_SPECIFICATION["particle_count"] == particle_policy()
    assert MOT_3D_RUN_SPECIFICATION["particle_count"] == particle_policy()
    assert SELECTED_STATE_BYTES_MAXIMUM == PARTICLE_MAXIMUM * 6 * 8
    assert SELECTED_STATE_FILE_BYTES_MAXIMUM > SELECTED_STATE_BYTES_MAXIMUM
    with pytest.raises(TypeError):
        PARTICLE_MAXIMUM_BY_MODE["local"] = 999


@pytest.mark.parametrize("mode", ["local", "zeus"])
def test_admission_edges_reject_bool_negative_and_above_mode_capacity(mode):
    maximum = PARTICLE_MAXIMUM_BY_MODE[mode]
    assert particle_count_allowed(maximum, mode)
    assert particle_count_allowed(1, mode)
    for invalid in [True, False, 0, -1, maximum + 1, 1.5, "1"]:
        assert not particle_count_allowed(invalid, mode)
    assert not particle_count_allowed(1, "unknown")


def test_generated_ui_limits_match_the_policy_exactly():
    from pathlib import Path
    from scripts.generate_individual_limits import render
    assert Path("ui/src/generated/individualLimits.v1.ts").read_text() == render()


def test_capacity_authority_is_part_of_each_source_provenance_closure(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    from workflow_api.repository_snapshot import (
        RepositorySnapshotProvider, RepositoryFilesChangedError,
        ZEEMAN_RELEVANT_FILES, MOT_2D_INDIVIDUAL_RELEVANT_FILES, MOT_3D_INDIVIDUAL_RELEVANT_FILES,
    )
    relative = "workflow_api/individual_limits.py"
    for closure in [ZEEMAN_RELEVANT_FILES, MOT_2D_INDIVIDUAL_RELEVANT_FILES, MOT_3D_INDIVIDUAL_RELEVANT_FILES]:
        assert relative in closure
    git = shutil.which("git")
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    policy = tmp_path / relative
    policy.parent.mkdir()
    policy.write_text(Path(relative).read_text())
    subprocess.run([git, "-C", str(tmp_path), "add", relative], check=True)
    subprocess.run([git, "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
    provider = RepositorySnapshotProvider(tmp_path, Path(git), audited_paths=(relative,))
    provider.capture()
    policy.write_text(policy.read_text() + "\n# changed capacity authority\n")
    with pytest.raises(RepositoryFilesChangedError):
        provider.capture()

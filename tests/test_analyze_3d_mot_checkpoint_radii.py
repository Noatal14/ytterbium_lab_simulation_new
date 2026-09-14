import json

import numpy as np

from config import Geometry
from studies.analyze_3d_mot_checkpoint_radii import analyze_checkpoint_root


def test_checkpoint_radii_use_instantaneous_position_and_speed(tmp_path):
    input_root = tmp_path / "run"
    shard = input_root / "shard_0"
    checkpoint = tmp_path / "checkpoints" / "shard_0"
    shard.mkdir(parents=True)
    checkpoint.mkdir(parents=True)
    (shard / "retention_summary.json").write_text(
        json.dumps({"profiles": ["example"], "checkpoint_dir": str(checkpoint)})
    )

    center = np.asarray(Geometry.MOT_3D_CENTER_M)
    states = np.zeros((4, 6))
    states[:, :3] = center
    states[0, 0] += 4e-3
    states[1, 0] += 6e-3
    states[2, 0] += 9e-3
    states[3, 0] += 4e-3
    states[3, 3] = 1.1
    np.savez_compressed(
        checkpoint / "example_final_states.npz",
        final_states=states,
        final_state_available=np.ones(4, dtype=bool),
        selected_particle_indices=np.arange(4),
        final_time_s=0.1,
    )

    rows = analyze_checkpoint_root(input_root)

    assert [row["usable_at_end_count"] for row in rows] == [1, 2, 3]
    assert all(row["final_time_s"] == 0.1 for row in rows)

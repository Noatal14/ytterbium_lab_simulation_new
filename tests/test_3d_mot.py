import numpy as np

from config import Geometry, mot_3d_laser_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from split_simulation import mot_3d_simulation


def test_setup_3dmot_lasers_uses_orthogonal_pairs_at_science_center():
    beams = setup_3dmot_lasers(
        center_position=mot_3d_laser_config["center_position"],
        s0_399=mot_3d_laser_config["399"]["s0"],
        detuning_gamma_399=mot_3d_laser_config["399"]["detuning_gamma"],
        waist_399=mot_3d_laser_config["399"]["waist"],
        enabled_399=mot_3d_laser_config["399"]["enabled"],
        s0_556=mot_3d_laser_config["556"]["s0"],
        detuning_gamma_556=mot_3d_laser_config["556"]["detuning_gamma"],
        waist_556=mot_3d_laser_config["556"]["waist"],
        enabled_556=mot_3d_laser_config["556"]["enabled"],
    )

    assert len(beams) == 12

    expected_directions = {
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    }

    directions_399 = {
        tuple(np.asarray(beam.direction, dtype=float))
        for beam in beams
        if beam.tag.startswith("3DMOT_399_")
    }
    directions_556 = {
        tuple(np.asarray(beam.direction, dtype=float))
        for beam in beams
        if beam.tag.startswith("3DMOT_556_")
    }

    assert directions_399 == expected_directions
    assert directions_556 == expected_directions

    for beam in beams:
        assert np.allclose(beam.waist_position, Geometry.MOT_3D_CENTER)


def test_mot_3d_simulation_handles_empty_input():
    trajectories, final_states = mot_3d_simulation([])
    assert trajectories == []
    assert final_states.shape == (0, 6)

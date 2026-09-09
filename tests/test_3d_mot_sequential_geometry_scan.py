import pytest

from config import MOT_3D_CONFIGURATIONS
from studies.scan_3d_mot_sequential_geometry import (
    apply_sequential_geometry,
    geometry_points,
    sequential_geometry_fields,
)


def test_requested_sequential_geometry_grid_contains_twelve_unique_points():
    points = geometry_points((3.0, 5.0, 10.0), (5.0, 10.0), (10.0, 20.0))

    assert len(points) == 12
    assert len(set(points)) == 12
    assert (3.0e-3, 10.0e-3, 10.0e-3) in points
    assert (10.0e-3, 5.0e-3, 20.0e-3) in points


def test_sequential_geometry_grid_rejects_crossing_inside_protected_core():
    with pytest.raises(ValueError, match="crossing distance"):
        geometry_points((5.0,), (10.0,), (5.0,))


def test_selected_geometry_can_be_applied_to_later_scan_stages():
    profile = {**MOT_3D_CONFIGURATIONS["angled_sequential"]}
    profile["399"] = dict(profile["399"])
    point = {
        "blue_waist_mm": 3.0,
        "green_exclusion_radius_mm": 5.0,
        "crossing_distance_mm": 20.0,
    }
    apply_sequential_geometry(profile, point)
    assert sequential_geometry_fields(profile) == point

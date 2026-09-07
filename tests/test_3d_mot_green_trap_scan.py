from config import MOT_3D_CONFIGURATIONS, MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM
from studies.scan_3d_mot_green_trap import (
    DEFAULT_GREEN_DETUNINGS_GAMMA,
    DEFAULT_GREEN_S0_VALUES,
    FIXED_BLUE_DETUNING_GAMMA,
    FIXED_BLUE_S0,
    FIXED_GRADIENT_G_CM,
    green_rank_key,
)


def test_scan_includes_current_green_default_and_selected_fixed_settings():
    profile = MOT_3D_CONFIGURATIONS["angled_sequential"]

    assert profile["556"]["s0"] in DEFAULT_GREEN_S0_VALUES
    assert profile["556"]["detuning_gamma"] in DEFAULT_GREEN_DETUNINGS_GAMMA
    assert FIXED_BLUE_S0 == 0.6
    assert FIXED_BLUE_DETUNING_GAMMA == -1.65
    assert FIXED_GRADIENT_G_CM == MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM


def test_green_ranking_prioritizes_full_capture_before_partial_metrics():
    base = {
        "capture_eligible_ever_count": 0,
        "peak_capture_eligible_count": 0,
        "minimum_residence_met_count": 10,
        "slow_inside_count": 10,
        "entered_capture_region_count": 10,
    }
    captured = dict(base, capture_eligible_ever_count=1)

    assert green_rank_key(captured) > green_rank_key(base)

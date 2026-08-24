"""Canonical locations for generated simulation data."""

from pathlib import Path


DATA_DIR = Path("data")
PARTICLE_STATES_DIR = DATA_DIR / "particle_states"
AFTER_ZEEMAN_DIR = PARTICLE_STATES_DIR / "after_zeeman"
AFTER_2D_MOT_DIR = PARTICLE_STATES_DIR / "after_2d_mot"
AFTER_3D_MOT_DIR = PARTICLE_STATES_DIR / "after_3d_mot"
OPTIMIZATION_DIR = DATA_DIR / "optimization"
SEED_SCAN_DIR = OPTIMIZATION_DIR / "seed_scan"
VALIDATION_DIR = DATA_DIR / "validation"
ZEEMAN_VALIDATION_DIR = VALIDATION_DIR / "zeeman"
ZEEMAN_TRAJECTORY_VALIDATION_DIR = ZEEMAN_VALIDATION_DIR / "trajectories"
ZEEMAN_CAPTURE_SCAN_DIR = ZEEMAN_VALIDATION_DIR / "capture_velocity_scan"
ZEEMAN_CONVERGENCE_DIR = ZEEMAN_VALIDATION_DIR / "stochastic_convergence"

DEFAULT_ZEEMAN_STATES_FILE = AFTER_ZEEMAN_DIR / "zeeman_survivors.npy"
DEFAULT_2D_MOT_STATES_FILE = AFTER_2D_MOT_DIR / "mot_2d_survivors.npy"
DEFAULT_3D_MOT_STATES_FILE = AFTER_3D_MOT_DIR / "mot_3d_captured.npy"
DEFAULT_3D_MOT_SUMMARY_FILE = AFTER_3D_MOT_DIR / "capture_summary.json"
PRODUCTION_ZEEMAN_STATES_FILE = (
    AFTER_ZEEMAN_DIR / "production_zeeman_survivors_50k_dt40us.npy"
)
LEGACY_PRODUCTION_ZEEMAN_STATES_FILE = (
    DATA_DIR / "production_zeeman_survivors_50k_dt40us.npy"
)


def production_zeeman_states_file():
    """Prefer the organized path while supporting an existing Zeus dataset."""
    if PRODUCTION_ZEEMAN_STATES_FILE.exists():
        return PRODUCTION_ZEEMAN_STATES_FILE
    if LEGACY_PRODUCTION_ZEEMAN_STATES_FILE.exists():
        return LEGACY_PRODUCTION_ZEEMAN_STATES_FILE
    return PRODUCTION_ZEEMAN_STATES_FILE


def load_particle_states(path):
    """Load an ``(N, 6)`` particle-state array and validate its shape."""
    import numpy as np

    states = np.asarray(np.load(path), dtype=float)
    if states.ndim != 2 or states.shape[1] != 6:
        raise ValueError(
            f"Expected particle states with shape (N, 6), got {states.shape}"
        )
    return states


def save_particle_states(path, states):
    """Save particle states, creating the stage directory when necessary."""
    import numpy as np

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, np.asarray(states, dtype=float))
    return output_path

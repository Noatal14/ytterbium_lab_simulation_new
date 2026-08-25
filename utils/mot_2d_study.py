"""Shared helpers for statistically paired 2D-MOT studies."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t

from utils.data_paths import production_zeeman_ensemble_files


def load_production_ensembles(
    max_ensembles=None, particles_per_ensemble=None, directory=None
):
    """Load the same deterministic particle subsets for every parameter point."""
    paths = (
        production_zeeman_ensemble_files()
        if directory is None
        else production_zeeman_ensemble_files(directory)
    )
    if max_ensembles is not None:
        paths = paths[:max_ensembles]
    if not paths:
        raise FileNotFoundError(
            "No per-seed Zeeman production ensembles were found under "
            "data/particle_states/after_zeeman."
        )

    ensembles = []
    for path in paths:
        states = np.load(path, mmap_mode="r")
        if states.ndim != 2 or states.shape[1] != 6:
            raise ValueError(f"Invalid particle-state shape in {path}: {states.shape}")
        if particles_per_ensemble is not None:
            states = states[:particles_per_ensemble]
        metadata_path = path.with_suffix(".json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        ensembles.append(
            {
                "path": path,
                "zeeman_seed": int(metadata["parameters"]["seed"]),
                "n_initial_zeeman": int(metadata["parameters"]["n_initial_atoms"]),
                "zeeman_survival_fraction": float(metadata["survival_fraction"]),
                "states": np.asarray(states),
            }
        )
    return ensembles


def student_mean_interval(values, confidence=0.95):
    """Return a mean and Student-t CI across independent paired replicates."""
    values = np.asarray(values, dtype=float)
    mean = float(np.mean(values))
    if len(values) < 2:
        return mean, None, None, None
    std = float(np.std(values, ddof=1))
    sem = std / np.sqrt(len(values))
    critical = float(student_t.ppf(0.5 + confidence / 2.0, len(values) - 1))
    return mean, mean - critical * sem, mean + critical * sem, critical * sem


def summarize_replicates(replicates):
    """Summarize conditional and total efficiency across paired replicates."""
    conditional = [row["conditional_efficiency"] for row in replicates]
    total = [row["estimated_total_efficiency"] for row in replicates]
    c_mean, c_low, c_high, c_half = student_mean_interval(conditional)
    t_mean, t_low, t_high, t_half = student_mean_interval(total)
    return {
        "n_replicates": len(replicates),
        "mean_conditional_efficiency": c_mean,
        "conditional_95_ci": [c_low, c_high],
        "conditional_95_ci_half_width": c_half,
        "mean_estimated_total_efficiency": t_mean,
        "estimated_total_95_ci": [t_low, t_high],
        "estimated_total_95_ci_half_width": t_half,
    }

"""Shared helpers for statistically paired 2D-MOT studies."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import numpy as np
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    attest_canonical_zeeman_metadata,
)
from scipy.stats import t as student_t

from utils.data_paths import production_zeeman_ensemble_files


def load_production_ensembles(
    max_ensembles=None,
    particles_per_ensemble=None,
    directory=None,
    zeeman_seeds=None,
    expected_profile=None,
    verify_sha256=True,
    acceptance_profile_id=None,
):
    """Load the same deterministic particle subsets for every parameter point."""
    from workflow_api.acceptance_profile import assert_acceptance_path, assert_scientific_source, load_acceptance_profile
    acceptance = load_acceptance_profile(acceptance_profile_id) if acceptance_profile_id is not None else None
    if acceptance is not None:
        if directory is None:
            raise ValueError("Acceptance ensembles require an explicit isolated directory.")
        assert_acceptance_path(directory, Path.cwd())
    elif directory is not None and "ui_acceptance" in Path(directory).parts:
        raise ValueError("TEST ONLY ensembles require an explicit acceptance profile.")
    paths = (
        production_zeeman_ensemble_files()
        if directory is None
        else production_zeeman_ensemble_files(directory)
    )
    if acceptance is not None:
        count = acceptance.policy['generation']['zeeman_initial_particles']
        paths = sorted(Path(directory).glob(f'production_zeeman_n{count}_dt40us_seed*.npy'))
    if zeeman_seeds is not None:
        requested = [int(seed) for seed in zeeman_seeds]
        by_seed = {}
        for path in paths:
            metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            by_seed[int(metadata["parameters"]["seed"])] = path
        missing = [seed for seed in requested if seed not in by_seed]
        if missing:
            raise FileNotFoundError(
                f"Missing Zeeman production ensembles for seeds: {missing}"
            )
        paths = [by_seed[seed] for seed in requested]
    if max_ensembles is not None:
        paths = paths[:max_ensembles]
    if not paths:
        raise FileNotFoundError(
            "No per-seed Zeeman production ensembles were found under "
            "data/particle_states/after_zeeman."
        )

    ensembles = []
    for path in paths:
        metadata_path = path.with_suffix(".json")
        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing adjacent metadata: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if acceptance is None:
            assert_scientific_source(metadata)
        elif metadata.get("acceptance") != acceptance.provenance():
            raise ValueError("Acceptance ensemble profile mismatch.")
        parameters = metadata.get("parameters", {})
        zeeman_seed = int(parameters["seed"])
        if expected_profile is not None:
            resolved = parameters.get("resolved_zeeman_magnet_profile")
            if resolved != expected_profile:
                raise ValueError(
                    f"Zeeman profile mismatch in {metadata_path}: "
                    f"expected {expected_profile!r}, found {resolved!r}"
                )
        if parameters.get("resolved_zeeman_magnet_profile") != CANONICAL_ZEEMAN_PROFILE_NAME:
            raise ValueError(
                f"Zeeman laboratory provenance mismatch in {metadata_path}"
            )
        try:
            laboratory = attest_canonical_zeeman_metadata(metadata, allow_legacy=True)
        except ValueError as error:
            raise ValueError(
                f"Zeeman laboratory provenance mismatch in {metadata_path}"
            ) from error
        states = np.load(path, mmap_mode="r")
        if states.ndim != 2 or states.shape[1] != 6:
            raise ValueError(f"Invalid particle-state shape in {path}: {states.shape}")
        if not np.all(np.isfinite(states)):
            raise ValueError(f"Non-finite particle states in {path}")
        if list(states.shape) != metadata.get("shape"):
            raise ValueError(f"State/metadata shape mismatch in {path}")
        if len(states) != int(metadata.get("n_survivors", -1)):
            raise ValueError(f"State/metadata survivor-count mismatch in {path}")
        expected_hash = metadata.get("output_sha256")
        if verify_sha256:
            if not isinstance(expected_hash, str):
                raise ValueError(f"Missing SHA-256 provenance in {metadata_path}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_hash:
                raise ValueError(f"SHA-256 mismatch in {path}")
        source_shape = list(states.shape)
        source_dtype = str(states.dtype)
        n_available = len(states)
        subset_seed = 100_000 + zeeman_seed
        if particles_per_ensemble is not None and particles_per_ensemble < n_available:
            rng = np.random.default_rng(subset_seed)
            selected_indices = np.sort(
                rng.choice(n_available, size=particles_per_ensemble, replace=False)
            )
            states = states[selected_indices]
            selection_method = "deterministic_random_without_replacement"
        else:
            states = np.asarray(states)
            selection_method = "all_particles"
        ensembles.append(
            {
                "path": path,
                "zeeman_seed": zeeman_seed,
                "n_initial_zeeman": int(metadata["parameters"]["n_initial_atoms"]),
                "zeeman_survival_fraction": float(metadata["survival_fraction"]),
                "states": np.asarray(states),
                "n_available": n_available,
                "selection_method": selection_method,
                "subset_seed": subset_seed,
                "sha256": expected_hash,
                "shape": source_shape,
                "dtype": source_dtype,
                "zeeman_profile": parameters.get("resolved_zeeman_magnet_profile"),
                "metadata_path": metadata_path,
                "source_git_commit": metadata.get("software", {}).get("git_commit"),
                "laboratory_spec_version": metadata.get("laboratory_spec_version"),
                "laboratory_spec_sha256": metadata.get("laboratory_spec_sha256"),
                "zeeman_profile_sha256": laboratory["zeeman_profile_sha256"],
                "legacy_attested_profile": laboratory["legacy_attested_profile"],
                "generation": {
                    "n_initial_atoms": parameters.get("n_initial_atoms"),
                    "dt_s": parameters.get("dt_s"),
                    "stochastic": parameters.get("stochastic"),
                    "collimation_angle_deg": parameters.get("collimation_angle_deg"),
                },
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
    sem = float(std / np.sqrt(len(values)))
    critical = float(student_t.ppf(0.5 + confidence / 2.0, len(values) - 1))
    half_width = float(critical * sem)
    return mean, mean - half_width, mean + half_width, half_width


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


def prediction_for_new_run(replicates, reporting_survivors=10_000_000):
    """Predict capture in a new large run from independent replicate results."""
    efficiencies = np.asarray(
        [row["conditional_efficiency"] for row in replicates], dtype=float
    )
    if len(efficiencies) < 2:
        return None
    mean = float(np.mean(efficiencies))
    between_run_sem = float(np.std(efficiencies, ddof=1) / np.sqrt(len(efficiencies)))
    future_counting_sem = float(np.sqrt(mean * (1.0 - mean) / reporting_survivors))
    combined_sem = float(np.sqrt(between_run_sem**2 + future_counting_sem**2))
    critical = float(student_t.ppf(0.975, len(efficiencies) - 1))
    half_width = float(critical * combined_sem)
    return {
        "reporting_zeeman_survivors": int(reporting_survivors),
        "expected_conditional_efficiency": mean,
        "expected_captured_atoms": int(round(mean * reporting_survivors)),
        "predicted_95_interval_fraction": [
            max(0.0, mean - half_width),
            min(1.0, mean + half_width),
        ],
        "predicted_95_half_width_fraction": half_width,
        "predicted_95_half_width_percentage_points": 100 * half_width,
        "method": (
            "Student-t uncertainty of the estimated mean combined with "
            f"binomial counting noise for a new {reporting_survivors:,}-survivor run"
        ),
    }

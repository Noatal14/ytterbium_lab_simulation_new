"""Pure final-production prediction helpers for fixed-s0 2D-MOT runs.

This module is deliberately independent of the executable ``studies``
package so campaign validation and the command-line runner share the exact
same statistical derivation without crossing the server import boundary.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import t as student_t


REPORTING_SURVIVORS = 10_000_000


def cluster_bootstrap_prediction(
    replicates: list[dict[str, Any]],
    reporting_survivors: int = REPORTING_SURVIVORS,
    draws: int = 20_000,
    random_seed: int = 20261005,
) -> np.ndarray:
    """Sample the survivor-weighted pooled efficiency and future count."""
    n_input = np.asarray([row["n_input"] for row in replicates], dtype=float)
    captured = np.asarray([row["captured"] for row in replicates], dtype=float)
    rng = np.random.default_rng(random_seed)
    bootstrap = np.empty(draws)
    for index in range(draws):
        selected = rng.integers(0, len(replicates), len(replicates))
        selected_n = n_input[selected]
        probabilities = rng.beta(
            captured[selected] + 0.5,
            selected_n - captured[selected] + 0.5,
        )
        pooled_probability = float(
            np.sum(probabilities * selected_n) / np.sum(selected_n)
        )
        bootstrap[index] = (
            rng.binomial(reporting_survivors, pooled_probability)
            / reporting_survivors
        )
    return bootstrap


def final_prediction(
    replicates: list[dict[str, Any]],
    reporting_survivors: int = REPORTING_SURVIVORS,
) -> dict[str, Any]:
    """Derive the frozen final-production point estimate and uncertainty."""
    n_input = np.asarray([row["n_input"] for row in replicates], dtype=float)
    captured = np.asarray([row["captured"] for row in replicates], dtype=float)
    efficiencies = captured / n_input
    total_input = int(n_input.sum())
    total_captured = int(captured.sum())
    pooled_efficiency = float(total_captured / total_input)

    binomial_mean_variance = float(
        pooled_efficiency * (1.0 - pooled_efficiency) / total_input
    )
    empirical_mean_variance = float(np.var(efficiencies, ddof=1) / len(efficiencies))
    use_empirical_variance = empirical_mean_variance > binomial_mean_variance
    selected_mean_variance = max(
        binomial_mean_variance,
        empirical_mean_variance,
    )
    future_counting_variance = float(
        pooled_efficiency * (1.0 - pooled_efficiency) / reporting_survivors
    )
    critical = float(
        student_t.ppf(0.975, len(replicates) - 1) if use_empirical_variance else 1.96
    )
    half_width = float(
        critical * np.sqrt(selected_mean_variance + future_counting_variance)
    )
    low = max(0.0, pooled_efficiency - half_width)
    high = min(1.0, pooled_efficiency + half_width)
    # Cluster-aware uncertainty: resample independent Zeeman/MOT ensemble
    # pairs, then sample each cluster's finite-count uncertainty and the new
    # reporting population.  This respects the actual crossed pair structure.
    bootstrap = cluster_bootstrap_prediction(replicates, reporting_survivors)
    bootstrap_low, bootstrap_high = map(float, np.quantile(bootstrap, [0.025, 0.975]))
    bootstrap_half = (bootstrap_high - bootstrap_low) / 2.0
    return {
        "reporting_zeeman_survivors": int(reporting_survivors),
        "simulated_zeeman_survivors": total_input,
        "simulated_captured_atoms": total_captured,
        "pooled_conditional_efficiency": pooled_efficiency,
        "expected_captured_atoms": int(round(pooled_efficiency * reporting_survivors)),
        "predicted_95_interval_fraction": [bootstrap_low, bootstrap_high],
        "predicted_95_captured_atoms_interval": [
            int(round(bootstrap_low * reporting_survivors)),
            int(round(bootstrap_high * reporting_survivors)),
        ],
        "predicted_95_half_width_fraction": bootstrap_half,
        "predicted_95_half_width_percentage_points": 100 * bootstrap_half,
        "binomial_mean_variance": binomial_mean_variance,
        "empirical_between_ensemble_mean_variance": empirical_mean_variance,
        "selected_mean_variance": selected_mean_variance,
        "selected_mean_variance_source": (
            "empirical_between_ensemble"
            if use_empirical_variance
            else "pooled_binomial"
        ),
        "critical_value": critical,
        "future_counting_variance": future_counting_variance,
        "uncertainty_method": (
            "20,000-draw cluster-aware parametric bootstrap: independent "
            "Zeeman/MOT ensemble pairs are resampled as clusters, finite "
            "within-cluster capture uncertainty is sampled with a Jeffreys "
            "beta model, cluster probabilities are pooled with their resampled "
            "survivor counts as weights, and future counting noise is sampled "
            "binomially"
        ),
        "bootstrap_replicates": 20_000,
    }

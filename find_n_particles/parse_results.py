from config import ZEEMAN_BEAM_DIR
from utils.file_helpers import read_data_json

import matplotlib.pyplot as plt
import numpy as np


def plot_multiple_zeeman_angular_intensities(
    particle_state_sets,
    labels,
    n_bins,
    normalization="max",
    max_angle_deg=None,
):
    """
    Plot normalized angular-intensity distributions for several
    Zeeman-survivor datasets.

    The angle theta is defined between the particle velocity vector
    and the Zeeman beam direction.

    The histogram estimates the theta probability density p(theta).
    For an approximately axisymmetric distribution,

        p(theta) ∝ I(theta) * sin(theta),

    so the angular intensity is reconstructed as

        I(theta) ∝ p(theta) / sin(theta).

    Parameters
    ----------
    particle_state_sets : list of array-like
        Each item must have shape (N, 6), where:
            state[:3] = position
            state[3:6] = velocity

    labels : list of str
        Label for each dataset.

    n_bins : int
        Number of angular bins shared by all datasets.

    normalization : {"max", "p95"}, optional
        Normalize every curve separately.

        "max":
            Divide by the maximum intensity.

        "p95":
            Divide by the 95th percentile of the nonzero intensity values.
            Some points may then be larger than 1.

    max_angle_deg : float or None, optional
        Maximum angle included in the histogram.

        If None, use the largest angle appearing in all datasets.

    Returns
    -------
    results : list of dict
        Calculated histogram and angular-intensity data for each dataset.
    """

    if len(particle_state_sets) != len(labels):
        raise ValueError(
            "particle_state_sets and labels must have the same length."
        )

    if not isinstance(n_bins, (int, np.integer)) or n_bins <= 0:
        raise ValueError("n_bins must be a positive integer.")

    beam_direction = -np.asarray(ZEEMAN_BEAM_DIR, dtype=float)

    beam_norm = np.linalg.norm(beam_direction)

    if not np.isfinite(beam_norm) or beam_norm == 0.0:
        raise ValueError("ZEEMAN_BEAM_DIR must be a valid nonzero vector.")

    beam_direction /= beam_norm

    all_theta_rad = []
    valid_particle_counts = []

    for particle_states in particle_state_sets:
        states = np.asarray(particle_states, dtype=float)

        if states.ndim != 2 or states.shape[1] < 6:
            raise ValueError(
                "Each particle-state array must have shape (N, 6) "
                "or contain at least six values per particle."
            )

        velocities = states[:, 3:6]
        speeds = np.linalg.norm(velocities, axis=1)

        valid_mask = (
            np.all(np.isfinite(velocities), axis=1)
            & np.isfinite(speeds)
            & (speeds > 0.0)
        )

        velocities = velocities[valid_mask]
        speeds = speeds[valid_mask]

        if len(velocities) == 0:
            raise ValueError(
                "One of the datasets contains no valid particle velocities."
            )

        cos_theta = (velocities @ beam_direction) / speeds
        cos_theta = np.clip(cos_theta, -1.0, 1.0)

        theta_rad = np.arccos(cos_theta)

        all_theta_rad.append(theta_rad)
        valid_particle_counts.append(len(theta_rad))

    if max_angle_deg is None:
        theta_max_rad = max(
            np.max(theta_rad)
            for theta_rad in all_theta_rad
        )

        if theta_max_rad <= 0.0:
            theta_max_rad = np.finfo(float).eps
    else:
        if not np.isfinite(max_angle_deg) or max_angle_deg <= 0.0:
            raise ValueError("max_angle_deg must be positive.")

        theta_max_rad = np.deg2rad(max_angle_deg)

    theta_edges = np.linspace(
        0.0,
        theta_max_rad,
        n_bins + 1,
    )

    theta_centers_rad = 0.5 * (
        theta_edges[:-1] + theta_edges[1:]
    )

    theta_centers_deg = np.rad2deg(theta_centers_rad)

    plt.figure(figsize=(11, 7))

    results = []

    for theta_rad, label, n_valid in zip(
        all_theta_rad,
        labels,
        valid_particle_counts,
    ):
        theta_in_range = theta_rad[
            theta_rad <= theta_max_rad
        ]

        if len(theta_in_range) == 0:
            raise ValueError(
                f"No particles from dataset '{label}' fall inside "
                "the requested angular range."
            )

        # Probability density p(theta).
        theta_pdf, _ = np.histogram(
            theta_in_range,
            bins=theta_edges,
            density=True,
        )

        # Convert p(theta) back to angular intensity:
        # I(theta) ∝ p(theta) / sin(theta).
        angular_intensity = np.divide(
            theta_pdf,
            np.sin(theta_centers_rad),
            out=np.zeros_like(theta_pdf, dtype=float),
            where=np.sin(theta_centers_rad) > 0.0,
        )

        if normalization == "max":
            normalization_value = np.max(angular_intensity)

        elif normalization == "p95":
            nonzero_intensity = angular_intensity[
                angular_intensity > 0.0
            ]

            normalization_value = (
                np.percentile(nonzero_intensity, 95)
                if len(nonzero_intensity) > 0
                else 0.0
            )

        else:
            raise ValueError(
                "normalization must be either 'max' or 'p95'."
            )

        if normalization_value > 0.0:
            normalized_intensity = (
                angular_intensity / normalization_value
            )
        else:
            normalized_intensity = np.zeros_like(
                angular_intensity
            )

        plt.xlim(0, 3.5)
        plt.plot(
            theta_centers_deg,
            normalized_intensity,
            marker="o",
            markersize=3,
            linewidth=1.4,
            label=label,
        )

        results.append(
            {
                "label": label,
                "theta_centers_deg": theta_centers_deg.copy(),
                "theta_pdf": theta_pdf,
                "angular_intensity": angular_intensity,
                "normalized_intensity": normalized_intensity,
                "particle_angles_deg": np.rad2deg(theta_rad),
                "n_valid_particles": n_valid,
                "n_particles_in_angle_range": len(theta_in_range),
                "normalization_value": normalization_value,
            }
        )

    plt.xlabel(
        r"Angle between $\vec{v}$ and Zeeman beam direction (degrees)",
        fontsize=16,
    )
    plt.ylabel(
        "Normalized angular intensity",
        fontsize=16,
    )
    plt.title(
        "Angular Distribution of Zeeman Beam Survivors",
        fontsize=20,
    )

    plt.tick_params(
        axis="both",
        which="major",
        labelsize=14,
    )

    plt.grid(alpha=0.3)
    plt.legend(fontsize=13)
    plt.tight_layout()
    plt.show()

    return results


if __name__ == "__main__":
    N_results = [
        1000,
        5000,
        10000,
        30000,
        50000,
        100000,
    ]

    states_by_particle_number = []

    for N in N_results:
        path = (
            "find_n_particles/"
            "zeeman_phase_survivors/"
            f"N_{N}.json"
        )

        data = read_data_json(path)

        print(
            f"Loaded {len(data)} survivors "
            f"from simulation with N={N}"
        )

        states_by_particle_number.append(data)

    labels = [
        f"N = {N:,}"
        for N in N_results
    ]

    results = plot_multiple_zeeman_angular_intensities(
        particle_state_sets=states_by_particle_number,
        labels=labels,
        n_bins=40,
        normalization="max",
        max_angle_deg=None,
    )
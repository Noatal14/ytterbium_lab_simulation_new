"""Shared presentation style for 3D-MOT longitudinal-velocity diagnostics."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np

from config import MOT_3D_CAPTURE_CONFIG


def plot_longitudinal_velocity(
    *,
    time_s,
    velocities_m_s,
    initial_vz_m_s,
    usable,
    title,
    output_path,
    statistics_lines=(),
    usable_label="captured at least once",
    unusable_label="not captured",
    emphasized_failure_count=30,
):
    """Plot one all-atom vz history using the curated figure-19 style."""
    time_ms = np.asarray(time_s, dtype=float) * 1e3
    velocities = np.asarray(velocities_m_s, dtype=float)
    initial = np.asarray(initial_vz_m_s, dtype=float)
    usable = np.asarray(usable, dtype=bool)
    if velocities.ndim != 2 or velocities.shape[0] != len(initial):
        raise ValueError("Velocity histories and initial velocities do not align.")
    if len(usable) != len(initial):
        raise ValueError("Usability mask and velocity histories do not align.")

    normalization = Normalize(
        vmin=float(np.nanmin(initial)), vmax=float(np.nanmax(initial))
    )
    colormap = plt.get_cmap("coolwarm")
    fig, axis = plt.subplots(figsize=(11, 7))

    # All unsuccessful trajectories remain visible as a neutral background.
    for row in velocities[~usable]:
        axis.plot(
            time_ms,
            row,
            color="#555b61",
            linewidth=0.5,
            alpha=0.20,
            rasterized=True,
        )

    # A deterministic velocity-stratified subset is slightly darker, making
    # representative loss paths traceable without dominating the figure.
    failed_indices = np.flatnonzero(~usable)
    emphasized = min(int(emphasized_failure_count), len(failed_indices))
    if emphasized:
        ordered = failed_indices[np.argsort(initial[failed_indices])]
        positions = np.linspace(0, len(ordered) - 1, emphasized, dtype=int)
        for row in velocities[ordered[positions]]:
            axis.plot(
                time_ms,
                row,
                color="#30343b",
                linewidth=0.8,
                alpha=0.65,
                rasterized=True,
            )

    for row, initial_vz in zip(velocities[usable], initial[usable]):
        axis.plot(
            time_ms,
            row,
            color=colormap(normalization(initial_vz)),
            linewidth=0.8,
            alpha=0.62,
            rasterized=True,
        )

    speed_bound = MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"]
    axis.axhline(speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.axhline(-speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.plot(
        [], [], color="tab:blue", linewidth=1.2,
        label=f"{usable_label} ({usable.sum()})",
    )
    failure_suffix = f"; {emphasized} emphasized" if emphasized else ""
    axis.plot(
        [], [], color="#555b61", linewidth=1.2,
        label=f"{unusable_label} ({len(usable) - usable.sum()}{failure_suffix})",
    )
    axis.set_xlabel("simulation time [ms]")
    axis.set_ylabel("longitudinal velocity vz [m/s]")
    axis.set_title(title)
    axis.grid(alpha=0.2)
    axis.legend()

    if statistics_lines:
        axis.text(
            0.985,
            0.77,
            "\n".join(statistics_lines),
            transform=axis.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            color="0.20",
            bbox={"facecolor": "white", "edgecolor": "0.75", "alpha": 0.88},
        )

    scalar = plt.cm.ScalarMappable(norm=normalization, cmap=colormap)
    scalar.set_array([])
    colorbar = fig.colorbar(scalar, ax=axis, pad=0.025)
    colorbar.set_label(
        "initial longitudinal velocity vz,0 [m/s]\nblue = slower, red = faster"
    )
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path

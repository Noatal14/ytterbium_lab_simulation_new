from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from scipy.ndimage import gaussian_filter

from utils.file_helpers import read_data_json


N_ZEEMAN_SURVIVORS = 28261

def largest_rectangle_in_mask(mask, x_grid, y_grid):
    """
    Find the largest axis-aligned rectangle fully contained
    inside a boolean 2D mask.

    Returns
    -------
    x_min, x_max, y_min, y_max
    """
    rows, cols = mask.shape

    heights = np.zeros(cols, dtype=int)

    best_area = 0
    best_bounds = None

    for row in range(rows):

        # Histogram of consecutive True cells ending at this row
        heights = np.where(
            mask[row],
            heights + 1,
            0,
        )

        stack = []

        for col in range(cols + 1):

            current_height = (
                heights[col]
                if col < cols
                else 0
            )

            start = col

            while stack and stack[-1][1] > current_height:

                start_idx, height = stack.pop()

                width = col - start_idx
                area = height * width

                if area > best_area:

                    best_area = area

                    row_bottom = row
                    row_top = row - height + 1

                    col_left = start_idx
                    col_right = col - 1

                    best_bounds = (
                        x_grid[col_left],
                        x_grid[col_right],
                        y_grid[row_top],
                        y_grid[row_bottom],
                    )

                start = start_idx

            stack.append(
                (start, current_height)
            )

    return best_bounds


# ============================================================
# Plot fixed-s0 optimization
# ============================================================

def plot_fixed_s0_optimization(
    s0,
    detuning,
    magnet_radius,
    success_count,
    n_zeeman_survivors=N_ZEEMAN_SURVIVORS,
    grid_size=300,
    bandwidth_detuning=0.18,
    bandwidth_radius_mm=0.8,
    region_fraction=0.98,
    region_density_threshold=0.15,
    save_path=None,
):
    """
    Plot fixed-s0 2D-MOT optimization results.

    The measured Optuna trials are shown as colored scatter points.

    A contour marks the region where the locally estimated capture
    efficiency is at least `region_fraction` of the maximum estimated
    efficiency, considering only sufficiently sampled regions.

    Parameters
    ----------
    s0 : float
        Fixed saturation parameter.

    detuning : array-like
        Detuning values in units of Gamma.

    magnet_radius : array-like
        Magnet radius values in meters.

    success_count : array-like
        Number of successfully captured MOT atoms for each trial.

    n_zeeman_survivors : int
        Number of atoms entering the MOT.

    grid_size : int
        Resolution of the interpolation grid.

    bandwidth_detuning : float
        Gaussian-kernel width in detuning units.

    bandwidth_radius_mm : float
        Gaussian-kernel width in mm for magnet radius.

    region_fraction : float
        Fraction of the estimated maximum efficiency used to define
        the high-efficiency region.

    region_density_threshold : float
        Minimum normalized Optuna sampling density required for a
        grid point to be included in the high-efficiency region.

    save_path : str or Path or None
        Optional output path.

    Returns
    -------
    fig, ax
        Matplotlib figure and axes.
    """

    # ========================================================
    # Convert inputs
    # ========================================================

    detuning = np.asarray(
        detuning,
        dtype=float,
    )

    magnet_radius = np.asarray(
        magnet_radius,
        dtype=float,
    )

    success_count = np.asarray(
        success_count,
        dtype=float,
    )

    if not (
        len(detuning)
        == len(magnet_radius)
        == len(success_count)
    ):
        raise ValueError(
            "detuning, magnet_radius and success_count "
            "must have the same length."
        )

    radius_mm = (
        1000.0 * magnet_radius
    )

    efficiency = (
        100.0
        * success_count
        / n_zeeman_survivors
    )

    # ========================================================
    # Best measured trial
    # ========================================================

    best_idx = np.argmax(
        efficiency
    )

    best_efficiency = (
        efficiency[best_idx]
    )

    best_detuning = (
        detuning[best_idx]
    )

    best_radius_mm = (
        radius_mm[best_idx]
    )

    # ========================================================
    # Interpolation grid
    # ========================================================

    x_margin = (
        0.08
        * (detuning.max() - detuning.min())
    )

    y_margin = (
        0.10
        * (radius_mm.max() - radius_mm.min())
    )

    if x_margin == 0:
        x_margin = 0.1

    if y_margin == 0:
        y_margin = 0.5

    x_grid = np.linspace(
        detuning.min() - x_margin,
        detuning.max() + x_margin,
        grid_size,
    )

    y_grid = np.linspace(
        radius_mm.min() - y_margin,
        radius_mm.max() + y_margin,
        grid_size,
    )

    X, Y = np.meshgrid(
        x_grid,
        y_grid,
    )

    # ========================================================
    # Kernel regression
    # ========================================================

    weighted_efficiency = np.zeros_like(
        X,
        dtype=float,
    )

    density = np.zeros_like(
        X,
        dtype=float,
    )

    for x_i, y_i, eta_i in zip(
        detuning,
        radius_mm,
        efficiency,
    ):

        distance_squared = (
            ((X - x_i) / bandwidth_detuning) ** 2
            +
            ((Y - y_i) / bandwidth_radius_mm) ** 2
        )

        weights = np.exp(
            -0.5 * distance_squared
        )

        density += weights

        weighted_efficiency += (
            weights * eta_i
        )

    efficiency_surface = (
        weighted_efficiency
        / np.maximum(density, 1e-12)
    )

    # Small smoothing for visual stability
    efficiency_surface = gaussian_filter(
        efficiency_surface,
        sigma=1.0,
    )

    density = gaussian_filter(
        density,
        sigma=1.0,
    )

    density_normalized = (
        density / density.max()
    )

    # ========================================================
    # Reliable interpolation region
    # ========================================================

    reliable_mask = (
        density_normalized
        >= region_density_threshold
    )

    if not np.any(reliable_mask):
        raise RuntimeError(
            "No interpolation grid points satisfy the "
            "sampling-density threshold."
        )

    max_estimated_efficiency = np.max(
        efficiency_surface[reliable_mask]
    )

    region_threshold = (
        region_fraction
        * max_estimated_efficiency
    )

    high_efficiency_mask = (
        reliable_mask
        &
        (
            efficiency_surface
            >= region_threshold
        )
    )

    # ========================================================
    # Largest rectangular region fully inside high-efficiency region
    # ========================================================

    if np.any(high_efficiency_mask):

        rectangle_bounds = largest_rectangle_in_mask(
            high_efficiency_mask,
            x_grid,
            y_grid,
        )

        if rectangle_bounds is None:
            raise RuntimeError(
                "Could not determine a rectangular "
                "high-efficiency region."
            )

        (
            detuning_min,
            detuning_max,
            radius_min,
            radius_max,
        ) = rectangle_bounds

    else:

        detuning_min = np.nan
        detuning_max = np.nan

        radius_min = np.nan
        radius_max = np.nan

    # ========================================================
    # Plot
    # ========================================================

    fig, ax = plt.subplots(
        figsize=(10, 7)
    )

    # --------------------------------------------------------
    # Actual Optuna trials
    # --------------------------------------------------------

    scatter = ax.scatter(
        detuning,
        radius_mm,
        c=efficiency,
        cmap="coolwarm",
        s=105,
        edgecolors="black",
        linewidths=1.0,
        zorder=3,
    )

    # --------------------------------------------------------
    # 98% high-efficiency region
    # --------------------------------------------------------

    if np.any(high_efficiency_mask):

        # Mask everything outside the sufficiently sampled region.
        contour_surface = np.ma.masked_where(
            ~reliable_mask,
            efficiency_surface,
        )

        # --------------------------------------------------------
        # High-efficiency rectangular operating region
        # --------------------------------------------------------

        if np.any(high_efficiency_mask):

            from matplotlib.patches import Rectangle

            rectangle = Rectangle(
                (detuning_min, radius_min),
                detuning_max - detuning_min,
                radius_max - radius_min,
                fill=False,
                linewidth=2.5,
                edgecolor="purple",
                linestyle="-",
                zorder=4,
                label=(
                    f"{100 * region_fraction:.0f}% "
                    "high-efficiency operating region"
                ),
            )

            ax.add_patch(rectangle)

    # --------------------------------------------------------
    # Best measured trial
    # --------------------------------------------------------

    ax.scatter(
        best_detuning,
        best_radius_mm,
        marker="*",
        s=360,
        facecolors="white",
        edgecolors="black",
        linewidths=2.0,
        zorder=6,
        label=(
            f"Best trial: {best_efficiency:.2f}%\n"
            f"$\\Delta/\\Gamma$ = {best_detuning:.3f}\n"
            f"Magnet radius = {best_radius_mm:.2f} mm"
        ),
    )

    # ========================================================
    # 98% region information box
    # ========================================================

    if np.any(high_efficiency_mask):

        region_percent = (
            100.0 * region_fraction
        )

        region_text = (
            f"{region_percent:.0f}% high-efficiency operating range\n"
            f"$\\Delta/\\Gamma$: "
            f"{detuning_min:.3f} to {detuning_max:.3f}\n"
            f"Magnet radius: "
            f"{radius_min:.2f} to {radius_max:.2f} mm"
        )

        ax.text(
            0.02,
            0.02,
            region_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment="bottom",
            bbox=dict(
                boxstyle="round",
                facecolor="white",
                alpha=0.9,
            ),
        )

    # ========================================================
    # Colorbar
    # ========================================================

    cbar = fig.colorbar(
        scatter,
        ax=ax,
        pad=0.02,
    )

    cbar.set_label(
        "MOT capture efficiency (%)"
    )

    # ========================================================
    # Labels
    # ========================================================

    ax.set_xlabel(
        r"Detuning $\Delta/\Gamma$"
    )

    ax.set_ylabel(
        "Magnet radius (mm)"
    )

    ax.set_title(
        rf"2D MOT capture efficiency — fixed $s_0={s0}$"
    )

    ax.grid(
        alpha=0.20
    )

    ax.legend(
        loc="upper right",
    )

    plt.tight_layout()

    # ========================================================
    # Print useful numerical information
    # ========================================================

    print()
    print("========================================")
    print(f"Fixed s0 = {s0}")
    print("========================================")

    print(
        f"Best measured efficiency = "
        f"{best_efficiency:.4f}%"
    )

    print(
        f"Best detuning = "
        f"{best_detuning:.6f}"
    )

    print(
        f"Best magnet radius = "
        f"{best_radius_mm:.4f} mm"
    )

    print()

    print(
        f"Maximum locally estimated efficiency = "
        f"{max_estimated_efficiency:.4f}%"
    )

    print(
        f"{100 * region_fraction:.0f}% threshold = "
        f"{region_threshold:.4f}%"
    )

    if np.any(high_efficiency_mask):

        print()
        print(
            f"{100 * region_fraction:.0f}% high-efficiency region:"
        )

        print(
            f"detuning range = "
            f"[{detuning_min:.6f}, "
            f"{detuning_max:.6f}]"
        )

        print(
            f"magnet radius range = "
            f"[{radius_min:.4f}, "
            f"{radius_max:.4f}] mm"
        )

    # ========================================================
    # Save
    # ========================================================

    if save_path is not None:

        save_path = Path(
            save_path
        )

        save_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fig.savefig(
            save_path,
            dpi=300,
            bbox_inches="tight",
        )

        print(
            f"Saved figure: {save_path}"
        )

    return fig, ax


# ============================================================
# Load fixed-s0 results
# ============================================================

def load_fixed_s0_results(
    s0,
    data_dir="data",
):
    """
    Load fixed-s0 optimization results from the JSON summary.
    """

    file_path = (
        Path(data_dir)
        / (
            "mot_optimization_fixed_s0_"
            f"{s0:.6f}_summary.json"
        )
    )

    if not file_path.exists():
        raise FileNotFoundError(
            f"Could not find results for s0={s0}: "
            f"{file_path}"
        )

    data = read_data_json(
        file_path
    )

    results = list(
        data.values()
    )

    detuning = np.array(
        [
            result["detuning_gamma"]
            for result in results
        ],
        dtype=float,
    )

    magnet_radius = np.array(
        [
            result["magnet_radius"]
            for result in results
        ],
        dtype=float,
    )

    success_count = np.array(
        [
            result["success_count"]
            for result in results
        ],
        dtype=int,
    )

    return (
        detuning,
        magnet_radius,
        success_count,
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    s0_values = [
        1.1,
        1.2,
        1.3,
        1.35,
        1.37,
        1.4,
        1.42,
        1.45,
        1.47,
        1.5,
        1.6,
    ]

    output_dir = Path(
        "graphs/mot_optimization"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for s0 in s0_values:

        detuning, magnet_radius, success_count = (
            load_fixed_s0_results(
                s0
            )
        )

        print(
            f"Loaded {len(success_count)} "
            f"trials for s0={s0}"
        )

        save_path = (
            output_dir
            / (
                "fixed_s0_optimization_"
                f"{s0:.2f}.png"
            )
        )

        fig, ax = plot_fixed_s0_optimization(
            s0=s0,
            detuning=detuning,
            magnet_radius=magnet_radius,
            success_count=success_count,
            region_fraction=0.99,
            region_density_threshold=0.15,
            save_path=save_path,
        )

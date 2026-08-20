from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from utils.file_helpers import read_data_json


# ============================================================
# Input data
# ============================================================

RESULTS_FILE = Path(
    "data/optimization/mot_optimization_s0max1p5_summary.json"
)

N_ZEEMAN_SURVIVORS = 28261


# ============================================================
# Load Optuna results
# ============================================================

def load_optimization_results(results_file=RESULTS_FILE):
    """
    Load the constrained 3-parameter 2D MOT optimization results.

    Returns
    -------
    s0 : np.ndarray
        Saturation parameter values.

    detuning : np.ndarray
        Detuning values in units of Gamma.

    magnet_radius : np.ndarray
        Magnet radius values in meters.

    success_count : np.ndarray
        Number of successfully captured MOT atoms.
    """

    if not Path(results_file).exists():
        raise FileNotFoundError(
            f"Optimization results file not found: "
            f"{results_file}"
        )

    data = read_data_json(results_file)

    results = list(data.values())

    s0 = np.array(
        [
            result["s0"]
            for result in results
        ],
        dtype=float,
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
        s0,
        detuning,
        magnet_radius,
        success_count,
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    (
        s0,
        detuning,
        magnet_radius,
        success_count,
    ) = load_optimization_results()

    capture_efficiency = (
        100
        * success_count
        / N_ZEEMAN_SURVIVORS
    )

    print(
        f"Loaded {len(success_count)} completed trials"
    )

    # ========================================================
    # Best trial
    # ========================================================

    best_idx = np.argmax(
        capture_efficiency
    )

    print()
    print("Best trial:")
    print(
        f"s0 = {s0[best_idx]:.4f}"
    )
    print(
        f"detuning = {detuning[best_idx]:.4f}"
    )
    print(
        f"magnet radius = "
        f"{1000 * magnet_radius[best_idx]:.2f} mm"
    )
    print(
        f"capture efficiency = "
        f"{capture_efficiency[best_idx]:.3f}%"
    )

    # ========================================================
    # Plot
    # ========================================================

    fig, ax = plt.subplots(
        figsize=(9, 6)
    )

    scatter = ax.scatter(
        s0,
        detuning,
        c=capture_efficiency,
        cmap="coolwarm",
        s=120,
        edgecolors="black",
    )

    # Mark best trial
    ax.scatter(
        s0[best_idx],
        detuning[best_idx],
        marker="*",
        s=350,
        facecolors="none",
        edgecolors="black",
        linewidths=2.0,
        zorder=5,
        label=(
            f"Best trial: "
            f"{capture_efficiency[best_idx]:.2f}%\n"
            f"$s_0$ = {s0[best_idx]:.3f}\n"
            f"$\\Delta/\\Gamma$ = "
            f"{detuning[best_idx]:.3f}\n"
            f"Magnet radius = "
            f"{1000 * magnet_radius[best_idx]:.2f} mm"
        ),
    )

    cbar = plt.colorbar(
        scatter,
        ax=ax,
    )

    cbar.set_label(
        "MOT capture efficiency (%)"
    )

    ax.set_xlabel(
        r"$s_0$"
    )

    ax.set_ylabel(
        r"Detuning $\Delta/\Gamma$"
    )

    ax.set_title(
        r"2D MOT optimization results "
        r"($s_0 \leq 1.5$)"
    )

    ax.grid(
        alpha=0.25
    )

    ax.legend()

    plt.tight_layout()

    # ============================================================
    # Save figure
    # ============================================================

    output_dir = Path("graphs/mot_optimization")
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = output_dir / "mot_optimization_s0max1p5.png"

    fig.savefig(
        output_file,
        dpi=300,
        bbox_inches="tight",
    )

    print(f"Figure saved to: {output_file}")

    plt.show()
    plt.show()

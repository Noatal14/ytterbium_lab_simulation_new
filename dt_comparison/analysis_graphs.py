from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from utils.graph_utils import make_graph
from utils.helper_functions import read_data


def load_dt_summary(summary_path):
    data = read_data(summary_path)
    dt = data.get("dt")
    spread = data.get("transverse_spread_exit")
    temp = data.get("transverse_temp_mK")
    n_seeds = data.get("n_seeds")
    std_vx = data.get("std_vx_exit")
    std_vy = data.get("std_vy_exit")

    if dt is None or spread is None or temp is None or n_seeds is None or std_vx is None or std_vy is None:
        raise ValueError(
            f"Required columns are missing from {summary_path}. "
            "Expected dt, n_seeds, std_vx_exit, std_vy_exit, transverse_spread_exit, transverse_temp_mK."
        )

    dt = np.asarray(dt, dtype=float)
    spread = np.asarray(spread, dtype=float)
    temp = np.asarray(temp, dtype=float)
    n_seeds = np.asarray(n_seeds, dtype=float)
    std_vx = np.asarray(std_vx, dtype=float)
    std_vy = np.asarray(std_vy, dtype=float)

    # Simple error estimates using the reported velocity standard deviations and seed count.
    spread_err = np.sqrt((std_vx**2 + std_vy**2) / np.maximum(n_seeds, 1.0))
    temp_err = temp / np.sqrt(np.maximum(n_seeds, 1.0))

    order = np.argsort(dt)
    return (
        dt[order],
        spread[order],
        temp[order],
        spread_err[order],
        temp_err[order],
    )


def plot_exit_transverse_spread(dt, spread, spread_err, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / "exit_transverse_spread_vs_dt.png"
    make_graph(
        dt,
        spread,
        yerr=spread_err,
        save=True,
        filename=str(filename),
        title="Exit Transverse Spread vs Time Step (dt)",
        xlabel="dt (s)",
        ylabel="Exit Transverse Spread",
        show=False,
        fit=None,
    )
    print(f"Saved spread plot to: {filename}")


def plot_exit_transverse_temperature(dt, temp, temp_err, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / "exit_transverse_temp_vs_dt.png"
    fit = "power_offset" if len(dt) >= 3 else None
    if fit is None:
        print(
            "Not enough points for x^p + x_0 fitting; plotting temperature without a fit."
        )
    fig, ax, fit_result = make_graph(
        dt,
        temp,
        yerr=temp_err,
        save=True,
        filename=str(filename),
        title="Exit Transverse Temperature vs Time Step (dt)",
        xlabel="dt (s)",
        ylabel="Transverse Temperature (mK)",
        show=False,
        fit=fit,
    )
    print(f"Saved temperature plot to: {filename}")
    if fit_result is not None:
        print("Temperature fit:", fit_result["label"])


def main():
    summary_path = ROOT / "tests" / "dt_comparison" / "figures" / "summary.csv"
    output_dir = ROOT / "tests" / "dt_comparison" / "figures"

    dt, spread, temp, spread_err, temp_err = load_dt_summary(summary_path)
    plot_exit_transverse_spread(dt, spread, spread_err, output_dir)
    plot_exit_transverse_temperature(dt, temp, temp_err, output_dir)


if __name__ == "__main__":
    main()

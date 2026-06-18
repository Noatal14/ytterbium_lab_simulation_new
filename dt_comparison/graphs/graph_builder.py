from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence
import numpy as np
from dt_comparison.graphs.data_getter import _get_all_dts, compute_force_Ni_bad_fraction, get_data_for_dt
from utils.qualitative_analysis_graphs_builder import (
    plot_2d_series,
    plot_3d_paths,
    plot_grouped_histogram,
    plot_scatter_with_thresholds,
)
from utils.file_helpers import read_data_json
from utils.data_helpers import make_histogram_counts


DEFAULT_NI_BINS = [0.0, 2.0, 5.0, 10.0, 20.0, np.inf]
DEFAULT_NI_LABELS = ["0-2", "2-5", "5-10", "10-20", "20+"]

def plot_force_vs_Ni_diagnostic(
    Ni_values,
    force_values,
    dt_value: float,
    output_dir: Path,
    epsilon: float = 0.1,
    N_min: float = 10.0,

) -> None:
    diagnostics = compute_force_Ni_bad_fraction(
        Ni_values=Ni_values,
        force_values=force_values,
        epsilon=epsilon,
        N_min=N_min,
        dt_value=dt_value,
        output_dir=output_dir,
    )

    Ni_values = diagnostics["Ni_values"]
    F_norm = diagnostics["F_norm"]
    filename = output_dir / f"force_vs_Ni_dt_{dt_value:.0e}.png"
    plot_Ni = np.maximum(Ni_values, 1e-12)
    
    plot_scatter_with_thresholds(
        x=plot_Ni,
        y=F_norm,
        title=f"dt={dt_value:.0e}, epsilon={epsilon}, N_min={N_min}, bad_fraction={diagnostics['bad_fraction']:.3f}",
        xlabel="N_i = rate * dt",
        ylabel="Normalized force",
        x_threshold=N_min,
        y_threshold=epsilon,
        x_threshold_label=f"N_min = {N_min}",
        y_threshold_label=f"epsilon = {epsilon}",
        save=True,
        filename=filename,
    )
    
def plot_3d_apparatus_for_dt(
    dt_value: float,
    output_dir: Path,
    deterministic,
    stochastic_mean,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"apparatus_3d_dt_{dt_value:.0e}.png"

    plot_3d_paths(
        paths=[deterministic, stochastic_mean],
        labels=["deterministic", "mean stochastic"],
        colors=["C0", "C1"],
        title=f"3D Apparatus for dt={dt_value} with MOT beams",
        xlabel="x",
        ylabel="y",
        zlabel="z",
        save=True,
        filename=filename,
    )
    print(f"Saved 3D apparatus graph for dt={dt_value} to {filename}")


def plot_distance_vs_time_for_dts(
    data: dict,
    dt_values: Iterable[float],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    x_series = []
    y_series = []
    labels = []

    for dt_value in dt_values:
        x_series.append(data[dt_value]["time_values"])
        y_series.append(data[dt_value]["distance"])
        labels.append(f"dt={dt_value}")

    filename = output_dir / "distance_between_paths_vs_time.png"
    plot_2d_series(
        x_series=x_series,
        y_series=y_series,
        labels=labels,
        title="Distance between deterministic and mean stochastic path vs time",
        xlabel="time (s)",
        ylabel="distance (m)",
        save=True,
        filename=filename,
    )
    print(f"Saved distance vs time plot to {filename}")


def plot_ni_histogram_for_dt(
    dt_value: float,
    laser_names: Sequence[str],
    mean_N_channels: Sequence[float],
    output_dir: Path,
    bins: Sequence[float] = DEFAULT_NI_BINS,
    bin_labels: Sequence[str] = DEFAULT_NI_LABELS,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = make_histogram_counts(
        names=laser_names, 
        vals=mean_N_channels, 
        bins=bins
    )
    filename = output_dir / f"ni_histogram_dt_{dt_value:.0e}.png"

    plot_grouped_histogram(
        categories=list(bin_labels),
        counts=counts,
        labels=list(laser_names[:len(counts)]),
        title=f"Ni histogram by laser for dt={dt_value}",
        xlabel="Ni range",
        ylabel="count",
        save=True,
        filename=filename,
    )

    print(f"Saved Ni histogram for dt={dt_value} to {filename}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot 3D apparatus graphs and comparison graphs from simulation JSON files."
    )
    parser.add_argument("json_file", help="The JSON file containing summary_rows entries.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    json_file = str(Path(args.json_file).resolve())
    json_filename = Path(json_file).stem
    json_data = read_data_json(json_file)
    
    args = {
        "output_dir": Path(json_file).resolve().parent / "figures",
        "laser_names": ["laser1", "laser2", "laser3", "laser4"],
        "epsilon": 0.1,
        "n_min": 10,
    }
        
    # Create subdirectories for each plot type
    apparatus_3d_dir = args["output_dir"] / json_filename / "3d_apparatus"
    distance_vs_time_dir = args["output_dir"] / json_filename / "distance_vs_time"
    ni_histogram_dir = args["output_dir"] / json_filename / "ni_histogram"
    force_vs_ni_dir = args["output_dir"] / json_filename / "force_vs_ni"

    dt_values = _get_all_dts(json_data)
    dt_values = sorted(set(float(value) for value in dt_values))

    data = {}
    for dt_value in dt_values:
        data[dt_value] = get_data_for_dt(
            data=json_data,
            dt_value=dt_value,
        )

    for dt_value in dt_values:
        plot_3d_apparatus_for_dt(
            dt_value = dt_value,
            output_dir = apparatus_3d_dir, 
            deterministic=data[dt_value]["deterministic_trajectory"],
            stochastic_mean=data[dt_value]["stochastic_mean_trajectory"],
        )
        plot_ni_histogram_for_dt(
            dt_value = dt_value,
            laser_names = args["laser_names"],
            mean_N_channels = data[dt_value]["mean_N_channels"],
            output_dir = ni_histogram_dir,
        )
        plot_force_vs_Ni_diagnostic(
            Ni_values = data[dt_value]["Ni_values"],
            force_values = data[dt_value]["force_values"],
            dt_value = dt_value,
            output_dir = force_vs_ni_dir,
            epsilon = args["epsilon"],
            N_min = args["n_min"],
        )

    plot_distance_vs_time_for_dts(
        data = data,
        dt_values = dt_values,
        output_dir = distance_vs_time_dir,
    )


if __name__ == "__main__":
    main()

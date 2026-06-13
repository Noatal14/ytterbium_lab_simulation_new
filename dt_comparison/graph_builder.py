from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np

from dt_comparison.data_getter import get_json_value
from utils.qualitative_analysis_graphs_builder import (
    plot_2d_series,
    plot_3d_paths_with_beams,
    plot_grouped_histogram,
    plot_scatter_with_thresholds,
)


DEFAULT_NI_BINS = [0.0, 2.0, 5.0, 10.0, 20.0, np.inf]
DEFAULT_NI_LABELS = ["0-2", "2-5", "5-10", "10-20", "20+"]


def _flatten_channel_data(channel_list):
    if not channel_list:
        return np.array([], dtype=float)
    flattened = np.concatenate([np.asarray(channel, dtype=float).ravel() for channel in channel_list])
    return flattened


def compute_force_Ni_bad_fraction(
    mean_N_channels: Sequence,
    mean_force_channels: Sequence,
    epsilon: float = 0.1,
    N_min: float = 10.0,
) -> dict:
    Ni_values = _flatten_channel_data(mean_N_channels)
    force_values = _flatten_channel_data(mean_force_channels)

    if Ni_values.size == 0 or force_values.size == 0:
        return {
            "total_points": 0,
            "important_points": 0,
            "bad_points": 0,
            "bad_fraction": 0.0,
            "min_Ni_among_important": None,
            "median_Ni_among_important": None,
            "percentile_5_Ni_among_important": None,
            "F_scale": 0.0,
            "F_norm": np.array([], dtype=float),
            "Ni_values": Ni_values,
            "force_values": force_values,
        }

    F_scale = float(np.nanpercentile(force_values, 95.0))
    if not np.isfinite(F_scale) or F_scale <= 0.0:
        F_scale = 0.0
        F_norm = np.zeros_like(force_values, dtype=float)
    else:
        F_norm = force_values / F_scale

    important_mask = F_norm > epsilon
    important_points = int(np.count_nonzero(important_mask))
    bad_mask = important_mask & (Ni_values < N_min)
    bad_points = int(np.count_nonzero(bad_mask))
    total_points = int(force_values.size)
    bad_fraction = float(bad_points / important_points) if important_points > 0 else 0.0

    Ni_important = Ni_values[important_mask]
    if Ni_important.size > 0:
        min_Ni = float(np.min(Ni_important))
        median_Ni = float(np.median(Ni_important))
        percentile_5_Ni = float(np.percentile(Ni_important, 5.0))
    else:
        min_Ni = None
        median_Ni = None
        percentile_5_Ni = None

    return {
        "total_points": total_points,
        "important_points": important_points,
        "bad_points": bad_points,
        "bad_fraction": bad_fraction,
        "min_Ni_among_important": min_Ni,
        "median_Ni_among_important": median_Ni,
        "percentile_5_Ni_among_important": percentile_5_Ni,
        "F_scale": F_scale,
        "F_norm": F_norm,
        "Ni_values": Ni_values,
        "force_values": force_values,
    }


def plot_force_vs_Ni_diagnostic(
    json_file: str,
    dt_value: float,
    output_dir: Path,
    epsilon: float = 0.1,
    N_min: float = 10.0,
    show: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_index = _find_dt_row_index(json_file, dt_value)

    mean_n_channels = get_json_value(
        json_file, f"summary_rows.{row_index}.stochastic_results.mean_N_channels", default=[]
    )
    mean_force_channels = get_json_value(
        json_file, f"summary_rows.{row_index}.stochastic_results.mean_force_channels", default=[]
    )

    diagnostics = compute_force_Ni_bad_fraction(
        mean_n_channels,
        mean_force_channels,
        epsilon=epsilon,
        N_min=N_min,
    )

    Ni_values = diagnostics["Ni_values"]
    F_norm = diagnostics["F_norm"]
    F_scale = diagnostics["F_scale"]

    if Ni_values.size == 0 or F_norm.size == 0:
        print(f"No force/Ni diagnostic data available for dt={dt_value}")
        return

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
        show=show,
    )

    if F_scale != 0.0:
        # Add a small summary file with the force scaling information
        diagnostics["F_scale"] = F_scale

    diagnostics_path = output_dir / f"force_vs_Ni_diagnostics_dt_{dt_value:.0e}.json"
    with diagnostics_path.open("w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in diagnostics.items() if k != "F_norm" and k != "Ni_values" and k != "force_values"}, fh, indent=2)

    print(f"Saved force vs Ni diagnostic plot for dt={dt_value} to {filename}")
    print(f"Saved force vs Ni diagnostics for dt={dt_value} to {diagnostics_path}")
    print(
        f"total_points={diagnostics['total_points']}, important_points={diagnostics['important_points']}, bad_points={diagnostics['bad_points']}, bad_fraction={diagnostics['bad_fraction']:.3f}"
    )


def _find_dt_row_index(json_file: str, dt_value: float) -> int:
    rows = get_json_value(json_file, "summary_rows")
    if not isinstance(rows, list):
        raise ValueError("Expected summary_rows to be a list of dt entries.")

    for index, row in enumerate(rows):
        row_dt = row.get("dt")
        if row_dt is None:
            continue
        if np.isclose(float(row_dt), float(dt_value)):
            return index

    raise ValueError(f"Could not find dt={dt_value} in summary_rows.")


def _load_trajectory(
    json_file: str,
    row_index: int,
    base_key: str,
    coords: Sequence[str],
) -> np.ndarray:
    data = []
    for coord in coords:
        path = f"summary_rows.{row_index}.{base_key}.{coord}"
        values = get_json_value(json_file, path)
        data.append(np.asarray(values, dtype=float))

    trajectory = np.stack(data, axis=1)
    return trajectory


def _load_time_values(json_file: str, row_index: int, dt_value: float) -> np.ndarray:
    timepoints = int(get_json_value(json_file, f"summary_rows.{row_index}.deterministic_results.timepoints"))
    return np.arange(timepoints, dtype=float) * float(dt_value)


def _get_all_dts(json_file: str) -> List[float]:
    rows = get_json_value(json_file, "summary_rows")
    return [float(row["dt"]) for row in rows if "dt" in row]


def _generate_2dmot_beam_paths(line_length: float = 0.03):
    from lab_setup.laser_setup import setup_2dmot_lasers

    beams = setup_2dmot_lasers()
    beam_paths = []
    beam_labels = []
    for beam in beams:
        direction = np.asarray(beam.direction, dtype=float)
        origin = np.asarray(getattr(beam, "waist_position", (0.0, 0.0, 0.0)), dtype=float)
        beam_paths.append(
            np.stack([origin - direction * line_length, origin + direction * line_length], axis=0)
        )
        beam_labels.append(getattr(beam, "tag", "MOT beam"))

    return beam_paths, beam_labels


def plot_3d_apparatus_for_dt(
    json_file: str,
    dt_value: float,
    output_dir: Path,
    show: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_index = _find_dt_row_index(json_file, dt_value)

    deterministic = _load_trajectory(
        json_file,
        row_index,
        "deterministic_results",
        ["position_x", "position_y", "position_z"],
    )
    stochastic_mean = _load_trajectory(
        json_file,
        row_index,
        "stochastic_results",
        ["mean_x_position", "mean_y_position", "mean_z_position"],
    )

    all_points = np.vstack([deterministic, stochastic_mean]) if deterministic.size and stochastic_mean.size else (
        deterministic if deterministic.size else stochastic_mean
    )
    max_extent = float(np.max(np.abs(all_points))) if all_points.size else 0.03
    beam_length = max(0.03, max_extent * 1.2)
    beam_paths, beam_labels = _generate_2dmot_beam_paths(line_length=beam_length)

    filename = output_dir / f"apparatus_3d_dt_{dt_value:.0e}.png"
    plot_3d_paths_with_beams(
        paths=[deterministic, stochastic_mean],
        labels=["deterministic", "mean stochastic"],
        beam_paths=beam_paths,
        beam_labels=beam_labels,
        colors=["C0", "C1"],
        beam_color="C3",
        title=f"3D Apparatus for dt={dt_value} with MOT beams",
        xlabel="x",
        ylabel="y",
        zlabel="z",
        save=True,
        filename=filename,
        show=show,
    )
    print(f"Saved 3D apparatus graph for dt={dt_value} to {filename}")


def plot_distance_vs_time_for_dts(
    json_file: str,
    dt_values: Iterable[float],
    output_dir: Path,
    show: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    x_series = []
    y_series = []
    labels = []

    for dt_value in dt_values:
        row_index = _find_dt_row_index(json_file, dt_value)
        deterministic = _load_trajectory(
            json_file,
            row_index,
            "deterministic_results",
            ["position_x", "position_y", "position_z"],
        )
        stochastic_mean = _load_trajectory(
            json_file,
            row_index,
            "stochastic_results",
            ["mean_x_position", "mean_y_position", "mean_z_position"],
        )

        n = min(len(deterministic), len(stochastic_mean))
        deterministic = deterministic[:n]
        stochastic_mean = stochastic_mean[:n]
        time_values = _load_time_values(json_file, row_index, dt_value)
        time_values = time_values[:n]

        distance = np.linalg.norm(deterministic - stochastic_mean, axis=1)
        x_series.append(time_values)
        y_series.append(distance)
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
        show=show,
    )
    print(f"Saved distance vs time plot to {filename}")


def plot_ni_histogram_for_dt(
    json_file: str,
    dt_value: float,
    laser_names: Sequence[str],
    ni_value_key_template: str,
    output_dir: Path,
    show: bool = False,
    bins: Sequence[float] = DEFAULT_NI_BINS,
    bin_labels: Sequence[str] = DEFAULT_NI_LABELS,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_index = _find_dt_row_index(json_file, dt_value)

    counts = []
    # Load mean_N_channels directly from stochastic_results
    mean_n_channels = get_json_value(
        json_file, f"summary_rows.{row_index}.stochastic_results.mean_N_channels"
    )

    for laser_idx, laser in enumerate(laser_names):
        if laser_idx < len(mean_n_channels):
            values = np.asarray(mean_n_channels[laser_idx], dtype=float)
            histogram, _ = np.histogram(values, bins=bins)
            counts.append(histogram)

    if counts:
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
            show=show,
        )
        print(f"Saved Ni histogram for dt={dt_value} to {filename}")
    else:
        print(f"No laser data found for dt={dt_value}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot 3D apparatus graphs and comparison graphs from simulation JSON files."
    )
    parser.add_argument("json_file", help="The JSON file containing summary_rows entries.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for generated figures. Defaults to the JSON parent directory / figures.",
    )
    parser.add_argument(
        "--dt",
        type=float,
        action="append",
        help="One or more dt values to plot. If omitted, all dt values in JSON are used.",
    )
    parser.add_argument(
        "--laser-names",
        nargs="+",
        default=["laser1", "laser2", "laser3", "laser4"],
        help="Laser names used for Ni histogram plotting (default: laser1, laser2, laser3, laser4).",
    )
    parser.add_argument(
        "--ni-key-template",
        default="stochastic_results.laser_counts.{laser}.Ni",
        help=(
            "Template path to laser Ni values inside the summary row. "
            "Use '{laser}' as placeholder for each laser name "
            "(default: stochastic_results.laser_counts.{laser}.Ni)"
        ),
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=0.1,
        help="Threshold for dynamically important force points (default: 0.1).",
    )
    parser.add_argument(
        "--n-min",
        type=float,
        default=10.0,
        help="Minimum Ni for an important point to be considered safe (default: 10).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the plots after creating them.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_file = str(Path(args.json_file).resolve())
    
    # Extract JSON filename without extension for subdirectory
    json_filename = Path(json_file).stem
    
    base_output_dir = Path(args.output_dir) if args.output_dir else Path(json_file).resolve().parent / "figures"
    
    # Create subdirectories for each plot type
    apparatus_3d_dir = base_output_dir / json_filename / "3d_apparatus"
    distance_vs_time_dir = base_output_dir / json_filename / "distance_vs_time"
    ni_histogram_dir = base_output_dir / json_filename / "ni_histogram"
    force_vs_ni_dir = base_output_dir / json_filename / "force_vs_ni"

    dt_values = args.dt if args.dt else _get_all_dts(json_file)
    dt_values = sorted(set(float(value) for value in dt_values))

    for dt_value in dt_values:
        plot_3d_apparatus_for_dt(json_file, dt_value, apparatus_3d_dir, show=args.show)

    plot_distance_vs_time_for_dts(json_file, dt_values, distance_vs_time_dir, show=args.show)

    for dt_value in dt_values:
        plot_ni_histogram_for_dt(
            json_file,
            dt_value,
            args.laser_names,
            args.ni_key_template,
            ni_histogram_dir,
            show=args.show,
        )
        plot_force_vs_Ni_diagnostic(
            json_file,
            dt_value,
            force_vs_ni_dir,
            epsilon=args.epsilon,
            N_min=args.n_min,
            show=args.show,
        )


if __name__ == "__main__":
    main()

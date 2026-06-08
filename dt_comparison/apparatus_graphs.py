from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np

from dt_comparison.data_getter import get_json_value
from utils.plot_helpers import plot_2d_series, plot_3d_paths, plot_grouped_histogram


DEFAULT_NI_BINS = [0.0, 2.0, 5.0, 10.0, 20.0, np.inf]
DEFAULT_NI_LABELS = ["0-2", "2-5", "5-10", "10-20", "20+"]


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

    filename = output_dir / f"apparatus_3d_dt_{dt_value:.0e}.png"
    plot_3d_paths(
        paths=[deterministic, stochastic_mean],
        labels=["deterministic", "mean stochastic"],
        colors=["C0", "C1"],
        title=f"3D Apparatus for dt={dt_value}",
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
    for laser in laser_names:
        key_path = ni_value_key_template.format(laser=laser)
        values = np.asarray(
            get_json_value(json_file, f"summary_rows.{row_index}.{key_path}"),
            dtype=float,
        )
        histogram, _ = np.histogram(values, bins=bins)
        counts.append(histogram)

    filename = output_dir / f"ni_histogram_dt_{dt_value:.0e}.png"
    plot_grouped_histogram(
        categories=list(bin_labels),
        counts=counts,
        labels=list(laser_names),
        title=f"Ni histogram by laser for dt={dt_value}",
        xlabel="Ni range",
        ylabel="count",
        save=True,
        filename=filename,
        show=show,
    )
    print(f"Saved Ni histogram for dt={dt_value} to {filename}")


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
        help="Laser names used for Ni histogram plotting.",
    )
    parser.add_argument(
        "--ni-key-template",
        help=(
            "Template path to laser Ni values inside the summary row. "
            "Use '{laser}' as placeholder for each laser name, e.g. "
            "stochastic_results.laser_counts.{laser}.Ni"
        ),
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
    output_dir = Path(args.output_dir) if args.output_dir else Path(json_file).resolve().parent / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    dt_values = args.dt if args.dt else _get_all_dts(json_file)
    dt_values = sorted(set(float(value) for value in dt_values))

    for dt_value in dt_values:
        plot_3d_apparatus_for_dt(json_file, dt_value, output_dir, show=args.show)

    plot_distance_vs_time_for_dts(json_file, dt_values, output_dir, show=args.show)

    if args.laser_names and args.ni_key_template:
        for dt_value in dt_values:
            plot_ni_histogram_for_dt(
                json_file,
                dt_value,
                args.laser_names,
                args.ni_key_template,
                output_dir,
                show=args.show,
            )
    elif args.laser_names or args.ni_key_template:
        print(
            "Skipping Ni histogram plots because both --laser-names and --ni-key-template are required."
        )


if __name__ == "__main__":
    main()

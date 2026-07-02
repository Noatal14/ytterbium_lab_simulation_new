from typing import Sequence, List
import numpy as np
from utils.file_helpers import save_file_json
from utils.data_helpers import get_from_data
from dt_comparison.consts import F_scale

def _get_all_dts(data: dict) -> List[float]:
    rows = get_from_data(data, "summary_rows")
    return [float(row["dt"]) for row in rows if "dt" in row]

def _find_dt_row_index(data: dict, dt_value: float) -> int:
    rows = get_from_data(data, "summary_rows")
    if not isinstance(rows, list):
        raise ValueError("Expected summary_rows to be a list of dt entries.")

    for index, row in enumerate(rows):
        row_dt = row.get("dt")
        if row_dt is None:
            continue
        if np.isclose(float(row_dt), float(dt_value)):
            return index

    raise ValueError(f"Could not find dt={dt_value} in summary_rows.")

def _flatten_channel_data(channel_list):
    if not channel_list:
        return np.array([], dtype=float)
    flattened = np.concatenate([np.asarray(channel, dtype=float).ravel() for channel in channel_list])
    return flattened

def _load_trajectory(
    data: dict,
    row_index: int,
    base_key: str,
    coords: Sequence[str],
) -> np.ndarray:
    _data_ = []
    for coord in coords:
        path = f"summary_rows.{row_index}.{base_key}.{coord}"
        values = get_from_data(data, path)
        _data_.append(np.asarray(values, dtype=float))

    trajectory = np.stack(_data_, axis=1)
    return trajectory

def _flatten_channel_data(channel_list):
    if not channel_list:
        return np.array([], dtype=float)
    flattened = np.concatenate([np.asarray(channel, dtype=float).ravel() for channel in channel_list])
    return flattened

def _load_deterministic_time_values(data: dict, row_index: int, dt_value: float) -> np.ndarray:
    timepoints = int(get_from_data(data, f"summary_rows.{row_index}.deterministic_results.timepoints"))
    return np.arange(timepoints, dtype=float) * float(dt_value)

def get_data_for_dt(data: dict, dt_value: float):
    row_index = _find_dt_row_index(data, dt_value)
    
    mean_N_channels = get_from_data(
        data, f"summary_rows.{row_index}.stochastic_results.mean_N_channels", default=[]
    )
    
    mean_force_channels = get_from_data(
        data, f"summary_rows.{row_index}.stochastic_results.mean_force_channels", default=[]
    )

    Ni_values = _flatten_channel_data(mean_N_channels)

    force_values = _flatten_channel_data(mean_force_channels)
    
    deterministic_trajectory = _load_trajectory(
        data,
        row_index,
        "deterministic_results",
        ["position_x", "position_y", "position_z"],
    )
    
    stochastic_mean_trajectory = _load_trajectory(
        data,
        row_index,
        "stochastic_results",
        ["mean_x_position", "mean_y_position", "mean_z_position"],
	)

    n = min(len(deterministic_trajectory), len(stochastic_mean_trajectory))
    deterministic_trajectory = deterministic_trajectory[:n]
    stochastic_mean_trajectory = stochastic_mean_trajectory[:n]
    time_values = _load_deterministic_time_values(data, row_index, dt_value)[:n]

    distance = np.linalg.norm(deterministic_trajectory - stochastic_mean_trajectory, axis=1)

    return {
        "time_values": time_values,
        "deterministic_trajectory": deterministic_trajectory,
        "stochastic_mean_trajectory": stochastic_mean_trajectory,
        "Ni_values": Ni_values,
        "force_values": force_values,
        "mean_N_channels": mean_N_channels,
        "mean_force_channels": mean_force_channels,
        "distance": distance,
    }

def compute_force_Ni_bad_fraction(
    Ni_values: Sequence,
    force_values: Sequence,
    epsilon: float = 0.1,
    N_min: float = 10.0,
    dt_value = None,
    output_dir = None,
) -> dict:
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

    diagnostics = {
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

    diagnostics_path = output_dir / f"force_vs_Ni_diagnostics_dt_{dt_value:.0e}.json"

    save_file_json(diagnostics_path, {k: v for k, v in diagnostics.items() if k != "F_norm" and k != "Ni_values" and k != "force_values"})

    print(f"Saved force vs Ni diagnostics for dt={dt_value} to {diagnostics_path}")
    print(
        f"total_points={diagnostics['total_points']}, important_points={diagnostics['important_points']}, bad_points={diagnostics['bad_points']}, bad_fraction={diagnostics['bad_fraction']:.3f}"
    )

    return diagnostics
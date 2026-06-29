from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence, Tuple

from utils.data_helpers import get_from_data
from utils.file_helpers import read_data_json, save_file_json


F_SCALE_FILE_PATTERN = re.compile(r"^force_vs_Ni_diagnostics_dt_(.+)\.json$")


def _extract_dt_from_filename(filename: str) -> str | None:
    match = F_SCALE_FILE_PATTERN.match(filename)
    if match:
        return match.group(1)
    return None


def collect_F_scale_from_diagnostics(
    initial_conditions: Sequence[Tuple[float, float]],
    base_dir: str | Path = "dt_comparison/data/N_min_10_epsilon_0.1",
    output_json: str | Path | None = "dt_comparison/data/F_scale_summary.json",
) -> dict:
    """Collect F_scale values from force_vs_ni diagnostics JSON files.

    Parameters
    ----------
    initial_conditions : Sequence[Tuple[float, float]]
        List of (v, r) tuples that identify summary folders.
    base_dir : str | Path, optional
        Base data directory containing the summary folders.
    output_json : str | Path, optional
        Path to the output JSON file. Defaults to
        <base_dir>/F_scale_summary.json.

    Returns
    -------
    dict
        Collected F_scale values organized by summary folder and dt.
    """
    base_path = Path(base_dir)
    if output_json is None:
        output_path = base_path / "F_scale_summary.json"
    else:
        output_path = Path(output_json)

    collected = {}

    for v, r in initial_conditions:
        summary_name = f"summary_v{v}r{r}"
        diagnostics_dir = base_path / summary_name / "force_vs_ni"
        if not diagnostics_dir.exists():
            print(f"Warning: condition folder does not exist, skipping: {diagnostics_dir}")
            continue
        if not diagnostics_dir.is_dir():
            print(f"Warning: expected directory but found file, skipping: {diagnostics_dir}")
            continue

        diagnostics_files = sorted(diagnostics_dir.glob("force_vs_Ni_diagnostics_dt_*.json"))
        if not diagnostics_files:
            print(f"Warning: no diagnostics files found for {summary_name} in {diagnostics_dir}")
            continue

        summary_results: dict[str, dict[str, float]] = {}
        for diagnostics_file in diagnostics_files:
            dt_key = _extract_dt_from_filename(diagnostics_file.name)
            if dt_key is None:
                print(f"Warning: ignored unexpected diagnostics filename: {diagnostics_file.name}")
                continue

            data = read_data_json(diagnostics_file)
            f_scale = get_from_data(data, "F_scale", default=None)
            if f_scale is None:
                print(f"Warning: missing F_scale in diagnostics file, skipping: {diagnostics_file}")
                continue

            try:
                summary_results[dt_key] = {"F_scale": float(f_scale)}
            except (TypeError, ValueError):
                print(f"Warning: invalid F_scale value in {diagnostics_file}, skipping")

        if not summary_results:
            print(f"Warning: no valid F_scale entries found for {summary_name}")
            continue

        collected[summary_name] = summary_results

    if collected:
        save_file_json(output_path, collected)
    else:
        print(f"Warning: no F_scale diagnostics were collected. No output file was written.")

    return collected

if __name__ == "__main__":
    initial_conditions = [
        ("15", "002"),
        ("35", "002"),
        ("50", "002"),
    ]
    base_dir = "dt_comparison/data/N_min_10_epsilon_0.1"
    output_json = "dt_comparison/data/F_scale_summary.json"

    collect_F_scale_from_diagnostics(initial_conditions, base_dir, output_json)
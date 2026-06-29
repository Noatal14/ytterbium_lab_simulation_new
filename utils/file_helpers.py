import csv
import json
from pathlib import Path
import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from typing import Any

def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

"""
=====
CSV
=====
"""

def save_file_csv(filename, data):
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)

    print(f"CSV summary saved to: {filename}")

def _parse_csv_value(value):
    if value is None:
        return np.nan
    value = str(value).strip()
    if value == "":
        return np.nan
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value
        
def read_data_csv(filename, delimiter=","):
    """Read a CSV file and return column arrays.

    Parameters
    ----------
    filename : str
        Path to the CSV file.
    delimiter : str, optional
        Field delimiter used in the CSV file.

    Returns
    -------
    dict
        Dictionary mapping column names to NumPy arrays.
    """
    with open(filename, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        columns = {name: [] for name in fieldnames}
        for row in reader:
            for name in fieldnames:
                columns[name].append(_parse_csv_value(row.get(name)))

    arrays = {}
    for name, values in columns.items():
        if all(not isinstance(v, str) for v in values):
            arrays[name] = np.asarray(values, dtype=float)
        else:
            arrays[name] = np.asarray(values, dtype=object)

    return arrays

"""
=====
JSON
=====
"""

def save_file_json(filename, data):
    filepath = Path(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)

    print(f"JSON summary saved to: {filepath}")


def read_data_json(json_file):
	with open(json_file,"r", encoding="utf-8") as fh:
		return json.load(fh)

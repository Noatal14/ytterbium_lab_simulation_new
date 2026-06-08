from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Union


def get_json_value(json_file: Union[str, Path], key: str, default: Any = ... ) -> Any:
	"""Load a JSON file and return the value at a dot-separated key path.

	Args:
		json_file: Path to the JSON file. If no suffix is provided, ".json" is appended.
		key: Dot-separated path into the JSON structure, e.g. "parent.child.0.name".
			 If empty string, the whole JSON object is returned.
		default: If provided (not the sentinel), return this when a key is missing.

	Returns:
		The value found at the path.

	Raises:
		FileNotFoundError: If the JSON file cannot be found.
		KeyError: If a path segment cannot be resolved and `default` is not provided.
	"""
	path = Path(json_file)
	if path.suffix == "":
		path = path.with_suffix(".json")

	if not path.exists():
		raise FileNotFoundError(f"JSON file not found: {path}")

	with path.open("r", encoding="utf-8") as fh:
		data = json.load(fh)

	if key is None or key == "":
		return data

	cur: Any = data
	for part in key.split("."):
		# If current value is a list, allow numeric indices
		if isinstance(cur, list):
			try:
				idx = int(part)
			except ValueError:
				if default is not ...:
					return default
				raise KeyError(f"Expected list index but got '{part}' while resolving '{key}'")
			try:
				cur = cur[idx]
			except IndexError:
				if default is not ...:
					return default
				raise KeyError(f"List index out of range: {idx} while resolving '{key}'")
			continue

		# If current value is a dict, lookup by key
		if isinstance(cur, dict):
			if part in cur:
				cur = cur[part]
				continue
			if default is not ...:
				return default
			raise KeyError(f"Key '{part}' not found while resolving '{key}'")

		# Otherwise cannot traverse further
		if default is not ...:
			return default
		raise KeyError(f"Cannot traverse into non-container value at '{part}' while resolving '{key}'")

	return cur


__all__ = ["get_json_value"]


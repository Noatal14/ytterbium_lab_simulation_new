from typing import Any, Sequence
import numpy as np

def get_from_data(data: dict, key: str, default: Any = ... ) -> Any:
	"""
	Return the value from a nested dictionary or list structure given a dot-separated key.
	"""
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

def make_histogram_counts(names: Sequence[str], vals: Sequence[float], bins: Sequence[float]) -> Sequence[np.ndarray]:
    counts = []

    for index, name in enumerate(names):
        if index < len(vals):
            values = np.asarray(vals[index], dtype=float)
            histogram, _ = np.histogram(values, bins=bins)
            counts.append(histogram)
    
    return counts
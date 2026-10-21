"""Narrow read verification of cross-platform paired Student intervals.

Producer bytes are never normalized.  This is not a tolerance for means,
observations, prediction/bootstrap statistics, or scientific decision changes.
"""
from __future__ import annotations

import copy
import math
from typing import Any

_CI = "95_ci_fraction"
_HALF = "95_ci_half_width_fraction"


def typed_exact(left: Any, right: Any) -> bool:
    """JSON equality without bool/int aliases or floating representation changes."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            typed_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(map(lambda pair: typed_exact(*pair), zip(left, right)))
    if isinstance(left, float):
        return math.isfinite(left) and math.isfinite(right) and left.hex() == right.hex()
    return left == right


def _float(value: Any) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("Sensitivity interval contains an invalid float.")
    return value


def _comparison(observed: dict[str, Any], expected: dict[str, Any]) -> tuple[float, float, bool]:
    # Exact non-CI equality is checked by the caller before this function.
    mean = _float(expected["mean_difference_fraction"])
    halves = [_float(item[_HALF]) for item in (observed, expected)]
    budget = 0.0 if mean == 0.0 and halves == [0.0, 0.0] else 4 * max(
        math.ulp(mean), *(math.ulp(half) for half in halves)
    )
    if budget == 0.0 and (
        not typed_exact(observed[_HALF], expected[_HALF])
        or not typed_exact(observed[_CI], expected[_CI])
    ):
        raise ValueError("Zero-scale sensitivity intervals must match exactly.")
    if not math.isfinite(budget) or min(halves) < 0:
        raise ValueError("Sensitivity interval has an invalid scale.")
    lows = []
    for item, half in zip((observed, expected), halves):
        interval = item[_CI]
        if type(interval) is not list or len(interval) != 2:
            raise ValueError("Sensitivity interval has an invalid shape.")
        low, high = map(_float, interval)
        if not typed_exact(low, mean - half) or not typed_exact(high, mean + half):
            raise ValueError("Sensitivity interval is internally inconsistent.")
        lows.append(low)
    if any(abs(_float(observed[key]) - _float(expected[key])) > budget for key in (_HALF,)) or any(
        abs(observed[_CI][index] - expected[_CI][index]) > budget for index in (0, 1)
    ):
        raise ValueError("Sensitivity interval exceeds the portability bound.")
    differences = expected["differences_fraction"]
    zero = (
        budget == 0.0 and mean == 0.0 and halves == [0.0, 0.0]
        and all(type(value) is float and value == 0.0 for value in differences)
        and all(value == 0.0 for item in (observed, expected) for value in item[_CI])
    )
    return min(lows) - budget, max(lows) + budget, zero


def verify_sensitivity_summary(observed: Any, expected: Any, *, target_loss_fraction: float) -> None:
    """Accept exact evidence or prove only CI rounding differs without decisions.

    The caller retains all existing evidence/hash checks and the original object.
    Exact historical evidence keeps the original acceptance path.  For differing
    CI evidence, every point and selection must pass the conservative proof.
    """
    if typed_exact(observed, expected):
        return
    if type(observed) is not dict or type(expected) is not dict or observed.keys() != expected.keys():
        raise ValueError("Sensitivity summary schema differs.")
    if type(target_loss_fraction) is not float or not math.isfinite(target_loss_fraction) or target_loss_fraction < 0:
        raise ValueError("Invalid frozen sensitivity loss threshold.")
    stripped = copy.deepcopy(observed)
    canonical = copy.deepcopy(expected)
    try:
        for key in canonical:
            for group in (stripped[key], canonical[key]):
                for comparison in [point["comparison_to_reference"] for point in group["points"]] + [
                    group["production_selection"]["comparison_to_confirmed_winner"]
                ]:
                    comparison.pop(_CI, None)
                    comparison.pop(_HALF, None)
    except (KeyError, TypeError) as exc:
        raise ValueError("Sensitivity summary schema differs.") from exc
    if not typed_exact(stripped, canonical):
        raise ValueError("Non-CI sensitivity evidence differs.")
    try:
        for key, group in expected.items():
            actual = observed[key]
            envelopes = []
            better = []
            for index, (point, original) in enumerate(zip(group["points"], actual["points"])):
                low, high, zero = _comparison(original["comparison_to_reference"], point["comparison_to_reference"])
                canonical_low = point["comparison_to_reference"][_CI][0]
                original_low = original["comparison_to_reference"][_CI][0]
                for threshold, inclusive in ((0.0, False), (-target_loss_fraction, True)):
                    decision = (lambda value: value >= threshold) if inclusive else (lambda value: value > threshold)
                    if decision(canonical_low) != decision(original_low) or (not zero and low <= threshold <= high):
                        raise ValueError("Sensitivity decision is numerically ambiguous.")
                if original["within_loss_margin_at_95_percent"] is not (original_low >= -target_loss_fraction):
                    raise ValueError("Sensitivity loss decision is inconsistent.")
                envelopes.append((low, high))
                if canonical_low > 0.0:
                    better.append(index)
            selection = group["production_selection"]
            _comparison(actual["production_selection"]["comparison_to_confirmed_winner"], selection["comparison_to_confirmed_winner"])
            if better:
                winner = max(better, key=lambda index: (
                    group["points"][index]["comparison_to_reference"][_CI][0],
                    group["points"][index]["mean_efficiency"],
                ))
                if any(envelopes[winner][0] <= envelopes[index][1] for index in better if index != winner):
                    raise ValueError("Sensitivity ranking is numerically ambiguous.")
                reason = "sensitivity_neighbor_clearly_better_at_95_percent"
            else:
                winner = next(index for index, point in enumerate(group["points"]) if point["offsets"] == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0})
                reason = "no_sensitivity_neighbor_clearly_better_at_95_percent"
            chosen = group["points"][winner]
            if not typed_exact(actual["production_selection"]["comparison_to_confirmed_winner"], actual["points"][winner]["comparison_to_reference"]):
                raise ValueError("Observed sensitivity selection is inconsistent.")
            if not typed_exact(selection["parameters"], chosen["parameters"]) or not typed_exact(selection["comparison_to_confirmed_winner"], chosen["comparison_to_reference"]) or selection["selection_reason"] != reason:
                raise ValueError("Sensitivity selection is inconsistent.")
    except (KeyError, TypeError, StopIteration) as exc:
        raise ValueError("Sensitivity summary schema differs.") from exc

"""Pure canonical individual-result metrics shared by publication and inspection."""
from __future__ import annotations

import math
from typing import Any, Mapping
from workflow_api.run_records import RunRecordError


def _same_json_identity(actual, expected):
    """Compare canonical JSON identities without bool/integer/float aliases."""
    if isinstance(expected, Mapping):
        return (isinstance(actual, Mapping) and set(actual) == set(expected)
                and all(_same_json_identity(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, (list, tuple)):
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expected)
                and all(_same_json_identity(left, right) for left, right in zip(actual, expected)))
    return type(actual) is type(expected) and actual == expected


def mot_2d_result_provenance(
    run: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the exact provenance object required for individual 2D results."""
    resolved = configuration["resolved"]
    sampling = resolved["sampling"]
    source = resolved["input_source"]
    controls = resolved["mot_2d"]
    return {
        "git_revision": run["git_revision"],
        "configuration_sha256": run["configuration_sha256"],
        "inputs_sha256": run["inputs_sha256"],
        "laboratory_spec_sha256": configuration["laboratory_spec"]["sha256"],
        "numerical_policy_sha256": configuration["numerical_policy"]["sha256"],
        "admission_specification_sha256": resolved["admission_specification"]["sha256"],
        "source_id": source["id"],
        "source_fingerprint": source["fingerprint"],
        "selection_algorithm": sampling["algorithm"],
        "selection_version": sampling["version"],
        "selection_seed": sampling["selection_seed"],
        "mot_seed": resolved["simulation"]["mot_seed"],
        "s0": controls["laser"]["s0"],
        "detuning_gamma": controls["laser"]["detuning_gamma"],
        "magnet_radius_m": controls["magnet_radius_m"],
        "solver": resolved["numerical_policy"]["solver"],
        "timestep_s": resolved["numerical_policy"]["dt_s"],
        "capture_criterion_version": controls["capture_criterion_version"],
    }


def mot_3d_result_provenance(
    run: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the exact provenance object required for individual 3D results."""
    resolved = configuration["resolved"]
    return {
        "git_revision": run["git_revision"],
        "configuration_sha256": run["configuration_sha256"],
        "inputs_sha256": run["inputs_sha256"],
        "laboratory_spec_sha256": configuration["laboratory_spec"]["sha256"],
        "numerical_policy_sha256": configuration["numerical_policy"]["sha256"],
        "admission_specification_sha256": resolved["admission_specification"]["sha256"],
        "source_id": resolved["input_source"]["id"],
        "source_fingerprint": resolved["input_source"]["fingerprint"],
        "selection_algorithm": resolved["sampling"]["algorithm"],
        "selection_version": resolved["sampling"]["version"],
        "selection_seed": resolved["sampling"]["selection_seed"],
        "simulation_seed": resolved["simulation"]["simulation_seed"],
        "geometry_family": resolved["mot_3d"]["geometry_family"],
        "solver": resolved["numerical_policy"]["solver"],
        "timestep_s": resolved["numerical_policy"]["dt_s"],
        "t_max_s": resolved["numerical_policy"]["t_max_s"],
        "convergence_claim": resolved["numerical_policy"]["convergence_claim"],
    }


def validate_family_metrics(
    family: str,
    run: Mapping[str, Any],
    results: Mapping[str, Any],
    configuration: Mapping[str, Any] | None = None,
) -> None:
    """Enforce the same family relationships at publication and canonical reads."""
    if family == "mot_3d":
        if configuration is None:
            raise RunRecordError("3D-MOT result validation requires configuration evidence.")
        metrics = results["metrics"]
        expected = {
            "n_input", "usable_at_end_count", "usable_at_end_fraction",
            "residence_qualified_captured_count",
            "residence_qualified_captured_fraction", "elapsed_s",
            "selection_sha256", "provenance",
        }
        resolved = configuration["resolved"]
        n_input = metrics.get("n_input")
        usable = metrics.get("usable_at_end_count")
        captured = metrics.get("residence_qualified_captured_count")
        elapsed = metrics.get("elapsed_s")
        if (
            set(metrics) != expected
            or isinstance(n_input, bool) or not isinstance(n_input, int)
            or n_input != run["particle_count"]
            or n_input != resolved["sampling"]["selected_count"]
            or isinstance(usable, bool) or not isinstance(usable, int)
            or isinstance(captured, bool) or not isinstance(captured, int)
            or not 0 <= captured <= usable <= n_input
            or isinstance(metrics.get("usable_at_end_fraction"), bool)
            or not isinstance(metrics.get("usable_at_end_fraction"), (int, float))
            or not math.isfinite(float(metrics["usable_at_end_fraction"]))
            or metrics.get("usable_at_end_fraction") != usable / n_input
            or isinstance(metrics.get("residence_qualified_captured_fraction"), bool)
            or not isinstance(metrics.get("residence_qualified_captured_fraction"), (int, float))
            or not math.isfinite(float(metrics["residence_qualified_captured_fraction"]))
            or metrics.get("residence_qualified_captured_fraction") != captured / n_input
            or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed)) or elapsed < 0
            or metrics.get("selection_sha256") != resolved["sampling"]["selected_identities_sha256"]
            or not _same_json_identity(metrics.get("provenance"), mot_3d_result_provenance(run, configuration))
        ):
            raise RunRecordError("3D-MOT result metrics are scientifically inconsistent.")
        return
    if family == "mot_2d":
        if configuration is None:
            raise RunRecordError("2D-MOT result validation requires configuration evidence.")
        metrics = results["metrics"]
        expected = {
            "n_input", "n_survivors", "conditional_efficiency", "elapsed_s",
            "selection_sha256", "provenance",
        }
        resolved = configuration["resolved"]
        sampling = resolved["sampling"]
        expected_provenance = mot_2d_result_provenance(run, configuration)
        n_input = metrics.get("n_input")
        n_survivors = metrics.get("n_survivors")
        efficiency = metrics.get("conditional_efficiency")
        elapsed = metrics.get("elapsed_s")
        if (
            set(metrics) != expected
            or isinstance(n_input, bool)
            or not isinstance(n_input, int)
            or n_input != run["particle_count"]
            or n_input != sampling["selected_count"]
            or isinstance(n_survivors, bool)
            or not isinstance(n_survivors, int)
            or not 0 <= n_survivors <= n_input
            or isinstance(efficiency, bool)
            or not isinstance(efficiency, (int, float))
            or not math.isfinite(float(efficiency))
            or float(efficiency) != n_survivors / n_input
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or elapsed < 0
            or metrics.get("selection_sha256")
            != sampling["selected_identities_sha256"]
            or not _same_json_identity(metrics.get("provenance"), expected_provenance)
        ):
            raise RunRecordError("2D-MOT result metrics are scientifically inconsistent.")
        return
    if family != "zeeman":
        return
    if configuration is None:
        raise RunRecordError("Zeeman result validation requires configuration evidence.")
    simulation = configuration["resolved"].get("simulation")
    configured_count = simulation.get("particle_count") if isinstance(simulation, Mapping) else None
    metrics = results["metrics"]
    expected = {
        "n_initial",
        "n_survivors",
        "captured",
        "survival_fraction",
        "elapsed_s",
    }
    if set(metrics) != expected:
        raise RunRecordError("Zeeman result metrics are incomplete or unexpected.")
    n_initial = metrics["n_initial"]
    n_survivors = metrics["n_survivors"]
    captured = metrics["captured"]
    elapsed = metrics["elapsed_s"]
    fraction = metrics["survival_fraction"]
    if (
        isinstance(n_initial, bool)
        or not isinstance(n_initial, int)
        or n_initial != run["particle_count"]
        or type(configured_count) is not int
        or n_initial != configured_count
        or isinstance(n_survivors, bool)
        or not isinstance(n_survivors, int)
        or not 0 <= n_survivors <= n_initial
        or isinstance(captured, bool)
        or not isinstance(captured, int)
        or captured != n_survivors
        or isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(float(fraction))
        or float(fraction) != n_survivors / n_initial
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise RunRecordError("Zeeman result metrics are scientifically inconsistent.")



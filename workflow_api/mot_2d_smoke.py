"""Strict validation of canonical 2D-MOT smoke outputs.

The smoke stage is an execution-integrity check, not a performance gate.  A
valid run may capture zero atoms; provenance and internal consistency are what
this module establishes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from workflow_api.safe_json import read_json

MAX_DATABASE_BYTES = 64 * 1024 * 1024
DEFAULT_SAMPLER_SEED = 42


class SmokeValidationError(ValueError):
    """A smoke artifact is missing, unsafe, or scientifically inconsistent."""


def smoke_key(value: float) -> str:
    return f"s0_{float(value):.6f}".replace(".", "p")


def _finite(value: Any) -> float:
    if isinstance(value, bool):
        raise SmokeValidationError("Smoke output contains a non-numeric value.")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise SmokeValidationError("Smoke output contains a non-numeric value.") from error
    if not math.isfinite(result):
        raise SmokeValidationError("Smoke output contains a non-finite value.")
    return result


def _exact_number(observed: Any, expected: float, label: str) -> None:
    if _finite(observed) != float(expected):
        raise SmokeValidationError(f"Smoke {label} does not match the frozen campaign.")


def _regular_bounded(path: Path, maximum: int) -> os.stat_result:
    try:
        row = path.lstat()
    except OSError as error:
        raise SmokeValidationError(f"Required smoke artifact is missing: {path.name}.") from error
    if not stat.S_ISREG(row.st_mode) or path.is_symlink() or row.st_size <= 0 or row.st_size > maximum:
        raise SmokeValidationError(f"Smoke artifact is not a bounded regular file: {path.name}.")
    return row


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_finite_numeric_leaves(value: Any, label: str) -> None:
    """Reject JSON NaN/Infinity anywhere in a scientific result structure."""
    if isinstance(value, dict):
        for child in value.values():
            _require_finite_numeric_leaves(child, label)
    elif isinstance(value, list):
        for child in value:
            _require_finite_numeric_leaves(child, label)
    elif isinstance(value, float) and not math.isfinite(value):
        raise SmokeValidationError(f"Smoke {label} contains a non-finite value.")


def _expected_design(manifest: dict[str, Any], s0: float) -> dict[str, Any]:
    fixed = manifest["fixed_design"]
    return {
        "fixed_s0": float(s0),
        "dt_s": float(fixed["working_dt_s"]),
        "solver": str(fixed["solver"]),
        "ensemble_dir": manifest["ensemble_source"]["directory"],
        "zeeman_seeds": [manifest["seed_roles"]["discovery"][0]],
        "mot_seeds": [manifest["mot_seeds"]["discovery"][0]],
        "particles_per_ensemble": 2,
        "sampler_seed": DEFAULT_SAMPLER_SEED,
        "bounds": {
            "s0": [float(s0), float(s0)],
            "detuning_gamma": list(fixed["detuning_bounds_gamma"]),
            "magnet_radius_m": list(fixed["magnet_radius_bounds_m"]),
        },
        "git_commit": manifest["provenance"]["git_commit"],
        "campaign_design_id": manifest["provenance"]["physical_model_sha256"],
    }


def _validate_sqlite(path: Path, expected_design: dict[str, Any]) -> None:
    _regular_bounded(path, MAX_DATABASE_BYTES)
    # mode=ro and immutable=1 prevent journals or sidecar files from being
    # created while inspecting an untrusted runtime artifact.
    uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        complete = connection.execute("SELECT COUNT(*) FROM trials WHERE state='COMPLETE'").fetchone()
        total = connection.execute("SELECT COUNT(*) FROM trials").fetchone()
        attrs = dict(connection.execute(
            "SELECT key, value_json FROM study_user_attributes WHERE key IN ('scientific_design','design_id')"
        ))
    except (sqlite3.Error, OSError, ValueError) as error:
        raise SmokeValidationError("Smoke Optuna database is invalid.") from error
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    design_id = hashlib.sha256(json.dumps(expected_design, sort_keys=True).encode()).hexdigest()
    try:
        recorded_design = json.loads(attrs["scientific_design"])
        recorded_id = json.loads(attrs["design_id"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SmokeValidationError("Smoke Optuna database lacks frozen design metadata.") from error
    if integrity != ("ok",) or complete != (1,) or total != (1,):
        raise SmokeValidationError("Smoke Optuna database does not contain exactly one complete trial.")
    if recorded_design != expected_design or recorded_id != design_id:
        raise SmokeValidationError("Smoke Optuna database design differs from the frozen campaign.")


def validate_smoke_outputs(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate every frozen s0 smoke output and return a compact report."""
    if manifest.get("kind") != "mot_2d_s0_campaign" or manifest.get("stage") != "smoke":
        raise SmokeValidationError("Campaign is not awaiting canonical smoke validation.")
    s0_values = manifest.get("s0_values")
    if not isinstance(s0_values, list) or not s0_values:
        raise SmokeValidationError("Campaign has no frozen s0 values.")
    reports: list[dict[str, Any]] = []
    for raw_s0 in s0_values:
        s0 = _finite(raw_s0)
        directory = root / "smoke" / smoke_key(s0)
        summary_path = directory / "summary.json"
        trial_path = directory / "trials" / "trial_0000.json"
        database_path = directory / "joint_screening.db"
        try:
            summary = read_json(summary_path)
            trial = read_json(trial_path)
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
            raise SmokeValidationError("Smoke JSON output is missing or invalid.") from error
        expected = _expected_design(manifest, s0)
        if not isinstance(summary, dict) or summary.get("kind") != "mot_2d_joint_optimization_summary":
            raise SmokeValidationError("Smoke summary kind is invalid.")
        _require_finite_numeric_leaves(summary, "summary")
        if summary.get("n_registered_trials") != 1 or summary.get("n_finished_trials") != 1:
            raise SmokeValidationError("Smoke summary must contain exactly one finished trial.")
        if summary.get("objectives") != ["maximize_mean_conditional_efficiency"] or summary.get("pareto_front") != []:
            raise SmokeValidationError("Smoke summary objectives are invalid.")
        _exact_number(summary.get("fixed_s0"), s0, "fixed s0")
        ranked = summary.get("ranked_trials")
        if not isinstance(ranked, list) or len(ranked) != 1 or ranked[0].get("trial_number") != 0:
            raise SmokeValidationError("Smoke summary ranking is invalid.")
        design = summary.get("design")
        if not isinstance(design, dict):
            raise SmokeValidationError("Smoke summary design is invalid.")
        expected_summary = {
            "dt_s": expected["dt_s"], "n_ensembles": 1, "particles_per_ensemble": 2,
            "mot_seed_start": 4000, "stochastic_solver": expected["solver"],
            "ensemble_dir": expected["ensemble_dir"], "zeeman_seeds": expected["zeeman_seeds"],
            "sampler_seed": expected["sampler_seed"], "bounds": expected["bounds"],
        }
        if design != expected_summary:
            raise SmokeValidationError("Smoke summary design differs from the frozen campaign.")
        if not isinstance(trial, dict) or trial.get("kind") != "mot_2d_joint_optimization_trial" or trial.get("trial_number") != 0:
            raise SmokeValidationError("Smoke trial record is invalid.")
        _require_finite_numeric_leaves(trial, "trial")
        parameters = trial.get("parameters")
        if not isinstance(parameters, dict) or set(parameters) != {"s0", "detuning_gamma", "magnet_radius"}:
            raise SmokeValidationError("Smoke trial parameters are invalid.")
        _exact_number(parameters["s0"], s0, "trial s0")
        detuning = _finite(parameters["detuning_gamma"]); radius = _finite(parameters["magnet_radius"])
        if not expected["bounds"]["detuning_gamma"][0] <= detuning <= expected["bounds"]["detuning_gamma"][1] or not expected["bounds"]["magnet_radius_m"][0] <= radius <= expected["bounds"]["magnet_radius_m"][1]:
            raise SmokeValidationError("Smoke trial parameters lie outside frozen bounds.")
        trial_design = trial.get("design")
        expected_id = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
        expected_trial_design = {
            "dt_s": expected["dt_s"], "n_ensembles": 1, "particles_per_ensemble": 2,
            "mot_seed_start": 4000, "stochastic_solver": expected["solver"],
            "design_id": expected_id, "git_commit": expected["git_commit"],
            "ensemble_dir": expected["ensemble_dir"], "zeeman_seeds": expected["zeeman_seeds"],
            "mot_seeds": expected["mot_seeds"],
        }
        if trial_design != expected_trial_design:
            raise SmokeValidationError("Smoke trial provenance differs from the frozen campaign.")
        replicates = trial.get("replicates")
        if not isinstance(replicates, list) or len(replicates) != 1:
            raise SmokeValidationError("Smoke trial must contain exactly one replicate.")
        replicate = replicates[0]
        if not isinstance(replicate, dict) or replicate.get("zeeman_seed") != expected["zeeman_seeds"][0] or replicate.get("mot_seed") != expected["mot_seeds"][0] or replicate.get("n_input") != 2:
            raise SmokeValidationError("Smoke replicate provenance is invalid.")
        captured = replicate.get("captured")
        if not isinstance(captured, int) or isinstance(captured, bool) or not 0 <= captured <= 2:
            raise SmokeValidationError("Smoke captured count is invalid.")
        efficiency = _finite(replicate.get("conditional_efficiency"))
        ranked_efficiency = _finite(ranked[0].get("mean_conditional_efficiency"))
        if efficiency != captured / 2 or ranked_efficiency != efficiency:
            raise SmokeValidationError("Smoke efficiency is internally inconsistent.")
        statistics = trial.get("statistics")
        if not isinstance(statistics, dict):
            raise SmokeValidationError("Smoke trial statistics are invalid.")
        statistics_mean = _finite(statistics.get("mean_conditional_efficiency"))
        if statistics_mean != efficiency:
            raise SmokeValidationError("Smoke statistics differ from the replicate result.")
        if "n_replicates" in statistics and statistics["n_replicates"] != 1:
            raise SmokeValidationError("Smoke statistics must describe exactly one replicate.")
        for field in ("conditional_95_ci", "estimated_total_95_ci"):
            if field in statistics and statistics[field] != [None, None]:
                raise SmokeValidationError("A one-replicate smoke run cannot have a confidence interval.")
        for field in ("conditional_95_ci_half_width", "estimated_total_95_ci_half_width"):
            if field in statistics and statistics[field] is not None:
                raise SmokeValidationError("A one-replicate smoke run cannot have an interval half-width.")
        if ranked[0].get("parameters") != parameters:
            raise SmokeValidationError("Smoke ranked parameters differ from the trial record.")
        _validate_sqlite(database_path, expected)
        reports.append({
            "s0": s0, "captured": captured, "input": 2, "efficiency": efficiency,
            "artifacts": {
                "summary_sha256": _digest(summary_path), "trial_sha256": _digest(trial_path),
                "database_sha256": _digest(database_path),
            },
        })
    return reports

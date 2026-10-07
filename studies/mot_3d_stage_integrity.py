"""Integrity helpers shared by post-discovery 3D-MOT selection stages."""

import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_stage_design(
    manifest_path, selection_path, role, dt_s, t_max_s, *, particle_selection,
    particles_per_ensemble=None, selection_seed=None,
):
    manifest_path = Path(manifest_path)
    selection_path = Path(selection_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("input_roles", {}).get(role)
    if not records:
        raise ValueError(f"Missing frozen role {role!r}.")
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"))
    selection_canonical = json.dumps(
        particle_selection, sort_keys=True, separators=(",", ":")
    )
    return {
        "campaign_manifest_path": str(manifest_path.resolve()),
        "campaign_manifest_sha256": sha256(manifest_path),
        "selection_path": str(selection_path.resolve()),
        "selection_sha256": sha256(selection_path),
        "git_commit": manifest["provenance"]["git_commit"],
        "physical_model_sha256": manifest["provenance"]["physical_model_sha256"],
        "input_role": role,
        "input_role_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "dt_s": float(dt_s),
        "t_max_s": float(t_max_s),
        "solver": manifest["design"]["solver"],
        "particles_per_ensemble": particles_per_ensemble,
        "selection_seed": selection_seed,
        "particle_selection_sha256": hashlib.sha256(
            selection_canonical.encode()
        ).hexdigest(),
    }


def validate_completed_result(
    json_path,
    npz_path,
    *,
    kind,
    family,
    candidate_id,
    recoil_seed,
    design,
):
    json_path, npz_path = Path(json_path), Path(npz_path)
    if json_path.exists() != npz_path.exists():
        raise ValueError(f"Partial result pair: {json_path}, {npz_path}")
    if not json_path.is_file():
        return False
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    expected = {
        "kind": kind,
        "family": family,
        "candidate_id": candidate_id,
        "recoil_seed": int(recoil_seed),
        "design": design,
        "outcomes_sha256": sha256(npz_path),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"Stale or contaminated result {json_path}: {key} mismatch.")
    with np.load(npz_path) as data:
        required = {"usable_at_end", "usable_ever", "ensemble_ids"}
        if not required.issubset(data.files):
            raise ValueError(f"Incomplete outcome archive: {npz_path}")
        lengths = {len(np.asarray(data[key])) for key in required}
        if lengths != {int(payload["input_particle_count"])}:
            raise ValueError(f"Outcome length mismatch: {npz_path}")
    return True


def validate_artifact_registry(json_paths, npz_paths, *, candidates, recoil_seeds, kind, family):
    json_paths = list(json_paths)
    npz_paths = list(npz_paths)
    expected_stems = {
        f"{candidate['candidate_id']}_seed_{seed}"
        for candidate in candidates
        for seed in recoil_seeds
    }
    json_stems = [path.stem for path in json_paths]
    npz_stems = [path.stem for path in npz_paths]
    if (
        len(json_paths) != len(expected_stems)
        or len(npz_paths) != len(expected_stems)
        or set(json_stems) != expected_stems
        or set(npz_stems) != expected_stems
    ):
        raise RuntimeError("Stage artifact registry is incomplete, duplicated, or contaminated.")
    npz_by_stem = {path.stem: path for path in npz_paths}
    records = []
    for json_path in json_paths:
        row = json.loads(json_path.read_text(encoding="utf-8"))
        expected_stem = f"{row.get('candidate_id')}_seed_{row.get('recoil_seed')}"
        if (
            row.get("kind") != kind
            or row.get("family") != family
            or expected_stem != json_path.stem
        ):
            raise ValueError(f"Artifact metadata disagrees with its registry key: {json_path}")
        npz_path = npz_by_stem[json_path.stem]
        if Path(row.get("outcomes_path", "")).resolve() != npz_path.resolve():
            raise ValueError(f"Artifact points at an unexpected outcome archive: {json_path}")
        if row.get("outcomes_sha256") != sha256(npz_path):
            raise ValueError(f"Outcome hash mismatch: {npz_path}")
        with np.load(npz_path) as data:
            required = {"usable_at_end", "usable_ever", "ensemble_ids"}
            if not required.issubset(data.files):
                raise ValueError(f"Incomplete outcome archive: {npz_path}")
            lengths = {len(np.asarray(data[key])) for key in required}
            if lengths != {int(row["input_particle_count"])}:
                raise ValueError(f"Outcome length mismatch: {npz_path}")
        records.append(row)
    return records


def simultaneous_intervals(bootstrap, means, alpha=0.05):
    bootstrap = np.asarray(bootstrap, dtype=float)
    means = np.asarray(means, dtype=float)
    centered = bootstrap - means[None, :]
    standard_errors = bootstrap.std(axis=0, ddof=1)
    safe = np.where(standard_errors > 0, standard_errors, 1.0)
    studentized = centered / safe[None, :]
    studentized[:, standard_errors == 0] = 0.0
    critical = float(np.quantile(np.max(np.abs(studentized), axis=1), 1.0 - alpha))
    return means - critical * standard_errors, means + critical * standard_errors, critical


def simultaneous_paired_differences(bootstrap, means, leader_index, alpha=0.05):
    differences = bootstrap - bootstrap[:, [leader_index]]
    mean_differences = means - means[leader_index]
    centered = differences - mean_differences[None, :]
    standard_errors = differences.std(axis=0, ddof=1)
    safe = np.where(standard_errors > 0, standard_errors, 1.0)
    studentized = centered / safe[None, :]
    studentized[:, standard_errors == 0] = 0.0
    critical = float(np.quantile(np.max(np.abs(studentized), axis=1), 1.0 - alpha))
    return (
        mean_differences - critical * standard_errors,
        mean_differences + critical * standard_errors,
        critical,
    )

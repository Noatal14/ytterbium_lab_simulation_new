"""Integrity helpers shared by post-discovery 3D-MOT selection stages."""

import hashlib
import io
import json
from pathlib import Path

import numpy as np


OUTCOME_ARCHIVE_MEMBERS = frozenset({"usable_at_end", "usable_ever", "ensemble_ids"})


def expected_ensemble_ids(counts):
    if (
        not isinstance(counts, (list, tuple))
        or not counts
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in counts
        )
    ):
        raise ValueError("Frozen ensemble counts must be positive integers.")
    return np.concatenate(
        [np.full(value, index, dtype=np.int64) for index, value in enumerate(counts)]
    )


def validate_outcome_archive(npz_path, input_particle_count, *, expected_sha256=None):
    """Return strict, uncoerced outcome arrays from a canonical result archive."""
    if (
        isinstance(input_particle_count, bool)
        or not isinstance(input_particle_count, int)
        or input_particle_count <= 0
    ):
        raise ValueError("Outcome particle count must be a positive integer.")
    try:
        from workflow_api.mot_3d_preliminary_results import (
            validate_npz_container_bytes,
        )

        with Path(npz_path).open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if (
            expected_sha256 is not None
            and hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise ValueError(f"Outcome hash mismatch: {npz_path}")
        # An int64 ID array for 16,675 sealed atoms exceeds the preliminary
        # stage's 128-KiB limit. Bound allocation by the trusted count, while
        # retaining the shared 2-MiB ceiling and strict array checks below.
        validate_npz_container_bytes(
            raw, max_member_bytes=min(2 * 1024 * 1024,
                                      max(128 * 1024, 8 * input_particle_count + 10_000))
        )
        with np.load(io.BytesIO(raw), allow_pickle=False) as data:
            if set(data.files) != OUTCOME_ARCHIVE_MEMBERS:
                raise ValueError(f"Unexpected outcome archive members: {npz_path}")
            usable_at_end = np.asarray(data["usable_at_end"])
            usable_ever = np.asarray(data["usable_ever"])
            ensemble_ids = np.asarray(data["ensemble_ids"])
    except (OSError, ValueError, TypeError) as error:
        if isinstance(error, ValueError) and str(error).startswith("Unexpected"):
            raise
        raise ValueError(f"Invalid outcome archive: {npz_path}") from error
    arrays = (usable_at_end, usable_ever, ensemble_ids)
    if any(array.ndim != 1 or len(array) != input_particle_count for array in arrays):
        raise ValueError(f"Outcome shape mismatch: {npz_path}")
    if usable_at_end.dtype.kind != "b" or usable_ever.dtype.kind != "b":
        raise ValueError(f"Outcome masks must have boolean dtype: {npz_path}")
    if ensemble_ids.dtype.kind not in "iu" or np.any(ensemble_ids < 0):
        raise ValueError(
            f"Ensemble identifiers must be non-negative integers: {npz_path}"
        )
    if np.any(usable_at_end & ~usable_ever):
        raise ValueError(f"End-usable particles must also be ever-usable: {npz_path}")
    return usable_at_end, usable_ever, ensemble_ids


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_stage_design(
    manifest_path,
    selection_path,
    role,
    dt_s,
    t_max_s,
    *,
    particle_selection,
    particles_per_ensemble=None,
    selection_seed=None,
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
    from workflow_api.mot_3d_workload import artifact_identity
    return {
        **artifact_identity(manifest),
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
            raise ValueError(
                f"Stale or contaminated result {json_path}: {key} mismatch."
            )
    validate_outcome_archive(npz_path, payload.get("input_particle_count"))
    return True


def validate_artifact_registry(
    json_paths, npz_paths, *, candidates, recoil_seeds, kind, family
):
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
        raise RuntimeError(
            "Stage artifact registry is incomplete, duplicated, or contaminated."
        )
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
            raise ValueError(
                f"Artifact metadata disagrees with its registry key: {json_path}"
            )
        npz_path = npz_by_stem[json_path.stem]
        if Path(row.get("outcomes_path", "")).resolve() != npz_path.resolve():
            raise ValueError(
                f"Artifact points at an unexpected outcome archive: {json_path}"
            )
        from workflow_api.mot_3d_preliminary_results import (
            validate_npz_container_bytes,
        )

        try:
            with Path(npz_path).open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            if hashlib.sha256(raw).hexdigest() != row.get("outcomes_sha256"):
                raise ValueError(f"Outcome hash mismatch: {npz_path}")
            # Selection counts are checked against the frozen stage design
            # downstream; retain a hard per-member ceiling before NumPy load.
            validate_npz_container_bytes(raw, max_member_bytes=2 * 1024 * 1024)
        except (OSError, ValueError) as error:
            raise ValueError(f"Invalid outcome archive: {npz_path}") from error
        with np.load(io.BytesIO(raw), allow_pickle=False) as data:
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
    return (
        means - critical * standard_errors,
        means + critical * standard_errors,
        critical,
    )


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

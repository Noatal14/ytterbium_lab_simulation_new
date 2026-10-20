"""Strict byte-bound validation of the canonical finalist-selection results."""

from __future__ import annotations

from argparse import Namespace
import contextlib
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping

import numpy as np

from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY
from workflow_api.mot_3d_preliminary_results import (
    FROZEN_DESIGN_KEYS,
    FROZEN_ROLE_KEYS,
    PRELIMINARY_RESULT_REASON_CODES,
    PreliminaryResultError,
    _canonical,
    _outcome_reference_matches,
    _finite_tree,
    _strict_json,
    _strict_json_bytes,
    _validate_npz_container,
    validate_frozen_role_records,
)
from workflow_api.mot_3d_stage_topology import FAMILIES

RECOIL_SEEDS = (43001, 43002, 43003)
EXPECTED_CANDIDATES = 3
EXPECTED_RESULT_FILES = 44
SELECTION_RULE = (
    "top three closure candidates ranked by the lower endpoint of the "
    "simultaneous 95% confidence interval"
)
ROLE_SEEDS = {
    "discovery": tuple(range(3015, 3027)),
    "refinement": tuple(range(3027, 3031)),
    "preliminary_check": tuple(range(3031, 3035)),
}
FINALIST_RESULT_REASON_CODES = PRELIMINARY_RESULT_REASON_CODES


class FinalistResultError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedFinalistResults:
    paths: tuple[str, ...]
    hashes: Mapping[str, str]
    summaries: Mapping[str, Mapping[str, Any]]
    evidence_sha256: str


def _raise(code: str, error: Exception | None = None):
    if error is None:
        raise FinalistResultError(code)
    raise FinalistResultError(code) from error


def _candidate_ids(selection, family):
    rows = selection.get("candidates") if isinstance(selection, Mapping) else None
    identifiers = tuple(
        row.get("candidate_id") if isinstance(row, Mapping) else None
        for row in rows or ()
    )
    if (
        selection.get("kind") != "mot_3d_finalist_selection"
        or selection.get("family") != family
        or selection.get("candidate_count") != EXPECTED_CANDIDATES
        or len(rows or ()) != EXPECTED_CANDIDATES
        or identifiers
        != tuple(f"{family}_finalist_{index:02d}" for index in range(1, 4))
    ):
        _raise("selection_mismatch")
    return identifiers


def _all_particle_provenance(manifest, project_directory):
    from workflow_api.mot_3d_workload import policy

    acceptance = policy(manifest)
    roles = manifest.get("input_roles")
    names = ("discovery", "refinement", "preliminary_check")
    if not isinstance(roles, Mapping) or set(roles) != set(names):
        _raise("particle_selection_mismatch")
    # Frozen 2D ensembles retain their original authenticated source revision;
    # the 3D worker revision is independently bound by its own design/receipts.
    upstream = manifest.get("upstream_2d_campaign", {})
    if not isinstance(upstream, Mapping):
        _raise("particle_selection_mismatch")
    source_design = upstream.get("expected_survivor_design")
    commit = upstream.get("git_commit")
    if (
        not isinstance(source_design, Mapping)
        or type(commit) is not str
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or source_design.get("git_commit") != commit
    ):
        _raise("particle_selection_mismatch")
    rows = []
    for role in names:
        try:
            validated = validate_frozen_role_records(
                roles[role],
                project_directory=project_directory,
                expected_zeeman_seeds=ROLE_SEEDS[role],
                source_git_commit=commit,
                acceptance_provenance=(
                    None if acceptance is None else acceptance.provenance()
                ),
            )
        except PreliminaryResultError as exc:
            _raise("particle_selection_mismatch", exc)
        rows.extend(validated)
    if len(rows) != 20:
        _raise("particle_selection_mismatch")
    provenance = []
    for ensemble_id, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != FROZEN_ROLE_KEYS:
            _raise("particle_selection_mismatch")
        count, path = row["n_survivors"], row["path"]
        digest = row["sha256"]
        provenance.append(
            {
                "ensemble_id": ensemble_id,
                "file": path,
                "array_sha256": digest,
                "zeeman_seed": row["zeeman_seed"],
                "mot_seed": row["mot_seed"],
                "particle_count": count,
            }
        )
    return rows, provenance


def expected_paths(selections):
    if not isinstance(selections, Mapping) or set(selections) != set(FAMILIES):
        _raise("selection_mismatch")
    paths = set()
    for family in FAMILIES:
        identifiers = _candidate_ids(selections[family], family)
        for index, identifier in enumerate(identifiers):
            root = f"finalist_selection/{family}/finalist_{index}"
            paths.add(f"{root}/particle_selection.json")
            for seed in RECOIL_SEEDS:
                stem = f"{identifier}_seed_{seed}"
                paths.update({f"{root}/{stem}.json", f"{root}/{stem}.npz"})
        paths.add(f"finalist_selection/{family}/merged/finalist_summary.json")
    if len(paths) != EXPECTED_RESULT_FILES:
        _raise("artifact_registry_mismatch")
    return tuple(sorted(paths))


def validate_finalist_result_bytes(
    manifest_bytes: bytes,
    selection_bytes: Mapping[str, bytes],
    result_files: Mapping[str, bytes],
    *,
    project_directory: str,
    campaign_absolute_path: str,
    closure_summary_bytes: Mapping[str, bytes] | None = None,
):
    """Validate against original Closure summaries from an authenticated bundle.

    The caller must authenticate those bytes through the predecessor receipt;
    omitted authority fails closed rather than accepting a weaker selection.
    """
    if (
        not isinstance(manifest_bytes, bytes)
        or not 0 < len(manifest_bytes) <= 2 * 1024 * 1024
        or not isinstance(selection_bytes, Mapping)
        or set(selection_bytes) != set(FAMILIES)
        or not isinstance(result_files, Mapping)
        or any(
            not isinstance(raw, bytes) or not 0 < len(raw) <= 2 * 1024 * 1024
            for raw in selection_bytes.values()
        )
        or any(
            type(name) is not str
            or not isinstance(raw, bytes)
            or not 0 < len(raw) <= 2 * 1024 * 1024
            for name, raw in result_files.items()
        )
    ):
        _raise("artifact_registry_mismatch")
    if (not isinstance(closure_summary_bytes, Mapping)
            or set(closure_summary_bytes) != set(FAMILIES)
            or any(not isinstance(raw, bytes) or not 0 < len(raw) <= 2 * 1024 * 1024
                   for raw in closure_summary_bytes.values())):
        _raise("selection_mismatch")
    try:
        manifest = _strict_json_bytes(manifest_bytes)
        from workflow_api.mot_3d_workload import artifact_identity

        frozen_keys = FROZEN_DESIGN_KEYS | set(artifact_identity(manifest))
        selections = {
            family: _strict_json_bytes(selection_bytes[family]) for family in FAMILIES
        }
    except (KeyError, TypeError, PreliminaryResultError) as exc:
        _raise("malformed_json", exc)
    paths = expected_paths(selections)
    if set(result_files) != set(paths):
        _raise("artifact_registry_mismatch")
    name = manifest.get("name")
    segment = "ui_acceptance/" if artifact_identity(manifest) else ""
    expected_root = f"{project_directory}/data/optimization/mot_3d/{segment}{name}"
    stage = manifest.get("stages", {}).get("finalist_selection", {})
    if (
        type(name) is not str
        or campaign_absolute_path != expected_root
        or str(PurePosixPath(campaign_absolute_path)) != campaign_absolute_path
        or manifest.get("stage") != "finalist_selection"
        or stage.get("classification")
        != "final_candidate_selection_not_unbiased_validation"
        or stage.get("input_roles") != ["discovery", "refinement", "preliminary_check"]
        or manifest.get("design", {}).get("screening_dt_s")
        != MOT_3D_TIMESTEP_POLICY["search_dt_s"]
        or manifest.get("design", {}).get("solver") != MOT_3D_TIMESTEP_POLICY["solver"]
    ):
        _raise("design_mismatch")
    role_rows, expected_particles = _all_particle_provenance(
        manifest, project_directory
    )
    hashes = {
        path: hashlib.sha256(raw).hexdigest() for path, raw in result_files.items()
    }
    with tempfile.TemporaryDirectory(prefix="mot3d-finalist-verify-") as temporary:
        root = Path(temporary)
        (root / "campaign.json").write_bytes(manifest_bytes)
        for family, raw in selection_bytes.items():
            target = root / "selection/finalists" / f"{family}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        for relative, raw in result_files.items():
            target = root.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".npz"):
                try:
                    _validate_npz_container(raw, max_member_bytes=2 * 1024 * 1024)
                except PreliminaryResultError as exc:
                    _raise("result_archive_invalid", exc)
            if (
                relative.endswith(".json")
                and "finalist_" in relative
                and not relative.endswith("particle_selection.json")
                and not relative.endswith("finalist_summary.json")
            ):
                try:
                    record = _strict_json_bytes(raw)
                except PreliminaryResultError as exc:
                    _raise("malformed_json", exc)
                suffix = PurePosixPath(relative).with_suffix(".npz").as_posix()
                if not _outcome_reference_matches(
                    record.get("outcomes_path"), campaign_absolute_path=str(expected_root),
                    project_directory=project_directory, artifact=suffix,
                ):
                    _raise("result_metadata_mismatch")
                record["outcomes_path"] = str(
                    root.joinpath(*PurePosixPath(suffix).parts)
                )
                raw = json.dumps(record, indent=2, allow_nan=False).encode() + b"\n"
            target.write_bytes(raw)
        summaries = {}
        for family in FAMILIES:
            selection = selections[family]
            ids = _candidate_ids(selection, family)
            from studies.mot_3d.discovery.optimize import build_profile_from_parameters

            if set(selection) != {
                "kind",
                "family",
                "candidate_count",
                "selection_rule",
                "candidates",
            }:
                _raise("selection_mismatch")
            if selection.get("selection_rule") != SELECTION_RULE:
                _raise("selection_mismatch")
            if not isinstance(closure_summary_bytes, Mapping) or set(closure_summary_bytes) != set(FAMILIES):
                _raise("selection_mismatch")
            try:
                from studies.mot_3d.finalists.select import select_from_summary

                source_summary = _strict_json_bytes(closure_summary_bytes[family])
                expected_selection = select_from_summary(family, source_summary)
            except Exception as exc:
                _raise("selection_mismatch", exc)
            if _canonical(selection) != _canonical(expected_selection):
                _raise("selection_mismatch")
            for rank, candidate in enumerate(selection["candidates"], 1):
                if not isinstance(candidate, Mapping):
                    _raise("selection_mismatch")
                try:
                    profile, parameters, derived = build_profile_from_parameters(
                        family, candidate.get("parameters")
                    )
                except Exception as exc:
                    _raise("selection_mismatch", exc)
                if (
                    set(candidate)
                    != {
                        "candidate_id",
                        "finalist_rank_from_closure",
                        "source_candidate_id",
                        "source_closure_role",
                        "source_closure_fraction",
                        "source_closure_ci",
                        "parameters",
                        "derived_parameters",
                        "resolved_profile",
                    }
                    or candidate.get("finalist_rank_from_closure") != rank
                    or candidate.get("parameters") != parameters
                    or candidate.get("derived_parameters") != derived
                    or _canonical(candidate.get("resolved_profile"))
                    != _canonical(profile)
                    or type(candidate.get("source_candidate_id")) is not str
                    or type(candidate.get("source_closure_fraction"))
                    not in {int, float}
                    or isinstance(candidate.get("source_closure_fraction"), bool)
                    or not 0 <= candidate["source_closure_fraction"] <= 1
                    or not isinstance(candidate.get("source_closure_ci"), list)
                    or len(candidate["source_closure_ci"]) != 2
                    or any(
                        type(value) not in {int, float} or isinstance(value, bool)
                        for value in candidate["source_closure_ci"]
                    )
                ):
                    _raise("selection_mismatch")
            json_paths, npz_paths, particle_rows = [], [], []
            for index, identifier in enumerate(ids):
                directory = root / "finalist_selection" / family / f"finalist_{index}"
                particle_rows.append(
                    _strict_json(
                        directory / "particle_selection.json", require_mapping=False
                    )
                )
                for seed in RECOIL_SEEDS:
                    stem = f"{identifier}_seed_{seed}"
                    json_paths.append(directory / f"{stem}.json")
                    npz_paths.append(directory / f"{stem}.npz")
            if any(row != expected_particles for row in particle_rows):
                _raise("particle_selection_mismatch")
            try:
                from studies.mot_3d.integrity import validate_artifact_registry

                records = validate_artifact_registry(
                    json_paths,
                    npz_paths,
                    candidates=selection["candidates"],
                    recoil_seeds=RECOIL_SEEDS,
                    kind="mot_3d_finalist_seed_result",
                    family=family,
                )
            except Exception as exc:
                _raise("result_registry_invalid", exc)
            designs = [row.get("design") for row in records]
            if (
                not designs
                or not isinstance(designs[0], Mapping)
                or any(row != designs[0] for row in designs[1:])
            ):
                _raise("design_mismatch")
            design = designs[0]
            expected_count = sum(row["n_survivors"] for row in role_rows)
            for record in records:
                counts = [
                    record.get(key)
                    for key in (
                        "usable_at_end_count",
                        "usable_ever_count",
                        "peak_usable_count",
                        "entered_capture_region_count",
                        "slow_inside_count",
                    )
                ]
                if (
                    set(record)
                    != {
                        "kind",
                        "family",
                        "candidate_id",
                        "finalist_index",
                        "recoil_seed",
                        "input_particle_count",
                        "usable_at_end_count",
                        "usable_ever_count",
                        "peak_usable_count",
                        "entered_capture_region_count",
                        "slow_inside_count",
                        "outcomes_path",
                        "outcomes_sha256",
                        "design",
                    }
                    or record.get("input_particle_count") != expected_count
                    or type(record.get("finalist_index")) is not int
                    or not 0 <= record["finalist_index"] < 3
                    or ids[record["finalist_index"]] != record.get("candidate_id")
                    or record.get("recoil_seed") not in RECOIL_SEEDS
                    or any(
                        type(value) is not int or not 0 <= value <= expected_count
                        for value in counts
                    )
                    or counts[0] > counts[1]
                    or counts[0] > counts[2]
                    or counts[4] > counts[3]
                ):
                    _raise("result_metadata_mismatch")
                stem = f"{record['candidate_id']}_seed_{record['recoil_seed']}"
                archive_path = next(path for path in npz_paths if path.stem == stem)
                with np.load(archive_path, allow_pickle=False) as archive:
                    usable = archive["usable_at_end"]
                    ever = archive["usable_ever"]
                    groups = archive["ensemble_ids"]
                    expected_groups = np.repeat(
                        np.arange(20), [row["n_survivors"] for row in role_rows]
                    )
                    if (
                        usable.shape != (expected_count,)
                        or ever.shape != (expected_count,)
                        or groups.shape != (expected_count,)
                        or usable.dtype != np.bool_
                        or ever.dtype != np.bool_
                        or not np.issubdtype(groups.dtype, np.integer)
                        or not np.array_equal(groups, expected_groups)
                        or np.any(usable & ~ever)
                        or int(usable.sum()) != record["usable_at_end_count"]
                        or int(ever.sum()) != record["usable_ever_count"]
                    ):
                        _raise("result_archive_invalid")
            if (
                set(design) != frozen_keys
                or any(
                    design.get(key) != value
                    for key, value in artifact_identity(manifest).items()
                )
                or design.get("campaign_manifest_path")
                != f"{expected_root}/campaign.json"
                or design.get("selection_path")
                != f"{expected_root}/selection/finalists/{family}.json"
                or design.get("git_commit")
                != manifest.get("provenance", {}).get("git_commit")
                or design.get("physical_model_sha256")
                != manifest.get("provenance", {}).get("physical_model_sha256")
                or design.get("campaign_manifest_sha256")
                != hashlib.sha256(manifest_bytes).hexdigest()
                or design.get("input_role_sha256")
                != hashlib.sha256(_canonical(role_rows)).hexdigest()
                or design.get("particle_selection_sha256")
                != hashlib.sha256(_canonical(expected_particles)).hexdigest()
                or design.get("selection_sha256")
                != hashlib.sha256(selection_bytes[family]).hexdigest()
                or design.get("input_role") != "all_existing_selection"
                or design.get("dt_s") != MOT_3D_TIMESTEP_POLICY["search_dt_s"]
                or design.get("t_max_s") != MOT_3D_TIMESTEP_POLICY["t_max_s"]
                or design.get("solver") != MOT_3D_TIMESTEP_POLICY["solver"]
            ):
                _raise("design_mismatch")
            summary = _strict_json(
                root / "finalist_selection" / family / "merged/finalist_summary.json"
            )
            if (
                summary.get("kind") != "merged_mot_3d_finalist_selection"
                or summary.get("family") != family
                or summary.get("candidate_count") != 3
                or summary.get("ensemble_file_indices") != list(range(20))
                or summary.get("recoil_seed_count") != 3
                or summary.get("bootstrap_replicates") != 10_000
                or summary.get("bootstrap_seed") != 82_001
                or summary.get("selection_sha256")
                != hashlib.sha256(selection_bytes[family]).hexdigest()
                or summary.get("design") != design
                or not _finite_tree(summary)
            ):
                _raise("summary_mismatch")
            from studies.mot_3d.finalists.merge import merge

            # The normal merger reopens the design's frozen manifest. Only
            # after validating every original remote identity/hash above, bind
            # that temporary recomputation to the already captured bytes.
            captured_manifest_path = str(root / "campaign.json")
            for metadata_path in json_paths:
                materialized = _strict_json(metadata_path)
                materialized["design"] = {
                    **materialized["design"],
                    "campaign_manifest_path": captured_manifest_path,
                }
                metadata_path.write_bytes(_canonical(materialized))
            output = root / "recomputed" / family
            with contextlib.redirect_stdout(io.StringIO()):
                merge(
                    Namespace(
                        selection=str(root / "selection/finalists" / f"{family}.json"),
                        input_root=str(root / "finalist_selection" / family),
                        output_dir=str(output),
                        bootstrap_replicates=10_000,
                        bootstrap_seed=82_001,
                    )
                )
            recomputed = _strict_json(output / "finalist_summary.json")
            recomputed_design = recomputed.get("design")
            if (
                not isinstance(recomputed_design, dict)
                or recomputed_design.get("campaign_manifest_path")
                != captured_manifest_path
            ):
                _raise("summary_mismatch")
            recomputed_design["campaign_manifest_path"] = design["campaign_manifest_path"]
            if recomputed != summary:
                _raise("summary_mismatch")
            summaries[family] = summary
    return ValidatedFinalistResults(
        paths, hashes, summaries, hashlib.sha256(_canonical(hashes)).hexdigest()
    )

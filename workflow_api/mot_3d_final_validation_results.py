"""Strict byte-source validation for sealed 3D final-validation results."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Mapping

from workflow_api.mot_3d_preliminary_results import (
    _canonical,
    _strict_json_bytes,
    validate_npz_container_bytes,
)
from workflow_api.mot_3d_stage_topology import FAMILIES

RECOIL_SEEDS = (44001, 44002, 44003)
EXPECTED_RESULT_FILES = 14
MAX_FILE_BYTES = 2 * 1024 * 1024
FINAL_VALIDATION_RESULT_REASON_CODES = frozenset(
    {
        "artifact_registry_mismatch",
        "manifest_mismatch",
        "submission_mismatch",
        "result_archive_invalid",
        "result_registry_invalid",
        "summary_mismatch",
        "completion_mismatch",
    }
)


class FinalValidationResultError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedFinalValidationResults:
    paths: tuple[str, ...]
    hashes: Mapping[str, str]
    summaries: Mapping[str, Mapping[str, object]]
    evidence_sha256: str
    outcome: str
    terminal_name: str
    terminal_bytes: bytes
    campaign_bytes: bytes


def expected_paths() -> tuple[str, ...]:
    paths = set()
    for family in FAMILIES:
        root = f"final_validation/{family}"
        for seed in RECOIL_SEEDS:
            paths.update({f"{root}/seed_{seed}.json", f"{root}/seed_{seed}.npz"})
        paths.add(f"{root}/final_validation_summary.json")
    if len(paths) != EXPECTED_RESULT_FILES:
        raise AssertionError("invalid final-validation result registry")
    return tuple(sorted(paths))


def _raise(code: str, cause: Exception | None = None):
    if cause is None:
        raise FinalValidationResultError(code)
    raise FinalValidationResultError(code) from cause


def _safe_bytes(value, *, code):
    if type(value) is not bytes or not 0 < len(value) <= MAX_FILE_BYTES:
        _raise(code)


def validate_final_validation_result_bytes(
    *,
    manifest_bytes: bytes,
    locked_nominals_bytes: bytes,
    input_manifest_bytes: bytes,
    generation_submission_bytes: bytes,
    submission_bytes: bytes,
    job_files: Mapping[str, bytes],
    input_files: Mapping[str, bytes],
    result_files: Mapping[str, bytes],
    logical_campaign_root: str,
    project_directory: str,
    campaign_absolute_path: str,
) -> ValidatedFinalValidationResults:
    """Validate and recompute one exact sealed result set from captured bytes."""

    for value, code in (
        (manifest_bytes, "manifest_mismatch"),
        (locked_nominals_bytes, "manifest_mismatch"),
        (input_manifest_bytes, "manifest_mismatch"),
        (generation_submission_bytes, "manifest_mismatch"),
        (submission_bytes, "submission_mismatch"),
    ):
        _safe_bytes(value, code=code)
    expected = set(expected_paths())
    from workflow_api.mot_3d_final_input_results import expected_paths as input_paths

    if (
        not isinstance(result_files, Mapping)
        or set(result_files) != expected
        or not isinstance(job_files, Mapping)
        or set(job_files)
        != {
            f"jobs/final_validation/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        }
        or not isinstance(input_files, Mapping)
        or set(input_files) != set(input_paths(_strict_json_bytes(manifest_bytes)))
    ):
        _raise("artifact_registry_mismatch")
    for name, raw in {**job_files, **input_files, **result_files}.items():
        if (
            type(name) is not str
            or PurePosixPath(name).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(name).parts)
        ):
            _raise("artifact_registry_mismatch")
        _safe_bytes(raw, code="result_registry_invalid")
        if name.endswith(".npz"):
            try:
                validate_npz_container_bytes(raw, max_member_bytes=MAX_FILE_BYTES)
            except Exception as exc:
                _raise("result_archive_invalid", exc)
        elif name.endswith(".json"):
            try:
                decoded = _strict_json_bytes(raw)
            except Exception as exc:
                _raise("result_registry_invalid", exc)
            if not isinstance(decoded, dict):
                _raise("result_registry_invalid")
        elif name.endswith(".pbs"):
            try:
                text = raw.decode("utf-8", "strict")
            except UnicodeError as exc:
                _raise("result_registry_invalid", exc)
            if not text.startswith("#!/bin/bash\n"):
                _raise("result_registry_invalid")
        elif not name.endswith(".npy"):
            _raise("result_registry_invalid")
    try:
        manifest = _strict_json_bytes(manifest_bytes)
        from workflow_api import mot_3d_workload as workload

        acceptance = workload.policy(manifest)
        _strict_json_bytes(locked_nominals_bytes)
        _strict_json_bytes(input_manifest_bytes)
        _strict_json_bytes(generation_submission_bytes)
        _strict_json_bytes(submission_bytes)
    except Exception as exc:
        _raise("manifest_mismatch", exc)
    logical = PurePosixPath(logical_campaign_root)
    project = PurePosixPath(project_directory)
    absolute_campaign = PurePosixPath(campaign_absolute_path)
    stage = manifest.get("stages", {}).get("final_validation", {})
    if (
        manifest.get("stage") != "final_validation"
        or logical.is_absolute()
        or logical.parts[:3] != ("data", "optimization", "mot_3d")
        or len(logical.parts) != (5 if acceptance else 4)
        or logical.name != manifest.get("name")
        or not project.is_absolute()
        or absolute_campaign != project / logical
        or str(project) != project_directory
        or str(absolute_campaign) != campaign_absolute_path
        or stage.get("locked_nominals")
        != f"{logical_campaign_root}/selection/locked_nominals.json"
        or stage.get("input_manifest")
        != f"{logical_campaign_root}/final_validation_inputs/input_manifest.json"
        or stage.get("worker_jobs")
        != {
            family: f"{logical_campaign_root}/jobs/final_validation/{family}_array.pbs"
            for family in FAMILIES
        }
        or stage.get("merge_jobs")
        != {
            family: f"{logical_campaign_root}/jobs/final_validation/{family}_merge.pbs"
            for family in FAMILIES
        }
    ):
        _raise("manifest_mismatch")
    original_inputs = _strict_json_bytes(input_manifest_bytes)
    if not isinstance(original_inputs, dict) or not isinstance(
        original_inputs.get("ensembles"), list
    ):
        _raise("manifest_mismatch")
    input_rows = original_inputs["ensembles"]
    if len(input_rows) != 20:
        _raise("manifest_mismatch")
    locked_nominals_sha256 = hashlib.sha256(locked_nominals_bytes).hexdigest()
    generation_submission_sha256 = hashlib.sha256(
        generation_submission_bytes
    ).hexdigest()
    survivor_counts = []
    for row in input_rows:
        if not isinstance(row, dict):
            _raise("manifest_mismatch")
        count = row.get("n_survivors")
        if type(count) is not int or count < 0:
            _raise("manifest_mismatch")
        survivor_counts.append(count)
    if (
        original_inputs.get("locked_nominals_sha256") != locked_nominals_sha256
        or original_inputs.get("generation_submission_sha256")
        != generation_submission_sha256
        or type(original_inputs.get("total_survivors")) is not int
        or original_inputs["total_survivors"] != sum(survivor_counts)
    ):
        _raise("manifest_mismatch")
    from lab_setup.physical_specification import (
        CANONICAL_ZEEMAN_PROFILE_SHA256,
        LABORATORY_SPEC_SHA256,
        LABORATORY_SPEC_VERSION,
    )
    from studies import mot_3d_campaign as campaign_module

    for row in input_rows:
        if not isinstance(row, dict):
            _raise("manifest_mismatch")
        for path_key, hash_key in (
            ("path", "sha256"),
            ("metadata_path", "metadata_sha256"),
            ("replicate_path", "replicate_sha256"),
            ("zeeman_path", "zeeman_sha256"),
            ("zeeman_metadata_path", "zeeman_metadata_sha256"),
        ):
            value = row.get(path_key)
            if type(value) is not str or not value.startswith(
                campaign_absolute_path + "/final_validation_inputs/"
            ):
                _raise("manifest_mismatch")
            relative = value[len(campaign_absolute_path) + 1 :]
            if (
                str(PurePosixPath(value)) != value
                or relative not in input_files
                or row.get(hash_key)
                != hashlib.sha256(input_files[relative]).hexdigest()
            ):
                _raise("manifest_mismatch")
        metadata_relative = row["metadata_path"][len(campaign_absolute_path) + 1 :]
        replicate_relative = row["replicate_path"][len(campaign_absolute_path) + 1 :]
        zeeman_metadata_relative = row["zeeman_metadata_path"][
            len(campaign_absolute_path) + 1 :
        ]
        metadata = _strict_json_bytes(input_files[metadata_relative])
        replicate = _strict_json_bytes(input_files[replicate_relative])
        zeeman_metadata = _strict_json_bytes(input_files[zeeman_metadata_relative])
        if acceptance is not None and any(
            item.get("acceptance") != manifest["acceptance"]
            for item in (metadata, replicate, zeeman_metadata)
        ):
            _raise("manifest_mismatch")
        expected_design = {
            "dt_s": campaign_module.MOT_2D_SIM_CONFIG["dt_s"],
            "stochastic_solver": manifest["upstream_2d_campaign"][
                "expected_survivor_design"
            ]["stochastic_solver"],
            "uses_all_available_particles": True,
            "npools": (
                200
                if acceptance is None
                else acceptance.policy["generation"]["jobs"]["mot_2d"]["npools"]
            ),
            "ensemble_dir": f"{campaign_absolute_path}/final_validation_inputs/after_zeeman",
            "zeeman_profile": manifest["upstream_2d_campaign"][
                "expected_survivor_design"
            ]["zeeman_profile"],
            "git_commit": manifest["provenance"]["git_commit"],
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        }
        if acceptance is not None:
            expected_design["acceptance"] = manifest["acceptance"]
        if (
            not isinstance(metadata, dict)
            or metadata.get("design") != expected_design
            or metadata.get("source_zeeman_ensemble") != row["zeeman_path"]
            or not isinstance(replicate, dict)
            or replicate.get("design") != expected_design
            or replicate.get("replicate", {}).get("ensemble_file") != row["zeeman_path"]
            or zeeman_metadata.get("laboratory_spec_version") != LABORATORY_SPEC_VERSION
            or zeeman_metadata.get("laboratory_spec_sha256") != LABORATORY_SPEC_SHA256
            or zeeman_metadata.get("zeeman_profile_sha256")
            != CANONICAL_ZEEMAN_PROFILE_SHA256
            or zeeman_metadata.get("output_sha256") != row["zeeman_sha256"]
        ):
            _raise("manifest_mismatch")
    hashes = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in result_files.items()
    }
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / logical.name
            root.mkdir()
            (root / "campaign.json").write_bytes(manifest_bytes)
            (root / "selection").mkdir()
            (root / "selection/locked_nominals.json").write_bytes(locked_nominals_bytes)
            (root / "final_validation_inputs").mkdir()
            (root / "final_validation_inputs/input_manifest.json").write_bytes(
                input_manifest_bytes
            )
            (root / "final_validation_submission.json").write_bytes(submission_bytes)
            (root / "final_validation_input_generation_submission.json").write_bytes(
                generation_submission_bytes
            )
            for name, raw in {**job_files, **input_files, **result_files}.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)

            def private_input_path(value: object) -> str:
                if type(value) is not str:
                    _raise("manifest_mismatch")
                portable = PurePosixPath(value)
                if any(part in {"", ".", ".."} for part in portable.parts):
                    _raise("manifest_mismatch")
                marker = "final_validation_inputs/"
                offset = value.find(marker)
                if offset < 0:
                    _raise("manifest_mismatch")
                relative = value[offset:]
                if relative not in input_files:
                    _raise("manifest_mismatch")
                return str(root / relative)

            private_inputs = json.loads(
                json.dumps(_strict_json_bytes(input_manifest_bytes))
            )
            from lab_setup.physical_specification import (
                CANONICAL_ZEEMAN_PROFILE_SHA256,
                LABORATORY_SPEC_SHA256,
                LABORATORY_SPEC_VERSION,
            )
            from studies import mot_3d_campaign as campaign_module

            for row in private_inputs.get("ensembles", []):
                survivor_metadata_name = row["metadata_path"].split(
                    "final_validation_inputs/", 1
                )[1]
                survivor_metadata_name = (
                    "final_validation_inputs/" + survivor_metadata_name
                )
                survivor_metadata = _strict_json_bytes(
                    input_files[survivor_metadata_name]
                )
                survivor_metadata["source_zeeman_ensemble"] = private_input_path(
                    survivor_metadata["source_zeeman_ensemble"]
                )
                survivor_metadata["design"][
                    "laboratory_spec_version"
                ] = LABORATORY_SPEC_VERSION
                survivor_metadata["design"][
                    "laboratory_spec_sha256"
                ] = LABORATORY_SPEC_SHA256
                survivor_metadata["design"][
                    "zeeman_profile_sha256"
                ] = CANONICAL_ZEEMAN_PROFILE_SHA256
                survivor_metadata["design"]["ensemble_dir"] = str(
                    root / "final_validation_inputs/after_zeeman"
                )
                survivor_metadata["design"]["dt_s"] = campaign_module.MOT_2D_SIM_CONFIG[
                    "dt_s"
                ]
                survivor_raw = json.dumps(
                    survivor_metadata, separators=(",", ":"), allow_nan=False
                ).encode()
                (root / survivor_metadata_name).write_bytes(survivor_raw)

                replicate_name = row["replicate_path"].split(
                    "final_validation_inputs/", 1
                )[1]
                replicate_name = "final_validation_inputs/" + replicate_name
                replicate = _strict_json_bytes(input_files[replicate_name])
                replicate["replicate"]["ensemble_file"] = private_input_path(
                    replicate["replicate"]["ensemble_file"]
                )
                replicate["design"] = json.loads(
                    json.dumps(survivor_metadata["design"])
                )
                replicate_raw = json.dumps(
                    replicate, separators=(",", ":"), allow_nan=False
                ).encode()
                (root / replicate_name).write_bytes(replicate_raw)

                zeeman_metadata_name = row["zeeman_metadata_path"].split(
                    "final_validation_inputs/", 1
                )[1]
                zeeman_metadata_name = "final_validation_inputs/" + zeeman_metadata_name
                zeeman_metadata = _strict_json_bytes(input_files[zeeman_metadata_name])
                zeeman_metadata["laboratory_spec_version"] = LABORATORY_SPEC_VERSION
                zeeman_metadata["laboratory_spec_sha256"] = LABORATORY_SPEC_SHA256
                zeeman_metadata["zeeman_profile_sha256"] = (
                    CANONICAL_ZEEMAN_PROFILE_SHA256
                )
                zeeman_raw = json.dumps(
                    zeeman_metadata, separators=(",", ":"), allow_nan=False
                ).encode()
                (root / zeeman_metadata_name).write_bytes(zeeman_raw)

                for key in (
                    "path",
                    "metadata_path",
                    "replicate_path",
                    "zeeman_path",
                    "zeeman_metadata_path",
                ):
                    row[key] = private_input_path(row[key])
                row["metadata_sha256"] = hashlib.sha256(survivor_raw).hexdigest()
                row["replicate_sha256"] = hashlib.sha256(replicate_raw).hexdigest()
                row["zeeman_metadata_sha256"] = hashlib.sha256(zeeman_raw).hexdigest()
            private_inputs["locked_nominals_sha256"] = locked_nominals_sha256
            private_inputs["generation_submission_sha256"] = (
                generation_submission_sha256
            )
            provisional_manifest = json.loads(json.dumps(manifest))
            provisional_stage = provisional_manifest["stages"][
                "final_validation_input_generation"
            ]
            provisional_stage["locked_nominals"] = str(
                root / "selection/locked_nominals.json"
            )
            provisional_stage["zeeman_job"] = str(
                root / "jobs/final_validation_inputs/01_generate_zeeman.pbs"
            )
            provisional_stage["mot_job"] = str(
                root / "jobs/final_validation_inputs/02_generate_2d_survivors.pbs"
            )
            provisional_stage["freeze_job"] = str(
                root / "jobs/final_validation_inputs/03_freeze_inputs.pbs"
            )
            provisional_stage["input_manifest"] = str(
                root / "final_validation_inputs/input_manifest.json"
            )
            from studies.mot_3d_campaign import _collect_final_validation_inputs

            private_inputs["ensembles"] = _collect_final_validation_inputs(
                root, provisional_manifest
            )
            private_inputs["total_survivors"] = sum(
                row["n_survivors"] for row in private_inputs["ensembles"]
            )
            private_input_raw = json.dumps(
                private_inputs, separators=(",", ":"), allow_nan=False
            ).encode()
            (root / "final_validation_inputs/input_manifest.json").write_bytes(
                private_input_raw
            )
            private_input_sha = hashlib.sha256(private_input_raw).hexdigest()

            original_summaries = {}
            original_summary_hashes = {}
            for family in FAMILIES:
                family_root = f"final_validation/{family}"
                for seed in RECOIL_SEEDS:
                    json_name = f"{family_root}/seed_{seed}.json"
                    archive_name = f"{family_root}/seed_{seed}.npz"
                    row = _strict_json_bytes(result_files[json_name])
                    path = PurePosixPath(row.get("outcomes_path", ""))
                    if (
                        row.get("outcomes_path")
                        != f"{campaign_absolute_path}/{archive_name}"
                        or str(path) != row["outcomes_path"]
                        or row.get("design", {}).get("input_manifest_sha256")
                        != hashlib.sha256(input_manifest_bytes).hexdigest()
                    ):
                        _raise("result_registry_invalid")
                    row["outcomes_path"] = str(root / archive_name)
                    row["design"]["input_manifest_sha256"] = private_input_sha
                    (root / json_name).write_bytes(
                        json.dumps(row, separators=(",", ":"), allow_nan=False).encode()
                    )
                summary_name = f"{family_root}/final_validation_summary.json"
                summary = _strict_json_bytes(result_files[summary_name])
                original_summaries[family] = summary
                original_summary_hashes[family] = hashlib.sha256(
                    result_files[summary_name]
                ).hexdigest()
                private_summary = json.loads(json.dumps(summary))
                private_summary["design"]["input_manifest_sha256"] = private_input_sha
                (root / summary_name).write_bytes(
                    json.dumps(
                        private_summary, separators=(",", ":"), allow_nan=False
                    ).encode()
                )
            private = json.loads(json.dumps(manifest))
            private_input_stage = private["stages"]["final_validation_input_generation"]
            private_input_stage["locked_nominals"] = str(
                root / "selection/locked_nominals.json"
            )
            private_input_stage["zeeman_job"] = str(
                root / "jobs/final_validation_inputs/01_generate_zeeman.pbs"
            )
            private_input_stage["mot_job"] = str(
                root / "jobs/final_validation_inputs/02_generate_2d_survivors.pbs"
            )
            private_input_stage["freeze_job"] = str(
                root / "jobs/final_validation_inputs/03_freeze_inputs.pbs"
            )
            private_input_stage["input_manifest"] = str(
                root / "final_validation_inputs/input_manifest.json"
            )
            private_stage = private["stages"]["final_validation"]
            private_stage["locked_nominals"] = str(
                root / "selection/locked_nominals.json"
            )
            private_stage["input_manifest"] = str(
                root / "final_validation_inputs/input_manifest.json"
            )
            private_stage["worker_jobs"] = {
                family: str(root / f"jobs/final_validation/{family}_array.pbs")
                for family in FAMILIES
            }
            private_stage["merge_jobs"] = {
                family: str(root / f"jobs/final_validation/{family}_merge.pbs")
                for family in FAMILIES
            }
            from studies.mot_3d_campaign import complete_final_validation

            complete_final_validation(root, private)
            outcome = private["stage"]
            terminal_name = (
                "final_report.json"
                if outcome == "complete"
                else "final_validation_status.json"
            )
            if outcome not in {"complete", "final_validation_extension_required"}:
                _raise("completion_mismatch")
            terminal = _strict_json_bytes((root / terminal_name).read_bytes())
            terminal["results"] = original_summaries
            terminal["result_summary_sha256"] = original_summary_hashes
            terminal["provenance"]["input_manifest_sha256"] = hashlib.sha256(
                input_manifest_bytes
            ).hexdigest()
            from studies.mot_3d_campaign import _validate_final_report_schema

            _validate_final_report_schema(terminal)
            terminal_bytes = json.dumps(
                terminal, indent=2, ensure_ascii=False, allow_nan=False
            ).encode()
            completed = _strict_json_bytes((root / "campaign.json").read_bytes())
            # The canonical routine operates on private materialized paths.  Never
            # allow those temporary host paths into the portable campaign manifest.
            completed["stages"]["final_validation_input_generation"] = manifest[
                "stages"
            ]["final_validation_input_generation"]
            completed["stages"]["final_validation"] = manifest["stages"][
                "final_validation"
            ]
            registry_key = (
                "final_report" if outcome == "complete" else "final_validation_status"
            )
            completed["stages"][
                registry_key
            ] = f"{logical_campaign_root}/{terminal_name}"
            campaign_bytes = json.dumps(
                completed, indent=2, ensure_ascii=False, allow_nan=False
            ).encode()
            summaries = original_summaries
    except FinalValidationResultError:
        raise
    except Exception as exc:
        _raise("summary_mismatch", exc)
    evidence = hashlib.sha256(_canonical(hashes)).hexdigest()
    return ValidatedFinalValidationResults(
        expected_paths(),
        hashes,
        summaries,
        evidence,
        outcome,
        terminal_name,
        terminal_bytes,
        campaign_bytes,
    )

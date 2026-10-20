"""Strict byte validation for sealed final-validation input generation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
from typing import Mapping

import numpy as np
from config import MOT_2D_SIM_CONFIG

ZEEMAN_SEEDS = tuple(range(3035, 3055))
MOT_SEEDS = tuple(range(43035, 43055))
EXPECTED_RESULT_FILES = 101
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
ARRAY_JOB = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR_JOB = re.compile(r"^\d+\.zeus-master$")
FAMILIES = ("angled_donut", "single_pass")
FINAL_INPUT_RESULT_REASON_CODES = (
    "artifact_registry_mismatch",
    "artifact_too_large",
    "malformed_json",
    "manifest_mismatch",
    "submission_mismatch",
    "input_metadata_mismatch",
    "input_array_invalid",
    "input_manifest_mismatch",
)


class FinalInputResultError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedFinalInputResults:
    paths: tuple[str, ...]
    hashes: Mapping[str, str]
    input_manifest: Mapping[str, object]
    evidence_sha256: str


def _raise(code, error=None):
    if error is None:
        raise FinalInputResultError(code)
    raise FinalInputResultError(code) from error


def _strict(raw: bytes):
    try:

        def pairs(rows):
            value = {}
            for key, item in rows:
                if key in value:
                    raise ValueError
                value[key] = item
            return value

        return json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except Exception as exc:
        _raise("malformed_json", exc)


def expected_paths(manifest=None) -> tuple[str, ...]:
    from workflow_api.mot_3d_workload import policy

    profile = None if manifest is None else policy(manifest)
    initial_particles = (
        50000
        if profile is None
        else profile.policy["generation"]["zeeman_initial_particles"]
    )
    paths = set()
    for zseed, mseed in zip(ZEEMAN_SEEDS, MOT_SEEDS):
        zstem = f"final_validation_inputs/after_zeeman/production_zeeman_n{initial_particles}_dt40us_seed{zseed}"
        mstem = f"final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed{zseed}_mot_seed{mseed}"
        paths.update({f"{zstem}.npy", f"{zstem}.json", f"{mstem}.npy", f"{mstem}.json"})
        paths.add(
            f"final_validation_inputs/mot_2d_records/replicates/zeeman_seed{zseed}.json"
        )
    paths.add("final_validation_inputs/input_manifest.json")
    assert len(paths) == EXPECTED_RESULT_FILES
    return tuple(sorted(paths))


def _canonical_path(value, expected):
    return (
        type(value) is str and value == expected and str(PurePosixPath(value)) == value
    )


def _array(raw, *, allow_empty=False):
    try:
        value = np.load(io.BytesIO(raw), allow_pickle=False)
    except Exception as exc:
        _raise("input_array_invalid", exc)
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.float64
        or value.ndim != 2
        or value.shape[1] != 6
        or (not allow_empty and value.shape[0] == 0)
        or not np.all(np.isfinite(value))
    ):
        _raise("input_array_invalid")
    return value


def _shape_matches(value, array):
    return type(value) is list and all(type(item) is int for item in value) and value == list(array.shape)


def _validate_current_zeeman(metadata, array, *, seed, initial, npools, profile, basename, output_hash, commit):
    """Attest the exact current producer schema and its physical run inputs."""
    import math
    from datetime import datetime
    from simulations.zeeman import _resolved_run_parameters
    from utils.file_helpers import _json_default
    from lab_setup.physical_specification import attest_canonical_zeeman_metadata
    keys={"kind","laboratory_spec_version","laboratory_spec_sha256","zeeman_profile_sha256",
          "created_utc","output_file","output_sha256","state_layout","shape","dtype",
          "n_survivors","survival_fraction","elapsed_seconds","parameters","software"}
    controlled=profile is not None and "controlled_input_recipe" in profile.policy["generation"]
    if profile is not None:keys.add("acceptance")
    if controlled:keys.update({"suitability","input_origin","controlled_input_origin"})
    try:
        expected=json.loads(json.dumps(_resolved_run_parameters({"seed":seed,"N_particles":initial,
                            "dt":4e-5,"npools":npools,"stochastic":True,"collimation_angle_deg":1.5}), default=_json_default))
        software=metadata.get("software")
        if (set(metadata)!=keys or metadata.get("kind")!="zeeman_survivor_ensemble"
                or json.dumps(metadata.get("parameters"),sort_keys=True,allow_nan=False)!=json.dumps(expected,sort_keys=True,allow_nan=False) or metadata.get("output_file")!=basename
                or metadata.get("output_sha256")!=output_hash or not _shape_matches(metadata.get("shape"),array)
                or metadata.get("dtype")!="float64" or metadata.get("state_layout")!=["x_m","y_m","z_m","vx_m_s","vy_m_s","vz_m_s"]
                or type(metadata.get("n_survivors")) is not int or metadata["n_survivors"]!=len(array)
                or len(array)>initial or type(metadata.get("survival_fraction")) is not float or metadata.get("survival_fraction")!=len(array)/initial
                or type(metadata.get("elapsed_seconds")) not in {int,float}
                or not math.isfinite(metadata["elapsed_seconds"]) or metadata["elapsed_seconds"]<0
                or not isinstance(software,dict) or set(software)!={"git_commit","tracked_worktree_was_dirty","python_version","atomsmltr_version","numpy_version","host"}
                or software.get("git_commit")!=commit or software.get("tracked_worktree_was_dirty") is not False
                or any(type(software[key]) is not str or len(software[key])>256 for key in ("python_version","numpy_version","host"))
                or software["atomsmltr_version"] is not None and type(software["atomsmltr_version"]) is not str):
            raise ValueError()
        if datetime.fromisoformat(metadata["created_utc"]).utcoffset() is None:raise ValueError()
        attest_canonical_zeeman_metadata(metadata,allow_legacy=False)
        if profile is not None and metadata.get("acceptance")!=profile.provenance():raise ValueError()
        if controlled:
            from workflow_api.acceptance_inputs import controlled_initial_states
            _,origin=controlled_initial_states(seed,profile)
            explicit={"kind":"explicit_initial_states","suitability":"acceptance_only","thermal_sampler_used":False,
                      "initial_state_sha256":origin["initial_state_sha256"],"particle_count":initial}
            if (metadata.get("suitability")!="acceptance_only" or metadata.get("controlled_input_origin")!=origin
                    or metadata.get("input_origin")!=explicit):raise ValueError()
    except (ValueError,KeyError,TypeError,AttributeError) as error:
        _raise("input_metadata_mismatch",error)


def validate_final_input_result_bytes(
    manifest_bytes: bytes,
    locked_nominals_bytes: bytes,
    submission_bytes: bytes,
    result_files: Mapping[str, bytes],
    *,
    project_directory: str,
    campaign_absolute_path: str,
) -> ValidatedFinalInputResults:
    from workflow_api.mot_3d_workload import policy

    profile = policy(_strict(manifest_bytes)) if type(manifest_bytes) is bytes else None
    initial_particles = (
        50000
        if profile is None
        else profile.policy["generation"]["zeeman_initial_particles"]
    )
    paths = (
        expected_paths(_strict(manifest_bytes))
        if type(manifest_bytes) is bytes
        else expected_paths()
    )
    if (
        type(manifest_bytes) is not bytes
        or type(locked_nominals_bytes) is not bytes
        or type(submission_bytes) is not bytes
        or not isinstance(result_files, Mapping)
        or set(result_files) != set(paths)
        or type(project_directory) is not str
        or type(campaign_absolute_path) is not str
    ):
        _raise("artifact_registry_mismatch")
    all_bytes = [
        manifest_bytes,
        locked_nominals_bytes,
        submission_bytes,
        *result_files.values(),
    ]
    if any(
        type(raw) is not bytes or not 0 < len(raw) <= MAX_FILE_BYTES
        for raw in all_bytes
    ):
        _raise("artifact_too_large")
    if sum(map(len, all_bytes)) > MAX_TOTAL_BYTES:
        _raise("artifact_too_large")
    manifest, locked, submission = map(
        _strict, (manifest_bytes, locked_nominals_bytes, submission_bytes)
    )
    name = manifest.get("name") if isinstance(manifest, dict) else None
    segment = "ui_acceptance/" if profile else ""
    expected_root = f"{project_directory}/data/optimization/mot_3d/{segment}{name}"
    logical_root = f"data/optimization/mot_3d/{segment}{name}"
    stage = manifest.get("stages", {}).get("final_validation_input_generation", {})
    if (
        type(name) is not str
        or not isinstance(stage, dict)
        or set(stage)
        != {
            "classification",
            "locked_nominals",
            "zeeman_seeds",
            "mot_seeds",
            "zeeman_job",
            "mot_job",
            "freeze_job",
            "input_manifest",
        }
        or campaign_absolute_path != expected_root
        or str(PurePosixPath(campaign_absolute_path)) != campaign_absolute_path
        or manifest.get("stage") != "final_validation_input_generation"
        or stage.get("classification") != "new_unopened_inputs_after_nominal_lock"
        or stage.get("zeeman_seeds") != list(ZEEMAN_SEEDS)
        or stage.get("mot_seeds") != list(MOT_SEEDS)
        or stage.get("locked_nominals")
        != f"{logical_root}/selection/locked_nominals.json"
        or stage.get("input_manifest")
        != f"{logical_root}/final_validation_inputs/input_manifest.json"
        or stage.get("zeeman_job")
        != f"{logical_root}/jobs/final_validation_inputs/01_generate_zeeman.pbs"
        or stage.get("mot_job")
        != f"{logical_root}/jobs/final_validation_inputs/02_generate_2d_survivors.pbs"
        or stage.get("freeze_job")
        != f"{logical_root}/jobs/final_validation_inputs/03_freeze_inputs.pbs"
    ):
        _raise("manifest_mismatch")
    if (
        not isinstance(locked, dict)
        or set(locked)
        != {
            "kind",
            "classification",
            "campaign_manifest_sha256_before_stage",
            "families",
            *({"acceptance", "suitability"} if profile else set()),
        }
        or (
            profile is not None
            and (
                locked.get("acceptance") != profile.provenance()
                or locked.get("suitability") != "acceptance_only"
            )
        )
        or locked.get("kind") != "mot_3d_locked_nominals"
        or locked.get("classification") != "locked_before_new_validation_inputs"
        or type(locked.get("campaign_manifest_sha256_before_stage")) is not str
        or HEX64.fullmatch(locked["campaign_manifest_sha256_before_stage"]) is None
        or not isinstance(locked.get("families"), dict)
        or set(locked["families"]) != set(FAMILIES)
        or any(
            not isinstance(locked["families"][family], dict)
            or set(locked["families"][family])
            != {
                "candidate_id",
                "parameters",
                "derived_parameters",
                "resolved_profile",
                "selection_summary_sha256",
            }
            or locked["families"][family].get("candidate_id")
            not in {f"{family}_finalist_0{index}" for index in range(1, 4)}
            or not isinstance(locked["families"][family].get("parameters"), dict)
            or not isinstance(
                locked["families"][family].get("derived_parameters"), dict
            )
            or not isinstance(locked["families"][family].get("resolved_profile"), dict)
            or type(locked["families"][family].get("selection_summary_sha256"))
            is not str
            or HEX64.fullmatch(locked["families"][family]["selection_summary_sha256"])
            is None
            for family in FAMILIES
        )
    ):
        _raise("manifest_mismatch")
    submission_keys = {
        "kind",
        "status",
        "submission_key",
        "nonce",
        "commit",
        "created_unix_s",
        "zeeman_array_job_id",
        "mot_array_job_id",
        "freeze_job_id",
    }
    if (
        not isinstance(submission, dict)
        or set(submission) != submission_keys
        or submission.get("kind") != "mot_3d_final_validation_input_submission"
        or submission.get("status") != "submitted"
        or type(submission.get("submission_key")) is not str
        or HEX64.fullmatch(submission["submission_key"]) is None
        or type(submission.get("nonce")) is not str
        or HEX32.fullmatch(submission["nonce"]) is None
        or submission.get("commit") != manifest.get("provenance", {}).get("git_commit")
        or type(submission.get("created_unix_s")) is not int
        or submission["created_unix_s"] < 0
        or type(submission.get("zeeman_array_job_id")) is not str
        or ARRAY_JOB.fullmatch(submission["zeeman_array_job_id"]) is None
        or type(submission.get("mot_array_job_id")) is not str
        or ARRAY_JOB.fullmatch(submission["mot_array_job_id"]) is None
        or type(submission.get("freeze_job_id")) is not str
        or SCALAR_JOB.fullmatch(submission["freeze_job_id"]) is None
        or len(
            {
                submission["zeeman_array_job_id"].split("[", 1)[0],
                submission["mot_array_job_id"].split("[", 1)[0],
                submission["freeze_job_id"].split(".", 1)[0],
            }
        )
        != 3
        or not (
            int(submission["zeeman_array_job_id"].split("[", 1)[0])
            < int(submission["mot_array_job_id"].split("[", 1)[0])
            < int(submission["freeze_job_id"].split(".", 1)[0])
        )
    ):
        _raise("submission_mismatch")
    hashes = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in result_files.items()
    }
    rows = []
    for zseed, mseed in zip(ZEEMAN_SEEDS, MOT_SEEDS):
        zbase = f"final_validation_inputs/after_zeeman/production_zeeman_n{initial_particles}_dt40us_seed{zseed}"
        mbase = f"final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed{zseed}_mot_seed{mseed}"
        rpath = (
            f"final_validation_inputs/mot_2d_records/replicates/zeeman_seed{zseed}.json"
        )
        za = _array(result_files[f"{zbase}.npy"])
        ma = _array(result_files[f"{mbase}.npy"])
        zm, mm, replicate = map(
            _strict,
            (
                result_files[f"{zbase}.json"],
                result_files[f"{mbase}.json"],
                result_files[rpath],
            ),
        )
        expected_parameters = manifest.get("upstream_2d_campaign", {}).get(
            "expected_survivor_parameters"
        )
        expected_design = manifest.get("upstream_2d_campaign", {}).get(
            "expected_survivor_design"
        )
        survivor_keys = {
            "kind",
            "zeeman_seed",
            "mot_seed",
            "parameters",
            "design",
            "source_zeeman_ensemble",
            "shape",
            "output_sha256",
            "n_input", "n_survivors", "state_layout", "dtype",
        }
        replicate_keys = {"kind", "parameters", "design", "replicate"}
        if any(not isinstance(item,dict) for item in (zm,mm,replicate)):
            _raise("input_metadata_mismatch")
        if profile:
            if any(
                item.get("acceptance") != profile.provenance()
                for item in (zm, mm, replicate)
            ):
                _raise("input_metadata_mismatch")
            survivor_keys.add("acceptance")
            replicate_keys.add("acceptance")
        expected_profile = (
            expected_design.get("zeeman_profile")
            if isinstance(expected_design, dict)
            else None
        )
        _validate_current_zeeman(zm,za,seed=zseed,initial=initial_particles,
            npools=profile.policy["generation"]["jobs"]["zeeman"]["npools"] if profile else 200,
            profile=profile,basename=PurePosixPath(zbase).name+".npy",output_hash=hashes[f"{zbase}.npy"],
            commit=manifest.get("provenance",{}).get("git_commit"))
        if (
            expected_profile != zm["parameters"]["resolved_zeeman_magnet_profile"]
            or not isinstance(mm, dict)
            or set(mm) != survivor_keys
            or mm.get("kind") != "mot_2d_final_survivor_ensemble"
            or type(mm.get("zeeman_seed")) is not int
            or mm.get("zeeman_seed") != zseed
            or type(mm.get("mot_seed")) is not int
            or mm.get("mot_seed") != mseed
            or mm.get("parameters") != expected_parameters
            or not isinstance(mm.get("design"), dict)
            or set(mm["design"])
            != {
                "dt_s",
                "stochastic_solver",
                "uses_all_available_particles",
                "npools",
                "ensemble_dir",
                "zeeman_profile",
                "git_commit",
                "laboratory_spec_version",
                "laboratory_spec_sha256",
                "zeeman_profile_sha256",
                *({"acceptance"} if profile else set()),
            }
            or (
                profile is not None
                and mm["design"].get("acceptance") != profile.provenance()
            )
            or mm["design"].get("stochastic_solver")
            != expected_design.get("stochastic_solver")
            or mm["design"].get("zeeman_profile") != expected_profile
            or mm["design"].get("git_commit")
            != manifest.get("provenance", {}).get("git_commit")
            or mm["design"].get("laboratory_spec_sha256")
            != zm.get("laboratory_spec_sha256")
            or mm["design"].get("zeeman_profile_sha256")
            != zm.get("zeeman_profile_sha256")
            or type(mm["design"].get("ensemble_dir")) is not str
            or mm["design"].get("ensemble_dir") not in {
                f"{expected_root}/final_validation_inputs/after_zeeman",
                f"{logical_root}/final_validation_inputs/after_zeeman",
            }
            or mm["design"].get("dt_s")
            != MOT_2D_SIM_CONFIG["dt_s"]
            or mm["design"].get("uses_all_available_particles") is not True
            or type(mm["design"].get("npools")) is not int
            or mm["design"].get("npools")
            != (
                profile.policy["generation"]["jobs"]["mot_2d"]["npools"]
                if profile
                else 200
            )
            or mm["design"].get("laboratory_spec_version") != zm["laboratory_spec_version"]
            or type(mm.get("n_input")) is not int or mm["n_input"] != len(za)
            or type(mm.get("n_survivors")) is not int or mm["n_survivors"] != len(ma)
            or len(ma)>len(za)
            or mm.get("state_layout") != ["x_m","y_m","z_m","vx_m_s","vy_m_s","vz_m_s"]
            or mm.get("dtype") != "float64"
            or not _shape_matches(mm.get("shape"),ma)
            or mm.get("output_sha256") != hashes[f"{mbase}.npy"]
            or not any(_canonical_path(mm.get("source_zeeman_ensemble"),value) for value in (
                f"{expected_root}/{zbase}.npy",f"{logical_root}/{zbase}.npy",PurePosixPath(zbase).name+".npy"))
            or not isinstance(replicate, dict)
            or set(replicate) != replicate_keys
            or replicate.get("kind") != "mot_2d_final_production_replicate"
            or replicate.get("parameters") != expected_parameters
            or replicate.get("design") != mm.get("design")
            or not isinstance(replicate.get("replicate"), dict)
            or set(replicate["replicate"])
            != {"ensemble_file","zeeman_seed","mot_seed","n_available","selection_method","subset_seed","n_input","captured","conditional_efficiency","estimated_total_efficiency","batch_elapsed_seconds"}
            or type(replicate["replicate"].get("zeeman_seed")) is not int
            or replicate.get("replicate", {}).get("zeeman_seed") != zseed
            or type(replicate["replicate"].get("mot_seed")) is not int
            or replicate.get("replicate", {}).get("mot_seed") != mseed
            or type(replicate["replicate"].get("captured")) is not int
            or replicate["replicate"].get("captured") != len(ma)
            or type(replicate["replicate"].get("n_input")) is not int
            or replicate["replicate"].get("n_input") != len(za)
            or type(replicate["replicate"].get("n_available")) is not int
            or replicate["replicate"].get("n_available") != len(za)
            or replicate["replicate"].get("selection_method") != "all_particles"
            or type(replicate["replicate"].get("subset_seed")) is not int
            or replicate["replicate"].get("subset_seed") != 100000+zseed
            or type(replicate["replicate"].get("conditional_efficiency")) is not float
            or replicate["replicate"].get("conditional_efficiency") != len(ma)/len(za)
            or type(replicate["replicate"].get("estimated_total_efficiency")) is not float
            or replicate["replicate"].get("estimated_total_efficiency") != (len(ma)/len(za))*(len(za)/initial_particles)
            or type(replicate["replicate"].get("batch_elapsed_seconds")) not in {int,float}
            or not np.isfinite(replicate["replicate"].get("batch_elapsed_seconds"))
            or replicate["replicate"].get("batch_elapsed_seconds") < 0
            or not _canonical_path(
                replicate.get("replicate", {}).get("ensemble_file"),
                PurePosixPath(zbase).name+".npy",
            )
        ):
            _raise("input_metadata_mismatch")
        rows.append(
            {
                "zeeman_seed": zseed,
                "mot_seed": mseed,
                "path": f"{expected_root}/{mbase}.npy",
                "metadata_path": f"{expected_root}/{mbase}.json",
                "sha256": hashes[f"{mbase}.npy"],
                "metadata_sha256": hashes[f"{mbase}.json"],
                "replicate_path": f"{expected_root}/{rpath}",
                "replicate_sha256": hashes[rpath],
                "zeeman_path": f"{expected_root}/{zbase}.npy",
                "zeeman_sha256": hashes[f"{zbase}.npy"],
                "zeeman_metadata_path": f"{expected_root}/{zbase}.json",
                "zeeman_metadata_sha256": hashes[f"{zbase}.json"],
                "shape": list(ma.shape),
                "n_survivors": len(ma),
            }
        )
    inputs = _strict(result_files["final_validation_inputs/input_manifest.json"])
    if (
        not isinstance(inputs, dict)
        or set(inputs)
        != {
            "kind",
            "classification",
            "locked_nominals_sha256",
            "solver",
            "campaign_name",
            "git_commit",
            "physical_model_sha256",
            "generation_submission_sha256",
            "generation_jobs",
            "ensembles",
            "total_survivors",
            *({"acceptance", "suitability"} if profile else set()),
        }
        or (
            profile is not None
            and (
                inputs.get("acceptance") != profile.provenance()
                or inputs.get("suitability") != "acceptance_only"
            )
        )
        or inputs.get("kind") != "mot_3d_final_validation_inputs"
        or inputs.get("classification") != "newly_generated_sealed_after_nominal_lock"
        or inputs.get("locked_nominals_sha256")
        != hashlib.sha256(locked_nominals_bytes).hexdigest()
        or inputs.get("campaign_name") != name
        or inputs.get("git_commit") != manifest.get("provenance", {}).get("git_commit")
        or inputs.get("physical_model_sha256")
        != manifest.get("provenance", {}).get("physical_model_sha256")
        or inputs.get("solver") != manifest.get("design", {}).get("solver")
        or inputs.get("generation_submission_sha256")
        != hashlib.sha256(submission_bytes).hexdigest()
        or inputs.get("generation_jobs") != submission
        or inputs.get("ensembles") != rows
        or inputs.get("total_survivors") != sum(row["n_survivors"] for row in rows)
    ):
        _raise("input_manifest_mismatch")
    evidence = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ValidatedFinalInputResults(paths, hashes, inputs, evidence)

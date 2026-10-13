import json
import hashlib
import inspect
import shlex
import subprocess
import sys
import threading
import numpy as np
import pytest
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    LABORATORY_PHYSICAL_SPECIFICATION,
)
from pathlib import Path
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from workflow_api.server import ReadOnlyWorkflowHandler, workflow_catalog_payload
import workflow_api.server as server_module
from workflow_api.mot_2d_validation import modern_contract, validated_progress
from workflow_api.discovery import (
    DiscoveryError,
    _modern_3d_contract,
    _progress_aware_plan,
    list_campaigns,
)
from workflow_api.mot_3d_provenance import input_registry_digest
from workflow_api.error_catalog import ERROR_DOMAINS
from workflow_api.mot_2d_sources import list_sources
from workflow_api.mot_2d_plan import RELEVANT_FILES
from workflow_api.mot_3d_refinement_submission import Mot3DRefinementSubmissionError
from workflow_api.mot_3d_closure_submission import Mot3DClosureSubmissionError
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeus_transfer import ZeusPreparationError
from workflow_api.zeus_submission import ZeusSubmissionError
from workflow_api.zeus_screening import ZeusScreeningError
from workflow_api.zeus_screen_submission import ZeusScreenSubmissionError


def modern_2d_manifest(repository_root, name="modern", stage="smoke"):
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field_config = {
        key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")
    }
    roles = {
        "discovery": list(range(3000, 3005)),
        "refinement": list(range(3005, 3010)),
        "held_out_confirmation": list(range(3010, 3015)),
        "sealed_validation": list(range(3015, 3035)),
    }
    inputs = repository_root / "data" / "particle_states" / "after_zeeman" / "profile"
    inputs.mkdir(parents=True, exist_ok=True)
    frozen = {}
    for role, seeds in roles.items():
        frozen[role] = []
        for seed in seeds:
            state = inputs / f"input-{seed}.npy"
            metadata = state.with_suffix(".json")
            state.write_bytes(f"states-{seed}".encode())
            digest = hashlib.sha256(state.read_bytes()).hexdigest()
            metadata.write_text(
                json.dumps(
                    {
                        "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                        "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
                        "shape": [10, 6],
                        "dtype": "float64",
                        "n_survivors": 10,
                        "output_sha256": digest,
                        "parameters": {
                            "seed": seed,
                            "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                            "n_initial_atoms": 50000,
                            "dt_s": 4e-5,
                            "stochastic": True,
                            "collimation_angle_deg": 0.02,
                            "zeeman_field_config": field_config,
                        },
                        "software": {"git_commit": "source"},
                    }
                )
            )
            metadata_digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
            frozen[role].append(
                {
                    "zeeman_seed": seed,
                    "path": str(state.relative_to(repository_root)),
                    "metadata_path": str(metadata.relative_to(repository_root)),
                    "sha256": digest,
                    "metadata_sha256": metadata_digest,
                    "shape": [10, 6],
                    "dtype": "float64",
                    "survivor_count": 10,
                    "zeeman_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                    "source_git_commit": "source",
                    "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                    "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                    "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
                    "generation": {
                        "n_initial_atoms": 50000,
                        "dt_s": 4e-5,
                        "stochastic": True,
                        "collimation_angle_deg": 0.02,
                    },
                }
            )
    return {
        "kind": "mot_2d_s0_campaign",
        "name": name,
        "stage": stage,
        "s0_values": [1.3],
        "stages": {},
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/profile",
            "zeeman_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        },
        "seed_roles": roles,
        "input_ensembles": frozen,
        "mot_seeds": {
            role: [40000 + seed for seed in seeds] for role, seeds in roles.items()
        },
        "provenance": {
            "git_commit": "abc",
            "physical_model_sha256": "b" * 64,
            "hashed_files": ["config.py"],
            "capture_criterion_version": "v1",
            "path_contract": "repository-relative-v1",
        },
        "fixed_design": {
            "working_dt_s": 1.25e-6,
            "final_dt_s": 0.625e-6,
            "solver": "RK4StHybridCustom",
            "detuning_bounds_gamma": [-2, -0.5],
            "magnet_radius_bounds_m": [0.04, 0.05],
            "particle_counts": {},
            "trial_budgets": {"screen_per_worker": 17, "refine_per_worker": 10},
            "control_resolution": {},
            "stress_test_offsets": {},
        },
    }


def write_valid_smoke(campaign, manifest):
    directory = campaign / "smoke" / "s0_1p300000"
    (directory / "trials").mkdir(parents=True, exist_ok=True)
    s0 = 1.3
    design_input = {
        "fixed_s0": s0,
        "dt_s": 1.25e-6,
        "solver": "RK4StHybridCustom",
        "ensemble_dir": "data/particle_states/after_zeeman/profile",
        "zeeman_seeds": [3000],
        "mot_seeds": [43000],
        "particles_per_ensemble": 2,
        "sampler_seed": 42,
        "bounds": {
            "s0": [s0, s0],
            "detuning_gamma": [-2, -0.5],
            "magnet_radius_m": [0.04, 0.05],
        },
        "git_commit": "abc",
        "campaign_design_id": "b" * 64,
    }
    design_id = hashlib.sha256(
        json.dumps(design_input, sort_keys=True).encode()
    ).hexdigest()
    (directory / "trials" / "trial_0000.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_joint_optimization_trial",
                "trial_number": 0,
                "parameters": {
                    "s0": s0,
                    "detuning_gamma": -1.0,
                    "magnet_radius": 0.046,
                },
                "design": {
                    "dt_s": 1.25e-6,
                    "n_ensembles": 1,
                    "particles_per_ensemble": 2,
                    "mot_seed_start": 4000,
                    "stochastic_solver": "RK4StHybridCustom",
                    "design_id": design_id,
                    "git_commit": "abc",
                    "ensemble_dir": design_input["ensemble_dir"],
                    "zeeman_seeds": [3000],
                    "mot_seeds": [43000],
                },
            }
        )
    )
    (directory / "summary.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_joint_optimization_summary",
                "fixed_s0": s0,
                "n_finished_trials": 1,
                "design": {"stochastic_solver": "RK4StHybridCustom", "dt_s": 1.25e-6},
            }
        )
    )


def test_modern_contract_rejects_noncanonical_seeds_and_metadata_mismatch(tmp_path):
    root = tmp_path / "repo"
    manifest = modern_2d_manifest(root)
    assert modern_contract(manifest, root) == (True, ())

    manifest["seed_roles"]["discovery"][0] = 2999
    trusted, errors = modern_contract(manifest, root)
    assert not trusted
    assert any("canonical frozen set" in message for message in errors)

    manifest = modern_2d_manifest(root)
    metadata_path = root / manifest["input_ensembles"]["discovery"][0]["metadata_path"]
    metadata = json.loads(metadata_path.read_text())
    metadata["parameters"]["resolved_zeeman_magnet_profile"] = "wrong"
    metadata_path.write_text(json.dumps(metadata))
    trusted, errors = modern_contract(manifest, root)
    assert not trusted
    assert any("provenance does not match" in message for message in errors)


def test_pre_c2_corrected_campaign_is_validated_in_memory_without_rewrite(tmp_path):
    root = tmp_path / "repo"
    manifest = modern_2d_manifest(root)
    laboratory_keys = (
        "laboratory_spec_version",
        "laboratory_spec_sha256",
        "zeeman_profile_sha256",
    )
    for key in laboratory_keys:
        manifest["ensemble_source"].pop(key)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    arrays = {
        key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")
    }
    for records in manifest["input_ensembles"].values():
        for record in records:
            for key in laboratory_keys:
                record.pop(key)
            metadata_path = root / record["metadata_path"]
            metadata = json.loads(metadata_path.read_text())
            for key in laboratory_keys:
                metadata.pop(key)
            metadata["parameters"]["zeeman_field_config"] = arrays
            metadata_path.write_text(json.dumps(metadata))
            record["metadata_sha256"] = hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest()
    before = json.dumps(manifest, sort_keys=True).encode()
    assert modern_contract(manifest, root) == (True, ())
    assert json.dumps(manifest, sort_keys=True).encode() == before


def test_smoke_requires_genuine_trial_identity(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root)
    write_valid_smoke(campaign, manifest)
    assert validated_progress(campaign, manifest)[0].status == "complete"

    trial = campaign / "smoke/s0_1p300000/trials/trial_0000.json"
    payload = json.loads(trial.read_text())
    payload["design"]["mot_seeds"] = [999]
    trial.write_text(json.dumps(payload))
    assert validated_progress(campaign, manifest)[0].status == "inconsistent"


def test_duplicate_confirmation_and_production_tasks_are_inconsistent(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root)
    manifest["stage"] = "production"
    manifest["stages"] = {
        "confirmation": {"tasks": 2},
        "production": {"tasks": 2},
    }
    confirmation = campaign / "confirmation"
    production = campaign / "production"
    confirmation.mkdir()
    production.mkdir()
    duplicate_confirmation = {"s0": 1.3, "candidate_index": 0, "parameters": {}}
    (confirmation / "tasks.json").write_text(
        json.dumps([duplicate_confirmation, duplicate_confirmation])
    )
    duplicate_production = {
        "s0": 1.3,
        "zeeman_seed": 3015,
        "mot_seed": 43015,
        "parameters": {},
    }
    (production / "tasks.json").write_text(
        json.dumps([duplicate_production, duplicate_production])
    )

    progress = {row.stage: row for row in validated_progress(campaign, manifest)}
    assert progress["confirmation"].status == "inconsistent"
    assert progress["production"].status == "inconsistent"


def test_malformed_3d_sibling_is_isolated_from_valid_listing(tmp_path):
    root = tmp_path / "repo"
    valid = root / "data/optimization/mot_2d/valid"
    valid.mkdir(parents=True)
    (valid / "campaign.json").write_text(json.dumps(modern_2d_manifest(root)))
    malformed = root / "data/optimization/mot_3d/malformed"
    malformed.mkdir(parents=True)
    (malformed / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_campaign_v2",
                "name": "bad",
                "stage": "dt_validation_required",
                "provenance": {"git_commit": "abc", "physical_model_sha256": "a" * 64},
                "design": {"families": 3, "solver": "RK4StHybridCustom"},
            }
        )
    )

    result = list_campaigns(root)
    assert [row["name"] for row in result["campaigns"]] == ["modern"]
    assert result["invalid_count"] == 1


def test_legacy_2d_campaign_is_inspectable_but_cannot_prepare_remote_work(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/legacy"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root, name="legacy")
    manifest["provenance"].pop("path_contract")
    (campaign / "campaign.json").write_text(json.dumps(manifest))

    result = list_campaigns(root)

    assert result["invalid_count"] == 0
    assert result["total"] == 1
    record = result["campaigns"][0]
    assert record["name"] == "legacy"
    assert record["trust"] == "legacy-incomplete"
    assert record["remote_preparation"] == {
        "status": "legacy-local-only",
        "reason_code": "absolute-input-paths",
    }
    assert record["next_plan"] is None


def test_explicit_portable_2d_campaign_with_invalid_path_is_unavailable(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/incomplete-portability"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root, name="incomplete portability")
    manifest["ensemble_source"]["directory"] = "../../outside-repository"
    (campaign / "campaign.json").write_text(json.dumps(manifest))

    result = list_campaigns(root)

    assert result["invalid_count"] == 0
    assert result["total"] == 1
    record = result["campaigns"][0]
    assert record["name"] == "incomplete portability"
    assert record["trust"] == "legacy-incomplete"
    assert record["remote_preparation"] == {
        "status": "unavailable",
        "reason_code": "incomplete-portability-record",
    }
    assert record["next_plan"] is None


def test_progress_aware_plan_never_resubmits_partial_stage(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    summary = {
        "stage": "screen",
        "next_plan": {"label": "Submit", "command": ["qsub", "job.pbs"]},
    }
    assert (
        _progress_aware_plan(
            summary, [{"stage": "screen", "status": "in-progress"}], campaign, root
        )
        is None
    )
    assert (
        _progress_aware_plan(
            summary, [{"stage": "screen", "status": "not-started"}], campaign, root
        )["operation_scope"]
        == "remote-submission"
    )
    complete = _progress_aware_plan(
        summary, [{"stage": "screen", "status": "complete"}], campaign, root
    )
    assert complete["operation_scope"] == "local-mutation"
    assert "advance" in complete["command"]


def test_progress_aware_plan_never_emits_a_2d_advance_for_3d(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_3d/current"
    campaign.mkdir(parents=True)
    assert (
        _progress_aware_plan(
            {"kind": "mot_3d_campaign_v2", "stage": "closure"},
            [{"stage": "closure", "status": "complete"}],
            campaign,
            root,
        )
        is None
    )


def current_3d_contract_fixture(root):
    upstream = root / "data/optimization/mot_2d/source"
    frozen = root / "data/particle_states/after_2d_mot/source"
    upstream.mkdir(parents=True)
    frozen.mkdir(parents=True)
    campaign_bytes, report_bytes = (
        b'{"kind":"mot_2d_s0_campaign"}',
        b'{"kind":"mot_2d_s0_campaign_final_report"}',
    )
    array_bytes, metadata_bytes = b"NUMPY", b'{"kind":"mot_2d_final_survivor_ensemble"}'
    (upstream / "campaign.json").write_bytes(campaign_bytes)
    (upstream / "final_report.json").write_bytes(report_bytes)
    (frozen / "input.npy").write_bytes(array_bytes)
    (frozen / "input.json").write_bytes(metadata_bytes)
    record = {
        "stage": "closure",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "design": {
            "families": ["angled_donut", "single_pass"],
            "solver": "RK4StHybridCustom",
            "screening_dt_s": 1e-5,
            "production_dt_s": 0.625e-6,
            "timestep_status": "pragmatic_user_approved_not_converged",
            "optimization_bounds": {},
            "selection_statistics": {},
        },
        "upstream_2d_campaign": {
            "campaign_path": "data/optimization/mot_2d/source/campaign.json",
            "campaign_sha256": hashlib.sha256(campaign_bytes).hexdigest(),
            "final_report_path": "data/optimization/mot_2d/source/final_report.json",
            "final_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "sealed_seed_pairs": [
                {"zeeman_seed": seed, "mot_seed": 40000 + seed}
                for seed in range(3015, 3035)
            ],
            "expected_survivor_design": {"solver": "RK4StHybridCustom"},
            "expected_survivor_parameters": {"s0": 1.3},
        },
        "input_roles": {},
        "stages": {
            "closure": {"classification": "candidate_selection_not_final_validation"}
        },
    }
    for role, seeds in {
        "discovery": range(3015, 3027),
        "refinement": range(3027, 3031),
        "preliminary_check": range(3031, 3035),
    }.items():
        records = []
        for seed in seeds:
            array_path = frozen / f"input_{seed}.npy"
            metadata_path = frozen / f"input_{seed}.json"
            array_path.write_bytes(array_bytes)
            current_metadata = json.dumps(
                {
                    "kind": "mot_2d_final_survivor_ensemble",
                    "zeeman_seed": seed,
                    "mot_seed": 40000 + seed,
                    "shape": [1, 6],
                    "dtype": "float64",
                    "n_survivors": 1,
                },
                sort_keys=True,
            ).encode()
            metadata_path.write_bytes(current_metadata)
            records.append(
                {
                    "path": array_path.relative_to(root).as_posix(),
                    "metadata_path": metadata_path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(array_bytes).hexdigest(),
                    "metadata_sha256": hashlib.sha256(current_metadata).hexdigest(),
                    "shape": [1, 6],
                    "dtype": "float64",
                    "n_survivors": 1,
                    "zeeman_seed": seed,
                    "mot_seed": 40000 + seed,
                    "source_design": {"solver": "RK4StHybridCustom"},
                    "source_parameters": {"s0": 1.3},
                }
            )
        record["input_roles"][role] = records
    digest = input_registry_digest(record["input_roles"])
    record["design"]["timestep_evidence"] = {
        "source_handoff": {
            "campaign_sha256": record["upstream_2d_campaign"]["campaign_sha256"],
            "final_report_sha256": record["upstream_2d_campaign"][
                "final_report_sha256"
            ],
            "input_registry_sha256": digest,
        }
    }
    return record


def test_current_3d_contract_has_no_obsolete_unconditional_blocker(tmp_path):
    record = current_3d_contract_fixture(tmp_path)
    ok, errors = _modern_3d_contract(
        record,
        [
            {"stage": "dt_validation", "status": "complete"},
            {"stage": "closure", "status": "not-started"},
        ],
        tmp_path,
    )
    assert ok, errors


@pytest.mark.parametrize(
    "mutation",
    [
        "upstream_hash",
        "upstream_bytes",
        "upstream_traversal",
        "upstream_symlink",
        "report_hash",
        "report_bytes",
        "report_traversal",
        "report_symlink",
        "array_hash",
        "array_bytes",
        "array_traversal",
        "array_symlink",
        "metadata_hash",
        "metadata_bytes",
        "metadata_traversal",
        "metadata_symlink",
        "registry",
        "role_order",
        "seed_pair",
        "extra_pair",
        "reordered_pairs",
        "duplicate_pair",
        "source_design",
        "source_parameters",
        "metadata_record",
    ],
)
def test_current_3d_contract_rejects_forged_or_unsafe_frozen_identity(
    tmp_path, mutation
):
    record = current_3d_contract_fixture(tmp_path)
    frozen = record["input_roles"]["discovery"][0]
    upstream = record["upstream_2d_campaign"]
    if mutation == "upstream_hash":
        upstream["campaign_sha256"] = "0" * 64
    elif mutation == "upstream_bytes":
        (tmp_path / upstream["campaign_path"]).write_bytes(b"changed")
    elif mutation == "upstream_traversal":
        upstream["campaign_path"] = "../outside.json"
    elif mutation == "upstream_symlink":
        target = tmp_path / upstream["campaign_path"]
        replacement = tmp_path / "upstream.json"
        replacement.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(replacement)
    elif mutation == "report_hash":
        upstream["final_report_sha256"] = "0" * 64
    elif mutation == "report_bytes":
        (tmp_path / upstream["final_report_path"]).write_bytes(b"changed")
    elif mutation == "report_traversal":
        upstream["final_report_path"] = "../outside.json"
    elif mutation == "report_symlink":
        target = tmp_path / upstream["final_report_path"]
        replacement = tmp_path / "report.json"
        replacement.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(replacement)
    elif mutation == "array_hash":
        frozen["sha256"] = "0" * 64
    elif mutation == "array_bytes":
        (tmp_path / frozen["path"]).write_bytes(b"changed")
    elif mutation == "array_traversal":
        frozen["path"] = "../outside.npy"
    elif mutation == "array_symlink":
        target = tmp_path / frozen["path"]
        replacement = tmp_path / "replacement.npy"
        replacement.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(replacement)
    elif mutation == "metadata_hash":
        frozen["metadata_sha256"] = "0" * 64
    elif mutation == "metadata_bytes":
        (tmp_path / frozen["metadata_path"]).write_bytes(b"changed")
    elif mutation == "metadata_traversal":
        frozen["metadata_path"] = "../outside.json"
    elif mutation == "metadata_symlink":
        target = tmp_path / frozen["metadata_path"]
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(replacement)
    elif mutation == "registry":
        record["design"]["timestep_evidence"]["source_handoff"][
            "input_registry_sha256"
        ] = ("0" * 64)
    elif mutation == "role_order":
        record["input_roles"]["discovery"].reverse()
    elif mutation == "seed_pair":
        upstream["sealed_seed_pairs"][0]["mot_seed"] += 1
    elif mutation == "extra_pair":
        upstream["sealed_seed_pairs"].append({"zeeman_seed": 3035, "mot_seed": 43035})
    elif mutation == "reordered_pairs":
        upstream["sealed_seed_pairs"].reverse()
    elif mutation == "duplicate_pair":
        upstream["sealed_seed_pairs"][1] = dict(upstream["sealed_seed_pairs"][0])
    elif mutation in {"source_design", "source_parameters"}:
        frozen[mutation] = {"forged": True}
        record["design"]["timestep_evidence"]["source_handoff"][
            "input_registry_sha256"
        ] = input_registry_digest(record["input_roles"])
    else:
        path = tmp_path / frozen["metadata_path"]
        metadata = json.loads(path.read_text())
        metadata["n_survivors"] = 2
        path.write_text(json.dumps(metadata, sort_keys=True))
        frozen["metadata_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["design"]["timestep_evidence"]["source_handoff"][
            "input_registry_sha256"
        ] = input_registry_digest(record["input_roles"])
    ok, errors = _modern_3d_contract(
        record,
        [
            {"stage": "dt_validation", "status": "complete"},
            {"stage": "closure", "status": "not-started"},
        ],
        tmp_path,
    )
    assert not ok
    assert errors


def write_zeeman_source(root, name="source"):
    directory = root / "data/particle_states/after_zeeman" / name
    directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field_config = {
        key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")
    }
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.zeros((2, 6), dtype=float))
        digest = hashlib.sha256(state.read_bytes()).hexdigest()
        state.with_suffix(".json").write_text(
            json.dumps(
                {
                    "shape": [2, 6],
                    "dtype": "float64",
                    "n_survivors": 2,
                    "output_sha256": digest,
                    "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                    "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                    "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
                    "parameters": {
                        "seed": seed,
                        "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                        "n_initial_atoms": 50000,
                        "dt_s": 4e-5,
                        "zeeman_field_config": field_config,
                    },
                    "software": {"git_commit": "abc"},
                }
            )
        )
    return directory


def test_zeeman_source_registry_requires_all_valid_frozen_inputs(tmp_path):
    root = tmp_path / "repo"
    directory = write_zeeman_source(root)
    result = list_sources(root)
    assert result["total"] == 1
    assert result["sources"][0]["ensemble_count"] == 35
    assert result["sources"][0]["path"] == "data/particle_states/after_zeeman/source"
    (directory / "production_zeeman_n50000_dt40us_seed3010.json").unlink()
    result = list_sources(root)
    assert result == {"sources": [], "invalid_count": 1, "total": 0}


def test_zeeman_source_registry_rejects_laboratory_hash_tampering(tmp_path):
    root = tmp_path / "repo"
    directory = write_zeeman_source(root)
    metadata = directory / "production_zeeman_n50000_dt40us_seed3000.json"
    payload = json.loads(metadata.read_text())
    payload["laboratory_spec_sha256"] = "0" * 64
    metadata.write_text(json.dumps(payload))
    assert list_sources(root) == {"sources": [], "invalid_count": 1, "total": 0}


@contextmanager
def running_server(
    request_count=2,
    repository_root=None,
    creation_service=None,
    zeus_service=None,
    transfer_service=None,
    submission_service=None,
    screening_service=None,
    screen_submission_service=None,
    mot_3d_bootstrap_service=None,
    mot_3d_discovery_submission_service=None,
    mot_3d_discovery_transition_service=None,
    mot_3d_preliminary_submission_service=None,
    mot_3d_refinement_submission_service=None,
    mot_3d_closure_submission_service=None,
    mot_3d_preliminary_transition_service=None,
    mot_3d_refinement_transition_service=None,
    mot_3d_closure_transition_service=None,
    mot_3d_final_validation_completion_service=None,
):
    handler = type("TestHandler", (ReadOnlyWorkflowHandler,), {})
    handler.sessions = {}
    handler.sessions = {}
    handler.creation_service = creation_service
    handler.zeus_service = zeus_service
    handler.transfer_service = transfer_service
    handler.submission_service = submission_service
    handler.screening_service = screening_service
    handler.screen_submission_service = screen_submission_service
    handler.mot_3d_bootstrap_service = mot_3d_bootstrap_service
    handler.mot_3d_discovery_submission_service = mot_3d_discovery_submission_service
    handler.mot_3d_discovery_transition_service = mot_3d_discovery_transition_service
    handler.mot_3d_preliminary_submission_service = (
        mot_3d_preliminary_submission_service
    )
    handler.mot_3d_refinement_submission_service = mot_3d_refinement_submission_service
    handler.mot_3d_closure_submission_service = mot_3d_closure_submission_service
    handler.mot_3d_preliminary_transition_service = (
        mot_3d_preliminary_transition_service
    )
    handler.mot_3d_refinement_transition_service = mot_3d_refinement_transition_service
    handler.mot_3d_closure_transition_service = mot_3d_closure_transition_service
    handler.mot_3d_final_validation_completion_service = (
        mot_3d_final_validation_completion_service
    )
    if repository_root is not None:
        handler.repository_root = repository_root
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    server.block_on_close = False
    server.timeout = 2

    def handle_expected_requests():
        for _ in range(request_count):
            server.handle_request()

    thread = threading.Thread(target=handle_expected_requests, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        thread.join(timeout=5)
        server.server_close()


def request_json(url, *, method="GET", headers=None, request_target=None, body=None):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        connection.request(
            method, request_target or target, body=body, headers=headers or {}
        )
        response = connection.getresponse()
        raw = response.read()
        return response.status, response.headers, json.loads(raw) if raw else None
    finally:
        connection.close()


class _RefinementSubmissionFailure:
    def preview(self, payload, *, session_id):
        raise Mot3DRefinementSubmissionError("refinement_partial_submission")


def test_refinement_submission_subtype_uses_its_own_error_domain():
    service = _RefinementSubmissionFailure()
    with running_server(
        request_count=2, mot_3d_refinement_submission_service=service
    ) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-refinement/preview",
            method="POST",
            headers=trusted,
            body="{}",
        )
        expected = ERROR_DOMAINS["mot_3d_refinement_submission"].entries[
            "refinement_partial_submission"
        ]
        assert status == int(expected.status)
        assert payload["error"] == {
            "code": "refinement_partial_submission",
            "message": expected.message,
        }


class _ClosureSubmissionFailure:
    def preview(self, payload, *, session_id):
        raise Mot3DClosureSubmissionError("closure_partial_submission")


def test_closure_submission_subtype_uses_its_own_error_domain():
    service = _ClosureSubmissionFailure()
    with running_server(
        request_count=2, mot_3d_closure_submission_service=service
    ) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-closure/preview",
            method="POST",
            headers=trusted,
            body="{}",
        )
        expected = ERROR_DOMAINS["mot_3d_closure_submission"].entries[
            "closure_partial_submission"
        ]
        assert status == int(expected.status)
        assert payload["error"] == {
            "code": "closure_partial_submission",
            "message": expected.message,
        }


def test_local_server_catalog_uses_versioned_workflow_api():
    payload = workflow_catalog_payload()

    assert payload["api_version"] == 1
    assert {item["workflow_id"] for item in payload["data"]} >= {
        "mot_2d_fixed_s0",
        "mot_3d_optimization",
    }
    assert all(item["capabilities"] in (("inspect",), ()) for item in payload["data"])


def test_loopback_health_and_workflow_endpoints_are_read_only_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/health")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert payload == {"api_version": 1, "status": "ok"}

        status, headers, payload = request_json(f"{base_url}/api/workflows")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert payload["api_version"] == 1
        assert {row["workflow_id"] for row in payload["data"]} >= {
            "mot_2d_fixed_s0",
            "mot_3d_optimization",
        }


def test_loopback_unknown_and_mutating_requests_are_rejected_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/unknown")
        assert status == 404
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"error": {"code": "not_found", "message": "Not found."}}

        status, headers, payload = request_json(
            f"{base_url}/api/workflows", method="POST"
        )
        assert status == 405
        assert headers["Cache-Control"] == "no-store"
        assert headers["Allow"] == "GET, POST"
        assert payload == {
            "error": {
                "code": "method_not_allowed",
                "message": "This method is not available.",
            }
        }


def test_every_non_get_method_is_json_read_only_rejection():
    methods = ("PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
    with running_server(request_count=len(methods)) as base_url:
        for method in methods:
            status, headers, payload = request_json(
                f"{base_url}/api/workflows", method=method
            )
            assert status == 405
            assert headers["Cache-Control"] == "no-store"
            assert headers["X-Content-Type-Options"] == "nosniff"
            if method != "HEAD":
                assert payload["error"]["code"] == "method_not_allowed"


def test_host_query_and_absolute_targets_fail_closed():
    with running_server(request_count=3) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/health", headers={"Host": "evil.example"}
        )
        assert status == 400 and payload["error"]["code"] == "untrusted_host"
        status, _, payload = request_json(f"{base_url}/api/health?path=x")
        assert status == 400 and payload["error"]["code"] == "unsupported_query"
        status, _, payload = request_json(
            f"{base_url}/api/health", request_target="http://evil.example/api/health"
        )
        assert status == 400 and payload["error"]["code"] == "invalid_request_target"


def test_campaign_endpoints_discover_only_allowlisted_direct_manifests(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_2d" / "same-name-a"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "name": "same name",
                "stage": "complete",
                "s0_values": [1.3],
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "profile"},
            }
        )
    )
    second = campaign.parent / "same-name-b"
    second.mkdir()
    (second / "campaign.json").write_text((campaign / "campaign.json").read_text())
    nested = campaign.parent / "not-a-campaign" / "nested"
    nested.mkdir(parents=True)
    (nested / "campaign.json").write_text((campaign / "campaign.json").read_text())

    with running_server(request_count=2, repository_root=root) as base_url:
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns")
        assert status == 200
        rows = payload["data"]["campaigns"]
        assert len(rows) == 2
        assert rows[0]["id"] != rows[1]["id"]
        assert all(not row["path"].startswith("/") for row in rows)
        status, _, detail = request_json(f"{base_url}/api/v1/campaigns/{rows[0]['id']}")
        assert status == 200
        assert detail["data"]["scheduler_status"] == "unchecked"
        assert detail["data"]["trust"] == "legacy-incomplete"
        assert detail["data"]["scientific_role"] == "historical-evidence"
        assert detail["data"]["next_plan"] is None


def test_campaign_endpoint_rejects_encoded_or_unknown_ids(tmp_path):
    with running_server(request_count=2, repository_root=tmp_path) as base_url:
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/%252e%252e")
        assert status == 400
        assert payload["error"]["code"] == "invalid_campaign_id"
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/mot_2d-missing")
        assert status == 404
        assert payload["error"]["code"] == "campaign_not_found"


def test_every_catalogued_local_read_error_matches_the_real_handler(
    monkeypatch, tmp_path
):
    for case, spec in ERROR_DOMAINS["local_read"].entries.items():
        wire_code = spec.wire_code or case

        def fail(_root, _campaign_id, *, code=wire_code, message=spec.message):
            raise DiscoveryError(code, message)

        monkeypatch.setattr("workflow_api.server.get_campaign", fail)
        with running_server(request_count=1, repository_root=tmp_path) as base_url:
            status, headers, payload = request_json(
                f"{base_url}/api/v1/campaigns/catalog-case"
            )
        assert status == int(spec.status), case
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"error": {"code": wire_code, "message": spec.message}}, case


def test_unknown_local_read_error_fails_closed_without_leaking(monkeypatch, tmp_path):
    def fail(_root, _campaign_id):
        raise DiscoveryError("internal_secret_code", "secret /absolute/path")

    monkeypatch.setattr("workflow_api.server.get_campaign", fail)
    with running_server(request_count=1, repository_root=tmp_path) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/campaigns/catalog-case"
        )
    assert status == 500
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert payload == {
        "error": {
            "code": "inspection_failed",
            "message": "Campaign inspection failed safely.",
        }
    }
    serialized = json.dumps(payload)
    assert "internal_secret_code" not in serialized
    assert "secret" not in serialized
    assert "/absolute/path" not in serialized


def test_unexpected_discovery_error_returns_safe_json(monkeypatch):
    def fail(_root):
        raise OSError("secret /absolute/path")

    monkeypatch.setattr("workflow_api.server.list_campaigns", fail)
    with running_server(request_count=1) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/campaigns")
    assert status == 500
    assert headers["Cache-Control"] == "no-store"
    assert payload == {
        "error": {
            "code": "inspection_failed",
            "message": "Campaign inspection failed safely.",
        }
    }
    assert "/absolute/path" not in json.dumps(payload)


def test_validated_complete_stage_offers_copy_only_local_advance(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_2d" / "modern"
    smoke = campaign / "smoke" / "s0_1p300000"
    jobs = campaign / "jobs"
    smoke.mkdir(parents=True)
    jobs.mkdir()
    manifest = modern_2d_manifest(root)
    (campaign / "campaign.json").write_text(json.dumps(manifest))
    (jobs / "01_smoke.pbs").write_text("#!/bin/bash\n")
    write_valid_smoke(campaign, manifest)

    with running_server(request_count=2, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
        campaign_id = listing["data"]["campaigns"][0]["id"]
        status, _, detail = request_json(f"{base_url}/api/v1/campaigns/{campaign_id}")

    assert status == 200
    row = detail["data"]
    assert row["trust"] == "trusted-current"
    assert row["progress"][0]["status"] == "complete"
    assert row["next_plan"]["operation_scope"] == "local-mutation"
    assert row["next_plan"]["mode"] == "copy-only"
    assert "advance" in row["next_plan"]["command"]
    assert (
        shlex.split(row["next_plan"]["display_command"]) == row["next_plan"]["command"]
    )


def test_copy_command_shell_quotes_hostile_campaign_directory(tmp_path):
    root = tmp_path / "repo"
    campaign = (
        root
        / "data"
        / "optimization"
        / "mot_2d"
        / "name with spaces; $(unsafe) 'quote'"
    )
    smoke = campaign / "smoke" / "s0_1p300000"
    jobs = campaign / "jobs"
    smoke.mkdir(parents=True)
    jobs.mkdir()
    (campaign / "campaign.json").write_text(json.dumps(modern_2d_manifest(root)))
    (jobs / "01_smoke.pbs").write_text("#!/bin/bash\n")
    write_valid_smoke(campaign, modern_2d_manifest(root))

    with running_server(request_count=1, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
    plan = listing["data"]["campaigns"][0]["next_plan"]
    assert shlex.split(plan["display_command"]) == plan["command"]
    assert "'" in plan["display_command"]


def test_3d_structural_manifest_without_verified_frozen_artifacts_is_inspection_only(
    tmp_path,
):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_3d" / "structural-only"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_campaign_v2",
                "name": "structural only",
                "stage": "dt_validation_required",
                "provenance": {"git_commit": "abc", "physical_model_sha256": "a" * 64},
                "upstream_2d_campaign": {
                    "campaign_path": "fake",
                    "campaign_sha256": "b" * 64,
                    "final_report_path": "fake",
                    "final_report_sha256": "c" * 64,
                    "sealed_seed_pairs": [{"zeeman_seed": 3015, "mot_seed": 43015}],
                    "expected_survivor_design": {"solver": "RK4StHybridCustom"},
                    "expected_survivor_parameters": {"s0": 1.3},
                },
                "input_roles": {
                    "discovery": [
                        {
                            "path": "x",
                            "metadata_path": "y",
                            "sha256": "d" * 64,
                            "metadata_sha256": "e" * 64,
                            "shape": [1, 6],
                            "dtype": "float64",
                            "zeeman_seed": 3015,
                            "mot_seed": 43015,
                            "source_design": {},
                            "source_parameters": {},
                        }
                    ]
                },
                "design": {
                    "families": ["angled_donut", "single_pass"],
                    "solver": "RK4StHybridCustom",
                    "screening_dt_s": 1.25e-6,
                    "production_dt_s": 0.625e-6,
                    "timestep_status": "provisional_pending_3d_validation",
                    "optimization_bounds": {},
                    "selection_statistics": {},
                },
            }
        )
    )

    with running_server(request_count=1, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
    row = listing["data"]["campaigns"][0]
    assert row["trust"] == "legacy-incomplete"
    assert row["scientific_role"] == "historical-evidence"
    assert row["next_plan"] is None
    assert row["progress"] == []


def test_server_import_does_not_cross_the_simulation_or_study_boundary():
    code = (
        "import sys; import workflow_api.server; "
        "assert not any(name == 'simulations' or name.startswith('simulations.') "
        "or name == 'studies' or name.startswith('studies.') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_documented_development_command_starts_api_and_ui():
    package = json.loads(Path("ui/package.json").read_text())
    launcher = Path("ui/scripts/dev.mjs").read_text()
    assert package["scripts"]["dev"] == "node scripts/dev.mjs"
    assert '["-m", "workflow_api.server"]' in launcher
    assert '"vite.js"' in launcher
    assert "shell: true" not in launcher


class _FixedSnapshots:
    def capture(self):
        return RepositorySnapshot("a" * 40)


def _creation_service(root):
    write_zeeman_source(root)
    for relative in RELEVANT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    lab = root / "lab_setup/model.py"
    lab.parent.mkdir(exist_ok=True)
    lab.write_text("MODEL = 1")
    return CreationService(root, _FixedSnapshots())


def _session_headers(base_url, cookie, csrf):
    host = urlsplit(base_url).netloc
    return {
        "Content-Type": "application/json",
        "Origin": f"http://{host}",
        "Sec-Fetch-Site": "same-origin",
        "X-CSRF-Token": csrf,
        "Cookie": cookie,
    }


def test_creation_requires_same_origin_csrf_and_confirm_is_local_only(tmp_path):
    root = tmp_path / "repo"
    service = _creation_service(root)
    with running_server(
        request_count=5, repository_root=root, creation_service=service
    ) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        csrf = payload["data"]["csrf_token"]
        body = json.dumps(
            {
                "name": "Fixed s0 1.3",
                "slug": "s0_1p3",
                "source_id": list_sources(root)["sources"][0]["id"],
                "s0_values": [1.3],
            }
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/2d/preview",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        trusted = _session_headers(base_url, cookie, csrf)
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/2d/preview",
            method="POST",
            headers=trusted,
            body=body,
        )
        assert status == 200 and payload["data"]["preview_token"]
        confirm = json.dumps({"preview_token": payload["data"]["preview_token"]})
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/2d/confirm",
            method="POST",
            headers=trusted,
            body=confirm,
        )
        assert status == 201
        assert payload["data"]["submitted_to_zeus"] is False
        status, _, replay = request_json(
            f"{base_url}/api/v1/campaigns/2d/confirm",
            method="POST",
            headers=trusted,
            body=confirm,
        )
        assert status == 201 and replay == payload


def test_creation_rejects_unknown_fields_and_oversized_body(tmp_path):
    root = tmp_path / "repo"
    service = _creation_service(root)
    with running_server(
        request_count=3, repository_root=root, creation_service=service
    ) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/2d/preview",
            method="POST",
            headers=trusted,
            body=json.dumps({"password": "never"}),
        )
        assert status == 400
        oversized_headers = {**trusted, "Content-Length": str(33 * 1024)}
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/2d/preview",
            method="POST",
            headers=oversized_headers,
            body="{}",
        )
        assert status == 413


def test_cross_site_request_cannot_allocate_creation_session(tmp_path):
    root = tmp_path / "repo"
    service = _creation_service(root)
    with running_server(
        request_count=2, repository_root=root, creation_service=service
    ) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200 and payload["data"]["csrf_token"]


class _FakeMot3DBootstrapService:
    def __init__(self):
        self.calls = []

    def status(self, payload):
        self.calls.append(("status", payload, None))
        if payload != {}:
            raise ValueError("invalid")
        return {
            "lifecycle": "ready",
            "sources": [],
            "reason": None,
            "evidence_requirement": None,
            "timestep_policy": {
                "status": "pragmatic_user_approved_after_inconclusive_study",
                "convergence_claim": "not_established",
                "sha256": "d" * 64,
            },
        }

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        raise ValueError("secret /private/path")

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        raise AssertionError("confirm should not be reached")


def test_mot_3d_bootstrap_http_boundary_is_session_bound_and_sanitized():
    service = _FakeMot3DBootstrapService()
    with running_server(request_count=4, mot_3d_bootstrap_service=service) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/3d/bootstrap/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body="{}",
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/3d/bootstrap/status",
            method="POST",
            headers=trusted,
            body="{}",
        )
        assert status == 200 and payload["data"]["lifecycle"] == "ready"
        status, _, payload = request_json(
            f"{base_url}/api/v1/campaigns/3d/bootstrap/preview",
            method="POST",
            headers=trusted,
            body=json.dumps({"source_id": "a" * 64, "campaign_name": "mot3d"}),
        )
        assert status == 412 and payload == {
            "error": {
                "code": "mot_3d_bootstrap_failed",
                "message": "3D campaign preparation stopped safely.",
            }
        }
        assert "/private/path" not in json.dumps(payload)


class _FakeMot3DDiscoverySubmissionService:
    def __init__(self):
        self.calls = []

    def status(self, payload):
        self.calls.append(("status", payload, None))
        return {
            "source": "zeus",
            "queried_at": "2026-10-11T00:00:00+00:00",
            "campaign": {"id": "campaign-id", "name": "mot3d", "stage": "discovery"},
            "submission": {
                "status": "not_submitted",
                "chain": {"angled_donut": [], "single_pass": []},
            },
            "next_action": "review_submission",
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        return {
            "preview_token": "token",
            "expires_in_seconds": 300,
            "campaign": {"id": "campaign-id", "name": "mot3d", "git_commit": "a" * 40},
            "stage": {"id": "discovery", "label": "Discovery"},
            "chain": {
                "families": [
                    {"id": "angled_donut", "rounds": 2},
                    {"id": "single_pass", "rounds": 3},
                ],
                "arrays": 5,
                "tasks_per_array": 3,
                "dependency": "afterok within each family",
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "effects": {
                "submit_discovery_chain": True,
                "submit_smoke": False,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        return {
            "status": "submitted",
            "campaign_id": "campaign-id",
            "stage": "discovery",
            "chain": {
                "angled_donut": ["1[].zeus-master", "2[].zeus-master"],
                "single_pass": [
                    "3[].zeus-master",
                    "4[].zeus-master",
                    "5[].zeus-master",
                ],
            },
            "submitted_at": "2026-10-11T00:00:00+00:00",
            "local_sync": {"status": "not_synchronized"},
        }


def test_mot_3d_discovery_submission_http_boundary_is_explicit_and_session_bound():
    service = _FakeMot3DDiscoverySubmissionService()
    with running_server(
        request_count=5, mot_3d_discovery_submission_service=service
    ) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-discovery/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-discovery/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert (
            status == 200 and payload["data"]["submission"]["status"] == "not_submitted"
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-discovery/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["effects"]["submit_smoke"] is False
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/mot-3d-discovery/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "token"}),
        )
        assert status == 201 and payload["data"]["chain"]["single_pass"] == [
            "3[].zeus-master",
            "4[].zeus-master",
            "5[].zeus-master",
        ]
    assert [call[0] for call in service.calls] == ["status", "preview", "confirm"]


class _FakeMot3DDiscoveryTransitionService:
    def __init__(self):
        self.calls = []

    def status(self, payload):
        self.calls.append(("status", payload, None))
        return {"source": "zeus"}

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        return {
            "preview_token": "token",
            "effects": {"submit_preliminary_check": False},
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        return {"status": "preliminary_check_prepared", "submitted_to_zeus": False}


def test_mot_3d_discovery_transition_http_boundary_is_explicit_and_session_bound():
    service = _FakeMot3DDiscoveryTransitionService()
    with running_server(
        request_count=5, mot_3d_discovery_transition_service=service
    ) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/discovery-transition/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, _ = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/discovery-transition/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/discovery-transition/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert (
            status == 200
            and payload["data"]["effects"]["submit_preliminary_check"] is False
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/discovery-transition/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "token"}),
        )
        assert status == 201 and payload["data"]["submitted_to_zeus"] is False
    assert [call[0] for call in service.calls] == ["status", "preview", "confirm"]


class _FakeMot3DPreliminaryTransitionService:
    def __init__(self):
        self.calls = []

    def status(self, payload):
        self.calls.append(("status", payload, None))
        return {"source": "zeus", "next_action": "review_transition"}

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        return {
            "preview_token": "token",
            "effects": {
                "synchronize_preliminary_check": True,
                "prepare_refinement": True,
                "submit_refinement": False,
            },
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        return {
            "status": "refinement_prepared",
            "submitted_to_zeus": False,
            "simulation_started": False,
        }


def test_mot_3d_preliminary_transition_http_boundary_is_explicit_and_session_bound():
    service = _FakeMot3DPreliminaryTransitionService()
    with running_server(
        request_count=5,
        mot_3d_preliminary_transition_service=service,
    ) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/preliminary-transition/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/preliminary-transition/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["next_action"] == "review_transition"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/preliminary-transition/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200
        assert payload["data"]["effects"]["submit_refinement"] is False
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/preliminary-transition/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "token"}),
        )
        assert status == 201
        assert payload["data"]["simulation_started"] is False
    assert [call[0] for call in service.calls] == ["status", "preview", "confirm"]


class _FakeMot3DRefinementTransitionService:
    def __init__(self):
        self.calls = []

    def status(self, payload):
        self.calls.append(("status", payload, None))
        return {"source": "zeus", "next_action": "review_transition"}

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        return {
            "preview_token": "token",
            "effects": {
                "synchronize_refinement": True,
                "prepare_closure": True,
                "submit_closure": False,
            },
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        return {
            "status": "closure_prepared",
            "submitted_to_zeus": False,
            "simulation_started": False,
        }


def test_mot_3d_refinement_transition_http_boundary_is_explicit_and_session_bound():
    service = _FakeMot3DRefinementTransitionService()
    with running_server(
        request_count=5,
        mot_3d_refinement_transition_service=service,
    ) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/refinement-transition/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/refinement-transition/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["next_action"] == "review_transition"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/refinement-transition/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["effects"]["submit_closure"] is False
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/refinement-transition/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "token"}),
        )
        assert status == 201 and payload["data"]["simulation_started"] is False
    assert [call[0] for call in service.calls] == ["status", "preview", "confirm"]


class _FakeMot3DClosureTransitionService:
    def status(self, payload):
        return {"source": "zeus", "next_action": "review_transition"}

    def preview(self, payload, *, session_id):
        return {"preview_token": "token", "effects": {"submit_finalists": False}}

    def confirm(self, payload, *, session_id):
        return {
            "status": "finalist_selection_prepared",
            "submitted_to_zeus": False,
            "simulation_started": False,
        }


def test_mot_3d_closure_transition_http_boundary_is_explicit_and_session_bound():
    with running_server(
        request_count=5,
        mot_3d_closure_transition_service=_FakeMot3DClosureTransitionService(),
    ) as base_url:
        session_status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert session_status == 200, payload
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/closure-transition/status",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/closure-transition/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["next_action"] == "review_transition"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/closure-transition/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["effects"]["submit_finalists"] is False
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/mot-3d/closure-transition/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "token"}),
        )
        assert (
            status == 201 and payload["data"]["status"] == "finalist_selection_prepared"
        )


class _FakeZeusService:
    def __init__(self):
        self.payload = None

    def snapshot(self, payload):
        ZeusProfile.parse(payload)
        self.payload = payload
        return {
            "connection_status": "connected",
            "profile": {
                "host": "zeus.technion.ac.il",
                "username": payload["username"],
                "project_directory": payload["project_directory"],
                "authentication": "ssh-key-or-agent",
            },
            "remote": {
                "project_directory": payload["project_directory"],
                "git_commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "scheduler": {
                "status": "available",
                "queried_at": "2026-10-08T00:00:00+00:00",
                "jobs": [],
            },
        }


class _FakeTransferService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        if set(payload) != {"campaign_id", "username", "project_directory"}:
            raise ZeusPreparationError("request_invalid")
        if self.error:
            raise self.error
        return {
            "preview_token": "review-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": payload["campaign_id"],
                "name": "Campaign",
                "path": "data/optimization/mot_2d/c",
                "git_commit": "a" * 40,
            },
            "destination": {
                "host": "zeus.technion.ac.il",
                "project_directory": payload["project_directory"],
                "campaign_directory": f'{payload["project_directory"]}/data/optimization/mot_2d/c',
            },
            "artifacts": {
                "ensemble_count": 35,
                "total_count": 72,
                "missing_count": 72,
                "identical_count": 0,
                "total_bytes": 100,
                "missing_bytes": 100,
            },
            "effects": {
                "copy_missing_only": True,
                "overwrite_existing": False,
                "submit_jobs": False,
                "run_simulation": False,
            },
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        if set(payload) != {"preview_token"}:
            raise ZeusPreparationError("request_invalid")
        if self.error:
            raise self.error
        return {
            "status": "prepared",
            "campaign_id": "mot_2d-id",
            "destination": "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/c",
            "transferred_count": 72,
            "reused_identical_count": 0,
            "bytes_transferred": 100,
            "submitted_to_zeus": False,
            "simulation_started": False,
        }


def test_zeus_snapshot_requires_explicit_same_origin_csrf_and_never_accepts_password():
    service = _FakeZeusService()
    with running_server(request_count=4, zeus_service=service) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        body = json.dumps(
            {
                "username": "tal.noa",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
            }
        )
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/snapshot",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/snapshot",
            method="POST",
            headers=trusted,
            body=body,
        )
        assert status == 200 and payload["data"]["connection_status"] == "connected"
        assert service.payload == {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/snapshot",
            method="POST",
            headers=trusted,
            body=json.dumps(
                {
                    "username": "tal.noa",
                    "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                    "password": "never",
                }
            ),
        )
        assert status == 400 and payload["error"]["code"] == "invalid_request"


def test_zeus_transfer_preview_and_confirm_require_session_csrf_and_never_submit():
    service = _FakeTransferService()
    with running_server(request_count=5, transfer_service=service) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        body = json.dumps(request)
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/preview",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/preview",
            method="POST",
            headers=trusted,
            body=body,
        )
        assert status == 200 and payload["data"]["effects"]["submit_jobs"] is False
        token = payload["data"]["preview_token"]
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": token}),
        )
        assert status == 201
        assert payload["data"]["submitted_to_zeus"] is False
        assert payload["data"]["simulation_started"] is False
        assert service.calls[0][1] == request
        assert service.calls[0][2] == service.calls[1][2]
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": token, "extra": True}),
        )
        assert status == 400 and payload["error"]["code"] == "request_invalid"


def test_zeus_transfer_unavailable_and_errors_are_sanitized():
    with running_server(request_count=1) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/preview",
            method="POST",
            headers={"Content-Type": "application/json"},
            body="{}",
        )
        assert status == 503 and payload["error"] == {
            "code": "zeus_preparation_unavailable",
            "message": "Zeus campaign preparation is unavailable.",
        }

    service = _FakeTransferService(ZeusPreparationError("remote_input_conflict"))
    with running_server(request_count=2, transfer_service=service) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 409
        assert payload["error"] == {
            "code": "remote_input_conflict",
            "message": "A required Zeus input differs from the frozen campaign input.",
        }


class _FakeSubmissionService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        if set(payload) != {"campaign_id", "username", "project_directory"}:
            raise ZeusSubmissionError("request_invalid")
        if self.error:
            raise self.error
        return {
            "preview_token": "submit-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": payload["campaign_id"],
                "name": "Campaign",
                "path": "data/optimization/mot_2d/c",
                "git_commit": "a" * 40,
                "s0_values": [1.3],
            },
            "stage": {
                "id": "smoke",
                "label": "Smoke check",
                "purpose": "Validate first.",
            },
            "job": {
                "file": "jobs/01_smoke.pbs",
                "kind": "job",
                "task_count": 1,
                "queue": "zeus_combined_q",
                "cores_per_task": 1,
                "memory_per_task_bytes": 68719476736,
                "walltime_seconds": 1200,
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": payload["project_directory"],
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "inputs": {"verified_count": 72, "status": "ready"},
            "effects": {
                "submit_smoke": True,
                "submit_later_stages": False,
                "modify_files": False,
            },
            "later_stages_locked": True,
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        if set(payload) != {"preview_token"}:
            raise ZeusSubmissionError("request_invalid")
        if self.error:
            raise self.error
        return {
            "status": "submitted",
            "campaign_id": "mot_2d-id",
            "stage": "smoke",
            "job_id": "12345.zeus-master",
            "submitted_at": "2026-10-08T18:00:00+00:00",
            "later_stages_locked": True,
        }


def test_smoke_submission_endpoints_require_same_session_csrf_and_exact_payload():
    service = _FakeSubmissionService()
    with running_server(request_count=5, submission_service=service) as base_url:
        status, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert status == 200
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        preview_url = f"{base_url}/api/v1/zeus/submissions/smoke/preview"
        confirm_url = f"{base_url}/api/v1/zeus/submissions/smoke/confirm"
        status, _, payload = request_json(
            preview_url,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(request),
        )
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(
            preview_url, method="POST", headers=trusted, body=json.dumps(request)
        )
        assert status == 200 and payload["data"]["stage"]["id"] == "smoke"
        token = payload["data"]["preview_token"]
        status, _, payload = request_json(
            confirm_url,
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": token}),
        )
        assert status == 201 and payload["data"]["job_id"] == "12345.zeus-master"
        assert service.calls[0][2] == service.calls[1][2]
        status, _, payload = request_json(
            confirm_url,
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": token, "command": "qdel 1"}),
        )
        assert status == 400 and payload["error"]["code"] == "request_invalid"


def test_smoke_submission_unavailable_and_uncertain_errors_are_sanitized():
    with running_server(request_count=1) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/smoke/preview",
            method="POST",
            headers={"Content-Type": "application/json"},
            body="{}",
        )
        assert status == 503
        assert payload["error"] == {
            "code": "zeus_submission_unavailable",
            "message": "Zeus smoke submission is unavailable.",
        }

    for code, expected_message in (
        ("submission_outcome_unknown", "Automatic retry is blocked"),
        ("smoke_already_started", "outputs already exist"),
    ):
        service = _FakeSubmissionService(ZeusSubmissionError(code))
        with running_server(request_count=2, submission_service=service) as base_url:
            _, headers, payload = request_json(
                f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
            )
            trusted = _session_headers(
                base_url,
                headers["Set-Cookie"].split(";", 1)[0],
                payload["data"]["csrf_token"],
            )
            request = {
                "campaign_id": "mot_2d-id",
                "username": "tal.noa",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
            }
            status, _, payload = request_json(
                f"{base_url}/api/v1/zeus/submissions/smoke/preview",
                method="POST",
                headers=trusted,
                body=json.dumps(request),
            )
            assert status == 409
            assert payload["error"]["code"] == code
            assert expected_message in payload["error"]["message"]
            assert "/home/" not in payload["error"]["message"]


class _FakeScreeningService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def status(self, payload, *, session_id):
        self.calls.append(("status", payload, session_id))
        if self.error:
            raise self.error
        return {
            "source": "zeus",
            "queried_at": "2026-10-08T20:00:00+00:00",
            "campaign": {"id": "mot_2d-id", "name": "Campaign", "stage": "smoke"},
            "submission": {"job_id": "12345.zeus-master"},
            "scheduler": {
                "state": "completed_success",
                "raw_state": "F",
                "exit_status": 0,
            },
            "validation": {
                "status": "valid",
                "points": [{"s0": 1.3, "captured": 0, "input": 2, "efficiency": 0.0}],
                "artifact_count": 3,
            },
            "lifecycle": "ready_to_prepare_screen",
            "next_action": "review_screening_preparation",
        }

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        if self.error:
            raise self.error
        return {
            "preview_token": "screen-token",
            "expires_in_seconds": 300,
            "campaign": {"id": "mot_2d-id", "name": "Campaign", "git_commit": "a" * 40},
            "from_stage": "smoke",
            "to_stage": "screen",
            "smoke": {
                "job_id": "12345.zeus-master",
                "points": [{"s0": 1.3, "captured": 0, "input": 2, "efficiency": 0.0}],
                "artifact_count": 3,
            },
            "artifacts": {
                "create": ["screen/tasks.json", "jobs/02_screen.pbs"],
                "update": ["campaign.json"],
            },
            "effects": {
                "prepare_screening": True,
                "submit_screening": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        if self.error:
            raise self.error
        return {
            "status": "screening_prepared",
            "campaign_id": "mot_2d-id",
            "stage": "screen",
            "artifacts": {"created": 2, "updated": 1},
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "not_synchronized"},
        }


def test_screening_endpoints_are_session_bound_and_do_not_submit():
    service = _FakeScreeningService()
    with running_server(request_count=4, screening_service=service) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/smoke/status",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["source"] == "zeus"
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/screening/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["effects"]["submit_screening"] is False
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/screening/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "screen-token"}),
        )
        assert status == 201 and payload["data"]["submitted_to_zeus"] is False
        assert len({call[2] for call in service.calls}) == 1


def test_screening_errors_are_sanitized():
    service = _FakeScreeningService(ZeusScreeningError("transition_outcome_unknown"))
    with running_server(request_count=2, screening_service=service) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/screening/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert (
            status == 409 and payload["error"]["code"] == "transition_outcome_unknown"
        )
        assert "/home/" not in payload["error"]["message"]


class _FakeScreenSubmissionService:
    def preview(self, payload, *, session_id):
        return {
            "preview_token": "t",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "mot_2d-id",
                "name": "C",
                "git_commit": "a" * 40,
                "s0_values": [1.3],
            },
            "stage": {"id": "screen", "label": "Screening", "purpose": "Broad search."},
            "job": {
                "file": "jobs/02_screen.pbs",
                "kind": "array",
                "task_count": 3,
                "array_throttle": 3,
                "queue": "zeus_combined_q",
                "cores_per_task": 200,
                "memory_per_task_bytes": 68719476736,
                "walltime_seconds": 86400,
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": payload["project_directory"],
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "inputs": {"verified_count": 72, "status": "ready"},
            "smoke": {
                "status": "validated",
                "job_id": "1.zeus-master",
                "point_count": 1,
            },
            "effects": {
                "submit_screening": True,
                "submit_later_stages": False,
                "modify_files": False,
            },
            "later_stages_locked": True,
        }

    def confirm(self, payload, *, session_id):
        return {
            "status": "submitted",
            "campaign_id": "mot_2d-id",
            "stage": "screen",
            "job_id": "2[].zeus-master",
            "submitted_at": "2026-10-08T21:00:00+00:00",
            "later_stages_locked": True,
        }


def test_screen_submission_endpoints_require_explicit_session_confirmation():
    service = _FakeScreenSubmissionService()
    with running_server(request_count=3, screen_submission_service=service) as base_url:
        _, headers, payload = request_json(
            f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        trusted = _session_headers(
            base_url,
            headers["Set-Cookie"].split(";", 1)[0],
            payload["data"]["csrf_token"],
        )
        request = {
            "campaign_id": "mot_2d-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/screening/preview",
            method="POST",
            headers=trusted,
            body=json.dumps(request),
        )
        assert status == 200 and payload["data"]["job"]["array_throttle"] == 3
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/screening/confirm",
            method="POST",
            headers=trusted,
            body=json.dumps({"preview_token": "t"}),
        )
        assert status == 201 and payload["data"]["job_id"] == "2[].zeus-master"


def test_server_main_closes_both_bounded_local_execution_pools():
    source = inspect.getsource(server_module.main)
    assert "mot_2d_local.close(wait=False)" in source
    assert "zeeman_local.close(wait=False)" in source

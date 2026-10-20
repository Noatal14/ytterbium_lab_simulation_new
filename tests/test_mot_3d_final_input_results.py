import copy
import hashlib
import io
import json

import numpy as np
import pytest

from studies.mot_3d_campaign import render_final_validation_transition
from workflow_api.mot_3d_final_input_results import (
    FinalInputResultError,
    expected_paths,
    validate_final_input_result_bytes,
)


PROJECT = "/home/test/ytterbium_lab_simulation_new"
ROOT = f"{PROJECT}/data/optimization/mot_3d/campaign"
LOGICAL = "data/optimization/mot_3d/campaign"
COMMIT = "a" * 40
PHYSICAL = "1" * 64
PROFILE_HASH = "2" * 64
LAB_HASH = "3" * 64


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _npy(value):
    stream = io.BytesIO()
    np.save(stream, np.asarray(value, dtype=np.float64), allow_pickle=False)
    return stream.getvalue()


def _fixture():
    stage = {
        "classification": "new_unopened_inputs_after_nominal_lock",
        "locked_nominals": f"{LOGICAL}/selection/locked_nominals.json",
        "zeeman_seeds": list(range(3035, 3055)),
        "mot_seeds": list(range(43035, 43055)),
        "zeeman_job": f"{LOGICAL}/jobs/final_validation_inputs/01_generate_zeeman.pbs",
        "mot_job": f"{LOGICAL}/jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
        "freeze_job": f"{LOGICAL}/jobs/final_validation_inputs/03_freeze_inputs.pbs",
        "input_manifest": f"{LOGICAL}/final_validation_inputs/input_manifest.json",
    }
    parameters = {"s0": 1.3, "detuning_gamma": -1.0, "magnet_radius": 0.046}
    design = {
        "dt_s": 4e-5,
        "stochastic_solver": "RK4StHybridCustom",
        "uses_all_available_particles": True,
        "npools": 200,
        "ensemble_dir": f"{ROOT}/final_validation_inputs/after_zeeman",
        "zeeman_profile": "corrected",
        "git_commit": COMMIT,
        "laboratory_spec_version": "laboratory_physical_v1",
        "laboratory_spec_sha256": LAB_HASH,
        "zeeman_profile_sha256": PROFILE_HASH,
    }
    manifest = {
        "kind": "mot_3d_campaign_v2",
        "name": "campaign",
        "stage": "final_validation_input_generation",
        "provenance": {"git_commit": COMMIT, "physical_model_sha256": PHYSICAL},
        "design": {
            "solver": "RK4StHybridCustom",
            "production_dt_s": 5e-6,
            "families": ["angled_donut", "single_pass"],
        },
        "upstream_2d_campaign": {
            "expected_survivor_parameters": parameters,
            "expected_survivor_design": {
                "stochastic_solver": "RK4StHybridCustom",
                "zeeman_profile": "corrected",
            },
        },
        "stages": {"final_validation_input_generation": stage},
    }
    locked = {
        "kind": "mot_3d_locked_nominals",
        "classification": "locked_before_new_validation_inputs",
        "campaign_manifest_sha256_before_stage": "4" * 64,
        "families": {
            family: {
                "candidate_id": f"{family}_finalist_02",
                "parameters": {},
                "derived_parameters": {},
                "resolved_profile": {"geometry": family},
                "selection_summary_sha256": "5" * 64,
            }
            for family in ("angled_donut", "single_pass")
        },
    }
    submission = {
        "kind": "mot_3d_final_validation_input_submission",
        "status": "submitted",
        "submission_key": "6" * 64,
        "nonce": "7" * 32,
        "commit": COMMIT,
        "created_unix_s": 1,
        "zeeman_array_job_id": "101[].zeus-master",
        "mot_array_job_id": "102[].zeus-master",
        "freeze_job_id": "103.zeus-master",
    }
    files = {}
    rows = []
    for index, (zseed, mseed) in enumerate(zip(range(3035, 3055), range(43035, 43055))):
        zbase = f"final_validation_inputs/after_zeeman/production_zeeman_n50000_dt40us_seed{zseed}"
        mbase = f"final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed{zseed}_mot_seed{mseed}"
        rpath = (
            f"final_validation_inputs/mot_2d_records/replicates/zeeman_seed{zseed}.json"
        )
        zraw = _npy([[index + 1] * 6, [index + 2] * 6])
        mraw = _npy([[index + 0.25] * 6])
        files[f"{zbase}.npy"] = zraw
        files[f"{mbase}.npy"] = mraw
        files[f"{zbase}.json"] = _json(
            {
                "kind": "zeeman_ensemble",
                "parameters": {
                    "seed": zseed,
                    "resolved_zeeman_magnet_profile": "corrected",
                },
                "shape": [2, 6],
                "output_sha256": hashlib.sha256(zraw).hexdigest(),
                "laboratory_spec_version": "laboratory_physical_v1",
                "laboratory_spec_sha256": LAB_HASH,
                "zeeman_profile_sha256": PROFILE_HASH,
                "software": {"git_commit": COMMIT},
            }
        )
        files[f"{mbase}.json"] = _json(
            {
                "kind": "mot_2d_final_survivor_ensemble",
                "zeeman_seed": zseed,
                "mot_seed": mseed,
                "parameters": parameters,
                "design": design,
                "source_zeeman_ensemble": f"{ROOT}/{zbase}.npy",
                "shape": [1, 6],
                "output_sha256": hashlib.sha256(mraw).hexdigest(),
            }
        )
        files[rpath] = _json(
            {
                "kind": "mot_2d_final_production_replicate",
                "parameters": parameters,
                "design": design,
                "replicate": {
                    "zeeman_seed": zseed,
                    "mot_seed": mseed,
                    "ensemble_file": f"{ROOT}/{zbase}.npy",
                    "captured": 1,
                },
            }
        )
        rows.append(
            {
                "zeeman_seed": zseed,
                "mot_seed": mseed,
                "path": f"{ROOT}/{mbase}.npy",
                "metadata_path": f"{ROOT}/{mbase}.json",
                "sha256": hashlib.sha256(mraw).hexdigest(),
                "metadata_sha256": hashlib.sha256(files[f"{mbase}.json"]).hexdigest(),
                "replicate_path": f"{ROOT}/{rpath}",
                "replicate_sha256": hashlib.sha256(files[rpath]).hexdigest(),
                "zeeman_path": f"{ROOT}/{zbase}.npy",
                "zeeman_sha256": hashlib.sha256(zraw).hexdigest(),
                "zeeman_metadata_path": f"{ROOT}/{zbase}.json",
                "zeeman_metadata_sha256": hashlib.sha256(
                    files[f"{zbase}.json"]
                ).hexdigest(),
                "shape": [1, 6],
                "n_survivors": 1,
            }
        )
    files["final_validation_inputs/input_manifest.json"] = _json(
        {
            "kind": "mot_3d_final_validation_inputs",
            "classification": "newly_generated_sealed_after_nominal_lock",
            "locked_nominals_sha256": hashlib.sha256(_json(locked)).hexdigest(),
            "solver": "RK4StHybridCustom",
            "campaign_name": "campaign",
            "git_commit": COMMIT,
            "physical_model_sha256": PHYSICAL,
            "generation_submission_sha256": hashlib.sha256(
                _json(submission)
            ).hexdigest(),
            "generation_jobs": submission,
            "ensembles": rows,
            "total_survivors": 20,
        }
    )
    assert set(files) == set(expected_paths()) and len(files) == 101
    return manifest, locked, submission, files


def _validate(values):
    manifest, locked, submission, files = values
    return validate_final_input_result_bytes(
        _json(manifest),
        _json(locked),
        _json(submission),
        files,
        project_directory=PROJECT,
        campaign_absolute_path=ROOT,
    )


def test_realistic_exact_101_file_fixture_validates_original_bytes():
    values = _fixture()
    result = _validate(values)
    assert result.paths == expected_paths()
    assert len(result.hashes) == 101
    assert result.input_manifest["total_survivors"] == 20
    assert (
        result.evidence_sha256 == hashlib.sha256(_json(dict(result.hashes))).hexdigest()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate_json",
        "nonfinite_json",
        "foreign_root",
        "manifest_seed",
        "manifest_stage",
        "locked_kind",
        "locked_candidate",
        "submission_job",
        "submission_nonce",
        "zeeman_seed",
        "zeeman_hash",
        "zeeman_profile",
        "zeeman_spec",
        "survivor_seed",
        "survivor_parameters",
        "survivor_design",
        "survivor_source",
        "survivor_shape",
        "replicate_kind",
        "replicate_seed",
        "replicate_design",
        "replicate_source",
        "replicate_count",
        "npy_dtype",
        "npy_shape",
        "npy_nonfinite",
        "manifest_order",
        "manifest_hash",
        "manifest_total",
        "manifest_solver",
        "manifest_commit",
        "original_byte_change",
    ],
)
def test_exact_fixture_rejects_every_provenance_schema_and_array_mutation(mutation):
    manifest, locked, submission, files = _fixture()
    files = dict(files)
    zbase = (
        "final_validation_inputs/after_zeeman/production_zeeman_n50000_dt40us_seed3035"
    )
    mbase = "final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed3035_mot_seed43035"
    rpath = "final_validation_inputs/mot_2d_records/replicates/zeeman_seed3035.json"

    def change(path, fn):
        value = json.loads(files[path])
        fn(value)
        files[path] = _json(value)

    if mutation == "missing":
        files.pop(rpath)
    elif mutation == "extra":
        files["foreign.json"] = b"{}"
    elif mutation == "duplicate_json":
        files[rpath] = b'{"kind":"x","kind":"y"}'
    elif mutation == "nonfinite_json":
        files[rpath] = b'{"value":NaN}'
    elif mutation == "foreign_root":
        with pytest.raises(FinalInputResultError):
            validate_final_input_result_bytes(
                _json(manifest),
                _json(locked),
                _json(submission),
                files,
                project_directory=PROJECT,
                campaign_absolute_path=f"{PROJECT}/other",
            )
        return
    elif mutation == "manifest_seed":
        manifest["stages"]["final_validation_input_generation"]["zeeman_seeds"][0] = 1
    elif mutation == "manifest_stage":
        manifest["stage"] = "final_validation"
    elif mutation == "locked_kind":
        locked["kind"] = "foreign"
    elif mutation == "locked_candidate":
        locked["families"]["angled_donut"]["candidate_id"] = "single_pass_finalist_01"
    elif mutation == "submission_job":
        submission["freeze_job_id"] = "101[].zeus-master"
    elif mutation == "submission_nonce":
        submission["nonce"] = 7
    elif mutation == "zeeman_seed":
        change(f"{zbase}.json", lambda x: x["parameters"].update(seed=1))
    elif mutation == "zeeman_hash":
        change(f"{zbase}.json", lambda x: x.update(output_sha256="0" * 64))
    elif mutation == "zeeman_profile":
        change(
            f"{zbase}.json",
            lambda x: x["parameters"].update(resolved_zeeman_magnet_profile="other"),
        )
    elif mutation == "zeeman_spec":
        change(f"{zbase}.json", lambda x: x.update(laboratory_spec_sha256="0" * 64))
    elif mutation == "survivor_seed":
        change(f"{mbase}.json", lambda x: x.update(mot_seed=1))
    elif mutation == "survivor_parameters":
        change(f"{mbase}.json", lambda x: x.update(parameters={}))
    elif mutation == "survivor_design":
        change(f"{mbase}.json", lambda x: x["design"].update(npools=199))
    elif mutation == "survivor_source":
        change(
            f"{mbase}.json", lambda x: x.update(source_zeeman_ensemble="../foreign.npy")
        )
    elif mutation == "survivor_shape":
        change(f"{mbase}.json", lambda x: x.update(shape=[2, 6]))
    elif mutation == "replicate_kind":
        change(rpath, lambda x: x.update(kind="foreign"))
    elif mutation == "replicate_seed":
        change(rpath, lambda x: x["replicate"].update(mot_seed=1))
    elif mutation == "replicate_design":
        change(rpath, lambda x: x["design"].update(npools=1))
    elif mutation == "replicate_source":
        change(rpath, lambda x: x["replicate"].update(ensemble_file="../foreign.npy"))
    elif mutation == "replicate_count":
        change(rpath, lambda x: x["replicate"].update(captured=2))
    elif mutation == "npy_dtype":
        stream = io.BytesIO()
        np.save(stream, np.ones((1, 6), dtype=np.float32))
        files[f"{mbase}.npy"] = stream.getvalue()
    elif mutation == "npy_shape":
        files[f"{mbase}.npy"] = _npy([[1] * 5])
    elif mutation == "npy_nonfinite":
        files[f"{mbase}.npy"] = _npy([[np.nan] * 6])
    else:
        inputs = json.loads(files["final_validation_inputs/input_manifest.json"])
        if mutation == "manifest_order":
            inputs["ensembles"] = list(reversed(inputs["ensembles"]))
        elif mutation == "manifest_hash":
            inputs["ensembles"][0]["sha256"] = "0" * 64
        elif mutation == "manifest_total":
            inputs["total_survivors"] = 19
        elif mutation == "manifest_solver":
            inputs["solver"] = "other"
        elif mutation == "manifest_commit":
            inputs["git_commit"] = "b" * 40
        elif mutation == "original_byte_change":
            files[rpath] += b"\n"
        files["final_validation_inputs/input_manifest.json"] = _json(inputs)
    with pytest.raises(FinalInputResultError):
        _validate((manifest, locked, submission, files))


@pytest.mark.parametrize(
    "mutation",
    [
        "locked_schema",
        "locked_family",
        "submission_schema",
        "submission_dependency",
        "zeeman_schema",
        "zeeman_profile",
        "zeeman_software",
        "survivor_schema",
        "survivor_parameters",
        "survivor_design",
        "replicate_schema",
        "replicate_design",
    ],
)
def test_coordinated_hash_updates_cannot_hide_semantic_mutation(mutation):
    """Rehashing a mutated child and its manifest row must not bypass semantics."""
    manifest, locked, submission, files = _fixture()
    files = dict(files)
    zbase = (
        "final_validation_inputs/after_zeeman/production_zeeman_n50000_dt40us_seed3035"
    )
    mbase = "final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed3035_mot_seed43035"
    rpath = "final_validation_inputs/mot_2d_records/replicates/zeeman_seed3035.json"
    inputs = json.loads(files["final_validation_inputs/input_manifest.json"])
    if mutation == "locked_schema":
        locked["extra"] = True
    elif mutation == "locked_family":
        locked["families"]["angled_donut"]["candidate_id"] = "single_pass_finalist_01"
    elif mutation == "submission_schema":
        submission["extra"] = True
    elif mutation == "submission_dependency":
        submission["mot_array_job_id"] = "104[].zeus-master"
    else:
        path = (
            f"{zbase}.json"
            if mutation.startswith("zeeman")
            else f"{mbase}.json" if mutation.startswith("survivor") else rpath
        )
        value = json.loads(files[path])
        if mutation == "zeeman_schema":
            value["extra"] = True
        elif mutation == "zeeman_profile":
            value["parameters"]["resolved_zeeman_magnet_profile"] = "other"
        elif mutation == "zeeman_software":
            value["software"]["git_commit"] = "b" * 40
        elif mutation == "survivor_schema":
            value["extra"] = True
        elif mutation == "survivor_parameters":
            value["parameters"]["s0"] = 99
        elif mutation == "survivor_design":
            value["design"]["npools"] = 199
        elif mutation == "replicate_schema":
            value["extra"] = True
        elif mutation == "replicate_design":
            value["design"]["git_commit"] = "b" * 40
        files[path] = _json(value)
    row = inputs["ensembles"][0]
    row["zeeman_metadata_sha256"] = hashlib.sha256(files[f"{zbase}.json"]).hexdigest()
    row["metadata_sha256"] = hashlib.sha256(files[f"{mbase}.json"]).hexdigest()
    row["replicate_sha256"] = hashlib.sha256(files[rpath]).hexdigest()
    inputs["locked_nominals_sha256"] = hashlib.sha256(_json(locked)).hexdigest()
    inputs["generation_submission_sha256"] = hashlib.sha256(
        _json(submission)
    ).hexdigest()
    inputs["generation_jobs"] = submission
    files["final_validation_inputs/input_manifest.json"] = _json(inputs)
    with pytest.raises(FinalInputResultError):
        _validate((manifest, locked, submission, files))


def test_final_validation_renderer_is_exact_portable_and_science_bound():
    manifest, _, _, _ = _fixture()
    stage = manifest["stages"]["final_validation_input_generation"]
    stage["locked_nominals"] = f"{LOGICAL}/selection/locked_nominals.json"
    stage["input_manifest"] = f"{LOGICAL}/final_validation_inputs/input_manifest.json"
    stage["zeeman_job"] = (
        f"{LOGICAL}/jobs/final_validation_inputs/01_generate_zeeman.pbs"
    )
    stage["mot_job"] = (
        f"{LOGICAL}/jobs/final_validation_inputs/02_generate_2d_survivors.pbs"
    )
    stage["freeze_job"] = f"{LOGICAL}/jobs/final_validation_inputs/03_freeze_inputs.pbs"
    artifacts, updated = render_final_validation_transition(LOGICAL, manifest)
    assert set(artifacts) == {
        "campaign.json",
        "jobs/final_validation/angled_donut_array.pbs",
        "jobs/final_validation/angled_donut_merge.pbs",
        "jobs/final_validation/single_pass_array.pbs",
        "jobs/final_validation/single_pass_merge.pbs",
    }
    assert updated["stage"] == "final_validation"
    assert (
        updated["stages"]["final_validation"]["classification"]
        == "sealed_unbiased_final_validation"
    )
    combined = b"\n".join(artifacts.values())
    assert (
        ROOT.encode() not in combined
        and b"/home/" not in combined
        and b".." not in combined
    )
    for family in ("angled_donut", "single_pass"):
        worker = artifacts[f"jobs/final_validation/{family}_array.pbs"]
        merge = artifacts[f"jobs/final_validation/{family}_merge.pbs"]
        for literal in (b"44001 44002 44003", b"--npools 200", b"--dt 5e-06", b"--t-max 0.05"):
            assert literal in worker
        for literal in (
            b"--bootstrap-replicates 20000",
            b"--bootstrap-seed 92001",
            b"--dt 5e-06",
        ):
            assert literal in merge
    for bad_root in (
        "/absolute/campaign",
        "data/optimization/mot_3d/other",
        "data/optimization/../campaign",
    ):
        with pytest.raises(ValueError):
            render_final_validation_transition(bad_root, manifest)
    for key, value in (("stage", "final_validation"), ("name", "other")):
        bad = copy.deepcopy(manifest)
        bad[key] = value
        with pytest.raises(ValueError):
            render_final_validation_transition(LOGICAL, bad)

from argparse import Namespace
import hashlib
import io
import json

import numpy as np
import pytest

from workflow_api.mot_3d_finalist_results import (
    FinalistResultError,
    expected_paths,
    validate_finalist_result_bytes,
)


BASE_PARAMETERS = {
    "angled_donut": {
        "green_s0": 18.0,
        "green_detuning_gamma": -18.0,
        "green_waist_m": 0.0065,
        "blue_s0": 1.4,
        "blue_waist_m": 0.0074,
        "magnetic_gradient_G_cm": 5.5,
        "blue_detuning_gamma": -0.8,
        "core_shell_split_radius_m": 0.0026,
    },
    "single_pass": {
        "green_s0": 38.0,
        "green_detuning_gamma": -25.0,
        "green_waist_m": 0.0074,
        "blue_s0": 0.2,
        "blue_waist_m": 0.0073,
        "magnetic_gradient_G_cm": 2.3,
        "blue_detuning_anchor_gamma": -2.5,
        "blue_crossing_angle_deg": 46.0,
        "blue_crossing_z_offset_m": -0.046,
    },
}


def selections():
    return {
        family: {
            "kind": "mot_3d_finalist_selection",
            "family": family,
            "candidate_count": 3,
            "candidates": [
                {"candidate_id": f"{family}_finalist_{index:02d}"}
                for index in range(1, 4)
            ],
        }
        for family in ("angled_donut", "single_pass")
    }


def test_exact_registry_has_44_files_and_no_aliases():
    paths = expected_paths(selections())
    assert len(paths) == len(set(paths)) == 44
    assert all("worker_" not in path for path in paths)
    assert sum(path.endswith("particle_selection.json") for path in paths) == 6
    assert sum(path.endswith("finalist_summary.json") for path in paths) == 2


@pytest.mark.parametrize("mutation", ["missing_family", "wrong_id", "extra_candidate"])
def test_selection_registry_mutations_fail_closed(mutation):
    value = selections()
    if mutation == "missing_family":
        value.pop("angled_donut")
    elif mutation == "wrong_id":
        value["angled_donut"]["candidates"][0]["candidate_id"] = "unsafe"
    else:
        value["single_pass"]["candidates"].append({"candidate_id": "extra"})
    with pytest.raises(FinalistResultError, match="selection_mismatch"):
        expected_paths(value)


def test_validator_rejects_nonbyte_and_oversized_boundaries_before_loading():
    with pytest.raises(FinalistResultError, match="artifact_registry_mismatch"):
        validate_finalist_result_bytes(
            b"{}",
            {"angled_donut": b"{}", "single_pass": b"{}"},
            {"bad": b"x" * (2 * 1024 * 1024 + 1)},
            project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
            campaign_absolute_path="/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_3d/example",
        )


def _fixture(tmp_path):
    from studies.mot_3d.discovery.optimize import build_profile_from_parameters
    from studies.mot_3d.finalists.merge import merge

    project = str(tmp_path / "project")
    remote = f"{project}/data/optimization/mot_3d/campaign"
    root = tmp_path / "project/data/optimization/mot_3d/campaign"
    root.mkdir(parents=True)
    roles, provenance = {}, []
    seeds = iter(range(3015, 3035))
    for role, count in (("discovery", 12), ("refinement", 4), ("preliminary_check", 4)):
        rows = []
        for _ in range(count):
            seed = next(seeds)
            row = {
                "path": f"{project}/data/input_{seed}.npy",
                "metadata_path": f"{project}/data/input_{seed}.json",
                "sha256": hashlib.sha256(str(seed).encode()).hexdigest(),
                "metadata_sha256": hashlib.sha256(f"meta{seed}".encode()).hexdigest(),
                "zeeman_seed": seed,
                "mot_seed": 40000 + seed,
                "n_survivors": 1,
                "shape": [1, 6],
                "dtype": "float64",
                "source_git_commit": "a" * 40,
                "source_design": {},
                "source_parameters": {},
            }
            rows.append(row)
            provenance.append(
                {
                    "ensemble_id": len(provenance),
                    "file": row["path"],
                    "array_sha256": row["sha256"],
                    "zeeman_seed": seed,
                    "mot_seed": row["mot_seed"],
                    "particle_count": 1,
                }
            )
        roles[role] = rows
    manifest = {
        "name": "campaign",
        "stage": "finalist_selection",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "design": {"screening_dt_s": 1e-5, "solver": "RK4StHybridCustom"},
        "input_roles": roles,
        "stages": {
            "finalist_selection": {
                "classification": "final_candidate_selection_not_unbiased_validation",
                "input_roles": ["discovery", "refinement", "preliminary_check"],
            }
        },
    }
    manifest_raw = json.dumps(manifest, indent=2).encode() + b"\n"
    (root / "campaign.json").write_bytes(manifest_raw)
    role_rows = sum(
        (roles[key] for key in ("discovery", "refinement", "preliminary_check")), []
    )
    role_digest = hashlib.sha256(
        json.dumps(role_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    particle_digest = hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    selection_bytes, results = {}, {}
    for family in ("angled_donut", "single_pass"):
        candidates = []
        for rank in range(1, 4):
            parameters = dict(BASE_PARAMETERS[family])
            parameters["green_s0"] += rank / 10
            profile, normalized, derived = build_profile_from_parameters(
                family, parameters
            )
            candidates.append(
                {
                    "candidate_id": f"{family}_finalist_{rank:02d}",
                    "finalist_rank_from_closure": rank,
                    "source_candidate_id": f"{family}_closure_{rank:02d}",
                    "source_closure_role": f"rank_{rank}",
                    "source_closure_fraction": 0.2 - rank / 100,
                    "source_closure_ci": [0.1 - rank / 100, 0.3],
                    "parameters": normalized,
                    "derived_parameters": derived,
                    "resolved_profile": profile,
                }
            )
        selection = {
            "kind": "mot_3d_finalist_selection",
            "family": family,
            "candidate_count": 3,
            "selection_rule": "top three closure candidates ranked by the lower endpoint of the simultaneous 95% confidence interval",
            "candidates": candidates,
        }
        selection_raw = json.dumps(selection, indent=2).encode() + b"\n"
        selection_bytes[family] = selection_raw
        selection_path = root / "selection/finalists" / f"{family}.json"
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_bytes(selection_raw)
        design = {
            "campaign_manifest_path": f"{remote}/campaign.json",
            "campaign_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "selection_path": f"{remote}/selection/finalists/{family}.json",
            "selection_sha256": hashlib.sha256(selection_raw).hexdigest(),
            "git_commit": "a" * 40,
            "physical_model_sha256": "b" * 64,
            "input_role": "all_existing_selection",
            "input_role_sha256": role_digest,
            "dt_s": 1e-5,
            "t_max_s": 0.1,
            "solver": "RK4StHybridCustom",
            "particles_per_ensemble": None,
            "selection_seed": None,
            "particle_selection_sha256": particle_digest,
        }
        for index, candidate in enumerate(candidates):
            directory = root / "finalist_selection" / family / f"finalist_{index}"
            directory.mkdir(parents=True)
            (directory / "particle_selection.json").write_text(json.dumps(provenance))
            for seed in (43001, 43002, 43003):
                usable = np.zeros(20, dtype=bool)
                usable[: (index + seed) % 5] = True
                archive = io.BytesIO()
                np.savez_compressed(
                    archive,
                    usable_at_end=usable,
                    usable_ever=usable,
                    ensemble_ids=np.arange(20, dtype=np.int64),
                )
                stem = f"{candidate['candidate_id']}_seed_{seed}"
                npz = directory / f"{stem}.npz"
                npz.write_bytes(archive.getvalue())
                record = {
                    "kind": "mot_3d_finalist_seed_result",
                    "family": family,
                    "candidate_id": candidate["candidate_id"],
                    "finalist_index": index,
                    "recoil_seed": seed,
                    "input_particle_count": 20,
                    "usable_at_end_count": int(usable.sum()),
                    "usable_ever_count": int(usable.sum()),
                    "peak_usable_count": int(usable.sum()),
                    "entered_capture_region_count": int(usable.sum()),
                    "slow_inside_count": int(usable.sum()),
                    "outcomes_path": str(npz),
                    "outcomes_sha256": hashlib.sha256(archive.getvalue()).hexdigest(),
                    "design": design,
                }
                (directory / f"{stem}.json").write_text(json.dumps(record))
        merge(
            Namespace(
                selection=str(selection_path),
                input_root=str(root / "finalist_selection" / family),
                output_dir=str(root / "finalist_selection" / family / "merged"),
                bootstrap_replicates=10000,
                bootstrap_seed=82001,
            )
        )
        for path in (root / "finalist_selection" / family).rglob("*"):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                raw = path.read_bytes()
                if (
                    relative.endswith(".json")
                    and "finalist_" in relative
                    and not relative.endswith("particle_selection.json")
                    and not relative.endswith("finalist_summary.json")
                ):
                    row = json.loads(raw)
                    row["outcomes_path"] = f"{remote}/{relative[:-5]}.npz"
                    raw = json.dumps(row).encode()
                results[relative] = raw
    return project, remote, manifest, manifest_raw, selection_bytes, results, provenance


def test_realistic_exact_44_file_fixture_and_adversarial_matrix(tmp_path):
    project, remote, manifest, manifest_raw, selections_raw, results, provenance = (
        _fixture(tmp_path)
    )
    validated = validate_finalist_result_bytes(
        manifest_raw,
        selections_raw,
        results,
        project_directory=project,
        campaign_absolute_path=remote,
    )
    assert len(validated.paths) == len(validated.hashes) == 44

    def reject(
        *,
        manifest_value=manifest_raw,
        selection_value=selections_raw,
        result_value=results,
        code,
    ):
        with pytest.raises(FinalistResultError, match=code):
            validate_finalist_result_bytes(
                manifest_value,
                selection_value,
                result_value,
                project_directory=project,
                campaign_absolute_path=remote,
            )

    record_key = next(
        key
        for key in results
        if key.endswith(".json")
        and "finalist_0/" in key
        and not key.endswith("particle_selection.json")
    )
    npz_key = record_key[:-5] + ".npz"
    summary_key = "finalist_selection/angled_donut/merged/finalist_summary.json"
    particle_key = "finalist_selection/angled_donut/finalist_0/particle_selection.json"

    for mutate, code in (
        (lambda m: m.update(stage="closure"), "design_mismatch"),
        (
            lambda m: m["stages"]["finalist_selection"]["input_roles"].reverse(),
            "design_mismatch",
        ),
    ):
        changed = json.loads(manifest_raw)
        mutate(changed)
        reject(manifest_value=json.dumps(changed).encode(), code=code)

    for mutate in (
        lambda m: m["input_roles"]["discovery"].pop(),
        lambda m: m["input_roles"]["discovery"][0].update(zeeman_seed=3016),
        lambda m: m["input_roles"]["discovery"][0].update(
            metadata_sha256="not-a-digest"
        ),
        lambda m: m["input_roles"]["discovery"][0].update(source_git_commit="0" * 40),
        lambda m: m["input_roles"]["discovery"][0].update(
            path=f"{project}/../outside.npy",
            metadata_path=f"{project}/../outside.json",
        ),
    ):
        changed = json.loads(manifest_raw)
        mutate(changed)
        reject(
            manifest_value=json.dumps(changed).encode(),
            code="particle_selection_mismatch",
        )

    changed = dict(selections_raw)
    selection = json.loads(changed["angled_donut"])
    selection["selection_rule"] = "some other ranking"
    changed["angled_donut"] = json.dumps(selection).encode()
    reject(selection_value=changed, code="selection_mismatch")

    for field, value in (
        ("finalist_rank_from_closure", 2),
        ("source_candidate_id", "foreign"),
        ("source_closure_role", "rank_2"),
        ("parameters", {}),
        ("derived_parameters", {"unexpected": 1}),
        ("resolved_profile", {}),
    ):
        changed = dict(selections_raw)
        selection = json.loads(changed["angled_donut"])
        selection["candidates"][0][field] = value
        changed["angled_donut"] = json.dumps(selection).encode()
        reject(selection_value=changed, code="selection_mismatch")

    for field, value, code in (
        ("extra", 1, "result_metadata_mismatch"),
        ("finalist_index", True, "result_metadata_mismatch"),
        ("usable_at_end_count", True, "result_metadata_mismatch"),
        ("peak_usable_count", -1, "result_metadata_mismatch"),
        ("git_commit", "0" * 40, "design_mismatch"),
        ("physical_model_sha256", "0" * 64, "design_mismatch"),
        ("campaign_manifest_path", "/foreign/campaign.json", "design_mismatch"),
        ("selection_path", "/foreign/selection.json", "design_mismatch"),
        ("input_role_sha256", "0" * 64, "design_mismatch"),
        ("selection_sha256", "0" * 64, "design_mismatch"),
        ("particle_selection_sha256", "0" * 64, "design_mismatch"),
    ):
        changed = dict(results)
        row = json.loads(changed[record_key])
        if field in row.get("design", {}):
            row["design"][field] = value
        else:
            row[field] = value
        changed[record_key] = json.dumps(row).encode()
        reject(result_value=changed, code=code)

    changed = dict(results)
    particles = json.loads(changed[particle_key])
    particles[0]["particle_count"] += 1
    changed[particle_key] = json.dumps(particles).encode()
    reject(result_value=changed, code="particle_selection_mismatch")

    changed_manifest = json.loads(manifest_raw)
    changed_manifest["input_roles"]["discovery"][0]["n_survivors"] = 2
    reject(
        manifest_value=json.dumps(changed_manifest).encode(),
        code="particle_selection_mismatch",
    )
    changed = dict(results)
    changed["finalist_selection/single_pass/finalist_0/particle_selection.json"] = (
        json.dumps(provenance[:-1]).encode()
    )
    reject(result_value=changed, code="particle_selection_mismatch")

    changed = dict(results)
    raw = io.BytesIO()
    np.savez_compressed(
        raw,
        usable_at_end=np.ones(20, dtype=np.int8),
        usable_ever=np.ones(20, dtype=bool),
        ensemble_ids=np.arange(20),
    )
    changed[npz_key] = raw.getvalue()
    row = json.loads(changed[record_key])
    row["outcomes_sha256"] = hashlib.sha256(raw.getvalue()).hexdigest()
    changed[record_key] = json.dumps(row).encode()
    reject(result_value=changed, code="result_archive_invalid")
    changed = dict(results)
    raw = io.BytesIO()
    np.savez_compressed(
        raw,
        usable_at_end=np.zeros(20, dtype=bool),
        usable_ever=np.zeros(20, dtype=bool),
        ensemble_ids=np.arange(19, -1, -1, dtype=np.int64),
    )
    changed[npz_key] = raw.getvalue()
    row = json.loads(changed[record_key])
    row["outcomes_sha256"] = hashlib.sha256(raw.getvalue()).hexdigest()
    changed[record_key] = json.dumps(row).encode()
    reject(result_value=changed, code="result_archive_invalid")
    changed = dict(results)
    summary = json.loads(changed[summary_key])
    summary["ranked_candidates"].reverse()
    changed[summary_key] = json.dumps(summary).encode()
    reject(result_value=changed, code="summary_mismatch")

    reformatted = dict(results)
    row = json.loads(reformatted[record_key])
    reformatted[record_key] = json.dumps(row, indent=4).encode()
    other = validate_finalist_result_bytes(
        manifest_raw,
        selections_raw,
        reformatted,
        project_directory=project,
        campaign_absolute_path=remote,
    )
    assert other.hashes[record_key] != validated.hashes[record_key]
    assert other.evidence_sha256 != validated.evidence_sha256

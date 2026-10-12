from argparse import Namespace
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from workflow_api.mot_3d_refinement_results import (
    EXPECTED_RESULT_FILES,
    RefinementResultError,
    expected_paths,
    render_typescript_refinement_result_contract,
    validate_refinement_result_bytes,
)
from workflow_api.mot_3d_preliminary_results import (
    expected_selection_particle_provenance,
)


def _selection(family):
    return {
        "kind": "mot_3d_focused_refinement_selection",
        "family": family,
        "candidate_count": 16,
        "candidates": [
            {"candidate_id": f"{family}_refine_{index:02d}"} for index in range(16)
        ],
    }


def test_refinement_registry_is_exact_and_worker_partitioned():
    paths = expected_paths(
        {family: _selection(family) for family in ("angled_donut", "single_pass")}
    )
    assert len(paths) == EXPECTED_RESULT_FILES == 200
    assert len(set(paths)) == len(paths)
    assert sum(path.endswith("particle_selection.json") for path in paths) == 6
    assert sum(path.endswith("refinement_summary.json") for path in paths) == 2
    assert sum(path.endswith(".npz") for path in paths) == 96
    assert sum(path.endswith(".json") for path in paths) == 104


def test_generated_ui_reason_contract_has_no_drift():
    artifact = Path("ui/src/generated/mot3dRefinementTransitionSpec.v1.ts")
    assert artifact.read_text() == render_typescript_refinement_result_contract()


def test_registry_is_deterministic():
    selections = {
        family: _selection(family) for family in ("angled_donut", "single_pass")
    }
    assert expected_paths(selections) == expected_paths(
        json.loads(json.dumps(selections, sort_keys=True))
    )


def test_closed_200_file_fixture_validates_and_binds_canonical_paths(tmp_path):
    project = "/home/tal.noa/ytterbium_lab_simulation_new"
    remote = f"{project}/data/optimization/mot_3d/campaign"
    root = tmp_path / "campaign"
    root.mkdir()
    roles = []
    for index, seed in enumerate(range(3027, 3031)):
        roles.append(
            {
                "path": f"{project}/data/input_{seed}.npy",
                "metadata_path": f"{project}/data/input_{seed}.json",
                "sha256": f"{index + 1}" * 64,
                "metadata_sha256": f"{index + 5}" * 64,
                "zeeman_seed": seed,
                "mot_seed": 43000 + seed,
                "n_survivors": 800,
                "shape": [800, 6],
                "dtype": "float64",
                "source_git_commit": "a" * 40,
                "source_design": {},
                "source_parameters": {},
            }
        )
    manifest = {
        "name": "campaign",
        "stage": "refinement",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "design": {"screening_dt_s": 1e-5, "solver": "RK4StHybridCustom"},
        "input_roles": {"refinement": roles},
        "stages": {
            "refinement": {
                "classification": "candidate_selection_not_final_validation",
                "input_role": "refinement",
            }
        },
    }
    manifest_raw = json.dumps(manifest, indent=2).encode() + b"\n"
    (root / "campaign.json").write_bytes(manifest_raw)
    particles = expected_selection_particle_provenance(
        manifest,
        project_directory=project,
        input_role="refinement",
        input_ensembles=4,
        particles_per_ensemble=750,
        selection_seed=61001,
        expected_zeeman_seeds=tuple(range(3027, 3031)),
    )
    selections, results = {}, {}
    for family in ("angled_donut", "single_pass"):
        selection = _selection(family)
        for row in selection["candidates"]:
            row.update({"parameters": {}, "resolved_profile": {}})
        selection_raw = json.dumps(selection, indent=2).encode() + b"\n"
        selections[family] = selection_raw
        selection_path = root / "selection" / "refinement" / f"{family}.json"
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_bytes(selection_raw)
        design = {
            "campaign_manifest_path": f"{remote}/campaign.json",
            "campaign_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "selection_path": f"{remote}/selection/refinement/{family}.json",
            "selection_sha256": hashlib.sha256(selection_raw).hexdigest(),
            "git_commit": "a" * 40,
            "physical_model_sha256": "b" * 64,
            "input_role": "refinement",
            "input_role_sha256": hashlib.sha256(
                json.dumps(roles, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "dt_s": 1e-5,
            "t_max_s": 0.1,
            "solver": "RK4StHybridCustom",
            "particles_per_ensemble": 750,
            "selection_seed": 61001,
            "particle_selection_sha256": hashlib.sha256(
                json.dumps(particles, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        for worker in range(3):
            worker_root = root / "refinement" / family / f"worker_{worker}"
            worker_root.mkdir(parents=True)
            (worker_root / "particle_selection.json").write_text(json.dumps(particles))
            for candidate in selection["candidates"][worker::3]:
                for seed in (42001, 42002, 42003):
                    stem = f"{candidate['candidate_id']}_seed_{seed}"
                    usable = np.zeros(3000, dtype=bool)
                    usable[: (seed + worker) % 13] = True
                    archive = io.BytesIO()
                    np.savez_compressed(
                        archive,
                        usable_at_end=usable,
                        usable_ever=usable,
                        ensemble_ids=np.repeat(np.arange(4), 750),
                    )
                    npz = worker_root / f"{stem}.npz"
                    npz.write_bytes(archive.getvalue())
                    record = {
                        "kind": "mot_3d_focused_refinement_seed_result",
                        "family": family,
                        "candidate_id": candidate["candidate_id"],
                        "worker_index": worker,
                        "recoil_seed": seed,
                        "input_particle_count": 3000,
                        "usable_at_end_count": int(usable.sum()),
                        "usable_ever_count": int(usable.sum()),
                        "peak_usable_count": int(usable.sum()),
                        "entered_capture_region_count": int(usable.sum()),
                        "slow_inside_count": int(usable.sum()),
                        "outcomes_path": str(npz),
                        "outcomes_sha256": hashlib.sha256(
                            archive.getvalue()
                        ).hexdigest(),
                        "design": design,
                    }
                    (worker_root / f"{stem}.json").write_text(json.dumps(record))
        from studies.mot_3d.refinement.merge import merge

        merge(
            Namespace(
                selection=str(selection_path),
                input_root=str(root / "refinement" / family),
                output_dir=str(root / "refinement" / family / "merged"),
                bootstrap_replicates=10000,
                bootstrap_seed=62001,
            )
        )
        for path in (root / "refinement" / family).rglob("*"):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                raw = path.read_bytes()
                if (
                    relative.endswith(".json")
                    and "worker_" in relative
                    and not relative.endswith("particle_selection.json")
                ):
                    row = json.loads(raw)
                    row["outcomes_path"] = (
                        f"{remote}/{Path(relative).with_suffix('.npz').as_posix()}"
                    )
                    raw = json.dumps(row).encode()
                results[relative] = raw
    validated = validate_refinement_result_bytes(
        manifest_raw,
        selections,
        results,
        project_directory=project,
        campaign_absolute_path=remote,
    )
    assert len(validated.paths) == 200

    def rejected(
        *,
        manifest_value=manifest_raw,
        selection_value=selections,
        result_value=results,
        code,
    ):
        with pytest.raises(RefinementResultError, match=code):
            validate_refinement_result_bytes(
                manifest_value,
                selection_value,
                result_value,
                project_directory=project,
                campaign_absolute_path=remote,
            )

    record_key = next(
        name
        for name in results
        if name.endswith(".json")
        and "worker_" in name
        and not name.endswith("particle_selection.json")
    )
    npz_key = str(Path(record_key).with_suffix(".npz"))
    bad = dict(results)
    row = json.loads(bad[record_key])
    row["outcomes_path"] = f"/attacker/{npz_key}"
    bad[record_key] = json.dumps(row).encode()
    rejected(result_value=bad, code="result_metadata_mismatch")
    bad = dict(results)
    bad.pop(npz_key)
    rejected(result_value=bad, code="artifact_registry_mismatch")
    bad = dict(results)
    bad[npz_key] = bad[npz_key][:-8]
    rejected(result_value=bad, code="result_archive_invalid")
    bad = dict(results)
    row = json.loads(bad[record_key])
    row["input_particle_count"] = True
    bad[record_key] = json.dumps(row).encode()
    rejected(result_value=bad, code="result_registry_invalid")
    bad_manifest = json.loads(manifest_raw)
    bad_manifest["stage"] = "closure"
    rejected(manifest_value=json.dumps(bad_manifest).encode(), code="design_mismatch")
    bad_selections = dict(selections)
    row = json.loads(bad_selections["angled_donut"])
    row["candidate_count"] = 15
    bad_selections["angled_donut"] = json.dumps(row).encode()
    rejected(selection_value=bad_selections, code="selection_mismatch")
    summary_key = "refinement/angled_donut/merged/refinement_summary.json"
    bad = dict(results)
    row = json.loads(bad[summary_key])
    row["bootstrap_seed"] = 1
    bad[summary_key] = json.dumps(row).encode()
    rejected(result_value=bad, code="summary_mismatch")
    bad = dict(results)
    row = json.loads(bad[record_key])
    row["design"]["dt_s"] = 2e-5
    bad[record_key] = json.dumps(row).encode()
    rejected(result_value=bad, code="design_mismatch")

    # Duplicate/non-finite JSON is rejected at every public byte boundary.
    rejected(
        manifest_value=b'{"name":"campaign","name":"other"}', code="malformed_json"
    )
    rejected(manifest_value=b'{"name":NaN}', code="malformed_json")
    bad_selections = dict(selections)
    bad_selections["angled_donut"] = b'{"kind":"x","kind":"y"}'
    rejected(selection_value=bad_selections, code="malformed_json")
    bad = dict(results)
    bad[record_key] = b'{"outcomes_path":"x","outcomes_path":"y"}'
    rejected(result_value=bad, code="malformed_json")

    # Exact registry membership rejects additions and path substitutions.
    bad = dict(results)
    bad["refinement/angled_donut/worker_0/unexpected.json"] = b"{}"
    rejected(result_value=bad, code="artifact_registry_mismatch")
    bad = dict(results)
    moved = bad.pop(record_key)
    worker = int(record_key.split("/worker_", 1)[1].split("/", 1)[0])
    bad[record_key.replace(f"worker_{worker}", f"worker_{(worker + 1) % 3}")] = moved
    rejected(result_value=bad, code="artifact_registry_mismatch")

    def mutate_record(field, value):
        changed = dict(results)
        payload = json.loads(changed[record_key])
        payload[field] = value
        changed[record_key] = json.dumps(payload).encode()
        return changed

    original_record = json.loads(results[record_key])
    wrong_worker = (original_record["worker_index"] + 1) % 3
    for field, value, code in (
        ("kind", "foreign", "result_registry_invalid"),
        ("family", "single_pass", "result_registry_invalid"),
        ("worker_index", True, "result_metadata_mismatch"),
        ("worker_index", wrong_worker, "result_metadata_mismatch"),
        ("recoil_seed", True, "result_registry_invalid"),
        ("recoil_seed", 999, "result_registry_invalid"),
        ("outcomes_sha256", "0" * 64, "result_registry_invalid"),
        ("usable_at_end_count", True, "result_metadata_mismatch"),
        ("usable_at_end_count", 3001, "result_metadata_mismatch"),
        ("peak_usable_count", -1, "result_metadata_mismatch"),
        ("slow_inside_count", 3001, "result_metadata_mismatch"),
    ):
        rejected(result_value=mutate_record(field, value), code=code)

    for field, value in (
        ("solver", "other"),
        ("selection_seed", True),
        ("particles_per_ensemble", 749),
        ("campaign_manifest_sha256", "0" * 64),
        ("input_role_sha256", "0" * 64),
        ("particle_selection_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("physical_model_sha256", "0" * 64),
    ):
        changed = dict(results)
        payload = json.loads(changed[record_key])
        payload["design"][field] = value
        changed[record_key] = json.dumps(payload).encode()
        rejected(result_value=changed, code="design_mismatch")

    # Archives are preflighted and then checked for exact science arrays.
    with np.load(io.BytesIO(results[npz_key]), allow_pickle=False) as archive:
        usable = archive["usable_at_end"].copy()
        ever = archive["usable_ever"].copy()
        groups = archive["ensemble_ids"].copy()

    def archive_bytes(
        *, usable_value=usable, ever_value=ever, groups_value=groups, extra=False
    ):
        output = io.BytesIO()
        arrays = {
            "usable_at_end": usable_value,
            "usable_ever": ever_value,
            "ensemble_ids": groups_value,
        }
        if extra:
            arrays["extra"] = np.zeros(1)
        np.savez_compressed(output, **arrays)
        return output.getvalue()

    for raw, code in (
        (archive_bytes(extra=True), "result_archive_invalid"),
        (archive_bytes(usable_value=usable.astype(np.int8)), "result_archive_invalid"),
        (archive_bytes(usable_value=usable[:-1]), "result_registry_invalid"),
        (
            archive_bytes(groups_value=np.zeros(3000, dtype=np.int64)),
            "result_archive_invalid",
        ),
    ):
        bad = dict(results)
        bad[npz_key] = raw
        record = json.loads(bad[record_key])
        record["outcomes_sha256"] = hashlib.sha256(raw).hexdigest()
        bad[record_key] = json.dumps(record).encode()
        rejected(result_value=bad, code=code)
    unusable = np.flatnonzero(~ever)
    if len(unusable):
        non_subset = usable.copy()
        non_subset[unusable[0]] = True
        bad = dict(results)
        raw = archive_bytes(usable_value=non_subset)
        bad[npz_key] = raw
        record = json.loads(bad[record_key])
        record["outcomes_sha256"] = hashlib.sha256(raw).hexdigest()
        bad[record_key] = json.dumps(record).encode()
        rejected(result_value=bad, code="result_archive_invalid")

    # Summary decisions are exact and canonically recomputed.
    for field, value in (
        ("family", "single_pass"),
        ("candidate_count", 15),
        ("particle_count", 2999),
        ("recoil_seed_count", 2),
        ("bootstrap_replicates", 9999),
        ("selection_sha256", "0" * 64),
    ):
        bad = dict(results)
        payload = json.loads(bad[summary_key])
        payload[field] = value
        bad[summary_key] = json.dumps(payload).encode()
        rejected(result_value=bad, code="summary_mismatch")
    bad = dict(results)
    payload = json.loads(bad[summary_key])
    payload["ranked_candidates"] = list(reversed(payload["ranked_candidates"]))
    bad[summary_key] = json.dumps(payload).encode()
    rejected(result_value=bad, code="summary_mismatch")

    # Evidence binds original bytes, not a normalized JSON representation.
    reformatted = dict(results)
    payload = json.loads(reformatted[record_key])
    reformatted[record_key] = json.dumps(payload, indent=4).encode() + b"\n"
    reformatted_validated = validate_refinement_result_bytes(
        manifest_raw,
        selections,
        reformatted,
        project_directory=project,
        campaign_absolute_path=remote,
    )
    assert reformatted_validated.hashes[record_key] != validated.hashes[record_key]
    assert reformatted_validated.evidence_sha256 != validated.evidence_sha256

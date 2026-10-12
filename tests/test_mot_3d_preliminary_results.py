import hashlib
import io
import json
import zipfile
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from workflow_api.mot_3d_preliminary_results import (
    EXPECTED_RESULT_FILES,
    PreliminaryResultError,
    expected_preliminary_particle_selection,
    expected_paths,
    validate_preliminary_result_bytes,
    _validate_npz_container,
    render_typescript_preliminary_result_contract,
)
from workflow_api.mot_3d_stage_topology import PRELIMINARY_CHECK_TOPOLOGY


def _selection(family):
    return {
        "family": family,
        "candidate_count": 12,
        "candidates": [
            {"candidate_id": f"{family}_candidate_{index:02d}"}
            for index in range(12)
        ],
    }


def test_preliminary_registry_is_exact_and_worker_partitioned():
    paths = expected_paths(
        {
            "angled_donut": _selection("angled_donut"),
            "single_pass": _selection("single_pass"),
        }
    )
    assert len(paths) == EXPECTED_RESULT_FILES == 152
    assert len(set(paths)) == len(paths)
    assert sum(path.endswith("particle_selection.json") for path in paths) == 6
    assert sum(path.endswith("early_check_summary.json") for path in paths) == 2
    assert sum(path.endswith(".npz") for path in paths) == 72
    assert sum(path.endswith(".json") for path in paths) == 80
    assert PRELIMINARY_CHECK_TOPOLOGY.jobs == {
        family: {
            "array": f"jobs/preliminary_check/{family}_array.pbs",
            "merge": f"jobs/preliminary_check/{family}_merge.pbs",
        }
        for family in ("angled_donut", "single_pass")
    }


def test_generated_ui_reason_contract_has_no_drift():
    artifact = Path("ui/src/generated/mot3dPreliminaryTransitionSpec.v1.ts")
    assert artifact.read_text() == render_typescript_preliminary_result_contract()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _closed_fixture(tmp_path):
    campaign_name = "campaign"
    remote = f"/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_3d/{campaign_name}"
    campaign = tmp_path / campaign_name
    campaign.mkdir()
    roles = []
    for index, seed in enumerate(range(3031, 3035)):
        roles.append(
            {
                "path": f"/home/tal.noa/ytterbium_lab_simulation_new/data/input_{seed}.npy",
                "metadata_path": f"/home/tal.noa/ytterbium_lab_simulation_new/data/input_{seed}.json",
                "sha256": f"{index + 1}" * 64,
                "metadata_sha256": f"{index + 5}" * 64,
                "zeeman_seed": seed,
                "mot_seed": 43000 + seed,
                "n_survivors": 200,
                "shape": [200, 6],
                "dtype": "float64",
                "source_git_commit": "a" * 40,
                "source_design": {},
                "source_parameters": {},
            }
        )
    manifest = {
        "name": campaign_name,
        "stage": "preliminary_check",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "design": {"screening_dt_s": 1e-5, "solver": "RK4StHybridCustom"},
        "input_roles": {"preliminary_check": roles},
        "stages": {
            "preliminary_check": {
                "classification": "candidate_selection_not_final_validation",
                "input_role": "preliminary_check",
            }
        },
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode() + b"\n"
    (campaign / "campaign.json").write_bytes(manifest_bytes)
    particle_selection = expected_preliminary_particle_selection(
        manifest, project_directory="/home/tal.noa/ytterbium_lab_simulation_new"
    )
    selections = {}
    result_files = {}
    for family in ("angled_donut", "single_pass"):
        selection = _selection(family)
        for candidate in selection["candidates"]:
            candidate["parameters"] = {}
            candidate["resolved_profile"] = {}
        selection_raw = json.dumps(selection, indent=2).encode() + b"\n"
        selections[family] = selection_raw
        selection_path = campaign / "selection" / "discovery" / f"{family}.json"
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_bytes(selection_raw)
        design = {
            "campaign_manifest_path": f"{remote}/campaign.json",
            "campaign_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "selection_path": f"{remote}/selection/discovery/{family}.json",
            "selection_sha256": hashlib.sha256(selection_raw).hexdigest(),
            "git_commit": "a" * 40,
            "physical_model_sha256": "b" * 64,
            "input_role": "preliminary_check",
            "input_role_sha256": hashlib.sha256(_canonical(roles)).hexdigest(),
            "dt_s": 1e-5,
            "t_max_s": 0.1,
            "solver": "RK4StHybridCustom",
            "particles_per_ensemble": 150,
            "selection_seed": 51001,
            "particle_selection_sha256": hashlib.sha256(
                _canonical(particle_selection)
            ).hexdigest(),
        }
        for worker in range(3):
            worker_root = campaign / "preliminary_check" / family / f"worker_{worker}"
            worker_root.mkdir(parents=True)
            particle_raw = json.dumps(particle_selection, indent=2).encode() + b"\n"
            (worker_root / "particle_selection.json").write_bytes(particle_raw)
            result_files[
                f"preliminary_check/{family}/worker_{worker}/particle_selection.json"
            ] = particle_raw
            for candidate in selection["candidates"][worker::3]:
                for seed in (41001, 41002, 41003):
                    stem = f"{candidate['candidate_id']}_seed_{seed}"
                    usable = np.zeros(600, dtype=bool)
                    usable[: (seed + worker) % 17] = True
                    ever = usable.copy()
                    groups = np.repeat(np.arange(4), 150)
                    archive_buffer = io.BytesIO()
                    np.savez_compressed(
                        archive_buffer,
                        usable_at_end=usable,
                        usable_ever=ever,
                        ensemble_ids=groups,
                    )
                    archive = archive_buffer.getvalue()
                    npz_path = worker_root / f"{stem}.npz"
                    npz_path.write_bytes(archive)
                    record = {
                        "kind": "mot_3d_early_independent_check_seed_result",
                        "family": family,
                        "candidate_id": candidate["candidate_id"],
                        "worker_index": worker,
                        "recoil_seed": seed,
                        "input_particle_count": 600,
                        "usable_at_end_count": int(usable.sum()),
                        "usable_ever_count": int(ever.sum()),
                        "peak_usable_count": int(usable.sum()),
                        "entered_capture_region_count": int(usable.sum()),
                        "slow_inside_count": int(usable.sum()),
                        "outcomes_path": str(npz_path),
                        "outcomes_sha256": hashlib.sha256(archive).hexdigest(),
                        "design": design,
                    }
                    json_path = worker_root / f"{stem}.json"
                    json_path.write_text(json.dumps(record, indent=2) + "\n")
        from studies.mot_3d.preliminary.merge import merge

        merge(
            Namespace(
                selection=str(selection_path),
                input_root=str(campaign / "preliminary_check" / family),
                output_dir=str(campaign / "preliminary_check" / family / "merged"),
                bootstrap_replicates=10000,
                bootstrap_seed=52001,
            )
        )
        for path in (campaign / "preliminary_check" / family).rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(campaign).as_posix()
            raw = path.read_bytes()
            if relative.endswith(".json") and "worker_" in relative and not relative.endswith(
                "particle_selection.json"
            ):
                record = json.loads(raw)
                record["outcomes_path"] = str(
                    Path(remote) / Path(relative).with_suffix(".npz")
                )
                raw = json.dumps(record, indent=2).encode() + b"\n"
            result_files[relative] = raw
    return manifest_bytes, selections, result_files, particle_selection, remote


@pytest.fixture(scope="module")
def closed_fixture(tmp_path_factory):
    """Build the expensive canonical 152-file registry once for mutations."""

    return _closed_fixture(tmp_path_factory.mktemp("preliminary-closed"))


def _validate_fixture(fixture, *, manifest=None, selections=None, results=None,
                      particle_selection=None):
    original_manifest, original_selections, original_results, original_particle, remote = fixture
    return validate_preliminary_result_bytes(
        manifest_bytes=original_manifest if manifest is None else manifest,
        selection_bytes=original_selections if selections is None else selections,
        result_files=original_results if results is None else results,
        expected_particle_selection=(
            original_particle if particle_selection is None else particle_selection
        ),
        campaign_absolute_path=remote,
        project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
    )


def _replace_npz(results, name, **arrays):
    with np.load(io.BytesIO(results[name]), allow_pickle=False) as archive:
        values = {key: archive[key].copy() for key in archive.files}
    values.update(arrays)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **values)
    results[name] = buffer.getvalue()
    record_name = name[:-4] + ".json"
    record = json.loads(results[record_name])
    record["outcomes_sha256"] = hashlib.sha256(results[name]).hexdigest()
    results[record_name] = json.dumps(record).encode()


def test_full_captured_registry_validates_and_preserves_original_hashes(tmp_path):
    manifest, selections, results, particle_selection, remote = _closed_fixture(tmp_path)
    validated = validate_preliminary_result_bytes(
        manifest_bytes=manifest,
        selection_bytes=selections,
        result_files=results,
        expected_particle_selection=particle_selection,
        campaign_absolute_path=remote,
        project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
    )
    assert len(validated.paths) == 152
    assert validated.sha256 == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in results.items()
    }


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("manifest_dt", "design_mismatch"),
        ("selection_duplicate", "selection_mismatch"),
        ("design_extra", "design_mismatch"),
        ("design_solver", "design_mismatch"),
        ("record_extra", "result_metadata_mismatch"),
        ("record_worker_bool", "result_metadata_mismatch"),
        ("record_recoil_float", "result_registry_invalid"),
        ("record_count_relation", "result_metadata_mismatch"),
        ("record_bad_outcome", "result_metadata_mismatch"),
        ("record_bad_digest", "result_registry_invalid"),
        ("npz_wrong_dtype", "result_archive_invalid"),
        ("npz_wrong_shape", "result_registry_invalid"),
        ("npz_wrong_groups", "result_archive_invalid"),
        ("summary_ranking", "summary_mismatch"),
        ("summary_nonfinite", "malformed_json"),
        ("json_duplicate_key", "malformed_json"),
    ],
)
def test_scientific_trust_boundary_mutations_fail_closed(closed_fixture, mutation, code):
    manifest, selections, original_results, particle_selection, _ = closed_fixture
    results = dict(original_results)
    selections = dict(selections)
    if mutation == "manifest_dt":
        value = json.loads(manifest)
        value["design"]["screening_dt_s"] = 2e-5
        manifest = json.dumps(value).encode()
    elif mutation == "selection_duplicate":
        value = json.loads(selections["angled_donut"])
        value["candidates"][1]["candidate_id"] = value["candidates"][0]["candidate_id"]
        selections["angled_donut"] = json.dumps(value).encode()
    elif mutation.startswith("design_"):
        name = next(
            name for name in results
            if name.endswith(".json") and "worker_" in name
            and not name.endswith("particle_selection.json")
        )
        value = json.loads(results[name])
        if mutation == "design_extra":
            value["design"]["unreviewed"] = True
        else:
            value["design"]["solver"] = "unreviewed"
        results[name] = json.dumps(value).encode()
    elif mutation.startswith("record_"):
        name = next(
            name for name in results
            if name.endswith(".json") and "worker_" in name
            and not name.endswith("particle_selection.json")
        )
        value = json.loads(results[name])
        if mutation == "record_extra":
            value["extra"] = 1
        elif mutation == "record_worker_bool":
            value["worker_index"] = True
        elif mutation == "record_recoil_float":
            value["recoil_seed"] = float(value["recoil_seed"])
        elif mutation == "record_count_relation":
            value["slow_inside_count"] = value["entered_capture_region_count"] + 1
        elif mutation == "record_bad_outcome":
            value["outcomes_path"] = "/attacker/result.npz"
        else:
            value["outcomes_sha256"] = "0" * 64
        results[name] = json.dumps(value).encode()
    elif mutation.startswith("npz_"):
        name = next(name for name in results if name.endswith(".npz"))
        with np.load(io.BytesIO(results[name]), allow_pickle=False) as archive:
            usable = archive["usable_at_end"].copy()
            ever = archive["usable_ever"].copy()
            groups = archive["ensemble_ids"].copy()
        if mutation == "npz_wrong_dtype":
            usable = usable.astype(np.uint8)
        elif mutation == "npz_wrong_shape":
            usable = usable[:-1]
        else:
            groups[:] = 0
        _replace_npz(
            results, name, usable_at_end=usable, usable_ever=ever, ensemble_ids=groups
        )
    elif mutation.startswith("summary_"):
        name = next(name for name in results if name.endswith("early_check_summary.json"))
        value = json.loads(results[name])
        if mutation == "summary_ranking":
            value["ranked_candidates"][0]["candidate_id"] = "foreign"
            results[name] = json.dumps(value).encode()
        else:
            results[name] = json.dumps(value).replace("{", '{"bad":NaN,', 1).encode()
    else:
        name = next(
            name for name in results
            if name.endswith(".json") and "worker_" in name
            and not name.endswith("particle_selection.json")
        )
        results[name] = results[name].replace(b'{\n  "kind"', b'{\n  "kind":"x",\n  "kind"', 1)
    with pytest.raises(PreliminaryResultError) as error:
        _validate_fixture(
            closed_fixture,
            manifest=manifest,
            selections=selections,
            results=results,
            particle_selection=particle_selection,
        )
    assert error.value.code == code


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("extra", "artifact_registry_mismatch"),
        ("particle", "particle_selection_mismatch"),
        ("usable_subset", "result_archive_invalid"),
        ("summary", "summary_mismatch"),
    ],
)
def test_captured_registry_mutations_fail_closed(tmp_path, mutation, code):
    manifest, selections, results, particle_selection, remote = _closed_fixture(tmp_path)
    results = dict(results)
    if mutation == "extra":
        results["preliminary_check/extra"] = b"x"
    elif mutation == "particle":
        name = next(name for name in results if name.endswith("particle_selection.json"))
        results[name] = b"[]\n"
    elif mutation == "summary":
        name = next(name for name in results if name.endswith("early_check_summary.json"))
        row = json.loads(results[name])
        row["bootstrap_seed"] = 1
        results[name] = json.dumps(row).encode()
    else:
        npz_name = next(name for name in results if name.endswith(".npz"))
        with np.load(io.BytesIO(results[npz_name]), allow_pickle=False) as archive:
            usable = archive["usable_at_end"].copy()
            ever = archive["usable_ever"].copy()
            groups = archive["ensemble_ids"].copy()
        usable[0] = True
        ever[0] = False
        buffer = io.BytesIO()
        np.savez_compressed(buffer, usable_at_end=usable, usable_ever=ever, ensemble_ids=groups)
        results[npz_name] = buffer.getvalue()
        json_name = npz_name[:-4] + ".json"
        record = json.loads(results[json_name])
        record["outcomes_sha256"] = hashlib.sha256(results[npz_name]).hexdigest()
        record["usable_at_end_count"] = int(usable.sum())
        record["usable_ever_count"] = int(ever.sum())
        results[json_name] = json.dumps(record).encode()
    with pytest.raises(PreliminaryResultError) as error:
        validate_preliminary_result_bytes(
            manifest_bytes=manifest,
            selection_bytes=selections,
            result_files=results,
            expected_particle_selection=particle_selection,
            campaign_absolute_path=remote,
            project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
        )
    assert error.value.code == code


@pytest.mark.parametrize(
    "path",
    [
        "/home/tal.noa/ytterbium_lab_simulation_new/../ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign",
        "/home//tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign",
        "/attacker/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign",
    ],
)
def test_campaign_path_must_be_exactly_profile_bound(tmp_path, path):
    manifest, selections, results, particle_selection, _ = _closed_fixture(tmp_path)
    with pytest.raises(PreliminaryResultError):
        validate_preliminary_result_bytes(
            manifest_bytes=manifest,
            selection_bytes=selections,
            result_files=results,
            expected_particle_selection=particle_selection,
            campaign_absolute_path=path,
            project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
        )


def test_npz_container_rejects_duplicate_members():
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("usable_at_end.npy", b"one")
        archive.writestr("usable_at_end.npy", b"two")
        archive.writestr("usable_ever.npy", b"three")
        archive.writestr("ensemble_ids.npy", b"four")
    with pytest.raises(PreliminaryResultError):
        _validate_npz_container(buffer.getvalue())


@pytest.mark.parametrize(
    "field,value",
    [
        ("n_survivors", True),
        ("n_survivors", 200.0),
        ("zeeman_seed", "3031"),
        ("mot_seed", -1),
        ("sha256", "g" * 64),
        ("metadata_sha256", "0" * 63),
        ("shape", [200, 3]),
        ("dtype", "float32"),
        ("source_git_commit", "0" * 39),
        ("path", "/home/tal.noa/ytterbium_lab_simulation_new/../escape.npy"),
        ("metadata_path", "/home/tal.noa/ytterbium_lab_simulation_new/data/not-a-sibling.json"),
    ],
)
def test_particle_selection_rejects_permissive_frozen_role_values(
    closed_fixture, field, value
):
    manifest_raw, _, _, _, _ = closed_fixture
    manifest = json.loads(manifest_raw)
    manifest["input_roles"]["preliminary_check"][0][field] = value
    with pytest.raises(PreliminaryResultError) as error:
        expected_preliminary_particle_selection(
            manifest,
            project_directory="/home/tal.noa/ytterbium_lab_simulation_new",
        )
    assert error.value.code == "particle_selection_mismatch"


def test_particle_selection_rejects_extra_role_key_and_wrong_order(closed_fixture):
    manifest_raw, _, _, _, _ = closed_fixture
    manifest = json.loads(manifest_raw)
    manifest["input_roles"]["preliminary_check"][0]["extra"] = True
    with pytest.raises(PreliminaryResultError):
        expected_preliminary_particle_selection(
            manifest, project_directory="/home/tal.noa/ytterbium_lab_simulation_new"
        )
    manifest = json.loads(manifest_raw)
    manifest["input_roles"]["preliminary_check"].reverse()
    with pytest.raises(PreliminaryResultError):
        expected_preliminary_particle_selection(
            manifest, project_directory="/home/tal.noa/ytterbium_lab_simulation_new"
        )


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_npz_container_rejects_unapproved_compression(compression):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name in ("usable_at_end.npy", "usable_ever.npy", "ensemble_ids.npy"):
            archive.writestr(name, b"x")
    with pytest.raises(PreliminaryResultError) as error:
        _validate_npz_container(buffer.getvalue())
    assert error.value.code == "result_archive_invalid"


def test_npz_container_rejects_member_expansion_cap():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("usable_at_end.npy", b"x" * (128 * 1024 + 1))
        archive.writestr("usable_ever.npy", b"x")
        archive.writestr("ensemble_ids.npy", b"x")
    with pytest.raises(PreliminaryResultError) as error:
        _validate_npz_container(buffer.getvalue())
    assert error.value.code == "result_archive_invalid"


def test_pure_particle_provenance_matches_legacy_sampler(monkeypatch, tmp_path):
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    _, _, _, expected, _ = _closed_fixture(fixture_root)
    manifest = {
        "input_roles": {
            "preliminary_check": [
                {
                    "path": row["file"],
                    "metadata_path": str(Path(row["file"]).with_suffix(".json")),
                    "metadata_sha256": str(index + 5) * 64,
                    "sha256": row["array_sha256"],
                    "shape": [row["available_count"], 6],
                    "dtype": "float64",
                    "zeeman_seed": row["zeeman_seed"],
                    "mot_seed": row["mot_seed"],
                    "n_survivors": row["available_count"],
                    "source_git_commit": "a" * 40,
                    "source_design": {},
                    "source_parameters": {},
                }
                for index, row in enumerate(expected)
            ]
        }
    }
    from studies import mot_3d_campaign

    monkeypatch.setattr(
        mot_3d_campaign,
        "validate_frozen_inputs",
        lambda *_args, **_kwargs: manifest["input_roles"]["preliminary_check"],
    )
    monkeypatch.setattr(
        mot_3d_campaign,
        "load_particle_states",
        lambda _path: np.zeros((200, 6)),
    )
    manifest_path = tmp_path / "campaign.json"
    manifest_path.write_text(json.dumps(manifest))
    _, _, legacy = mot_3d_campaign.load_role_particles(
        manifest_path, "preliminary_check", 150, 51001
    )
    assert expected_preliminary_particle_selection(
        manifest, project_directory="/home/tal.noa/ytterbium_lab_simulation_new"
    ) == legacy


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaign_manifest_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("git_commit", "0" * 40),
        ("physical_model_sha256", "0" * 64),
        ("input_role_sha256", "0" * 64),
        ("particle_selection_sha256", "0" * 64),
        ("dt_s", 2e-5),
        ("t_max_s", 0.2),
        ("particles_per_ensemble", 151),
        ("selection_seed", 51002),
    ],
)
def test_every_frozen_design_binding_is_enforced(closed_fixture, field, value):
    _, _, original_results, _, _ = closed_fixture
    results = dict(original_results)
    name = next(
        name
        for name in results
        if name.endswith(".json")
        and "worker_" in name
        and not name.endswith("particle_selection.json")
    )
    record = json.loads(results[name])
    record["design"][field] = value
    results[name] = json.dumps(record).encode()

    with pytest.raises(PreliminaryResultError) as error:
        _validate_fixture(closed_fixture, results=results)
    assert error.value.code == "design_mismatch"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("manifest_duplicate", "malformed_json"),
        ("manifest_nonfinite", "malformed_json"),
        ("selection_duplicate_key", "malformed_json"),
        ("selection_unsafe_candidate", "selection_mismatch"),
        ("result_missing_key", "result_metadata_mismatch"),
        ("result_input_bool", "result_registry_invalid"),
        ("result_peak_below_end", "result_metadata_mismatch"),
        ("result_slow_above_entered", "result_metadata_mismatch"),
        ("summary_metric", "summary_mismatch"),
    ],
)
def test_json_schema_and_count_math_mutations_fail_closed(
    closed_fixture, mutation, code
):
    manifest, original_selections, original_results, _, _ = closed_fixture
    selections = dict(original_selections)
    results = dict(original_results)
    if mutation == "manifest_duplicate":
        manifest = manifest.replace(b'{\n  "name"', b'{\n  "name":"other",\n  "name"', 1)
    elif mutation == "manifest_nonfinite":
        manifest = manifest.replace(b'{\n  "name"', b'{\n  "unreviewed":NaN,\n  "name"', 1)
    elif mutation == "selection_duplicate_key":
        selections["angled_donut"] = selections["angled_donut"].replace(
            b'{\n  "family"', b'{\n  "family":"other",\n  "family"', 1
        )
    elif mutation == "selection_unsafe_candidate":
        selection = json.loads(selections["angled_donut"])
        selection["candidates"][0]["candidate_id"] = "../escape"
        selections["angled_donut"] = json.dumps(selection).encode()
    elif mutation == "summary_metric":
        name = next(
            name for name in results if name.endswith("early_check_summary.json")
        )
        summary = json.loads(results[name])
        summary["ranked_candidates"][0]["mean_usable_fraction"] += 0.01
        results[name] = json.dumps(summary).encode()
    else:
        name = next(
            name
            for name in results
            if name.endswith(".json")
            and "worker_" in name
            and not name.endswith("particle_selection.json")
        )
        record = json.loads(results[name])
        if mutation == "result_missing_key":
            del record["peak_usable_count"]
        elif mutation == "result_input_bool":
            record["input_particle_count"] = True
        elif mutation == "result_peak_below_end":
            record["peak_usable_count"] = record["usable_at_end_count"] - 1
        else:
            record["slow_inside_count"] = record["entered_capture_region_count"] + 1
        results[name] = json.dumps(record).encode()

    with pytest.raises(PreliminaryResultError) as error:
        _validate_fixture(
            closed_fixture,
            manifest=manifest,
            selections=selections,
            results=results,
        )
    assert error.value.code == code


@pytest.mark.parametrize(
    "mutation",
    ["ensemble_dtype", "ensemble_shape", "ensemble_balance", "usable_ever_dtype"],
)
def test_npz_scientific_array_contract_is_exact(closed_fixture, mutation):
    _, _, original_results, _, _ = closed_fixture
    results = dict(original_results)
    name = next(name for name in results if name.endswith(".npz"))
    with np.load(io.BytesIO(results[name]), allow_pickle=False) as archive:
        usable = archive["usable_at_end"].copy()
        ever = archive["usable_ever"].copy()
        groups = archive["ensemble_ids"].copy()
    if mutation == "ensemble_dtype":
        groups = groups.astype(float)
    elif mutation == "ensemble_shape":
        groups = groups.reshape(20, 30)
    elif mutation == "ensemble_balance":
        groups[0] = 1
    else:
        ever = ever.astype(np.uint8)
    _replace_npz(
        results,
        name,
        usable_at_end=usable,
        usable_ever=ever,
        ensemble_ids=groups,
    )

    with pytest.raises(PreliminaryResultError) as error:
        _validate_fixture(closed_fixture, results=results)
    assert error.value.code in {"result_archive_invalid", "result_registry_invalid"}

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
import workflow_api.mot_2d_individual_sources as catalog
import workflow_api.mot_2d_sources as campaign_sources
from workflow_api.mot_2d_sources import SourceScanLimits, list_sources
from workflow_api.run_discovery import DiscoverySnapshot, DiscoveredRun


def _canonical_folder(root: Path, name: str = "source") -> Path:
    directory = root / "data/particle_states/after_zeeman" / name
    directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field = {
        key: list(profile[key])
        for key in ("radii_m", "positions_m", "tilt_angles_deg")
    }
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.full((seed % 3 + 1, 6), seed, dtype=np.float64))
        digest = hashlib.sha256(state.read_bytes()).hexdigest()
        metadata = {
            "shape": list(np.load(state, mmap_mode="r").shape),
            "dtype": "float64",
            "n_survivors": seed % 3 + 1,
            "output_sha256": digest,
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "parameters": {
                "seed": seed,
                "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                "n_initial_atoms": 50_000,
                "dt_s": 4e-5,
                "zeeman_field_config": field,
            },
            "software": {"git_commit": "a" * 40},
        }
        state.with_suffix(".json").write_text(json.dumps(metadata))
    return directory


def _retained_inspection(
    *,
    survivors: int = 7,
    suitability: str = "individual_only",
    run_id: str = "private-run-name",
    completed: str = "2026-10-11T10:00:00+00:00",
):
    state = SimpleNamespace(
        sha256="d" * 64,
        size_bytes=1024,
        shape=(survivors, 6),
        dtype="float64",
        survivor_count=survivors,
    )
    publication = SimpleNamespace(results_sha256="e" * 64, state_array=state)
    return SimpleNamespace(
        family="zeeman",
        run_id=run_id,
        state="succeeded",
        integrity="complete_verified",
        run={
            "configuration_sha256": "b" * 64,
            "inputs_sha256": "c" * 64,
            "retention": {"particle_states": True},
        },
        results={
            "states_retained": True,
            "suitability": suitability,
            "completed_utc": completed,
            "metrics": {"n_survivors": survivors},
        },
        publication=publication,
        configuration={
            "resolved": {
                "zeeman": {
                    "magnet_profile_name": "production-profile",
                    "laser": {"s0": 2.4, "detuning_gamma": -7.3},
                }
            }
        },
    )


def test_catalog_exposes_validated_folder_without_path_or_seed_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _canonical_folder(root, "zeeman source (reviewed) 🚀")

    result = catalog.list_individual_mot_2d_sources(root)

    assert result["contract_version"] == catalog.CATALOG_VERSION
    assert result["total"] == 1
    assert result["invalid_count"] == 0
    assert result["truncated"] is False
    source = result["sources"][0]
    assert source["source_kind"] == "canonical_folder"
    assert source["label"] == "zeeman source reviewed"
    assert source["ensemble_count"] == 35
    assert source["available_particle_count"] == {
        "pooled": 69,
        "minimum_per_ensemble": 1,
        "maximum_per_ensemble": 3,
    }
    assert source["source_qualification"] == "canonical_campaign_source"
    assert source["result_suitability"] == "individual_only"
    assert source["id"].startswith("mot2d-source-")
    rendered = json.dumps(result)
    assert "data/particle_states" not in rendered
    assert "production_zeeman" not in rendered
    assert "🚀" not in rendered


def test_catalog_id_binds_attested_folder_contents_and_order_is_stable(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    first = _canonical_folder(root, "zeta")
    _canonical_folder(root, "alpha")
    before = catalog.list_individual_mot_2d_sources(root)
    assert [row["label"] for row in before["sources"]] == ["alpha", "zeta"]
    assert catalog.list_individual_mot_2d_sources(root) == before

    state = first / "production_zeeman_n50000_dt40us_seed3000.npy"
    np.save(state, np.ones((2, 6), dtype=np.float64))
    metadata = json.loads(state.with_suffix(".json").read_text())
    metadata.update(
        shape=[2, 6],
        n_survivors=2,
        output_sha256=hashlib.sha256(state.read_bytes()).hexdigest(),
    )
    state.with_suffix(".json").write_text(json.dumps(metadata))
    after = catalog.list_individual_mot_2d_sources(root)
    old = next(row for row in before["sources"] if row["label"] == "zeta")
    new = next(row for row in after["sources"] if row["label"] == "zeta")
    assert new["id"] != old["id"]
    assert new["provenance"]["fingerprint"] != old["provenance"]["fingerprint"]


def test_default_campaign_source_schema_is_unchanged(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _canonical_folder(root)
    result = list_sources(root)
    assert set(result) == {"sources", "invalid_count", "total"}
    assert set(result["sources"][0]) == {
        "id",
        "path",
        "profile",
        "ensemble_count",
        "minimum_survivors",
        "maximum_survivors",
        "fingerprint",
    }


def test_zero_particle_sources_are_rejected_for_both_source_kinds(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    directory = _canonical_folder(root)
    for state in directory.glob("*.npy"):
        np.save(state, np.empty((0, 6), dtype=np.float64))
        metadata = json.loads(state.with_suffix(".json").read_text())
        metadata.update(
            shape=[0, 6],
            n_survivors=0,
            output_sha256=hashlib.sha256(state.read_bytes()).hexdigest(),
        )
        state.with_suffix(".json").write_text(json.dumps(metadata))
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["sources"] == []
    assert result["invalid_count"] == 1

    directory.rename(tmp_path / "removed")
    record = DiscoveredRun(
        "zeeman", "zero", "data/runs/zeeman/zero", "succeeded",
        "complete_verified", None,
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot((record,), False),
    )
    monkeypatch.setattr(
        catalog, "inspect_run", lambda *_args: _retained_inspection(survivors=0)
    )
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["sources"] == []
    assert result["invalid_count"] == 1


@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    [
        ("maximum_file_bytes", 32),
        ("maximum_total_bytes", 1_000),
        ("maximum_rows_per_file", 1),
        ("maximum_total_rows", 40),
        ("maximum_npy_header_bytes", 16),
    ],
)
def test_interactive_catalog_applies_file_aggregate_row_and_header_bounds(
    tmp_path, monkeypatch, limit_name, limit_value
):
    root = tmp_path / "repo"
    root.mkdir()
    _canonical_folder(root)
    values = {
        "maximum_file_bytes": 512 * 1024 * 1024,
        "maximum_total_bytes": 8 * 1024 * 1024 * 1024,
        "maximum_rows_per_file": 2_000_000,
        "maximum_total_rows": 70_000_000,
        "maximum_npy_header_bytes": 64 * 1024,
    }
    values[limit_name] = limit_value
    monkeypatch.setattr(catalog, "_INTERACTIVE_LIMITS", SourceScanLimits(**values))
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["sources"] == []
    assert result["invalid_count"] == 1


def test_malformed_npy_and_sparse_oversized_file_fail_before_state_scan(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    directory = _canonical_folder(root)
    state = directory / "production_zeeman_n50000_dt40us_seed3000.npy"
    state.write_bytes(b"not-npy")
    assert catalog.list_individual_mot_2d_sources(root)["sources"] == []

    directory = tmp_path / "replacement"
    (root / "data/particle_states/after_zeeman/source").rename(directory)
    _canonical_folder(root)
    state = root / "data/particle_states/after_zeeman/source/production_zeeman_n50000_dt40us_seed3000.npy"
    with state.open("r+b") as stream:
        stream.truncate(1024 * 1024)
    limits = SourceScanLimits(
        maximum_file_bytes=100_000,
        maximum_total_bytes=8 * 1024 * 1024,
        maximum_rows_per_file=2_000_000,
        maximum_total_rows=70_000_000,
        maximum_npy_header_bytes=64 * 1024,
    )
    monkeypatch.setattr(catalog, "_INTERACTIVE_LIMITS", limits)
    assert catalog.list_individual_mot_2d_sources(root)["sources"] == []


@pytest.mark.parametrize("attack", ["symlink_folder", "symlink_state", "bad_hash", "missing_seed"])
def test_catalog_never_admits_untrusted_or_incomplete_folders(tmp_path, attack):
    root = tmp_path / "repo"
    root.mkdir()
    directory = _canonical_folder(root, "valid")
    source_root = directory.parent
    if attack == "symlink_folder":
        outside = tmp_path / "outside"
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
    elif attack == "symlink_state":
        state = directory / "production_zeeman_n50000_dt40us_seed3000.npy"
        outside = tmp_path / "state.npy"
        state.rename(outside)
        state.symlink_to(outside)
    elif attack == "bad_hash":
        state = directory / "production_zeeman_n50000_dt40us_seed3000.npy"
        with state.open("ab") as stream:
            stream.write(b"tamper")
    else:
        (directory / "production_zeeman_n50000_dt40us_seed3000.npy").unlink()
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["sources"] == []
    # Symlink folders are ignored rather than treated as candidate sources.
    assert result["invalid_count"] in {0, 1}
    assert str(source_root) not in json.dumps(result)


def test_only_complete_retained_individual_zeeman_results_are_offered(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    record = DiscoveredRun(
        "zeeman",
        "private-run-name",
        "data/runs/zeeman/private-run-name",
        "succeeded",
        "complete_verified",
        None,
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot((record,), False),
    )
    monkeypatch.setattr(catalog, "inspect_run", lambda *_args: _retained_inspection())

    result = catalog.list_individual_mot_2d_sources(root)

    assert result["total"] == 1
    source = result["sources"][0]
    assert source == {
        "id": source["id"],
        "source_kind": "retained_individual_zeeman",
        "label": source["label"],
        "ensemble_count": 1,
        "available_particle_count": {
            "pooled": 7,
            "minimum_per_ensemble": 7,
            "maximum_per_ensemble": 7,
        },
        "source_qualification": "verified_individual_result",
        "result_suitability": "individual_only",
        "provenance": {
            "validation": "verified_retained_individual_result",
            "completed_at": "2026-10-11T10:00:00+00:00",
            "public_run_id": source["provenance"]["public_run_id"],
            "scientific_summary": {
                "profile": "production-profile",
                "laser_s0": 2.4,
                "laser_detuning_gamma": -7.3,
            },
            "fingerprint": source["provenance"]["fingerprint"],
        },
    }
    assert "private-run-name" not in json.dumps(result)
    assert source["provenance"]["public_run_id"].startswith("individual-run-")
    assert source["provenance"]["public_run_id"][-24:-16] in source["label"]

    monkeypatch.setattr(
        catalog,
        "inspect_run",
        lambda *_args: _retained_inspection(suitability="campaign_input"),
    )
    assert catalog.list_individual_mot_2d_sources(root)["sources"] == []


def test_retained_sources_have_stable_unique_safe_labels_and_summaries(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    records = tuple(
        DiscoveredRun(
            "zeeman", run_id, f"data/runs/zeeman/{run_id}", "succeeded",
            "complete_verified", None,
        )
        for run_id in ("secret-alpha", "secret-beta")
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot(records, False),
    )
    monkeypatch.setattr(
        catalog,
        "inspect_run",
        lambda _root, _family, run_id: _retained_inspection(
            run_id=run_id,
            completed=(
                "2026-10-10T10:00:00+00:00"
                if run_id.endswith("alpha")
                else "2026-10-11T10:00:00+00:00"
            ),
        ),
    )
    first = catalog.list_individual_mot_2d_sources(root)
    second = catalog.list_individual_mot_2d_sources(root)
    assert first == second
    assert first["total"] == 2
    assert len({row["id"] for row in first["sources"]}) == 2
    assert len({row["label"] for row in first["sources"]}) == 2
    rendered = json.dumps(first)
    assert "secret-alpha" not in rendered and "secret-beta" not in rendered
    assert all(
        row["provenance"]["scientific_summary"] == {
            "profile": "production-profile",
            "laser_s0": 2.4,
            "laser_detuning_gamma": -7.3,
        }
        for row in first["sources"]
    )


def test_active_unretained_and_other_family_runs_are_not_sources(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    records = (
        DiscoveredRun("zeeman", "active", "x", "running", "active", None),
        DiscoveredRun("mot_2d", "other", "y", "succeeded", "complete_verified", None),
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot(records, True),
    )
    active = _retained_inspection()
    active.state = "running"
    monkeypatch.setattr(catalog, "inspect_run", lambda *_args: active)
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["sources"] == []
    assert result["truncated"] is True


def test_component_discovery_is_bounded_and_duplicate_ids_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    seen = {}

    def snapshot(_root, *, maximum_runs):
        seen["maximum_runs"] = maximum_runs
        return DiscoverySnapshot((), False)

    monkeypatch.setattr(catalog, "discover_run_snapshot", snapshot)
    assert catalog.list_individual_mot_2d_sources(root)["total"] == 0
    assert seen == {"maximum_runs": catalog.MAX_INDIVIDUAL_RUNS}

    duplicate = {
        "id": "mot2d-source-" + "a" * 32,
        "source_kind": "canonical_folder",
        "label": "same",
    }
    monkeypatch.setattr(catalog, "_canonical_options", lambda _root: ([duplicate], 0, False))
    monkeypatch.setattr(catalog, "_retained_options", lambda _root: ([duplicate], 0, False))
    with pytest.raises(RuntimeError, match="duplicate identities"):
        catalog.list_individual_mot_2d_sources(root)


def test_truncation_is_not_misreported_as_invalid(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _canonical_folder(root, "first")
    _canonical_folder(root, "second")
    monkeypatch.setattr(campaign_sources, "MAX_SOURCES", 1)
    result = catalog.list_individual_mot_2d_sources(root)
    assert result["total"] == 1
    assert result["invalid_count"] == 0
    assert result["truncated"] is True


def test_legacy_default_preserves_raw_islice_and_pre_filter_overflow_semantics(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    source_root = root / "data/particle_states/after_zeeman"
    source_root.mkdir(parents=True)
    directories = []
    for index in range(129):
        directory = source_root / f"candidate-{index:03d}"
        directory.mkdir()
        directories.append(directory)

    calls = []

    def inspect(directory, repository_root, *, include_records=False, scan_limits=None):
        calls.append(directory.name)
        return {
            "id": directory.name,
            "path": directory.relative_to(repository_root).as_posix(),
            "profile": "profile",
            "ensemble_count": 35,
            "minimum_survivors": 1,
            "maximum_survivors": 1,
            "fingerprint": "f" * 64,
        }

    monkeypatch.setattr(campaign_sources, "inspect_source", inspect)
    legacy = list_sources(root)
    assert set(legacy) == {"sources", "invalid_count", "total"}
    assert legacy["total"] == 128
    assert legacy["invalid_count"] == 1
    assert len(calls) == 128
    assert set(calls).issubset({directory.name for directory in directories})

    # This second exact-HEAD case demonstrates that ignored raw entries do
    # consume the legacy islice bound.  They are not invalid themselves, but
    # can prevent later candidates from being observed.
    ignored_root = tmp_path / "ignored-repo"
    ignored_source = ignored_root / "data/particle_states/after_zeeman"
    ignored_source.mkdir(parents=True)
    ignored_entries = []
    for index in range(127):
        entry = ignored_source / f".{index:03d}"
        entry.mkdir()
        ignored_entries.append(entry)
    ordinary = ignored_source / "ordinary-file"
    ordinary.write_text("ignored")
    ignored_entries.append(ordinary)
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink = ignored_source / "symlink"
    symlink.symlink_to(outside, target_is_directory=True)
    ignored_entries.append(symlink)
    visible = ignored_source / "visible"
    visible.mkdir()
    original_iterdir = Path.iterdir

    def ordered_iterdir(path):
        if path == ignored_source:
            return iter([*ignored_entries, visible])
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", ordered_iterdir)
    calls.clear()
    ignored_result = list_sources(ignored_root)
    assert ignored_result == {"sources": [], "invalid_count": 0, "total": 0}
    assert calls == []

    calls.clear()

    def inspect_pooled(directory, repository_root, *, include_records=False, scan_limits=None):
        row = inspect(
            directory,
            repository_root,
            include_records=include_records,
            scan_limits=scan_limits,
        )
        row["records"] = [{"survivor_count": 1}]
        return row

    monkeypatch.setattr(campaign_sources, "inspect_source", inspect_pooled)
    interactive = list_sources(root, include_pool_counts=True)
    assert interactive["total"] == 128
    assert interactive["invalid_count"] == 0
    assert interactive["truncated"] is True
    assert len(calls) == 128

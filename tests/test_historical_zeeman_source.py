"""Regression against the actual distributed historical bank, never relabelled."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lab_setup.historical_zeeman_source import historical_source_evidence
from workflow_api.mot_2d_sources import inspect_source
from workflow_api.mot_2d_spec import ROLE_SEEDS, build_manifest
from workflow_api.mot_2d_validation import modern_contract
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.mot_2d_plan import build_plan, RELEVANT_FILES, materialize

ROOT = Path(__file__).resolve().parents[1]
BANK = Path("data/particle_states/after_zeeman/corrected_projectant_19ring_20261005")


@pytest.fixture(scope="module")
def source():
    return inspect_source(ROOT / BANK, ROOT, include_records=True)


@pytest.fixture
def checkout(tmp_path):
    shutil.copytree(ROOT / BANK, tmp_path / BANK)
    for relative in RELEVANT_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def plan(root):
    source = inspect_source(root / BANK, root)
    return build_plan(root, name="Historical source regression", slug="historical-source-regression",
                      s0_values=[1.35], source=source, snapshot=RepositorySnapshot("a" * 40))


def test_original_bank_creates_honest_portable_campaign_and_runner_inputs(checkout, monkeypatch):
    import studies.mot_2d_s0_campaign as runner
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (checkout / BANK).iterdir()}
    created = plan(checkout)
    manifest = created.manifest
    assert modern_contract(manifest, checkout) == (True, ())
    source = manifest["ensemble_source"]
    assert source["historical_evidence"]["id"] == "corrected-19ring-original-35-ensembles-v1"
    assert not {"laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"}.intersection(source)
    assert all(row["legacy_attested_profile"] is True for rows in manifest["input_ensembles"].values() for row in rows)
    materialize(created)
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", checkout)
    loaded = runner.stage_ensembles(manifest, "smoke", 2)
    assert len(loaded) == 5
    assert all(row["states"].shape == (2, 6) for row in loaded)
    cli_inputs = runner.freeze_input_ensembles(checkout / BANK, source["zeeman_profile"], ROLE_SEEDS)
    assert historical_source_evidence([row for rows in cli_inputs.values() for row in rows]) == source["historical_evidence"]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (checkout / BANK).iterdir()}
    assert after == before


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("metadata_sha256", "0" * 64),
    ("source_git_commit", "a" * 40), ("zeeman_seed", True),
    ("legacy_attested_profile", False), ("survivor_count", 1),
    ("laboratory_spec_version", "invented"),
])
def test_original_evidence_rejects_changed_records(source, field, value):
    records = copy.deepcopy(source["records"])
    records[0][field] = value
    with pytest.raises(ValueError, match="cannot create a new campaign"):
        historical_source_evidence(records)


def test_original_evidence_rejects_subset(source):
    with pytest.raises(ValueError):
        historical_source_evidence(source["records"][:-1])


def test_historical_identity_cannot_be_forged_or_relabelled(checkout):
    manifest = plan(checkout).manifest
    for mutate in (
        lambda source: source["historical_evidence"].update(source_fingerprint="0" * 64),
        lambda source: source.update(laboratory_spec_version="invented"),
    ):
        changed = copy.deepcopy(manifest)
        mutate(changed["ensemble_source"])
        assert not modern_contract(changed, checkout)[0]
    metadata = next((checkout / BANK).glob("*.json"))
    original = json.loads(metadata.read_text())
    original["elapsed_seconds"] += 1
    metadata.write_text(json.dumps(original))
    assert not modern_contract(manifest, checkout)[0]
    with pytest.raises(ValueError, match="cannot create a new campaign"):
        plan(checkout)


def test_state_corruption_rejected_by_existing_scientific_validation(checkout):
    manifest = plan(checkout).manifest
    state = next((checkout / BANK).glob("*.npy"))
    content = bytearray(state.read_bytes())
    content[-1] ^= 1
    state.write_bytes(content)
    assert not modern_contract(manifest, checkout)[0]
    with pytest.raises(ValueError):
        plan(checkout)


def test_original_scientific_bank_cannot_be_relabelled_test_only(source):
    records = {row["zeeman_seed"]: row for row in source["records"]}
    with pytest.raises(ValueError, match="TEST ONLY"):
        build_manifest(name="Forbidden", s0_values=[1.35], ensemble_directory=str(BANK),
                       zeeman_profile=source["profile"],
                       frozen_inputs={role: [records[seed] for seed in seeds] for role, seeds in ROLE_SEEDS.items()},
                       git_commit="a" * 40, physical_model_sha256="b" * 64, hashed_files=[],
                       acceptance_profile_id="ui_acceptance_v1")

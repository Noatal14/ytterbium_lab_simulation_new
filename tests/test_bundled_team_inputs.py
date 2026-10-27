"""Shipped populations use production attestation and keep their identity."""
import json
import shutil
from pathlib import Path

import pytest

from workflow_api.mot_3d_individual_sources import list_individual_mot_3d_sources, resolve_individual_mot_3d_source
from workflow_api.mot_3d_run_plan import build_mot_3d_run_plan
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION

SOURCE = Path(__file__).resolve().parents[1]

@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "team app with spaces"
    index = json.loads((SOURCE / "data/team_inputs/mot_3d_sources.json").read_text())
    files = {"data/team_inputs/mot_3d_sources.json"}
    for entry in index["sources"]:
        files.update(d["path"] for d in entry["provenance_documents"])
        for r in entry["records"]:
            files.update([r["path"], r["metadata_path"]])
    for relative in files:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, dest)
    return root, index

def test_packaged_populations_are_distinct_portable_and_individual_only(bundle):
    root, index = bundle
    catalog = list_individual_mot_3d_sources(root)
    assert catalog["invalid_count"] == 0
    assert sorted(r["available_particle_count"]["pooled"] for r in catalog["sources"]) == [16675, 16883]
    identities = []
    for entry in index["sources"]:
        identities.append({(r["zeeman_seed"], r["mot_seed"]) for r in entry["records"]})
    assert identities[0].isdisjoint(identities[1])
    assert {r["provenance"]["population"] for r in catalog["sources"]} == {"optimization", "held_out_validation"}
    for row in catalog["sources"]:
        assert row["result_suitability"] == "individual_only"
        source = resolve_individual_mot_3d_source(root, row["id"])
        assert sum(r["survivor_count"] for r in source.records) == row["available_particle_count"]["pooled"]
        assert all(not Path(r["path"]).is_absolute() and "\\" not in r["path"] for r in source.records)
        plan = build_mot_3d_run_plan({"source_id":row["id"], "geometry_family":"angled_donut", "particle_count":1,
            "selection_seed":42, "simulation_seed":42, "parameters":dict(MOT_3D_RUN_SPECIFICATION["defaults"]["angled_donut"]),
            "npools":1, "retain_particle_states":False, "execution_mode":"local"},
            repository_root=root, run_id="mot3d-team-test", git_revision="a"*40, created_utc="2026-10-27T00:00:00+00:00")
        assert plan.run["suitability"] == "individual_only"
        assert plan.review.source_qualification == "verified_bundled_ensemble"

@pytest.mark.parametrize("attack", ["state", "metadata", "document", "traversal", "count", "role", "duplicate"])
def test_corrupt_bundle_entry_is_rejected_without_losing_other_population(bundle, attack):
    root, index = bundle
    entry = index["sources"][0]
    record = entry["records"][0]
    if attack in {"state", "metadata", "document"}:
        relative = record["path"] if attack=="state" else record["metadata_path"] if attack=="metadata" else entry["provenance_documents"][0]["path"]
        p=root/relative
        p.write_bytes(p.read_bytes()+b"corrupt")
    elif attack=="traversal": record["path"]="../outside.npy"
    elif attack=="count": entry["particle_count"]+=1
    elif attack=="role": entry["population"]="scientific_campaign"
    else: entry["records"][1]=entry["records"][0].copy()
    (root/"data/team_inputs/mot_3d_sources.json").write_text(json.dumps(index))
    catalog=list_individual_mot_3d_sources(root)
    assert catalog["invalid_count"]==1
    assert catalog["total"]==1
    assert catalog["sources"][0]["provenance"]["population"]=="held_out_validation"


def test_bundle_limits_apply_before_opening_arrays(bundle, monkeypatch):
    import numpy as np
    import workflow_api.mot_3d_individual_sources as module
    root, index = bundle
    from copy import copy
    bounds=copy(module.individual_mot_3d_source_scan_limits())
    bounds.maximum_total_rows=16700
    monkeypatch.setattr(module, "individual_mot_3d_source_scan_limits", lambda: bounds)
    original=np.load
    forbidden={str(root/r["path"]) for r in index["sources"][0]["records"]}
    def guarded(path, **kwargs):
        assert str(path) not in forbidden, "over-budget population was opened"
        return original(path, **kwargs)
    monkeypatch.setattr(np, "load", guarded)
    result=module.list_individual_mot_3d_sources(root)
    assert result["invalid_count"]==1 and result["total"]==1


def test_array_modified_after_first_attestation_is_rejected(bundle, monkeypatch):
    import numpy as np
    root, index = bundle
    target=root/index["sources"][0]["records"][0]["path"]
    original=np.load
    def raced(path, **kwargs):
        value=original(path, **kwargs)
        if Path(path)==target:
            with target.open("r+b") as stream:
                stream.seek(-1, 2)
                byte=stream.read(1)
                stream.seek(-1, 2)
                stream.write(bytes([byte[0]^1]))
        return value
    monkeypatch.setattr(np, "load", raced)
    result=list_individual_mot_3d_sources(root)
    assert result["invalid_count"]==1 and result["total"]==1

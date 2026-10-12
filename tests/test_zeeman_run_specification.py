import json
from pathlib import Path

import pytest

import workflow_api.zeeman_run_specification as specification
from workflow_api.zeeman_run_specification import (
    ZEEMAN_RUN_SPECIFICATION,
    ZEEMAN_RUN_SPEC_SHA256,
    ZEEMAN_RUN_SPEC_VERSION,
    _validate,
)


def _mutable():
    def thaw(value):
        if hasattr(value, "items"):
            return {key: thaw(child) for key, child in value.items()}
        if isinstance(value, tuple):
            return [thaw(child) for child in value]
        return value

    return thaw(ZEEMAN_RUN_SPECIFICATION)


def test_specification_is_stable_and_deeply_immutable():
    assert ZEEMAN_RUN_SPEC_VERSION == "zeeman-individual-v1"
    assert len(ZEEMAN_RUN_SPEC_SHA256) == 64
    assert ZEEMAN_RUN_SPECIFICATION["request_fields"] == (
        "particle_count",
        "seed",
        "mot_2d_s0",
        "mot_2d_detuning_gamma",
        "mot_2d_magnet_radius_m",
        "npools",
        "retain_particle_states",
        "execution_mode",
    )
    assert ZEEMAN_RUN_SPECIFICATION["fixed_classification"]["suitability"] == (
        "individual_only"
    )
    assert ZEEMAN_RUN_SPECIFICATION["particle_count"] == {
        "minimum": 1,
        "default_by_execution_mode": {"local": 200, "zeus": 50_000},
        "maximum_by_execution_mode": {"local": 1_000, "zeus": 50_000},
    }
    with pytest.raises(TypeError):
        ZEEMAN_RUN_SPECIFICATION["seed"]["default"] = 7


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(extra=True),
        lambda row: row.update(spec_version="other"),
        lambda row: row["request_fields"].append("shell_command"),
        lambda row: row["particle_count"].update(minimum=True),
        lambda row: row["particle_count"]["default_by_execution_mode"].update(
            local=1_001
        ),
        lambda row: row["particle_count"]["maximum_by_execution_mode"].update(
            local=10
        ),
        lambda row: row["seed"].update(default=43),
        lambda row: row["seed"].update(maximum=-1),
        lambda row: row["worker_policy"]["local"].update(default=7),
        lambda row: row["worker_policy"].update(shell={"fixed": 1}),
        lambda row: row["mot_2d_controls"]["s0"].update(default=4.0),
        lambda row: row["fixed_classification"].update(
            suitability="campaign_input"
        ),
        lambda row: row["fixed_classification"].update(
            magnet_profile_policy="arbitrary"
        ),
    ],
)
def test_invalid_specification_variants_are_rejected(mutation):
    value = _mutable()
    mutation(value)
    with pytest.raises(ValueError):
        _validate(value)


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads(
            '{"spec_version":"one","spec_version":"two"}',
            object_pairs_hook=specification._unique_object,
        )


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"\xff", b"x" * (specification.MAX_SPECIFICATION_BYTES + 1)],
)
def test_loader_rejects_invalid_or_oversized_files(tmp_path, monkeypatch, payload):
    path = tmp_path / "zeeman_individual_v1.json"
    path.write_bytes(payload)
    monkeypatch.setattr(specification, "SPECIFICATION_PATH", path)
    with pytest.raises(RuntimeError, match="Zeeman-run specification"):
        specification._read_validated()


def test_loader_rejects_final_symlink(tmp_path, monkeypatch):
    target = tmp_path / "target.json"
    target.write_text("{}")
    path = tmp_path / "zeeman_individual_v1.json"
    path.symlink_to(target)
    monkeypatch.setattr(specification, "SPECIFICATION_PATH", path)
    with pytest.raises(RuntimeError, match="Zeeman-run specification"):
        specification._read_validated()


def test_checked_in_typescript_contract_matches_authority_exactly():
    generated = Path("ui/src/generated/zeemanIndividualSpec.v1.ts")
    assert generated.read_text() == specification.render_typescript_specification()

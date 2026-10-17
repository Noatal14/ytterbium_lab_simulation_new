import json

import pytest

import workflow_api.run_specification as run_specification
from workflow_api.run_specification import (
    INDIVIDUAL_RUN_SPECIFICATION,
    INDIVIDUAL_RUN_SPEC_SHA256,
    INDIVIDUAL_RUN_SPEC_VERSION,
    _validate,
)


def _mutable_specification():
    def thaw(value):
        if hasattr(value, "items"):
            return {key: thaw(child) for key, child in value.items()}
        if isinstance(value, tuple):
            return [thaw(child) for child in value]
        return value

    return thaw(INDIVIDUAL_RUN_SPECIFICATION)


def test_individual_run_specification_has_stable_identity_and_layout():
    specification = INDIVIDUAL_RUN_SPECIFICATION
    assert INDIVIDUAL_RUN_SPEC_VERSION == "individual-run-specification-v1"
    assert len(INDIVIDUAL_RUN_SPEC_SHA256) == 64
    assert specification["layout"]["root"] == "data/runs"
    assert specification["layout"]["families"] == ("zeeman", "mot_2d", "mot_3d")
    assert specification["suitability_levels"] == (
        "individual_only",
        "campaign_input",
    )


def test_terminal_states_have_no_outgoing_transitions():
    lifecycle = INDIVIDUAL_RUN_SPECIFICATION["lifecycle"]
    for state in lifecycle["terminal"]:
        assert lifecycle["transitions"][state] == ()


def test_retention_contract_requires_exactly_one_state_disposition():
    layout = INDIVIDUAL_RUN_SPECIFICATION["layout"]
    retention = INDIVIDUAL_RUN_SPECIFICATION["retention"]
    assert retention["retained_requires"] == layout["particle_states"]
    assert retention["retained_forbids"] == layout["retention_receipt"]
    assert retention["not_retained_requires"] == layout["retention_receipt"]
    assert retention["not_retained_forbids"] == layout["particle_states"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["layout"].update(root="../runs"),
        lambda value: value["layout"].update(result_registry="results/summary\u0000.json"),
        lambda value: value["layout"]["families"].append("unknown"),
        lambda value: value["layout"].update(immutable_files=["attacker.json"]),
        lambda value: value["layout"].update(result_registry="elsewhere/summary.json"),
        lambda value: value["layout"].update(logs_directory="otherlogs"),
        lambda value: (
            value["layout"].update(particle_states="results/other.npy"),
            value["retention"].update(
                retained_requires="results/other.npy",
                not_retained_forbids="results/other.npy",
            ),
        ),
        lambda value: (
            value["layout"].update(retention_receipt="results/other.json"),
            value["retention"].update(
                retained_forbids="results/other.json",
                not_retained_requires="results/other.json",
            ),
        ),
        lambda value: value.update(output_kinds=["arbitrary"]),
        lambda value: value["execution_modes"].append("shell"),
        lambda value: value["lifecycle"]["transitions"].update(invented=[]),
        lambda value: value["lifecycle"]["transitions"]["succeeded"].append("running"),
        lambda value: value["lifecycle"]["transitions"]["running"].append("invented"),
        lambda value: value["retention"].update(retained_requires="results/other.npy"),
        lambda value: value["retention"].update(retained_forbids="results/states.npy"),
        lambda value: value["limits"].update(json_max_bytes=True),
        lambda value: value["limits"].update(json_max_bytes=10**18),
    ],
)
def test_invalid_contract_variants_are_rejected(mutation):
    value = _mutable_specification()
    mutation(value)
    with pytest.raises(ValueError):
        _validate(value)


def test_exported_contract_is_deeply_immutable():
    with pytest.raises(TypeError):
        INDIVIDUAL_RUN_SPECIFICATION["layout"]["root"] = "elsewhere"
    with pytest.raises(AttributeError):
        INDIVIDUAL_RUN_SPECIFICATION["layout"]["families"].append("elsewhere")


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads(
            '{"spec_version":"first","spec_version":"second"}',
            object_pairs_hook=run_specification._unique_object,
        )


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"\xff", b"x" * (run_specification.MAX_SPECIFICATION_BYTES + 1)],
    ids=["invalid-json", "invalid-utf8", "oversized"],
)
def test_loader_rejects_invalid_or_oversized_files(tmp_path, monkeypatch, payload):
    path = tmp_path / "individual_run_v1.json"
    path.write_bytes(payload)
    monkeypatch.setattr(run_specification, "SPECIFICATION_PATH", path)
    with pytest.raises(RuntimeError, match="individual-run specification"):
        run_specification._read_validated()


def test_loader_rejects_final_symlink(tmp_path, monkeypatch):
    target = tmp_path / "target.json"
    target.write_text("{}")
    path = tmp_path / "individual_run_v1.json"
    path.symlink_to(target)
    monkeypatch.setattr(run_specification, "SPECIFICATION_PATH", path)
    with pytest.raises(RuntimeError, match="individual-run specification"):
        run_specification._read_validated()

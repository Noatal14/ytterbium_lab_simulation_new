import hashlib
import json
import pytest

from workflow_api import mot_3d_finalist_transition_remote as remote
from workflow_api import mot_3d_preliminary_transition_remote as core
from workflow_api.mot_3d_finalist_results import expected_paths
from workflow_api.mot_3d_finalist_transition import GENERATED_PATHS
from workflow_api.mot_3d_finalist_transition import Mot3DFinalistTransitionCoordinator
from workflow_api.mot_3d_preliminary_transition import RemotePreliminaryTransitionState
from workflow_api.preview_registry import PreviewRegistry
from tests.test_mot_3d_refinement_transition_remote import _fixture, _invoke
from tests.test_mot_3d_refinement_transition_local import fixture as local_fixture
from workflow_api import mot_3d_preliminary_transition as transition_module
import threading
from studies.mot_3d.finalists.merge import FINALIST_WINNER_RANKING_RULE


WINNER_SELECTION = {
    "rule": FINALIST_WINNER_RANKING_RULE,
    "winners": [
        {"family": family, "candidate_id": f"{family}_finalist_01"}
        for family in core.FAMILIES
    ],
    "evidence_sha256": "2" * 64,
}


def _selections():
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
        for family in core.FAMILIES
    }


def test_finalist_transition_descriptor_and_registry_are_exact():
    assert remote.DESCRIPTOR.from_stage == "finalist_selection"
    assert remote.DESCRIPTOR.to_stage == "final_validation_input_generation"
    assert remote.DESCRIPTOR.source_submission_receipt == (
        "finalist_selection_submission.json"
    )
    assert remote.DESCRIPTOR.prior_transition_name == "closure_to_finalist_selection"
    assert remote.DESCRIPTOR.source_result_count == 44
    assert remote.DESCRIPTOR.transfer_file_count == 50
    assert len(GENERATED_PATHS) == 5
    paths = expected_paths(_selections())
    assert len(paths) == 44
    with core.descriptor_scope(remote.DESCRIPTOR):
        assert core._result_paths(_selections()) == paths


def test_winner_preview_preserves_valid_recomputed_ranked_winner():
    summaries = {
        family: {"ranked_candidates": [{"candidate_id": f"{family}_finalist_02"}]}
        for family in core.FAMILIES
    }
    with core.descriptor_scope(remote.DESCRIPTOR):
        selection = core._winner_selection_from_summaries(summaries, "a" * 64)
    assert [row["candidate_id"] for row in selection["winners"]] == [
        "angled_donut_finalist_02",
        "single_pass_finalist_02",
    ]
    assert selection["rule"] == FINALIST_WINNER_RANKING_RULE


def test_finalist_wrapper_publishes_exact_50_and_status_is_zero_write(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _fixture(tmp_path, monkeypatch, remote)
    _invoke(monkeypatch, root, payload, receiver=remote)
    response = json.loads(capsys.readouterr().out)
    assert response["lifecycle"] == "final_validation_input_generation_prepared"
    assert response["bundle"]["file_count"] == 50
    receipt = (
        campaign
        / ".mot_ui/transitions/finalist_selection_to_final_validation_inputs.json"
    )
    assert receipt.is_file()
    before = {
        path.relative_to(campaign)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    _invoke(monkeypatch, root, payload, operation="status", receiver=remote)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == (
        "final_validation_input_generation_prepared"
    )
    after = {
        path.relative_to(campaign)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_finalist_local_manifest_last_session_and_idempotent_confirm(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, prepared, files = local_fixture(
        tmp_path,
        monkeypatch,
        coordinator_type=Mot3DFinalistTransitionCoordinator,
        from_stage="finalist_selection",
        to_stage="final_validation_input_generation",
        prepared_status="final_validation_input_generation_prepared",
    )
    digest = coordinator._synchronize(plan, transport, prepared)
    assert coordinator._synchronize(plan, transport, prepared) == digest
    assert json.loads((plan[2] / "campaign.json").read_text())["stage"] == (
        "final_validation_input_generation"
    )
    assert len(files) == 50
    ready = RemotePreliminaryTransitionState(
        **{
            **prepared.__dict__,
            "lifecycle": "ready_to_advance",
            "receipt": None,
            "bundle": None,
            "winner_selection": WINNER_SELECTION,
        }
    )
    prepared = RemotePreliminaryTransitionState(
        **{**prepared.__dict__, "winner_selection": WINNER_SELECTION}
    )

    class Transport:
        def prepare(self, **_payload):
            return prepared

    coordinator._previews = PreviewRegistry(
        clock=lambda: 1_800_000_000, token_factory=lambda: "token"
    )
    coordinator._confirm_lock = threading.Lock()
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        Transport(),
        ready if operation == "inspect" else prepared,
    )
    coordinator._synchronize = lambda *_args: "9" * 64
    monkeypatch.setattr(transition_module.secrets, "token_hex", lambda _size: "f" * 32)
    preview = coordinator.preview({}, session_id="session-a")
    assert preview["artifacts"]["transfer_files"] == 50
    assert preview["artifacts"]["create"] == {
        "selection_files": 1,
        "job_files": 3,
    }
    assert preview["winner_selection"] == WINNER_SELECTION
    with pytest.raises(Exception, match="confirmation_invalid"):
        coordinator.confirm({"preview_token": "token"}, session_id="session-b")
    result = coordinator.confirm({"preview_token": "token"}, session_id="session-a")
    assert result["status"] == "final_validation_input_generation_prepared"
    assert result["artifacts"]["synchronized"] == 45
    assert result["artifacts"]["created"] == 4
    assert result["artifacts"]["updated"] == 1
    assert len(result["artifacts"]["bundle_sha256"]) == 64
    assert (
        coordinator.confirm({"preview_token": "token"}, session_id="session-a")
        == result
    )

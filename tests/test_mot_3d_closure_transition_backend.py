import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from workflow_api.mot_3d_closure_results import expected_paths
from workflow_api.mot_3d_closure_transition import GENERATED_PATHS
from workflow_api.mot_3d_closure_transition import Mot3DClosureTransitionCoordinator
from workflow_api.mot_3d_closure_transition_remote import DESCRIPTOR
from workflow_api.mot_3d_preliminary_transition_remote import (
    descriptor_scope,
    _result_paths,
)
from workflow_api import mot_3d_closure_transition_remote as closure_remote
from workflow_api import mot_3d_preliminary_transition_remote as core
from tests.test_mot_3d_refinement_transition_remote import _fixture, _invoke
from tests.test_mot_3d_refinement_transition_local import fixture as local_fixture
from tests.test_mot_3d_closure_submission import (
    _invoke_receiver as invoke_closure_submission,
    _receiver_repository as closure_submission_repository,
)
from workflow_api.mot_3d_preliminary_transition import RemotePreliminaryTransitionState
from workflow_api.preview_registry import PreviewRegistry
from workflow_api import mot_3d_preliminary_transition as transition_module
from workflow_api import mot_3d_preliminary_submission_remote as submission_remote


def _selections():
    return {
        family: {
            "kind": "mot_3d_local_closure_selection",
            "family": family,
            "candidate_count": 16,
            "candidates": [
                {"candidate_id": f"{family}_closure_{index:02d}"} for index in range(16)
            ],
        }
        for family in ("angled_donut", "single_pass")
    }


def test_closure_transition_descriptor_is_exact_and_never_submits():
    assert DESCRIPTOR.from_stage == "closure"
    assert DESCRIPTOR.to_stage == "finalist_selection"
    assert DESCRIPTOR.source_submission_receipt == "closure_submission.json"
    assert DESCRIPTOR.prior_transition_name == "refinement_to_closure"
    assert DESCRIPTOR.source_result_count == 200
    assert DESCRIPTOR.transfer_file_count == 208
    assert len(GENERATED_PATHS) == 7


def test_closure_result_registry_is_exact_and_descriptor_dispatched():
    paths = expected_paths(_selections())
    assert len(paths) == 200
    assert all(path.startswith("closure/") for path in paths)
    with descriptor_scope(DESCRIPTOR):
        assert _result_paths(_selections()) == paths


def test_closure_result_registry_rejects_substituted_refinement_selection():
    selections = _selections()
    selections["angled_donut"]["kind"] = "mot_3d_focused_refinement_selection"
    with pytest.raises(Exception, match="selection_mismatch"):
        expected_paths(selections)


def test_closure_receiver_publishes_exact_208_and_status_is_zero_write(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload = _fixture(tmp_path, monkeypatch, closure_remote)
    _invoke(monkeypatch, root, payload, receiver=closure_remote)
    response = json.loads(capsys.readouterr().out)
    assert response["lifecycle"] == "finalist_selection_prepared"
    assert response["bundle"]["file_count"] == 208
    receipt = campaign / ".mot_ui/transitions/closure_to_finalist_selection.json"
    assert receipt.is_file()
    assert not (receipt.parent / "closure_to_finalist_selection.pending.json").exists()
    assert (
        json.loads((campaign / "campaign.json").read_text())["stage"]
        == "finalist_selection"
    )
    before = {
        path.relative_to(campaign)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    _invoke(monkeypatch, root, payload, operation="status", receiver=closure_remote)
    assert (
        json.loads(capsys.readouterr().out)["lifecycle"]
        == "finalist_selection_prepared"
    )
    after = {
        path.relative_to(campaign)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_direct_finalist_renderer_dependency_is_in_frozen_ledger_and_rechecked(
    tmp_path, monkeypatch
):
    original_identity = core._identity
    root, campaign, payload = _fixture(tmp_path, monkeypatch, closure_remote)
    monkeypatch.setattr(core, "_identity", original_identity)
    dependency = "studies/mot_3d/discovery/optimize.py"
    assert dependency in closure_remote.DESCRIPTOR.code_paths
    # Populate exact source files; the intentionally wrong direct-dependency
    # digest must stop admission before any transition publication is read.
    for name in closure_remote.DESCRIPTOR.source_identity_paths:
        payload["identity"]["source_files"][name] = hashlib.sha256(
            (campaign / name).read_bytes()
        ).hexdigest()
    repository = os.open(os.getcwd(), os.O_RDONLY | os.O_DIRECTORY)
    campaign_fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in closure_remote.DESCRIPTOR.code_paths:
            payload["identity"]["code_files"][name] = hashlib.sha256(
                Path(name).read_bytes()
            ).hexdigest()
        payload["identity"]["code_files"][dependency] = "0" * 64
        payload["transition_key"] = core.digest(payload)
        with (
            core.descriptor_scope(closure_remote.DESCRIPTOR),
            pytest.raises(SystemExit),
        ):
            core._identity(payload, campaign_fd, repository)
    finally:
        os.close(campaign_fd)
        os.close(repository)
    assert not (
        campaign / ".mot_ui/transitions/closure_to_finalist_selection.json"
    ).exists()


def test_closure_local_manifest_last_session_stale_and_double_confirm(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, prepared, files = local_fixture(
        tmp_path,
        monkeypatch,
        coordinator_type=Mot3DClosureTransitionCoordinator,
        from_stage="closure",
        to_stage="finalist_selection",
        prepared_status="finalist_selection_prepared",
    )
    digest = coordinator._synchronize(plan, transport, prepared)
    assert coordinator._synchronize(plan, transport, prepared) == digest
    assert (
        json.loads((plan[2] / "campaign.json").read_text())["stage"]
        == "finalist_selection"
    )
    assert len(files) == 208

    ready = RemotePreliminaryTransitionState(
        **{
            **prepared.__dict__,
            "lifecycle": "ready_to_advance",
            "receipt": None,
            "bundle": None,
        }
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
    assert preview["from_stage"] == "closure"
    assert preview["to_stage"] == "finalist_selection"
    with pytest.raises(Exception, match="confirmation_invalid"):
        coordinator.confirm({"preview_token": "token"}, session_id="session-b")
    result = coordinator.confirm({"preview_token": "token"}, session_id="session-a")
    assert result["status"] == "finalist_selection_prepared"
    assert (
        coordinator.confirm({"preview_token": "token"}, session_id="session-a")
        == result
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "pending",
        *sorted(DESCRIPTOR.generated_paths - {"campaign.json"}),
        "bundle",
        "campaign",
        "final",
        "unlink",
    ],
)
def test_closure_every_durable_publication_boundary_recovers_exactly_once(
    tmp_path, monkeypatch, capsys, boundary
):
    root, campaign, payload = _fixture(tmp_path, monkeypatch, closure_remote)
    prepared = dict(payload, nonce="7" * 32)
    publish_bytes = core._publish_bytes
    publish_relative = core._publish_relative
    replace_campaign = core._replace_campaign
    unlink = core.unlink_at
    crashed = False

    def crash():
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit(93)

    def wrapped_publish_bytes(parent, name, raw, *, identical_ok):
        result = publish_bytes(parent, name, raw, identical_ok=identical_ok)
        if (
            (boundary == "pending" and name == DESCRIPTOR.pending_name)
            or (boundary == "bundle" and name == DESCRIPTOR.bundle_name)
            or (boundary == "final" and name == DESCRIPTOR.final_name)
        ):
            crash()
        return result

    def wrapped_publish_relative(parent, name, raw):
        result = publish_relative(parent, name, raw)
        if boundary == name:
            crash()
        return result

    def wrapped_replace_campaign(parent, old, new):
        result = replace_campaign(parent, old, new)
        if boundary == "campaign":
            crash()
        return result

    def wrapped_unlink(parent, name):
        result = unlink(parent, name)
        if boundary == "unlink" and name == DESCRIPTOR.pending_name:
            crash()
        return result

    monkeypatch.setattr(core, "_publish_bytes", wrapped_publish_bytes)
    monkeypatch.setattr(core, "_publish_relative", wrapped_publish_relative)
    monkeypatch.setattr(core, "_replace_campaign", wrapped_replace_campaign)
    monkeypatch.setattr(core, "unlink_at", wrapped_unlink)
    with pytest.raises(SystemExit) as error:
        _invoke(monkeypatch, root, prepared, receiver=closure_remote)
    assert error.value.code == 93
    monkeypatch.setattr(core, "_publish_bytes", publish_bytes)
    monkeypatch.setattr(core, "_publish_relative", publish_relative)
    monkeypatch.setattr(core, "_replace_campaign", replace_campaign)
    monkeypatch.setattr(core, "unlink_at", unlink)
    _invoke(monkeypatch, root, prepared, receiver=closure_remote)
    response = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert response["lifecycle"] == "finalist_selection_prepared"
    assert (
        json.loads((campaign / "campaign.json").read_text())["stage"]
        == "finalist_selection"
    )
    assert not (campaign / ".mot_ui/transitions" / DESCRIPTOR.pending_name).exists()


def test_closure_closed_transition_namespace_rejects_unexpected_entry_zero_write(
    tmp_path, monkeypatch
):
    root, campaign, payload = _fixture(tmp_path, monkeypatch, closure_remote)
    transitions = campaign / ".mot_ui/transitions"
    transitions.mkdir()
    (transitions / "closure_to_finalist_selection.evil.json").write_bytes(b"{}")
    before = (campaign / "campaign.json").read_bytes()
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, payload, operation="status", receiver=closure_remote)
    assert (campaign / "campaign.json").read_bytes() == before
    assert set(path.name for path in transitions.iterdir()) == {
        "closure_to_finalist_selection.evil.json"
    }


def test_closure_symlinked_generated_parent_cannot_write_outside_campaign(
    tmp_path, monkeypatch
):
    root, campaign, payload = _fixture(tmp_path, monkeypatch, closure_remote)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = campaign / "selection/finalists"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, payload, receiver=closure_remote)
    assert list(outside.iterdir()) == []
    assert json.loads((campaign / "campaign.json").read_text())["stage"] == "closure"


def test_closure_transition_accepts_only_exact_stage5_receipts_and_qstat(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload, _ = closure_submission_repository(tmp_path)
    submit = {**payload, "nonce": "8" * 32}
    ids = iter(
        [
            b"510[].zeus-master\n",
            b"511.zeus-master\n",
            b"512[].zeus-master\n",
            b"513.zeus-master\n",
        ]
    )

    def run(argv, input_data=None, limit=None):
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            return 0, next(ids), b""
        if argv[0] == "/usr/local/bin/qstat":
            job = argv[-1]
            if "[]" in job:
                prefix = job.split("[]", 1)[0]
                return (
                    0,
                    b"".join(
                        f"Job Id: {prefix}[{index}].zeus-master\n    job_state = F\n    Exit_status = 0\n".encode()
                        for index in range(3)
                    ),
                    b"",
                )
            return (
                0,
                f"Job Id: {job}\n    job_state = F\n    Exit_status = 0\n".encode(),
                b"",
            )
        raise AssertionError(argv)

    invoke_closure_submission(monkeypatch, root, "submit", submit, run)
    capsys.readouterr()
    campaign_fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with core.descriptor_scope(DESCRIPTOR):
            final, jobs = core._exact_stage2(
                campaign_fd, payload["submission_key"], "a" * 40
            )
            monkeypatch.setattr(submission_remote, "run", run)
            assert core._scheduler(jobs) == ("completed_success_unvalidated", 6, 2)
            assert final["status"] == "submitted"
            step = campaign / ".mot_ui/submissions/closure_angled_donut_merge.json"
            changed = json.loads(step.read_text())
            changed["depends_on"] = "999[].zeus-master"
            step.write_text(json.dumps(changed))
            with pytest.raises(SystemExit):
                core._exact_stage2(campaign_fd, payload["submission_key"], "a" * 40)
    finally:
        os.close(campaign_fd)

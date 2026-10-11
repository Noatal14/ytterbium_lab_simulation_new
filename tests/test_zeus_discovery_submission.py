from pathlib import Path

import pytest

from workflow_api.zeus_discovery_submission import (
    RemoteDiscoveryState,
    ZeusMot3DDiscoverySubmissionCoordinator,
    ZeusMot3DDiscoverySubmissionError,
)
from workflow_api.zeus_snapshot import ZeusProfile


class Transport:
    def __init__(self):
        self.submits = 0
        self.state = RemoteDiscoveryState(
            "eligible", "main", {"angled_donut": [], "single_pass": []}, None, None
        )

    def inspect(self, **_payload):
        return self.state

    def status(self, **_payload):
        return self.state

    def submit(self, **payload):
        self.submits += 1
        self.state = RemoteDiscoveryState(
            "submitted",
            "main",
            {
                "angled_donut": ["1[].zeus-master", "2[].zeus-master"],
                "single_pass": [
                    "3[].zeus-master",
                    "4[].zeus-master",
                    "5[].zeus-master",
                ],
            },
            payload["nonce"],
            1_800_000_000,
        )
        return self.state


def fixture(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    ssh = tmp_path / "ssh"
    git = tmp_path / "git"
    ssh.write_text("")
    git.write_text("")
    campaign = root / "data/optimization/mot_3d/example"
    campaign.mkdir(parents=True)
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    files = {
        name: str(index) * 64
        for index, name in enumerate(
            sorted(
                {
                    "campaign.json",
                    "jobs/01_smoke_angled_donut.pbs",
                    "jobs/01_smoke_single_pass.pbs",
                    "jobs/02_submit_discovery_chain.sh",
                    "jobs/angled_donut/round_01.pbs",
                    "jobs/angled_donut/round_02.pbs",
                    "jobs/single_pass/round_01.pbs",
                    "jobs/single_pass/round_02.pbs",
                    "jobs/single_pass/round_03.pbs",
                }
            ),
            1,
        )
    }
    plan = (
        "mot-3d-id",
        profile,
        campaign,
        {"name": "example"},
        "a" * 40,
        files,
        "b" * 32,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )
    transport = Transport()
    coordinator = ZeusMot3DDiscoverySubmissionCoordinator(
        root,
        ssh,
        git,
        token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    monkeypatch.setattr(coordinator, "_plan", lambda _request: plan)
    return coordinator, transport, profile


def test_explicit_session_bound_replay_safe_five_array_submit(tmp_path, monkeypatch):
    coordinator, transport, profile = fixture(tmp_path, monkeypatch)
    request = {
        "campaign_id": "mot-3d-id",
        "username": profile.username,
        "project_directory": profile.project_directory,
    }
    preview = coordinator.preview(request, session_id="owner")
    assert preview["chain"]["arrays"] == 5
    assert preview["effects"]["submit_smoke"] is False
    with pytest.raises(ZeusMot3DDiscoverySubmissionError) as caught:
        coordinator.confirm({"preview_token": "token"}, session_id="intruder")
    assert caught.value.code == "discovery_invalid"
    first = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert first == coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert transport.submits == 1
    assert len(first["chain"]["angled_donut"]) == 2
    assert len(first["chain"]["single_pass"]) == 3


def test_confirm_rejects_changed_frozen_plan_before_submit(tmp_path, monkeypatch):
    coordinator, transport, profile = fixture(tmp_path, monkeypatch)
    request = {
        "campaign_id": "mot-3d-id",
        "username": profile.username,
        "project_directory": profile.project_directory,
    }
    coordinator.preview(request, session_id="owner")
    original = coordinator._plan(request)
    changed = list(original)
    changed[7] = "f" * 64
    monkeypatch.setattr(coordinator, "_plan", lambda _request: tuple(changed))
    with pytest.raises(ZeusMot3DDiscoverySubmissionError) as caught:
        coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert caught.value.code == "local_files_changed"
    assert transport.submits == 0


def test_ambiguous_remote_state_blocks_retry(tmp_path, monkeypatch):
    coordinator, transport, profile = fixture(tmp_path, monkeypatch)
    transport.state = RemoteDiscoveryState(
        "outcome_unknown", "main", {"angled_donut": [], "single_pass": []}, None, None
    )
    with pytest.raises(ZeusMot3DDiscoverySubmissionError) as caught:
        coordinator.preview(
            {
                "campaign_id": "mot-3d-id",
                "username": profile.username,
                "project_directory": profile.project_directory,
            },
            session_id="owner",
        )
    assert caught.value.code == "discovery_submission_outcome_unknown"

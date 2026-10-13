import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
from copy import deepcopy

from workflow_api import mot_3d_preliminary_transition_remote as core
from workflow_api import mot_3d_refinement_transition_remote as remote


def _invoke(monkeypatch, root, payload, operation="prepare", receiver=remote):
    request = dict(payload)
    if operation == "prepare":
        request["nonce"] = "9" * 32
    encoded = base64.urlsafe_b64encode(json.dumps(request).encode()).decode()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "receiver",
            operation,
            "tester",
            "/home/tester/ytterbium_lab_simulation_new",
            encoded,
        ],
    )
    receiver.main(trusted_root_override=root)


def _fixture(tmp_path, monkeypatch, receiver=remote):
    descriptor = receiver.DESCRIPTOR
    root = tmp_path / "repository"
    campaign = root / "data/optimization/mot_3d/campaign"
    (campaign / ".mot_ui").mkdir(parents=True)
    manifest = {"name": "campaign", "stage": descriptor.from_stage}
    manifest_raw = json.dumps(manifest).encode()
    (campaign / "campaign.json").write_bytes(manifest_raw)
    for family in core.FAMILIES:
        selection = campaign / f"selection/{descriptor.selection_stage}/{family}.json"
        selection.parent.mkdir(parents=True, exist_ok=True)
        selection.write_text("{}")
        for kind in ("array", "merge"):
            job = campaign / f"jobs/{descriptor.from_stage}/{family}_{kind}.pbs"
            job.parent.mkdir(parents=True, exist_ok=True)
            job.write_text(f"{family}-{kind}")
    (campaign / descriptor.source_submission_receipt).write_text("receipt")
    result_paths = tuple(
        f"{descriptor.from_stage}/results/result_{index:03d}.json"
        for index in range(200)
    )
    results = {}
    for name in result_paths:
        raw = name.encode()
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        results[name] = raw
    generated = {
        "campaign.json": json.dumps(
            {**manifest, "stage": descriptor.to_stage}
        ).encode(),
        **{
            name: name.encode()
            for name in descriptor.generated_paths - {"campaign.json"}
        },
    }
    identity = {
        "source_files": {name: "a" * 64 for name in descriptor.source_identity_paths},
        "code_files": {name: "b" * 64 for name in descriptor.code_paths},
        "stage3_local_sync_receipt_sha256": "c" * 64,
        "stage3_remote_receipt_sha256": "d" * 64,
        "stage3_bundle_sha256": "e" * 64,
        "stage4_submission_identity": {
            "campaign_sha256": "1" * 64,
            "local_transition_receipt_sha256": "2" * 64,
            "transition_key": "3" * 64,
            "remote_transition_receipt_sha256": "4" * 64,
            "bundle_sha256": "5" * 64,
            "files": {name: "6" * 64 for name in descriptor.source_identity_paths},
            "science": {"classification": "candidate_selection_not_final_validation"},
            "physical_model_sha256": "7" * 64,
            "upstream_campaign_sha256": "8" * 64,
            "upstream_final_report_sha256": "9" * 64,
            "timestep_policy_sha256": "a" * 64,
            "code_files": {"config.py": "b" * 64},
        },
    }
    submission_key = core.digest(
        {
            "campaign": "data/optimization/mot_3d/campaign",
            "commit": "a" * 40,
            **identity["stage4_submission_identity"],
        }
    )
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": "a" * 40,
        "submission_key": submission_key,
        "identity": identity,
    }
    payload["transition_key"] = core.digest(payload)
    monkeypatch.setattr(core, "run", lambda *a, **k: (0, b"a" * 40 + b"\n", b""))
    calls = iter([(0, b"branch\n", b""), (0, b"", b"")])
    monkeypatch.setattr(core, "run", lambda *a, **k: next(calls))

    # main invokes git three times before the trusted transition seams.
    def git_run(argv, limit):
        if argv[-2:] == ["rev-parse", "HEAD"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[-2:] == ["branch", "--show-current"]:
            return 0, b"main\n", b""
        return 0, b"", b""

    monkeypatch.setattr(core, "run", git_run)
    monkeypatch.setattr(
        core, "_identity", lambda *a, **k: (identity, {"campaign.json": manifest_raw})
    )
    jobs = {
        family: {"array": f"{11+i*2}[].zeus-master", "merge": f"{12+i*2}.zeus-master"}
        for i, family in enumerate(core.FAMILIES)
    }
    monkeypatch.setattr(core, "_exact_stage2", lambda *a, **k: ({}, jobs))
    monkeypatch.setattr(
        core, "_scheduler", lambda jobs: ("completed_success_unvalidated", 6, 2)
    )
    validated = type("Validated", (), {"summaries": {}, "evidence_sha256": "0" * 64})()
    monkeypatch.setattr(
        core, "_capture", lambda *a, **k: (manifest, results, validated)
    )
    monkeypatch.setattr(core, "_render_transition", lambda *a, **k: (generated, {}))
    monkeypatch.setattr(core, "_result_paths", lambda parsed: result_paths)
    return root, campaign, payload


def test_stage5_wrapper_publishes_exact_208_file_bundle(tmp_path, monkeypatch, capsys):
    root, campaign, payload = _fixture(tmp_path, monkeypatch)
    _invoke(monkeypatch, root, payload)
    response = json.loads(capsys.readouterr().out)
    assert response["lifecycle"] == "closure_prepared"
    assert response["bundle"]["file_count"] == 208
    assert (campaign / ".mot_ui/transitions/refinement_to_closure.json").is_file()
    assert not (
        campaign / ".mot_ui/transitions/refinement_to_closure.pending.json"
    ).exists()
    assert json.loads((campaign / "campaign.json").read_text())["stage"] == "closure"


def test_descriptor_scopes_are_thread_isolated():
    preliminary = core.preliminary_transition_descriptor()
    refinement = remote.DESCRIPTOR

    def observe(descriptor):
        with core.descriptor_scope(descriptor):
            return core._descriptor().sync_name, core._descriptor().prepared_status

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = set(pool.map(observe, (preliminary, refinement)))
    assert values == {
        ("refinement", "refinement_prepared"),
        ("refinement_to_closure", "closure_prepared"),
    }


def test_descriptor_rejects_wrong_scalar_types():
    values = dict(remote.DESCRIPTOR.__dict__)
    values["transfer_file_count"] = True
    try:
        core.TransitionDescriptor(**values)
    except ValueError:
        pass
    else:
        raise AssertionError("bool count must fail closed")


def test_stage4_nested_identity_mutations_require_a_new_submission_key(
    tmp_path, monkeypatch
):
    _, _, payload = _fixture(tmp_path, monkeypatch)
    assert core._stage4_key_matches(
        payload, payload["identity"]["stage4_submission_identity"]
    )
    mutations = []
    science = deepcopy(payload["identity"]["stage4_submission_identity"])
    science["science"]["classification"] = "drifted"
    mutations.append(science)
    code = deepcopy(payload["identity"]["stage4_submission_identity"])
    code["code_files"]["config.py"] = "0" * 64
    mutations.append(code)
    provenance = deepcopy(payload["identity"]["stage4_submission_identity"])
    provenance["physical_model_sha256"] = "0" * 64
    mutations.append(provenance)
    assert all(
        not core._stage4_key_matches(payload, mutation) for mutation in mutations
    )

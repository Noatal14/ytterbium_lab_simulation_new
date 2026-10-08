import json
import hashlib
import shlex
import subprocess
import sys
import threading
import numpy as np
from pathlib import Path
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from workflow_api.server import ReadOnlyWorkflowHandler, workflow_catalog_payload
from workflow_api.mot_2d_validation import modern_contract, validated_progress
from workflow_api.discovery import _progress_aware_plan, list_campaigns
from workflow_api.mot_2d_sources import list_sources
from workflow_api.mot_2d_plan import RELEVANT_FILES
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeus_transfer import ZeusPreparationError
from workflow_api.zeus_submission import ZeusSubmissionError


def modern_2d_manifest(repository_root, name="modern", stage="smoke"):
    roles = {
        "discovery": list(range(3000, 3005)), "refinement": list(range(3005, 3010)),
        "held_out_confirmation": list(range(3010, 3015)), "sealed_validation": list(range(3015, 3035)),
    }
    inputs = repository_root / "data" / "particle_states" / "after_zeeman" / "profile"
    inputs.mkdir(parents=True, exist_ok=True)
    frozen = {}
    for role, seeds in roles.items():
        frozen[role] = []
        for seed in seeds:
            state = inputs / f"input-{seed}.npy"; metadata = state.with_suffix(".json")
            state.write_bytes(f"states-{seed}".encode())
            digest = hashlib.sha256(state.read_bytes()).hexdigest()
            metadata.write_text(json.dumps({
                "shape": [10, 6], "dtype": "float64", "n_survivors": 10,
                "output_sha256": digest,
                "parameters": {
                    "seed": seed, "resolved_zeeman_magnet_profile": "profile",
                    "n_initial_atoms": 50000, "dt_s": 4e-5,
                    "stochastic": True, "collimation_angle_deg": 0.02,
                },
                "software": {"git_commit": "source"},
            }))
            metadata_digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
            frozen[role].append({
                "zeeman_seed": seed, "path": str(state.relative_to(repository_root)), "metadata_path": str(metadata.relative_to(repository_root)),
                "sha256": digest, "metadata_sha256": metadata_digest, "shape": [10, 6], "dtype": "float64", "survivor_count": 10,
                "zeeman_profile": "profile", "source_git_commit": "source",
                "generation": {"n_initial_atoms": 50000, "dt_s": 4e-5, "stochastic": True, "collimation_angle_deg": 0.02},
            })
    return {
        "kind": "mot_2d_s0_campaign", "name": name, "stage": stage, "s0_values": [1.3], "stages": {},
        "ensemble_source": {"directory": "data/particle_states/after_zeeman/profile", "zeeman_profile": "profile"},
        "seed_roles": roles, "input_ensembles": frozen,
        "mot_seeds": {role: [40000 + seed for seed in seeds] for role, seeds in roles.items()},
        "provenance": {"git_commit": "abc", "physical_model_sha256": "b" * 64, "hashed_files": ["config.py"], "capture_criterion_version": "v1", "path_contract": "repository-relative-v1"},
        "fixed_design": {"working_dt_s": 1.25e-6, "final_dt_s": 0.625e-6, "solver": "RK4StHybridCustom",
            "detuning_bounds_gamma": [-2, -0.5], "magnet_radius_bounds_m": [0.04, 0.05],
            "particle_counts": {}, "trial_budgets": {"screen_per_worker": 17, "refine_per_worker": 10},
            "control_resolution": {}, "stress_test_offsets": {}},
    }


def write_valid_smoke(campaign, manifest):
    directory = campaign / "smoke" / "s0_1p300000"
    (directory / "trials").mkdir(parents=True, exist_ok=True)
    s0 = 1.3
    design_input = {
        "fixed_s0": s0, "dt_s": 1.25e-6, "solver": "RK4StHybridCustom",
        "ensemble_dir": "data/particle_states/after_zeeman/profile",
        "zeeman_seeds": [3000], "mot_seeds": [43000],
        "particles_per_ensemble": 2, "sampler_seed": 42,
        "bounds": {"s0": [s0, s0], "detuning_gamma": [-2, -0.5], "magnet_radius_m": [0.04, 0.05]},
        "git_commit": "abc", "campaign_design_id": "b" * 64,
    }
    design_id = hashlib.sha256(json.dumps(design_input, sort_keys=True).encode()).hexdigest()
    (directory / "trials" / "trial_0000.json").write_text(json.dumps({
        "kind": "mot_2d_joint_optimization_trial", "trial_number": 0,
        "parameters": {"s0": s0, "detuning_gamma": -1.0, "magnet_radius": 0.046},
        "design": {
            "dt_s": 1.25e-6, "n_ensembles": 1, "particles_per_ensemble": 2,
            "mot_seed_start": 4000, "stochastic_solver": "RK4StHybridCustom",
            "design_id": design_id, "git_commit": "abc",
            "ensemble_dir": design_input["ensemble_dir"], "zeeman_seeds": [3000], "mot_seeds": [43000],
        },
    }))
    (directory / "summary.json").write_text(json.dumps({
        "kind": "mot_2d_joint_optimization_summary", "fixed_s0": s0, "n_finished_trials": 1,
        "design": {"stochastic_solver": "RK4StHybridCustom", "dt_s": 1.25e-6},
    }))


def test_modern_contract_rejects_noncanonical_seeds_and_metadata_mismatch(tmp_path):
    root = tmp_path / "repo"
    manifest = modern_2d_manifest(root)
    assert modern_contract(manifest, root) == (True, ())

    manifest["seed_roles"]["discovery"][0] = 2999
    trusted, errors = modern_contract(manifest, root)
    assert not trusted
    assert any("canonical frozen set" in message for message in errors)

    manifest = modern_2d_manifest(root)
    metadata_path = root / manifest["input_ensembles"]["discovery"][0]["metadata_path"]
    metadata = json.loads(metadata_path.read_text())
    metadata["parameters"]["resolved_zeeman_magnet_profile"] = "wrong"
    metadata_path.write_text(json.dumps(metadata))
    trusted, errors = modern_contract(manifest, root)
    assert not trusted
    assert any("provenance does not match" in message for message in errors)


def test_smoke_requires_genuine_trial_identity(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root)
    write_valid_smoke(campaign, manifest)
    assert validated_progress(campaign, manifest)[0].status == "complete"

    trial = campaign / "smoke/s0_1p300000/trials/trial_0000.json"
    payload = json.loads(trial.read_text())
    payload["design"]["mot_seeds"] = [999]
    trial.write_text(json.dumps(payload))
    assert validated_progress(campaign, manifest)[0].status == "inconsistent"


def test_duplicate_confirmation_and_production_tasks_are_inconsistent(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root)
    manifest["stage"] = "production"
    manifest["stages"] = {
        "confirmation": {"tasks": 2},
        "production": {"tasks": 2},
    }
    confirmation = campaign / "confirmation"
    production = campaign / "production"
    confirmation.mkdir(); production.mkdir()
    duplicate_confirmation = {"s0": 1.3, "candidate_index": 0, "parameters": {}}
    (confirmation / "tasks.json").write_text(json.dumps([duplicate_confirmation, duplicate_confirmation]))
    duplicate_production = {"s0": 1.3, "zeeman_seed": 3015, "mot_seed": 43015, "parameters": {}}
    (production / "tasks.json").write_text(json.dumps([duplicate_production, duplicate_production]))

    progress = {row.stage: row for row in validated_progress(campaign, manifest)}
    assert progress["confirmation"].status == "inconsistent"
    assert progress["production"].status == "inconsistent"


def test_malformed_3d_sibling_is_isolated_from_valid_listing(tmp_path):
    root = tmp_path / "repo"
    valid = root / "data/optimization/mot_2d/valid"
    valid.mkdir(parents=True)
    (valid / "campaign.json").write_text(json.dumps(modern_2d_manifest(root)))
    malformed = root / "data/optimization/mot_3d/malformed"
    malformed.mkdir(parents=True)
    (malformed / "campaign.json").write_text(json.dumps({
        "kind": "mot_3d_campaign_v2", "name": "bad", "stage": "dt_validation_required",
        "provenance": {"git_commit": "abc", "physical_model_sha256": "a" * 64},
        "design": {"families": 3, "solver": "RK4StHybridCustom"},
    }))

    result = list_campaigns(root)
    assert [row["name"] for row in result["campaigns"]] == ["modern"]
    assert result["invalid_count"] == 1


def test_legacy_2d_campaign_is_inspectable_but_cannot_prepare_remote_work(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/legacy"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root, name="legacy")
    manifest["provenance"].pop("path_contract")
    (campaign / "campaign.json").write_text(json.dumps(manifest))

    result = list_campaigns(root)

    assert result["invalid_count"] == 0
    assert result["total"] == 1
    record = result["campaigns"][0]
    assert record["name"] == "legacy"
    assert record["trust"] == "legacy-incomplete"
    assert record["remote_preparation"] == {
        "status": "legacy-local-only",
        "reason_code": "absolute-input-paths",
    }
    assert record["next_plan"] is None


def test_explicit_portable_2d_campaign_with_invalid_path_is_unavailable(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/incomplete-portability"
    campaign.mkdir(parents=True)
    manifest = modern_2d_manifest(root, name="incomplete portability")
    manifest["ensemble_source"]["directory"] = "../../outside-repository"
    (campaign / "campaign.json").write_text(json.dumps(manifest))

    result = list_campaigns(root)

    assert result["invalid_count"] == 0
    assert result["total"] == 1
    record = result["campaigns"][0]
    assert record["name"] == "incomplete portability"
    assert record["trust"] == "legacy-incomplete"
    assert record["remote_preparation"] == {
        "status": "unavailable",
        "reason_code": "incomplete-portability-record",
    }
    assert record["next_plan"] is None


def test_progress_aware_plan_never_resubmits_partial_stage(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_2d/modern"
    campaign.mkdir(parents=True)
    summary = {
        "stage": "screen",
        "next_plan": {"label": "Submit", "command": ["qsub", "job.pbs"]},
    }
    assert _progress_aware_plan(summary, [{"stage": "screen", "status": "in-progress"}], campaign, root) is None
    assert _progress_aware_plan(summary, [{"stage": "screen", "status": "not-started"}], campaign, root)["operation_scope"] == "remote-submission"
    complete = _progress_aware_plan(summary, [{"stage": "screen", "status": "complete"}], campaign, root)
    assert complete["operation_scope"] == "local-mutation"
    assert "advance" in complete["command"]


def write_zeeman_source(root, name="source"):
    directory = root / "data/particle_states/after_zeeman" / name
    directory.mkdir(parents=True)
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.zeros((2, 6), dtype=float))
        digest = hashlib.sha256(state.read_bytes()).hexdigest()
        state.with_suffix(".json").write_text(json.dumps({
            "shape": [2, 6], "dtype": "float64", "n_survivors": 2,
            "output_sha256": digest,
            "parameters": {"seed": seed, "resolved_zeeman_magnet_profile": "profile", "n_initial_atoms": 50000, "dt_s": 4e-5},
            "software": {"git_commit": "abc"},
        }))
    return directory


def test_zeeman_source_registry_requires_all_valid_frozen_inputs(tmp_path):
    root = tmp_path / "repo"; directory = write_zeeman_source(root)
    result = list_sources(root)
    assert result["total"] == 1
    assert result["sources"][0]["ensemble_count"] == 35
    assert result["sources"][0]["path"] == "data/particle_states/after_zeeman/source"
    (directory / "production_zeeman_n50000_dt40us_seed3010.json").unlink()
    result = list_sources(root)
    assert result == {"sources": [], "invalid_count": 1, "total": 0}


@contextmanager
def running_server(request_count=2, repository_root=None, creation_service=None, zeus_service=None, transfer_service=None, submission_service=None):
    handler = type("TestHandler", (ReadOnlyWorkflowHandler,), {})
    handler.sessions = {}
    handler.creation_service = creation_service
    handler.zeus_service = zeus_service
    handler.transfer_service = transfer_service
    handler.submission_service = submission_service
    if repository_root is not None:
        handler.repository_root = repository_root
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    server.block_on_close = False
    server.timeout = 2

    def handle_expected_requests():
        for _ in range(request_count):
            server.handle_request()

    thread = threading.Thread(target=handle_expected_requests, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        thread.join(timeout=5)
        server.server_close()


def request_json(url, *, method="GET", headers=None, request_target=None, body=None):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        connection.request(method, request_target or target, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        return response.status, response.headers, json.loads(raw) if raw else None
    finally:
        connection.close()


def test_local_server_catalog_uses_versioned_workflow_api():
    payload = workflow_catalog_payload()

    assert payload["api_version"] == 1
    assert {item["workflow_id"] for item in payload["data"]} >= {
        "mot_2d_fixed_s0",
        "mot_3d_optimization",
    }
    assert all(item["capabilities"] in (("inspect",), ()) for item in payload["data"])


def test_loopback_health_and_workflow_endpoints_are_read_only_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/health")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert payload == {"api_version": 1, "status": "ok"}

        status, headers, payload = request_json(f"{base_url}/api/workflows")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert payload["api_version"] == 1
        assert {row["workflow_id"] for row in payload["data"]} >= {
            "mot_2d_fixed_s0",
            "mot_3d_optimization",
        }


def test_loopback_unknown_and_mutating_requests_are_rejected_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/unknown")
        assert status == 404
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"error": {"code": "not_found", "message": "Not found."}}

        status, headers, payload = request_json(
            f"{base_url}/api/workflows", method="POST"
        )
        assert status == 405
        assert headers["Cache-Control"] == "no-store"
        assert headers["Allow"] == "GET, POST"
        assert payload == {"error": {"code": "method_not_allowed", "message": "This method is not available."}}


def test_every_non_get_method_is_json_read_only_rejection():
    methods = ("PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
    with running_server(request_count=len(methods)) as base_url:
        for method in methods:
            status, headers, payload = request_json(f"{base_url}/api/workflows", method=method)
            assert status == 405
            assert headers["Cache-Control"] == "no-store"
            assert headers["X-Content-Type-Options"] == "nosniff"
            if method != "HEAD":
                assert payload["error"]["code"] == "method_not_allowed"


def test_host_query_and_absolute_targets_fail_closed():
    with running_server(request_count=3) as base_url:
        status, _, payload = request_json(f"{base_url}/api/health", headers={"Host": "evil.example"})
        assert status == 400 and payload["error"]["code"] == "untrusted_host"
        status, _, payload = request_json(f"{base_url}/api/health?path=x")
        assert status == 400 and payload["error"]["code"] == "unsupported_query"
        status, _, payload = request_json(f"{base_url}/api/health", request_target="http://evil.example/api/health")
        assert status == 400 and payload["error"]["code"] == "invalid_request_target"


def test_campaign_endpoints_discover_only_allowlisted_direct_manifests(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_2d" / "same-name-a"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign", "name": "same name", "stage": "complete",
        "s0_values": [1.3], "provenance": {"git_commit": "abc"},
        "ensemble_source": {"zeeman_profile": "profile"},
    }))
    second = campaign.parent / "same-name-b"
    second.mkdir()
    (second / "campaign.json").write_text((campaign / "campaign.json").read_text())
    nested = campaign.parent / "not-a-campaign" / "nested"
    nested.mkdir(parents=True)
    (nested / "campaign.json").write_text((campaign / "campaign.json").read_text())

    with running_server(request_count=2, repository_root=root) as base_url:
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns")
        assert status == 200
        rows = payload["data"]["campaigns"]
        assert len(rows) == 2
        assert rows[0]["id"] != rows[1]["id"]
        assert all(not row["path"].startswith("/") for row in rows)
        status, _, detail = request_json(f"{base_url}/api/v1/campaigns/{rows[0]['id']}")
        assert status == 200
        assert detail["data"]["scheduler_status"] == "unchecked"
        assert detail["data"]["trust"] == "legacy-incomplete"
        assert detail["data"]["scientific_role"] == "historical-evidence"
        assert detail["data"]["next_plan"] is None


def test_campaign_endpoint_rejects_encoded_or_unknown_ids(tmp_path):
    with running_server(request_count=2, repository_root=tmp_path) as base_url:
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/%252e%252e")
        assert status == 400
        assert payload["error"]["code"] == "invalid_campaign_id"
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/mot_2d-missing")
        assert status == 404
        assert payload["error"]["code"] == "campaign_not_found"


def test_unexpected_discovery_error_returns_safe_json(monkeypatch):
    def fail(_root):
        raise OSError("secret /absolute/path")

    monkeypatch.setattr("workflow_api.server.list_campaigns", fail)
    with running_server(request_count=1) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/campaigns")
    assert status == 500
    assert headers["Cache-Control"] == "no-store"
    assert payload == {"error": {"code": "inspection_failed", "message": "Campaign inspection failed safely."}}
    assert "/absolute/path" not in json.dumps(payload)


def test_validated_complete_stage_offers_copy_only_local_advance(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_2d" / "modern"
    smoke = campaign / "smoke" / "s0_1p300000"
    jobs = campaign / "jobs"
    smoke.mkdir(parents=True); jobs.mkdir()
    manifest = modern_2d_manifest(root)
    (campaign / "campaign.json").write_text(json.dumps(manifest))
    (jobs / "01_smoke.pbs").write_text("#!/bin/bash\n")
    write_valid_smoke(campaign, manifest)

    with running_server(request_count=2, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
        campaign_id = listing["data"]["campaigns"][0]["id"]
        status, _, detail = request_json(f"{base_url}/api/v1/campaigns/{campaign_id}")

    assert status == 200
    row = detail["data"]
    assert row["trust"] == "trusted-current"
    assert row["progress"][0]["status"] == "complete"
    assert row["next_plan"]["operation_scope"] == "local-mutation"
    assert row["next_plan"]["mode"] == "copy-only"
    assert "advance" in row["next_plan"]["command"]
    assert shlex.split(row["next_plan"]["display_command"]) == row["next_plan"]["command"]


def test_copy_command_shell_quotes_hostile_campaign_directory(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_2d" / "name with spaces; $(unsafe) 'quote'"
    smoke = campaign / "smoke" / "s0_1p300000"; jobs = campaign / "jobs"
    smoke.mkdir(parents=True); jobs.mkdir()
    (campaign / "campaign.json").write_text(json.dumps(modern_2d_manifest(root)))
    (jobs / "01_smoke.pbs").write_text("#!/bin/bash\n")
    write_valid_smoke(campaign, modern_2d_manifest(root))

    with running_server(request_count=1, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
    plan = listing["data"]["campaigns"][0]["next_plan"]
    assert shlex.split(plan["display_command"]) == plan["command"]
    assert "'" in plan["display_command"]


def test_3d_structural_manifest_without_verified_frozen_artifacts_is_inspection_only(tmp_path):
    root = tmp_path / "repo"
    campaign = root / "data" / "optimization" / "mot_3d" / "structural-only"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text(json.dumps({
        "kind": "mot_3d_campaign_v2", "name": "structural only", "stage": "dt_validation_required",
        "provenance": {"git_commit": "abc", "physical_model_sha256": "a" * 64},
        "upstream_2d_campaign": {"campaign_path": "fake", "campaign_sha256": "b" * 64, "final_report_path": "fake", "final_report_sha256": "c" * 64, "sealed_seed_pairs": [{"zeeman_seed": 3015, "mot_seed": 43015}], "expected_survivor_design": {"solver": "RK4StHybridCustom"}, "expected_survivor_parameters": {"s0": 1.3}},
        "input_roles": {"discovery": [{"path": "x", "metadata_path": "y", "sha256": "d" * 64, "metadata_sha256": "e" * 64, "shape": [1, 6], "dtype": "float64", "zeeman_seed": 3015, "mot_seed": 43015, "source_design": {}, "source_parameters": {}}]},
        "design": {"families": ["angled_donut", "single_pass"], "solver": "RK4StHybridCustom", "screening_dt_s": 1.25e-6, "production_dt_s": 0.625e-6, "timestep_status": "provisional_pending_3d_validation", "optimization_bounds": {}, "selection_statistics": {}},
    }))

    with running_server(request_count=1, repository_root=root) as base_url:
        _, _, listing = request_json(f"{base_url}/api/v1/campaigns")
    row = listing["data"]["campaigns"][0]
    assert row["trust"] == "legacy-incomplete"
    assert row["scientific_role"] == "historical-evidence"
    assert row["next_plan"] is None
    assert row["progress"] == []


def test_server_import_does_not_cross_the_simulation_or_study_boundary():
    code = (
        "import sys; import workflow_api.server; "
        "assert not any(name == 'simulations' or name.startswith('simulations.') "
        "or name == 'studies' or name.startswith('studies.') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_documented_development_command_starts_api_and_ui():
    package = json.loads(Path("ui/package.json").read_text())
    launcher = Path("ui/scripts/dev.mjs").read_text()
    assert package["scripts"]["dev"] == "node scripts/dev.mjs"
    assert '["-m", "workflow_api.server"]' in launcher
    assert '"vite.js"' in launcher
    assert "shell: true" not in launcher


class _FixedSnapshots:
    def capture(self): return RepositorySnapshot("a" * 40)


def _creation_service(root):
    write_zeeman_source(root)
    for relative in RELEVANT_FILES:
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(relative)
    lab = root / "lab_setup/model.py"; lab.parent.mkdir(exist_ok=True); lab.write_text("MODEL = 1")
    return CreationService(root, _FixedSnapshots())


def _session_headers(base_url, cookie, csrf):
    host = urlsplit(base_url).netloc
    return {"Content-Type": "application/json", "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": csrf, "Cookie": cookie}


def test_creation_requires_same_origin_csrf_and_confirm_is_local_only(tmp_path):
    root = tmp_path / "repo"; service = _creation_service(root)
    with running_server(request_count=5, repository_root=root, creation_service=service) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert status == 200
        cookie = headers["Set-Cookie"].split(";", 1)[0]; csrf = payload["data"]["csrf_token"]
        body = json.dumps({"name": "Fixed s0 1.3", "slug": "s0_1p3", "source_id": list_sources(root)["sources"][0]["id"], "s0_values": [1.3]})
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/2d/preview", method="POST", headers={"Content-Type": "application/json"}, body=body)
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        trusted = _session_headers(base_url, cookie, csrf)
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/2d/preview", method="POST", headers=trusted, body=body)
        assert status == 200 and payload["data"]["preview_token"]
        confirm = json.dumps({"preview_token": payload["data"]["preview_token"]})
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/2d/confirm", method="POST", headers=trusted, body=confirm)
        assert status == 201
        assert payload["data"]["submitted_to_zeus"] is False
        status, _, replay = request_json(f"{base_url}/api/v1/campaigns/2d/confirm", method="POST", headers=trusted, body=confirm)
        assert status == 201 and replay == payload


def test_creation_rejects_unknown_fields_and_oversized_body(tmp_path):
    root = tmp_path / "repo"; service = _creation_service(root)
    with running_server(request_count=3, repository_root=root, creation_service=service) as base_url:
        _, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/2d/preview", method="POST", headers=trusted, body=json.dumps({"password": "never"}))
        assert status == 400
        oversized_headers = {**trusted, "Content-Length": str(33 * 1024)}
        status, _, payload = request_json(f"{base_url}/api/v1/campaigns/2d/preview", method="POST", headers=oversized_headers, body="{}")
        assert status == 413


def test_cross_site_request_cannot_allocate_creation_session(tmp_path):
    root = tmp_path / "repo"; service = _creation_service(root)
    with running_server(request_count=2, repository_root=root, creation_service=service) as base_url:
        status, _, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"})
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert status == 200 and payload["data"]["csrf_token"]


class _FakeZeusService:
    def __init__(self): self.payload = None
    def snapshot(self, payload):
        ZeusProfile.parse(payload)
        self.payload = payload
        return {
            "connection_status": "connected",
            "profile": {"host": "zeus.technion.ac.il", "username": payload["username"], "project_directory": payload["project_directory"], "authentication": "ssh-key-or-agent"},
            "remote": {"project_directory": payload["project_directory"], "git_commit": "a" * 40, "branch": "main", "dirty": False},
            "scheduler": {"status": "available", "queried_at": "2026-10-08T00:00:00+00:00", "jobs": []},
        }


class _FakeTransferService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        if set(payload) != {"campaign_id", "username", "project_directory"}:
            raise ZeusPreparationError("request_invalid")
        if self.error:
            raise self.error
        return {
            "preview_token": "review-token", "expires_in_seconds": 300,
            "campaign": {"id": payload["campaign_id"], "name": "Campaign", "path": "data/optimization/mot_2d/c", "git_commit": "a" * 40},
            "destination": {"host": "zeus.technion.ac.il", "project_directory": payload["project_directory"], "campaign_directory": f'{payload["project_directory"]}/data/optimization/mot_2d/c'},
            "artifacts": {"ensemble_count": 35, "total_count": 72, "missing_count": 72, "identical_count": 0, "total_bytes": 100, "missing_bytes": 100},
            "effects": {"copy_missing_only": True, "overwrite_existing": False, "submit_jobs": False, "run_simulation": False},
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        if set(payload) != {"preview_token"}:
            raise ZeusPreparationError("request_invalid")
        if self.error:
            raise self.error
        return {
            "status": "prepared", "campaign_id": "mot_2d-id",
            "destination": "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/c",
            "transferred_count": 72, "reused_identical_count": 0, "bytes_transferred": 100,
            "submitted_to_zeus": False, "simulation_started": False,
        }


def test_zeus_snapshot_requires_explicit_same_origin_csrf_and_never_accepts_password():
    service = _FakeZeusService()
    with running_server(request_count=4, zeus_service=service) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert status == 200
        trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
        body = json.dumps({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"})
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/snapshot", method="POST", headers={"Content-Type": "application/json"}, body=body)
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/snapshot", method="POST", headers=trusted, body=body)
        assert status == 200 and payload["data"]["connection_status"] == "connected"
        assert service.payload == {"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/snapshot", method="POST", headers=trusted, body=json.dumps({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new", "password": "never"}))
        assert status == 400 and payload["error"]["code"] == "invalid_request"


def test_zeus_transfer_preview_and_confirm_require_session_csrf_and_never_submit():
    service = _FakeTransferService()
    with running_server(request_count=5, transfer_service=service) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert status == 200
        trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
        request = {"campaign_id": "mot_2d-id", "username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
        body = json.dumps(request)
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/transfers/preview", method="POST", headers={"Content-Type": "application/json"}, body=body)
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/transfers/preview", method="POST", headers=trusted, body=body)
        assert status == 200 and payload["data"]["effects"]["submit_jobs"] is False
        token = payload["data"]["preview_token"]
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/transfers/confirm", method="POST", headers=trusted, body=json.dumps({"preview_token": token}))
        assert status == 201
        assert payload["data"]["submitted_to_zeus"] is False
        assert payload["data"]["simulation_started"] is False
        assert service.calls[0][1] == request
        assert service.calls[0][2] == service.calls[1][2]
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/transfers/confirm", method="POST", headers=trusted, body=json.dumps({"preview_token": token, "extra": True}))
        assert status == 400 and payload["error"]["code"] == "request_invalid"


def test_zeus_transfer_unavailable_and_errors_are_sanitized():
    with running_server(request_count=1) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/transfers/preview", method="POST",
            headers={"Content-Type": "application/json"}, body="{}",
        )
        assert status == 503 and payload["error"] == {"code": "zeus_preparation_unavailable", "message": "Zeus campaign preparation is unavailable."}

    service = _FakeTransferService(ZeusPreparationError("remote_input_conflict"))
    with running_server(request_count=2, transfer_service=service) as base_url:
        _, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
        request = {"campaign_id": "mot_2d-id", "username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
        status, _, payload = request_json(f"{base_url}/api/v1/zeus/transfers/preview", method="POST", headers=trusted, body=json.dumps(request))
        assert status == 409
        assert payload["error"] == {"code": "remote_input_conflict", "message": "A required Zeus input differs from the frozen campaign input."}


class _FakeSubmissionService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def preview(self, payload, *, session_id):
        self.calls.append(("preview", payload, session_id))
        if set(payload) != {"campaign_id", "username", "project_directory"}:
            raise ZeusSubmissionError("request_invalid")
        if self.error:
            raise self.error
        return {
            "preview_token": "submit-token", "expires_in_seconds": 300,
            "campaign": {"id": payload["campaign_id"], "name": "Campaign", "path": "data/optimization/mot_2d/c", "git_commit": "a" * 40, "s0_values": [1.3]},
            "stage": {"id": "smoke", "label": "Smoke check", "purpose": "Validate first."},
            "job": {"file": "jobs/01_smoke.pbs", "kind": "job", "task_count": 1, "queue": "zeus_combined_q", "cores_per_task": 1, "memory_per_task_bytes": 68719476736, "walltime_seconds": 1200},
            "remote": {"host": "zeus.technion.ac.il", "project_directory": payload["project_directory"], "commit": "a" * 40, "branch": "main", "dirty": False},
            "inputs": {"verified_count": 72, "status": "ready"},
            "effects": {"submit_smoke": True, "submit_later_stages": False, "modify_files": False},
            "later_stages_locked": True,
        }

    def confirm(self, payload, *, session_id):
        self.calls.append(("confirm", payload, session_id))
        if set(payload) != {"preview_token"}:
            raise ZeusSubmissionError("request_invalid")
        if self.error:
            raise self.error
        return {"status": "submitted", "campaign_id": "mot_2d-id", "stage": "smoke", "job_id": "12345.zeus-master", "submitted_at": "2026-10-08T18:00:00+00:00", "later_stages_locked": True}


def test_smoke_submission_endpoints_require_same_session_csrf_and_exact_payload():
    service = _FakeSubmissionService()
    with running_server(request_count=5, submission_service=service) as base_url:
        status, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert status == 200
        trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
        request = {"campaign_id": "mot_2d-id", "username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
        preview_url = f"{base_url}/api/v1/zeus/submissions/smoke/preview"
        confirm_url = f"{base_url}/api/v1/zeus/submissions/smoke/confirm"
        status, _, payload = request_json(preview_url, method="POST", headers={"Content-Type": "application/json"}, body=json.dumps(request))
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, _, payload = request_json(preview_url, method="POST", headers=trusted, body=json.dumps(request))
        assert status == 200 and payload["data"]["stage"]["id"] == "smoke"
        token = payload["data"]["preview_token"]
        status, _, payload = request_json(confirm_url, method="POST", headers=trusted, body=json.dumps({"preview_token": token}))
        assert status == 201 and payload["data"]["job_id"] == "12345.zeus-master"
        assert service.calls[0][2] == service.calls[1][2]
        status, _, payload = request_json(confirm_url, method="POST", headers=trusted, body=json.dumps({"preview_token": token, "command": "qdel 1"}))
        assert status == 400 and payload["error"]["code"] == "request_invalid"


def test_smoke_submission_unavailable_and_uncertain_errors_are_sanitized():
    with running_server(request_count=1) as base_url:
        status, _, payload = request_json(
            f"{base_url}/api/v1/zeus/submissions/smoke/preview", method="POST",
            headers={"Content-Type": "application/json"}, body="{}",
        )
        assert status == 503
        assert payload["error"] == {"code": "zeus_submission_unavailable", "message": "Zeus smoke submission is unavailable."}

    for code, expected_message in (
        ("submission_outcome_unknown", "Automatic retry is blocked"),
        ("smoke_already_started", "outputs already exist"),
    ):
        service = _FakeSubmissionService(ZeusSubmissionError(code))
        with running_server(request_count=2, submission_service=service) as base_url:
            _, headers, payload = request_json(f"{base_url}/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
            trusted = _session_headers(base_url, headers["Set-Cookie"].split(";", 1)[0], payload["data"]["csrf_token"])
            request = {"campaign_id": "mot_2d-id", "username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
            status, _, payload = request_json(f"{base_url}/api/v1/zeus/submissions/smoke/preview", method="POST", headers=trusted, body=json.dumps(request))
            assert status == 409
            assert payload["error"]["code"] == code
            assert expected_message in payload["error"]["message"]
            assert "/home/" not in payload["error"]["message"]

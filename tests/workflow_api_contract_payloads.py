"""Independent deterministic DTOs returned by contract-test fake services."""

from __future__ import annotations

from copy import deepcopy

_MOT3D_SOURCE_ID = "mot3d-source-" + "a" * 32
_MOT3D_PARAMETERS = {
    "green_s0": 30,
    "green_detuning_gamma": -25,
    "green_waist_m": 0.0075,
    "blue_s0": 1.5,
    "blue_waist_m": 0.0075,
    "magnetic_gradient_G_cm": 2.5,
    "blue_detuning_gamma": -3,
    "core_shell_split_radius_m": 0.0025,
}
_MOT3D_CONTRACT_PAYLOADS = {
    "mot3d-sources": {
        "contract_version": "mot-3d-individual-source-catalog-v1",
        "sources": [
            {
                "id": _MOT3D_SOURCE_ID,
                "source_kind": "canonical_2d_campaign",
                "label": "campaign · s0 1.3",
                "ensemble_count": 20,
                "available_particle_count": {
                    "pooled": 100,
                    "minimum_per_ensemble": 5,
                    "maximum_per_ensemble": 5,
                },
                "source_qualification": "canonical_campaign_source",
                "result_suitability": "individual_only",
                "provenance": {
                    "validation": "completed_canonical_2d_campaign",
                    "campaign_name": "campaign",
                    "s0": 1.3,
                    "ensemble_count": 20,
                    "campaign_sha256": "a" * 64,
                    "final_report_sha256": "b" * 64,
                    "fingerprint": "c" * 64,
                },
            }
        ],
        "invalid_count": 0,
        "total": 1,
        "truncated": False,
    },
    "mot3d-run-preview": {
        "preview_token": "mot3d-token",
        "expires_in_seconds": 300,
        "plan": {
            "run_id": "mot3d-contract",
            "family": "mot_3d",
            "source": {
                "id": _MOT3D_SOURCE_ID,
                "kind": "canonical_2d_campaign",
                "qualification": "canonical_campaign_source",
                "fingerprint": "c" * 64,
                "pooled_particle_count": 100,
            },
            "selection": {
                "algorithm": "pcg64-raw-partial-fisher-yates-unbiased",
                "version": "v1",
                "seed": 1,
                "selected_count": 20,
                "selected_identities_sha256": "c" * 64,
            },
            "geometry": {
                "family": "angled_donut",
                "parameters": _MOT3D_PARAMETERS,
                "derived_parameters": {},
            },
            "execution": {"mode": "local", "particle_count": 20, "simulation_seed": 2},
            "retention": {"particle_states": False},
            "suitability": "individual_only",
            "output_disposition": "discard_survivor_states_after_summary",
            "locked_settings": {
                "solver": "RK4StHybridCustom",
                "timestep_s": 0.00001,
                "t_max_s": 0.1,
                "convergence_claim": "not_established",
                "capture": {
                    "capture_radius_m": 0.005,
                    "maximum_final_speed_m_s": 1,
                    "minimum_residence_time_s": 0.005,
                },
                "sampling_algorithm": "pcg64-raw-partial-fisher-yates-unbiased",
                "sampling_version": "v1",
                "workers": 8,
            },
            "lifecycle_state": "configured",
            "laboratory_specification": {
                "version": "laboratory-physical-v2",
                "sha256": "1ef77eecdd306d2d92c08fde9897f283de57e741e9f1a45a6bc6c0063779eac3",
            },
            "numerical_policy": {
                "version": "numerical-policy-v1",
                "sha256": "08a6ad18017ff9a649e46dc94595be24922b3838ffd7c183cdf1a9c9c097cef1",
            },
            "plan_sha256": "d" * 64,
            "execution_started": False,
            "submitted_to_zeus": False,
        },
    },
    "mot3d-run-confirm": {
        "status": "created",
        "run_id": "mot3d-contract",
        "family": "mot_3d",
        "path": "data/runs/mot_3d/mot3d-contract",
        "lifecycle_state": "configured",
        "execution_started": False,
        "submitted_to_zeus": False,
    },
    "mot3d-local-start": {
        "status": "queued",
        "run_id": "mot3d-contract",
        "execution_mode": "local",
    },
    "mot3d-zeus-preview": {
        "preview_token": "mot3d-zeus-token",
        "expires_in_seconds": 300,
        "run_id": "mot3d-contract",
        "job": {"kind": "scalar", "array": False, "pbs_sha256": "b" * 64},
        "package_sha256": "c" * 64,
        "submission_key": "d" * 64,
        "effects": {
            "submit_one_job": True,
            "reconcile_existing_job": False,
            "cancel_job": False,
        },
    },
    "mot3d-zeus-confirm": {
        "status": "submitted",
        "run_id": "mot3d-contract",
        "job_id": "502.zeus-master",
        "submission_key": "d" * 64,
    },
    "mot3d-zeus-refresh": {"state": "running", "job_id": "502.zeus-master"},
}

_PAYLOADS = {
    "campaign-detail": {
        "families": [],
        "family": "mot_2d",
        "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "id": "campaign-id",
        "kind": "mot_2d_s0_campaign",
        "name": "Campaign",
        "next_plan": None,
        "path": "data/optimization/mot_2d/campaign-id",
        "progress": [],
        "remote_preparation": {"reason_code": None, "status": "ready"},
        "s0_values": [1.3],
        "scheduler_status": "unchecked",
        "scientific_role": "candidate-selection",
        "stage": "smoke",
        "stage_semantics": "prepared-workflow-stage",
        "trust": "trusted-current",
        "warnings": [],
    },
    "campaigns": {"campaigns": [], "invalid_count": 0, "total": 0},
    "confirmation-confirm": {
        "artifacts": {"created": 3, "updated": 1},
        "campaign_id": "campaign-id",
        "local_sync": {"status": "not_synchronized"},
        "simulation_started": False,
        "stage": "confirmation",
        "status": "confirmation_prepared",
        "submitted_to_zeus": False,
    },
    "confirmation-submit-confirm": {
        "campaign_id": "campaign-id",
        "job_id": "401[].zeus-master",
        "local_sync": {"status": "not_synchronized"},
        "stage": "confirmation",
        "status": "submitted",
        "submitted_at": "2026-10-08T00:00:00+00:00",
    },
    "confirmation-submit-preview": {
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "s0_values": [1.3],
        },
        "effects": {
            "modify_campaign_files": False,
            "record_submission_receipt": True,
            "start_simulation": True,
            "submit_confirmation": True,
            "submit_later_stages": False,
        },
        "expires_in_seconds": 300,
        "job": {
            "array_throttle": 3,
            "cores_per_task": 200,
            "file": "jobs/04_confirmation.pbs",
            "kind": "array",
            "memory_per_task_bytes": 68719476736,
            "queue": "zeus_combined_q",
            "task_count": 5,
            "walltime_seconds": 36000,
        },
        "local_sync": {"status": "not_synchronized"},
        "preview_token": "confirmation-submit-token",
        "remote": {
            "branch": "main",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "dirty": False,
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "stage": {"id": "confirmation", "label": "Confirmation"},
    },
    "confirmation-submit-status": {
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "confirmation"},
        "local_sync": {"status": "not_synchronized"},
        "next_action": "review_submission",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "source": "zeus",
        "submission": {"job_id": None, "status": "not_submitted"},
    },
    "confirmation-preview": {
        "artifacts": {
            "create": [
                "refined_candidates.json",
                "confirmation/tasks.json",
                "jobs/04_confirmation.pbs",
            ],
            "update": ["campaign.json"],
        },
        "bounds": {
            "detuning_gamma": {"high": -0.1, "low": -3.0},
            "magnet_radius_m": {"high": 0.06, "low": 0.03},
        },
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "s0_values": [1.3],
        },
        "effects": {
            "overwrite_existing": False,
            "prepare_confirmation": True,
            "start_simulation": False,
            "submit_confirmation": False,
        },
        "expires_in_seconds": 300,
        "from_stage": "refine",
        "job": {
            "array_throttle": 3,
            "cores_per_task": 200,
            "file": "jobs/04_confirmation.pbs",
            "kind": "array",
            "memory_per_task_bytes": 68719476736,
            "queue": "zeus_combined_q",
            "task_count": 5,
            "walltime_seconds": 36000,
        },
        "local_sync": {"status": "not_synchronized"},
        "preview_token": "confirmation-token",
        "refinement": {
            "candidates": [
                {
                    "detuning_gamma": -1.01,
                    "magnet_radius_m": 0.0401,
                    "mean_conditional_efficiency": 0.05,
                    "rank": 1,
                    "s0": 1.3,
                    "source": "refine/s0_1p300000/worker0/trials/trial_0001.json",
                },
                {
                    "detuning_gamma": -1.02,
                    "magnet_radius_m": 0.0402,
                    "mean_conditional_efficiency": 0.04,
                    "rank": 2,
                    "s0": 1.3,
                    "source": "refine/s0_1p300000/worker1/trials/trial_0002.json",
                },
                {
                    "detuning_gamma": -1.03,
                    "magnet_radius_m": 0.0403,
                    "mean_conditional_efficiency": 0.03,
                    "rank": 3,
                    "s0": 1.3,
                    "source": "refine/s0_1p300000/worker2/trials/trial_0003.json",
                },
                {
                    "detuning_gamma": -1.04,
                    "magnet_radius_m": 0.0404,
                    "mean_conditional_efficiency": 0.02,
                    "rank": 4,
                    "s0": 1.3,
                    "source": "refine/s0_1p300000/worker0/trials/trial_0004.json",
                },
                {
                    "detuning_gamma": -1.05,
                    "magnet_radius_m": 0.0405,
                    "mean_conditional_efficiency": 0.01,
                    "rank": 5,
                    "s0": 1.3,
                    "source": "refine/s0_1p300000/worker1/trials/trial_0005.json",
                },
            ],
            "completed_trials": 30,
            "expected_trials": 30,
            "round_job_ids": [
                "301[].zeus-master",
                "302[].zeus-master",
                "303[].zeus-master",
                "304[].zeus-master",
            ],
        },
        "to_stage": "confirmation",
    },
    "confirmation-status": {
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "refine"},
        "chain": {
            "rounds": [
                {
                    "depends_on_job_id": None,
                    "job_id": "301[].zeus-master",
                    "round": 1,
                    "scheduler": {
                        "counts": {
                            "failed": 0,
                            "held": 0,
                            "queued": 0,
                            "running": 0,
                            "succeeded": 3,
                        },
                        "state": "completed_success",
                        "task_count": 3,
                    },
                },
                {
                    "depends_on_job_id": "301[].zeus-master",
                    "job_id": "302[].zeus-master",
                    "round": 2,
                    "scheduler": {
                        "counts": {
                            "failed": 0,
                            "held": 0,
                            "queued": 0,
                            "running": 0,
                            "succeeded": 3,
                        },
                        "state": "completed_success",
                        "task_count": 3,
                    },
                },
                {
                    "depends_on_job_id": "302[].zeus-master",
                    "job_id": "303[].zeus-master",
                    "round": 3,
                    "scheduler": {
                        "counts": {
                            "failed": 0,
                            "held": 0,
                            "queued": 0,
                            "running": 0,
                            "succeeded": 3,
                        },
                        "state": "completed_success",
                        "task_count": 3,
                    },
                },
                {
                    "depends_on_job_id": "303[].zeus-master",
                    "job_id": "304[].zeus-master",
                    "round": 4,
                    "scheduler": {
                        "counts": {
                            "failed": 0,
                            "held": 0,
                            "queued": 0,
                            "running": 0,
                            "succeeded": 3,
                        },
                        "state": "completed_success",
                        "task_count": 3,
                    },
                },
            ],
            "status": "ready_to_prepare_confirmation",
        },
        "local_sync": {"status": "not_synchronized"},
        "next_action": "review_confirmation_preparation",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "source": "zeus",
        "validation": {
            "candidate_count": 5,
            "completed_trials": 30,
            "expected_trials": 30,
            "status": "valid",
        },
    },
    "sensitivity-status": {
        "source": "zeus",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "confirmation"},
        "confirmation": {
            "status": "ready_to_prepare_sensitivity",
            "job_id": "401[].zeus-master",
            "scheduler": {
                "state": "completed_success",
                "task_count": 5,
                "counts": {
                    "queued": 0,
                    "running": 0,
                    "held": 0,
                    "succeeded": 5,
                    "failed": 0,
                },
                "job_id": "401[].zeus-master",
                "submission_nonce": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
        },
        "validation": {"status": "valid", "completed_points": 5, "expected_points": 5},
        "next_action": "review_sensitivity_preparation",
        "local_sync": {"status": "not_synchronized"},
    },
    "sensitivity-preview": {
        "preview_token": "sensitivity-token",
        "expires_in_seconds": 300,
        "campaign": {
            "id": "campaign-id",
            "name": "Campaign",
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "s0_values": [1.3],
        },
        "from_stage": "confirmation",
        "to_stage": "sensitivity",
        "confirmation": {
            "job_id": "401[].zeus-master",
            "completed_points": 5,
            "expected_points": 5,
        },
        "artifacts": {
            "create": [
                "winners.json",
                "sensitivity/tasks.json",
                "jobs/05_sensitivity.pbs",
            ],
            "update": ["campaign.json"],
        },
        "job": {
            "file": "jobs/05_sensitivity.pbs",
            "kind": "array",
            "task_count": 17,
            "array_throttle": 3,
            "queue": "zeus_combined_q",
            "cores_per_task": 200,
            "memory_per_task_bytes": 68719476736,
            "walltime_seconds": 36000,
        },
        "effects": {
            "prepare_sensitivity": True,
            "submit_sensitivity": False,
            "start_simulation": False,
            "overwrite_existing": False,
        },
        "local_sync": {"status": "not_synchronized"},
    },
    "sensitivity-confirm": {
        "status": "sensitivity_prepared",
        "campaign_id": "campaign-id",
        "stage": "sensitivity",
        "artifacts": {"created": 3, "updated": 1},
        "submitted_to_zeus": False,
        "simulation_started": False,
        "local_sync": {"status": "not_synchronized"},
    },
    "sensitivity-submit-status": {
        "source": "zeus",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "sensitivity"},
        "submission": {"status": "not_submitted", "job_id": None},
        "next_action": "review_submission",
        "local_sync": {"status": "not_synchronized"},
    },
    "sensitivity-submit-preview": {
        "preview_token": "sensitivity-submit-token",
        "expires_in_seconds": 300,
        "campaign": {
            "id": "campaign-id",
            "name": "Campaign",
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "s0_values": [1.3],
        },
        "stage": {"id": "sensitivity", "label": "Sensitivity"},
        "job": {
            "file": "jobs/05_sensitivity.pbs",
            "kind": "array",
            "task_count": 17,
            "array_throttle": 3,
            "queue": "zeus_combined_q",
            "cores_per_task": 200,
            "memory_per_task_bytes": 68719476736,
            "walltime_seconds": 36000,
        },
        "remote": {
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "branch": "main",
            "dirty": False,
        },
        "effects": {
            "submit_sensitivity": True,
            "start_simulation": True,
            "submit_later_stages": False,
            "modify_campaign_files": False,
            "record_submission_receipt": True,
        },
        "local_sync": {"status": "not_synchronized"},
    },
    "sensitivity-submit-confirm": {
        "status": "submitted",
        "campaign_id": "campaign-id",
        "stage": "sensitivity",
        "job_id": "402[].zeus-master",
        "submitted_at": "2026-10-08T00:00:00+00:00",
        "local_sync": {"status": "not_synchronized"},
    },
    "creation-confirm": {
        "campaign_id": "campaign-id",
        "path": "data/optimization/mot_2d/campaign-id",
        "stage": "smoke",
        "status": "created",
        "submitted_to_zeus": False,
    },
    "creation-preview": {
        "duplicate": None,
        "expires_in_seconds": 300,
        "plan": {
            "files": ["campaign.json", "jobs/01_smoke.pbs"],
            "name": "Campaign",
            "path": "data/optimization/mot_2d/campaign-id",
            "s0_values": [1.3],
            "source_id": "source",
            "stage": "smoke",
        },
        "preview_token": "creation-token",
        "provenance": {
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "input_count": 35,
        },
        "scientific_design": {},
    },
    "refinement-confirm": {
        "artifacts": {"created": 7, "updated": 1},
        "campaign_id": "campaign-id",
        "local_sync": {"status": "not_synchronized"},
        "simulation_started": False,
        "stage": "refine",
        "status": "refinement_prepared",
        "submitted_to_zeus": False,
    },
    "refinement-preview": {
        "artifacts": {
            "create": [
                "screening_candidates.json",
                "refine/tasks.json",
                "jobs/03_refine_round_01.pbs",
                "jobs/03_refine_round_02.pbs",
                "jobs/03_refine_round_03.pbs",
                "jobs/03_refine_round_04.pbs",
                "jobs/03_submit_refinement_chain.sh",
            ],
            "update": ["campaign.json"],
        },
        "bounds": {
            "detuning_gamma": {"high": -0.1, "low": -3.0},
            "magnet_radius_m": {"high": 0.06, "low": 0.03},
        },
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "s0_values": [1.3],
        },
        "effects": {
            "overwrite_existing": False,
            "prepare_refinement": True,
            "start_simulation": False,
            "submit_refinement": False,
        },
        "expires_in_seconds": 300,
        "from_stage": "screen",
        "local_sync": {"status": "not_synchronized"},
        "preview_token": "refine-token",
        "screening": {
            "candidates": [
                {
                    "detuning_gamma": -1.0,
                    "magnet_radius_m": 0.04,
                    "mean_conditional_efficiency": 0.03,
                    "rank": 1,
                    "s0": 1.3,
                    "source": "screen/s0_1p300000/worker0/trials/trial_0001.json",
                },
                {
                    "detuning_gamma": -1.1,
                    "magnet_radius_m": 0.041,
                    "mean_conditional_efficiency": 0.02,
                    "rank": 2,
                    "s0": 1.3,
                    "source": "screen/s0_1p300000/worker1/trials/trial_0002.json",
                },
                {
                    "detuning_gamma": -1.2,
                    "magnet_radius_m": 0.042,
                    "mean_conditional_efficiency": 0.01,
                    "rank": 3,
                    "s0": 1.3,
                    "source": "screen/s0_1p300000/worker2/trials/trial_0003.json",
                },
            ],
            "completed_trials": 51,
            "expected_trials": 51,
            "job_id": "200[].zeus-master",
        },
        "to_stage": "refine",
    },
    "refinement-submit-confirm": {
        "campaign_id": "campaign-id",
        "chain": {
            "rounds": [
                {"depends_on_job_id": None, "job_id": "301[].zeus-master", "round": 1},
                {
                    "depends_on_job_id": "301[].zeus-master",
                    "job_id": "302[].zeus-master",
                    "round": 2,
                },
                {
                    "depends_on_job_id": "302[].zeus-master",
                    "job_id": "303[].zeus-master",
                    "round": 3,
                },
                {
                    "depends_on_job_id": "303[].zeus-master",
                    "job_id": "304[].zeus-master",
                    "round": 4,
                },
            ],
            "status": "submitted",
        },
        "local_sync": {"status": "not_synchronized"},
        "stage": "refine",
        "status": "submitted",
        "submitted_at": "2026-10-08T00:00:00+00:00",
    },
    "refinement-submit-preview": {
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "s0_values": [1.3],
        },
        "chain": {
            "dependency": "afterok",
            "rounds": [
                {
                    "array_throttle": 3,
                    "cores_per_task": 200,
                    "cumulative_target": 3,
                    "depends_on": None,
                    "file": "jobs/03_refine_round_01.pbs",
                    "kind": "array",
                    "memory_per_task_bytes": 68719476736,
                    "queue": "zeus_combined_q",
                    "round": 1,
                    "task_count": 3,
                    "walltime_seconds": 72000,
                },
                {
                    "array_throttle": 3,
                    "cores_per_task": 200,
                    "cumulative_target": 6,
                    "depends_on": 1,
                    "file": "jobs/03_refine_round_02.pbs",
                    "kind": "array",
                    "memory_per_task_bytes": 68719476736,
                    "queue": "zeus_combined_q",
                    "round": 2,
                    "task_count": 3,
                    "walltime_seconds": 72000,
                },
                {
                    "array_throttle": 3,
                    "cores_per_task": 200,
                    "cumulative_target": 9,
                    "depends_on": 2,
                    "file": "jobs/03_refine_round_03.pbs",
                    "kind": "array",
                    "memory_per_task_bytes": 68719476736,
                    "queue": "zeus_combined_q",
                    "round": 3,
                    "task_count": 3,
                    "walltime_seconds": 72000,
                },
                {
                    "array_throttle": 3,
                    "cores_per_task": 200,
                    "cumulative_target": 10,
                    "depends_on": 3,
                    "file": "jobs/03_refine_round_04.pbs",
                    "kind": "array",
                    "memory_per_task_bytes": 68719476736,
                    "queue": "zeus_combined_q",
                    "round": 4,
                    "task_count": 3,
                    "walltime_seconds": 72000,
                },
            ],
        },
        "effects": {
            "modify_files": False,
            "start_simulation": True,
            "submit_later_stages": False,
            "submit_refinement_chain": True,
        },
        "expires_in_seconds": 300,
        "local_sync": {"status": "not_synchronized"},
        "preview_token": "chain-token",
        "remote": {
            "branch": "main",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "dirty": False,
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "stage": {"id": "refine", "label": "Refinement"},
    },
    "refinement-submit-status": {
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "refine"},
        "chain": {
            "dependency": "afterok",
            "rounds": [
                {
                    "depends_on_job_id": None,
                    "job_id": None,
                    "round": 1,
                    "state": "not_submitted",
                },
                {
                    "depends_on_job_id": None,
                    "job_id": None,
                    "round": 2,
                    "state": "not_submitted",
                },
                {
                    "depends_on_job_id": None,
                    "job_id": None,
                    "round": 3,
                    "state": "not_submitted",
                },
                {
                    "depends_on_job_id": None,
                    "job_id": None,
                    "round": 4,
                    "state": "not_submitted",
                },
            ],
            "status": "not_submitted",
        },
        "local_sync": {"status": "not_synchronized"},
        "next_action": "review_submission",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "source": "zeus",
    },
    "screen-status": {
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "screen"},
        "lifecycle": "ready_to_prepare_refinement",
        "next_action": "review_refinement_preparation",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "scheduler": {
            "counts": {
                "failed": 0,
                "held": 0,
                "queued": 0,
                "running": 0,
                "succeeded": 3,
            },
            "exit_status": 0,
            "raw_state": "F",
            "state": "completed_success",
            "task_count": 3,
        },
        "source": "zeus",
        "submission": {"job_id": "200[].zeus-master"},
        "validation": {
            "candidate_count": 3,
            "completed_trials": 51,
            "expected_trials": 51,
            "status": "valid",
        },
    },
    "screen-submit-confirm": {
        "campaign_id": "campaign-id",
        "job_id": "200[].zeus-master",
        "later_stages_locked": True,
        "stage": "screen",
        "status": "submitted",
        "submitted_at": "2026-10-08T00:00:00+00:00",
    },
    "screen-submit-preview": {
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "s0_values": [1.3],
        },
        "effects": {
            "modify_files": False,
            "submit_later_stages": False,
            "submit_screening": True,
        },
        "expires_in_seconds": 300,
        "inputs": {"status": "ready", "verified_count": 72},
        "job": {
            "array_throttle": 3,
            "cores_per_task": 200,
            "file": "jobs/02_screen.pbs",
            "kind": "array",
            "memory_per_task_bytes": 68719476736,
            "queue": "zeus_combined_q",
            "task_count": 3,
            "walltime_seconds": 86400,
        },
        "later_stages_locked": True,
        "preview_token": "screen-submit-token",
        "remote": {
            "branch": "main",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "dirty": False,
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "smoke": {"job_id": "100.zeus-master", "point_count": 1, "status": "validated"},
        "stage": {"id": "screen", "label": "Screening", "purpose": "Broad search."},
    },
    "screening-confirm": {
        "artifacts": {"created": 2, "updated": 1},
        "campaign_id": "campaign-id",
        "local_sync": {"status": "not_synchronized"},
        "simulation_started": False,
        "stage": "screen",
        "status": "screening_prepared",
        "submitted_to_zeus": False,
    },
    "screening-preview": {
        "artifacts": {
            "create": ["screen/tasks.json", "jobs/02_screen.pbs"],
            "update": ["campaign.json"],
        },
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
        },
        "effects": {
            "overwrite_existing": False,
            "prepare_screening": True,
            "start_simulation": False,
            "submit_screening": False,
        },
        "expires_in_seconds": 300,
        "from_stage": "smoke",
        "local_sync": {"status": "not_synchronized"},
        "preview_token": "screen-token",
        "smoke": {
            "artifact_count": 3,
            "job_id": "100.zeus-master",
            "points": [{"captured": 0, "efficiency": 0.0, "input": 2, "s0": 1.3}],
        },
        "to_stage": "screen",
    },
    "smoke-status": {
        "campaign": {"id": "campaign-id", "name": "Campaign", "stage": "smoke"},
        "lifecycle": "ready_to_prepare_screen",
        "next_action": "review_screening_preparation",
        "queried_at": "2026-10-08T00:00:00+00:00",
        "scheduler": {"exit_status": 0, "raw_state": "F", "state": "completed_success"},
        "source": "zeus",
        "submission": {"job_id": "100.zeus-master"},
        "validation": {
            "artifact_count": 3,
            "points": [{"captured": 0, "efficiency": 0.0, "input": 2, "s0": 1.3}],
            "status": "valid",
        },
    },
    "smoke-submit-confirm": {
        "campaign_id": "campaign-id",
        "job_id": "100.zeus-master",
        "later_stages_locked": True,
        "stage": "smoke",
        "status": "submitted",
        "submitted_at": "2026-10-08T00:00:00+00:00",
    },
    "smoke-submit-preview": {
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "path": "data/optimization/mot_2d/campaign-id",
            "s0_values": [1.3],
        },
        "effects": {
            "modify_files": False,
            "submit_later_stages": False,
            "submit_smoke": True,
        },
        "expires_in_seconds": 300,
        "inputs": {"status": "ready", "verified_count": 72},
        "job": {
            "cores_per_task": 1,
            "file": "jobs/01_smoke.pbs",
            "kind": "job",
            "memory_per_task_bytes": 68719476736,
            "queue": "zeus_combined_q",
            "task_count": 1,
            "walltime_seconds": 1200,
        },
        "later_stages_locked": True,
        "preview_token": "smoke-token",
        "remote": {
            "branch": "main",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "dirty": False,
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "stage": {"id": "smoke", "label": "Smoke check", "purpose": "Validate setup."},
    },
    "sources": {"invalid_count": 0, "sources": [], "total": 0},
    "transfer-confirm": {
        "bytes_transferred": 100,
        "campaign_id": "campaign-id",
        "destination": "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/campaign-id",
        "reused_identical_count": 0,
        "simulation_started": False,
        "status": "prepared",
        "submitted_to_zeus": False,
        "transferred_count": 72,
    },
    "transfer-preview": {
        "artifacts": {
            "ensemble_count": 35,
            "identical_count": 0,
            "missing_bytes": 100,
            "missing_count": 72,
            "total_bytes": 100,
            "total_count": 72,
        },
        "campaign": {
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": "campaign-id",
            "name": "Campaign",
            "path": "data/optimization/mot_2d/campaign-id",
        },
        "destination": {
            "campaign_directory": "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/campaign-id",
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "effects": {
            "copy_missing_only": True,
            "overwrite_existing": False,
            "run_simulation": False,
            "submit_jobs": False,
        },
        "expires_in_seconds": 300,
        "preview_token": "transfer-token",
    },
    "workflows": [],
    "zeus-snapshot": {
        "connection_status": "connected",
        "profile": {
            "authentication": "ssh-key-or-agent",
            "host": "zeus.technion.ac.il",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
            "username": "tal.noa",
        },
        "remote": {
            "branch": "main",
            "dirty": False,
            "git_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        "scheduler": {
            "jobs": [],
            "queried_at": "2026-10-08T00:00:00+00:00",
            "status": "available",
        },
    },
}


_FINAL_RESULT = {
    "s0": 1.3,
    "n_ensembles": 20,
    "total_input": 1000,
    "total_survivors": 100,
    "recommended_parameters": {
        "s0": 1.3,
        "detuning_gamma": -0.92,
        "magnet_radius": 0.0467,
    },
    "prediction": {
        "reporting_zeeman_survivors": 10000000,
        "simulated_zeeman_survivors": 1000,
        "simulated_captured_atoms": 100,
        "pooled_conditional_efficiency": 0.1,
        "expected_captured_atoms": 1000000,
        "predicted_95_interval_fraction": [0.09, 0.11],
        "predicted_95_captured_atoms_interval": [900000, 1100000],
        "predicted_95_half_width_fraction": 0.01,
        "predicted_95_half_width_percentage_points": 1.0,
        "binomial_mean_variance": 0.0001,
        "empirical_between_ensemble_mean_variance": 0.0002,
        "selected_mean_variance": 0.0002,
        "selected_mean_variance_source": "empirical_between_ensemble",
        "critical_value": 2.093,
        "future_counting_variance": 9e-9,
        "uncertainty_method": "cluster-aware parametric bootstrap",
        "bootstrap_replicates": 20000,
    },
    "target_uncertainty_passes": True,
    "robustness_status": "not_established_pending_adaptive_challenger_validation",
    "near_optimality_status": "not_established_pending_domain_challenger_elimination",
    "warnings": [
        "robust_operating_region_not_established",
        "epsilon_near_optimality_not_established",
    ],
    "retention": "retained",
    "output_suitability": "eligible_as_3d_campaign_input",
}

_PAYLOADS.update(
    {
        "zeeman-run-preview": {
            "preview_token": "zeeman-token",
            "expires_in_seconds": 300,
            "plan": {
                "run_id": "zeeman-contract",
                "family": "zeeman",
                "execution_mode": "local",
                "particle_count": 10,
                "seed": 42,
                "retain_particle_states": False,
                "suitability": "individual_only",
                "output_disposition": "summary_only",
                "locked_settings": {},
                "resolved_configuration": {},
                "lifecycle_state": "configured",
                "laboratory_specification": {},
                "numerical_policy": {},
                "plan_sha256": "a" * 64,
                "execution_started": False,
                "submitted_to_zeus": False,
            },
        },
        "zeeman-run-confirm": {
            "status": "created",
            "run_id": "zeeman-contract",
            "family": "zeeman",
            "path": "data/runs/zeeman/zeeman-contract",
            "lifecycle_state": "configured",
            "execution_started": False,
            "submitted_to_zeus": False,
        },
        "zeeman-local-start": {
            "status": "queued",
            "run_id": "zeeman-contract",
            "execution_mode": "local",
        },
        "zeeman-zeus-preview": {
            "preview_token": "zeus-token",
            "expires_in_seconds": 300,
            "run_id": "zeeman-contract",
            "job": {"kind": "scalar", "array": False, "pbs_sha256": "b" * 64},
            "package_sha256": "c" * 64,
            "submission_key": "d" * 64,
            "effects": {
                "submit_one_job": True,
                "reconcile_existing_job": False,
                "cancel_job": False,
            },
        },
        "zeeman-zeus-confirm": {
            "status": "submitted",
            "run_id": "zeeman-contract",
            "job_id": "500.zeus-master",
            "submission_key": "d" * 64,
        },
        "zeeman-zeus-refresh": {"state": "running", "job_id": "500.zeus-master"},
        "zeeman-zeus-recover": {
            "run_id": "zeeman-contract",
            "family": "zeeman",
            "job_id": "500.zeus-master",
            "scheduler_state": "running",
            "exit_status": None,
            "local_state": "queued",
            "read_only": True,
        },
        "mot2d-sources": {
            "contract_version": "mot-2d-individual-source-catalog-v1",
            "sources": [],
            "invalid_count": 0,
            "total": 0,
            "truncated": False,
        },
        "mot2d-run-preview": {
            "preview_token": "mot2d-token",
            "expires_in_seconds": 300,
            "plan": {},
        },
        "mot2d-run-confirm": {
            "status": "created",
            "run_id": "mot2d-contract",
            "family": "mot_2d",
            "path": "data/runs/mot_2d/mot2d-contract",
            "lifecycle_state": "configured",
            "execution_started": False,
            "submitted_to_zeus": False,
        },
        "mot2d-local-start": {
            "status": "queued",
            "run_id": "mot2d-contract",
            "execution_mode": "local",
        },
        "mot2d-zeus-preview": {
            "preview_token": "mot2d-zeus-token",
            "expires_in_seconds": 300,
            "run_id": "mot2d-contract",
            "job": {"kind": "scalar", "array": False, "pbs_sha256": "b" * 64},
            "package_sha256": "c" * 64,
            "submission_key": "d" * 64,
            "effects": {
                "submit_one_job": True,
                "reconcile_existing_job": False,
                "cancel_job": False,
            },
        },
        "mot2d-zeus-confirm": {
            "status": "submitted",
            "run_id": "mot2d-contract",
            "job_id": "501.zeus-master",
            "submission_key": "d" * 64,
        },
        "mot2d-zeus-refresh": {"state": "running", "job_id": "501.zeus-master"},
        "mot2d-zeus-recover": {
            "run_id": "mot2d-contract",
            "family": "mot_2d",
            "job_id": "501.zeus-master",
            "scheduler_state": "running",
            "exit_status": None,
            "local_state": "queued",
            "read_only": True,
        },
        "mot3d-sources": _MOT3D_CONTRACT_PAYLOADS["mot3d-sources"],
        "mot3d-run-preview": _MOT3D_CONTRACT_PAYLOADS["mot3d-run-preview"],
        "mot3d-run-confirm": _MOT3D_CONTRACT_PAYLOADS["mot3d-run-confirm"],
        "mot3d-local-start": _MOT3D_CONTRACT_PAYLOADS["mot3d-local-start"],
        "mot3d-zeus-preview": _MOT3D_CONTRACT_PAYLOADS["mot3d-zeus-preview"],
        "mot3d-zeus-confirm": _MOT3D_CONTRACT_PAYLOADS["mot3d-zeus-confirm"],
        "mot3d-zeus-refresh": _MOT3D_CONTRACT_PAYLOADS["mot3d-zeus-refresh"],
        "mot3d-zeus-recover": {
            "run_id": "mot3d-contract",
            "family": "mot_3d",
            "job_id": "502.zeus-master",
            "scheduler_state": "running",
            "exit_status": None,
            "local_state": "queued",
            "read_only": True,
        },
        "production-status": {
            "source": "zeus",
            "queried_at": "2026-10-08T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "stage": "sensitivity",
            },
            "sensitivity": {
                "status": "ready_to_prepare_production",
                "job_id": "402[].zeus-master",
                "scheduler": {
                    "state": "completed_success",
                    "task_count": 17,
                    "counts": {
                        "queued": 0,
                        "running": 0,
                        "held": 0,
                        "succeeded": 17,
                        "failed": 0,
                    },
                    "job_id": "402[].zeus-master",
                    "submission_nonce": "b" * 32,
                },
            },
            "validation": {
                "status": "valid",
                "completed_points": 17,
                "expected_points": 17,
            },
            "next_action": "review_production_preparation",
            "local_sync": {"status": "not_synchronized"},
        },
        "production-preview": {
            "preview_token": "production-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "git_commit": "a" * 40,
                "s0_values": [1.3],
            },
            "from_stage": "sensitivity",
            "to_stage": "production",
            "sensitivity": {
                "job_id": "402[].zeus-master",
                "completed_points": 17,
                "expected_points": 17,
            },
            "artifacts": {
                "create": [
                    "sensitivity_summary.json",
                    "production/tasks.json",
                    "jobs/06_production.pbs",
                ],
                "update": ["campaign.json"],
            },
            "job": {
                "file": "jobs/06_production.pbs",
                "kind": "array",
                "task_count": 20,
                "array_throttle": 4,
                "queue": "zeus_combined_q",
                "cores_per_task": 150,
                "memory_per_task_bytes": 68719476736,
                "walltime_seconds": 43200,
            },
            "effects": {
                "prepare_production": True,
                "submit_production": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        },
        "production-confirm": {
            "status": "production_prepared",
            "campaign_id": "campaign-id",
            "stage": "production",
            "artifacts": {"created": 3, "updated": 1},
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "not_synchronized"},
        },
        "production-submit-status": {
            "source": "zeus",
            "queried_at": "2026-10-08T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "stage": "production",
            },
            "submission": {"status": "not_submitted", "job_id": None},
            "next_action": "review_submission",
            "local_sync": {"status": "not_synchronized"},
        },
        "production-submit-preview": {
            "preview_token": "production-submit-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "git_commit": "a" * 40,
                "s0_values": [1.3],
            },
            "stage": {"id": "production", "label": "Production"},
            "job": {
                "file": "jobs/06_production.pbs",
                "kind": "array",
                "task_count": 20,
                "array_throttle": 4,
                "queue": "zeus_combined_q",
                "cores_per_task": 150,
                "memory_per_task_bytes": 68719476736,
                "walltime_seconds": 43200,
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "effects": {
                "submit_production": True,
                "start_simulation": True,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
            "local_sync": {"status": "not_synchronized"},
        },
        "production-submit-confirm": {
            "status": "submitted",
            "campaign_id": "campaign-id",
            "stage": "production",
            "job_id": "403[].zeus-master",
            "submitted_at": "2026-10-08T00:00:00+00:00",
            "local_sync": {"status": "not_synchronized"},
        },
        "finalization-status": {
            "source": "zeus",
            "queried_at": "2026-10-08T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "stage": "production",
            },
            "production": {
                "status": "ready_to_finalize",
                "job_id": "403[].zeus-master",
                "scheduler": {
                    "state": "completed_success",
                    "task_count": 20,
                    "counts": {
                        "queued": 0,
                        "running": 0,
                        "held": 0,
                        "succeeded": 20,
                        "failed": 0,
                    },
                    "job_id": "403[].zeus-master",
                    "submission_nonce": "c" * 32,
                },
            },
            "validation": {
                "status": "valid",
                "completed_ensembles": 20,
                "expected_ensembles": 20,
            },
            "next_action": "review_finalization",
            "local_sync": {"status": "not_synchronized"},
        },
        "finalization-preview": {
            "preview_token": "finalization-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "Campaign",
                "git_commit": "a" * 40,
                "s0_values": [1.3],
            },
            "from_stage": "production",
            "to_stage": "complete",
            "production": {
                "job_id": "403[].zeus-master",
                "completed_ensembles": 20,
                "expected_ensembles": 20,
            },
            "results": [_FINAL_RESULT],
            "artifacts": {
                "create": ["final_report.json", "production/s0_1p300000/summary.json"],
                "update": ["campaign.json"],
            },
            "effects": {
                "finalize_campaign": True,
                "submit_job": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        },
        "finalization-confirm": {
            "status": "campaign_complete",
            "campaign_id": "campaign-id",
            "stage": "complete",
            "results": [_FINAL_RESULT],
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "not_synchronized"},
        },
        "mot3d-bootstrap-status": {
            "lifecycle": "ready",
            "sources": [],
            "reason": None,
            "evidence_requirement": None,
            "timestep_policy": {
                "status": "pragmatic_user_approved_after_inconclusive_study",
                "convergence_claim": "not_established",
                "sha256": "d" * 64,
            },
        },
        "mot3d-bootstrap-preview": {
            "preview_token": "mot3d-bootstrap-token",
            "expires_in_seconds": 300,
            "campaign": {"name": "mot_3d_contract", "stage": "discovery"},
            "source": {
                "source_id": "a" * 64,
                "campaign_name": "Completed 2D",
                "s0": 1.3,
                "sealed_ensemble_count": 20,
                "completion": "complete",
                "provenance_fingerprint": "b" * 64,
            },
            "discovery": {
                "families": ["angled_donut", "single_pass"],
                "solver": "RK4StHybridCustom",
                "screening_dt_s": 10e-6,
                "production_dt_s": 0.625e-6,
                "timestep_policy_status": "pragmatic_user_approved_after_inconclusive_study",
                "convergence_claim": "not_established",
                "input_role_counts": {
                    "discovery": 12,
                    "refinement": 4,
                    "preliminary_check": 4,
                },
            },
            "artifacts": {
                "create": [
                    "campaign.json",
                    "jobs/01_smoke_angled_donut.pbs",
                    "jobs/01_smoke_single_pass.pbs",
                    "jobs/02_submit_discovery_chain.sh",
                    "jobs/angled_donut/round_01.pbs",
                    "jobs/angled_donut/round_02.pbs",
                    "jobs/single_pass/round_01.pbs",
                    "jobs/single_pass/round_02.pbs",
                    "jobs/single_pass/round_03.pbs",
                ]
            },
            "effects": {
                "create_campaign": True,
                "submit_job": False,
                "start_simulation": False,
                "prepare_dt_validation": False,
            },
        },
        "mot3d-bootstrap-confirm": {
            "lifecycle": "discovery_prepared",
            "campaign_name": "mot_3d_contract",
            "stage": "discovery",
            "submitted_to_zeus": False,
            "bootstrap_key": "c" * 64,
        },
        "mot3d-discovery-status": {
            "source": "zeus",
            "queried_at": "2026-10-11T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "discovery",
            },
            "submission": {
                "status": "not_submitted",
                "chain": {"angled_donut": [], "single_pass": []},
            },
            "next_action": "review_submission",
            "local_sync": {"status": "not_synchronized"},
        },
        "mot3d-discovery-preview": {
            "preview_token": "mot3d-discovery-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "stage": {"id": "discovery", "label": "Discovery"},
            "chain": {
                "families": [
                    {"id": "angled_donut", "rounds": 2},
                    {"id": "single_pass", "rounds": 3},
                ],
                "arrays": 5,
                "tasks_per_array": 3,
                "dependency": "afterok within each family",
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "effects": {
                "submit_discovery_chain": True,
                "submit_smoke": False,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
        },
        "mot3d-discovery-confirm": {
            "status": "submitted",
            "campaign_id": "campaign-id",
            "stage": "discovery",
            "chain": {
                "angled_donut": ["500[].zeus-master", "501[].zeus-master"],
                "single_pass": [
                    "502[].zeus-master",
                    "503[].zeus-master",
                    "504[].zeus-master",
                ],
            },
            "submitted_at": "2026-10-11T00:00:00+00:00",
            "local_sync": {"status": "not_synchronized"},
        },
        "mot3d-transition-status": {
            "source": "zeus",
            "queried_at": "2026-10-12T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "discovery",
            },
            "discovery": {
                "status": "ready_to_advance",
                "chain": {
                    "angled_donut": ["500[].zeus-master", "501[].zeus-master"],
                    "single_pass": [
                        "502[].zeus-master",
                        "503[].zeus-master",
                        "504[].zeus-master",
                    ],
                },
            },
            "validation": {
                "status": "valid",
                "completed_trials": 950,
                "expected_trials": 950,
            },
            "next_action": "review_transition",
            "local_sync": {"status": "not_synchronized", "receipt_sha256": None},
        },
        "mot3d-transition-preview": {
            "preview_token": "mot3d-transition-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "from_stage": "discovery",
            "to_stage": "preliminary_check",
            "discovery": {
                "completed_trials": 950,
                "expected_trials": 950,
                "families": ["angled_donut", "single_pass"],
                "evidence_sha256": "b" * 64,
            },
            "artifacts": {
                "synchronize": {"trial_registries": 950, "merged_files": 4},
                "create": {"selection_files": 2, "job_files": 4},
                "update": ["campaign.json"],
            },
            "effects": {
                "synchronize_discovery": True,
                "prepare_preliminary_check": True,
                "submit_preliminary_check": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
        },
        "mot3d-transition-confirm": {
            "status": "preliminary_check_prepared",
            "campaign_id": "campaign-id",
            "stage": "preliminary_check",
            "artifacts": {
                "synchronized": 954,
                "created": 6,
                "updated": 1,
                "bundle_sha256": "c" * 64,
            },
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
        "mot3d-preliminary-status": {
            "source": "zeus",
            "queried_at": "2026-10-12T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "preliminary_check",
            },
            "submission": {
                "status": "not_submitted",
                "chain": {
                    "dependency": "afterok within each family",
                    "families": [
                        {
                            "id": "angled_donut",
                            "array_job_id": None,
                            "merge_job_id": None,
                        },
                        {
                            "id": "single_pass",
                            "array_job_id": None,
                            "merge_job_id": None,
                        },
                    ],
                },
            },
            "scheduler": {
                "expected_array_tasks": 6,
                "expected_merge_jobs": 2,
                "completed_array_tasks": 0,
                "completed_merge_jobs": 0,
            },
            "validation": {
                "status": "not_started",
                "expected_candidates_per_family": 12,
                "expected_recoil_seeds_per_candidate": 3,
            },
            "next_action": "review_submission",
            "local_sync": {"status": "not_synchronized"},
        },
        "mot3d-preliminary-preview": {
            "preview_token": "mot3d-preliminary-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "stage": {"id": "preliminary_check", "label": "Preliminary check"},
            "chain": {
                "families": [
                    {"id": "angled_donut", "array_tasks": 3, "merge_jobs": 1},
                    {"id": "single_pass", "array_tasks": 3, "merge_jobs": 1},
                ],
                "qsub_calls": 4,
                "dependency": "afterok within each family",
            },
            "resources": {
                "array": {
                    "ncpus_per_task": 200,
                    "memory_gb_per_task": 64,
                    "walltime": "24:00:00",
                },
                "merge": {"ncpus": 1, "memory_gb": 4, "walltime": "01:00:00"},
            },
            "science": {
                "classification": "candidate_selection_not_final_validation",
                "candidates_per_family": 12,
                "input_ensembles": 4,
                "particles_per_ensemble": 150,
                "total_particles": 600,
                "recoil_seeds": [41001, 41002, 41003],
                "dt_s": 1e-5,
                "t_max_s": 0.1,
                "solver": "RK4StHybridCustom",
                "selection_seed": 51001,
                "bootstrap_replicates": 10000,
                "bootstrap_seed": 52001,
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "effects": {
                "submit_preliminary_check": True,
                "start_simulation": True,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
        },
        "mot3d-preliminary-confirm": {
            "status": "submitted",
            "campaign_id": "campaign-id",
            "stage": "preliminary_check",
            "chain": {
                "dependency": "afterok within each family",
                "families": [
                    {
                        "id": "angled_donut",
                        "array_job_id": "510[].zeus-master",
                        "merge_job_id": "511.zeus-master",
                    },
                    {
                        "id": "single_pass",
                        "array_job_id": "512[].zeus-master",
                        "merge_job_id": "513.zeus-master",
                    },
                ],
            },
            "submitted_at": "2026-10-12T00:00:00+00:00",
            "local_sync": {"status": "not_synchronized"},
        },
        "mot3d-refinement-status": {
            "source": "zeus",
            "queried_at": "2026-10-12T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "refinement",
            },
            "submission": {
                "status": "not_submitted",
                "chain": {
                    "dependency": "afterok within each family",
                    "families": [
                        {
                            "id": "angled_donut",
                            "array_job_id": None,
                            "merge_job_id": None,
                        },
                        {
                            "id": "single_pass",
                            "array_job_id": None,
                            "merge_job_id": None,
                        },
                    ],
                },
            },
            "scheduler": {
                "expected_array_tasks": 6,
                "expected_merge_jobs": 2,
                "completed_array_tasks": 0,
                "completed_merge_jobs": 0,
            },
            "validation": {
                "status": "not_started",
                "expected_candidates_per_family": 16,
                "expected_recoil_seeds_per_candidate": 3,
            },
            "next_action": "review_submission",
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
        "mot3d-refinement-preview": {
            "preview_token": "mot3d-refinement-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "stage": {"id": "refinement", "label": "Refinement"},
            "chain": {
                "families": [
                    {"id": "angled_donut", "array_tasks": 3, "merge_jobs": 1},
                    {"id": "single_pass", "array_tasks": 3, "merge_jobs": 1},
                ],
                "qsub_calls": 4,
                "dependency": "afterok within each family",
            },
            "resources": {
                "array": {
                    "ncpus_per_task": 200,
                    "memory_gb_per_task": 64,
                    "walltime": "24:00:00",
                },
                "merge": {"ncpus": 1, "memory_gb": 4, "walltime": "01:00:00"},
            },
            "science": {
                "classification": "candidate_selection_not_final_validation",
                "candidates_per_family": 16,
                "input_ensembles": 4,
                "particles_per_ensemble": 750,
                "total_particles": 3000,
                "recoil_seeds": [42001, 42002, 42003],
                "dt_s": 1e-5,
                "t_max_s": 0.1,
                "solver": "RK4StHybridCustom",
                "selection_seed": 61001,
                "bootstrap_replicates": 10000,
                "bootstrap_seed": 62001,
            },
            "remote": {
                "host": "zeus.technion.ac.il",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
                "commit": "a" * 40,
                "branch": "main",
                "dirty": False,
            },
            "effects": {
                "submit_refinement": True,
                "start_simulation": True,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
        "mot3d-refinement-confirm": {
            "status": "submitted",
            "campaign_id": "campaign-id",
            "stage": "refinement",
            "chain": {
                "dependency": "afterok within each family",
                "families": [
                    {
                        "id": "angled_donut",
                        "array_job_id": "610[].zeus-master",
                        "merge_job_id": "611.zeus-master",
                    },
                    {
                        "id": "single_pass",
                        "array_job_id": "612[].zeus-master",
                        "merge_job_id": "613.zeus-master",
                    },
                ],
            },
            "submitted_at": "2026-10-12T00:00:00+00:00",
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
        "mot3d-preliminary-transition-status": {
            "source": "zeus",
            "queried_at": "2026-10-12T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "preliminary_check",
            },
            "preliminary": {
                "status": "ready_to_advance",
                "chain": {
                    "dependency": "afterok within each family",
                    "families": [
                        {
                            "id": "angled_donut",
                            "array_job_id": "510[].zeus-master",
                            "merge_job_id": "511.zeus-master",
                        },
                        {
                            "id": "single_pass",
                            "array_job_id": "512[].zeus-master",
                            "merge_job_id": "513.zeus-master",
                        },
                    ],
                },
            },
            "scheduler": {
                "expected_array_tasks": 6,
                "expected_merge_jobs": 2,
                "completed_array_tasks": 6,
                "completed_merge_jobs": 2,
            },
            "validation": {
                "status": "valid",
                "result_artifacts": 152,
                "expected_result_artifacts": 152,
                "reason_code": None,
            },
            "transition": {"status": "not_prepared"},
            "next_action": "review_transition",
            "local_sync": {"status": "not_synchronized", "receipt_sha256": None},
        },
        "mot3d-preliminary-transition-preview": {
            "preview_token": "mot3d-preliminary-transition-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "from_stage": "preliminary_check",
            "to_stage": "refinement",
            "preliminary": {
                "result_artifacts": 152,
                "expected_result_artifacts": 152,
                "families": ["angled_donut", "single_pass"],
                "evidence_sha256": "b" * 64,
            },
            "artifacts": {
                "synchronize": {"result_files": 152, "submission_receipts": 1},
                "create": {"selection_files": 2, "job_files": 4},
                "update": ["campaign.json"],
                "transfer_files": 160,
            },
            "effects": {
                "synchronize_preliminary_check": True,
                "prepare_refinement": True,
                "submit_refinement": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
        },
        "mot3d-preliminary-transition-confirm": {
            "status": "refinement_prepared",
            "campaign_id": "campaign-id",
            "stage": "refinement",
            "artifacts": {
                "synchronized": 153,
                "created": 6,
                "updated": 1,
                "bundle_sha256": "c" * 64,
            },
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
        "mot3d-refinement-transition-status": {
            "source": "zeus",
            "queried_at": "2026-10-12T00:00:00+00:00",
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "stage": "refinement",
            },
            "refinement": {
                "status": "ready_to_advance",
                "chain": {
                    "dependency": "afterok within each family",
                    "families": [
                        {
                            "id": "angled_donut",
                            "array_job_id": "610[].zeus-master",
                            "merge_job_id": "611.zeus-master",
                        },
                        {
                            "id": "single_pass",
                            "array_job_id": "612[].zeus-master",
                            "merge_job_id": "613.zeus-master",
                        },
                    ],
                },
            },
            "scheduler": {
                "expected_array_tasks": 6,
                "expected_merge_jobs": 2,
                "completed_array_tasks": 6,
                "completed_merge_jobs": 2,
            },
            "validation": {
                "status": "valid",
                "result_artifacts": 200,
                "expected_result_artifacts": 200,
                "reason_code": None,
            },
            "transition": {"status": "not_prepared"},
            "next_action": "review_transition",
            "local_sync": {"status": "not_synchronized", "receipt_sha256": None},
        },
        "mot3d-refinement-transition-preview": {
            "preview_token": "mot3d-refinement-transition-token",
            "expires_in_seconds": 300,
            "campaign": {
                "id": "campaign-id",
                "name": "mot_3d_contract",
                "git_commit": "a" * 40,
            },
            "from_stage": "refinement",
            "to_stage": "closure",
            "refinement": {
                "result_artifacts": 200,
                "expected_result_artifacts": 200,
                "families": ["angled_donut", "single_pass"],
                "evidence_sha256": "b" * 64,
            },
            "artifacts": {
                "synchronize": {"result_files": 200, "submission_receipts": 1},
                "create": {"selection_files": 2, "job_files": 4},
                "update": ["campaign.json"],
                "transfer_files": 208,
            },
            "effects": {
                "synchronize_refinement": True,
                "prepare_closure": True,
                "submit_closure": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
        },
        "mot3d-refinement-transition-confirm": {
            "status": "closure_prepared",
            "campaign_id": "campaign-id",
            "stage": "closure",
            "artifacts": {
                "synchronized": 201,
                "created": 6,
                "updated": 1,
                "bundle_sha256": "c" * 64,
            },
            "submitted_to_zeus": False,
            "simulation_started": False,
            "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
        },
    }
)

# Closure uses the same reviewed two-family chain contract as Refinement with
# only its stage-specific scientific identity and effect changed.
_PAYLOADS["mot3d-closure-status"] = deepcopy(_PAYLOADS["mot3d-refinement-status"])
_PAYLOADS["mot3d-closure-status"]["campaign"]["stage"] = "closure"
_PAYLOADS["mot3d-closure-preview"] = deepcopy(_PAYLOADS["mot3d-refinement-preview"])
_closure_preview = _PAYLOADS["mot3d-closure-preview"]
_closure_preview["preview_token"] = "mot3d-closure-token"
_closure_preview["stage"] = {"id": "closure", "label": "Closure"}
_closure_preview["science"]["selection_seed"] = 71001
_closure_preview["science"]["bootstrap_seed"] = 72001
_closure_preview["effects"].pop("submit_refinement")
_closure_preview["effects"]["submit_closure"] = True
_PAYLOADS["mot3d-closure-confirm"] = deepcopy(_PAYLOADS["mot3d-refinement-confirm"])
_closure_confirm = _PAYLOADS["mot3d-closure-confirm"]
_closure_confirm["stage"] = "closure"
_closure_confirm["chain"]["families"][0].update(
    {"array_job_id": "710[].zeus-master", "merge_job_id": "711.zeus-master"}
)
_closure_confirm["chain"]["families"][1].update(
    {"array_job_id": "712[].zeus-master", "merge_job_id": "713.zeus-master"}
)

_PAYLOADS["mot3d-finalist-status"] = deepcopy(_PAYLOADS["mot3d-closure-status"])
_finalist_status = _PAYLOADS["mot3d-finalist-status"]
_finalist_status["campaign"]["stage"] = "finalist_selection"
_finalist_status["validation"]["expected_candidates_per_family"] = 3
_PAYLOADS["mot3d-finalist-preview"] = deepcopy(_PAYLOADS["mot3d-closure-preview"])
_finalist_preview = _PAYLOADS["mot3d-finalist-preview"]
_finalist_preview["preview_token"] = "mot3d-finalist-token"
_finalist_preview["stage"] = {"id": "finalist_selection", "label": "Finalist Selection"}
_finalist_preview["science"] = {
    "classification": "final_candidate_selection_not_unbiased_validation",
    "candidates_per_family": 3,
    "input_ensembles": 20,
    "recoil_seeds": [43001, 43002, 43003],
    "dt_s": 0.00001,
    "t_max_s": 0.1,
    "solver": "RK4StHybridCustom",
    "npools": 200,
    "bootstrap_replicates": 10000,
    "bootstrap_seed": 82001,
}
_finalist_preview["effects"].pop("submit_closure")
_finalist_preview["effects"]["submit_finalist_selection"] = True
_PAYLOADS["mot3d-finalist-confirm"] = deepcopy(_PAYLOADS["mot3d-closure-confirm"])
_finalist_confirm = _PAYLOADS["mot3d-finalist-confirm"]
_finalist_confirm["stage"] = "finalist_selection"
_finalist_confirm["chain"]["families"][0].update(
    {"array_job_id": "810[].zeus-master", "merge_job_id": "811.zeus-master"}
)
_finalist_confirm["chain"]["families"][1].update(
    {"array_job_id": "812[].zeus-master", "merge_job_id": "813.zeus-master"}
)

_PAYLOADS["mot3d-final-input-status"] = {
    "source": "zeus",
    "queried_at": "2026-01-01T00:00:00+00:00",
    "campaign": {
        "id": "mot3d-campaign",
        "name": "campaign",
        "stage": "final_validation_input_generation",
    },
    "chain": {
        "status": "eligible",
        "dependency": "afterok linear chain",
        "jobs": [
            {"id": "zeeman", "job_id": None},
            {"id": "mot_2d", "job_id": None},
            {"id": "freeze", "job_id": None},
        ],
    },
    "scheduler": {
        "expected_array_tasks": 40,
        "expected_scalar_jobs": 1,
        "completed_array_tasks": 0,
        "completed_scalar_jobs": 0,
    },
    "next_action": "review_submission",
    "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
}
_PAYLOADS["mot3d-final-input-preview"] = {
    "preview_token": "mot3d-final-input-token",
    "expires_in_seconds": 300,
    "campaign": {
        "id": "mot3d-campaign",
        "name": "campaign",
        "git_commit": "a" * 40,
    },
    "stage": {
        "id": "final_validation_input_generation",
        "label": "Final validation input generation",
    },
    "chain": {
        "dependency": "afterok linear chain",
        "steps": [
            {"id": "zeeman", "tasks": 20, "resources": {"ncpus": 200, "memory_gb": 64, "walltime": "08:00:00"}},
            {"id": "mot_2d", "tasks": 20, "resources": {"ncpus": 200, "memory_gb": 64, "walltime": "12:00:00"}},
            {"id": "freeze", "tasks": 1, "resources": {"ncpus": 1, "memory_gb": 8, "walltime": "00:30:00"}},
        ],
    },
    "science": {
        "classification": "new_unopened_inputs_after_nominal_lock",
        "zeeman_seeds": list(range(3035, 3055)),
        "mot_seeds": list(range(43035, 43055)),
        "zeeman_tasks": 20,
        "mot_tasks": 20,
        "npools": 200,
        "dependency": "afterok linear chain",
        "resources": {
            "zeeman": {"ncpus": 200, "memory_gb": 64, "walltime": "08:00:00"},
            "mot_2d": {"ncpus": 200, "memory_gb": 64, "walltime": "12:00:00"},
            "freeze": {"ncpus": 1, "memory_gb": 8, "walltime": "00:30:00"},
        },
    },
    "effects": {
        "submit_input_generation": True,
        "start_final_validation": False,
        "advance_campaign": False,
        "modify_files": False,
    },
    "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
}
_PAYLOADS["mot3d-final-input-confirm"] = {
    "status": "submitted",
    "campaign_id": "mot3d-campaign",
    "stage": "final_validation_input_generation",
    "chain": {
        "dependency": "afterok linear chain",
        "jobs": [
            {"id": "zeeman", "job_id": "901[].zeus-master"},
            {"id": "mot_2d", "job_id": "902[].zeus-master"},
            {"id": "freeze", "job_id": "903.zeus-master"},
        ],
    },
    "submitted_to_zeus": True,
    "simulation_started": True,
    "final_validation_started": False,
    "local_sync": {"status": "synchronized", "receipt_sha256": "d" * 64},
}

_PAYLOADS["mot3d-closure-transition-status"] = deepcopy(
    _PAYLOADS["mot3d-refinement-transition-status"]
)
_closure_transition_status = _PAYLOADS["mot3d-closure-transition-status"]
_closure_transition_status["campaign"]["stage"] = "closure"
_closure_transition_status["closure"] = _closure_transition_status.pop("refinement")
_PAYLOADS["mot3d-closure-transition-preview"] = deepcopy(
    _PAYLOADS["mot3d-refinement-transition-preview"]
)
_closure_transition_preview = _PAYLOADS["mot3d-closure-transition-preview"]
_closure_transition_preview["preview_token"] = "mot3d-closure-transition-token"
_closure_transition_preview["from_stage"] = "closure"
_closure_transition_preview["to_stage"] = "finalist_selection"
_closure_transition_preview["closure"] = _closure_transition_preview.pop("refinement")
_closure_transition_preview["effects"] = {
    "synchronize_closure": True,
    "prepare_finalist_selection": True,
    "submit_finalists": False,
    "start_simulation": False,
    "overwrite_existing": False,
}
_PAYLOADS["mot3d-closure-transition-confirm"] = deepcopy(
    _PAYLOADS["mot3d-refinement-transition-confirm"]
)
_closure_transition_confirm = _PAYLOADS["mot3d-closure-transition-confirm"]
_closure_transition_confirm["status"] = "finalist_selection_prepared"
_closure_transition_confirm["stage"] = "finalist_selection"

_PAYLOADS["mot3d-finalist-transition-status"] = deepcopy(
    _PAYLOADS["mot3d-closure-transition-status"]
)
_finalist_transition_status = _PAYLOADS["mot3d-finalist-transition-status"]
_finalist_transition_status["campaign"]["stage"] = "finalist_selection"
_finalist_transition_status["finalist_selection"] = _finalist_transition_status.pop(
    "closure"
)
_finalist_transition_status["validation"].update(
    {"result_artifacts": 44, "expected_result_artifacts": 44}
)
_PAYLOADS["mot3d-finalist-transition-preview"] = deepcopy(
    _PAYLOADS["mot3d-closure-transition-preview"]
)
_finalist_transition_preview = _PAYLOADS["mot3d-finalist-transition-preview"]
_finalist_transition_preview["preview_token"] = "mot3d-finalist-transition-token"
_finalist_transition_preview["from_stage"] = "finalist_selection"
_finalist_transition_preview["to_stage"] = "final_validation_input_generation"
_finalist_transition_preview["finalist_selection"] = _finalist_transition_preview.pop(
    "closure"
)
_finalist_transition_preview["finalist_selection"].update(
    {"result_artifacts": 44, "expected_result_artifacts": 44}
)
_finalist_transition_preview["artifacts"] = {
    "synchronize": {"result_files": 44, "submission_receipts": 1},
    "create": {"selection_files": 1, "job_files": 3},
    "update": ["campaign.json"],
    "transfer_files": 50,
}
_finalist_transition_preview["winner_selection"] = {
    "rule": "largest lower endpoint of the simultaneous two-sided 95% interval; ties broken by mean usable fraction",
    "winners": [
        {"family": family, "candidate_id": f"{family}_finalist_01"}
        for family in ("angled_donut", "single_pass")
    ],
    "evidence_sha256": "b" * 64,
}
_finalist_transition_preview["effects"] = {
    "synchronize_finalist_selection": True,
    "prepare_final_validation_inputs": True,
    "submit_final_validation_inputs": False,
    "start_simulation": False,
    "overwrite_existing": False,
}
_PAYLOADS["mot3d-finalist-transition-confirm"] = deepcopy(
    _PAYLOADS["mot3d-closure-transition-confirm"]
)
_finalist_transition_confirm = _PAYLOADS["mot3d-finalist-transition-confirm"]
_finalist_transition_confirm["status"] = "final_validation_input_generation_prepared"
_finalist_transition_confirm["stage"] = "final_validation_input_generation"
_finalist_transition_confirm["artifacts"].update({"synchronized": 45, "created": 4})


def fake_service_payloads() -> dict[str, object]:
    """Return fresh full public DTOs without consulting contract snapshots."""
    return deepcopy(_PAYLOADS)

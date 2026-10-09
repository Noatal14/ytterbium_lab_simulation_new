// Generated from workflow_api/specifications/mot_2d_v1.json; do not edit.
export const MOT_2D_SPECIFICATION_V1 = {
  "design": {
    "confirmation_candidates_per_s0": 5,
    "ensemble_count": 35,
    "final_dt_s": 6.25e-07,
    "prepared_file_count": 72,
    "refine_trials_per_worker": 10,
    "screen_candidates_per_s0": 3,
    "screen_trials_per_worker": 17,
    "solver": "RK4StHybridCustom",
    "workers_per_s0": 3,
    "working_dt_s": 1.25e-06
  },
  "spec_version": "mot_2d-v1",
  "stage_order": [
    "smoke",
    "screen",
    "refine",
    "confirmation",
    "sensitivity",
    "production"
  ],
  "stages": {
    "confirmation": {
      "array_throttle": 3,
      "artifacts": [
        "refined_candidates.json",
        "confirmation/tasks.json",
        "jobs/04_confirmation.pbs",
        "campaign.json"
      ],
      "cores_per_task": 200,
      "job_file": "jobs/04_confirmation.pbs",
      "label": "Confirmation",
      "memory_per_task_bytes": 68719476736,
      "walltime_seconds": 36000
    },
    "production": {
      "label": "Production"
    },
    "refine": {
      "array_throttle": 3,
      "artifacts": [
        "screening_candidates.json",
        "refine/tasks.json",
        "jobs/03_refine_round_01.pbs",
        "jobs/03_refine_round_02.pbs",
        "jobs/03_refine_round_03.pbs",
        "jobs/03_refine_round_04.pbs",
        "jobs/03_submit_refinement_chain.sh",
        "campaign.json"
      ],
      "cores_per_task": 200,
      "cumulative_trial_targets": [
        3,
        6,
        9,
        10
      ],
      "dependency": "afterok",
      "label": "Refinement",
      "memory_per_task_bytes": 68719476736,
      "round_job_files": [
        "jobs/03_refine_round_01.pbs",
        "jobs/03_refine_round_02.pbs",
        "jobs/03_refine_round_03.pbs",
        "jobs/03_refine_round_04.pbs"
      ],
      "submit_chain": "jobs/03_submit_refinement_chain.sh",
      "walltime_seconds": 72000
    },
    "screen": {
      "array_throttle": 3,
      "artifacts": [
        "screen/tasks.json",
        "jobs/02_screen.pbs",
        "campaign.json"
      ],
      "cores_per_task": 200,
      "job_file": "jobs/02_screen.pbs",
      "label": "Screening",
      "memory_per_task_bytes": 68719476736,
      "walltime_seconds": 86400
    },
    "sensitivity": {
      "label": "Sensitivity"
    },
    "smoke": {
      "array_throttle": 1,
      "artifacts": [
        "campaign.json",
        "jobs/01_smoke.pbs"
      ],
      "cores_per_task": 1,
      "job_file": "jobs/01_smoke.pbs",
      "label": "Smoke check",
      "memory_per_task_bytes": 68719476736,
      "walltime_seconds": 1200
    }
  }
} as const;

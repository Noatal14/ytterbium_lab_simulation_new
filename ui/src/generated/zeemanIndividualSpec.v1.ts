// Generated from workflow_api/specifications/zeeman_individual_v1.json; do not edit.
export const ZEEMAN_INDIVIDUAL_SPECIFICATION_V1 = {
  "fixed_classification": {
    "magnet_profile_policy": "canonical_only",
    "solver_policy": "bundled_numerical_policy",
    "suitability": "individual_only"
  },
  "particle_count": {
    "default_by_execution_mode": {
      "local": 200,
      "zeus": 50000
    },
    "maximum_by_execution_mode": {
      "local": 1000,
      "zeus": 50000
    },
    "minimum": 1
  },
  "request_fields": [
    "particle_count",
    "seed",
    "retain_particle_states",
    "execution_mode"
  ],
  "seed": {
    "default": 42,
    "maximum": 4294967295,
    "minimum": 0
  },
  "spec_version": "zeeman-individual-v1",
  "workers_by_execution_mode": {
    "local": 8,
    "zeus": 200
  }
} as const;

// Generated from workflow_api/specifications/zeeman_individual_v1.json; do not edit.
export const ZEEMAN_INDIVIDUAL_SPECIFICATION_V1 = {
  "fixed_classification": {
    "magnet_profile_policy": "canonical_only",
    "solver_policy": "bundled_numerical_policy",
    "suitability": "individual_only"
  },
  "mot_2d_controls": {
    "detuning_gamma": {
      "default": -0.9196610026631429,
      "maximum": -0.85,
      "minimum": -1.55
    },
    "magnet_radius_m": {
      "default": 0.04676406447474441,
      "maximum": 0.051,
      "minimum": 0.045
    },
    "s0": {
      "default": 1.3,
      "maximum": 3.0,
      "minimum": 0.1
    }
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
    "mot_2d_s0",
    "mot_2d_detuning_gamma",
    "mot_2d_magnet_radius_m",
    "npools",
    "retain_particle_states",
    "execution_mode"
  ],
  "seed": {
    "default": 42,
    "maximum": 4294967295,
    "minimum": 0
  },
  "spec_version": "zeeman-individual-v1",
  "worker_policy": {
    "local": {
      "default": 8,
      "maximum": 64,
      "minimum": 1
    },
    "zeus": {
      "fixed": 200
    }
  }
} as const;

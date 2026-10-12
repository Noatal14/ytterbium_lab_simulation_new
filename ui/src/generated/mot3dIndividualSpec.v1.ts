// Generated from workflow_api/specifications/mot_3d_individual_v1.json; do not edit.
export const MOT_3D_INDIVIDUAL_SPECIFICATION_V1 = {
  "authority_references": {
    "laboratory_specification": {
      "sha256": "1ef77eecdd306d2d92c08fde9897f283de57e741e9f1a45a6bc6c0063779eac3",
      "version": "laboratory-physical-v2"
    },
    "numerical_policy": {
      "sha256": "08a6ad18017ff9a649e46dc94595be24922b3838ffd7c183cdf1a9c9c097cef1",
      "version": "numerical-policy-v1"
    }
  },
  "common_controls": {
    "blue_s0": {
      "maximum": 1.5,
      "minimum": 0.05
    },
    "blue_waist_m": {
      "maximum": 0.02,
      "minimum": 0.002
    },
    "green_detuning_gamma": {
      "maximum": -5.0,
      "minimum": -35.0
    },
    "green_s0": {
      "maximum": 150.0,
      "minimum": 0.5
    },
    "green_waist_m": {
      "maximum": 0.02,
      "minimum": 0.002
    },
    "magnetic_gradient_G_cm": {
      "maximum": 100.0,
      "minimum": 0.5
    }
  },
  "defaults": {
    "angled_donut": {
      "blue_detuning_gamma": -3.0,
      "blue_s0": 1.5,
      "blue_waist_m": 0.0075,
      "core_shell_split_radius_m": 0.0025,
      "green_detuning_gamma": -25.0,
      "green_s0": 30.0,
      "green_waist_m": 0.0075,
      "magnetic_gradient_G_cm": 2.5
    },
    "single_pass": {
      "blue_crossing_angle_deg": 45.0,
      "blue_crossing_z_offset_m": -0.05,
      "blue_detuning_anchor_gamma": -2.034161875,
      "blue_s0": 0.75,
      "blue_waist_m": 0.01,
      "green_detuning_gamma": -25.0,
      "green_s0": 30.0,
      "green_waist_m": 0.01,
      "magnetic_gradient_G_cm": 2.5
    }
  },
  "family_controls": {
    "angled_donut": {
      "blue_detuning_gamma": {
        "maximum": -0.5,
        "minimum": -6.0
      },
      "core_shell_split_radius_m": {
        "maximum": 0.0049,
        "minimum": 0.0005
      }
    },
    "single_pass": {
      "blue_crossing_angle_deg": {
        "maximum": 70.0,
        "minimum": 45.0
      },
      "blue_crossing_z_offset_m": {
        "maximum": -0.04,
        "minimum": -0.05
      },
      "blue_detuning_anchor_gamma": {
        "maximum": -1.75,
        "minimum": -3.75
      }
    }
  },
  "fixed_classification": {
    "capture": {
      "capture_radius_m": 0.005,
      "maximum_final_speed_m_s": 1.0,
      "minimum_residence_time_s": 0.005
    },
    "convergence_claim": "not_established",
    "donut_shared_aperture_radius_m": 0.005,
    "gravity_enabled": true,
    "green_full_angle_deg": 62.0,
    "single_pass_blue_aperture_radius_m": 0.0075,
    "single_pass_green_aperture_radius_m": 0.005,
    "solver": "RK4StHybridCustom",
    "suitability": "individual_only",
    "t_max_s": 0.1,
    "timestep_s": 1e-05
  },
  "geometry_families": [
    "angled_donut",
    "single_pass"
  ],
  "particle_count": {
    "default": 200,
    "maximum_by_execution_mode": {
      "local": 1000,
      "zeus": 50000
    },
    "minimum": 1
  },
  "request_fields": [
    "source_id",
    "geometry_family",
    "particle_count",
    "selection_seed",
    "simulation_seed",
    "parameters",
    "retain_particle_states",
    "execution_mode"
  ],
  "sampling": {
    "algorithm": "pcg64-raw-partial-fisher-yates-unbiased",
    "canonical_order": "constituent-record-order-then-row-index",
    "version": "v1"
  },
  "selection_seed": {
    "default": 42,
    "maximum": 4294967295,
    "minimum": 0
  },
  "simulation_seed": {
    "default": 42,
    "maximum": 4294967295,
    "minimum": 0
  },
  "spec_version": "mot-3d-individual-v1",
  "workers_by_execution_mode": {
    "local": 8,
    "zeus": 200
  }
} as const;

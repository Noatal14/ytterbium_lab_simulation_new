// Generated from lab_setup/specifications/mot_3d_timestep_policy_v1.json; do not edit.
export const MOT_3D_TIMESTEP_POLICY_V1 = {
  "convergence_claim": "not_established",
  "decision": {
    "legacy_campaign_mutation_forbidden": true,
    "rationale": "Use the larger tested timestep for search and optimization to reduce runtime while retaining the smaller timestep for sealed final validation.",
    "requires_new_campaign": true
  },
  "inconclusive_evidence": {
    "archive_path": "docs/evidence/mot_3d_timestep_20261010_inconclusive.json",
    "artifact_availability": "reported_on_zeus_not_imported",
    "campaign_name": "mot_3d_s0_1p3_20261010_v1",
    "evidence_sha256": "3426f50916a14fe02beccf203119ab8310ac581bc91af21b968aab158045fbac",
    "raw_result_registry_sha256": null,
    "status": "inconclusive_degenerate_sentinel",
    "study_date": "2026-10-10",
    "tasks_sha256": null
  },
  "sealed_final_validation_dt_s": 6.25e-07,
  "search_dt_s": 1e-05,
  "solver": "RK4StHybridCustom",
  "spec_version": "mot-3d-timestep-policy-v1",
  "status": "pragmatic_user_approved_after_inconclusive_study"
} as const;

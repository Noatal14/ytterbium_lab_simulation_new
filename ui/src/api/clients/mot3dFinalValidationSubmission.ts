import {
  isKnownServerError,
  requiresManualVerification,
} from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { MOT_3D_TIMESTEP_POLICY_V1 } from "../../generated/mot3dTimestepPolicy.v1";
import { creationApi } from "./campaign";
import {
  parseMot3DClosureSubmissionStatus,
  parseMot3DClosureSubmissionPreview,
  parseMot3DClosureSubmissionResult,
} from "./mot3dClosureSubmission";

type Profile = ZeusSnapshot["profile"];
const domain = "mot_3d_final_validation_submission" as const;
const object = (v: unknown, keys: string[]) => {
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    !exactKeys(v as Record<string, unknown>, keys)
  )
    throw new Error("Invalid Final Validation response.");
  return v as Record<string, unknown>;
};
const clone = (v: unknown) => structuredClone(v) as Record<string, unknown>;
export class Mot3DFinalValidationSubmissionApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
const adapt = (e: { code: string; message: string }) =>
  new Mot3DFinalValidationSubmissionApiError(
    isKnownServerError(domain, e.code)
      ? e.code
      : "mot_3d_final_validation_submission_failed",
    isKnownServerError(domain, e.code)
      ? e.message
      : "Final Validation submission stopped safely.",
  );
export const finalValidationConfirmIsUncertain = (e: unknown) =>
  e instanceof Mot3DFinalValidationSubmissionApiError &&
  (requiresManualVerification(domain, e.code) ||
    [
      "final_validation_partial_submission",
      "final_validation_submission_outcome_unknown",
      "final_validation_already_started",
    ].includes(e.code));

export function parseMot3DFinalValidationSubmissionStatus(value: unknown) {
  const original = clone(value),
    normalized = clone(value);
  object(original, [
    "source",
    "queried_at",
    "campaign",
    "submission",
    "scheduler",
    "validation",
    "next_action",
    "local_sync",
  ]);
  const campaign = object(original.campaign, ["id", "name", "stage"]),
    validation = object(original.validation, [
      "status",
      "expected_candidates_per_family",
      "expected_recoil_seeds_per_candidate",
    ]);
  if (
    campaign.stage !== "final_validation" ||
    validation.expected_candidates_per_family !== 1 ||
    validation.expected_recoil_seeds_per_candidate !== 3
  )
    throw new Error("Invalid Final Validation status.");
  (normalized.campaign as any).stage = "closure";
  (normalized.validation as any).expected_candidates_per_family = 16;
  parseMot3DClosureSubmissionStatus(normalized);
  return original as Omit<
    ReturnType<typeof parseMot3DClosureSubmissionStatus>,
    "campaign" | "validation"
  > & {
    campaign: { id: string; name: string; stage: "final_validation" };
    validation: {
      status: "not_started";
      expected_candidates_per_family: 1;
      expected_recoil_seeds_per_candidate: 3;
    };
  };
}
export function parseMot3DFinalValidationSubmissionPreview(
  value: unknown,
  expected: { campaignId: string; profile: Profile },
) {
  const original = clone(value),
    normalized = clone(value);
  object(original, [
    "preview_token",
    "expires_in_seconds",
    "campaign",
    "stage",
    "chain",
    "resources",
    "science",
    "remote",
    "effects",
    "local_sync",
  ]);
  const stage = object(original.stage, ["id", "label"]),
    science = object(original.science, [
      "classification",
      "candidates_per_family",
      "input_ensembles",
      "recoil_seeds",
      "dt_s",
      "t_max_s",
      "solver",
      "npools",
      "bootstrap_replicates",
      "bootstrap_seed",
    ]),
    effects = object(original.effects, [
      "start_simulation",
      "submit_later_stages",
      "modify_campaign_files",
      "record_submission_receipt",
      "submit_final_validation",
    ]),
    resources = object(original.resources, ["array", "merge"]),
    merge = object(resources.merge, ["ncpus", "memory_gb", "walltime"]);
  if (
    stage.id !== "final_validation" ||
    stage.label !== "Final Validation" ||
    science.classification !== "sealed_unbiased_final_validation" ||
    science.candidates_per_family !== 1 ||
    science.input_ensembles !== 20 ||
    JSON.stringify(science.recoil_seeds) !==
      JSON.stringify([44001, 44002, 44003]) ||
    science.dt_s !== MOT_3D_TIMESTEP_POLICY_V1.sealed_final_validation_dt_s ||
    science.t_max_s !== 0.1 ||
    science.solver !== MOT_3D_TIMESTEP_POLICY_V1.solver ||
    science.npools !== 200 ||
    science.bootstrap_replicates !== 20000 ||
    science.bootstrap_seed !== 92001 ||
    merge.ncpus !== 1 ||
    merge.memory_gb !== 8 ||
    merge.walltime !== "02:00:00" ||
    effects.start_simulation !== true ||
    effects.submit_later_stages !== false ||
    effects.modify_campaign_files !== false ||
    effects.record_submission_receipt !== true ||
    effects.submit_final_validation !== true
  )
    throw new Error("Invalid Final Validation review.");
  normalized.stage = { id: "closure", label: "Closure" };
  normalized.science = {
    classification: "candidate_selection_not_final_validation",
    candidates_per_family: 16,
    input_ensembles: 4,
    particles_per_ensemble: 750,
    total_particles: 3000,
    recoil_seeds: [42001, 42002, 42003],
    dt_s: MOT_3D_TIMESTEP_POLICY_V1.search_dt_s,
    t_max_s: 0.1,
    solver: science.solver,
    selection_seed: 71001,
    bootstrap_replicates: 10000,
    bootstrap_seed: 72001,
  };
  normalized.effects = {
    start_simulation: true,
    submit_later_stages: false,
    modify_campaign_files: false,
    record_submission_receipt: true,
    submit_closure: true,
  };
  (normalized.resources as any).merge = {
    ncpus: 1,
    memory_gb: 4,
    walltime: "01:00:00",
  };
  parseMot3DClosureSubmissionPreview(normalized, expected);
  return original as any;
}
export function parseMot3DFinalValidationSubmissionResult(
  value: unknown,
  campaignId: string,
) {
  const original = clone(value),
    normalized = clone(value);
  object(original, [
    "status",
    "campaign_id",
    "stage",
    "chain",
    "submitted_at",
    "local_sync",
  ]);
  if (original.stage !== "final_validation")
    throw new Error("Invalid Final Validation result.");
  normalized.stage = "closure";
  parseMot3DClosureSubmissionResult(normalized, campaignId);
  return original as any;
}
export type Mot3DFinalValidationSubmissionStatus = ReturnType<
  typeof parseMot3DFinalValidationSubmissionStatus
>;
export type Mot3DFinalValidationSubmissionPreview = ReturnType<
  typeof parseMot3DFinalValidationSubmissionPreview
>;
export type Mot3DFinalValidationSubmissionResult = ReturnType<
  typeof parseMot3DFinalValidationSubmissionResult
>;
export function createMot3DFinalValidationSubmissionApi(
  session: () => Promise<string>,
) {
  let generation = 0;
  const contexts = new Map<
    string,
    { campaignId: string; csrf: string; generation: number; profile: Profile }
  >();
  const body = (campaign_id: string, p: Profile) => ({
    campaign_id,
    username: p.username,
    project_directory: p.project_directory,
  });
  return {
    async status(id: string, p: Profile) {
      const g = generation,
        r = parseMot3DFinalValidationSubmissionStatus(
          await postData(
            "/api/v1/zeus/submissions/mot-3d-final-validation/status",
            body(id, p),
            await session(),
            adapt,
          ),
        );
      if (g !== generation || r.campaign.id !== id)
        throw new Error("Final Validation status is stale.");
      return r;
    },
    async preview(id: string, p: Profile) {
      const g = generation,
        csrf = await session(),
        r = parseMot3DFinalValidationSubmissionPreview(
          await postData(
            "/api/v1/zeus/submissions/mot-3d-final-validation/preview",
            body(id, p),
            csrf,
            adapt,
          ),
          { campaignId: id, profile: p },
        );
      if (g !== generation)
        throw new Error("Final Validation review is stale.");
      contexts.set(r.preview_token, {
        campaignId: id,
        csrf,
        generation: g,
        profile: p,
      });
      return r;
    },
    async confirm(token: string) {
      const c = contexts.get(token);
      if (!c)
        throw new Error("The Final Validation review is no longer active.");
      contexts.delete(token);
      try {
        const r = parseMot3DFinalValidationSubmissionResult(
          await postData(
            "/api/v1/zeus/submissions/mot-3d-final-validation/confirm",
            { preview_token: token },
            c.csrf,
            adapt,
          ),
          c.campaignId,
        );
        if (c.generation !== generation) throw new Error("stale");
        return r;
      } catch (e) {
        if (e instanceof Mot3DFinalValidationSubmissionApiError) throw e;
        throw new Mot3DFinalValidationSubmissionApiError(
          "final_validation_submission_outcome_unknown",
          "The submission outcome could not be verified. Do not submit again; inspect Zeus first.",
        );
      }
    },
    reset() {
      generation++;
      contexts.clear();
    },
  };
}
export type Mot3DFinalValidationSubmissionApi = ReturnType<
  typeof createMot3DFinalValidationSubmissionApi
>;
export const mot3DFinalValidationSubmissionApi =
  createMot3DFinalValidationSubmissionApi(() => creationApi.session());

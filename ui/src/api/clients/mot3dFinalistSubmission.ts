import { isKnownServerError, requiresManualVerification } from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { MOT_3D_TIMESTEP_POLICY_V2 } from "../../generated/mot3dTimestepPolicy.v2";
import { creationApi } from "./campaign";
import { parseMot3DClosureSubmissionPreview, parseMot3DClosureSubmissionResult, parseMot3DClosureSubmissionStatus } from "./mot3dClosureSubmission";

type Profile = ZeusSnapshot["profile"];
const domain = "mot_3d_finalist_submission" as const;
const record = (value: unknown, keys: string[], message: string) => { if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message); return value as Record<string, unknown>; };
const clone = (value: unknown) => structuredClone(value) as Record<string, unknown>;
export class Mot3DFinalistSubmissionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
const adaptError = (error: { code: string; message: string }) => new Mot3DFinalistSubmissionApiError(isKnownServerError(domain, error.code) ? error.code : "mot_3d_finalist_submission_failed", isKnownServerError(domain, error.code) ? error.message : "Finalist Selection submission stopped safely.");
export const finalistConfirmIsUncertain = (cause: unknown) => cause instanceof Mot3DFinalistSubmissionApiError && (requiresManualVerification(domain, cause.code) || ["finalist_selection_partial_submission", "finalist_selection_submission_outcome_unknown", "finalist_selection_already_started"].includes(cause.code));

export function parseMot3DFinalistSubmissionStatus(value: unknown) {
  const original = clone(value), normalized = clone(value);
  record(original, ["source", "queried_at", "campaign", "submission", "scheduler", "validation", "next_action", "local_sync"], "Invalid Finalist Selection status.");
  const campaign = record(original.campaign, ["id", "name", "stage"], "Invalid Finalist Selection status.");
  const validation = record(original.validation, ["status", "expected_candidates_per_family", "expected_recoil_seeds_per_candidate"], "Invalid Finalist Selection status.");
  if (campaign.stage !== "finalist_selection" || validation.expected_candidates_per_family !== 3 || validation.expected_recoil_seeds_per_candidate !== 3) throw new Error("Invalid Finalist Selection status.");
  (normalized.campaign as Record<string, unknown>).stage = "closure";
  (normalized.validation as Record<string, unknown>).expected_candidates_per_family = 16;
  parseMot3DClosureSubmissionStatus(normalized);
  return original as Omit<ReturnType<typeof parseMot3DClosureSubmissionStatus>, "campaign" | "validation"> & { campaign: { id: string; name: string; stage: "finalist_selection" }; validation: { status: "not_started"; expected_candidates_per_family: 3; expected_recoil_seeds_per_candidate: 3 } };
}

export function parseMot3DFinalistSubmissionPreview(value: unknown, expected: { campaignId: string; profile: Profile }) {
  const original = clone(value), normalized = clone(value);
  record(original, ["preview_token", "expires_in_seconds", "campaign", "stage", "chain", "resources", "science", "remote", "effects", "local_sync"], "Invalid Finalist Selection review.");
  const stage = record(original.stage, ["id", "label"], "Invalid Finalist Selection review.");
  const science = record(original.science, ["classification", "candidates_per_family", "input_ensembles", "recoil_seeds", "dt_s", "t_max_s", "solver", "npools", "bootstrap_replicates", "bootstrap_seed"], "Invalid Finalist Selection review.");
  const effects = record(original.effects, ["start_simulation", "submit_later_stages", "modify_campaign_files", "record_submission_receipt", "submit_finalist_selection"], "Invalid Finalist Selection review.");
  if (stage.id !== "finalist_selection" || stage.label !== "Finalist Selection" || science.classification !== "final_candidate_selection_not_unbiased_validation" || science.candidates_per_family !== 3 || science.input_ensembles !== 20 || JSON.stringify(science.recoil_seeds) !== JSON.stringify([43001, 43002, 43003]) || science.dt_s !== MOT_3D_TIMESTEP_POLICY_V2.search_dt_s || science.t_max_s !== MOT_3D_TIMESTEP_POLICY_V2.t_max_s || science.solver !== MOT_3D_TIMESTEP_POLICY_V2.solver || science.npools !== 200 || science.bootstrap_replicates !== 10000 || science.bootstrap_seed !== 82001 || effects.start_simulation !== true || effects.submit_later_stages !== false || effects.modify_campaign_files !== false || effects.record_submission_receipt !== true || effects.submit_finalist_selection !== true) throw new Error("Invalid Finalist Selection review.");
  normalized.stage = { id: "closure", label: "Closure" };
  normalized.science = { classification: "candidate_selection_not_final_validation", candidates_per_family: 16, input_ensembles: 4, particles_per_ensemble: 750, total_particles: 3000, recoil_seeds: [42001, 42002, 42003], dt_s: science.dt_s, t_max_s: science.t_max_s, solver: science.solver, selection_seed: 71001, bootstrap_replicates: science.bootstrap_replicates, bootstrap_seed: 72001 };
  normalized.effects = { start_simulation: true, submit_later_stages: false, modify_campaign_files: false, record_submission_receipt: true, submit_closure: true };
  parseMot3DClosureSubmissionPreview(normalized, expected);
  return original as { preview_token: string; expires_in_seconds: 300; campaign: { id: string; name: string; git_commit: string }; stage: { id: "finalist_selection"; label: "Finalist Selection" }; chain: ReturnType<typeof parseMot3DClosureSubmissionPreview>["chain"]; resources: ReturnType<typeof parseMot3DClosureSubmissionPreview>["resources"]; science: { classification: "final_candidate_selection_not_unbiased_validation"; candidates_per_family: 3; input_ensembles: 20; recoil_seeds: [43001,43002,43003]; dt_s: number; t_max_s: 0.05; solver: string; npools: 200; bootstrap_replicates: 10000; bootstrap_seed: 82001 }; remote: ReturnType<typeof parseMot3DClosureSubmissionPreview>["remote"]; effects: { start_simulation: true; submit_later_stages: false; modify_campaign_files: false; record_submission_receipt: true; submit_finalist_selection: true }; local_sync: ReturnType<typeof parseMot3DClosureSubmissionPreview>["local_sync"] };
}

export function parseMot3DFinalistSubmissionResult(value: unknown, campaignId: string) {
  const original = clone(value), normalized = clone(value);
  record(original, ["status", "campaign_id", "stage", "chain", "submitted_at", "local_sync"], "Invalid Finalist Selection result.");
  if (original.stage !== "finalist_selection") throw new Error("Invalid Finalist Selection result.");
  normalized.stage = "closure";
  parseMot3DClosureSubmissionResult(normalized, campaignId);
  return original as Omit<ReturnType<typeof parseMot3DClosureSubmissionResult>, "stage"> & { stage: "finalist_selection" };
}
export type Mot3DFinalistSubmissionStatus = ReturnType<typeof parseMot3DFinalistSubmissionStatus>;
export type Mot3DFinalistSubmissionPreview = ReturnType<typeof parseMot3DFinalistSubmissionPreview>;
export type Mot3DFinalistSubmissionResult = ReturnType<typeof parseMot3DFinalistSubmissionResult>;

export function createMot3DFinalistSubmissionApi(session: () => Promise<string>) {
  let generation = 0; const contexts = new Map<string, { campaignId: string; csrf: string; generation: number; profile: Profile }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(campaignId: string, profile: Profile) { const active = generation, parsed = parseMot3DFinalistSubmissionStatus(await postData("/api/v1/zeus/submissions/mot-3d-finalist-selection/status", body(campaignId, profile), await session(), adaptError)); if (active !== generation || parsed.campaign.id !== campaignId) throw new Error("Finalist Selection status is stale or mismatched."); return parsed; },
    async preview(campaignId: string, profile: Profile) { const active = generation, csrf = await session(), parsed = parseMot3DFinalistSubmissionPreview(await postData("/api/v1/zeus/submissions/mot-3d-finalist-selection/preview", body(campaignId, profile), csrf, adaptError), { campaignId, profile }); if (active !== generation) throw new Error("Finalist Selection review is stale."); contexts.set(parsed.preview_token, { campaignId, csrf, generation: active, profile }); return parsed; },
    async confirm(preview_token: string) { const context = contexts.get(preview_token); if (!context) throw new Error("The Finalist Selection review is no longer active."); contexts.delete(preview_token); try { const parsed = parseMot3DFinalistSubmissionResult(await postData("/api/v1/zeus/submissions/mot-3d-finalist-selection/confirm", { preview_token }, context.csrf, adaptError), context.campaignId); if (context.generation !== generation) throw new Error("stale"); return parsed; } catch (cause) { if (cause instanceof Mot3DFinalistSubmissionApiError) throw cause; throw new Mot3DFinalistSubmissionApiError("finalist_selection_submission_outcome_unknown", "The submission outcome could not be verified. Do not submit again; inspect Zeus first."); } },
    reset() { generation += 1; contexts.clear(); },
  };
}
export type Mot3DFinalistSubmissionApi = ReturnType<typeof createMot3DFinalistSubmissionApi>;
export const mot3DFinalistSubmissionApi = createMot3DFinalistSubmissionApi(() => creationApi.session());

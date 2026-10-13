import { isKnownServerError, requiresManualVerification } from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
import {
  parseMot3DRefinementTransitionPreview,
  parseMot3DRefinementTransitionResult,
  parseMot3DRefinementTransitionStatus,
} from "./mot3dRefinementTransition";

type Profile = ZeusSnapshot["profile"];
export type Mot3DClosureTransitionLifecycle =
  | "not_submitted" | "submitted" | "queued" | "running" | "held"
  | "completed_failed" | "status_unknown" | "partial" | "outcome_unknown"
  | "completed_success_unvalidated" | "ready_to_advance" | "finalist_selection_prepared";
export type Mot3DClosureTransitionStatus = ReturnType<typeof parseMot3DClosureTransitionStatus>;
export type Mot3DClosureTransitionPreview = ReturnType<typeof parseMot3DClosureTransitionPreview>;
export type Mot3DClosureTransitionResult = ReturnType<typeof parseMot3DClosureTransitionResult>;

export class Mot3DClosureTransitionApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
const domain = "mot_3d_closure_transition" as const;
const adaptError = (error: { code: string; message: string }) =>
  new Mot3DClosureTransitionApiError(
    isKnownServerError(domain, error.code) ? error.code : "mot_3d_closure_transition_failed",
    isKnownServerError(domain, error.code) ? error.message : "Closure result verification stopped safely.",
  );
export const closureTransitionIsUncertain = (cause: unknown) =>
  cause instanceof Mot3DClosureTransitionApiError && (
    requiresManualVerification(domain, cause.code) ||
    ["closure_transition_outcome_unknown", "transition_outcome_unknown", "local_sync_outcome_unknown"].includes(cause.code)
  );

const clone = (value: unknown) => structuredClone(value) as Record<string, unknown>;
const exactObject = (value: unknown, keys: string[], message: string) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message);
  return value as Record<string, unknown>;
};
export function parseMot3DClosureTransitionStatus(value: unknown) {
  const original = clone(value), normalized = clone(value);
  exactObject(original, ["source", "queried_at", "campaign", "closure", "scheduler", "validation", "transition", "next_action", "local_sync"], "Invalid Closure transition status.");
  const originalCampaign = exactObject(original.campaign, ["id", "name", "stage"], "Invalid Closure transition status.");
  const originalClosure = exactObject(original.closure, ["status", "chain"], "Invalid Closure transition status.");
  const originalTransition = exactObject(original.transition, ["status"], "Invalid Closure transition status.");
  if (!["closure", "finalist_selection"].includes(String(originalCampaign.stage)) || (originalCampaign.stage === "finalist_selection" && originalClosure.status !== "finalist_selection_prepared") || !["not_prepared", "finalist_selection_prepared"].includes(String(originalTransition.status))) throw new Error("Invalid Closure transition status.");
  normalized.refinement = normalized.closure;
  delete normalized.closure;
  const campaign = normalized.campaign as Record<string, unknown>;
  campaign.stage = campaign.stage === "finalist_selection" ? "closure" : "refinement";
  const refinement = normalized.refinement as Record<string, unknown>;
  if (refinement.status === "finalist_selection_prepared") refinement.status = "closure_prepared";
  const transition = normalized.transition as Record<string, unknown>;
  if (transition.status === "finalist_selection_prepared") transition.status = "closure_prepared";
  if (normalized.next_action === "open_finalist_selection") normalized.next_action = "open_closure";
  parseMot3DRefinementTransitionStatus(normalized);
  return original as {
    source: "zeus"; queried_at: string; campaign: { id: string; name: string; stage: "closure" | "finalist_selection" };
    closure: { status: Mot3DClosureTransitionLifecycle; chain: ReturnType<typeof parseMot3DRefinementTransitionStatus>["refinement"]["chain"] };
    scheduler: ReturnType<typeof parseMot3DRefinementTransitionStatus>["scheduler"];
    validation: ReturnType<typeof parseMot3DRefinementTransitionStatus>["validation"];
    transition: { status: "not_prepared" | "finalist_selection_prepared" };
    next_action: "wait" | "review_transition" | "synchronize_results" | "open_finalist_selection" | "inspect_zeus";
    local_sync: ReturnType<typeof parseMot3DRefinementTransitionStatus>["local_sync"];
  };
}
export function parseMot3DClosureTransitionPreview(value: unknown, campaignId: string) {
  const original = clone(value), normalized = clone(value);
  exactObject(original, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "closure", "artifacts", "effects"], "Invalid Closure transition review.");
  exactObject(original.closure, ["result_artifacts", "expected_result_artifacts", "families", "evidence_sha256"], "Invalid Closure transition review.");
  exactObject(original.effects, ["synchronize_closure", "prepare_finalist_selection", "submit_finalists", "start_simulation", "overwrite_existing"], "Invalid Closure transition review.");
  if (original.from_stage !== "closure" || original.to_stage !== "finalist_selection") throw new Error("Invalid Closure transition review.");
  normalized.refinement = normalized.closure;
  delete normalized.closure;
  normalized.from_stage = "refinement";
  normalized.to_stage = "closure";
  const effects = normalized.effects as Record<string, unknown>;
  normalized.effects = {
    synchronize_refinement: effects.synchronize_closure,
    prepare_closure: effects.prepare_finalist_selection,
    submit_closure: effects.submit_finalists,
    start_simulation: effects.start_simulation,
    overwrite_existing: effects.overwrite_existing,
  };
  parseMot3DRefinementTransitionPreview(normalized, campaignId);
  return original as {
    preview_token: string; expires_in_seconds: 300; campaign: { id: string; name: string; git_commit: string };
    from_stage: "closure"; to_stage: "finalist_selection";
    closure: { result_artifacts: 200; expected_result_artifacts: 200; families: ["angled_donut", "single_pass"]; evidence_sha256: string };
    artifacts: { synchronize: { result_files: 200; submission_receipts: 1 }; create: { selection_files: 2; job_files: 4 }; update: ["campaign.json"]; transfer_files: 208 };
    effects: { synchronize_closure: true; prepare_finalist_selection: true; submit_finalists: false; start_simulation: false; overwrite_existing: false };
  };
}
export function parseMot3DClosureTransitionResult(value: unknown, campaignId: string) {
  const original = clone(value), normalized = clone(value);
  exactObject(original, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"], "Invalid Closure transition result.");
  if (original.status !== "finalist_selection_prepared" || original.stage !== "finalist_selection") throw new Error("Invalid Closure transition result.");
  normalized.status = "closure_prepared";
  normalized.stage = "closure";
  parseMot3DRefinementTransitionResult(normalized, campaignId);
  return original as { status: "finalist_selection_prepared"; campaign_id: string; stage: "finalist_selection"; artifacts: { synchronized: 201; created: 6; updated: 1; bundle_sha256: string }; submitted_to_zeus: false; simulation_started: false; local_sync: { status: "synchronized"; receipt_sha256: string } };
}

export function createMot3DClosureTransitionApi(session: () => Promise<string>) {
  let generation = 0;
  const contexts = new Map<string, { campaignId: string; csrf: string; generation: number }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(campaignId: string, profile: Profile) { const active = generation; const value = parseMot3DClosureTransitionStatus(await postData("/api/v1/zeus/mot-3d/closure-transition/status", body(campaignId, profile), await session(), adaptError)); if (active !== generation || value.campaign.id !== campaignId) throw new Error("The Closure transition status is stale or mismatched."); return value; },
    async preview(campaignId: string, profile: Profile) { const active = generation, csrf = await session(); const value = parseMot3DClosureTransitionPreview(await postData("/api/v1/zeus/mot-3d/closure-transition/preview", body(campaignId, profile), csrf, adaptError), campaignId); if (active !== generation) throw new Error("The Closure transition review is stale."); contexts.set(value.preview_token, { campaignId, csrf, generation: active }); return value; },
    async confirm(preview_token: string) { const context = contexts.get(preview_token); if (!context) throw new Error("The Closure transition review is no longer active."); contexts.delete(preview_token); try { const value = parseMot3DClosureTransitionResult(await postData("/api/v1/zeus/mot-3d/closure-transition/confirm", { preview_token }, context.csrf, adaptError), context.campaignId); if (context.generation !== generation) throw new Error("stale"); return value; } catch (cause) { if (cause instanceof Mot3DClosureTransitionApiError) throw cause; throw new Mot3DClosureTransitionApiError("closure_transition_outcome_unknown", "The Closure transition outcome could not be verified. Do not retry; inspect the campaign and Zeus first."); } },
    reset() { generation += 1; contexts.clear(); },
  };
}
export type Mot3DClosureTransitionApi = ReturnType<typeof createMot3DClosureTransitionApi>;
export const mot3DClosureTransitionApi = createMot3DClosureTransitionApi(() => creationApi.session());

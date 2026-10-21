import { adaptConfirmationError, confirmationRequiresManualVerification } from "../errorSemantics";
import { reviewedCampaignStageArray, type Campaign3DResourceStage, reviewedCampaignResource, campaignParticles, campaignTotalParticles } from "../campaignPolicy";
import { MOT_3D_TIMESTEP_POLICY_V2 } from "../../generated/mot3dTimestepPolicy.v2";
import { postData } from "../http/envelope";
import { boundedPrintable, exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
import {
  isMot3DFamilyCanonicalPrefix,
  mot3DFamilyJobCount,
  parseMot3DFamilyChain,
  type Mot3DFamilyChain,
} from "./mot3dFamilyChain";

type Profile = ZeusSnapshot["profile"];
export class Mot3DClosureSubmissionApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
export const closureConfirmIsUncertain = (cause: unknown) =>
  cause instanceof Mot3DClosureSubmissionApiError && (confirmationRequiresManualVerification("mot_3d_closure_submission", cause.code) || [
    "closure_submission_outcome_unknown",
    "closure_partial_submission",
    "closure_already_started",
  ].includes(cause.code));
const closureErrorCodes = new Set([
  "request_invalid", "profile_invalid", "campaign_not_found", "closure_preparation_invalid",
  "closure_already_started", "closure_partial_submission", "closure_submission_outcome_unknown",
  "remote_checkout_mismatch", "remote_response_invalid", "local_files_changed",
  "too_many_pending_previews", "confirmation_invalid", "confirmation_expired",
  "zeus_authentication_required", "zeus_host_key_untrusted", "zeus_timeout", "zeus_unreachable",
  "mot_3d_closure_submission_failed", "mot_3d_closure_submission_unavailable",
]);
const closureApiError = (error: { code: string; message: string }) => {
  if (!closureErrorCodes.has(error.code)) return new Mot3DClosureSubmissionApiError("mot_3d_closure_submission_failed", "3D Closure submission could not be verified.");
  return new Mot3DClosureSubmissionApiError(error.code, error.message);
};
type Lifecycle = "not_submitted" | "submitted" | "queued" | "running" | "held" | "completed_failed" | "completed_success_unvalidated" | "status_unknown" | "outcome_unknown" | "partial";
export type Mot3DClosureSubmissionStatus = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: "closure" };
  submission: { status: Lifecycle; chain: Mot3DFamilyChain };
  scheduler: { expected_array_tasks: 6; expected_merge_jobs: 2; completed_array_tasks: number; completed_merge_jobs: number };
  validation: { status: "not_started"; expected_candidates_per_family: 16; expected_recoil_seeds_per_candidate: 3 };
  next_action: "review_submission" | "wait" | "inspect_zeus" | "await_result_synchronization";
  local_sync: { status: "synchronized"; receipt_sha256: string };
};
export type Mot3DClosureSubmissionPreview = {
  preview_token: string;
  expires_in_seconds: 300;
  campaign: { id: string; name: string; git_commit: string };
  stage: { id: "closure"; label: "Closure" };
  chain: { families: [{ id: "angled_donut"; array_tasks: 3; merge_jobs: 1 }, { id: "single_pass"; array_tasks: 3; merge_jobs: 1 }]; qsub_calls: 4; dependency: "afterok within each family" };
  resources: { array: { ncpus_per_task: number; memory_gb_per_task: number; walltime: string; array_throttle?: number; vnode?: string }; merge: { ncpus: 1; memory_gb: 4; walltime: "01:00:00" } };
  science: { classification: "candidate_selection_not_final_validation"; candidates_per_family: 16; input_ensembles: 4; particles_per_ensemble: number; total_particles: number; recoil_seeds: [42001, 42002, 42003]; dt_s: number; t_max_s: 0.05; solver: string; selection_seed: 71001; bootstrap_replicates: 10000; bootstrap_seed: 72001 };
  remote: { host: "zeus.technion.ac.il"; project_directory: string; commit: string; branch: string; dirty: false };
  effects: { start_simulation: true; submit_later_stages: false; modify_campaign_files: false; record_submission_receipt: true; submit_closure: true };
  local_sync: { status: "synchronized"; receipt_sha256: string };
};
export type Mot3DClosureSubmissionResult = { status: "submitted"; campaign_id: string; stage: "closure"; chain: Mot3DFamilyChain; submitted_at: string; local_sync: { status: "synchronized"; receipt_sha256: string } };

const sha40 = /^[0-9a-f]{40}$/;
const sha256 = /^[0-9a-f]{64}$/;
const object = (value: unknown, keys: string[], message: string) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message);
  return value as Record<string, unknown>;
};
const text = (value: unknown, limit = 256): value is string => boundedPrintable(value, limit) && value.length > 0;
const count = (value: unknown, maximum: number) => Number.isInteger(value) && Number(value) >= 0 && Number(value) <= maximum;
const sync = (value: unknown) => {
  const row = object(value, ["status", "receipt_sha256"], "Invalid Closure synchronization evidence.");
  if (row.status !== "synchronized" || typeof row.receipt_sha256 !== "string" || !sha256.test(row.receipt_sha256)) throw new Error("Invalid Closure synchronization evidence.");
  return row as Mot3DClosureSubmissionStatus["local_sync"];
};

export function parseMot3DClosureSubmissionStatus(value: unknown): Mot3DClosureSubmissionStatus {
  const row = object(value, ["source", "queried_at", "campaign", "submission", "scheduler", "validation", "next_action", "local_sync"], "Invalid Closure submission status.");
  const campaign = object(row.campaign, ["id", "name", "stage"], "Invalid Closure submission status.");
  const submission = object(row.submission, ["status", "chain"], "Invalid Closure submission status.");
  const scheduler = object(row.scheduler, ["expected_array_tasks", "expected_merge_jobs", "completed_array_tasks", "completed_merge_jobs"], "Invalid Closure submission status.");
  const validation = object(row.validation, ["status", "expected_candidates_per_family", "expected_recoil_seeds_per_candidate"], "Invalid Closure submission status.");
  const chain = parseMot3DFamilyChain(submission.chain), lifecycle = String(submission.status) as Lifecycle, jobs = mot3DFamilyJobCount(chain);
  const allowed = ["not_submitted", "submitted", "queued", "running", "held", "completed_failed", "completed_success_unvalidated", "status_unknown", "outcome_unknown", "partial"];
  const chainMatches = isMot3DFamilyCanonicalPrefix(chain) && (lifecycle === "not_submitted" ? jobs === 0 : lifecycle === "partial" ? jobs >= 1 && jobs <= 3 : lifecycle === "outcome_unknown" ? jobs <= 3 : jobs === 4);
  const arrays = chain.families.filter((family) => family.array_job_id !== null).length, merges = chain.families.filter((family) => family.merge_job_id !== null).length;
  const completedArrays = Number(scheduler.completed_array_tasks), completedMerges = Number(scheduler.completed_merge_jobs);
  const counts = count(completedArrays, 6) && count(completedMerges, 2) && completedArrays <= arrays * 3 && completedMerges <= merges && (!["not_submitted", "partial", "outcome_unknown", "submitted", "queued"].includes(lifecycle) || (completedArrays === 0 && completedMerges === 0)) && (lifecycle !== "running" || completedArrays !== 6 || completedMerges !== 2) && (lifecycle !== "completed_success_unvalidated" || (completedArrays === 6 && completedMerges === 2));
  const action = lifecycle === "not_submitted" ? "review_submission" : ["submitted", "queued", "running"].includes(lifecycle) ? "wait" : lifecycle === "completed_success_unvalidated" ? "await_result_synchronization" : "inspect_zeus";
  if (row.source !== "zeus" || !text(row.queried_at) || Number.isNaN(Date.parse(row.queried_at)) || !text(campaign.id, 512) || !text(campaign.name, 128) || campaign.stage !== "closure" || !allowed.includes(lifecycle) || !chainMatches || scheduler.expected_array_tasks !== 6 || scheduler.expected_merge_jobs !== 2 || !counts || validation.status !== "not_started" || validation.expected_candidates_per_family !== 16 || validation.expected_recoil_seeds_per_candidate !== 3 || row.next_action !== action) throw new Error("Invalid Closure submission status.");
  return { source: "zeus", queried_at: row.queried_at as string, campaign: campaign as Mot3DClosureSubmissionStatus["campaign"], submission: { status: lifecycle, chain }, scheduler: scheduler as Mot3DClosureSubmissionStatus["scheduler"], validation: validation as Mot3DClosureSubmissionStatus["validation"], next_action: action, local_sync: sync(row.local_sync) };
}

export function parseMot3DClosureSubmissionPreview(value: unknown, expected: { campaignId: string; profile: Profile }, resourceStage: Campaign3DResourceStage = "closure"): Mot3DClosureSubmissionPreview {
  const row = object(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "chain", "resources", "science", "remote", "effects", "local_sync"], "Invalid Closure submission review.");
  const campaign = object(row.campaign, ["id", "name", "git_commit"], "Invalid Closure submission review."), stage = object(row.stage, ["id", "label"], "Invalid Closure submission review."), chain = object(row.chain, ["families", "qsub_calls", "dependency"], "Invalid Closure submission review."), resources = object(row.resources, ["array", "merge"], "Invalid Closure submission review."), merge = reviewedCampaignResource(resources.merge, ["ncpus", "memory_gb", "walltime"], "Invalid Closure submission review."), science = object(row.science, ["classification", "candidates_per_family", "input_ensembles", "particles_per_ensemble", "total_particles", "recoil_seeds", "dt_s", "t_max_s", "solver", "selection_seed", "bootstrap_replicates", "bootstrap_seed"], "Invalid Closure submission review."), remote = object(row.remote, ["host", "project_directory", "commit", "branch", "dirty"], "Invalid Closure submission review."), effects = object(row.effects, ["start_simulation", "submit_later_stages", "modify_campaign_files", "record_submission_receipt", "submit_closure"], "Invalid Closure submission review.");
  reviewedCampaignStageArray(resources.array, resourceStage);
  const families = [{ id: "angled_donut", array_tasks: 3, merge_jobs: 1 }, { id: "single_pass", array_tasks: 3, merge_jobs: 1 }];
  if (!text(row.preview_token, 512) || row.expires_in_seconds !== 300 || campaign.id !== expected.campaignId || !text(campaign.name, 128) || typeof campaign.git_commit !== "string" || !sha40.test(campaign.git_commit) || stage.id !== "closure" || stage.label !== "Closure" || JSON.stringify(chain.families) !== JSON.stringify(families) || chain.qsub_calls !== 4 || chain.dependency !== "afterok within each family" || merge.ncpus !== 1 || merge.memory_gb !== 4 || merge.walltime !== "01:00:00" || science.classification !== "candidate_selection_not_final_validation" || science.candidates_per_family !== 16 || science.input_ensembles !== 4 || science.particles_per_ensemble !== campaignParticles(750) || science.total_particles !== campaignTotalParticles(3000) || JSON.stringify(science.recoil_seeds) !== JSON.stringify([42001, 42002, 42003]) || science.dt_s !== MOT_3D_TIMESTEP_POLICY_V2.search_dt_s || science.t_max_s !== MOT_3D_TIMESTEP_POLICY_V2.t_max_s || science.solver !== MOT_3D_TIMESTEP_POLICY_V2.solver || science.selection_seed !== 71001 || science.bootstrap_replicates !== 10000 || science.bootstrap_seed !== 72001 || remote.host !== expected.profile.host || remote.project_directory !== expected.profile.project_directory || remote.commit !== campaign.git_commit || !text(remote.branch) || remote.dirty !== false || effects.start_simulation !== true || effects.submit_later_stages !== false || effects.modify_campaign_files !== false || effects.record_submission_receipt !== true || effects.submit_closure !== true) throw new Error("Invalid Closure submission review.");
  sync(row.local_sync);
  return row as unknown as Mot3DClosureSubmissionPreview;
}

export function parseMot3DClosureSubmissionResult(value: unknown, campaignId: string): Mot3DClosureSubmissionResult {
  const row = object(value, ["status", "campaign_id", "stage", "chain", "submitted_at", "local_sync"], "Invalid Closure submission result."), chain = parseMot3DFamilyChain(row.chain), localSync = sync(row.local_sync);
  if (row.status !== "submitted" || row.campaign_id !== campaignId || row.stage !== "closure" || mot3DFamilyJobCount(chain) !== 4 || !text(row.submitted_at) || Number.isNaN(Date.parse(row.submitted_at))) throw new Error("Invalid Closure submission result.");
  return { ...row, chain, local_sync: localSync } as Mot3DClosureSubmissionResult;
}

export function createMot3DClosureSubmissionApi(session: () => Promise<string>) {
  let generation = 0;
  const contexts = new Map<string, { campaignId: string; csrf: string; generation: number }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(campaignId: string, profile: Profile) { const active = generation, parsed = parseMot3DClosureSubmissionStatus(await postData("/api/v1/zeus/submissions/mot-3d-closure/status", body(campaignId, profile), await session(), closureApiError)); if (active !== generation) throw new Error("The Closure status response is stale."); if (parsed.campaign.id !== campaignId) throw new Error("Closure status did not match the selected campaign."); return parsed; },
    async preview(campaignId: string, profile: Profile) { const active = generation, csrf = await session(), parsed = parseMot3DClosureSubmissionPreview(await postData("/api/v1/zeus/submissions/mot-3d-closure/preview", body(campaignId, profile), csrf, closureApiError), { campaignId, profile }); if (active !== generation) throw new Error("The Closure review response is stale."); contexts.set(parsed.preview_token, { campaignId, csrf, generation: active }); return parsed; },
    async confirm(preview_token: string) {
      const context = contexts.get(preview_token);
      if (!context) throw new Error("The Closure review is no longer active.");
      contexts.delete(preview_token);
      try {
        const result = parseMot3DClosureSubmissionResult(await postData("/api/v1/zeus/submissions/mot-3d-closure/confirm", { preview_token }, context.csrf, (error) => adaptConfirmationError(error, closureApiError, Mot3DClosureSubmissionApiError)), context.campaignId);
        if (context.generation !== generation) throw new Error("stale");
        return result;
      } catch (cause) {
        if (cause instanceof Mot3DClosureSubmissionApiError) throw cause;
        throw new Mot3DClosureSubmissionApiError("closure_submission_outcome_unknown", "The Closure submission result could not be verified. Do not submit again; inspect Zeus jobs.");
      }
    },
    reset() { generation += 1; contexts.clear(); },
  };
}

export type Mot3DClosureSubmissionApi = ReturnType<typeof createMot3DClosureSubmissionApi>;
export const mot3DClosureSubmissionApi = createMot3DClosureSubmissionApi(() => creationApi.session());

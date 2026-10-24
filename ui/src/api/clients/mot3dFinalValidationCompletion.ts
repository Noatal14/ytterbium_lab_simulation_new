import { adaptConfirmationError, isKnownServerError, confirmationRequiresManualVerification } from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";
import { mot3DFamilyJobCount, parseMot3DFamilyChain } from "./mot3dFamilyChain";

type Profile = ZeusSnapshot["profile"];
const domain = "mot_3d_final_validation_completion" as const;
const hex64 = /^[0-9a-f]{64}$/;
const token = /^[A-Za-z0-9_-]{1,256}$/;
const campaignId = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const outcomes = ["complete", "final_validation_extension_required"] as const;
const object = (value: unknown, keys: string[], message: string) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message);
  return value as Record<string, unknown>;
};

export type FinalValidationFamilyResult = {
  family: "angled_donut" | "single_pass";
  candidate_id: string;
  conditional_efficiency: number;
  bootstrap_95_ci: [number, number];
  ci_half_width: number;
  precision_target_met: boolean;
};
export type FinalValidationCompletion = {
  outcome: (typeof outcomes)[number];
  families: [FinalValidationFamilyResult, FinalValidationFamilyResult];
  evidence_sha256: string;
};

function parseCompletion(value: unknown): FinalValidationCompletion {
  const row = object(value, ["outcome", "families", "evidence_sha256"], "Invalid Final Validation completion evidence.");
  if (!outcomes.includes(row.outcome as (typeof outcomes)[number]) || typeof row.evidence_sha256 !== "string" || !hex64.test(row.evidence_sha256) || !Array.isArray(row.families) || row.families.length !== 2) throw new Error("Invalid Final Validation completion evidence.");
  const families = row.families.map((entry, index) => {
    const family = object(entry, ["family", "candidate_id", "conditional_efficiency", "bootstrap_95_ci", "ci_half_width", "precision_target_met"], "Invalid Final Validation completion evidence.");
    const expected = ["angled_donut", "single_pass"][index];
    if (family.family !== expected || typeof family.candidate_id !== "string" || !new RegExp(`^${expected}_finalist_0[1-3]$`).test(family.candidate_id) || typeof family.conditional_efficiency !== "number" || !Number.isFinite(family.conditional_efficiency) || !Array.isArray(family.bootstrap_95_ci) || family.bootstrap_95_ci.length !== 2 || family.bootstrap_95_ci.some((v) => typeof v !== "number" || !Number.isFinite(v)) || typeof family.ci_half_width !== "number" || !Number.isFinite(family.ci_half_width) || typeof family.precision_target_met !== "boolean") throw new Error("Invalid Final Validation completion evidence.");
    const [low, high] = family.bootstrap_95_ci as number[];
    const half = (high - low) / 2;
    if (!(0 <= low && low <= family.conditional_efficiency && family.conditional_efficiency <= high && high <= 1) || family.ci_half_width !== half || family.precision_target_met !== (half <= 0.0075)) throw new Error("Invalid Final Validation completion evidence.");
    return family as FinalValidationFamilyResult;
  }) as [FinalValidationFamilyResult, FinalValidationFamilyResult];
  if ((row.outcome === "complete") !== families.every((family) => family.precision_target_met)) throw new Error("Invalid Final Validation completion evidence.");
  return { outcome: row.outcome as FinalValidationCompletion["outcome"], families, evidence_sha256: row.evidence_sha256 };
}

export class Mot3DFinalValidationCompletionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
const adapt = (error: { code: string; message: string }) => new Mot3DFinalValidationCompletionApiError(isKnownServerError(domain, error.code) ? error.code : "mot_3d_final_validation_completion_failed", isKnownServerError(domain, error.code) ? error.message : "Final Validation completion could not be verified.");
export const finalValidationCompletionIsUncertain = (error: unknown) => error instanceof Mot3DFinalValidationCompletionApiError && (confirmationRequiresManualVerification(domain, error.code) || error.code.includes("outcome_unknown"));

export function parseMot3DFinalValidationCompletionStatus(value: unknown) {
  const r = object(value, ["source", "campaign", "final_validation", "scheduler", "validation", "completion", "next_action", "local_sync"], "Invalid Final Validation completion status.");
  const campaign = object(r.campaign, ["id", "name", "stage"], "Invalid Final Validation completion status.");
  const stage = object(r.final_validation, ["status", "chain"], "Invalid Final Validation completion status.");
  const scheduler = object(r.scheduler, ["completed_array_tasks", "expected_array_tasks", "completed_merge_jobs", "expected_merge_jobs"], "Invalid Final Validation completion status.");
  const validation = object(r.validation, ["status", "result_artifacts", "expected_result_artifacts", "reason_code"], "Invalid Final Validation completion status.");
  const completion = object(r.completion, ["status", "detail"], "Invalid Final Validation completion status.");
  const sync = object(r.local_sync, ["status", "receipt_sha256"], "Invalid Final Validation completion status.");
  const chain = parseMot3DFamilyChain(stage.chain);
  const lifecycle = stage.status;
  const terminal = outcomes.includes(lifecycle as (typeof outcomes)[number]);
  const ready = lifecycle === "ready_to_advance";
  const detail = completion.detail === null ? null : parseCompletion(completion.detail);
  const remotePrepared = terminal && campaign.stage === "final_validation" && sync.status === "not_synchronized" && sync.receipt_sha256 === null && r.next_action === "synchronize_results" && validation.status === "valid" && validation.result_artifacts === 14 && scheduler.completed_array_tasks === 6 && scheduler.completed_merge_jobs === 2;
  if (r.source !== "zeus" || typeof campaign.id !== "string" || !campaignId.test(campaign.id) || typeof campaign.name !== "string" || !campaign.name || !["final_validation", ...outcomes].includes(campaign.stage as string) || typeof lifecycle !== "string" || !["queued", "running", "held", "completed_failed", "status_unknown", "completed_success_unvalidated", "outputs_invalid", "ready_to_advance", "outcome_unknown", ...outcomes].includes(lifecycle) || mot3DFamilyJobCount(chain) !== 4 || scheduler.expected_array_tasks !== 6 || scheduler.expected_merge_jobs !== 2 || !Number.isInteger(scheduler.completed_array_tasks) || !Number.isInteger(scheduler.completed_merge_jobs) || Number(scheduler.completed_array_tasks) < 0 || Number(scheduler.completed_array_tasks) > 6 || Number(scheduler.completed_merge_jobs) < 0 || Number(scheduler.completed_merge_jobs) > 2 || validation.expected_result_artifacts !== 14 || validation.result_artifacts !== (validation.status === "valid" ? 14 : 0) || !["not_started", "valid", "scientifically_invalid"].includes(validation.status as string) || (validation.status === "scientifically_invalid" ? typeof validation.reason_code !== "string" : validation.reason_code !== null) || completion.status !== (terminal ? lifecycle : "not_completed") || (terminal && !remotePrepared ? detail?.outcome !== lifecycle : detail !== null) || campaign.stage !== (terminal && !remotePrepared ? lifecycle : "final_validation") || sync.status !== (terminal && campaign.stage === lifecycle ? "synchronized" : "not_synchronized") || (sync.status === "synchronized" ? typeof sync.receipt_sha256 !== "string" || !hex64.test(sync.receipt_sha256) : sync.receipt_sha256 !== null)) throw new Error("Invalid Final Validation completion status.");
  const expectedAction = terminal ? (sync.status === "synchronized" ? (lifecycle === "complete" ? "open_final_report" : "review_extension_required") : "synchronize_results") : ready ? "review_completion" : ["held", "completed_failed", "status_unknown", "outputs_invalid", "outcome_unknown"].includes(lifecycle as string) || validation.status === "scientifically_invalid" ? "inspect_zeus" : "wait";
  if (r.next_action !== expectedAction || ((ready || terminal) && validation.status !== "valid") || ((ready || terminal) && (scheduler.completed_array_tasks !== 6 || scheduler.completed_merge_jobs !== 2))) throw new Error("Invalid Final Validation completion status.");
  return { ...r, completion: { status: completion.status, detail } } as { source: "zeus"; campaign: { id: string; name: string; stage: "final_validation" | "complete" | "final_validation_extension_required" }; final_validation: { status: string; chain: typeof chain }; scheduler: { completed_array_tasks: number; expected_array_tasks: 6; completed_merge_jobs: number; expected_merge_jobs: 2 }; validation: { status: "not_started" | "valid" | "scientifically_invalid"; result_artifacts: number; expected_result_artifacts: 14; reason_code: string | null }; completion: { status: "not_completed" | FinalValidationCompletion["outcome"]; detail: FinalValidationCompletion | null }; next_action: "wait" | "inspect_zeus" | "review_completion" | "synchronize_results" | "open_final_report" | "review_extension_required"; local_sync: { status: "not_synchronized" | "synchronized"; receipt_sha256: string | null } };
}

export function parseMot3DFinalValidationCompletionPreview(value: unknown, expected: { campaignId: string; commit: string }) {
  const r = object(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "final_validation", "artifacts", "effects", "completion"], "Invalid Final Validation completion review.");
  const campaign = object(r.campaign, ["id", "name", "git_commit"], "Invalid Final Validation completion review.");
  const stage = object(r.final_validation, ["result_artifacts", "expected_result_artifacts", "families", "evidence_sha256"], "Invalid Final Validation completion review.");
  const artifacts = object(r.artifacts, ["synchronize", "create", "update", "transfer_files"], "Invalid Final Validation completion review.");
  const synchronize = object(artifacts.synchronize, ["result_files", "submission_receipts"], "Invalid Final Validation completion review.");
  const create = object(artifacts.create, ["terminal_files"], "Invalid Final Validation completion review.");
  const effects = object(r.effects, ["synchronize_final_validation", "complete_final_validation", "submit_extension", "start_simulation", "overwrite_existing"], "Invalid Final Validation completion review.");
  const completion = parseCompletion(r.completion);
  if (typeof r.preview_token !== "string" || !token.test(r.preview_token) || r.expires_in_seconds !== 300 || campaign.id !== expected.campaignId || typeof campaign.name !== "string" || !campaign.name || campaign.git_commit !== expected.commit || !/^[0-9a-f]{40}$/.test(expected.commit) || r.from_stage !== "final_validation" || r.to_stage !== "complete_or_extension_required" || stage.result_artifacts !== 14 || stage.expected_result_artifacts !== 14 || JSON.stringify(stage.families) !== JSON.stringify(["angled_donut", "single_pass"]) || stage.evidence_sha256 !== completion.evidence_sha256 || synchronize.result_files !== 14 || synchronize.submission_receipts !== 1 || create.terminal_files !== 1 || JSON.stringify(artifacts.update) !== JSON.stringify(["campaign.json"]) || artifacts.transfer_files !== 17 || effects.synchronize_final_validation !== true || effects.complete_final_validation !== true || effects.submit_extension !== false || effects.start_simulation !== false || effects.overwrite_existing !== false) throw new Error("Invalid Final Validation completion review.");
  return { ...r, completion } as typeof r & { preview_token: string; completion: FinalValidationCompletion };
}

function parseResult(value: unknown, id: string) {
  const r = object(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"], "Invalid Final Validation completion result.");
  const artifacts = object(r.artifacts, ["synchronized", "created", "updated", "bundle_sha256"], "Invalid Final Validation completion result.");
  const sync = object(r.local_sync, ["status", "receipt_sha256"], "Invalid Final Validation completion result.");
  if (!outcomes.includes(r.status as (typeof outcomes)[number]) || r.campaign_id !== id || r.stage !== r.status || artifacts.synchronized !== 15 || artifacts.created !== 1 || artifacts.updated !== 1 || typeof artifacts.bundle_sha256 !== "string" || !hex64.test(artifacts.bundle_sha256) || r.submitted_to_zeus !== false || r.simulation_started !== false || sync.status !== "synchronized" || typeof sync.receipt_sha256 !== "string" || !hex64.test(sync.receipt_sha256)) throw new Error("Invalid Final Validation completion result.");
  return r;
}

export function createMot3DFinalValidationCompletionApi(session: () => Promise<string>) {
  let generation = 0;
  const contexts = new Map<string, { campaignId: string; csrf: string; generation: number; completion: FinalValidationCompletion }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(id: string, profile: Profile) { const g = generation; const value = parseMot3DFinalValidationCompletionStatus(await postData("/api/v1/zeus/mot-3d/final-validation-completion/status", body(id, profile), await session(), adapt)); if (g !== generation || value.campaign.id !== id) throw new Error("Final Validation completion status is stale."); return value; },
    async preview(id: string, profile: Profile, commit: string) { const g = generation, csrf = await session(); const value = parseMot3DFinalValidationCompletionPreview(await postData("/api/v1/zeus/mot-3d/final-validation-completion/preview", body(id, profile), csrf, adapt), { campaignId: id, commit }); if (g !== generation) throw new Error("Final Validation completion review is stale."); contexts.set(value.preview_token, { campaignId: id, csrf, generation: g, completion: value.completion }); return value; },
    async confirm(review: { preview_token: string }) { const context = contexts.get(review.preview_token); if (!context) throw new Error("Review is no longer active."); contexts.delete(review.preview_token); try { const result = parseResult(await postData("/api/v1/zeus/mot-3d/final-validation-completion/confirm", { preview_token: review.preview_token }, context.csrf, (error) => adaptConfirmationError(error, adapt, Mot3DFinalValidationCompletionApiError)), context.campaignId); if (context.generation !== generation) throw new Error("stale"); return { ...result, completion: context.completion }; } catch (error) { if (error instanceof Mot3DFinalValidationCompletionApiError) throw error; throw new Mot3DFinalValidationCompletionApiError("final_validation_completion_outcome_unknown", "The completion outcome could not be verified. Do not retry."); } },
    reset() { generation += 1; contexts.clear(); },
  };
}
export type Mot3DFinalValidationCompletionApi = ReturnType<typeof createMot3DFinalValidationCompletionApi>;
export const mot3DFinalValidationCompletionApi = createMot3DFinalValidationCompletionApi(async () => creationApi.session());

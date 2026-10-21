import { reviewedCampaignResource, campaignGenerationJob, campaignGenerationPools } from "../campaignPolicy";
import { adaptConfirmationError, isKnownServerError, confirmationRequiresManualVerification } from "../errorSemantics";
import { postData } from "../http/envelope";
import { exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";

type Profile = ZeusSnapshot["profile"];
type Job = { id: "zeeman" | "mot_2d" | "freeze"; job_id: string | null };
const domain = "mot_3d_final_input_submission" as const;
const hex64 = /^[0-9a-f]{64}$/;
const arrayJob = /^\d+\[\]\.zeus-master$/;
const scalarJob = /^\d+\.zeus-master$/;
const token = /^[A-Za-z0-9_-]{1,256}$/;
const identifier = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const commit40 = /^[0-9a-f]{40}$/;
const lifecycles = ["eligible", "submitted", "queued", "running", "held", "completed_failed", "completed_success_unvalidated", "status_unknown", "partial", "outcome_unknown"] as const;
const record = (value: unknown, keys: string[], message: string) => { if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message); return value as Record<string, unknown>; };
const stringArray = (start: number) => Array.from({ length: 20 }, (_, index) => start + index);
export class Mot3DFinalInputSubmissionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
const adaptError = (error: { code: string; message: string }) => new Mot3DFinalInputSubmissionApiError(isKnownServerError(domain, error.code) ? error.code : "mot_3d_final_input_submission_failed", isKnownServerError(domain, error.code) ? error.message : "Final-validation input submission could not be verified.");
export const finalInputConfirmIsUncertain = (cause: unknown) => cause instanceof Mot3DFinalInputSubmissionApiError && (confirmationRequiresManualVerification(domain, cause.code) || ["final_input_partial_submission", "final_input_submission_outcome_unknown", "final_input_submission_conflict", "final_input_submission_busy"].includes(cause.code));

function parseJobs(value: unknown, lifecycle: string): [Job, Job, Job] {
  const chain = record(value, ["status", "dependency", "jobs"], "Invalid input-generation status.");
  if (chain.status !== lifecycle || chain.dependency !== "afterok linear chain" || !Array.isArray(chain.jobs) || chain.jobs.length !== 3) throw new Error("Invalid input-generation status.");
  const ids = ["zeeman", "mot_2d", "freeze"] as const;
  const jobs = chain.jobs.map((value, index) => { const job = record(value, ["id", "job_id"], "Invalid input-generation job chain."); if (job.id !== ids[index]) throw new Error("Invalid input-generation job chain."); return { id: ids[index], job_id: job.job_id as string | null }; }) as [Job, Job, Job];
  let prefix = 0;
  jobs.forEach((job, index) => { if (job.job_id !== null) { if (prefix !== index || !(index < 2 ? arrayJob : scalarJob).test(job.job_id)) throw new Error("Invalid input-generation job chain."); prefix += 1; } });
  const numbers = jobs.filter((job) => job.job_id).map((job) => job.job_id!.split(/[.[\]]/, 1)[0]);
  if (new Set(numbers).size !== numbers.length || (lifecycle === "eligible" && prefix !== 0) || (lifecycle === "partial" && ![1, 2].includes(prefix)) || (lifecycle === "outcome_unknown" && ![0, 1, 2].includes(prefix)) || (!["eligible", "partial", "outcome_unknown"].includes(lifecycle) && prefix !== 3)) throw new Error("Invalid input-generation job chain.");
  return jobs;
}

export function parseMot3DFinalInputStatus(value: unknown) {
  const root = record(value, ["source", "queried_at", "campaign", "chain", "scheduler", "next_action", "local_sync"], "Invalid input-generation status.");
  const campaign = record(root.campaign, ["id", "name", "stage"], "Invalid input-generation status.");
  const chain = record(root.chain, ["status", "dependency", "jobs"], "Invalid input-generation status.");
  const scheduler = record(root.scheduler, ["expected_array_tasks", "expected_scalar_jobs", "completed_array_tasks", "completed_scalar_jobs"], "Invalid input-generation status.");
  const sync = record(root.local_sync, ["status", "receipt_sha256"], "Invalid input-generation status.");
  if (typeof chain.status !== "string") throw new Error("Invalid input-generation status.");
  const lifecycle = chain.status;
  const action = lifecycle === "eligible" ? "review_submission" : lifecycle === "completed_success_unvalidated" ? "validate_generated_inputs" : ["partial", "outcome_unknown", "held", "completed_failed", "status_unknown"].includes(lifecycle) ? "inspect_zeus" : "wait";
  const counts = [scheduler.completed_array_tasks, scheduler.completed_scalar_jobs];
  if (root.source !== "zeus" || typeof root.queried_at !== "string" || !Number.isFinite(Date.parse(root.queried_at)) || typeof campaign.id !== "string" || !identifier.test(campaign.id) || typeof campaign.name !== "string" || campaign.name.length < 1 || campaign.name.length > 160 || campaign.stage !== "final_validation_input_generation" || !lifecycles.includes(lifecycle as typeof lifecycles[number]) || root.next_action !== action || scheduler.expected_array_tasks !== 40 || scheduler.expected_scalar_jobs !== 1 || counts.some((count) => !Number.isInteger(count)) || Number(counts[0]) < 0 || Number(counts[0]) > 40 || Number(counts[1]) < 0 || Number(counts[1]) > 1 || (["eligible", "submitted", "partial", "outcome_unknown"].includes(lifecycle) && counts.some((count) => count !== 0)) || (lifecycle === "completed_success_unvalidated" && (counts[0] !== 40 || counts[1] !== 1)) || sync.status !== "synchronized" || typeof sync.receipt_sha256 !== "string" || !hex64.test(sync.receipt_sha256)) throw new Error("Invalid input-generation status.");
  parseJobs(root.chain, lifecycle);
  return root as { source: "zeus"; queried_at: string; campaign: { id: string; name: string; stage: "final_validation_input_generation" }; chain: { status: typeof lifecycles[number]; dependency: "afterok linear chain"; jobs: [Job, Job, Job] }; scheduler: { expected_array_tasks: 40; expected_scalar_jobs: 1; completed_array_tasks: number; completed_scalar_jobs: number }; next_action: "review_submission" | "wait" | "inspect_zeus" | "validate_generated_inputs"; local_sync: { status: "synchronized"; receipt_sha256: string } };
}

const resource = (value: unknown, expected: [number, number, string]) => { const parsed = reviewedCampaignResource(value, ["ncpus", "memory_gb", "walltime"], "Invalid input-generation resources."); if (parsed.ncpus !== expected[0] || parsed.memory_gb !== expected[1] || parsed.walltime !== expected[2]) throw new Error("Invalid input-generation resources."); return parsed; };
export function parseMot3DFinalInputPreview(value: unknown, expected: { campaignId: string; commit: string }) {
  const root = record(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "chain", "science", "effects", "local_sync"], "Invalid input-generation review.");
  const campaign = record(root.campaign, ["id", "name", "git_commit"], "Invalid input-generation review.");
  const stage = record(root.stage, ["id", "label"], "Invalid input-generation review.");
  const chain = record(root.chain, ["dependency", "steps"], "Invalid input-generation review.");
  const science = record(root.science, ["classification", "zeeman_seeds", "mot_seeds", "zeeman_tasks", "mot_tasks", "npools", "dependency", "resources"], "Invalid input-generation review.");
  const resources = record(science.resources, ["zeeman", "mot_2d", "freeze"], "Invalid input-generation resources.");
  const effects = record(root.effects, ["submit_input_generation", "start_final_validation", "advance_campaign", "modify_files"], "Invalid input-generation review.");
  const sync = record(root.local_sync, ["status", "receipt_sha256"], "Invalid input-generation review.");
  const expectedSteps = [["zeeman", 20, campaignGenerationJob("zeeman", [200,64,"08:00:00"])], ["mot_2d", 20, campaignGenerationJob("mot_2d", [200,64,"12:00:00"])], ["freeze", 1, campaignGenerationJob("freeze", [1,8,"00:30:00"])]] as const;
  if (!Array.isArray(chain.steps) || chain.steps.length !== 3) throw new Error("Invalid input-generation review.");
  chain.steps.forEach((value, index) => { const step = record(value, ["id", "tasks", "resources"], "Invalid input-generation review."); const wanted = expectedSteps[index]; if (step.id !== wanted[0] || step.tasks !== wanted[1]) throw new Error("Invalid input-generation review."); resource(step.resources, [...wanted[2]]); });
  resource(resources.zeeman, campaignGenerationJob("zeeman", [200,64,"08:00:00"])); resource(resources.mot_2d, campaignGenerationJob("mot_2d", [200,64,"12:00:00"])); resource(resources.freeze, campaignGenerationJob("freeze", [1,8,"00:30:00"]));
  if (typeof root.preview_token !== "string" || !token.test(root.preview_token) || root.expires_in_seconds !== 300 || typeof campaign.id !== "string" || campaign.id !== expected.campaignId || !identifier.test(campaign.id) || typeof campaign.name !== "string" || campaign.name.length < 1 || campaign.name.length > 160 || typeof campaign.git_commit !== "string" || !commit40.test(campaign.git_commit) || campaign.git_commit !== expected.commit || stage.id !== "final_validation_input_generation" || stage.label !== "Final validation input generation" || chain.dependency !== "afterok linear chain" || science.classification !== "new_unopened_inputs_after_nominal_lock" || JSON.stringify(science.zeeman_seeds) !== JSON.stringify(stringArray(3035)) || JSON.stringify(science.mot_seeds) !== JSON.stringify(stringArray(43035)) || science.zeeman_tasks !== 20 || science.mot_tasks !== 20 || science.npools !== campaignGenerationPools() || science.dependency !== "afterok linear chain" || effects.submit_input_generation !== true || effects.start_final_validation !== false || effects.advance_campaign !== false || effects.modify_files !== false || sync.status !== "synchronized" || typeof sync.receipt_sha256 !== "string" || !hex64.test(sync.receipt_sha256)) throw new Error("Invalid input-generation review.");
  return root as { preview_token: string; expires_in_seconds: 300; campaign: { id: string; name: string; git_commit: string }; stage: { id: "final_validation_input_generation"; label: "Final validation input generation" }; chain: { dependency: "afterok linear chain"; steps: Array<{ id: "zeeman" | "mot_2d" | "freeze"; tasks: number; resources: { ncpus: number; memory_gb: number; walltime: string; vnode?: string } }> }; science: { classification: "new_unopened_inputs_after_nominal_lock"; zeeman_seeds: number[]; mot_seeds: number[]; zeeman_tasks: 20; mot_tasks: 20; npools: number; dependency: "afterok linear chain"; resources: Record<string, unknown> }; effects: { submit_input_generation: true; start_final_validation: false; advance_campaign: false; modify_files: false }; local_sync: { status: "synchronized"; receipt_sha256: string } };
}

export function parseMot3DFinalInputResult(value: unknown, campaignId: string) {
  const root = record(value, ["status", "campaign_id", "stage", "chain", "submitted_to_zeus", "simulation_started", "final_validation_started", "local_sync"], "Invalid input-generation result.");
  const sync = record(root.local_sync, ["status", "receipt_sha256"], "Invalid input-generation result.");
  if (root.status !== "submitted" || typeof root.campaign_id !== "string" || root.campaign_id !== campaignId || !identifier.test(root.campaign_id) || root.stage !== "final_validation_input_generation" || root.submitted_to_zeus !== true || root.simulation_started !== true || root.final_validation_started !== false || sync.status !== "synchronized" || typeof sync.receipt_sha256 !== "string" || !hex64.test(sync.receipt_sha256)) throw new Error("Invalid input-generation result.");
  parseJobs({ ...(root.chain as Record<string, unknown>), status: "submitted" }, "submitted");
  return root as { status: "submitted"; campaign_id: string; stage: "final_validation_input_generation"; chain: { dependency: "afterok linear chain"; jobs: [Job, Job, Job] }; submitted_to_zeus: true; simulation_started: true; final_validation_started: false; local_sync: { status: "synchronized"; receipt_sha256: string } };
}

export function createMot3DFinalInputSubmissionApi(session: () => Promise<string>) {
  let generation = 0; const contexts = new Map<string, { campaignId: string; csrf: string; generation: number }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(campaignId: string, profile: Profile) { const active = generation, parsed = parseMot3DFinalInputStatus(await postData("/api/v1/zeus/submissions/mot-3d-final-validation-inputs/status", body(campaignId, profile), await session(), adaptError)); if (active !== generation || parsed.campaign.id !== campaignId) throw new Error("Input-generation status is stale or mismatched."); return parsed; },
    async preview(campaignId: string, profile: Profile, commit: string) { const active = generation, csrf = await session(), parsed = parseMot3DFinalInputPreview(await postData("/api/v1/zeus/submissions/mot-3d-final-validation-inputs/preview", body(campaignId, profile), csrf, adaptError), { campaignId, commit }); if (active !== generation) throw new Error("Input-generation review is stale."); contexts.set(parsed.preview_token, { campaignId, csrf, generation: active }); return parsed; },
    async confirm(preview_token: string) { const context = contexts.get(preview_token); if (!context) throw new Error("The input-generation review is no longer active."); contexts.delete(preview_token); try { const parsed = parseMot3DFinalInputResult(await postData("/api/v1/zeus/submissions/mot-3d-final-validation-inputs/confirm", { preview_token }, context.csrf, (error) => adaptConfirmationError(error, adaptError, Mot3DFinalInputSubmissionApiError)), context.campaignId); if (context.generation !== generation) throw new Error("stale"); return parsed; } catch (cause) { if (cause instanceof Mot3DFinalInputSubmissionApiError) throw cause; throw new Mot3DFinalInputSubmissionApiError("final_input_submission_outcome_unknown", "The submission outcome could not be verified. Do not submit again; inspect Zeus first."); } },
    reset() { generation += 1; contexts.clear(); },
  };
}
export type Mot3DFinalInputSubmissionApi = ReturnType<typeof createMot3DFinalInputSubmissionApi>;
export const mot3DFinalInputSubmissionApi = createMot3DFinalInputSubmissionApi(() => creationApi.session());

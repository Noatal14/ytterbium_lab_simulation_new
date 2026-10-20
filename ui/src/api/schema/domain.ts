import { isCampaignProjectDirectory, zeusProjectDirectory } from "../zeusEnvironment";
import { campaignAcceptanceMode } from "../zeusEnvironment";
import { boundedPrintable, exactKeys as hasExactKeys, finiteNonnegative, nullableBoundedPrintable, roundTiesToEven, text, validUtc } from "./common";
import { MOT_2D_SPECIFICATION_V1, reviewedCampaignResource } from "../campaignPolicy";
export { roundTiesToEven } from "./common";

const canonicalDesign = MOT_2D_SPECIFICATION_V1.design;
const canonicalStages = MOT_2D_SPECIFICATION_V1.stages;
const sensitivityCreates=canonicalStages.sensitivity.artifacts.filter(item=>item!=="campaign.json");
const sensitivityUpdates=canonicalStages.sensitivity.artifacts.filter(item=>item==="campaign.json");
const productionCreates=canonicalStages.production.artifacts.filter(item=>item!=="campaign.json");
const productionUpdates=canonicalStages.production.artifacts.filter(item=>item==="campaign.json");
const finalizationUpdates=MOT_2D_SPECIFICATION_V1.finalization.artifacts.filter(item=>item==="campaign.json");
const canonicalRanks = (count: number) => Array.from({ length: count }, (_, index) => index + 1);
const canonicalWorkerSource = (value: unknown, stage: "screen" | "refine"): value is string => {
  if (!text(value)) return false;
  const match = new RegExp(`^${stage}/s0_[^/]+/worker(\\d+)/trials/trial_\\d{4}\\.json$`).exec(value);
  return match !== null && Number(match[1]) < canonicalDesign.workers_per_s0;
};

export type Warning = { severity: "info" | "attention" | "blocked"; message: string };
export type StageProgress = { stage: string; completed: number; expected: number | null; status: "not-started" | "in-progress" | "complete" | "unknown" | "inconsistent" };
export type Campaign = {
  id: string; family: "mot_2d" | "mot_3d"; kind: string; name: string; path: string; stage: string;
  stage_semantics: "prepared-workflow-stage"; scheduler_status: "unchecked";
  trust: "trusted-current" | "legacy-incomplete"; scientific_role: "candidate-selection" | "sealed-final-validation" | "historical-evidence" | "acceptance-only";
  progress: StageProgress[]; warnings: Warning[];
  next_plan: null | { label: string; command: string[]; display_command: string; mode: "copy-only"; scheduler_status: "unchecked"; operation_scope: "remote-submission" | "local-mutation"; executes_automatically: false };
  s0_values: number[]; families: string[]; git_commit: string | null;
  remote_preparation: { status: "ready" | "legacy-local-only" | "unavailable"; reason_code: null | "absolute-input-paths" | "fixed-checkout-path" | "incomplete-portability-record" | "campaign-validation-failed" };
};
const exactKeys = hasExactKeys;
const reviewedJobKeys = (value: Record<string, unknown>, keys: string[]) => {
  try { reviewedCampaignResource(value, keys); return true; } catch { return false; }
};
export function parseCampaign(value: unknown): Campaign {
  if (!value || typeof value !== "object") throw new Error("Invalid campaign response.");
  const row = value as Record<string, unknown>;
  const families = ["mot_2d", "mot_3d"];
  const trusts = ["trusted-current", "legacy-incomplete"];
  const roles = ["candidate-selection", "sealed-final-validation", "historical-evidence", "acceptance-only"];
  const acceptance = ["mot_2d_ui_acceptance_v1", "mot_3d_ui_acceptance_v1"].includes(String(row.kind));
  if (acceptance !== campaignAcceptanceMode() || (acceptance && row.scientific_role !== "acceptance-only")) throw new Error("Campaign policy does not match this UI environment.");
  const remote = row.remote_preparation as Record<string, unknown> | undefined;
  const remotePair = `${String(remote?.status)}/${String(remote?.reason_code)}`;
  if (!text(row.id) || !families.includes(String(row.family)) || !text(row.kind) || !text(row.name) || !text(row.path) || !text(row.stage) || row.stage_semantics !== "prepared-workflow-stage" || row.scheduler_status !== "unchecked" || !trusts.includes(String(row.trust)) || !roles.includes(String(row.scientific_role)) || !Array.isArray(row.progress) || !Array.isArray(row.warnings) || !Array.isArray(row.s0_values) || !row.s0_values.every((item) => typeof item === "number" && Number.isFinite(item)) || !Array.isArray(row.families) || !row.families.every(text) || (row.git_commit !== null && !text(row.git_commit)) || !remote || !exactKeys(remote, ["status", "reason_code"]) || !["ready/null", "legacy-local-only/absolute-input-paths", "legacy-local-only/fixed-checkout-path", "unavailable/incomplete-portability-record", "unavailable/campaign-validation-failed"].includes(remotePair)) throw new Error("Invalid campaign response.");
  for (const progress of row.progress) {
    const item = progress as Record<string, unknown>;
    if (!progress || typeof progress !== "object" || !text(item.stage) || !finiteNonnegative(item.completed) || (item.expected !== null && !finiteNonnegative(item.expected)) || (typeof item.expected === "number" && item.completed > item.expected) || !["not-started", "in-progress", "complete", "unknown", "inconsistent"].includes(String(item.status))) throw new Error("Invalid campaign progress response.");
  }
  for (const warning of row.warnings) {
    const item = warning as Record<string, unknown>;
    if (!warning || typeof warning !== "object" || !["info", "attention", "blocked"].includes(String(item.severity)) || !text(item.message)) throw new Error("Invalid campaign warning response.");
  }
  if (row.next_plan !== null && row.next_plan !== undefined) {
    const plan = row.next_plan as Record<string, unknown>;
    if (!text(plan.label) || !Array.isArray(plan.command) || !plan.command.every(text) || !text(plan.display_command) || plan.mode !== "copy-only" || plan.scheduler_status !== "unchecked" || plan.executes_automatically !== false || !["local-mutation", "remote-submission"].includes(String(plan.operation_scope))) throw new Error("Invalid campaign action response.");
  }
  if (remote.status !== "ready" && row.next_plan !== null && row.next_plan !== undefined) throw new Error("Invalid campaign action response.");
  return row as unknown as Campaign;
}
export type ZeemanSource = { id: string; path: string; profile: string; ensemble_count: number; minimum_survivors: number; maximum_survivors: number; fingerprint: string };
export type CreationPreview = {
  preview_token: string | null; expires_in_seconds: number;
  plan: null | { name: string; path: string; s0_values: number[]; source_id: string; files: string[]; stage: "smoke" };
  scientific_design: Record<string, unknown>;
  provenance: { commit: string; input_count: typeof canonicalDesign.ensemble_count };
  duplicate: null | { campaign_id: string | null; path: string; stage: string };
};
export type CreationResult = { status: "created"; campaign_id: string; path: string; stage: "smoke"; submitted_to_zeus: false };

export type ZeusJob = {
  id: string; name: string; raw_state: "Q" | "R" | "H" | "F" | "X" | "E" | "B" | "S" | "W" | "T" | "U" | "?";
  state: "queued" | "running" | "held_attention" | "completed_success" | "completed_failed" | "unknown";
  exit_status: number | null; walltime: string | null; start_time: string | null; comment: string | null; dependencies: string[];
};
export type ZeusSnapshot = {
  connection_status: "connected";
  profile: { host: "zeus.technion.ac.il"; username: string; project_directory: string; authentication: "ssh-key-or-agent" };
  remote: { project_directory: string; git_commit: string; branch: string; dirty: boolean };
  scheduler: { status: "available"; queried_at: string; jobs: ZeusJob[] };
};

export function parseZeusSnapshot(value: unknown): ZeusSnapshot {
  if (!value || typeof value !== "object") throw new Error("Invalid Zeus snapshot response.");
  const row = value as Record<string, unknown>;
  const profile = row.profile as Record<string, unknown>;
  const remote = row.remote as Record<string, unknown>;
  const scheduler = row.scheduler as Record<string, unknown>;
  if (!exactKeys(row, ["connection_status", "profile", "remote", "scheduler"]) || row.connection_status !== "connected" || !profile || !exactKeys(profile, ["host", "username", "project_directory", "authentication"]) || profile.host !== "zeus.technion.ac.il" || !text(profile.username) || !/^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(profile.username) || !text(profile.project_directory) || profile.project_directory !== zeusProjectDirectory(String(profile.username)) || profile.authentication !== "ssh-key-or-agent" || !remote || !exactKeys(remote, ["project_directory", "git_commit", "branch", "dirty"]) || remote.project_directory !== profile.project_directory || !text(remote.git_commit) || !/^[0-9a-f]{40}$/.test(remote.git_commit) || !boundedPrintable(remote.branch, 256) || typeof remote.dirty !== "boolean" || !scheduler || !exactKeys(scheduler, ["status", "queried_at", "jobs"]) || scheduler.status !== "available" || !text(scheduler.queried_at) || Number.isNaN(Date.parse(String(scheduler.queried_at))) || !Array.isArray(scheduler.jobs) || scheduler.jobs.length > 500) throw new Error("Invalid Zeus snapshot response.");
  const rawStates = ["Q", "R", "H", "F", "X", "E", "B", "S", "W", "T", "U", "?"];
  const states = ["queued", "running", "held_attention", "completed_success", "completed_failed", "unknown"];
  const jobId = /^\d+(?:\[\d+\]|\[\])?(?:\.zeus-master)?$/;
  const seenJobs = new Set<string>();
  for (const job of scheduler.jobs) {
    if (!job || typeof job !== "object") throw new Error("Invalid Zeus job response.");
    const item = job as Record<string, unknown>;
    if (!exactKeys(item, ["id", "name", "raw_state", "state", "exit_status", "walltime", "start_time", "comment", "dependencies"]) || !text(item.id) || !jobId.test(item.id) || seenJobs.has(item.id) || !boundedPrintable(item.name, 128) || !rawStates.includes(String(item.raw_state)) || !states.includes(String(item.state)) || (item.exit_status !== null && (!Number.isInteger(item.exit_status) || Number(item.exit_status) < -2_147_483_648 || Number(item.exit_status) > 2_147_483_647)) || !nullableBoundedPrintable(item.walltime, 32) || !nullableBoundedPrintable(item.start_time, 128) || !nullableBoundedPrintable(item.comment, 512) || !Array.isArray(item.dependencies) || item.dependencies.length > 500 || !item.dependencies.every((dependency) => text(dependency) && jobId.test(dependency))) throw new Error("Invalid Zeus job response.");
    seenJobs.add(item.id);
    const expectedState = item.raw_state === "Q" ? "queued"
      : ["R", "E", "B"].includes(String(item.raw_state)) ? "running"
      : item.raw_state === "H" ? "held_attention"
      : ["F", "X"].includes(String(item.raw_state)) && item.exit_status === 0 ? "completed_success"
      : ["F", "X"].includes(String(item.raw_state)) && item.exit_status !== null ? "completed_failed"
      : "unknown";
    if (item.state !== expectedState) throw new Error("Inconsistent Zeus job response.");
  }
  return row as unknown as ZeusSnapshot;
}


export type ZeusTransferPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; path: string; git_commit: string };
  destination: { host: "zeus.technion.ac.il"; project_directory: string; campaign_directory: string };
  artifacts: { ensemble_count: typeof canonicalDesign.ensemble_count; total_count: typeof canonicalDesign.prepared_file_count; missing_count: number; identical_count: number; total_bytes: number; missing_bytes: number };
  effects: { copy_missing_only: true; overwrite_existing: false; submit_jobs: false; run_simulation: false };
};
export type ZeusTransferResult = {
  status: "prepared"; campaign_id: string; destination: string; transferred_count: number;
  reused_identical_count: number; bytes_transferred: number; submitted_to_zeus: false; simulation_started: false;
};

export function parseTransferPreview(value: Record<string, unknown>): ZeusTransferPreview {
  const campaign = value.campaign as Record<string, unknown>;
  const destination = value.destination as Record<string, unknown>;
  const artifacts = value.artifacts as Record<string, unknown>;
  const effects = value.effects as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "destination", "artifacts", "effects"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "path", "git_commit"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !boundedPrintable(campaign.path, 1024) || !String(campaign.path).startsWith("data/optimization/mot_2d/") || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit))
    || !destination || !exactKeys(destination, ["host", "project_directory", "campaign_directory"]) || destination.host !== "zeus.technion.ac.il" || !boundedPrintable(destination.project_directory, 1024) || !isCampaignProjectDirectory(destination.project_directory) || !boundedPrintable(destination.campaign_directory, 2048) || destination.campaign_directory !== `${destination.project_directory}/${campaign.path}`
    || !artifacts || !exactKeys(artifacts, ["ensemble_count", "total_count", "missing_count", "identical_count", "total_bytes", "missing_bytes"]) || artifacts.ensemble_count !== canonicalDesign.ensemble_count || artifacts.total_count !== canonicalDesign.prepared_file_count || !Number.isInteger(artifacts.missing_count) || !Number.isInteger(artifacts.identical_count) || !Number.isInteger(artifacts.total_bytes) || !Number.isInteger(artifacts.missing_bytes) || !finiteNonnegative(artifacts.missing_count) || !finiteNonnegative(artifacts.identical_count) || !finiteNonnegative(artifacts.total_bytes) || !finiteNonnegative(artifacts.missing_bytes) || Number(artifacts.missing_count) + Number(artifacts.identical_count) !== canonicalDesign.prepared_file_count || Number(artifacts.missing_bytes) > Number(artifacts.total_bytes)
    || !effects || !exactKeys(effects, ["copy_missing_only", "overwrite_existing", "submit_jobs", "run_simulation"]) || effects.copy_missing_only !== true || effects.overwrite_existing !== false || effects.submit_jobs !== false || effects.run_simulation !== false) throw new Error("Invalid Zeus preparation preview response.");
  return value as unknown as ZeusTransferPreview;
}

export function parseTransferResult(value: Record<string, unknown>): ZeusTransferResult {
  if (!exactKeys(value, ["status", "campaign_id", "destination", "transferred_count", "reused_identical_count", "bytes_transferred", "submitted_to_zeus", "simulation_started"]) || value.status !== "prepared" || !boundedPrintable(value.campaign_id, 512) || !boundedPrintable(value.destination, 2048) || !Number.isInteger(value.transferred_count) || !Number.isInteger(value.reused_identical_count) || !Number.isInteger(value.bytes_transferred) || !finiteNonnegative(value.transferred_count) || !finiteNonnegative(value.reused_identical_count) || Number(value.transferred_count) + Number(value.reused_identical_count) !== canonicalDesign.prepared_file_count || !finiteNonnegative(value.bytes_transferred) || value.submitted_to_zeus !== false || value.simulation_started !== false) throw new Error("Invalid Zeus preparation result.");
  return value as unknown as ZeusTransferResult;
}


export type SmokeSubmissionPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; path: string; git_commit: string; s0_values: number[] };
  stage: { id: "smoke"; label: typeof canonicalStages.smoke.label; purpose: string };
  job: { file: typeof canonicalStages.smoke.job_file; kind: "job" | "array"; task_count: number; queue: "zeus_combined_q"; cores_per_task: typeof canonicalStages.smoke.cores_per_task; memory_per_task_bytes: typeof canonicalStages.smoke.memory_per_task_bytes; walltime_seconds: typeof canonicalStages.smoke.walltime_seconds };
  remote: { host: "zeus.technion.ac.il"; project_directory: string; commit: string; branch: string; dirty: false };
  inputs: { verified_count: typeof canonicalDesign.prepared_file_count; status: "ready" };
  effects: { submit_smoke: true; submit_later_stages: false; modify_files: false };
  later_stages_locked: true;
};
export type SmokeSubmissionResult = {
  status: "submitted"; campaign_id: string; stage: "smoke"; job_id: string;
  submitted_at: string; later_stages_locked: true;
};
export function parseSmokeSubmissionPreview(value: Record<string, unknown>): SmokeSubmissionPreview {
  const campaign = value.campaign as Record<string, unknown>;
  const stage = value.stage as Record<string, unknown>;
  const job = value.job as Record<string, unknown>;
  const remote = value.remote as Record<string, unknown>;
  const inputs = value.inputs as Record<string, unknown>;
  const effects = value.effects as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "job", "remote", "inputs", "effects", "later_stages_locked"])
    || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "path", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !boundedPrintable(campaign.path, 1024) || !String(campaign.path).startsWith("data/optimization/mot_2d/") || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0)
    || !stage || !exactKeys(stage, ["id", "label", "purpose"]) || stage.id !== "smoke" || stage.label !== canonicalStages.smoke.label || !boundedPrintable(stage.purpose, 512)
    || !job || !reviewedJobKeys(job, ["file", "kind", "task_count", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || job.file !== canonicalStages.smoke.job_file || !["job", "array"].includes(String(job.kind)) || !Number.isInteger(job.task_count) || Number(job.task_count) < 1 || job.task_count !== campaign.s0_values.length || (job.task_count === 1 ? job.kind !== "job" : job.kind !== "array") || job.queue !== "zeus_combined_q" || job.cores_per_task !== canonicalStages.smoke.cores_per_task || job.memory_per_task_bytes !== canonicalStages.smoke.memory_per_task_bytes || job.walltime_seconds !== canonicalStages.smoke.walltime_seconds
    || !remote || !exactKeys(remote, ["host", "project_directory", "commit", "branch", "dirty"]) || remote.host !== "zeus.technion.ac.il" || !isCampaignProjectDirectory(remote.project_directory) || remote.commit !== campaign.git_commit || !boundedPrintable(remote.branch, 256) || remote.dirty !== false
    || !inputs || !exactKeys(inputs, ["verified_count", "status"]) || inputs.verified_count !== canonicalDesign.prepared_file_count || inputs.status !== "ready"
    || !effects || !exactKeys(effects, ["submit_smoke", "submit_later_stages", "modify_files"]) || effects.submit_smoke !== true || effects.submit_later_stages !== false || effects.modify_files !== false || value.later_stages_locked !== true) throw new Error("Invalid smoke submission preview response.");
  return value as unknown as SmokeSubmissionPreview;
}

export function parseSmokeSubmissionResult(value: Record<string, unknown>): SmokeSubmissionResult {
  if (!exactKeys(value, ["status", "campaign_id", "stage", "job_id", "submitted_at", "later_stages_locked"]) || value.status !== "submitted" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "smoke" || !text(value.job_id) || !/^\d+(?:\[\])?\.zeus-master$/.test(value.job_id) || !text(value.submitted_at) || Number.isNaN(Date.parse(value.submitted_at)) || value.later_stages_locked !== true) throw new Error("Invalid smoke submission result.");
  return value as unknown as SmokeSubmissionResult;
}


export type SmokePoint = { s0: number; captured: number; input: 2; efficiency: number };
export type SmokeLifecycle = {
  source: "zeus"; queried_at: string;
  campaign: { id: string; name: string; stage: "smoke" | "screen" };
  submission: { job_id: string };
  scheduler: { state: "queued" | "running" | "held_attention" | "completed_success" | "completed_failed" | "unknown"; raw_state: string; exit_status: number | null };
  validation: { status: "not_ready" | "valid" | "invalid"; points: SmokePoint[]; artifact_count: number };
  lifecycle: "queued" | "running" | "awaiting_outputs" | "held_attention" | "failed" | "outputs_invalid" | "ready_to_prepare_screen" | "screen_prepared" | "unknown";
  next_action: "wait" | "inspect_on_zeus" | "review_screening_preparation" | "none";
};
const screeningArtifacts = [canonicalStages.screen.artifacts[0], canonicalStages.screen.artifacts[1]] as const;
const screeningUpdates = [canonicalStages.screen.artifacts[2]] as const;
export type ScreeningPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; git_commit: string };
  from_stage: "smoke"; to_stage: "screen";
  smoke: { job_id: string; points: SmokePoint[]; artifact_count: number };
  artifacts: { create: typeof screeningArtifacts; update: typeof screeningUpdates };
  effects: { prepare_screening: true; submit_screening: false; start_simulation: false; overwrite_existing: false };
  local_sync: { status: "not_synchronized" };
};
export type ScreeningResult = {
  status: "screening_prepared"; campaign_id: string; stage: "screen";
  artifacts: { created: typeof screeningArtifacts.length; updated: typeof screeningUpdates.length };
  submitted_to_zeus: false; simulation_started: false;
  local_sync: { status: "not_synchronized" };
};
const smokeJobId = /^\d+(?:\[\])?\.zeus-master$/;
export function parseSmokePoint(value: unknown): SmokePoint {
  if (!value || typeof value !== "object") throw new Error("Invalid smoke lifecycle response.");
  const row = value as Record<string, unknown>;
  if (!exactKeys(row, ["s0", "captured", "input", "efficiency"]) || typeof row.s0 !== "number" || !Number.isFinite(row.s0) || row.s0 <= 0 || !Number.isInteger(row.captured) || !finiteNonnegative(row.captured) || row.input !== 2 || Number(row.captured) > 2 || typeof row.efficiency !== "number" || !Number.isFinite(row.efficiency) || row.efficiency < 0 || row.efficiency > 1 || Math.abs(row.efficiency - Number(row.captured) / 2) > 1e-12) throw new Error("Invalid smoke lifecycle response.");
  return row as unknown as SmokePoint;
}
export function parseSmokeLifecycle(value: Record<string, unknown>): SmokeLifecycle {
  const campaign = value.campaign as Record<string, unknown>;
  const submission = value.submission as Record<string, unknown>;
  const scheduler = value.scheduler as Record<string, unknown>;
  const validation = value.validation as Record<string, unknown>;
  if (!exactKeys(value, ["source", "queried_at", "campaign", "submission", "scheduler", "validation", "lifecycle", "next_action"]) || value.source !== "zeus" || !text(value.queried_at) || Number.isNaN(Date.parse(String(value.queried_at)))
    || !campaign || !exactKeys(campaign, ["id", "name", "stage"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !["smoke", "screen"].includes(String(campaign.stage))
    || !submission || !exactKeys(submission, ["job_id"]) || !text(submission.job_id) || !smokeJobId.test(submission.job_id)
    || !scheduler || !exactKeys(scheduler, ["state", "raw_state", "exit_status"]) || !["queued", "running", "held_attention", "completed_success", "completed_failed", "unknown"].includes(String(scheduler.state)) || !boundedPrintable(scheduler.raw_state, 8) || (scheduler.exit_status !== null && !Number.isInteger(scheduler.exit_status))
    || !validation || !exactKeys(validation, ["status", "points", "artifact_count"]) || !["not_ready", "valid", "invalid"].includes(String(validation.status)) || !Array.isArray(validation.points) || validation.points.length > 100 || !Number.isInteger(validation.artifact_count) || !finiteNonnegative(validation.artifact_count)
    || !["queued", "running", "awaiting_outputs", "held_attention", "failed", "outputs_invalid", "ready_to_prepare_screen", "screen_prepared", "unknown"].includes(String(value.lifecycle)) || !["wait", "inspect_on_zeus", "review_screening_preparation", "none"].includes(String(value.next_action))) throw new Error("Invalid smoke lifecycle response.");
  const points = validation.points.map(parseSmokePoint);
  const expected = {
    queued: ["queued", "not_ready", "wait", "smoke"], running: ["running", "not_ready", "wait", "smoke"], awaiting_outputs: ["completed_success", "not_ready", "wait", "smoke"], held_attention: ["held_attention", "not_ready", "inspect_on_zeus", "smoke"], failed: ["completed_failed", "not_ready", "inspect_on_zeus", "smoke"], outputs_invalid: ["completed_success", "invalid", "inspect_on_zeus", "smoke"], ready_to_prepare_screen: ["completed_success", "valid", "review_screening_preparation", "smoke"], screen_prepared: ["completed_success", "valid", "none", "screen"], unknown: ["unknown", "not_ready", "inspect_on_zeus", "smoke"],
  }[String(value.lifecycle)] as string[];
  if (scheduler.state !== expected[0] || validation.status !== expected[1] || value.next_action !== expected[2] || campaign.stage !== expected[3] || (validation.status === "valid" && (points.length === 0 || validation.artifact_count !== points.length * 3)) || (validation.status === "not_ready" && (points.length !== 0 || validation.artifact_count !== 0))) throw new Error("Inconsistent smoke lifecycle response.");
  return { ...(value as unknown as SmokeLifecycle), validation: { ...(validation as unknown as SmokeLifecycle["validation"]), points } };
}
export function parseScreeningPreview(value: Record<string, unknown>): ScreeningPreview {
  const campaign = value.campaign as Record<string, unknown>; const smoke = value.smoke as Record<string, unknown>; const artifacts = value.artifacts as Record<string, unknown>; const effects = value.effects as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "smoke", "artifacts", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "git_commit"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || value.from_stage !== "smoke" || value.to_stage !== "screen"
    || !smoke || !exactKeys(smoke, ["job_id", "points", "artifact_count"]) || !text(smoke.job_id) || !smokeJobId.test(smoke.job_id) || !Array.isArray(smoke.points) || smoke.points.length === 0 || smoke.points.length > 100 || !Number.isInteger(smoke.artifact_count) || smoke.artifact_count !== smoke.points.length * 3
    || !artifacts || !exactKeys(artifacts, ["create", "update"]) || JSON.stringify(artifacts.create) !== JSON.stringify(screeningArtifacts) || JSON.stringify(artifacts.update) !== JSON.stringify(screeningUpdates)
    || !effects || !exactKeys(effects, ["prepare_screening", "submit_screening", "start_simulation", "overwrite_existing"]) || effects.prepare_screening !== true || effects.submit_screening !== false || effects.start_simulation !== false || effects.overwrite_existing !== false
    || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid screening preparation preview response.");
  return { ...(value as unknown as ScreeningPreview), smoke: { ...(smoke as unknown as ScreeningPreview["smoke"]), points: smoke.points.map(parseSmokePoint) } };
}
export function parseScreeningResult(value: Record<string, unknown>): ScreeningResult {
  const artifacts = value.artifacts as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"]) || value.status !== "screening_prepared" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "screen" || !artifacts || !exactKeys(artifacts, ["created", "updated"]) || artifacts.created !== screeningArtifacts.length || artifacts.updated !== screeningUpdates.length || value.submitted_to_zeus !== false || value.simulation_started !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid screening preparation result.");
  return value as unknown as ScreeningResult;
}
export type ScreeningSubmissionPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; git_commit: string; s0_values: number[] };
  stage: { id: "screen"; label: typeof canonicalStages.screen.label; purpose: string };
  job: { file: typeof canonicalStages.screen.job_file; kind: "array"; task_count: number; array_throttle: typeof canonicalStages.screen.array_throttle; queue: "zeus_combined_q"; cores_per_task: typeof canonicalStages.screen.cores_per_task; memory_per_task_bytes: typeof canonicalStages.screen.memory_per_task_bytes; walltime_seconds: typeof canonicalStages.screen.walltime_seconds };
  remote: { host: "zeus.technion.ac.il"; project_directory: string; commit: string; branch: string; dirty: false };
  inputs: { verified_count: typeof canonicalDesign.prepared_file_count; status: "ready" };
  smoke: { status: "validated"; job_id: string; point_count: number };
  effects: { submit_screening: true; submit_later_stages: false; modify_files: false };
  later_stages_locked: true;
};
export type ScreeningSubmissionResult = { status: "submitted"; campaign_id: string; stage: "screen"; job_id: string; submitted_at: string; later_stages_locked: true };

export function parseScreeningSubmissionPreview(value: Record<string, unknown>): ScreeningSubmissionPreview {
  const campaign = value.campaign as Record<string, unknown>; const stage = value.stage as Record<string, unknown>; const job = value.job as Record<string, unknown>; const remote = value.remote as Record<string, unknown>; const inputs = value.inputs as Record<string, unknown>; const smoke = value.smoke as Record<string, unknown>; const effects = value.effects as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "job", "remote", "inputs", "smoke", "effects", "later_stages_locked"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0)
    || !stage || !exactKeys(stage, ["id", "label", "purpose"]) || stage.id !== "screen" || stage.label !== canonicalStages.screen.label || !boundedPrintable(stage.purpose, 512)
    || !job || !reviewedJobKeys(job, ["file", "kind", "task_count", "array_throttle", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || job.file !== canonicalStages.screen.job_file || job.kind !== "array" || !Number.isInteger(job.task_count) || job.task_count !== campaign.s0_values.length * canonicalDesign.workers_per_s0 || job.array_throttle !== canonicalStages.screen.array_throttle || job.queue !== "zeus_combined_q" || job.cores_per_task !== canonicalStages.screen.cores_per_task || job.memory_per_task_bytes !== canonicalStages.screen.memory_per_task_bytes || job.walltime_seconds !== canonicalStages.screen.walltime_seconds
    || !remote || !exactKeys(remote, ["host", "project_directory", "commit", "branch", "dirty"]) || remote.host !== "zeus.technion.ac.il" || !isCampaignProjectDirectory(remote.project_directory) || remote.commit !== campaign.git_commit || !boundedPrintable(remote.branch, 256) || remote.dirty !== false
    || !inputs || !exactKeys(inputs, ["verified_count", "status"]) || inputs.verified_count !== canonicalDesign.prepared_file_count || inputs.status !== "ready"
    || !smoke || !exactKeys(smoke, ["status", "job_id", "point_count"]) || smoke.status !== "validated" || !text(smoke.job_id) || !smokeJobId.test(smoke.job_id) || !Number.isInteger(smoke.point_count) || smoke.point_count !== campaign.s0_values.length
    || !effects || !exactKeys(effects, ["submit_screening", "submit_later_stages", "modify_files"]) || effects.submit_screening !== true || effects.submit_later_stages !== false || effects.modify_files !== false || value.later_stages_locked !== true) throw new Error("Invalid Screening submission preview response.");
  return value as unknown as ScreeningSubmissionPreview;
}
export function parseScreeningSubmissionResult(value: Record<string, unknown>): ScreeningSubmissionResult {
  if (!exactKeys(value, ["status", "campaign_id", "stage", "job_id", "submitted_at", "later_stages_locked"]) || value.status !== "submitted" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "screen" || !text(value.job_id) || !/^\d+\[\]\.zeus-master$/.test(value.job_id) || !validUtc(value.submitted_at) || value.later_stages_locked !== true) throw new Error("Invalid Screening submission result.");
  return value as unknown as ScreeningSubmissionResult;
}

export type ScreeningLifecycle = {
  source: "zeus"; queried_at: string;
  campaign: { id: string; name: string; stage: "screen" | "refine" };
  submission: { job_id: string };
  scheduler: { state: "queued" | "running" | "held" | "completed_success" | "completed_failed" | "unknown"; raw_state: string; exit_status: number | null; task_count: number; counts: { queued: number; running: number; held: number; succeeded: number; failed: number } };
  validation: { status: "not_ready" | "valid" | "invalid"; completed_trials: number; expected_trials: number; candidate_count: number };
  lifecycle: "screen_queued" | "screen_running" | "screen_held" | "screen_failed" | "screen_status_unknown" | "awaiting_outputs" | "outputs_invalid" | "ready_to_prepare_refinement" | "refinement_prepared";
  next_action: "wait" | "inspect_zeus" | "review_refinement_preparation" | "none";
};
export type RefinementCandidate = { s0: number; rank: number; detuning_gamma: number; magnet_radius_m: number; mean_conditional_efficiency: number; source: string };
export type RefinementPreview = { preview_token: string; expires_in_seconds: number; campaign: { id: string; name: string; git_commit: string; s0_values: number[] }; from_stage: "screen"; to_stage: "refine"; bounds: { detuning_gamma: { low: number; high: number }; magnet_radius_m: { low: number; high: number } }; screening: { job_id: string; completed_trials: number; expected_trials: number; candidates: RefinementCandidate[] }; artifacts: { create: typeof refinementArtifacts; update: typeof refinementUpdates }; effects: { prepare_refinement: true; submit_refinement: false; start_simulation: false; overwrite_existing: false }; local_sync: { status: "not_synchronized" } };
export type RefinementResult = { status: "refinement_prepared"; campaign_id: string; stage: "refine"; artifacts: { created: typeof refinementArtifacts.length; updated: typeof refinementUpdates.length }; submitted_to_zeus: false; simulation_started: false; local_sync: { status: "not_synchronized" } };
const refinementArtifacts = [canonicalStages.refine.artifacts[0], canonicalStages.refine.artifacts[1], canonicalStages.refine.artifacts[2], canonicalStages.refine.artifacts[3], canonicalStages.refine.artifacts[4], canonicalStages.refine.artifacts[5], canonicalStages.refine.artifacts[6]] as const;
const refinementUpdates = [canonicalStages.refine.artifacts[7]] as const;
export function parseScreeningLifecycle(value: Record<string, unknown>): ScreeningLifecycle {
  const campaign = value.campaign as Record<string, unknown>; const submission = value.submission as Record<string, unknown>; const scheduler = value.scheduler as Record<string, unknown>; const counts = scheduler?.counts as Record<string, unknown>; const validation = value.validation as Record<string, unknown>;
  if (!exactKeys(value, ["source", "queried_at", "campaign", "submission", "scheduler", "validation", "lifecycle", "next_action"]) || value.source !== "zeus" || !text(value.queried_at) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value.queried_at) || Number.isNaN(Date.parse(value.queried_at))
    || !campaign || !exactKeys(campaign, ["id", "name", "stage"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !["screen", "refine"].includes(String(campaign.stage))
    || !submission || !exactKeys(submission, ["job_id"]) || !text(submission.job_id) || !/^\d+\[\]\.zeus-master$/.test(submission.job_id)
    || !scheduler || !exactKeys(scheduler, ["state", "raw_state", "exit_status", "task_count", "counts"]) || !["queued", "running", "held", "completed_success", "completed_failed", "unknown"].includes(String(scheduler.state)) || !boundedPrintable(scheduler.raw_state, 16) || (scheduler.exit_status !== null && !Number.isInteger(scheduler.exit_status)) || !Number.isInteger(scheduler.task_count) || Number(scheduler.task_count) <= 0
    || !counts || !exactKeys(counts, ["queued", "running", "held", "succeeded", "failed"]) || !Object.values(counts).every((item) => Number.isInteger(item) && Number(item) >= 0) || Object.values(counts).reduce<number>((sum, item) => sum + Number(item), 0) !== scheduler.task_count
    || !validation || !exactKeys(validation, ["status", "completed_trials", "expected_trials", "candidate_count"]) || !["not_ready", "valid", "invalid"].includes(String(validation.status)) || ![validation.completed_trials, validation.expected_trials, validation.candidate_count].every((item) => Number.isInteger(item) && Number(item) >= 0)
    || !["screen_queued", "screen_running", "screen_held", "screen_failed", "screen_status_unknown", "awaiting_outputs", "outputs_invalid", "ready_to_prepare_refinement", "refinement_prepared"].includes(String(value.lifecycle)) || !["wait", "inspect_zeus", "review_refinement_preparation", "none"].includes(String(value.next_action))) throw new Error("Invalid Screening lifecycle response.");
  const expected = { screen_queued: ["queued", "not_ready", "wait", "screen"], screen_running: ["running", "not_ready", "wait", "screen"], screen_held: ["held", "not_ready", "inspect_zeus", "screen"], screen_failed: ["completed_failed", "not_ready", "inspect_zeus", "screen"], screen_status_unknown: ["unknown", "not_ready", "inspect_zeus", "screen"], awaiting_outputs: ["completed_success", "not_ready", "wait", "screen"], outputs_invalid: ["completed_success", "invalid", "inspect_zeus", "screen"], ready_to_prepare_refinement: ["completed_success", "valid", "review_refinement_preparation", "screen"], refinement_prepared: ["completed_success", "valid", "none", "refine"] }[String(value.lifecycle)] as string[];
  const valid = validation.status === "valid"; const s0Count = Number(scheduler.task_count) / canonicalDesign.workers_per_s0;
  const numericCounts = counts as { queued: number; running: number; held: number; succeeded: number; failed: number };
  const completedCleanly = numericCounts.succeeded === scheduler.task_count && numericCounts.queued === 0 && numericCounts.running === 0 && numericCounts.held === 0 && numericCounts.failed === 0;
  if (scheduler.state !== expected[0] || validation.status !== expected[1] || value.next_action !== expected[2] || campaign.stage !== expected[3] || !Number.isInteger(s0Count) || validation.expected_trials !== s0Count * canonicalDesign.workers_per_s0 * canonicalDesign.screen_trials_per_worker || (valid && (validation.completed_trials !== validation.expected_trials || validation.candidate_count !== scheduler.task_count)) || (!valid && (validation.completed_trials !== 0 || validation.candidate_count !== 0)) || (scheduler.state === "completed_success" && !completedCleanly) || (scheduler.state === "completed_failed" && numericCounts.failed === 0) || (scheduler.state === "running" && numericCounts.running === 0) || (scheduler.state === "held" && numericCounts.held === 0) || (scheduler.state === "queued" && numericCounts.queued === 0)) throw new Error("Inconsistent Screening lifecycle response.");
  return value as unknown as ScreeningLifecycle;
}
export function parseRefinementPreview(value: Record<string, unknown>): RefinementPreview {
  const campaign = value.campaign as Record<string, unknown>; const bounds = value.bounds as Record<string, Record<string, unknown>>; const screening = value.screening as Record<string, unknown>; const artifacts = value.artifacts as Record<string, unknown>; const effects = value.effects as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "bounds", "screening", "artifacts", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0
    || !campaign || !exactKeys(campaign, ["id", "name", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0) || new Set(campaign.s0_values).size !== campaign.s0_values.length || value.from_stage !== "screen" || value.to_stage !== "refine"
    || !bounds || !exactKeys(bounds, ["detuning_gamma", "magnet_radius_m"]) || !bounds.detuning_gamma || !exactKeys(bounds.detuning_gamma, ["low", "high"]) || !bounds.magnet_radius_m || !exactKeys(bounds.magnet_radius_m, ["low", "high"]) || ![bounds.detuning_gamma.low, bounds.detuning_gamma.high, bounds.magnet_radius_m.low, bounds.magnet_radius_m.high].every((item) => typeof item === "number" && Number.isFinite(item)) || Number(bounds.detuning_gamma.low) >= Number(bounds.detuning_gamma.high) || Number(bounds.magnet_radius_m.low) <= 0 || Number(bounds.magnet_radius_m.low) >= Number(bounds.magnet_radius_m.high)
    || !screening || !exactKeys(screening, ["job_id", "completed_trials", "expected_trials", "candidates"]) || !text(screening.job_id) || !/^\d+\[\]\.zeus-master$/.test(screening.job_id) || screening.expected_trials !== campaign.s0_values.length * canonicalDesign.workers_per_s0 * canonicalDesign.screen_trials_per_worker || screening.completed_trials !== screening.expected_trials || !Array.isArray(screening.candidates) || screening.candidates.length !== campaign.s0_values.length * canonicalDesign.screen_candidates_per_s0
    || !artifacts || !exactKeys(artifacts, ["create", "update"]) || JSON.stringify(artifacts.create) !== JSON.stringify(refinementArtifacts) || JSON.stringify(artifacts.update) !== JSON.stringify(refinementUpdates)
    || !effects || !exactKeys(effects, ["prepare_refinement", "submit_refinement", "start_simulation", "overwrite_existing"]) || effects.prepare_refinement !== true || effects.submit_refinement !== false || effects.start_simulation !== false || effects.overwrite_existing !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement preparation preview response.");
  const candidates = screening.candidates as Record<string, unknown>[]; const sources = new Set<string>(); const cells = new Set<string>();
  for (const row of candidates) { if (!row || !exactKeys(row, ["s0", "rank", "detuning_gamma", "magnet_radius_m", "mean_conditional_efficiency", "source"]) || typeof row.s0 !== "number" || !campaign.s0_values.includes(row.s0) || !canonicalRanks(canonicalDesign.screen_candidates_per_s0).includes(Number(row.rank)) || ![row.detuning_gamma, row.magnet_radius_m, row.mean_conditional_efficiency].every((item) => typeof item === "number" && Number.isFinite(item)) || Number(row.detuning_gamma) < Number(bounds.detuning_gamma.low) || Number(row.detuning_gamma) > Number(bounds.detuning_gamma.high) || Number(row.magnet_radius_m) < Number(bounds.magnet_radius_m.low) || Number(row.magnet_radius_m) > Number(bounds.magnet_radius_m.high) || Number(row.mean_conditional_efficiency) < 0 || Number(row.mean_conditional_efficiency) > 1 || !canonicalWorkerSource(row.source, "screen") || sources.has(row.source)) throw new Error("Invalid Refinement candidate response."); const cell = `${row.s0}:${roundTiesToEven(Number(row.detuning_gamma) / 0.01)}:${roundTiesToEven(Number(row.magnet_radius_m) / 0.00001)}`; if (cells.has(cell)) throw new Error("Duplicate Refinement candidate cell."); sources.add(row.source); cells.add(cell); }
  for (const s0 of campaign.s0_values as number[]) if (JSON.stringify(candidates.filter((row) => row.s0 === s0).map((row) => row.rank).sort()) !== JSON.stringify(canonicalRanks(canonicalDesign.screen_candidates_per_s0))) throw new Error("Invalid Refinement candidate ranks.");
  return value as unknown as RefinementPreview;
}
export function parseRefinementResult(value: Record<string, unknown>): RefinementResult { const artifacts = value.artifacts as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>; if (!exactKeys(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"]) || value.status !== "refinement_prepared" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "refine" || !artifacts || !exactKeys(artifacts, ["created", "updated"]) || artifacts.created !== refinementArtifacts.length || artifacts.updated !== refinementUpdates.length || value.submitted_to_zeus !== false || value.simulation_started !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement preparation result."); return value as unknown as RefinementResult; }

export type RefinementChainRound = { round: 1 | 2 | 3 | 4; state: "not_submitted" | "pending" | "submitted" | "unknown"; job_id: string | null; depends_on_job_id: string | null };
export type RefinementChainStatus = { source: "zeus"; queried_at: string; campaign: { id: string; name: string; stage: "refine" }; chain: { status: "not_submitted" | "submitting" | "submitted" | "partial" | "outcome_unknown"; dependency: typeof canonicalStages.refine.dependency; rounds: RefinementChainRound[] }; next_action: "review_submission" | "wait" | "none" | "inspect_zeus"; local_sync: { status: "not_synchronized" } };
export type RefinementSubmissionPreview = { preview_token: string; expires_in_seconds: number; campaign: { id: string; name: string; git_commit: string; s0_values: number[] }; stage: { id: "refine"; label: typeof canonicalStages.refine.label }; chain: { dependency: typeof canonicalStages.refine.dependency; rounds: Array<{ round: 1 | 2 | 3 | 4; file: typeof canonicalStages.refine.round_job_files[number]; cumulative_target: typeof canonicalStages.refine.cumulative_trial_targets[number]; kind: "array"; task_count: number; array_throttle: typeof canonicalStages.refine.array_throttle; queue: "zeus_combined_q"; cores_per_task: typeof canonicalStages.refine.cores_per_task; memory_per_task_bytes: typeof canonicalStages.refine.memory_per_task_bytes; walltime_seconds: typeof canonicalStages.refine.walltime_seconds; depends_on: null | number }> }; remote: { host: "zeus.technion.ac.il"; project_directory: string; commit: string; branch: string; dirty: false }; effects: { submit_refinement_chain: true; start_simulation: true; submit_later_stages: false; modify_files: false }; local_sync: { status: "not_synchronized" } };
export type RefinementSubmissionResult = { status: "submitted"; campaign_id: string; stage: "refine"; chain: { status: "submitted"; rounds: Array<{ round: 1 | 2 | 3 | 4; job_id: string; depends_on_job_id: string | null }> }; submitted_at: string; local_sync: { status: "not_synchronized" } };
const canonicalArrayJob = /^\d+\[\]\.zeus-master$/;
export function parseChainRounds(value: unknown): RefinementChainRound[] { if (!Array.isArray(value) || value.length !== 4) throw new Error("Invalid Refinement chain rounds."); const rounds = value as Record<string, unknown>[]; const ids = new Set<string>(); let previousId: string | null = null; let prefixOpen = true; let uncertainSeen = false; rounds.forEach((row, index) => { if (!row || !exactKeys(row, ["round", "state", "job_id", "depends_on_job_id"]) || row.round !== index + 1 || !["not_submitted", "pending", "submitted", "unknown"].includes(String(row.state)) || (row.job_id !== null && (!text(row.job_id) || !canonicalArrayJob.test(row.job_id))) || (row.depends_on_job_id !== null && (!text(row.depends_on_job_id) || !canonicalArrayJob.test(row.depends_on_job_id)))) throw new Error("Invalid Refinement chain round."); if (row.state === "submitted") { if (!prefixOpen || uncertainSeen || row.job_id === null || ids.has(String(row.job_id)) || row.depends_on_job_id !== (index === 0 ? null : previousId)) throw new Error("Invalid Refinement submitted prefix."); ids.add(String(row.job_id)); previousId = String(row.job_id); return; } prefixOpen = false; if (["pending", "unknown"].includes(String(row.state))) { if (uncertainSeen || row.depends_on_job_id !== (index === 0 ? null : previousId) || (row.job_id !== null && ids.has(String(row.job_id)))) throw new Error("Invalid Refinement uncertain round."); uncertainSeen = true; if (row.job_id !== null) ids.add(String(row.job_id)); return; } if (row.job_id !== null || row.depends_on_job_id !== null) throw new Error("Invalid unsubmitted Refinement round."); }); return value as RefinementChainRound[]; }
export function parseRefinementChainStatus(value: Record<string, unknown>): RefinementChainStatus { const campaign = value.campaign as Record<string, unknown>; const chain = value.chain as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>; if (!exactKeys(value, ["source", "queried_at", "campaign", "chain", "next_action", "local_sync"]) || value.source !== "zeus" || !validUtc(value.queried_at) || !campaign || !exactKeys(campaign, ["id", "name", "stage"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || campaign.stage !== "refine" || !chain || !exactKeys(chain, ["status", "dependency", "rounds"]) || !["not_submitted", "submitting", "submitted", "partial", "outcome_unknown"].includes(String(chain.status)) || chain.dependency !== "afterok" || !["review_submission", "wait", "none", "inspect_zeus"].includes(String(value.next_action)) || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement chain status."); const rounds = parseChainRounds(chain.rounds); const uncertain = rounds.some((row) => ["pending", "unknown"].includes(row.state)); const allSubmitted = rounds.every((row) => row.state === "submitted"); const expectedAction = { not_submitted: "review_submission", submitting: "wait", submitted: "none", partial: "inspect_zeus", outcome_unknown: "inspect_zeus" }[String(chain.status)]; if (value.next_action !== expectedAction || (chain.status === "not_submitted" && rounds.some((row) => row.state !== "not_submitted")) || (chain.status === "submitting" && !uncertain) || (chain.status === "submitted" && !allSubmitted) || (chain.status === "partial" && (uncertain || !rounds.some((row) => row.state === "submitted") || allSubmitted)) || (chain.status === "outcome_unknown" && !uncertain && !allSubmitted)) throw new Error("Inconsistent Refinement chain status."); return { ...(value as unknown as RefinementChainStatus), chain: { ...(chain as unknown as RefinementChainStatus["chain"]), rounds } }; }
export function parseRefinementSubmissionPreview(value: Record<string, unknown>): RefinementSubmissionPreview { const campaign = value.campaign as Record<string, unknown>; const stage = value.stage as Record<string, unknown>; const chain = value.chain as Record<string, unknown>; const remote = value.remote as Record<string, unknown>; const effects = value.effects as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>; if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "chain", "remote", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !campaign || !exactKeys(campaign, ["id", "name", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0) || new Set(campaign.s0_values).size !== campaign.s0_values.length || !stage || !exactKeys(stage, ["id", "label"]) || stage.id !== "refine" || stage.label !== canonicalStages.refine.label || !chain || !exactKeys(chain, ["dependency", "rounds"]) || chain.dependency !== canonicalStages.refine.dependency || !Array.isArray(chain.rounds) || chain.rounds.length !== canonicalStages.refine.round_job_files.length || !remote || !exactKeys(remote, ["host", "project_directory", "commit", "branch", "dirty"]) || remote.host !== "zeus.technion.ac.il" || !isCampaignProjectDirectory(remote.project_directory) || remote.commit !== campaign.git_commit || !boundedPrintable(remote.branch, 256) || remote.dirty !== false || !effects || !exactKeys(effects, ["submit_refinement_chain", "start_simulation", "submit_later_stages", "modify_files"]) || effects.submit_refinement_chain !== true || effects.start_simulation !== true || effects.submit_later_stages !== false || effects.modify_files !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement submission preview."); const s0Values = campaign.s0_values as number[]; (chain.rounds as Record<string, unknown>[]).forEach((row, index) => { if (!reviewedJobKeys(row, ["round", "file", "cumulative_target", "kind", "task_count", "array_throttle", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds", "depends_on"]) || row.round !== index + 1 || row.file !== canonicalStages.refine.round_job_files[index] || row.cumulative_target !== canonicalStages.refine.cumulative_trial_targets[index] || row.kind !== "array" || row.task_count !== s0Values.length * canonicalDesign.workers_per_s0 || row.array_throttle !== canonicalStages.refine.array_throttle || row.queue !== "zeus_combined_q" || row.cores_per_task !== canonicalStages.refine.cores_per_task || row.memory_per_task_bytes !== canonicalStages.refine.memory_per_task_bytes || row.walltime_seconds !== canonicalStages.refine.walltime_seconds || row.depends_on !== (index === 0 ? null : index)) throw new Error("Invalid Refinement submission round."); }); return value as unknown as RefinementSubmissionPreview; }
export function parseRefinementSubmissionResult(value: Record<string, unknown>): RefinementSubmissionResult { const chain = value.chain as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>; if (!exactKeys(value, ["status", "campaign_id", "stage", "chain", "submitted_at", "local_sync"]) || value.status !== "submitted" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "refine" || !chain || !exactKeys(chain, ["status", "rounds"]) || chain.status !== "submitted" || !validUtc(value.submitted_at) || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement submission result."); const rounds = parseChainRounds((chain.rounds as Record<string, unknown>[]).map((row) => ({ ...row, state: "submitted" }))); return { ...(value as unknown as RefinementSubmissionResult), chain: { status: "submitted", rounds: rounds.map(({ round, job_id, depends_on_job_id }) => ({ round, job_id: job_id as string, depends_on_job_id })) } }; }

export type RefinementRoundLifecycle = { round: 1 | 2 | 3 | 4; job_id: string; depends_on_job_id: string | null; scheduler: { state: "queued" | "running" | "held" | "completed_success" | "completed_failed" | "unknown"; task_count: number; counts: { queued: number; running: number; held: number; succeeded: number; failed: number } } };
export type RefinementLifecycle = { source: "zeus"; queried_at: string; campaign: { id: string; name: string; stage: "refine" | "confirmation" }; chain: { status: "queued" | "running" | "held" | "failed" | "status_unknown" | "awaiting_outputs" | "outputs_invalid" | "ready_to_prepare_confirmation" | "confirmation_prepared"; rounds: RefinementRoundLifecycle[] }; validation: { status: "not_ready" | "invalid" | "valid"; completed_trials: number; expected_trials: number; candidate_count: number }; next_action: "wait" | "inspect_zeus" | "review_confirmation_preparation" | "none"; local_sync: { status: "not_synchronized" } };
export type ConfirmationCandidate = { s0: number; rank: number; detuning_gamma: number; magnet_radius_m: number; mean_conditional_efficiency: number; source: string };
export type ConfirmationPreview = { preview_token: string; expires_in_seconds: number; campaign: { id: string; name: string; git_commit: string; s0_values: number[] }; from_stage: "refine"; to_stage: "confirmation"; bounds: { detuning_gamma: { low: number; high: number }; magnet_radius_m: { low: number; high: number } }; refinement: { round_job_ids: readonly string[]; completed_trials: number; expected_trials: number; candidates: ConfirmationCandidate[] }; artifacts: { create: typeof confirmationArtifacts; update: typeof confirmationUpdates }; job: { file: typeof canonicalStages.confirmation.job_file; kind: "array"; task_count: number; array_throttle: typeof canonicalStages.confirmation.array_throttle; queue: "zeus_combined_q"; cores_per_task: typeof canonicalStages.confirmation.cores_per_task; memory_per_task_bytes: typeof canonicalStages.confirmation.memory_per_task_bytes; walltime_seconds: typeof canonicalStages.confirmation.walltime_seconds }; effects: { prepare_confirmation: true; submit_confirmation: false; start_simulation: false; overwrite_existing: false }; local_sync: { status: "not_synchronized" } };
export type ConfirmationResult = { status: "confirmation_prepared"; campaign_id: string; stage: "confirmation"; artifacts: { created: typeof confirmationArtifacts.length; updated: typeof confirmationUpdates.length }; submitted_to_zeus: false; simulation_started: false; local_sync: { status: "not_synchronized" } };
export function parseRefinementLifecycle(value: Record<string, unknown>): RefinementLifecycle {
  const campaign = value.campaign as Record<string, unknown>; const chain = value.chain as Record<string, unknown>; const validation = value.validation as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["source", "queried_at", "campaign", "chain", "validation", "next_action", "local_sync"]) || value.source !== "zeus" || !validUtc(value.queried_at) || !campaign || !exactKeys(campaign, ["id", "name", "stage"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !["refine", "confirmation"].includes(String(campaign.stage)) || !chain || !exactKeys(chain, ["status", "rounds"]) || !["queued", "running", "held", "failed", "status_unknown", "awaiting_outputs", "outputs_invalid", "ready_to_prepare_confirmation", "confirmation_prepared"].includes(String(chain.status)) || !Array.isArray(chain.rounds) || chain.rounds.length !== canonicalStages.refine.round_job_files.length || !validation || !exactKeys(validation, ["status", "completed_trials", "expected_trials", "candidate_count"]) || !["not_ready", "invalid", "valid"].includes(String(validation.status)) || ![validation.completed_trials, validation.expected_trials, validation.candidate_count].every((item) => Number.isInteger(item) && Number(item) >= 0) || !["wait", "inspect_zeus", "review_confirmation_preparation", "none"].includes(String(value.next_action)) || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Refinement lifecycle response.");
  const rounds = chain.rounds as Record<string, unknown>[]; const ids = new Set<string>(); let previous: string | null = null; let s0Count: number | null = null; let nonterminalSeen = false;
  rounds.forEach((row, index) => { const scheduler = row.scheduler as Record<string, unknown>; const counts = scheduler?.counts as Record<string, unknown>; if (!row || !exactKeys(row, ["round", "job_id", "depends_on_job_id", "scheduler"]) || row.round !== index + 1 || !text(row.job_id) || !canonicalArrayJob.test(row.job_id) || ids.has(row.job_id) || row.depends_on_job_id !== (index === 0 ? null : previous) || !scheduler || !exactKeys(scheduler, ["state", "task_count", "counts"]) || !["queued", "running", "held", "completed_success", "completed_failed", "unknown"].includes(String(scheduler.state)) || !Number.isInteger(scheduler.task_count) || Number(scheduler.task_count) <= 0 || !counts || !exactKeys(counts, ["queued", "running", "held", "succeeded", "failed"]) || !Object.values(counts).every((item) => Number.isInteger(item) && Number(item) >= 0) || Object.values(counts).reduce<number>((sum, item) => sum + Number(item), 0) !== scheduler.task_count) throw new Error("Invalid Refinement round lifecycle."); const numeric = counts as { queued:number; running:number; held:number; succeeded:number; failed:number }; const clean = numeric.succeeded === scheduler.task_count && numeric.queued + numeric.running + numeric.held + numeric.failed === 0; if ((scheduler.state === "completed_success" && !clean) || (scheduler.state === "completed_failed" && numeric.failed === 0) || (scheduler.state === "running" && numeric.running === 0) || (scheduler.state === "held" && numeric.held === 0) || (scheduler.state === "queued" && numeric.queued === 0)) throw new Error("Inconsistent Refinement scheduler counts."); if (nonterminalSeen && scheduler.state !== "queued") throw new Error("Invalid Refinement dependency ordering."); if (scheduler.state !== "completed_success") nonterminalSeen = true; ids.add(row.job_id); previous = row.job_id; const count = Number(scheduler.task_count) / canonicalDesign.workers_per_s0; if (!Number.isInteger(count) || (s0Count !== null && count !== s0Count)) throw new Error("Invalid Refinement task count."); s0Count = count; });
  const expected = Number(s0Count) * canonicalDesign.workers_per_s0 * canonicalDesign.refine_trials_per_worker; const status = String(chain.status); const expectedAction = ["queued", "running", "awaiting_outputs"].includes(status) ? "wait" : ["held", "failed", "status_unknown", "outputs_invalid"].includes(status) ? "inspect_zeus" : status === "ready_to_prepare_confirmation" ? "review_confirmation_preparation" : "none"; const valid = validation.status === "valid"; if (validation.expected_trials !== expected || value.next_action !== expectedAction || campaign.stage !== (status === "confirmation_prepared" ? "confirmation" : "refine") || (valid && (validation.completed_trials !== expected || validation.candidate_count !== Number(s0Count) * canonicalDesign.confirmation_candidates_per_s0)) || (!valid && (validation.completed_trials !== 0 || validation.candidate_count !== 0)) || (["ready_to_prepare_confirmation", "confirmation_prepared"].includes(status) && !rounds.every((row) => (row.scheduler as Record<string, unknown>).state === "completed_success")) || (status === "outputs_invalid" && validation.status !== "invalid") || (["awaiting_outputs", "queued", "running", "held", "failed", "status_unknown"].includes(status) && validation.status !== "not_ready")) throw new Error("Inconsistent Refinement lifecycle response.");
  return value as unknown as RefinementLifecycle;
}
const confirmationArtifacts = [canonicalStages.confirmation.artifacts[0], canonicalStages.confirmation.artifacts[1], canonicalStages.confirmation.artifacts[2]] as const;
const confirmationUpdates = [canonicalStages.confirmation.artifacts[3]] as const;
export function parseConfirmationPreview(value: Record<string, unknown>): ConfirmationPreview {
  const campaign = value.campaign as Record<string, unknown>; const bounds = value.bounds as Record<string, Record<string, unknown>>; const refinement = value.refinement as Record<string, unknown>; const artifacts = value.artifacts as Record<string, unknown>; const job = value.job as Record<string, unknown>; const effects = value.effects as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "bounds", "refinement", "artifacts", "job", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !campaign || !exactKeys(campaign, ["id", "name", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0) || new Set(campaign.s0_values).size !== campaign.s0_values.length || value.from_stage !== "refine" || value.to_stage !== "confirmation" || !bounds || !exactKeys(bounds, ["detuning_gamma", "magnet_radius_m"]) || !bounds.detuning_gamma || !exactKeys(bounds.detuning_gamma, ["low", "high"]) || !bounds.magnet_radius_m || !exactKeys(bounds.magnet_radius_m, ["low", "high"]) || ![bounds.detuning_gamma.low, bounds.detuning_gamma.high, bounds.magnet_radius_m.low, bounds.magnet_radius_m.high].every((item) => typeof item === "number" && Number.isFinite(item)) || Number(bounds.detuning_gamma.low) >= Number(bounds.detuning_gamma.high) || Number(bounds.magnet_radius_m.low) <= 0 || Number(bounds.magnet_radius_m.low) >= Number(bounds.magnet_radius_m.high) || !refinement || !exactKeys(refinement, ["round_job_ids", "completed_trials", "expected_trials", "candidates"]) || !Array.isArray(refinement.round_job_ids) || refinement.round_job_ids.length !== canonicalStages.refine.round_job_files.length || !refinement.round_job_ids.every((id) => text(id) && canonicalArrayJob.test(id)) || new Set(refinement.round_job_ids).size !== canonicalStages.refine.round_job_files.length || refinement.expected_trials !== campaign.s0_values.length * canonicalDesign.workers_per_s0 * canonicalDesign.refine_trials_per_worker || refinement.completed_trials !== refinement.expected_trials || !Array.isArray(refinement.candidates) || refinement.candidates.length !== campaign.s0_values.length * canonicalDesign.confirmation_candidates_per_s0 || !artifacts || !exactKeys(artifacts, ["create", "update"]) || JSON.stringify(artifacts.create) !== JSON.stringify(confirmationArtifacts) || JSON.stringify(artifacts.update) !== JSON.stringify(confirmationUpdates) || !job || !reviewedJobKeys(job, ["file", "kind", "task_count", "array_throttle", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || job.file !== canonicalStages.confirmation.job_file || job.kind !== "array" || job.task_count !== campaign.s0_values.length * canonicalDesign.confirmation_candidates_per_s0 || job.array_throttle !== canonicalStages.confirmation.array_throttle || job.queue !== "zeus_combined_q" || job.cores_per_task !== canonicalStages.confirmation.cores_per_task || job.memory_per_task_bytes !== canonicalStages.confirmation.memory_per_task_bytes || job.walltime_seconds !== canonicalStages.confirmation.walltime_seconds || !effects || !exactKeys(effects, ["prepare_confirmation", "submit_confirmation", "start_simulation", "overwrite_existing"]) || effects.prepare_confirmation !== true || effects.submit_confirmation !== false || effects.start_simulation !== false || effects.overwrite_existing !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Confirmation preparation preview.");
  const candidates = refinement.candidates as Record<string, unknown>[]; const sources = new Set<string>(); const cells = new Set<string>(); const ranks = canonicalRanks(canonicalDesign.confirmation_candidates_per_s0); for (const row of candidates) { if (!row || !exactKeys(row, ["s0", "rank", "detuning_gamma", "magnet_radius_m", "mean_conditional_efficiency", "source"]) || typeof row.s0 !== "number" || !campaign.s0_values.includes(row.s0) || !ranks.includes(Number(row.rank)) || ![row.detuning_gamma,row.magnet_radius_m,row.mean_conditional_efficiency].every((item) => typeof item === "number" && Number.isFinite(item)) || Number(row.detuning_gamma) < Number(bounds.detuning_gamma.low) || Number(row.detuning_gamma) > Number(bounds.detuning_gamma.high) || Number(row.magnet_radius_m) < Number(bounds.magnet_radius_m.low) || Number(row.magnet_radius_m) > Number(bounds.magnet_radius_m.high) || Number(row.mean_conditional_efficiency) < 0 || Number(row.mean_conditional_efficiency) > 1 || !canonicalWorkerSource(row.source, "refine") || sources.has(row.source)) throw new Error("Invalid Confirmation candidate."); const cell = `${row.s0}:${roundTiesToEven(Number(row.detuning_gamma)/0.01)}:${roundTiesToEven(Number(row.magnet_radius_m)/0.00001)}`; if (cells.has(cell)) throw new Error("Duplicate Confirmation candidate cell."); sources.add(row.source); cells.add(cell); } for (const s0 of campaign.s0_values as number[]) if (JSON.stringify(candidates.filter((row) => row.s0 === s0).map((row) => row.rank).sort()) !== JSON.stringify(ranks)) throw new Error("Invalid Confirmation candidate ranks.");
  return value as unknown as ConfirmationPreview;
}
export function parseConfirmationResult(value: Record<string, unknown>): ConfirmationResult { const artifacts=value.artifacts as Record<string,unknown>; const sync=value.local_sync as Record<string,unknown>; if (!exactKeys(value,["status","campaign_id","stage","artifacts","submitted_to_zeus","simulation_started","local_sync"]) || value.status !== "confirmation_prepared" || !boundedPrintable(value.campaign_id,512) || value.stage !== "confirmation" || !artifacts || !exactKeys(artifacts,["created","updated"]) || artifacts.created !== confirmationArtifacts.length || artifacts.updated !== confirmationUpdates.length || value.submitted_to_zeus !== false || value.simulation_started !== false || !sync || !exactKeys(sync,["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid Confirmation preparation result."); return value as unknown as ConfirmationResult; }

export type ConfirmationSubmissionStatus={source:"zeus";queried_at:string;campaign:{id:string;name:string;stage:"confirmation"};submission:{status:"not_submitted"|"queued"|"running"|"held"|"completed_success"|"completed_failed"|"status_unknown"|"outcome_unknown";job_id:string|null};next_action:"review_submission"|"inspect_zeus"|"wait"|"validate_outputs";local_sync:{status:"not_synchronized"}};
export type ConfirmationSubmissionPreview={preview_token:string;expires_in_seconds:number;campaign:{id:string;name:string;git_commit:string;s0_values:number[]};stage:{id:"confirmation";label:"Confirmation"};job:{file:"jobs/04_confirmation.pbs";kind:"array";task_count:number;array_throttle:number;queue:"zeus_combined_q";cores_per_task:number;memory_per_task_bytes:number;walltime_seconds:number};remote:{host:string;project_directory:string;commit:string;branch:string;dirty:false};effects:{submit_confirmation:true;start_simulation:true;submit_later_stages:false;modify_campaign_files:false;record_submission_receipt:true};local_sync:{status:"not_synchronized"}};
export type ConfirmationSubmissionResult={status:"submitted";campaign_id:string;stage:"confirmation";job_id:string;submitted_at:string;local_sync:{status:"not_synchronized"}};
export function parseConfirmationSubmissionStatus(value:Record<string,unknown>):ConfirmationSubmissionStatus{const campaign=value.campaign as Record<string,unknown>,submission=value.submission as Record<string,unknown>,sync=value.local_sync as Record<string,unknown>;const states=["not_submitted","queued","running","held","completed_success","completed_failed","status_unknown","outcome_unknown"];const action={not_submitted:"review_submission",queued:"wait",running:"wait",held:"inspect_zeus",completed_success:"validate_outputs",completed_failed:"inspect_zeus",status_unknown:"inspect_zeus",outcome_unknown:"inspect_zeus"} as Record<string,string>;const needsJob=!['not_submitted','outcome_unknown'].includes(String(submission?.status));if(!exactKeys(value,["source","queried_at","campaign","submission","next_action","local_sync"])||value.source!=="zeus"||!validUtc(value.queried_at)||!campaign||!exactKeys(campaign,["id","name","stage"])||!boundedPrintable(campaign.id,512)||!boundedPrintable(campaign.name,512)||campaign.stage!=="confirmation"||!submission||!exactKeys(submission,["status","job_id"])||!states.includes(String(submission.status))||(submission.job_id!==null&&!canonicalArrayJob.test(String(submission.job_id)))||(needsJob!==(typeof submission.job_id==="string"))||value.next_action!==action[String(submission.status)]||!sync||!exactKeys(sync,["status"])||sync.status!=="not_synchronized")throw new Error("Invalid Confirmation submission status.");return value as unknown as ConfirmationSubmissionStatus;}
export function parseConfirmationSubmissionPreview(value:Record<string,unknown>):ConfirmationSubmissionPreview{const campaign=value.campaign as Record<string,unknown>,stage=value.stage as Record<string,unknown>,job=value.job as Record<string,unknown>,remote=value.remote as Record<string,unknown>,effects=value.effects as Record<string,unknown>,sync=value.local_sync as Record<string,unknown>;if(!exactKeys(value,["preview_token","expires_in_seconds","campaign","stage","job","remote","effects","local_sync"])||!boundedPrintable(value.preview_token,512)||!Number.isInteger(value.expires_in_seconds)||Number(value.expires_in_seconds)<=0||!campaign||!exactKeys(campaign,["id","name","git_commit","s0_values"])||!boundedPrintable(campaign.id,512)||!boundedPrintable(campaign.name,512)||!/^[0-9a-f]{40}$/.test(String(campaign.git_commit))||!Array.isArray(campaign.s0_values)||campaign.s0_values.length===0||!campaign.s0_values.every(x=>typeof x==="number"&&Number.isFinite(x)&&x>0)||!stage||!exactKeys(stage,["id","label"])||stage.id!=="confirmation"||stage.label!=="Confirmation"||!job||!reviewedJobKeys(job, ["file","kind","task_count","array_throttle","queue","cores_per_task","memory_per_task_bytes","walltime_seconds"])||job.file!=="jobs/04_confirmation.pbs"||job.kind!=="array"||job.task_count!==campaign.s0_values.length*canonicalDesign.confirmation_candidates_per_s0||job.array_throttle!==canonicalStages.confirmation.array_throttle||job.queue!=="zeus_combined_q"||job.cores_per_task!==canonicalStages.confirmation.cores_per_task||job.memory_per_task_bytes!==canonicalStages.confirmation.memory_per_task_bytes||job.walltime_seconds!==canonicalStages.confirmation.walltime_seconds||!remote||!exactKeys(remote,["host","project_directory","commit","branch","dirty"])||remote.host!=="zeus.technion.ac.il"||!isCampaignProjectDirectory(remote.project_directory)||remote.commit!==campaign.git_commit||!boundedPrintable(remote.branch,256)||remote.dirty!==false||!effects||!exactKeys(effects,["submit_confirmation","start_simulation","submit_later_stages","modify_campaign_files","record_submission_receipt"])||effects.submit_confirmation!==true||effects.start_simulation!==true||effects.submit_later_stages!==false||effects.modify_campaign_files!==false||effects.record_submission_receipt!==true||!sync||!exactKeys(sync,["status"])||sync.status!=="not_synchronized")throw new Error("Invalid Confirmation submission preview.");return value as unknown as ConfirmationSubmissionPreview;}
export function parseConfirmationSubmissionResult(value:Record<string,unknown>):ConfirmationSubmissionResult{const sync=value.local_sync as Record<string,unknown>;if(!exactKeys(value,["status","campaign_id","stage","job_id","submitted_at","local_sync"])||value.status!=="submitted"||!boundedPrintable(value.campaign_id,512)||value.stage!=="confirmation"||!canonicalArrayJob.test(String(value.job_id))||!validUtc(value.submitted_at)||!sync||!exactKeys(sync,["status"])||sync.status!=="not_synchronized")throw new Error("Invalid Confirmation submission result.");return value as unknown as ConfirmationSubmissionResult;}

export type SensitivityStatus = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: "confirmation" | "sensitivity" };
  confirmation: {
    status: "queued" | "running" | "held" | "failed" | "status_unknown" | "awaiting_outputs" | "outputs_invalid" | "ready_to_prepare_sensitivity" | "sensitivity_prepared";
    job_id: string;
    scheduler: {
      state: string;
      task_count: number;
      counts: {
        queued: number;
        running: number;
        held: number;
        succeeded: number;
        failed: number;
      };
      job_id: string;
      submission_nonce: string;
    };
  };
  validation: {
    status: "valid" | "invalid" | "not_ready";
    completed_points: number;
    expected_points: number;
  };
  next_action: "review_sensitivity_preparation" | "none" | "inspect_zeus" | "wait";
  local_sync: { status: "not_synchronized" };
};
export type SensitivityPreview = {
  preview_token: string;
  expires_in_seconds: number;
  campaign: {
    id: string;
    name: string;
    git_commit: string;
    s0_values: number[];
  };
  from_stage: "confirmation";
  to_stage: "sensitivity";
  confirmation: {
    job_id: string;
    completed_points: number;
    expected_points: number;
  };
  artifacts: { create: string[]; update: string[] };
  job: {
    file: "jobs/05_sensitivity.pbs";
    kind: "array";
    task_count: number;
    array_throttle: 3;
    queue: "zeus_combined_q";
    cores_per_task: number;
    memory_per_task_bytes: number;
    walltime_seconds: number;
  };
  effects: {
    prepare_sensitivity: true;
    submit_sensitivity: false;
    start_simulation: false;
    overwrite_existing: false;
  };
  local_sync: { status: "not_synchronized" };
};
export type SensitivityResult = {
  status: "sensitivity_prepared";
  campaign_id: string;
  stage: "sensitivity";
  artifacts: { created: number; updated: number };
  submitted_to_zeus: false;
  simulation_started: false;
  local_sync: { status: "not_synchronized" };
};
export type SensitivitySubmissionStatus = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: "sensitivity" };
  submission: {
    status: "not_submitted" | "queued" | "running" | "held" | "completed_success" | "completed_failed" | "status_unknown" | "outcome_unknown";
    job_id: string | null;
  };
  next_action: "review_submission" | "inspect_zeus" | "wait" | "validate_outputs";
  local_sync: { status: "not_synchronized" };
};
export type SensitivitySubmissionPreview = {
  preview_token: string;
  expires_in_seconds: number;
  campaign: {
    id: string;
    name: string;
    git_commit: string;
    s0_values: number[];
  };
  stage: { id: "sensitivity"; label: "Sensitivity" };
  job: {
    file: "jobs/05_sensitivity.pbs";
    kind: "array";
    task_count: number;
    array_throttle: 3;
    queue: "zeus_combined_q";
    cores_per_task: number;
    memory_per_task_bytes: number;
    walltime_seconds: number;
  };
  remote: {
    host: "zeus.technion.ac.il";
    project_directory: string;
    commit: string;
    branch: string;
    dirty: false;
  };
  effects: {
    submit_sensitivity: true;
    start_simulation: true;
    submit_later_stages: false;
    modify_campaign_files: false;
    record_submission_receipt: true;
  };
  local_sync: { status: "not_synchronized" };
};
export type SensitivitySubmissionResult = {
  status: "submitted";
  campaign_id: string;
  stage: "sensitivity";
  job_id: string;
  submitted_at: string;
  local_sync: { status: "not_synchronized" };
};
const syncOk = (v: unknown) => !!v && typeof v === "object" && exactKeys(v as Record<string, unknown>, ["status"]) && (v as Record<string, unknown>).status === "not_synchronized";
const campaignCore = (v: unknown) => !!v && typeof v === "object" && boundedPrintable((v as Record<string, unknown>).id, 512) && boundedPrintable((v as Record<string, unknown>).name, 512);
const sensitivitySchedulerState: Record<string, string> = {
  queued: "queued",
  running: "running",
  held: "held",
  failed: "completed_failed",
  status_unknown: "status_unknown",
  awaiting_outputs: "completed_success",
  outputs_invalid: "completed_success",
  ready_to_prepare_sensitivity: "completed_success",
  sensitivity_prepared: "completed_success",
};
const sensitivityCountsMatch = (lifecycle: string, counts: Record<string, unknown>, total: unknown) => {
  if (lifecycle === "queued") return Number(counts.queued) > 0;
  if (lifecycle === "running") return Number(counts.running) > 0;
  if (lifecycle === "held") return Number(counts.held) > 0;
  if (lifecycle === "failed") return Number(counts.failed) > 0;
  if (["awaiting_outputs", "outputs_invalid", "ready_to_prepare_sensitivity", "sensitivity_prepared"].includes(lifecycle)) return counts.succeeded === total && counts.failed === 0;
  return lifecycle === "status_unknown";
};
export function parseSensitivityStatus(value: Record<string, unknown>): SensitivityStatus {
  const c = value.campaign as Record<string, unknown>,
    x = value.confirmation as Record<string, unknown>,
    s = x?.scheduler as Record<string, unknown>,
    n = s?.counts as Record<string, unknown>,
    v = value.validation as Record<string, unknown>;
  const states = ["queued", "running", "held", "failed", "status_unknown", "awaiting_outputs", "outputs_invalid", "ready_to_prepare_sensitivity", "sensitivity_prepared"];
  const state = String(x?.status),
    ready = ["ready_to_prepare_sensitivity", "sensitivity_prepared"].includes(state),
    invalid = state === "outputs_invalid",
    expectedStage = state === "sensitivity_prepared" ? "sensitivity" : "confirmation",
    expectedAction = state === "ready_to_prepare_sensitivity" ? "review_sensitivity_preparation" : state === "sensitivity_prepared" ? "none" : ["held", "failed", "status_unknown", "outputs_invalid"].includes(state) ? "inspect_zeus" : "wait";
  if (!exactKeys(value, ["source", "queried_at", "campaign", "confirmation", "validation", "next_action", "local_sync"]) || value.source !== "zeus" || !validUtc(value.queried_at) || !c || !exactKeys(c, ["id", "name", "stage"]) || !campaignCore(c) || c.stage !== expectedStage || !x || !exactKeys(x, ["status", "job_id", "scheduler"]) || !states.includes(state) || !canonicalArrayJob.test(String(x.job_id)) || !s || !exactKeys(s, ["state", "task_count", "counts", "job_id", "submission_nonce"]) || s.state !== sensitivitySchedulerState[state] || s.job_id !== x.job_id || !/^[0-9a-f]{32}$/.test(String(s.submission_nonce)) || !Number.isInteger(s.task_count) || Number(s.task_count) < 1 || Number(s.task_count) > 1000 || !n || !exactKeys(n, ["queued", "running", "held", "succeeded", "failed"]) || !Object.values(n).every((z) => Number.isInteger(z) && Number(z) >= 0) || Object.values(n).reduce<number>((a, z) => a + Number(z), 0) !== s.task_count || !sensitivityCountsMatch(state, n, s.task_count) || !v || !exactKeys(v, ["status", "completed_points", "expected_points"]) || v.status !== (ready ? "valid" : invalid ? "invalid" : "not_ready") || !Number.isInteger(v.completed_points) || !Number.isInteger(v.expected_points) || Number(v.expected_points) < 1 || Number(v.expected_points) > 1000 || s.task_count !== v.expected_points || v.completed_points !== (ready ? v.expected_points : 0) || value.next_action !== expectedAction || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity status.");
  return value as unknown as SensitivityStatus;
}
export function parseSensitivityPreview(value: Record<string, unknown>): SensitivityPreview {
  const c = value.campaign as Record<string, unknown>,
    q = value.confirmation as Record<string, unknown>,
    j = value.job as Record<string, unknown>,
    e = value.effects as Record<string, unknown>,
    a = value.artifacts as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "confirmation", "artifacts", "job", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !c || !exactKeys(c, ["id", "name", "git_commit", "s0_values"]) || !campaignCore(c) || !/^[0-9a-f]{40}$/.test(String(c.git_commit)) || !Array.isArray(c.s0_values) || c.s0_values.length < 1 || !c.s0_values.every((x) => typeof x === "number" && Number.isFinite(x) && x > 0) || value.from_stage !== "confirmation" || value.to_stage !== "sensitivity" || !q || !exactKeys(q, ["job_id", "completed_points", "expected_points"]) || !canonicalArrayJob.test(String(q.job_id)) || !Number.isInteger(q.completed_points) || !Number.isInteger(q.expected_points) || Number(q.expected_points) < 1 || Number(q.expected_points) > 1000 || q.expected_points !== c.s0_values.length * canonicalDesign.confirmation_candidates_per_s0 || q.completed_points !== q.expected_points || !a || !exactKeys(a, ["create", "update"]) || JSON.stringify(a.create) !== JSON.stringify(sensitivityCreates) || JSON.stringify(a.update) !== JSON.stringify(sensitivityUpdates) || !j || !reviewedJobKeys(j, ["file", "kind", "task_count", "array_throttle", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || j.file !== canonicalStages.sensitivity.job_file || j.kind !== "array" || !Number.isInteger(j.task_count) || Number(j.task_count) < 1 || Number(j.task_count) > 1000 || j.array_throttle !== canonicalStages.sensitivity.array_throttle || j.queue !== "zeus_combined_q" || j.cores_per_task !== canonicalStages.sensitivity.cores_per_task || j.memory_per_task_bytes !== canonicalStages.sensitivity.memory_per_task_bytes || j.walltime_seconds !== canonicalStages.sensitivity.walltime_seconds || !e || !exactKeys(e, ["prepare_sensitivity", "submit_sensitivity", "start_simulation", "overwrite_existing"]) || e.prepare_sensitivity !== true || e.submit_sensitivity !== false || e.start_simulation !== false || e.overwrite_existing !== false || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity preview.");
  return value as unknown as SensitivityPreview;
}
export function parseSensitivityResult(value: Record<string, unknown>): SensitivityResult {
  const a = value.artifacts as Record<string, unknown>;
  if (!exactKeys(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"]) || value.status !== "sensitivity_prepared" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "sensitivity" || !a || !exactKeys(a, ["created", "updated"]) || a.created !== sensitivityCreates.length || a.updated !== sensitivityUpdates.length || value.submitted_to_zeus !== false || value.simulation_started !== false || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity result.");
  return value as unknown as SensitivityResult;
}
export function parseSensitivitySubmissionStatus(value: Record<string, unknown>): SensitivitySubmissionStatus {
  const c = value.campaign as Record<string, unknown>,
    s = value.submission as Record<string, unknown>;
  const states = ["not_submitted", "queued", "running", "held", "completed_success", "completed_failed", "status_unknown", "outcome_unknown"];
  const actions = {
    not_submitted: "review_submission",
    queued: "wait",
    running: "wait",
    held: "inspect_zeus",
    completed_success: "validate_outputs",
    completed_failed: "inspect_zeus",
    status_unknown: "inspect_zeus",
    outcome_unknown: "inspect_zeus",
  } as Record<string, string>;
  const needsJob = !["not_submitted", "outcome_unknown"].includes(String(s?.status));
  if (!exactKeys(value, ["source", "queried_at", "campaign", "submission", "next_action", "local_sync"]) || value.source !== "zeus" || !validUtc(value.queried_at) || !c || !exactKeys(c, ["id", "name", "stage"]) || !campaignCore(c) || c.stage !== "sensitivity" || !s || !exactKeys(s, ["status", "job_id"]) || !states.includes(String(s.status)) || (s.job_id !== null && !canonicalArrayJob.test(String(s.job_id))) || needsJob !== (typeof s.job_id === "string") || value.next_action !== actions[String(s.status)] || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity submission status.");
  return value as unknown as SensitivitySubmissionStatus;
}
export function parseSensitivitySubmissionPreview(value: Record<string, unknown>): SensitivitySubmissionPreview {
  const c = value.campaign as Record<string, unknown>,
    j = value.job as Record<string, unknown>,
    r = value.remote as Record<string, unknown>,
    e = value.effects as Record<string, unknown>,
    s = value.stage as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "job", "remote", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || Number(value.expires_in_seconds) <= 0 || !c || !exactKeys(c, ["id", "name", "git_commit", "s0_values"]) || !campaignCore(c) || !/^[0-9a-f]{40}$/.test(String(c.git_commit)) || !Array.isArray(c.s0_values) || c.s0_values.length < 1 || !c.s0_values.every((x) => typeof x === "number" && Number.isFinite(x) && x > 0) || !s || !exactKeys(s, ["id", "label"]) || s.id !== "sensitivity" || s.label !== canonicalStages.sensitivity.label || !j || !reviewedJobKeys(j, ["file", "kind", "task_count", "array_throttle", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || j.file !== canonicalStages.sensitivity.job_file || j.kind !== "array" || !Number.isInteger(j.task_count) || Number(j.task_count) < 1 || Number(j.task_count) > 1000 || j.array_throttle !== canonicalStages.sensitivity.array_throttle || j.queue !== "zeus_combined_q" || j.cores_per_task !== canonicalStages.sensitivity.cores_per_task || j.memory_per_task_bytes !== canonicalStages.sensitivity.memory_per_task_bytes || j.walltime_seconds !== canonicalStages.sensitivity.walltime_seconds || !r || !exactKeys(r, ["host", "project_directory", "commit", "branch", "dirty"]) || r.host !== "zeus.technion.ac.il" || !isCampaignProjectDirectory(r.project_directory) || r.commit !== c.git_commit || !boundedPrintable(r.branch, 256) || r.dirty !== false || !e || !exactKeys(e, ["submit_sensitivity", "start_simulation", "submit_later_stages", "modify_campaign_files", "record_submission_receipt"]) || e.submit_sensitivity !== true || e.start_simulation !== true || e.submit_later_stages !== false || e.modify_campaign_files !== false || e.record_submission_receipt !== true || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity submission preview.");
  return value as unknown as SensitivitySubmissionPreview;
}
export function parseSensitivitySubmissionResult(value: Record<string, unknown>): SensitivitySubmissionResult {
  if (!exactKeys(value, ["status", "campaign_id", "stage", "job_id", "submitted_at", "local_sync"]) || value.status !== "submitted" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "sensitivity" || !canonicalArrayJob.test(String(value.job_id)) || !validUtc(value.submitted_at) || !syncOk(value.local_sync)) throw new Error("Invalid Sensitivity submission result.");
  return value as unknown as SensitivitySubmissionResult;
}

export type ProductionStatus = { source:"zeus"; queried_at:string; campaign:{id:string;name:string;stage:"sensitivity"|"production"}; sensitivity:{status:"queued"|"running"|"held"|"failed"|"status_unknown"|"awaiting_outputs"|"outputs_invalid"|"ready_to_prepare_production"|"production_prepared";job_id:string;scheduler:{state:string;task_count:number;counts:{queued:number;running:number;held:number;succeeded:number;failed:number};job_id:string;submission_nonce:string}}; validation:{status:"valid"|"invalid"|"not_ready";completed_points:number;expected_points:number}; next_action:"review_production_preparation"|"none"|"wait"; local_sync:{status:"not_synchronized"} };
export type ProductionPreview = {preview_token:string;expires_in_seconds:number;campaign:{id:string;name:string;git_commit:string;s0_values:number[]};from_stage:"sensitivity";to_stage:"production";sensitivity:{job_id:string;completed_points:number;expected_points:number};artifacts:{create:string[];update:string[]};job:{file:string;kind:"array";task_count:number;array_throttle:number;queue:string;cores_per_task:number;memory_per_task_bytes:number;walltime_seconds:number};effects:{prepare_production:true;submit_production:false;start_simulation:false;overwrite_existing:false};local_sync:{status:"not_synchronized"}};
export type ProductionResult = {status:"production_prepared";campaign_id:string;stage:"production";artifacts:{created:number;updated:number};submitted_to_zeus:false;simulation_started:false;local_sync:{status:"not_synchronized"}};
export type ProductionSubmissionStatus = {source:"zeus";queried_at:string;campaign:{id:string;name:string;stage:"production"};submission:{status:"not_submitted"|"queued"|"running"|"held"|"completed_success"|"completed_failed"|"status_unknown"|"outcome_unknown";job_id:string|null};next_action:"review_submission"|"wait"|"inspect_zeus"|"validate_outputs";local_sync:{status:"not_synchronized"}};
export type ProductionSubmissionPreview = Omit<SensitivitySubmissionPreview,"stage"|"effects"> & {stage:{id:"production";label:"Production"};effects:{submit_production:true;start_simulation:true;submit_later_stages:false;modify_campaign_files:false;record_submission_receipt:true}};
export type ProductionSubmissionResult = {status:"submitted";campaign_id:string;stage:"production";job_id:string;submitted_at:string;local_sync:{status:"not_synchronized"}};
export type FinalPrediction = {reporting_zeeman_survivors:number;simulated_zeeman_survivors:number;simulated_captured_atoms:number;pooled_conditional_efficiency:number;expected_captured_atoms:number;predicted_95_interval_fraction:[number,number];predicted_95_captured_atoms_interval:[number,number];predicted_95_half_width_fraction:number;predicted_95_half_width_percentage_points:number;binomial_mean_variance:number;empirical_between_ensemble_mean_variance:number;selected_mean_variance:number;selected_mean_variance_source:"empirical_between_ensemble"|"pooled_binomial";critical_value:number;future_counting_variance:number;uncertainty_method:string;bootstrap_replicates:20000};
export type FinalCampaignResult = {s0:number;n_ensembles:20;total_input:number;total_survivors:number;recommended_parameters:{s0:number;detuning_gamma:number;magnet_radius:number};prediction:FinalPrediction;target_uncertainty_passes:boolean;robustness_status:string;near_optimality_status:string;warnings:string[];retention:"retained";output_suitability:"eligible_as_3d_campaign_input"};
export type FinalizationStatus = {source:"zeus";queried_at:string;campaign:{id:string;name:string;stage:"production"|"complete"};production:{status:"queued"|"running"|"held"|"failed"|"status_unknown"|"awaiting_outputs"|"outputs_invalid"|"ready_to_finalize"|"campaign_complete";job_id:string;scheduler:{state:string;task_count:number;counts:{queued:number;running:number;held:number;succeeded:number;failed:number};job_id:string;submission_nonce:string}};validation:{status:"valid"|"invalid"|"not_ready";completed_ensembles:number;expected_ensembles:number};next_action:"review_finalization"|"none"|"wait";local_sync:{status:"not_synchronized"}};
export type FinalizationPreview = {preview_token:string;expires_in_seconds:number;campaign:{id:string;name:string;git_commit:string;s0_values:number[]};from_stage:"production";to_stage:"complete";production:{job_id:string;completed_ensembles:number;expected_ensembles:number};results:FinalCampaignResult[];artifacts:{create:string[];update:string[]};effects:{finalize_campaign:true;submit_job:false;start_simulation:false;overwrite_existing:false};local_sync:{status:"not_synchronized"}};
export type FinalizationResult = {status:"campaign_complete";campaign_id:string;stage:"complete";results:FinalCampaignResult[];submitted_to_zeus:false;simulation_started:false;local_sync:{status:"not_synchronized"}};

const arrayScheduler=(scheduler:unknown,expected:number,lifecycle:string,terminalReady:string)=>{const s=scheduler as Record<string,unknown>,n=s?.counts as Record<string,unknown>;const map:Record<string,string>={queued:"queued",running:"running",held:"held",failed:"completed_failed",status_unknown:"unknown",awaiting_outputs:"completed_success",outputs_invalid:"completed_success",[terminalReady]:"completed_success"};if(!s||!exactKeys(s,["state","task_count","counts","job_id","submission_nonce"])||s.state!==map[lifecycle]||s.task_count!==expected||!canonicalArrayJob.test(String(s.job_id))||!/^[0-9a-f]{32}$/.test(String(s.submission_nonce))||!n||!exactKeys(n,["queued","running","held","succeeded","failed"])||!Object.values(n).every(x=>Number.isInteger(x)&&Number(x)>=0)||Object.values(n).reduce<number>((a,x)=>a+Number(x),0)!==(lifecycle==="status_unknown"?0:expected))return false;if(lifecycle==="queued")return Number(n.queued)>0;if(lifecycle==="running")return Number(n.running)>0;if(lifecycle==="held")return Number(n.held)>0;if(lifecycle==="failed")return Number(n.failed)>0;if(["awaiting_outputs","outputs_invalid",terminalReady].includes(lifecycle))return n.succeeded===expected&&n.failed===0;return lifecycle==="status_unknown"};
const campaignWithS0=(c:Record<string,unknown>)=>campaignCore(c)&&/^[0-9a-f]{40}$/.test(String(c.git_commit))&&Array.isArray(c.s0_values)&&c.s0_values.length>0&&c.s0_values.every(x=>typeof x==="number"&&Number.isFinite(x)&&x>0);
const productionJob=(j:Record<string,unknown>,s0Count:number)=>!!j&&reviewedJobKeys(j, ["file","kind","task_count","array_throttle","queue","cores_per_task","memory_per_task_bytes","walltime_seconds"])&&j.file===canonicalStages.production.job_file&&j.kind==="array"&&j.task_count===20*s0Count&&j.array_throttle===canonicalStages.production.array_throttle&&j.queue==="zeus_combined_q"&&j.cores_per_task===canonicalStages.production.cores_per_task&&j.memory_per_task_bytes===canonicalStages.production.memory_per_task_bytes&&j.walltime_seconds===canonicalStages.production.walltime_seconds;
export function parseProductionStatus(value:Record<string,unknown>):ProductionStatus{const c=value.campaign as Record<string,unknown>,x=value.sensitivity as Record<string,unknown>,v=value.validation as Record<string,unknown>,state=String(x?.status),states=["queued","running","held","failed","status_unknown","awaiting_outputs","outputs_invalid","ready_to_prepare_production","production_prepared"],ready=["ready_to_prepare_production","production_prepared"].includes(state),expected=Number((x?.scheduler as Record<string,unknown>)?.task_count),action=state==="ready_to_prepare_production"?"review_production_preparation":state==="production_prepared"?"none":"wait";if(!exactKeys(value,["source","queried_at","campaign","sensitivity","validation","next_action","local_sync"])||value.source!=="zeus"||!validUtc(value.queried_at)||!c||!exactKeys(c,["id","name","stage"])||!campaignCore(c)||c.stage!==(state==="production_prepared"?"production":"sensitivity")||!x||!exactKeys(x,["status","job_id","scheduler"])||!states.includes(state)||!canonicalArrayJob.test(String(x.job_id))||!Number.isInteger(expected)||expected<1||expected>1000||!arrayScheduler(x.scheduler,expected,state,state==="production_prepared"?"production_prepared":"ready_to_prepare_production")||(x.scheduler as Record<string,unknown>).job_id!==x.job_id||!v||!exactKeys(v,["status","completed_points","expected_points"])||v.status!==(ready?"valid":state==="outputs_invalid"?"invalid":"not_ready")||v.expected_points!==expected||v.completed_points!==(ready?expected:0)||value.next_action!==action||!syncOk(value.local_sync))throw new Error("Invalid Production status.");return value as unknown as ProductionStatus}
export function parseProductionPreview(value:Record<string,unknown>):ProductionPreview{const c=value.campaign as Record<string,unknown>,q=value.sensitivity as Record<string,unknown>,a=value.artifacts as Record<string,unknown>,j=value.job as Record<string,unknown>,e=value.effects as Record<string,unknown>;if(!exactKeys(value,["preview_token","expires_in_seconds","campaign","from_stage","to_stage","sensitivity","artifacts","job","effects","local_sync"])||!boundedPrintable(value.preview_token,512)||!Number.isInteger(value.expires_in_seconds)||Number(value.expires_in_seconds)<=0||!c||!exactKeys(c,["id","name","git_commit","s0_values"])||!campaignWithS0(c)||value.from_stage!=="sensitivity"||value.to_stage!=="production"||!q||!exactKeys(q,["job_id","completed_points","expected_points"])||!canonicalArrayJob.test(String(q.job_id))||!Number.isInteger(q.expected_points)||Number(q.expected_points)<1||Number(q.expected_points)>1000||q.completed_points!==q.expected_points||!a||!exactKeys(a,["create","update"])||JSON.stringify(a.create)!==JSON.stringify(productionCreates)||JSON.stringify(a.update)!==JSON.stringify(productionUpdates)||!productionJob(j,(c.s0_values as unknown[]).length)||!e||!exactKeys(e,["prepare_production","submit_production","start_simulation","overwrite_existing"])||e.prepare_production!==true||e.submit_production!==false||e.start_simulation!==false||e.overwrite_existing!==false||!syncOk(value.local_sync))throw new Error("Invalid Production preview.");return value as unknown as ProductionPreview}
export function parseProductionResult(value:Record<string,unknown>):ProductionResult{const a=value.artifacts as Record<string,unknown>;if(!exactKeys(value,["status","campaign_id","stage","artifacts","submitted_to_zeus","simulation_started","local_sync"])||value.status!=="production_prepared"||!boundedPrintable(value.campaign_id,512)||value.stage!=="production"||!a||!exactKeys(a,["created","updated"])||a.created!==productionCreates.length||a.updated!==productionUpdates.length||value.submitted_to_zeus!==false||value.simulation_started!==false||!syncOk(value.local_sync))throw new Error("Invalid Production result.");return value as unknown as ProductionResult}
const submissionStatus=(value:Record<string,unknown>,stage:string)=>{const c=value.campaign as Record<string,unknown>,s=value.submission as Record<string,unknown>,states=["not_submitted","queued","running","held","completed_success","completed_failed","status_unknown","outcome_unknown"],actions:Record<string,string>={not_submitted:"review_submission",queued:"wait",running:"wait",held:"inspect_zeus",completed_success:"validate_outputs",completed_failed:"inspect_zeus",status_unknown:"inspect_zeus",outcome_unknown:"inspect_zeus"},needs=!['not_submitted','outcome_unknown'].includes(String(s?.status));return exactKeys(value,["source","queried_at","campaign","submission","next_action","local_sync"])&&value.source==="zeus"&&validUtc(value.queried_at)&&!!c&&exactKeys(c,["id","name","stage"])&&campaignCore(c)&&c.stage===stage&&!!s&&exactKeys(s,["status","job_id"])&&states.includes(String(s.status))&&(s.job_id===null||canonicalArrayJob.test(String(s.job_id)))&&needs===(typeof s.job_id==="string")&&value.next_action===actions[String(s.status)]&&syncOk(value.local_sync)};
export function parseProductionSubmissionStatus(value:Record<string,unknown>):ProductionSubmissionStatus{if(!submissionStatus(value,"production"))throw new Error("Invalid Production submission status.");return value as unknown as ProductionSubmissionStatus}
export function parseProductionSubmissionPreview(value:Record<string,unknown>):ProductionSubmissionPreview{const c=value.campaign as Record<string,unknown>,s=value.stage as Record<string,unknown>,j=value.job as Record<string,unknown>,r=value.remote as Record<string,unknown>,e=value.effects as Record<string,unknown>;if(!exactKeys(value,["preview_token","expires_in_seconds","campaign","stage","job","remote","effects","local_sync"])||!boundedPrintable(value.preview_token,512)||!Number.isInteger(value.expires_in_seconds)||Number(value.expires_in_seconds)<=0||!c||!exactKeys(c,["id","name","git_commit","s0_values"])||!campaignWithS0(c)||!s||!exactKeys(s,["id","label"])||s.id!=="production"||s.label!==canonicalStages.production.label||!productionJob(j,(c.s0_values as unknown[]).length)||!r||!exactKeys(r,["host","project_directory","commit","branch","dirty"])||r.host!=="zeus.technion.ac.il"||!isCampaignProjectDirectory(r.project_directory)||r.commit!==c.git_commit||!boundedPrintable(r.branch,256)||r.dirty!==false||!e||!exactKeys(e,["submit_production","start_simulation","submit_later_stages","modify_campaign_files","record_submission_receipt"])||e.submit_production!==true||e.start_simulation!==true||e.submit_later_stages!==false||e.modify_campaign_files!==false||e.record_submission_receipt!==true||!syncOk(value.local_sync))throw new Error("Invalid Production submission preview.");return value as unknown as ProductionSubmissionPreview}
export function parseProductionSubmissionResult(value:Record<string,unknown>):ProductionSubmissionResult{if(!exactKeys(value,["status","campaign_id","stage","job_id","submitted_at","local_sync"])||value.status!=="submitted"||!boundedPrintable(value.campaign_id,512)||value.stage!=="production"||!canonicalArrayJob.test(String(value.job_id))||!validUtc(value.submitted_at)||!syncOk(value.local_sync))throw new Error("Invalid Production submission result.");return value as unknown as ProductionSubmissionResult}
const nonnegativeFinite=(x:unknown)=>typeof x==="number"&&Number.isFinite(x)&&x>=0;
const probability=(x:unknown)=>nonnegativeFinite(x)&&Number(x)<=1;
const integerNonnegative=(x:unknown)=>Number.isInteger(x)&&Number(x)>=0;
const finalResult=(value:unknown)=>{const r=value as Record<string,unknown>,p=r?.recommended_parameters as Record<string,unknown>,x=r?.prediction as Record<string,unknown>;const interval=x?.predicted_95_interval_fraction as unknown[],atoms=x?.predicted_95_captured_atoms_interval as unknown[],warnings=r?.warnings as unknown[];const required=["robust_operating_region_not_established","epsilon_near_optimality_not_established",...(r?.target_uncertainty_passes===false?["target_95_prediction_half_width_not_met"]:[])],allowed=new Set([...required,"detuning_lower","detuning_upper","radius_lower","radius_upper"]);return !!r&&exactKeys(r,["s0","n_ensembles","total_input","total_survivors","recommended_parameters","prediction","target_uncertainty_passes","robustness_status","near_optimality_status","warnings","retention","output_suitability"])&&typeof r.s0==="number"&&Number.isFinite(r.s0)&&r.s0>0&&r.n_ensembles===20&&integerNonnegative(r.total_input)&&integerNonnegative(r.total_survivors)&&Number(r.total_survivors)<=Number(r.total_input)&&!!p&&exactKeys(p,["s0","detuning_gamma","magnet_radius"])&&p.s0===r.s0&&[p.detuning_gamma,p.magnet_radius].every(z=>typeof z==="number"&&Number.isFinite(z))&&!!x&&exactKeys(x,["reporting_zeeman_survivors","simulated_zeeman_survivors","simulated_captured_atoms","pooled_conditional_efficiency","expected_captured_atoms","predicted_95_interval_fraction","predicted_95_captured_atoms_interval","predicted_95_half_width_fraction","predicted_95_half_width_percentage_points","binomial_mean_variance","empirical_between_ensemble_mean_variance","selected_mean_variance","selected_mean_variance_source","critical_value","future_counting_variance","uncertainty_method","bootstrap_replicates"])&&integerNonnegative(x.reporting_zeeman_survivors)&&x.simulated_zeeman_survivors===r.total_input&&x.simulated_captured_atoms===r.total_survivors&&probability(x.pooled_conditional_efficiency)&&integerNonnegative(x.expected_captured_atoms)&&Array.isArray(interval)&&interval.length===2&&interval.every(probability)&&Number(interval[0])<=Number(interval[1])&&Array.isArray(atoms)&&atoms.length===2&&atoms.every(integerNonnegative)&&Number(atoms[0])<=Number(atoms[1])&&[x.predicted_95_half_width_fraction,x.predicted_95_half_width_percentage_points,x.binomial_mean_variance,x.empirical_between_ensemble_mean_variance,x.selected_mean_variance,x.critical_value,x.future_counting_variance].every(nonnegativeFinite)&&["empirical_between_ensemble","pooled_binomial"].includes(String(x.selected_mean_variance_source))&&boundedPrintable(x.uncertainty_method,1000)&&x.bootstrap_replicates===20000&&typeof r.target_uncertainty_passes==="boolean"&&r.robustness_status==="not_established_pending_adaptive_challenger_validation"&&r.near_optimality_status==="not_established_pending_domain_challenger_elimination"&&Array.isArray(warnings)&&warnings.every(w=>typeof w==="string"&&allowed.has(w))&&new Set(warnings).size===warnings.length&&required.every(w=>warnings.includes(w))&&r.retention==="retained"&&r.output_suitability==="eligible_as_3d_campaign_input"};
const finalResults=(values:unknown,s0s:unknown[])=>Array.isArray(values)&&values.length===s0s.length&&values.every(finalResult)&&values.every((r,i)=>(r as Record<string,unknown>).s0===s0s[i]);
export function parseFinalizationStatus(value:Record<string,unknown>):FinalizationStatus{const c=value.campaign as Record<string,unknown>,x=value.production as Record<string,unknown>,v=value.validation as Record<string,unknown>,state=String(x?.status),states=["queued","running","held","failed","status_unknown","awaiting_outputs","outputs_invalid","ready_to_finalize","campaign_complete"],ready=["ready_to_finalize","campaign_complete"].includes(state),expected=Number((x?.scheduler as Record<string,unknown>)?.task_count),action=state==="ready_to_finalize"?"review_finalization":state==="campaign_complete"?"none":"wait";if(!exactKeys(value,["source","queried_at","campaign","production","validation","next_action","local_sync"])||value.source!=="zeus"||!validUtc(value.queried_at)||!c||!exactKeys(c,["id","name","stage"])||!campaignCore(c)||c.stage!==(state==="campaign_complete"?"complete":"production")||!x||!exactKeys(x,["status","job_id","scheduler"])||!states.includes(state)||!canonicalArrayJob.test(String(x.job_id))||!Number.isInteger(expected)||expected<1||expected>1000||!arrayScheduler(x.scheduler,expected,state,state==="campaign_complete"?"campaign_complete":"ready_to_finalize")||(x.scheduler as Record<string,unknown>).job_id!==x.job_id||!v||!exactKeys(v,["status","completed_ensembles","expected_ensembles"])||v.status!==(ready?"valid":state==="outputs_invalid"?"invalid":"not_ready")||v.expected_ensembles!==expected||v.completed_ensembles!==(ready?expected:0)||value.next_action!==action||!syncOk(value.local_sync))throw new Error("Invalid finalization status.");return value as unknown as FinalizationStatus}
export function parseFinalizationPreview(value:Record<string,unknown>):FinalizationPreview{const c=value.campaign as Record<string,unknown>,p=value.production as Record<string,unknown>,a=value.artifacts as Record<string,unknown>,e=value.effects as Record<string,unknown>,s0s=c.s0_values as unknown[];if(!exactKeys(value,["preview_token","expires_in_seconds","campaign","from_stage","to_stage","production","results","artifacts","effects","local_sync"])||!boundedPrintable(value.preview_token,512)||!Number.isInteger(value.expires_in_seconds)||Number(value.expires_in_seconds)<=0||!c||!exactKeys(c,["id","name","git_commit","s0_values"])||!campaignWithS0(c)||value.from_stage!=="production"||value.to_stage!=="complete"||!p||!exactKeys(p,["job_id","completed_ensembles","expected_ensembles"])||!canonicalArrayJob.test(String(p.job_id))||p.expected_ensembles!==20*s0s.length||p.completed_ensembles!==p.expected_ensembles||!finalResults(value.results,s0s)||!a||!exactKeys(a,["create","update"])||JSON.stringify(a.create)!==JSON.stringify([...s0s.map(v=>`production/s0_${Number(v).toFixed(6).replace(".","p")}/summary.json`),"final_report.json"].sort())||JSON.stringify(a.update)!==JSON.stringify(finalizationUpdates)||!e||!exactKeys(e,["finalize_campaign","submit_job","start_simulation","overwrite_existing"])||e.finalize_campaign!==true||e.submit_job!==false||e.start_simulation!==false||e.overwrite_existing!==false||!syncOk(value.local_sync))throw new Error("Invalid finalization preview.");return value as unknown as FinalizationPreview}
export function parseFinalizationResult(value:Record<string,unknown>):FinalizationResult{const results=value.results as unknown[];if(!exactKeys(value,["status","campaign_id","stage","results","submitted_to_zeus","simulation_started","local_sync"])||value.status!=="campaign_complete"||!boundedPrintable(value.campaign_id,512)||value.stage!=="complete"||!Array.isArray(results)||results.length<1||!results.every(finalResult)||value.submitted_to_zeus!==false||value.simulation_started!==false||!syncOk(value.local_sync))throw new Error("Invalid finalization result.");return value as unknown as FinalizationResult}



export function parsePreview(value: Record<string, unknown>): CreationPreview {
  const provenance = value.provenance as Record<string, unknown>;
  const plan = value.plan as Record<string, unknown> | null;
  const duplicate = value.duplicate as Record<string, unknown> | null;
  if ((value.preview_token !== null && !text(value.preview_token)) || !finiteNonnegative(value.expires_in_seconds) || !provenance || !text(provenance.commit) || provenance.input_count !== canonicalDesign.ensemble_count || !value.scientific_design || typeof value.scientific_design !== "object") throw new Error("Invalid campaign preview response.");
  if (plan !== null && (!plan || !text(plan.name) || !text(plan.path) || !Array.isArray(plan.s0_values) || !plan.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0) || !text(plan.source_id) || !Array.isArray(plan.files) || !plan.files.every(text) || plan.stage !== "smoke")) throw new Error("Invalid campaign preview response.");
  if (duplicate !== null && (!duplicate || (duplicate.campaign_id !== null && !text(duplicate.campaign_id)) || !text(duplicate.path) || !text(duplicate.stage))) throw new Error("Invalid campaign preview response.");
  if ((duplicate === null) === (plan === null) || (plan !== null && !text(value.preview_token))) throw new Error("Invalid campaign preview response.");
  return value as unknown as CreationPreview;
}

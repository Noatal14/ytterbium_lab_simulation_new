export type Warning = { severity: "info" | "attention" | "blocked"; message: string };
export type StageProgress = { stage: string; completed: number; expected: number | null; status: "not-started" | "in-progress" | "complete" | "unknown" | "inconsistent" };
export type Campaign = {
  id: string; family: "mot_2d" | "mot_3d"; kind: string; name: string; path: string; stage: string;
  stage_semantics: "prepared-workflow-stage"; scheduler_status: "unchecked";
  trust: "trusted-current" | "legacy-incomplete"; scientific_role: "candidate-selection" | "sealed-final-validation" | "historical-evidence";
  progress: StageProgress[]; warnings: Warning[];
  next_plan: null | { label: string; command: string[]; display_command: string; mode: "copy-only"; scheduler_status: "unchecked"; operation_scope: "remote-submission" | "local-mutation"; executes_automatically: false };
  s0_values: number[]; families: string[]; git_commit: string | null;
  remote_preparation: { status: "ready" | "legacy-local-only" | "unavailable"; reason_code: null | "absolute-input-paths" | "fixed-checkout-path" | "incomplete-portability-record" | "campaign-validation-failed" };
};
type CampaignListEnvelope = { data: { campaigns: Campaign[]; invalid_count: number; total: number } };
type CampaignEnvelope = { data: Campaign };
async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`The local campaign service returned ${response.status}.`);
  return response.json() as Promise<T>;
}

const text = (value: unknown): value is string => typeof value === "string";
const finiteNonnegative = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
function parseCampaign(value: unknown): Campaign {
  if (!value || typeof value !== "object") throw new Error("Invalid campaign response.");
  const row = value as Record<string, unknown>;
  const families = ["mot_2d", "mot_3d"];
  const trusts = ["trusted-current", "legacy-incomplete"];
  const roles = ["candidate-selection", "sealed-final-validation", "historical-evidence"];
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
export const campaignApi = {
  async list() {
    const data = (await request<CampaignListEnvelope>("/api/v1/campaigns")).data;
    if (!data || !Array.isArray(data.campaigns) || !finiteNonnegative(data.invalid_count) || !finiteNonnegative(data.total) || data.total !== data.campaigns.length) throw new Error("Invalid campaign list response.");
    return { ...data, campaigns: data.campaigns.map(parseCampaign) };
  },
  async get(id: string) { return parseCampaign((await request<CampaignEnvelope>(`/api/v1/campaigns/${encodeURIComponent(id)}`)).data); },
};
export type ZeemanSource = { id: string; path: string; profile: string; ensemble_count: number; minimum_survivors: number; maximum_survivors: number; fingerprint: string };
export type CreationPreview = {
  preview_token: string | null; expires_in_seconds: number;
  plan: null | { name: string; path: string; s0_values: number[]; source_id: string; files: string[]; stage: "smoke" };
  scientific_design: Record<string, unknown>;
  provenance: { commit: string; input_count: 35 };
  duplicate: null | { campaign_id: string | null; path: string; stage: string };
};
export type CreationResult = { status: "created"; campaign_id: string; path: string; stage: "smoke"; submitted_to_zeus: false };
export const creationApi = {
  async sources(): Promise<ZeemanSource[]> {
    const payload = await request<{ data: { sources: unknown[]; total: number; invalid_count: number } }>("/api/v1/campaigns/2d/sources");
    if (!payload.data || !Array.isArray(payload.data.sources) || payload.data.total !== payload.data.sources.length) throw new Error("Invalid Zeeman source response.");
    return payload.data.sources.map((value) => {
      if (!value || typeof value !== "object") throw new Error("Invalid Zeeman source response.");
      const row = value as Record<string, unknown>;
      if (!text(row.id) || !text(row.path) || !text(row.profile) || row.ensemble_count !== 35 || !finiteNonnegative(row.minimum_survivors) || !finiteNonnegative(row.maximum_survivors) || !text(row.fingerprint)) throw new Error("Invalid Zeeman source response.");
      return row as unknown as ZeemanSource;
    });
  },
  async session(): Promise<string> {
    const payload = await request<{ data: { csrf_token: string } }>("/api/v1/session");
    if (!payload.data || !text(payload.data.csrf_token)) throw new Error("Invalid local creation session.");
    return payload.data.csrf_token;
  },
  async preview(input: { name: string; slug: string; source_id: string; s0_values: number[] }, csrf: string): Promise<CreationPreview> {
    return parsePreview(await mutationRequest("/api/v1/campaigns/2d/preview", input, csrf));
  },
  async confirm(preview_token: string, csrf: string): Promise<CreationResult> {
    const row = await mutationRequest("/api/v1/campaigns/2d/confirm", { preview_token }, csrf);
    if (row.status !== "created" || !text(row.campaign_id) || !text(row.path) || row.stage !== "smoke" || row.submitted_to_zeus !== false) throw new Error("Invalid campaign creation response.");
    return row as unknown as CreationResult;
  },
};
export type CreationApi = typeof creationApi;

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

export class ZeusApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

const boundedPrintable = (value: unknown, limit: number): value is string => text(value) && value.length <= limit && !/[\u0000-\u001f\u007f]/.test(value);
const nullableBoundedPrintable = (value: unknown, limit: number): value is string | null => value === null || boundedPrintable(value, limit);
function parseZeusSnapshot(value: unknown): ZeusSnapshot {
  if (!value || typeof value !== "object") throw new Error("Invalid Zeus snapshot response.");
  const row = value as Record<string, unknown>;
  const profile = row.profile as Record<string, unknown>;
  const remote = row.remote as Record<string, unknown>;
  const scheduler = row.scheduler as Record<string, unknown>;
  if (!exactKeys(row, ["connection_status", "profile", "remote", "scheduler"]) || row.connection_status !== "connected" || !profile || !exactKeys(profile, ["host", "username", "project_directory", "authentication"]) || profile.host !== "zeus.technion.ac.il" || !text(profile.username) || !/^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(profile.username) || !text(profile.project_directory) || profile.project_directory !== `/home/${profile.username}/ytterbium_lab_simulation_new` || profile.authentication !== "ssh-key-or-agent" || !remote || !exactKeys(remote, ["project_directory", "git_commit", "branch", "dirty"]) || remote.project_directory !== profile.project_directory || !text(remote.git_commit) || !/^[0-9a-f]{40}$/.test(remote.git_commit) || !boundedPrintable(remote.branch, 256) || typeof remote.dirty !== "boolean" || !scheduler || !exactKeys(scheduler, ["status", "queried_at", "jobs"]) || scheduler.status !== "available" || !text(scheduler.queried_at) || Number.isNaN(Date.parse(String(scheduler.queried_at))) || !Array.isArray(scheduler.jobs) || scheduler.jobs.length > 500) throw new Error("Invalid Zeus snapshot response.");
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

export const zeusApi = {
  async snapshot(username: string, project_directory: string): Promise<ZeusSnapshot> {
    const csrf = await creationApi.session();
    const response = await fetch("/api/v1/zeus/snapshot", { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ username, project_directory }) });
    const payload = await response.json() as { data?: unknown; error?: { code?: unknown; message?: unknown } };
    if (!response.ok || !payload.data) throw new ZeusApiError(text(payload.error?.code) ? payload.error.code : "check_failed", text(payload.error?.message) ? payload.error.message : "The read-only Zeus check failed safely.");
    const snapshot = parseZeusSnapshot(payload.data);
    if (snapshot.profile.username !== username || snapshot.profile.project_directory !== project_directory || snapshot.remote.project_directory !== project_directory) throw new Error("Zeus snapshot did not match the requested profile.");
    return snapshot;
  },
};
export type ZeusApi = typeof zeusApi;

export type ZeusTransferPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; path: string; git_commit: string };
  destination: { host: "zeus.technion.ac.il"; project_directory: string; campaign_directory: string };
  artifacts: { ensemble_count: 35; total_count: 72; missing_count: number; identical_count: number; total_bytes: number; missing_bytes: number };
  effects: { copy_missing_only: true; overwrite_existing: false; submit_jobs: false; run_simulation: false };
};
export type ZeusTransferResult = {
  status: "prepared"; campaign_id: string; destination: string; transferred_count: number;
  reused_identical_count: number; bytes_transferred: number; submitted_to_zeus: false; simulation_started: false;
};

function parseTransferPreview(value: Record<string, unknown>): ZeusTransferPreview {
  const campaign = value.campaign as Record<string, unknown>;
  const destination = value.destination as Record<string, unknown>;
  const artifacts = value.artifacts as Record<string, unknown>;
  const effects = value.effects as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "destination", "artifacts", "effects"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "path", "git_commit"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !boundedPrintable(campaign.path, 1024) || !String(campaign.path).startsWith("data/optimization/mot_2d/") || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit))
    || !destination || !exactKeys(destination, ["host", "project_directory", "campaign_directory"]) || destination.host !== "zeus.technion.ac.il" || !boundedPrintable(destination.project_directory, 1024) || !/^\/home\/[A-Za-z][A-Za-z0-9._-]{0,31}\/ytterbium_lab_simulation_new$/.test(String(destination.project_directory)) || !boundedPrintable(destination.campaign_directory, 2048) || destination.campaign_directory !== `${destination.project_directory}/${campaign.path}`
    || !artifacts || !exactKeys(artifacts, ["ensemble_count", "total_count", "missing_count", "identical_count", "total_bytes", "missing_bytes"]) || artifacts.ensemble_count !== 35 || artifacts.total_count !== 72 || !Number.isInteger(artifacts.missing_count) || !Number.isInteger(artifacts.identical_count) || !Number.isInteger(artifacts.total_bytes) || !Number.isInteger(artifacts.missing_bytes) || !finiteNonnegative(artifacts.missing_count) || !finiteNonnegative(artifacts.identical_count) || !finiteNonnegative(artifacts.total_bytes) || !finiteNonnegative(artifacts.missing_bytes) || Number(artifacts.missing_count) + Number(artifacts.identical_count) !== 72 || Number(artifacts.missing_bytes) > Number(artifacts.total_bytes)
    || !effects || !exactKeys(effects, ["copy_missing_only", "overwrite_existing", "submit_jobs", "run_simulation"]) || effects.copy_missing_only !== true || effects.overwrite_existing !== false || effects.submit_jobs !== false || effects.run_simulation !== false) throw new Error("Invalid Zeus preparation preview response.");
  return value as unknown as ZeusTransferPreview;
}

function parseTransferResult(value: Record<string, unknown>): ZeusTransferResult {
  if (!exactKeys(value, ["status", "campaign_id", "destination", "transferred_count", "reused_identical_count", "bytes_transferred", "submitted_to_zeus", "simulation_started"]) || value.status !== "prepared" || !boundedPrintable(value.campaign_id, 512) || !boundedPrintable(value.destination, 2048) || !Number.isInteger(value.transferred_count) || !Number.isInteger(value.reused_identical_count) || !Number.isInteger(value.bytes_transferred) || !finiteNonnegative(value.transferred_count) || !finiteNonnegative(value.reused_identical_count) || Number(value.transferred_count) + Number(value.reused_identical_count) !== 72 || !finiteNonnegative(value.bytes_transferred) || value.submitted_to_zeus !== false || value.simulation_started !== false) throw new Error("Invalid Zeus preparation result.");
  return value as unknown as ZeusTransferResult;
}

let transferSession: Promise<string> | null = null;
let transferContext: { token: string; campaignId: string; destination: string } | null = null;
const getTransferSession = () => transferSession ??= creationApi.session();
export const transferApi = {
  async preview(campaign_id: string, profile: ZeusSnapshot["profile"]): Promise<ZeusTransferPreview> {
    const csrf = await getTransferSession();
    try {
      const preview = parseTransferPreview(await mutationRequest("/api/v1/zeus/transfers/preview", { campaign_id, username: profile.username, project_directory: profile.project_directory }, csrf));
      if (preview.campaign.id !== campaign_id || preview.destination.project_directory !== profile.project_directory) throw new Error("Zeus preparation preview did not match the requested campaign and profile.");
      transferContext = { token: preview.preview_token, campaignId: preview.campaign.id, destination: preview.destination.campaign_directory };
      return preview;
    }
    catch (error) { transferSession = null; transferContext = null; throw error; }
  },
  async confirm(preview_token: string): Promise<ZeusTransferResult> {
    if (!transferContext || transferContext.token !== preview_token) throw new Error("The Zeus preparation preview is no longer active.");
    const csrf = await getTransferSession();
    try {
      const result = parseTransferResult(await mutationRequest("/api/v1/zeus/transfers/confirm", { preview_token }, csrf));
      if (result.campaign_id !== transferContext.campaignId || result.destination !== transferContext.destination) throw new Error("Zeus preparation result did not match the reviewed plan.");
      return result;
    }
    finally { transferSession = null; transferContext = null; }
  },
};
export type TransferApi = typeof transferApi;

export type SmokeSubmissionPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; path: string; git_commit: string; s0_values: number[] };
  stage: { id: "smoke"; label: "Smoke check"; purpose: string };
  job: { file: "jobs/01_smoke.pbs"; kind: "job" | "array"; task_count: number; queue: "zeus_combined_q"; cores_per_task: 1; memory_per_task_bytes: 68719476736; walltime_seconds: 1200 };
  remote: { host: "zeus.technion.ac.il"; project_directory: string; commit: string; branch: string; dirty: false };
  inputs: { verified_count: 72; status: "ready" };
  effects: { submit_smoke: true; submit_later_stages: false; modify_files: false };
  later_stages_locked: true;
};
export type SmokeSubmissionResult = {
  status: "submitted"; campaign_id: string; stage: "smoke"; job_id: string;
  submitted_at: string; later_stages_locked: true;
};
export class SubmissionApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

function parseSmokeSubmissionPreview(value: Record<string, unknown>): SmokeSubmissionPreview {
  const campaign = value.campaign as Record<string, unknown>;
  const stage = value.stage as Record<string, unknown>;
  const job = value.job as Record<string, unknown>;
  const remote = value.remote as Record<string, unknown>;
  const inputs = value.inputs as Record<string, unknown>;
  const effects = value.effects as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "stage", "job", "remote", "inputs", "effects", "later_stages_locked"])
    || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "path", "git_commit", "s0_values"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !boundedPrintable(campaign.path, 1024) || !String(campaign.path).startsWith("data/optimization/mot_2d/") || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || !Array.isArray(campaign.s0_values) || campaign.s0_values.length === 0 || !campaign.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0)
    || !stage || !exactKeys(stage, ["id", "label", "purpose"]) || stage.id !== "smoke" || stage.label !== "Smoke check" || !boundedPrintable(stage.purpose, 512)
    || !job || !exactKeys(job, ["file", "kind", "task_count", "queue", "cores_per_task", "memory_per_task_bytes", "walltime_seconds"]) || job.file !== "jobs/01_smoke.pbs" || !["job", "array"].includes(String(job.kind)) || !Number.isInteger(job.task_count) || Number(job.task_count) < 1 || job.task_count !== campaign.s0_values.length || (job.task_count === 1 ? job.kind !== "job" : job.kind !== "array") || job.queue !== "zeus_combined_q" || job.cores_per_task !== 1 || job.memory_per_task_bytes !== 68719476736 || job.walltime_seconds !== 1200
    || !remote || !exactKeys(remote, ["host", "project_directory", "commit", "branch", "dirty"]) || remote.host !== "zeus.technion.ac.il" || !/^\/home\/[A-Za-z][A-Za-z0-9._-]{0,31}\/ytterbium_lab_simulation_new$/.test(String(remote.project_directory)) || remote.commit !== campaign.git_commit || !boundedPrintable(remote.branch, 256) || remote.dirty !== false
    || !inputs || !exactKeys(inputs, ["verified_count", "status"]) || inputs.verified_count !== 72 || inputs.status !== "ready"
    || !effects || !exactKeys(effects, ["submit_smoke", "submit_later_stages", "modify_files"]) || effects.submit_smoke !== true || effects.submit_later_stages !== false || effects.modify_files !== false || value.later_stages_locked !== true) throw new Error("Invalid smoke submission preview response.");
  return value as unknown as SmokeSubmissionPreview;
}

function parseSmokeSubmissionResult(value: Record<string, unknown>): SmokeSubmissionResult {
  if (!exactKeys(value, ["status", "campaign_id", "stage", "job_id", "submitted_at", "later_stages_locked"]) || value.status !== "submitted" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "smoke" || !text(value.job_id) || !/^\d+(?:\[\])?\.zeus-master$/.test(value.job_id) || !text(value.submitted_at) || Number.isNaN(Date.parse(value.submitted_at)) || value.later_stages_locked !== true) throw new Error("Invalid smoke submission result.");
  return value as unknown as SmokeSubmissionResult;
}

let submissionSession: Promise<string> | null = null;
let submissionContext: { token: string; campaignId: string; jobKind: "job" | "array" } | null = null;
const getSubmissionSession = () => submissionSession ??= creationApi.session();
async function submissionMutation(path: string, body: object, csrf: string): Promise<Record<string, unknown>> {
  const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
  const payload = await response.json() as { data?: Record<string, unknown>; error?: { code?: unknown; message?: unknown } };
  if (!response.ok || !payload.data) throw new SubmissionApiError(text(payload.error?.code) ? payload.error.code : "submission_failed", text(payload.error?.message) ? payload.error.message : "Smoke submission stopped safely.");
  return payload.data;
}
export const submissionApi = {
  async preview(campaign_id: string, profile: ZeusSnapshot["profile"]): Promise<SmokeSubmissionPreview> {
    const csrf = await getSubmissionSession();
    try {
      const preview = parseSmokeSubmissionPreview(await submissionMutation("/api/v1/zeus/submissions/smoke/preview", { campaign_id, username: profile.username, project_directory: profile.project_directory }, csrf));
      if (preview.campaign.id !== campaign_id || preview.remote.project_directory !== profile.project_directory) throw new Error("Smoke submission preview did not match the requested campaign and profile.");
      submissionContext = { token: preview.preview_token, campaignId: preview.campaign.id, jobKind: preview.job.kind };
      return preview;
    } catch (error) { submissionSession = null; submissionContext = null; throw error; }
  },
  async confirm(preview_token: string): Promise<SmokeSubmissionResult> {
    if (!submissionContext || submissionContext.token !== preview_token) throw new Error("The smoke submission preview is no longer active.");
    const csrf = await getSubmissionSession();
    try {
      const result = parseSmokeSubmissionResult(await submissionMutation("/api/v1/zeus/submissions/smoke/confirm", { preview_token }, csrf));
      const resultIsArray = result.job_id.includes("[]");
      if (result.campaign_id !== submissionContext.campaignId || resultIsArray !== (submissionContext.jobKind === "array")) throw new Error("Smoke submission result did not match the reviewed campaign and job.");
      return result;
    } catch (error) {
      if (error instanceof SubmissionApiError) throw error;
      throw new SubmissionApiError("submission_outcome_unknown", "The submission result could not be verified. Do not submit again; check Zeus jobs first.");
    } finally { submissionSession = null; submissionContext = null; }
  },
};
export type SubmissionApi = typeof submissionApi;

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
export type ScreeningPreview = {
  preview_token: string; expires_in_seconds: number;
  campaign: { id: string; name: string; git_commit: string };
  from_stage: "smoke"; to_stage: "screen";
  smoke: { job_id: string; points: SmokePoint[]; artifact_count: number };
  artifacts: { create: ["screen/tasks.json", "jobs/02_screen.pbs"]; update: ["campaign.json"] };
  effects: { prepare_screening: true; submit_screening: false; start_simulation: false; overwrite_existing: false };
  local_sync: { status: "not_synchronized" };
};
export type ScreeningResult = {
  status: "screening_prepared"; campaign_id: string; stage: "screen";
  artifacts: { created: 2; updated: 1 };
  submitted_to_zeus: false; simulation_started: false;
  local_sync: { status: "not_synchronized" };
};
export class SmokeLifecycleApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

const smokeJobId = /^\d+(?:\[\])?\.zeus-master$/;
function parseSmokePoint(value: unknown): SmokePoint {
  if (!value || typeof value !== "object") throw new Error("Invalid smoke lifecycle response.");
  const row = value as Record<string, unknown>;
  if (!exactKeys(row, ["s0", "captured", "input", "efficiency"]) || typeof row.s0 !== "number" || !Number.isFinite(row.s0) || row.s0 <= 0 || !Number.isInteger(row.captured) || !finiteNonnegative(row.captured) || row.input !== 2 || Number(row.captured) > 2 || typeof row.efficiency !== "number" || !Number.isFinite(row.efficiency) || row.efficiency < 0 || row.efficiency > 1 || Math.abs(row.efficiency - Number(row.captured) / 2) > 1e-12) throw new Error("Invalid smoke lifecycle response.");
  return row as unknown as SmokePoint;
}
function parseSmokeLifecycle(value: Record<string, unknown>): SmokeLifecycle {
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
function parseScreeningPreview(value: Record<string, unknown>): ScreeningPreview {
  const campaign = value.campaign as Record<string, unknown>; const smoke = value.smoke as Record<string, unknown>; const artifacts = value.artifacts as Record<string, unknown>; const effects = value.effects as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "smoke", "artifacts", "effects", "local_sync"]) || !boundedPrintable(value.preview_token, 512) || !Number.isInteger(value.expires_in_seconds) || !finiteNonnegative(value.expires_in_seconds)
    || !campaign || !exactKeys(campaign, ["id", "name", "git_commit"]) || !boundedPrintable(campaign.id, 512) || !boundedPrintable(campaign.name, 512) || !/^[0-9a-f]{40}$/.test(String(campaign.git_commit)) || value.from_stage !== "smoke" || value.to_stage !== "screen"
    || !smoke || !exactKeys(smoke, ["job_id", "points", "artifact_count"]) || !text(smoke.job_id) || !smokeJobId.test(smoke.job_id) || !Array.isArray(smoke.points) || smoke.points.length === 0 || smoke.points.length > 100 || !Number.isInteger(smoke.artifact_count) || smoke.artifact_count !== smoke.points.length * 3
    || !artifacts || !exactKeys(artifacts, ["create", "update"]) || JSON.stringify(artifacts.create) !== JSON.stringify(["screen/tasks.json", "jobs/02_screen.pbs"]) || JSON.stringify(artifacts.update) !== JSON.stringify(["campaign.json"])
    || !effects || !exactKeys(effects, ["prepare_screening", "submit_screening", "start_simulation", "overwrite_existing"]) || effects.prepare_screening !== true || effects.submit_screening !== false || effects.start_simulation !== false || effects.overwrite_existing !== false
    || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid screening preparation preview response.");
  return { ...(value as unknown as ScreeningPreview), smoke: { ...(smoke as unknown as ScreeningPreview["smoke"]), points: smoke.points.map(parseSmokePoint) } };
}
function parseScreeningResult(value: Record<string, unknown>): ScreeningResult {
  const artifacts = value.artifacts as Record<string, unknown>; const sync = value.local_sync as Record<string, unknown>;
  if (!exactKeys(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"]) || value.status !== "screening_prepared" || !boundedPrintable(value.campaign_id, 512) || value.stage !== "screen" || !artifacts || !exactKeys(artifacts, ["created", "updated"]) || artifacts.created !== 2 || artifacts.updated !== 1 || value.submitted_to_zeus !== false || value.simulation_started !== false || !sync || !exactKeys(sync, ["status"]) || sync.status !== "not_synchronized") throw new Error("Invalid screening preparation result.");
  return value as unknown as ScreeningResult;
}
async function lifecycleMutation(path: string, body: object, csrf: string): Promise<Record<string, unknown>> {
  const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
  const payload = await response.json() as { data?: Record<string, unknown>; error?: { code?: unknown; message?: unknown } };
  if (!response.ok || !payload.data) throw new SmokeLifecycleApiError(text(payload.error?.code) ? payload.error.code : "smoke_check_failed", text(payload.error?.message) ? payload.error.message : "The smoke status check stopped safely.");
  return payload.data;
}
let screeningSession: Promise<string> | null = null;
let screeningContext: { token: string; campaignId: string } | null = null;
const getScreeningSession = () => screeningSession ??= creationApi.session();
export const smokeLifecycleApi = {
  async status(campaign_id: string, profile: ZeusSnapshot["profile"]): Promise<SmokeLifecycle> {
    const csrf = await creationApi.session();
    const result = parseSmokeLifecycle(await lifecycleMutation("/api/v1/zeus/smoke/status", { campaign_id, username: profile.username, project_directory: profile.project_directory }, csrf));
    if (result.campaign.id !== campaign_id) throw new Error("Smoke status did not match the selected campaign.");
    return result;
  },
  async preview(campaign_id: string, profile: ZeusSnapshot["profile"]): Promise<ScreeningPreview> {
    const csrf = await getScreeningSession();
    try {
      const preview = parseScreeningPreview(await lifecycleMutation("/api/v1/zeus/screening/preview", { campaign_id, username: profile.username, project_directory: profile.project_directory }, csrf));
      if (preview.campaign.id !== campaign_id) throw new Error("Screening preparation preview did not match the selected campaign.");
      screeningContext = { token: preview.preview_token, campaignId: campaign_id }; return preview;
    } catch (error) { screeningSession = null; screeningContext = null; throw error; }
  },
  async confirm(preview_token: string): Promise<ScreeningResult> {
    if (!screeningContext || screeningContext.token !== preview_token) throw new Error("The screening preparation preview is no longer active.");
    const csrf = await getScreeningSession();
    try { const result = parseScreeningResult(await lifecycleMutation("/api/v1/zeus/screening/confirm", { preview_token }, csrf)); if (result.campaign_id !== screeningContext.campaignId) throw new Error("Screening preparation result did not match the reviewed campaign."); return result; }
    finally { screeningSession = null; screeningContext = null; }
  },
};
export type SmokeLifecycleApi = typeof smokeLifecycleApi;

function parsePreview(value: Record<string, unknown>): CreationPreview {
  const provenance = value.provenance as Record<string, unknown>;
  const plan = value.plan as Record<string, unknown> | null;
  const duplicate = value.duplicate as Record<string, unknown> | null;
  if ((value.preview_token !== null && !text(value.preview_token)) || !finiteNonnegative(value.expires_in_seconds) || !provenance || !text(provenance.commit) || provenance.input_count !== 35 || !value.scientific_design || typeof value.scientific_design !== "object") throw new Error("Invalid campaign preview response.");
  if (plan !== null && (!plan || !text(plan.name) || !text(plan.path) || !Array.isArray(plan.s0_values) || !plan.s0_values.every((item) => typeof item === "number" && Number.isFinite(item) && item > 0) || !text(plan.source_id) || !Array.isArray(plan.files) || !plan.files.every(text) || plan.stage !== "smoke")) throw new Error("Invalid campaign preview response.");
  if (duplicate !== null && (!duplicate || (duplicate.campaign_id !== null && !text(duplicate.campaign_id)) || !text(duplicate.path) || !text(duplicate.stage))) throw new Error("Invalid campaign preview response.");
  if ((duplicate === null) === (plan === null) || (plan !== null && !text(value.preview_token))) throw new Error("Invalid campaign preview response.");
  return value as unknown as CreationPreview;
}
async function mutationRequest(path: string, body: object, csrf: string): Promise<Record<string, unknown>> {
  const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
  const payload = await response.json() as { data?: Record<string, unknown>; error?: { message?: string } };
  if (!response.ok || !payload.data) throw new Error(payload.error?.message ?? "Local campaign action failed safely.");
  return payload.data;
}
export type CampaignApi = typeof campaignApi;

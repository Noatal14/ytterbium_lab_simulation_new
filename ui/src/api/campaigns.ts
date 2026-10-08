export type Warning = { severity: "info" | "attention" | "blocked"; message: string };
export type StageProgress = { stage: string; completed: number; expected: number | null; status: "not-started" | "in-progress" | "complete" | "unknown" | "inconsistent" };
export type Campaign = {
  id: string; family: "mot_2d" | "mot_3d"; kind: string; name: string; path: string; stage: string;
  stage_semantics: "prepared-workflow-stage"; scheduler_status: "unchecked";
  trust: "trusted-current" | "legacy-incomplete"; scientific_role: "candidate-selection" | "sealed-final-validation" | "historical-evidence";
  progress: StageProgress[]; warnings: Warning[];
  next_plan: null | { label: string; command: string[]; display_command: string; mode: "copy-only"; scheduler_status: "unchecked"; operation_scope: "remote-submission" | "local-mutation"; executes_automatically: false };
  s0_values: number[]; families: string[]; git_commit: string | null;
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
function parseCampaign(value: unknown): Campaign {
  if (!value || typeof value !== "object") throw new Error("Invalid campaign response.");
  const row = value as Record<string, unknown>;
  const families = ["mot_2d", "mot_3d"];
  const trusts = ["trusted-current", "legacy-incomplete"];
  const roles = ["candidate-selection", "sealed-final-validation", "historical-evidence"];
  if (!text(row.id) || !families.includes(String(row.family)) || !text(row.kind) || !text(row.name) || !text(row.path) || !text(row.stage) || row.stage_semantics !== "prepared-workflow-stage" || row.scheduler_status !== "unchecked" || !trusts.includes(String(row.trust)) || !roles.includes(String(row.scientific_role)) || !Array.isArray(row.progress) || !Array.isArray(row.warnings) || !Array.isArray(row.s0_values) || !row.s0_values.every((item) => typeof item === "number" && Number.isFinite(item)) || !Array.isArray(row.families) || !row.families.every(text) || (row.git_commit !== null && !text(row.git_commit))) throw new Error("Invalid campaign response.");
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

const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
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

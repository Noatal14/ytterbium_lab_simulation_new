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
export type CampaignApi = typeof campaignApi;

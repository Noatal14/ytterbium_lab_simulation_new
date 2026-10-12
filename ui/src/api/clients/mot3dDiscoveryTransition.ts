import { postData } from "../http/envelope";
import { boundedPrintable, exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";

type Profile = ZeusSnapshot["profile"];
type Chain = { angled_donut: string[]; single_pass: string[] };
export type Mot3DDiscoveryTransitionLifecycle =
  | "queued" | "running" | "held" | "completed_failed"
  | "outputs_invalid" | "status_unknown"
  | "completed_success_unvalidated" | "ready_to_advance"
  | "preliminary_check_prepared";
export type Mot3DDiscoveryTransitionStatus = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: "discovery" | "preliminary_check" };
  discovery: { status: Mot3DDiscoveryTransitionLifecycle; chain: Chain };
  validation: { status: "not_ready" | "invalid" | "valid"; completed_trials: number; expected_trials: 950 };
  next_action: "wait" | "inspect_zeus" | "review_transition" | "none";
  local_sync: { status: "not_synchronized" | "synchronized"; receipt_sha256: string | null };
};
export type Mot3DDiscoveryTransitionPreview = {
  preview_token: string;
  expires_in_seconds: 300;
  campaign: { id: string; name: string; git_commit: string };
  from_stage: "discovery";
  to_stage: "preliminary_check";
  discovery: { completed_trials: 950; expected_trials: 950; families: ["angled_donut", "single_pass"]; evidence_sha256: string };
  artifacts: { synchronize: { trial_registries: 950; merged_files: 4 }; create: { selection_files: 2; job_files: 4 }; update: ["campaign.json"] };
  effects: { synchronize_discovery: true; prepare_preliminary_check: true; submit_preliminary_check: false; start_simulation: false; overwrite_existing: false };
};
export type Mot3DDiscoveryTransitionResult = {
  status: "preliminary_check_prepared";
  campaign_id: string;
  stage: "preliminary_check";
  artifacts: { synchronized: 954; created: 6; updated: 1; bundle_sha256: string };
  submitted_to_zeus: false;
  simulation_started: false;
  local_sync: { status: "synchronized"; receipt_sha256: string };
};

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const JOB = /^\d+\[\]\.zeus-master$/;
const object = (value: unknown, keys: string[], message: string) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>, keys)) throw new Error(message);
  return value as Record<string, unknown>;
};
const text = (value: unknown, limit = 256): value is string => boundedPrintable(value, limit) && value.length > 0;
const integer = (value: unknown) => Number.isInteger(value) && Number(value) >= 0;
const parseChain = (value: unknown): Chain => {
  const row = object(value, ["angled_donut", "single_pass"], "Invalid 3D Discovery transition status.");
  if (!Array.isArray(row.angled_donut) || row.angled_donut.length !== 2 || !Array.isArray(row.single_pass) || row.single_pass.length !== 3 || ![row.angled_donut, row.single_pass].every((entry) => entry.every((job) => typeof job === "string" && JOB.test(job)))) throw new Error("Invalid 3D Discovery transition status.");
  return { angled_donut: [...row.angled_donut as string[]], single_pass: [...row.single_pass as string[]] };
};
const parseSync = (value: unknown) => {
  const row = object(value, ["status", "receipt_sha256"], "Invalid 3D Discovery synchronization evidence.");
  if (!(["not_synchronized", "synchronized"].includes(String(row.status))) || (row.status === "not_synchronized" ? row.receipt_sha256 !== null : typeof row.receipt_sha256 !== "string" || !SHA256.test(row.receipt_sha256))) throw new Error("Invalid 3D Discovery synchronization evidence.");
  return row as Mot3DDiscoveryTransitionStatus["local_sync"];
};

export function parseMot3DDiscoveryTransitionStatus(value: unknown): Mot3DDiscoveryTransitionStatus {
  const row = object(value, ["source", "queried_at", "campaign", "discovery", "validation", "next_action", "local_sync"], "Invalid 3D Discovery transition status.");
  const campaign = object(row.campaign, ["id", "name", "stage"], "Invalid 3D Discovery transition status.");
  const discovery = object(row.discovery, ["status", "chain"], "Invalid 3D Discovery transition status.");
  const validation = object(row.validation, ["status", "completed_trials", "expected_trials"], "Invalid 3D Discovery transition status.");
  const lifecycle = String(discovery.status) as Mot3DDiscoveryTransitionLifecycle;
  const allowed = ["queued", "running", "held", "completed_failed", "outputs_invalid", "status_unknown", "completed_success_unvalidated", "ready_to_advance", "preliminary_check_prepared"];
  const sync = parseSync(row.local_sync);
  const expected = lifecycle === "ready_to_advance"
    ? [["valid", "review_transition", "not_synchronized", "discovery"]]
    : lifecycle === "preliminary_check_prepared"
      ? [
          ["valid", "review_transition", "not_synchronized", "discovery"],
          ["valid", "none", "synchronized", "preliminary_check"],
        ]
      : [["held", "completed_failed", "outputs_invalid", "status_unknown"].includes(lifecycle)
          ? [["held", "completed_failed", "outputs_invalid"].includes(lifecycle) ? "invalid" : "not_ready", "inspect_zeus", "not_synchronized", "discovery"]
          : ["not_ready", "wait", "not_synchronized", "discovery"]];
  const observed = [validation.status, row.next_action, sync.status, campaign.stage];
  const matrixMatches = expected.some((candidate) => candidate.every((entry, index) => entry === observed[index]));
  const trialCountMatches = validation.status === "valid" ? validation.completed_trials === 950 : validation.completed_trials === 0;
  if (row.source !== "zeus" || !text(row.queried_at) || Number.isNaN(Date.parse(row.queried_at)) || !text(campaign.id, 512) || !text(campaign.name, 128) || !allowed.includes(lifecycle) || !integer(validation.completed_trials) || validation.expected_trials !== 950 || !trialCountMatches || !matrixMatches) throw new Error("Invalid 3D Discovery transition status.");
  return { source: "zeus", queried_at: row.queried_at as string, campaign: campaign as Mot3DDiscoveryTransitionStatus["campaign"], discovery: { status: lifecycle, chain: parseChain(discovery.chain) }, validation: validation as Mot3DDiscoveryTransitionStatus["validation"], next_action: row.next_action as Mot3DDiscoveryTransitionStatus["next_action"], local_sync: sync };
}

export function parseMot3DDiscoveryTransitionPreview(value: unknown, expected: { campaignId: string }): Mot3DDiscoveryTransitionPreview {
  const row = object(value, ["preview_token", "expires_in_seconds", "campaign", "from_stage", "to_stage", "discovery", "artifacts", "effects"], "Invalid 3D Discovery transition review.");
  const campaign = object(row.campaign, ["id", "name", "git_commit"], "Invalid 3D Discovery transition review.");
  const discovery = object(row.discovery, ["completed_trials", "expected_trials", "families", "evidence_sha256"], "Invalid 3D Discovery transition review.");
  const artifacts = object(row.artifacts, ["synchronize", "create", "update"], "Invalid 3D Discovery transition review.");
  const synchronize = object(artifacts.synchronize, ["trial_registries", "merged_files"], "Invalid 3D Discovery transition review.");
  const create = object(artifacts.create, ["selection_files", "job_files"], "Invalid 3D Discovery transition review.");
  const effects = object(row.effects, ["synchronize_discovery", "prepare_preliminary_check", "submit_preliminary_check", "start_simulation", "overwrite_existing"], "Invalid 3D Discovery transition review.");
  if (!text(row.preview_token, 512) || row.expires_in_seconds !== 300 || campaign.id !== expected.campaignId || !text(campaign.name, 128) || typeof campaign.git_commit !== "string" || !SHA40.test(campaign.git_commit) || row.from_stage !== "discovery" || row.to_stage !== "preliminary_check" || discovery.completed_trials !== 950 || discovery.expected_trials !== 950 || JSON.stringify(discovery.families) !== JSON.stringify(["angled_donut", "single_pass"]) || typeof discovery.evidence_sha256 !== "string" || !SHA256.test(discovery.evidence_sha256) || synchronize.trial_registries !== 950 || synchronize.merged_files !== 4 || create.selection_files !== 2 || create.job_files !== 4 || JSON.stringify(artifacts.update) !== JSON.stringify(["campaign.json"]) || effects.synchronize_discovery !== true || effects.prepare_preliminary_check !== true || effects.submit_preliminary_check !== false || effects.start_simulation !== false || effects.overwrite_existing !== false) throw new Error("Invalid 3D Discovery transition review.");
  return row as unknown as Mot3DDiscoveryTransitionPreview;
}

export function parseMot3DDiscoveryTransitionResult(value: unknown, campaignId: string): Mot3DDiscoveryTransitionResult {
  const row = object(value, ["status", "campaign_id", "stage", "artifacts", "submitted_to_zeus", "simulation_started", "local_sync"], "Invalid 3D Discovery transition result.");
  const artifacts = object(row.artifacts, ["synchronized", "created", "updated", "bundle_sha256"], "Invalid 3D Discovery transition result.");
  const sync = parseSync(row.local_sync);
  if (row.status !== "preliminary_check_prepared" || row.campaign_id !== campaignId || row.stage !== "preliminary_check" || artifacts.synchronized !== 954 || artifacts.created !== 6 || artifacts.updated !== 1 || typeof artifacts.bundle_sha256 !== "string" || !SHA256.test(artifacts.bundle_sha256) || row.submitted_to_zeus !== false || row.simulation_started !== false || sync.status !== "synchronized") throw new Error("Invalid 3D Discovery transition result.");
  return row as unknown as Mot3DDiscoveryTransitionResult;
}

export function createMot3DDiscoveryTransitionApi(session: () => Promise<string>) {
  const contexts = new Map<string, { campaignId: string; csrf: string }>();
  const body = (campaign_id: string, profile: Profile) => ({ campaign_id, username: profile.username, project_directory: profile.project_directory });
  return {
    async status(campaignId: string, profile: Profile) { const csrf = await session(); const value = parseMot3DDiscoveryTransitionStatus(await postData("/api/v1/zeus/mot-3d/discovery-transition/status", body(campaignId, profile), csrf)); if (value.campaign.id !== campaignId) throw new Error("3D Discovery transition status did not match the selected campaign."); return value; },
    async preview(campaignId: string, profile: Profile) { const csrf = await session(); const value = parseMot3DDiscoveryTransitionPreview(await postData("/api/v1/zeus/mot-3d/discovery-transition/preview", body(campaignId, profile), csrf), { campaignId }); contexts.set(value.preview_token, { campaignId, csrf }); return value; },
    async confirm(preview_token: string) { const context = contexts.get(preview_token); if (!context) throw new Error("The Discovery synchronization review is no longer active."); contexts.delete(preview_token); return parseMot3DDiscoveryTransitionResult(await postData("/api/v1/zeus/mot-3d/discovery-transition/confirm", { preview_token }, context.csrf), context.campaignId); },
    reset() { contexts.clear(); },
  };
}
export const mot3DDiscoveryTransitionApi = createMot3DDiscoveryTransitionApi(() => creationApi.session());
export type Mot3DDiscoveryTransitionApi = ReturnType<typeof createMot3DDiscoveryTransitionApi>;

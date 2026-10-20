import { reviewedCampaignResource, campaignCores, campaignMemory, campaignWalltime, campaignParticles, campaignPools, campaignDiscoveryTargets, campaignDiscoveryTrials } from "../campaignPolicy";
import { MOT_3D_TIMESTEP_POLICY_V2 } from "../../generated/mot3dTimestepPolicy.v2";
import { postData } from "../http/envelope";
import { boundedPrintable, exactKeys } from "../schema/common";
import type { ZeusSnapshot } from "../schema/domain";
import { creationApi } from "./campaign";

type Profile = ZeusSnapshot["profile"];
type Chain = { angled_donut: string[]; single_pass: string[] };
export type Mot3DDiscoveryLifecycle =
  | "not_submitted"
  | "submitted"
  | "queued"
  | "running"
  | "held"
  | "completed_success"
  | "completed_failed"
  | "status_unknown"
  | "outcome_unknown";
export type Mot3DDiscoveryStatus = {
  source: "zeus";
  queried_at: string;
  campaign: { id: string; name: string; stage: "discovery" };
  submission: { status: Mot3DDiscoveryLifecycle; chain: Chain };
  next_action:
    "review_submission" | "wait" | "validate_outputs" | "inspect_zeus";
  local_sync: { status: "not_synchronized" };
};
export type Mot3DDiscoveryPreview = {
  preview_token: string;
  expires_in_seconds: 300;
  campaign: { id: string; name: string; git_commit: string };
  stage: { id: "discovery"; label: "Discovery" };
  chain: {
    families: [
      { id: "angled_donut"; rounds: 2 },
      { id: "single_pass"; rounds: 3 },
    ];
    arrays: 5;
    tasks_per_array: 3;
    dependency: "afterok within each family";
  };
  remote: {
    host: "zeus.technion.ac.il";
    project_directory: string;
    commit: string;
    branch: string;
    dirty: false;
  };
  resources: {array:{ncpus_per_task:number;memory_gb_per_task:number;walltime:string;vnode?:"gd002"}};
  science: {classification:"candidate_selection_not_final_validation";input_role:"discovery";input_ensembles:12;particles_per_ensemble:number;total_particles_per_trial:number;npools:number;dt_s:number;t_max_s:number;solver:string;final_trial_targets:{angled_donut:number[];single_pass:number[]};total_trials:number};
  effects: {
    submit_discovery_chain: true;
    submit_smoke: false;
    submit_later_stages: false;
    modify_campaign_files: false;
    record_submission_receipt: true;
  };
};
export type Mot3DDiscoveryResult = {
  status: "submitted";
  campaign_id: string;
  stage: "discovery";
  chain: Chain;
  submitted_at: string;
  local_sync: { status: "not_synchronized" };
};

const SHA40 = /^[0-9a-f]{40}$/;
const JOB = /^\d+\[\]\.zeus-master$/;
const LIFECYCLES = new Set<Mot3DDiscoveryLifecycle>([
  "not_submitted",
  "submitted",
  "queued",
  "running",
  "held",
  "completed_success",
  "completed_failed",
  "status_unknown",
  "outcome_unknown",
]);
const object = (value: unknown, keys: string[], message: string) => {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, keys)
  )
    throw new Error(message);
  return value as Record<string, unknown>;
};
const text = (value: unknown, limit = 256): value is string =>
  boundedPrintable(value, limit) && value.length > 0;
const parseChain = (value: unknown, populated: boolean): Chain => {
  const row = object(
    value,
    ["angled_donut", "single_pass"],
    "Invalid 3D Discovery chain.",
  );
  const expected = populated ? [2, 3] : [0, 0];
  const values = [row.angled_donut, row.single_pass];
  if (
    values.some(
      (entry, index) =>
        !Array.isArray(entry) ||
        entry.length !== expected[index] ||
        entry.some((job) => typeof job !== "string" || !JOB.test(job)),
    )
  )
    throw new Error("Invalid 3D Discovery chain.");
  return {
    angled_donut: [...(row.angled_donut as string[])],
    single_pass: [...(row.single_pass as string[])],
  };
};
const parseCampaign = (value: unknown, withCommit = false) => {
  const keys = withCommit
    ? ["id", "name", "git_commit"]
    : ["id", "name", "stage"];
  const row = object(value, keys, "Invalid 3D Discovery campaign response.");
  if (
    !text(row.id, 512) ||
    !text(row.name, 128) ||
    (withCommit
      ? typeof row.git_commit !== "string" || !SHA40.test(row.git_commit)
      : row.stage !== "discovery")
  )
    throw new Error("Invalid 3D Discovery campaign response.");
  return row;
};
const parseSync = (value: unknown) => {
  const row = object(value, ["status"], "Invalid 3D Discovery response.");
  if (row.status !== "not_synchronized")
    throw new Error("Invalid 3D Discovery response.");
  return { status: "not_synchronized" as const };
};

export function parseMot3DDiscoveryStatus(
  value: unknown,
): Mot3DDiscoveryStatus {
  const row = object(
    value,
    [
      "source",
      "queried_at",
      "campaign",
      "submission",
      "next_action",
      "local_sync",
    ],
    "Invalid 3D Discovery status.",
  );
  const campaign = parseCampaign(row.campaign);
  const submission = object(
    row.submission,
    ["status", "chain"],
    "Invalid 3D Discovery status.",
  );
  if (
    row.source !== "zeus" ||
    !text(row.queried_at) ||
    Number.isNaN(Date.parse(row.queried_at)) ||
    typeof submission.status !== "string" ||
    !LIFECYCLES.has(submission.status as Mot3DDiscoveryLifecycle)
  )
    throw new Error("Invalid 3D Discovery status.");
  const status = submission.status as Mot3DDiscoveryLifecycle;
  const populated = status !== "not_submitted" && status !== "outcome_unknown";
  const expectedAction =
    status === "not_submitted"
      ? "review_submission"
      : ["submitted", "queued", "running"].includes(status)
        ? "wait"
        : status === "completed_success"
          ? "validate_outputs"
          : "inspect_zeus";
  if (row.next_action !== expectedAction)
    throw new Error("Invalid 3D Discovery status.");
  return {
    source: "zeus",
    queried_at: row.queried_at as string,
    campaign: campaign as Mot3DDiscoveryStatus["campaign"],
    submission: { status, chain: parseChain(submission.chain, populated) },
    next_action: expectedAction,
    local_sync: parseSync(row.local_sync),
  };
}

export function parseMot3DDiscoveryPreview(
  value: unknown,
  expected: { campaignId: string; profile: Profile },
): Mot3DDiscoveryPreview {
  const row = object(
    value,
    [
      "preview_token",
      "expires_in_seconds",
      "campaign",
      "stage",
      "chain",
      "resources",
      "science",
      "remote",
      "effects",
    ],
    "Invalid 3D Discovery review.",
  );
  const campaign = parseCampaign(row.campaign, true);
  const stage = object(
    row.stage,
    ["id", "label"],
    "Invalid 3D Discovery review.",
  );
  const chain = object(
    row.chain,
    ["families", "arrays", "tasks_per_array", "dependency"],
    "Invalid 3D Discovery review.",
  );
  const remote = object(
    row.remote,
    ["host", "project_directory", "commit", "branch", "dirty"],
    "Invalid 3D Discovery review.",
  );
  const effects = object(
    row.effects,
    [
      "submit_discovery_chain",
      "submit_smoke",
      "submit_later_stages",
      "modify_campaign_files",
      "record_submission_receipt",
    ],
    "Invalid 3D Discovery review.",
  );
  const resources = object(row.resources, ["array"], "Invalid Discovery resource review.");
  const array = reviewedCampaignResource(resources.array, ["ncpus_per_task","memory_gb_per_task","walltime"], "Invalid Discovery resource review.");
  const science = object(row.science, ["classification","input_role","input_ensembles","particles_per_ensemble","total_particles_per_trial","npools","dt_s","t_max_s","solver","final_trial_targets","total_trials"], "Invalid Discovery workload review.");
  if (array.ncpus_per_task !== campaignCores() || array.memory_gb_per_task !== campaignMemory() || array.walltime !== campaignWalltime()
      || science.classification !== "candidate_selection_not_final_validation" || science.input_role !== "discovery" || science.input_ensembles !== 12
      || science.particles_per_ensemble !== campaignParticles(50) || science.total_particles_per_trial !== 12 * campaignParticles(50)
      || science.npools !== campaignPools() || science.dt_s !== MOT_3D_TIMESTEP_POLICY_V2.search_dt_s || science.t_max_s !== MOT_3D_TIMESTEP_POLICY_V2.t_max_s
      || science.solver !== MOT_3D_TIMESTEP_POLICY_V2.solver || science.total_trials !== campaignDiscoveryTrials()
      || JSON.stringify(science.final_trial_targets) !== JSON.stringify(campaignDiscoveryTargets())) throw new Error("Discovery resources or physical workload do not match the reviewed policy.");
  const families = chain.families;
  if (
    !text(row.preview_token, 512) ||
    row.expires_in_seconds !== 300 ||
    campaign.id !== expected.campaignId ||
    stage.id !== "discovery" ||
    stage.label !== "Discovery" ||
    !Array.isArray(families) ||
    families.length !== 2
  )
    throw new Error("Invalid 3D Discovery review.");
  const first = object(
    families[0],
    ["id", "rounds"],
    "Invalid 3D Discovery review.",
  );
  const second = object(
    families[1],
    ["id", "rounds"],
    "Invalid 3D Discovery review.",
  );
  if (
    first.id !== "angled_donut" ||
    first.rounds !== 2 ||
    second.id !== "single_pass" ||
    second.rounds !== 3 ||
    chain.arrays !== 5 ||
    chain.tasks_per_array !== 3 ||
    chain.dependency !== "afterok within each family" ||
    remote.host !== expected.profile.host ||
    remote.project_directory !== expected.profile.project_directory ||
    remote.commit !== campaign.git_commit ||
    !text(remote.branch) ||
    remote.dirty !== false ||
    effects.submit_discovery_chain !== true ||
    effects.submit_smoke !== false ||
    effects.submit_later_stages !== false ||
    effects.modify_campaign_files !== false ||
    effects.record_submission_receipt !== true
  )
    throw new Error("Invalid 3D Discovery review.");
  return row as unknown as Mot3DDiscoveryPreview;
}

export function parseMot3DDiscoveryResult(
  value: unknown,
  campaignId: string,
): Mot3DDiscoveryResult {
  const row = object(
    value,
    ["status", "campaign_id", "stage", "chain", "submitted_at", "local_sync"],
    "Invalid 3D Discovery result.",
  );
  if (
    row.status !== "submitted" ||
    row.campaign_id !== campaignId ||
    row.stage !== "discovery" ||
    !text(row.submitted_at) ||
    Number.isNaN(Date.parse(row.submitted_at))
  )
    throw new Error("Invalid 3D Discovery result.");
  return {
    ...row,
    chain: parseChain(row.chain, true),
    local_sync: parseSync(row.local_sync),
  } as Mot3DDiscoveryResult;
}

export function createMot3DDiscoveryApi(session: () => Promise<string>) {
  const contexts = new Map<
    string,
    { campaignId: string; csrf: string; profile: Profile }
  >();
  const body = (campaign_id: string, profile: Profile) => ({
    campaign_id,
    username: profile.username,
    project_directory: profile.project_directory,
  });
  return {
    async status(campaignId: string, profile: Profile) {
      const csrf = await session();
      const value = parseMot3DDiscoveryStatus(
        await postData(
          "/api/v1/zeus/submissions/mot-3d-discovery/status",
          body(campaignId, profile),
          csrf,
        ),
      );
      if (value.campaign.id !== campaignId)
        throw new Error(
          "3D Discovery status did not match the selected campaign.",
        );
      return value;
    },
    async preview(campaignId: string, profile: Profile) {
      const csrf = await session();
      const value = parseMot3DDiscoveryPreview(
        await postData(
          "/api/v1/zeus/submissions/mot-3d-discovery/preview",
          body(campaignId, profile),
          csrf,
        ),
        { campaignId, profile },
      );
      contexts.set(value.preview_token, {
        campaignId,
        csrf,
        profile: { ...profile },
      });
      return value;
    },
    async confirm(token: string) {
      const context = contexts.get(token);
      if (!context)
        throw new Error("The 3D Discovery review is no longer active.");
      contexts.delete(token);
      return parseMot3DDiscoveryResult(
        await postData(
          "/api/v1/zeus/submissions/mot-3d-discovery/confirm",
          { preview_token: token },
          context.csrf,
        ),
        context.campaignId,
      );
    },
    reset() {
      contexts.clear();
    },
  };
}
export type Mot3DDiscoveryApi = ReturnType<typeof createMot3DDiscoveryApi>;
export const mot3DDiscoveryApi = createMot3DDiscoveryApi(() =>
  creationApi.session(),
);

/** Explicit versioned workload contract; scientific defaults remain immutable. */
import { MOT_2D_SPECIFICATION_V1 as scientific } from "../generated/mot2dSpec.v1";
import { MOT_2D_ACCEPTANCE_SPECIFICATION, UI_ACCEPTANCE_POLICY } from "../generated/uiAcceptance.v1";
import { exactKeys } from "./schema/common";
import { campaignAcceptanceMode } from "./zeusEnvironment";

export const MOT_2D_SPECIFICATION_V1 = campaignAcceptanceMode() ? MOT_2D_ACCEPTANCE_SPECIFICATION : scientific;
export function campaignDiscoveryTrials(): number { return campaignAcceptanceMode() ? Object.values(UI_ACCEPTANCE_POLICY.mot_3d.discovery_targets).flat().reduce((sum, count) => sum + count, 0) : 950; }
export function campaignParticles(scientificCount: number): number { return campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.stages.discovery.particles_per_ensemble : scientificCount; }
export function campaignPools(): number { return campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.stages.discovery.npools : 200; }
export function campaignCores(scientificCount = 200): number { return campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.stages.discovery.ncpus : scientificCount; }
export function campaignMemory(scientificGB = 64): number { return campaignAcceptanceMode() ? 4 : scientificGB; }
export function campaignWalltime(scientificTime = "24:00:00"): string { return campaignAcceptanceMode() ? "01:00:00" : scientificTime; }

export function campaignTotalParticles(scientificCount: number): number { return campaignAcceptanceMode() ? 4 : scientificCount; }

export function campaignDiscoveryTargets() {
  return campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.discovery_targets : {angled_donut:[117,117,116],single_pass:[200,200,200]};
}

/** Resource extensions are authorized only by the frozen test profile. */
export function reviewedCampaignResource(value: unknown, keys: string[], message = "Invalid reviewed campaign resources."): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(message);
  const row = value as Record<string, unknown>;
  const scheduler = (UI_ACCEPTANCE_POLICY as unknown as {scheduler?: {vnode?: string}}).scheduler;
  const vnode = campaignAcceptanceMode() ? scheduler?.vnode : undefined;
  if (!exactKeys(row, vnode ? [...keys, "vnode"] : keys) || (vnode && row.vnode !== vnode)) throw new Error(message);
  return row;
}

export function campaignGenerationJob(name: "zeeman" | "mot_2d" | "freeze", scientific: [number,number,string]): [number,number,string] {
  if (!campaignAcceptanceMode()) return scientific;
  const jobs = (UI_ACCEPTANCE_POLICY as unknown as {generation: {jobs: Record<string,{ncpus:number,memory_gb:number,walltime_seconds:number}>}}).generation.jobs;
  const job = jobs[name];
  if (!job) throw new Error("Missing frozen generation job resources.");
  const hours = String(Math.floor(job.walltime_seconds / 3600)).padStart(2,"0");
  const minutes = String(Math.floor(job.walltime_seconds % 3600 / 60)).padStart(2,"0");
  const seconds = String(job.walltime_seconds % 60).padStart(2,"0");
  return [job.ncpus, job.memory_gb, `${hours}:${minutes}:${seconds}`];
}
export function campaignGenerationPools(): number {
  if (!campaignAcceptanceMode()) return 200;
  return (UI_ACCEPTANCE_POLICY as unknown as {generation:{jobs:{mot_2d:{npools:number}}}}).generation.jobs.mot_2d.npools;
}

export function campaignTestNode(): string | undefined {
  return campaignAcceptanceMode() ? (UI_ACCEPTANCE_POLICY as unknown as {scheduler?:{vnode?:string}}).scheduler?.vnode : undefined;
}


export type Campaign3DResourceStage = "closure" | "finalist_selection" | "final_validation";
export function campaignStagePools(stage: Campaign3DResourceStage): number {
  return campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.stages[stage].npools : 200;
}
/** Validate the actual stage resources before the shared envelope parser runs. */
export function reviewedCampaignStageArray(value: unknown, stage: Campaign3DResourceStage): Record<string, unknown> {
  const policy = campaignAcceptanceMode() ? UI_ACCEPTANCE_POLICY.mot_3d.stages[stage] : undefined;
  const throttle = policy && "array_throttle" in policy ? policy.array_throttle : undefined;
  const keys = ["ncpus_per_task", "memory_gb_per_task", "walltime", ...(throttle === undefined ? [] : ["array_throttle"])];
  const row = reviewedCampaignResource(value, keys);
  if (row.ncpus_per_task !== (policy?.ncpus ?? 200)
      || row.memory_gb_per_task !== (policy?.memory_gb ?? 64)
      || row.walltime !== (policy ? campaignWalltime() : "24:00:00")
      || (throttle !== undefined && row.array_throttle !== throttle)) throw new Error("Invalid stage-specific campaign resources.");
  return row;
}

import { afterEach, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { parseMot3DFinalistSubmissionPreview } from "../api/clients/mot3dFinalistSubmission";
import { parseMot3DFinalValidationSubmissionPreview } from "../api/clients/mot3dFinalValidationSubmission";
import { UI_ACCEPTANCE_POLICY } from "../generated/uiAcceptance.v1";
import { parsePreliminaryCheckPreview } from "../api/clients/mot3dPreliminaryCheck";
import { parseCampaign } from "../api/schema/domain";
import { reviewedCampaignStageArray, campaignDiscoveryTrials, campaignCores, campaignTestNode } from "../api/campaignPolicy";
import { campaignAcceptanceMode, zeusProjectDirectory } from "../api/zeusEnvironment";

// Begin with the frozen HTTP contract and change only reviewed workload fields.
const fixture = () => JSON.parse(JSON.stringify(success.cases.find(row => row.id === "mot3d-preliminary-preview")!.body.data));
const profile = (project: string) => ({host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: project, authentication: "ssh-key-or-agent" as const});
afterEach(() => vi.unstubAllEnvs());

it("requires miniature resources while preserving physical settings in acceptance mode", () => {
  vi.stubEnv("MODE", "ui-acceptance");
  expect(campaignAcceptanceMode()).toBe(true);
  const project = zeusProjectDirectory("tal.noa");
  expect(project).toBe("/home/tal.noa/ytterbium_lab_simulation_ui_acceptance");
  expect(campaignDiscoveryTrials()).toBe(24);
  const row = fixture();
  row.resources.array = {ncpus_per_task:campaignCores(), memory_gb_per_task:4, walltime:"01:00:00", vnode:campaignTestNode()};
  row.resources.merge.vnode=campaignTestNode();
  row.science.particles_per_ensemble = 1;
  row.science.total_particles = 4;
  row.remote.project_directory = project;
  const parsed = parsePreliminaryCheckPreview(row, {campaignId:"campaign-id", profile:profile(project)});
  expect(parsed.science).toMatchObject({particles_per_ensemble:1, total_particles:4,dt_s:1e-5,t_max_s:0.05});
  row.resources.array.ncpus_per_task = 200;
  expect(() => parsePreliminaryCheckPreview(row, {campaignId:"campaign-id", profile:profile(project)})).toThrow();
});

it("keeps the original scientific resource contract", () => {
  vi.stubEnv("MODE", "development");
  expect(campaignDiscoveryTrials()).toBe(950);
  const project = zeusProjectDirectory("tal.noa"), row = fixture();
  expect(parsePreliminaryCheckPreview(row, {campaignId:"campaign-id", profile:profile(project)}).science.total_particles).toBe(600);
  row.science.particles_per_ensemble = 1;
  row.science.total_particles = 4;
  expect(() => parsePreliminaryCheckPreview(row, {campaignId:"campaign-id", profile:profile(project)})).toThrow();
});

it("rejects scientific campaigns under the TEST ONLY banner", () => {
  vi.stubEnv("MODE", "ui-acceptance");
  const row = JSON.parse(JSON.stringify(success.cases.find(item => item.id === "campaign-detail")!.body.data));
  expect(() => parseCampaign(row)).toThrow(/environment/);
});


it.each([
  ["finalist_selection", "mot3d-finalist-preview", parseMot3DFinalistSubmissionPreview],
  ["final_validation", "mot3d-final-validation-preview", parseMot3DFinalValidationSubmissionPreview],
] as const)("authenticates bounded heavy-stage resources without changing %s physics", (stage, id, parse) => {
  vi.stubEnv("MODE", "ui-acceptance");
  const contract = success.cases.find(row => row.id === id);
  expect(contract, id).toBeDefined();
  const row = JSON.parse(JSON.stringify(contract!.body.data));
  const project = zeusProjectDirectory("tal.noa");
  row.remote.project_directory = project;
  const policy = UI_ACCEPTANCE_POLICY.mot_3d.stages[stage];
  row.resources.array = {ncpus_per_task:policy.ncpus, memory_gb_per_task:policy.memory_gb, walltime:"01:00:00", vnode:campaignTestNode(), array_throttle:1};
  row.resources.merge = {ncpus:1,memory_gb:4,walltime:"01:00:00",vnode:campaignTestNode()};
  row.science.npools = policy.npools;
  const expected = {campaignId:row.campaign.id, profile:profile(project)};
  expect(parse(row,expected).resources.array).toEqual(row.resources.array);
  expect(() => reviewedCampaignStageArray(row.resources.array,"closure")).toThrow();
  expect(row.science.t_max_s).toBe(0.05);
  expect(row.science.dt_s).toBe(stage === "final_validation" ? 5e-6 : 1e-5);
  for (const [key,bad] of [["ncpus_per_task",4],["memory_gb_per_task",4],["array_throttle",2],["walltime","24:00:00"],["vnode","gd003"]] as const) {
    const altered = structuredClone(row);altered.resources.array[key] = bad;
    expect(() => parse(altered,expected),key).toThrow();
  }
  const missing = structuredClone(row);delete missing.resources.array.array_throttle;
  expect(() => parse(missing,expected)).toThrow();
  const unknown = structuredClone(row);unknown.resources.array.unreviewed = true;
  expect(() => parse(unknown,expected)).toThrow();
  vi.stubEnv("MODE","development");
  expect(() => parse(row,expected)).toThrow();
});

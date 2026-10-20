import { afterEach, expect, it, vi } from "vitest";
import success from "../../../tests/contracts/v1/workflow_api_success.json";
import { parsePreliminaryCheckPreview } from "../api/clients/mot3dPreliminaryCheck";
import { parseCampaign } from "../api/schema/domain";
import { campaignDiscoveryTrials, campaignCores, campaignTestNode } from "../api/campaignPolicy";
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

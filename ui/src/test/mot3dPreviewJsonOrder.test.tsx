import { zeusProjectDirectory } from "../api/zeusEnvironment";
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import contracts from "./teamContractFixture";
import actual from "./fixtures/p45-preliminary-preview.sanitized.json";
import { createPreliminaryCheckApi, parsePreliminaryCheckPreview } from "../api/clients/mot3dPreliminaryCheck";
import { parseMot3DRefinementSubmissionPreview } from "../api/clients/mot3dRefinementSubmission";
import { parseMot3DClosureSubmissionPreview } from "../api/clients/mot3dClosureSubmission";
import { parseMot3DFinalistSubmissionPreview } from "../api/clients/mot3dFinalistSubmission";
import { parseMot3DFinalValidationSubmissionPreview } from "../api/clients/mot3dFinalValidationSubmission";
import { UI_ACCEPTANCE_POLICY } from "../generated/uiAcceptance.v1";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DPreliminaryCheckController } from "../features/campaign/controllers/useMot3DPreliminaryCheckController";

const profile = () => ({ host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: zeusProjectDirectory("tal.noa"), authentication: "ssh-key-or-agent" as const });
const definitions = [
  ["preliminary_check", "mot3d-preliminary-preview", parsePreliminaryCheckPreview],
  ["refinement", "mot3d-refinement-preview", parseMot3DRefinementSubmissionPreview],
  ["closure", "mot3d-closure-preview", parseMot3DClosureSubmissionPreview],
  ["finalist_selection", "mot3d-finalist-preview", parseMot3DFinalistSubmissionPreview],
  ["final_validation", "mot3d-final-validation-preview", parseMot3DFinalValidationSubmissionPreview],
] as const;
function sortedJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedJson);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, sortedJson(entry)]));
  return value;
}
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("accepts the actual sanitized P45 preview through the real client and controller", async () => {
  vi.stubEnv("MODE", "ui-acceptance");
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { requests.push(url); expect(url).toBe("/api/v1/zeus/submissions/mot-3d-preliminary-check/preview"); return new Response(JSON.stringify({api_version:1,data:actual}), {status:200}); }));
  const api = createPreliminaryCheckApi(async () => "csrf");
  const p = profile();
  const snapshot = { connection_status: "connected" as const, profile:p, remote:{project_directory:p.project_directory,git_commit:actual.campaign.git_commit,branch:"test",dirty:false},scheduler:{status:"available" as const,queried_at:"2026-10-21T00:00:00Z",jobs:[]} };
  const { result } = renderHook(() => useMot3DPreliminaryCheckController({ campaignId:actual.campaign.id, snapshot, enabled:true, api }));
  await act(async () => { await result.current.review(); });
  expect(result.current.state).toBe("review");
  expect(result.current.preview?.resources.array).toEqual(actual.resources.array);
  expect(result.current.error).toBe("");
  render(<Mot3DCampaignFlow stage="preliminary_check" connected discovery={{state:"submitted",status:null} as never} transition={{state:"prepared",status:null} as never} preliminary={result.current} onConnectZeus={vi.fn()} onViewJobs={vi.fn()} />);
  expect(screen.getByText("4 CPUs · 4 GiB · 01:00:00 · Node gd002")).toBeVisible();
  expect(screen.getByRole("button",{name:"Submit preliminary check to Zeus"})).toBeEnabled();
  expect(requests).toHaveLength(1); // No confirm or job submission.
});

for (const mode of ["development", "ui-acceptance"]) {
  it.each(definitions)(`accepts sorted server JSON for %s in ${mode} and keeps topology/policy closed`, (stage, id, parse) => {
    vi.stubEnv("MODE", mode);
    const contract = contracts.cases.find(c => c.id === id);
    expect(contract, id).toBeDefined();
    const row = structuredClone(contract!.body.data) as unknown as typeof actual & {local_sync?:unknown};
    const p = profile();
    if (mode === "ui-acceptance") {
      const policy = UI_ACCEPTANCE_POLICY.mot_3d.stages[stage];
      row.remote.project_directory = p.project_directory;
      row.resources.array = { ncpus_per_task:policy.ncpus,memory_gb_per_task:policy.memory_gb,walltime:"01:00:00",vnode:"gd002",...("array_throttle" in policy ? {array_throttle:policy.array_throttle}: {}) } as typeof actual.resources.array;
      row.resources.merge = {ncpus:1,memory_gb:4,walltime:"01:00:00",vnode:"gd002"};
      if ("particles_per_ensemble" in row.science) { row.science.particles_per_ensemble=1;row.science.total_particles=4; }
      if ("npools" in row.science) (row.science as unknown as {npools:number}).npools=policy.npools;
    }
    const expected = {campaignId:row.campaign.id,profile:p};
    const sorted = sortedJson(row) as typeof row;
    expect(parse(sorted, expected).chain.families).toEqual(row.chain.families);
    for (const mutation of ["extra", "missing", "duplicate", "reorder", "type", "count", "null"] as const) {
      const bad = structuredClone(sorted);
      if (mutation === "extra") Object.assign(bad.chain.families[0],{unreviewed:true});
      if (mutation === "missing") delete (bad.chain.families[0] as Partial<typeof bad.chain.families[0]>).merge_jobs;
      if (mutation === "duplicate") bad.chain.families[1].id=bad.chain.families[0].id;
      if (mutation === "reorder") bad.chain.families.reverse();
      if (mutation === "type") Object.assign(bad.chain.families[0],{array_tasks:"3"});
      if (mutation === "count") bad.chain.families[0].array_tasks=4;
      if (mutation === "null") Object.assign(bad.chain,{families:null});
      expect(() => parse(bad,expected),mutation).toThrow();
    }
    for (const [key,value] of [["dt_s",1e-3],["t_max_s",0.1],["classification","unbiased_final_validation"],["input_ensembles",999],["solver","unreviewed_solver"],["recoil_seeds",[1,2,3]]] as const) {
      const bad=structuredClone(sorted);Object.assign(bad.science,{[key]:value});expect(()=>parse(bad,expected),key).toThrow();
    }
    const resources=structuredClone(sorted);resources.resources.array.ncpus_per_task=999;expect(()=>parse(resources,expected)).toThrow();
    vi.stubEnv("MODE",mode === "development" ? "ui-acceptance":"development");
    expect(()=>parse(sorted,expected)).toThrow();
  });
}

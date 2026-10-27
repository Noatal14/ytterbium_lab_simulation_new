import { afterEach, expect, it, vi } from "vitest";
import success from "./teamContractFixture";

const fixture = () => structuredClone(success.cases.find(row => row.id === "smoke-submit-preview")!.body.data) as any;
afterEach(() => {vi.unstubAllEnvs();vi.resetModules();});
it("accepts only the isolated 2D smoke resources and destination in TEST ONLY mode", async () => {
  vi.stubEnv("MODE", "ui-acceptance"); vi.resetModules();
  const {parseSmokeSubmissionPreview} = await import("../api/schema/domain");
  const {UI_ACCEPTANCE_POLICY} = await import("../generated/uiAcceptance.v1");
  const policy = UI_ACCEPTANCE_POLICY.mot_2d.stages.smoke;
  const row = fixture();
  row.remote.project_directory = "/home/tal.noa/ytterbium_lab_simulation_ui_acceptance";
  row.job.cores_per_task=policy.ncpus;
  row.job.memory_per_task_bytes=policy.memory_gb*1024**3;
  row.job.walltime_seconds=policy.walltime_seconds;
  const node=(UI_ACCEPTANCE_POLICY as any).scheduler?.vnode;
  if(node)row.job.vnode=node;
  expect(parseSmokeSubmissionPreview(row).job.cores_per_task).toBe(policy.ncpus);
  row.remote.project_directory="/home/tal.noa/ytterbium_lab_simulation_ui";
  expect(()=>parseSmokeSubmissionPreview(row)).toThrow();
  row.remote.project_directory="/home/tal.noa/ytterbium_lab_simulation_ui_acceptance";
  row.job.vnode="unreviewed-node";
  expect(()=>parseSmokeSubmissionPreview(row)).toThrow();
});

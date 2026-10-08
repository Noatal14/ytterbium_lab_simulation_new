import { campaignApi } from "../api/campaigns";

describe("campaign API runtime validation", () => {
  it("rejects malformed nested status data instead of rendering it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ data: { campaigns: [{
        id: "x", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "bad", path: "data/x", stage: "screen",
        stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked",
        trust: "trusted-current", scientific_role: "candidate-selection",
        progress: [{ stage: "screen", completed: 1, expected: 2, status: "executing" }],
        warnings: [], next_plan: null, s0_values: [1.3], families: [], git_commit: "abc",
      }], invalid_count: 0, total: 1 } }),
    })));
    await expect(campaignApi.list()).rejects.toThrow("Invalid campaign progress response");
    vi.unstubAllGlobals();
  });

  it.each([
    ["missing kind", { kind: undefined }],
    ["non-finite s0", { s0_values: [Number.NaN] }],
    ["invalid family list", { families: [3] }],
    ["negative progress", { progress: [{ stage: "screen", completed: -1, expected: 2, status: "in-progress" }] }],
    ["missing action label", { next_plan: { command: ["qsub", "x"], display_command: "qsub x", mode: "copy-only", scheduler_status: "unchecked", operation_scope: "remote-submission", executes_automatically: false } }],
  ])("rejects %s", async (_label, override) => {
    const base = {
      id: "x", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "bad", path: "data/x", stage: "screen",
      stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current",
      scientific_role: "candidate-selection", progress: [], warnings: [], next_plan: null,
      s0_values: [1.3], families: [], git_commit: "abc",
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [{ ...base, ...override }], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow();
    vi.unstubAllGlobals();
  });

  it("rejects inconsistent list totals", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow("Invalid campaign list response");
    vi.unstubAllGlobals();
  });
});

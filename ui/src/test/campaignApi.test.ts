import { campaignApi, zeusApi, ZeusApiError } from "../api/campaigns";

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

  it("requests a session only when a Zeus snapshot is explicitly requested", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: {
        connection_status: "connected",
        profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
        remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
        scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1", name: "test", raw_state: "H", state: "held_attention", exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] }] },
      } }) });
    vi.stubGlobal("fetch", fetchMock);
    expect(fetchMock).not.toHaveBeenCalled();
    const snapshot = await zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new");
    expect(snapshot.scheduler.jobs[0].raw_state).toBe("H");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/zeus/snapshot", expect.objectContaining({
      method: "POST", credentials: "same-origin", body: JSON.stringify({ username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new" }),
      headers: expect.objectContaining({ "X-CSRF-Token": "csrf-token" }),
    }));
    vi.unstubAllGlobals();
  });

  it("fails closed on malformed Zeus job state", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: {
        connection_status: "connected",
        profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
        remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
        scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1", name: "bad", raw_state: "R", state: "finished", exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] }] },
      } }) }));
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toThrow("Invalid Zeus job response");
    vi.unstubAllGlobals();
  });

  it("accepts a bounded signed PBS failure code and rejects contradictory normalization", async () => {
    const response = (state: string) => ({ ok: true, json: async () => ({ data: {
      connection_status: "connected",
      profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
      remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1", name: "terminated", raw_state: "X", state, exit_status: -29, walltime: null, start_time: null, comment: null, dependencies: [] }] },
    } }) });
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce(response("completed_failed"))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce(response("completed_success")));
    expect((await zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).scheduler.jobs[0].exit_status).toBe(-29);
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toThrow("Inconsistent Zeus job response");
    vi.unstubAllGlobals();
  });

  it("treats every held job as attention-required even when dependencies are recorded", async () => {
    const response = (state: string) => ({ ok: true, json: async () => ({ data: {
      connection_status: "connected",
      profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
      remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1", name: "held", raw_state: "H", state, exit_status: null, walltime: null, start_time: null, comment: null, dependencies: ["2"] }] },
    } }) });
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce(response("held_attention"))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce(response("waiting_dependency")));
    expect((await zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).scheduler.jobs[0].state).toBe("held_attention");
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toThrow("Invalid Zeus job response");
    vi.unstubAllGlobals();
  });

  it("preserves sanitized Zeus error codes for nontechnical UI copy", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ error: { code: "zeus_authentication_required", message: "Configure an existing SSH key or agent." } }) }));
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toEqual(expect.objectContaining<Partial<ZeusApiError>>({ code: "zeus_authentication_required" }));
    vi.unstubAllGlobals();
  });

  it.each([
    ["mismatched profile", { profile: { host: "zeus-login.zeus.technion.ac.il", username: "other", project_directory: "/home/other/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } }],
    ["control character", { remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main\u0007", dirty: false } }],
    ["unexpected secret field", { profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent", password: "never" } }],
    ["hostile job id", { scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1; qsub x", name: "bad", raw_state: "Q", state: "queued", exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] }] } }],
  ])("rejects Zeus response with %s", async (_label, override) => {
    const base = {
      connection_status: "connected",
      profile: { host: "zeus-login.zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
      remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
      scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [] },
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { ...base, ...override } }) }));
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toThrow();
    vi.unstubAllGlobals();
  });
});

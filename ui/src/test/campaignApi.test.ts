import { campaignApi, screeningLifecycleApi, screeningSubmissionApi, smokeLifecycleApi, submissionApi, transferApi, zeusApi, ZeusApiError } from "../api/campaigns";

const smokePreviewData = (kind: "job" | "array" = "job") => ({
  preview_token: "submit-token", expires_in_seconds: 300,
  campaign: { id: "mot_2d-x", name: "x", path: "data/optimization/mot_2d/x", git_commit: "a".repeat(40), s0_values: kind === "job" ? [1.3] : [1.2, 1.3] },
  stage: { id: "smoke", label: "Smoke check", purpose: "Validate setup" },
  job: { file: "jobs/01_smoke.pbs", kind, task_count: kind === "job" ? 1 : 2, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 },
  remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "a".repeat(40), branch: "main", dirty: false },
  inputs: { verified_count: 72, status: "ready" }, effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
});

const smokeResultData = (job_id: string) => ({ status: "submitted", campaign_id: "mot_2d-x", stage: "smoke", job_id, submitted_at: "2026-10-08T12:00:00Z", later_stages_locked: true });

describe("campaign API runtime validation", () => {
  it("strictly previews and confirms one Screening array submission", async () => {
    const preview = { preview_token: "screen-submit-token", expires_in_seconds: 300, campaign: { id: "mot_2d-x", name: "x", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "screen", label: "Screening", purpose: "Find promising candidates" }, job: { file: "jobs/02_screen.pbs", kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 86400 }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "a".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, smoke: { status: "validated", job_id: "4759999.zeus-master", point_count: 1 }, effects: { submit_screening: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true };
    const result = { status: "submitted", campaign_id: "mot_2d-x", stage: "screen", job_id: "4760000[].zeus-master", submitted_at: "2026-10-08T13:00:00Z", later_stages_locked: true };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: preview }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: result }) });
    vi.stubGlobal("fetch", fetchMock);
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    expect((await screeningSubmissionApi.preview("mot_2d-x", profile)).job.array_throttle).toBe(3);
    expect((await screeningSubmissionApi.confirm("screen-submit-token")).job_id).toBe("4760000[].zeus-master");
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/v1/zeus/submissions/screening/confirm", expect.objectContaining({ body: JSON.stringify({ preview_token: "screen-submit-token" }) }));
    vi.unstubAllGlobals();
  });

  it("strictly validates Screening completion and prepares Refinement without qsub", async () => {
    const candidate = (rank: number, worker: number) => ({ s0: 1.3, rank, detuning_gamma: -0.9 - rank / 100, magnet_radius_m: 0.046 + rank / 100000, mean_conditional_efficiency: 0.02 + rank / 1000, source: `screen/s0_1p300000/worker${worker}/trials/trial_000${rank}.json` });
    const status = { source: "zeus", queried_at: "2026-10-09T08:00:00Z", campaign: { id: "mot_2d-x", name: "x", stage: "screen" }, submission: { job_id: "4760000[].zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0, task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } }, validation: { status: "valid", completed_trials: 51, expected_trials: 51, candidate_count: 3 }, lifecycle: "ready_to_prepare_refinement", next_action: "review_refinement_preparation" };
    const preview = { preview_token: "refine-token", expires_in_seconds: 300, campaign: { id: "mot_2d-x", name: "x", git_commit: "a".repeat(40), s0_values: [1.3] }, from_stage: "screen", to_stage: "refine", bounds: { detuning_gamma: { low: -3, high: -0.1 }, magnet_radius_m: { low: 0.03, high: 0.06 } }, screening: { job_id: "4760000[].zeus-master", completed_trials: 51, expected_trials: 51, candidates: [candidate(1, 0), candidate(2, 1), candidate(3, 2)] }, artifacts: { create: ["screening_candidates.json", "refine/tasks.json", "jobs/03_refine_round_01.pbs", "jobs/03_refine_round_02.pbs", "jobs/03_refine_round_03.pbs", "jobs/03_refine_round_04.pbs", "jobs/03_submit_refinement_chain.sh"], update: ["campaign.json"] }, effects: { prepare_refinement: true, submit_refinement: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } };
    const result = { status: "refinement_prepared", campaign_id: "mot_2d-x", stage: "refine", artifacts: { created: 7, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "status-csrf" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: status }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "refine-csrf" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: preview }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: result }) });
    vi.stubGlobal("fetch", fetchMock); const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    expect((await screeningLifecycleApi.status("mot_2d-x", profile)).validation.candidate_count).toBe(3);
    expect((await screeningLifecycleApi.preview("mot_2d-x", profile)).effects.submit_refinement).toBe(false);
    expect((await screeningLifecycleApi.confirm("refine-token")).submitted_to_zeus).toBe(false);
    vi.unstubAllGlobals();
  });
  it("rejects malformed nested status data instead of rendering it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ data: { campaigns: [{
        id: "x", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "bad", path: "data/x", stage: "screen",
        stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked",
        trust: "trusted-current", scientific_role: "candidate-selection",
        progress: [{ stage: "screen", completed: 1, expected: 2, status: "executing" }],
        warnings: [], next_plan: null, s0_values: [1.3], families: [], git_commit: "abc", remote_preparation: { status: "ready", reason_code: null },
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
      s0_values: [1.3], families: [], git_commit: "abc", remote_preparation: { status: "ready", reason_code: null },
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [{ ...base, ...override }], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow();
    vi.unstubAllGlobals();
  });

  it.each([
    ["ready campaign with a legacy reason", { status: "ready", reason_code: "absolute-input-paths" }],
    ["legacy campaign without a reason", { status: "legacy-local-only", reason_code: null }],
    ["legacy campaign with an unavailable reason", { status: "legacy-local-only", reason_code: "incomplete-portability-record" }],
    ["unavailable campaign without a reason", { status: "unavailable", reason_code: null }],
    ["unavailable campaign with a legacy reason", { status: "unavailable", reason_code: "fixed-checkout-path" }],
    ["remote preparation with an unexpected key", { status: "ready", reason_code: null, command: "qsub unsafe.pbs" }],
  ])("rejects %s", async (_label, remotePreparation) => {
    const campaign = {
      id: "x", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "bad", path: "data/x", stage: "screen",
      stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current",
      scientific_role: "candidate-selection", progress: [], warnings: [], next_plan: null,
      s0_values: [1.3], families: [], git_commit: "abc", remote_preparation: remotePreparation,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [campaign], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow("Invalid campaign response");
    vi.unstubAllGlobals();
  });

  it("rejects inconsistent list totals", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow("Invalid campaign list response");
    vi.unstubAllGlobals();
  });

  it("rejects a non-ready campaign that still exposes a next action", async () => {
    const campaign = {
      id: "x", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "contradictory", path: "data/x", stage: "screen",
      stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current",
      scientific_role: "candidate-selection", progress: [], warnings: [],
      next_plan: { label: "Submit", command: ["qsub", "unsafe.pbs"], display_command: "qsub unsafe.pbs", mode: "copy-only", scheduler_status: "unchecked", operation_scope: "remote-submission", executes_automatically: false },
      s0_values: [1.3], families: [], git_commit: "abc",
      remote_preparation: { status: "unavailable", reason_code: "incomplete-portability-record" },
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ data: { campaigns: [campaign], invalid_count: 0, total: 1 } }) })));
    await expect(campaignApi.list()).rejects.toThrow("Invalid campaign action response");
    vi.unstubAllGlobals();
  });

  it("requests a session only when a Zeus snapshot is explicitly requested", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: {
        connection_status: "connected",
        profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
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

  it("uses one session for transfer preview and confirmation and validates safe effects", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "transfer-csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: {
        preview_token: "transfer-token", expires_in_seconds: 300,
        campaign: { id: "mot_2d-x", name: "x", path: "data/optimization/mot_2d/x", git_commit: "a".repeat(40) },
        destination: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", campaign_directory: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/x" },
        artifacts: { ensemble_count: 35, total_count: 72, missing_count: 2, identical_count: 70, total_bytes: 52_000_000, missing_bytes: 1000 },
        effects: { copy_missing_only: true, overwrite_existing: false, submit_jobs: false, run_simulation: false },
      } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { status: "prepared", campaign_id: "mot_2d-x", destination: "/home/tal.noa/ytterbium_lab_simulation_new/data/optimization/mot_2d/x", transferred_count: 2, reused_identical_count: 70, bytes_transferred: 1000, submitted_to_zeus: false, simulation_started: false } }) });
    vi.stubGlobal("fetch", fetchMock);
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    expect((await transferApi.preview("mot_2d-x", profile)).artifacts.missing_count).toBe(2);
    expect((await transferApi.confirm("transfer-token")).submitted_to_zeus).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/zeus/transfers/preview", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "transfer-csrf" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/v1/zeus/transfers/confirm", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "transfer-csrf" }) }));
    vi.unstubAllGlobals();
  });

  it("uses one bound session for exact smoke preview and confirmation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "submit-csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: {
        preview_token: "submit-token", expires_in_seconds: 300,
        campaign: { id: "mot_2d-x", name: "x", path: "data/optimization/mot_2d/x", git_commit: "a".repeat(40), s0_values: [1.3] },
        stage: { id: "smoke", label: "Smoke check", purpose: "Validate setup" },
        job: { file: "jobs/01_smoke.pbs", kind: "job", task_count: 1, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 },
        remote: { host: "zeus.technion.ac.il", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", commit: "a".repeat(40), branch: "main", dirty: false },
        inputs: { verified_count: 72, status: "ready" }, effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
      } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { status: "submitted", campaign_id: "mot_2d-x", stage: "smoke", job_id: "4759999.zeus-master", submitted_at: "2026-10-08T12:00:00Z", later_stages_locked: true } }) });
    vi.stubGlobal("fetch", fetchMock);
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    expect((await submissionApi.preview("mot_2d-x", profile)).job.queue).toBe("zeus_combined_q");
    expect((await submissionApi.confirm("submit-token")).job_id).toBe("4759999.zeus-master");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/zeus/submissions/smoke/preview", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "submit-csrf" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/v1/zeus/submissions/smoke/confirm", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "submit-csrf" }) }));
    vi.unstubAllGlobals();
  });

  it("accepts a zero-capture scientifically valid smoke result and prepares no job", async () => {
    const status = { source: "zeus", queried_at: "2026-10-08T12:10:00Z", campaign: { id: "mot_2d-x", name: "x", stage: "smoke" }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 }, validation: { status: "valid", points: [{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }], artifact_count: 3 }, lifecycle: "ready_to_prepare_screen", next_action: "review_screening_preparation" };
    const preview = { preview_token: "screen-token", expires_in_seconds: 300, campaign: { id: "mot_2d-x", name: "x", git_commit: "a".repeat(40) }, from_stage: "smoke", to_stage: "screen", smoke: { job_id: "4759999.zeus-master", points: status.validation.points, artifact_count: 3 }, artifacts: { create: ["screen/tasks.json", "jobs/02_screen.pbs"], update: ["campaign.json"] }, effects: { prepare_screening: true, submit_screening: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } };
    const result = { status: "screening_prepared", campaign_id: "mot_2d-x", stage: "screen", artifacts: { created: 2, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "status-csrf" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: status }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "screen-csrf" } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ data: preview }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: result }) });
    vi.stubGlobal("fetch", fetchMock);
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    expect((await smokeLifecycleApi.status("mot_2d-x", profile)).validation.points[0].captured).toBe(0);
    expect((await smokeLifecycleApi.preview("mot_2d-x", profile)).effects.submit_screening).toBe(false);
    expect((await smokeLifecycleApi.confirm("screen-token")).submitted_to_zeus).toBe(false);
    expect(fetchMock).toHaveBeenNthCalledWith(5, "/api/v1/zeus/screening/confirm", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "screen-csrf" }) }));
    vi.unstubAllGlobals();
  });

  it("rejects a contradictory smoke lifecycle instead of enabling screening", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { source: "zeus", queried_at: "2026-10-08T12:10:00Z", campaign: { id: "mot_2d-x", name: "x", stage: "smoke" }, submission: { job_id: "4759999.zeus-master" }, scheduler: { state: "running", raw_state: "R", exit_status: null }, validation: { status: "valid", points: [{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }], artifact_count: 3 }, lifecycle: "ready_to_prepare_screen", next_action: "review_screening_preparation" } }) }));
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    await expect(smokeLifecycleApi.status("mot_2d-x", profile)).rejects.toThrow("Inconsistent smoke lifecycle response");
    vi.unstubAllGlobals();
  });

  it.each(["4759999", "4759999[]", "4759999[0].zeus-master", "4759999.other-server"])("rejects non-canonical smoke parent job id %s", async (jobId) => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "submit-csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: smokePreviewData() }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: smokeResultData(jobId) }) }));
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    await submissionApi.preview("mot_2d-x", profile);
    await expect(submissionApi.confirm("submit-token")).rejects.toEqual(expect.objectContaining({ code: "submission_outcome_unknown" }));
    vi.unstubAllGlobals();
  });

  it("rejects a scalar job id for a reviewed array submission", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "submit-csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: smokePreviewData("array") }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: smokeResultData("4759999.zeus-master") }) }));
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    await submissionApi.preview("mot_2d-x", profile);
    await expect(submissionApi.confirm("submit-token")).rejects.toEqual(expect.objectContaining({ code: "submission_outcome_unknown" }));
    vi.unstubAllGlobals();
  });

  it.each([
    ["network failure", () => Promise.reject(new TypeError("connection reset"))],
    ["non-JSON response", () => Promise.resolve({ ok: true, json: async () => { throw new SyntaxError("not json"); } })],
    ["malformed success", () => Promise.resolve({ ok: true, json: async () => ({ data: { ...smokeResultData("4759999.zeus-master"), later_stages_locked: false } }) })],
    ["mismatched campaign", () => Promise.resolve({ ok: true, json: async () => ({ data: { ...smokeResultData("4759999.zeus-master"), campaign_id: "mot_2d-other" } }) })],
  ])("treats %s after confirm starts as an unknown submission outcome", async (_label, confirmResponse) => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "submit-csrf" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: smokePreviewData() }) })
      .mockImplementationOnce(confirmResponse));
    const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
    await submissionApi.preview("mot_2d-x", profile);
    await expect(submissionApi.confirm("submit-token")).rejects.toEqual(expect.objectContaining({ code: "submission_outcome_unknown" }));
    vi.unstubAllGlobals();
  });

  it("fails closed on malformed Zeus job state", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { csrf_token: "csrf-token" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: {
        connection_status: "connected",
        profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
        remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main", dirty: false },
        scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1", name: "bad", raw_state: "R", state: "finished", exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] }] },
      } }) }));
    await expect(zeusApi.snapshot("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")).rejects.toThrow("Invalid Zeus job response");
    vi.unstubAllGlobals();
  });

  it("accepts a bounded signed PBS failure code and rejects contradictory normalization", async () => {
    const response = (state: string) => ({ ok: true, json: async () => ({ data: {
      connection_status: "connected",
      profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
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
      profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
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
    ["mismatched profile", { profile: { host: "zeus.technion.ac.il", username: "other", project_directory: "/home/other/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } }],
    ["control character", { remote: { project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", git_commit: "a".repeat(40), branch: "main\u0007", dirty: false } }],
    ["unexpected secret field", { profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent", password: "never" } }],
    ["hostile job id", { scheduler: { status: "available", queried_at: "2026-10-08T10:00:00Z", jobs: [{ id: "1; qsub x", name: "bad", raw_state: "Q", state: "queued", exit_status: null, walltime: null, start_time: null, comment: null, dependencies: [] }] } }],
  ])("rejects Zeus response with %s", async (_label, override) => {
    const base = {
      connection_status: "connected",
      profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" },
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

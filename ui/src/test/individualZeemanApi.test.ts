import { createIndividualZeemanApi, type ZeemanRequest } from "../api/clients/individualZeeman";

const request: ZeemanRequest = { particle_count: 200, seed: 42, mot_2d_s0: 1.3, mot_2d_detuning_gamma: -0.9196610026631429, mot_2d_magnet_radius_m: 0.04676406447474441, npools: 8, retain_particle_states: true, execution_mode: "local" };
const review = (overrides: Record<string, unknown> = {}) => ({
  preview_token: "review-token", expires_in_seconds: 300,
  plan: {
    zeeman_s0: 3, zeeman_detuning_gamma: -13.75, run_id: "zeeman-one", family: "zeeman", execution_mode: "local", particle_count: 200, seed: 42, mot_2d_s0: 1.3, mot_2d_detuning_gamma: -0.9196610026631429, mot_2d_magnet_radius_m: 0.04676406447474441, npools: 8,
    retain_particle_states: true, suitability: "individual_only", output_disposition: "retain_survivor_states",
    locked_settings: { policy: "canonical" }, resolved_configuration: { solver: "RK4StCustom" }, lifecycle_state: "configured",
    laboratory_specification: { version: 1 }, numerical_policy: { version: 1 }, plan_sha256: "a".repeat(64),
    execution_started: false, submitted_to_zeus: false, ...overrides,
  },
});
const zeusReview = { preview_token: "zeus-token", expires_in_seconds: 300, run_id: "zeeman-one", job: { kind: "scalar", array: false, pbs_sha256: "b".repeat(64), resources: { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 } }, package_sha256: "c".repeat(64), submission_key: "d".repeat(64), effects: { submit_one_job: true, reconcile_existing_job: false, cancel_job: false } };
const envelope = (data: unknown) => ({ ok: true, json: async () => ({ api_version: 1, data }) });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };
const runSummary = { id: "individual-run-" + "a".repeat(24), record_kind: "individual_simulation_run", run_kind: "zeeman", display_name: "zeeman-one", stage_semantics: "single-run-lifecycle", source: "local", queried_at: "2026-10-11T10:00:00+00:00", trust: "verified-package", scientific_role: "individual-only", record_state: "running", integrity: "active", lifecycle: "running", next_action: "wait", created_at: "2026-10-11T09:00:00+00:00", updated_at: "2026-10-11T10:00:00+00:00", execution: { mode: "local", zeus_job_id: null }, retention: { particle_states_requested: true, status: "pending" }, results: { availability: "not_ready", completed_at: null }, warnings: [] };

describe("individual Zeeman API trust boundary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["extra field", { ...review(), extra: true }],
    ["missing field", { preview_token: "review-token", plan: review().plan }],
    ["malformed digest", review({ plan_sha256: "not-a-digest" })],
    ["wrong mode", review({ execution_mode: "zeus" })],
    ["wrong run request", review({ particle_count: 201 })],
    ["mismatched saturation", review({ zeeman_s0: 2 })],
    ["mismatched detuning", review({ zeeman_detuning_gamma: -10 })],
    ["invalid saturation", review({ zeeman_s0: -1 })],
    ["nonfinite detuning", review({ zeeman_detuning_gamma: Infinity })],
  ])("rejects a %s in a creation review", async (_label, data) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope(data)));
    await expect(createIndividualZeemanApi(async () => "csrf").preview(request)).rejects.toThrow();
  });

  it("accepts the larger reviewed limit only for Zeus", async () => {
    const zeusRequest = { ...request, execution_mode: "zeus" as const, particle_count: 50_000, npools: 200 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope(review({ execution_mode: "zeus", particle_count: 50_000, npools: 200 }))));
    await expect(createIndividualZeemanApi(async () => "csrf").preview(zeusRequest)).resolves.toMatchObject({ plan: { particle_count: 50_000 } });
  });

  it("binds creation confirmation to the reviewed run and coalesces duplicate clicks", async () => {
    const confirmation = deferred<ReturnType<typeof envelope>>();
    const fetchMock = vi.fn().mockResolvedValueOnce(envelope(review())).mockImplementationOnce(() => confirmation.promise);
    vi.stubGlobal("fetch", fetchMock); const api = createIndividualZeemanApi(async () => "csrf");
    const preview = await api.preview(request);
    const first = api.confirm(preview.preview_token); const second = api.confirm(preview.preview_token);
    confirmation.resolve(envelope({ status: "created", run_id: "zeeman-one", family: "zeeman", path: "data/runs/zeeman/zeeman-one", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false }));
    await expect(first).resolves.toEqual(await second); expect(fetchMock).toHaveBeenCalledTimes(2);
    await expect(api.confirm(preview.preview_token)).resolves.toMatchObject({ run_id: "zeeman-one" }); expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("rejects a creation result for another run", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(envelope(review())).mockResolvedValueOnce(envelope({ status: "created", run_id: "zeeman-two", family: "zeeman", path: "data/runs/zeeman/zeeman-two", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false })));
    const api = createIndividualZeemanApi(async () => "csrf"); const preview = await api.preview(request);
    await expect(api.confirm(preview.preview_token)).rejects.toThrow(/did not match/);
  });

  it("does not accept a confirmation response after the client is reset", async () => {
    const confirmation = deferred<ReturnType<typeof envelope>>();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(envelope(review())).mockImplementationOnce(() => confirmation.promise));
    const api = createIndividualZeemanApi(async () => "csrf"); const preview = await api.preview(request); const pending = api.confirm(preview.preview_token); api.reset();
    confirmation.resolve(envelope({ status: "created", run_id: "zeeman-one", family: "zeeman", path: "data/runs/zeeman/zeeman-one", lifecycle_state: "configured", execution_started: false, submitted_to_zeus: false }));
    await expect(pending).rejects.toThrow(/stale/);
  });

  it("binds Zeus result, job, submission key, and profile", async () => {
    const submitted = { status: "submitted", run_id: "zeeman-one", job_id: "12345.zeus-master", submission_key: "d".repeat(64) };
    const fetchMock = vi.fn().mockResolvedValueOnce(envelope(zeusReview)).mockResolvedValueOnce(envelope(submitted)).mockResolvedValueOnce(envelope({ state: "running", job_id: "12345.zeus-master" }));
    vi.stubGlobal("fetch", fetchMock); const api = createIndividualZeemanApi(async () => "csrf");
    const preview = await api.previewZeus("zeeman-one", "tal.noa"); await api.confirmZeus(preview.preview_token);
    await expect(api.refreshZeus("zeeman-one", "other.user")).rejects.toThrow(/profile/);
    await expect(api.refreshZeus("zeeman-one", "tal.noa")).resolves.toMatchObject({ state: "running" });
  });

  it.each(["running", "held"])("recovers a fresh read-only Zeus binding before an explicit refresh (%s)", async (schedulerState) => {
    const recovered = { run_id: "zeeman-one", family: "zeeman", job_id: "12345.zeus-master", scheduler_state: schedulerState, exit_status: null, local_state: "queued", read_only: true };
    const fetchMock = vi.fn().mockResolvedValueOnce(envelope(recovered)).mockResolvedValueOnce(envelope({ state: schedulerState, job_id: "12345.zeus-master" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualZeemanApi(async () => "csrf");
    await expect(api.recoverZeus("zeeman-one", "tal.noa")).resolves.toEqual(recovered);
    await expect(api.refreshZeus("zeeman-one", "tal.noa")).resolves.toEqual({ state: schedulerState, job_id: "12345.zeus-master" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/individual-runs/zeeman/zeus/recover");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ run_id: "zeeman-one", profile: { username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_ui" } });
  });

  it.each([
    ["wrong family", { family: "mot_2d" }],
    ["wrong run", { run_id: "zeeman-other" }],
    ["extra submission key", { submission_key: "a".repeat(64) }],
    ["not read only", { read_only: false }],
    ["bad job", { job_id: "12345[]" }],
  ])("rejects a %s recovery response", async (_label, change) => {
    const recovered = { run_id: "zeeman-one", family: "zeeman", job_id: "12345.zeus-master", scheduler_state: "running", exit_status: null, local_state: "queued", read_only: true, ...change };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope(recovered)));
    await expect(createIndividualZeemanApi(async () => "csrf").recoverZeus("zeeman-one", "tal.noa")).rejects.toThrow(/recovery/);
  });

  it("fails closed when the server rejects the remembered Zeus profile", async () => {
    const response = new Response(JSON.stringify({ error: { code: "zeeman_zeus_profile_or_submission_identity_mismatch", message: "The saved run belongs to a different Zeus profile." } }), { status: 409, headers: { "Content-Type": "application/json" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const api = createIndividualZeemanApi(async () => "csrf");
    await expect(api.recoverZeus("zeeman-one", "other.user")).rejects.toThrow(/different Zeus profile/);
    await expect(api.refreshZeus("zeeman-one", "other.user")).rejects.toThrow(/profile/);
  });

  it.each([
    ["wrong run", { status: "submitted", run_id: "zeeman-two", job_id: "12345.zeus-master", submission_key: "d".repeat(64) }],
    ["wrong submission", { status: "submitted", run_id: "zeeman-one", job_id: "12345.zeus-master", submission_key: "e".repeat(64) }],
    ["array job", { status: "submitted", run_id: "zeeman-one", job_id: "12345[].zeus-master", submission_key: "d".repeat(64) }],
  ])("rejects a Zeus confirmation with %s identity", async (_label, result) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(envelope(zeusReview)).mockResolvedValueOnce(envelope(result)));
    const api = createIndividualZeemanApi(async () => "csrf"); const preview = await api.previewZeus("zeeman-one", "tal.noa");
    await expect(api.confirmZeus(preview.preview_token)).rejects.toThrow();
  });

  it("rejects a status response for another Zeus job", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(envelope(zeusReview)).mockResolvedValueOnce(envelope({ status: "submitted", run_id: "zeeman-one", job_id: "12345.zeus-master", submission_key: "d".repeat(64) })).mockResolvedValueOnce(envelope({ state: "running", job_id: "54321.zeus-master" })));
    const api = createIndividualZeemanApi(async () => "csrf"); const preview = await api.previewZeus("zeeman-one", "tal.noa"); await api.confirmZeus(preview.preview_token);
    await expect(api.refreshZeus("zeeman-one", "tal.noa")).rejects.toThrow(/did not match/);
  });

  it("suppresses a review response that becomes stale after reset", async () => {
    const response = deferred<ReturnType<typeof envelope>>(); vi.stubGlobal("fetch", vi.fn(() => response.promise));
    const api = createIndividualZeemanApi(async () => "csrf"); const pending = api.preview(request); api.reset(); response.resolve(envelope(review()));
    await expect(pending).rejects.toThrow(/stale/);
  });

  it("suppresses an older review that resolves after a newer request", async () => {
    const older = deferred<ReturnType<typeof envelope>>(); const newer = deferred<ReturnType<typeof envelope>>();
    vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => older.promise).mockImplementationOnce(() => newer.promise));
    const api = createIndividualZeemanApi(async () => "csrf"); const first = api.preview(request); const second = api.preview({ ...request, seed: 43 });
    newer.resolve(envelope(review({ seed: 43, run_id: "zeeman-new" }))); await expect(second).resolves.toMatchObject({ plan: { run_id: "zeeman-new" } });
    older.resolve(envelope(review())); await expect(first).rejects.toThrow(/stale/);
  });

  it("coalesces duplicate local-start clicks", async () => {
    const response = deferred<ReturnType<typeof envelope>>(); const fetchMock = vi.fn(() => response.promise); vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualZeemanApi(async () => "csrf"); const first = api.startLocal("zeeman-one"); const second = api.startLocal("zeeman-one");
    response.resolve(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }));
    await expect(first).resolves.toEqual(await second); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("allows a safe local-start retry after a rejected request", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error("temporary local service failure"))
      .mockResolvedValueOnce(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualZeemanApi(async () => "csrf");
    await expect(api.startLocal("zeeman-one")).rejects.toThrow(/temporary/);
    await expect(api.startLocal("zeeman-one")).resolves.toMatchObject({ run_id: "zeeman-one" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("coalesces concurrent local starts and caches the successful result", async () => {
    const response = deferred<ReturnType<typeof envelope>>();
    const fetchMock = vi.fn(() => response.promise);
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualZeemanApi(async () => "csrf");
    const first = api.startLocal("zeeman-one");
    const second = api.startLocal("zeeman-one");
    response.resolve(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }));
    await expect(first).resolves.toEqual(await second);
    await expect(api.startLocal("zeeman-one")).resolves.toMatchObject({ run_id: "zeeman-one" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not let a pre-reset local start evict the replacement request", async () => {
    const firstResponse = deferred<ReturnType<typeof envelope>>();
    const secondResponse = deferred<ReturnType<typeof envelope>>();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => firstResponse.promise)
      .mockImplementationOnce(() => secondResponse.promise);
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualZeemanApi(async () => "csrf");
    const first = api.startLocal("zeeman-one");
    api.reset();
    const replacement = api.startLocal("zeeman-one");
    firstResponse.resolve(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }));
    await expect(first).rejects.toThrow(/stale/);
    const third = api.startLocal("zeeman-one");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    secondResponse.resolve(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }));
    await expect(replacement).resolves.toEqual(await third);
  });

  it("strictly parses local-start, run-list, and run-detail responses", async () => {
    const detail = { ...runSummary, provenance: { git_revision: "a".repeat(40), configuration_sha256: "b".repeat(64), inputs_sha256: "c".repeat(64), laboratory_spec: {}, numerical_policy: {} }, configuration: { status: "complete", resolved: {} }, inputs: { status: "complete", artifacts: [] }, artifacts: [], metrics: null, error: null };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(envelope({ status: "queued", run_id: "zeeman-one", execution_mode: "local" }))
      .mockResolvedValueOnce(envelope({ runs: [runSummary], invalid_count: 0, total: 1, truncated: false }))
      .mockResolvedValueOnce(envelope(detail)));
    const api = createIndividualZeemanApi(async () => "csrf");
    await expect(api.startLocal("zeeman-one")).resolves.toMatchObject({ run_id: "zeeman-one" });
    const [listed] = await api.runs(); expect(listed.id).toBe(runSummary.id);
    await expect(api.run(runSummary.id)).resolves.toMatchObject({ id: runSummary.id });
  });

  it("accepts the verified detail returned for a completed local run", async () => {
    const completed = {
      ...runSummary,
      record_state: "succeeded",
      integrity: "complete_verified",
      lifecycle: "results_ready",
      next_action: "view_results",
      execution: { mode: "local", zeus_job_id: null, progress: null },
      retention: { particle_states_requested: false, status: "not_retained" },
      results: { availability: "verified", completed_at: "2026-10-11T10:00:00+00:00" },
      provenance: { git_revision: "a".repeat(40), configuration_sha256: "b".repeat(64), inputs_sha256: "c".repeat(64), laboratory_spec: { version: "laboratory-physical-v2", sha256: "d".repeat(64) }, numerical_policy: { version: "numerical-policy-v1", sha256: "e".repeat(64) } },
      configuration: { status: "complete", resolved: { simulation: { particle_count: 200 } } },
      inputs: { status: "complete", artifacts: [] },
      artifacts: [{ kind: "retention_receipt", path: "results/state_retention_receipt.json", sha256: "f".repeat(64), size_bytes: 197 }],
      metrics: { captured: 120, elapsed_s: 8.94, n_initial: 200, n_survivors: 120, survival_fraction: 0.6 },
      error: null,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope(completed)));
    await expect(createIndividualZeemanApi(async () => "csrf").run(runSummary.id)).resolves.toMatchObject({
      lifecycle: "results_ready",
      metrics: { n_survivors: 120 },
    });
  });

  it("selects only Zeeman records from the shared individual-run catalog", async () => {
    const mot2d = { ...runSummary, id: "individual-run-" + "b".repeat(24), run_kind: "mot_2d", display_name: "mot2d-one" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope({ runs: [mot2d, runSummary], invalid_count: 0, total: 2, truncated: false })));

    await expect(createIndividualZeemanApi(async () => "csrf").runs()).resolves.toEqual([
      expect.objectContaining({ run_kind: "zeeman", display_name: "zeeman-one" }),
    ]);
  });

  it.each([
    ["local start extra field", { status: "queued", run_id: "zeeman-one", execution_mode: "local", pid: 7 }, "startLocal"],
    ["run list malformed total", { runs: [runSummary], invalid_count: 0, total: 2, truncated: false }, "runs"],
    ["run detail wrong identity", { ...runSummary, id: "individual-run-" + "b".repeat(24), provenance: { git_revision: "a".repeat(40), configuration_sha256: "b".repeat(64), inputs_sha256: "c".repeat(64), laboratory_spec: {}, numerical_policy: {} }, configuration: { status: "complete", resolved: {} }, inputs: { status: "complete", artifacts: [] }, artifacts: [], metrics: null, error: null }, "run"],
  ])("rejects %s", async (_label, payload, operation) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(envelope(payload))); const api = createIndividualZeemanApi(async () => "csrf");
    const call = operation === "startLocal" ? api.startLocal("zeeman-one") : operation === "runs" ? api.runs() : api.run(runSummary.id);
    await expect(call).rejects.toThrow();
  });
});

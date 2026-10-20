import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createIndividualMot2DApi,
  type Mot2DRequest,
} from "../api/clients/individualMot2D";

const envelope = (data: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify({ api_version: 1, data }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
const request: Mot2DRequest = {
  source_id: `mot2d-source-${"a".repeat(32)}`,
  particle_count: 20,
  selection_seed: 1,
  mot_seed: 2,
  s0: 1.3,
  detuning_gamma: -0.92,
  magnet_radius_m: 0.046,
  npools: 8,
  retain_particle_states: false,
  execution_mode: "local",
};
const preview = () => ({
  preview_token: "token",
  expires_in_seconds: 300,
  plan: {
    run_id: "mot2d-test",
    family: "mot_2d",
    source: {
      id: request.source_id,
      kind: "canonical_folder",
      qualification: "canonical_campaign_source",
      fingerprint: "a".repeat(64),
      pooled_particle_count: 100,
    },
    selection: {
      algorithm: "stable",
      version: "1",
      seed: 1,
      selected_count: 20,
      selected_identities_sha256: "b".repeat(64),
    },
    controls: { s0: 1.3, detuning_gamma: -0.92, magnet_radius_m: 0.046 },
    execution: { mode: "local", particle_count: 20, mot_seed: 2 },
    retention: { particle_states: false },
    suitability: "individual_only",
    output_disposition: "discard_survivor_states_after_summary",
    locked_settings: { workers: 8 },
    lifecycle_state: "configured",
    laboratory_specification: {},
    numerical_policy: {},
    plan_sha256: "c".repeat(64),
    execution_started: false,
    submitted_to_zeus: false,
  },
});
afterEach(() => vi.unstubAllGlobals());
describe("individual 2D-MOT client", () => {
  it("allows a safe local-start retry after a rejected request", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error("temporary local service failure"))
      .mockResolvedValueOnce(await envelope({ status: "queued", run_id: "mot2d-test", execution_mode: "local" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf");
    await expect(api.startLocal("mot2d-test")).rejects.toThrow(/temporary/);
    await expect(api.startLocal("mot2d-test")).resolves.toMatchObject({ run_id: "mot2d-test" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("coalesces concurrent local starts and caches the successful result", async () => {
    let resolve!: (value: Response) => void;
    const pending = new Promise<Response>((done) => { resolve = done; });
    const fetchMock = vi.fn(() => pending);
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf");
    const first = api.startLocal("mot2d-test");
    const second = api.startLocal("mot2d-test");
    resolve(await envelope({ status: "queued", run_id: "mot2d-test", execution_mode: "local" }));
    await expect(first).resolves.toEqual(await second);
    await expect(api.startLocal("mot2d-test")).resolves.toMatchObject({ run_id: "mot2d-test" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not let a pre-reset local start evict the replacement request", async () => {
    let resolveFirst!: (value: Response) => void;
    let resolveSecond!: (value: Response) => void;
    const firstResponse = new Promise<Response>((done) => { resolveFirst = done; });
    const secondResponse = new Promise<Response>((done) => { resolveSecond = done; });
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => firstResponse)
      .mockImplementationOnce(() => secondResponse);
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf");
    const first = api.startLocal("mot2d-test");
    api.reset();
    const replacement = api.startLocal("mot2d-test");
    resolveFirst(await envelope({ status: "queued", run_id: "mot2d-test", execution_mode: "local" }));
    await expect(first).rejects.toThrow(/stale/);
    const third = api.startLocal("mot2d-test");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveSecond(await envelope({ status: "queued", run_id: "mot2d-test", execution_mode: "local" }));
    await expect(replacement).resolves.toEqual(await third);
  });

  it("rejects extra source fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        envelope({
          contract_version: "mot-2d-individual-source-catalog-v1",
          sources: [
            {
              id: request.source_id,
              source_kind: "canonical_folder",
              label: "source",
              ensemble_count: 1,
              available_particle_count: {
                pooled: 20,
                minimum_per_ensemble: 20,
                maximum_per_ensemble: 20,
              },
              source_qualification: "canonical_campaign_source",
              result_suitability: "individual_only",
              provenance: {},
              path: "secret",
            },
          ],
          invalid_count: 0,
          total: 1,
          truncated: false,
        }),
      ),
    );
    await expect(
      createIndividualMot2DApi(async () => "csrf").sources(),
    ).rejects.toThrow(/Invalid/);
  });
  it("suppresses an older preview response", async () => {
    let resolveFirst!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(
        await envelope({ ...preview(), preview_token: "new" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf");
    const older = api.preview(request);
    await api.preview({ ...request, mot_seed: 3 }).catch(() => undefined);
    resolveFirst(await envelope(preview()));
    await expect(older).rejects.toThrow(/stale/);
  });
  it("deduplicates confirmation double clicks", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await envelope(preview()))
      .mockResolvedValue(
        await envelope({
          status: "created",
          run_id: "mot2d-test",
          family: "mot_2d",
          path: "data/runs/mot_2d/mot2d-test",
          lifecycle_state: "configured",
          execution_started: false,
          submitted_to_zeus: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf"),
      review = await api.preview(request);
    const [a, b] = await Promise.all([
      api.confirm(review.preview_token),
      api.confirm(review.preview_token),
    ]);
    expect(a).toEqual(b);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(await api.confirm(review.preview_token)).toEqual(a);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("rejects malformed creation state flags", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await envelope(preview()))
      .mockResolvedValueOnce(
        await envelope({
          status: "created",
          run_id: "mot2d-test",
          family: "mot_2d",
          path: "data/runs/mot_2d/mot2d-test",
          lifecycle_state: "running",
          execution_started: true,
          submitted_to_zeus: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf"),
      review = await api.preview(request);
    await expect(api.confirm(review.preview_token)).rejects.toThrow(/Invalid/);
  });
  it("reset invalidates an in-flight review", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      ),
    );
    const api = createIndividualMot2DApi(async () => "csrf"),
      pending = api.preview(request);
    api.reset();
    resolve(await envelope(preview()));
    await expect(pending).rejects.toThrow(/stale/);
  });
  it.each([
    [
      "mismatched source qualification",
      (row: ReturnType<typeof preview>) => {
        row.plan.source.qualification = "verified_individual_result";
      },
    ],
    [
      "selection seed above uint32",
      (row: ReturnType<typeof preview>) => {
        row.plan.selection.seed = 4294967296;
      },
    ],
    [
      "selection count differs from execution",
      (row: ReturnType<typeof preview>) => {
        row.plan.selection.selected_count = 19;
      },
    ],
    [
      "local count exceeds cap",
      (row: ReturnType<typeof preview>) => {
        row.plan.execution.particle_count = 1001;
        row.plan.selection.selected_count = 1001;
        row.plan.source.pooled_particle_count = 2000;
      },
    ],
  ])("rejects %s", async (_label, mutate) => {
    const row = structuredClone(preview());
    mutate(row);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(await envelope(row)));
    await expect(
      createIndividualMot2DApi(async () => "csrf").preview(request),
    ).rejects.toThrow(/Invalid/);
  });
  it("rejects contradictory Zeus effects before confirmation", async () => {
    const zeusRequest = { ...request, execution_mode: "zeus" as const };
    const zeusPreview = {
      ...preview(),
      plan: {
        ...preview().plan,
        execution: { mode: "zeus", particle_count: 20, mot_seed: 2 },
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await envelope(zeusPreview))
      .mockResolvedValueOnce(
        await envelope({
          status: "created",
          run_id: "mot2d-test",
          family: "mot_2d",
          path: "data/runs/mot_2d/mot2d-test",
          lifecycle_state: "configured",
          execution_started: false,
          submitted_to_zeus: false,
        }),
      )
      .mockResolvedValueOnce(
        await envelope({
          preview_token: "z",
          expires_in_seconds: 300,
          run_id: "mot2d-test",
          job: { kind: "scalar", array: false, pbs_sha256: "d".repeat(64), resources: { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 } },
          package_sha256: "e".repeat(64),
          submission_key: "f".repeat(64),
          effects: {
            submit_one_job: true,
            reconcile_existing_job: true,
            cancel_job: false,
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf"),
      review = await api.preview(zeusRequest);
    await api.confirm(review.preview_token);
    await expect(api.previewZeus("mot2d-test", "tal.noa")).rejects.toThrow(
      /Invalid/,
    );
  });
  it("binds refresh to the reviewed Zeus profile and job identity", async () => {
    const zeusRequest = { ...request, execution_mode: "zeus" as const },
      zeusPlan = {
        ...preview(),
        plan: {
          ...preview().plan,
          execution: { mode: "zeus", particle_count: 20, mot_seed: 2 },
        },
      },
      key = "f".repeat(64);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await envelope(zeusPlan))
      .mockResolvedValueOnce(
        await envelope({
          status: "created",
          run_id: "mot2d-test",
          family: "mot_2d",
          path: "data/runs/mot_2d/mot2d-test",
          lifecycle_state: "configured",
          execution_started: false,
          submitted_to_zeus: false,
        }),
      )
      .mockResolvedValueOnce(
        await envelope({
          preview_token: "z",
          expires_in_seconds: 300,
          run_id: "mot2d-test",
          job: { kind: "scalar", array: false, pbs_sha256: "d".repeat(64), resources: { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 } },
          package_sha256: "e".repeat(64),
          submission_key: key,
          effects: {
            submit_one_job: true,
            reconcile_existing_job: false,
            cancel_job: false,
          },
        }),
      )
      .mockResolvedValueOnce(
        await envelope({
          status: "submitted",
          run_id: "mot2d-test",
          job_id: "123.zeus-master",
          submission_key: key,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf"),
      creation = await api.preview(zeusRequest);
    await api.confirm(creation.preview_token);
    const reviewed = await api.previewZeus("mot2d-test", "tal.noa");
    await api.confirmZeus(reviewed.preview_token);
    await expect(api.refreshZeus("mot2d-test", "other.user")).rejects.toThrow(
      /profile/,
    );
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
  it("reset invalidates an in-flight Zeus review", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      ),
    );
    const api = createIndividualMot2DApi(async () => "csrf"),
      pending = api.previewZeus("mot2d-test", "tal.noa");
    api.reset();
    resolve(
      await envelope({
        preview_token: "z",
        expires_in_seconds: 300,
        run_id: "mot2d-test",
        job: { kind: "scalar", array: false, pbs_sha256: "d".repeat(64), resources: { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 } },
        package_sha256: "e".repeat(64),
        submission_key: "f".repeat(64),
        effects: {
          submit_one_job: true,
          reconcile_existing_job: false,
          cancel_job: false,
        },
      }),
    );
    await expect(pending).rejects.toThrow(/stale/);
  });
  it("rehydrates a fresh-client Zeus binding read-only, then refreshes explicitly", async () => {
    const recovered = { run_id: "mot2d-test", family: "mot_2d", job_id: "501.zeus-master", scheduler_state: "running", exit_status: null, local_state: "queued", read_only: true };
    const fetchMock = vi.fn().mockResolvedValueOnce(await envelope(recovered)).mockResolvedValueOnce(await envelope({ state: "running", job_id: "501.zeus-master" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createIndividualMot2DApi(async () => "csrf");
    await expect(api.recoverZeus("mot2d-test", "tal.noa")).resolves.toEqual(recovered);
    await expect(api.refreshZeus("mot2d-test", "tal.noa")).resolves.toEqual({ state: "running", job_id: "501.zeus-master" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ run_id: "mot2d-test", profile: { username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new" } });
  });
});

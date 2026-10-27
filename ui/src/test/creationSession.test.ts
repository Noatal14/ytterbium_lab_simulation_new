import { creationApi } from "../api/clients/campaign";

afterEach(() => vi.unstubAllGlobals());

it("shares concurrent session handshakes and refreshes after completion", async () => {
  let resolve!: (value: unknown) => void;
  const fetchMock = vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done; }))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: { csrf_token: "refreshed" } }) });
  vi.stubGlobal("fetch", fetchMock);
  const first = creationApi.session();
  const concurrent = creationApi.session();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  resolve({ ok: true, json: async () => ({ api_version: 1, data: { csrf_token: "shared" } }) });
  expect(await Promise.all([first, concurrent])).toEqual(["shared", "shared"]);
  expect(await creationApi.session()).toBe("refreshed");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("clears a failed handshake so a retry can establish a session", async () => {
  const fetchMock = vi.fn().mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ api_version: 1, data: { csrf_token: "retry" } }) });
  vi.stubGlobal("fetch", fetchMock);
  const outcomes = await Promise.allSettled([creationApi.session(), creationApi.session()]);
  expect(outcomes.map(result => result.status)).toEqual(["rejected", "rejected"]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(await creationApi.session()).toBe("retry");
});

it("sends and validates an explicit isolated campaign deployment", async () => {
  vi.stubEnv("MODE", "development");
  vi.stubEnv("VITE_ZEUS_CHECKOUT", "ytterbium_lab_simulation_ui_test");
  const input = { name: "New campaign", slug: "new", source_id: "bank", s0_values: [1.35] };
  const data = {
    preview_token: "preview", expires_in_seconds: 300,
    plan: { ...input, path: "data/optimization/mot_2d/new", files: ["campaign.json", "jobs/01_smoke.pbs"], stage: "smoke", execution_checkout: "ytterbium_lab_simulation_ui_test" },
    provenance: { commit: "a".repeat(40), input_count: 35 }, scientific_design: {}, duplicate: null,
  };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ api_version: 1, data }) });
  vi.stubGlobal("fetch", fetchMock);
  try {
    const response = await creationApi.preview(input, "csrf");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ...input, execution_checkout: "ytterbium_lab_simulation_ui_test" });
    expect(response.plan?.execution_checkout).toBe("ytterbium_lab_simulation_ui_test");
    data.plan.execution_checkout = "arbitrary";
    await expect(creationApi.preview(input, "csrf")).rejects.toThrow("Invalid campaign deployment response.");
  } finally {
    vi.unstubAllEnvs();
  }
});

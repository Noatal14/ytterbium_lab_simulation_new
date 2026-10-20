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

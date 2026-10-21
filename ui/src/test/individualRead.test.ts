import { afterEach, expect, it, vi } from "vitest";
import { individualRead } from "../api/clients/individualRead";
import { createIndividualMot2DApi } from "../api/clients/individualMot2D";
import { createIndividualMot3DApi } from "../api/clients/individualMot3D";
import { createIndividualZeemanApi } from "../api/clients/individualZeeman";
const deferred = <T>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const response = (data: unknown) =>
  new Response(JSON.stringify({ api_version: 1, data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => vi.unstubAllGlobals());
it("shares concurrent resource observations without caching a completed read", async () => {
  const d = deferred<string>(),
    fetch = vi.fn().mockReturnValueOnce(d.promise).mockResolvedValue("fresh");
  const read = individualRead(() => 0, fetch);
  const a = read("/list"),
    b = read("/list");
  expect(a).toBe(b);
  d.resolve("original");
  expect(await a).toBe("original");
  expect(await b).toBe("original");
  expect(await read("/list")).toBe("fresh");
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("list and detail do not cancel each other", async () => {
  const a = deferred<string>(),
    b = deferred<string>();
  const read = individualRead(
    () => 0,
    (p) => (p === "/list" ? a.promise : b.promise),
  );
  const list = read("/list"),
    detail = read("/detail");
  b.resolve("detail");
  expect(await detail).toBe("detail");
  a.resolve("list");
  expect(await list).toBe("list");
});
it("reset rejects old read without clearing newer pending observation", async () => {
  let g = 0;
  const a = deferred<string>(),
    b = deferred<string>();
  const fetch = vi
      .fn()
      .mockReturnValueOnce(a.promise)
      .mockReturnValueOnce(b.promise),
    read = individualRead(() => g, fetch);
  const old = read("/list"),
    rejected = expect(old).rejects.toThrow(/stale/);
  g++;
  const current = read("/list");
  a.resolve("old");
  await rejected;
  expect(read("/list")).toBe(current);
  b.resolve("new");
  expect(await current).toBe("new");
});
it("network errors propagate to every caller and later reads remain fresh", async () => {
  const d = deferred<string>(),
    read = individualRead(
      () => 0,
      vi.fn().mockReturnValueOnce(d.promise).mockResolvedValue("fresh"),
    );
  const a = expect(read("/list")).rejects.toThrow("network"),
    b = expect(read("/list")).rejects.toThrow("network");
  d.reject(Error("network"));
  await Promise.all([a, b]);
  expect(await read("/list")).toBe("fresh");
});
for (const [family, create] of [
  ["2D", createIndividualMot2DApi],
  ["3D", createIndividualMot3DApi],
  ["Zeeman", createIndividualZeemanApi],
] as const) {
  it(`${family}: manual runs and catalog share real validated response`, async () => {
    const d = deferred<Response>(),
      fetch = vi.fn().mockReturnValue(d.promise);
    vi.stubGlobal("fetch", fetch);
    const api = create(async () => "csrf");
    const a = api.runs(),
      b = api.catalog();
    d.resolve(
      response({ runs: [], invalid_count: 0, total: 0, truncated: false }),
    );
    expect(await a).toEqual([]);
    expect((await b).runs).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it(`${family}: malformed response rejects both callers`, async () => {
    const d = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(d.promise));
    const api = create(async () => "csrf");
    const a = expect(api.runs()).rejects.toThrow(/Invalid/),
      b = expect(api.catalog()).rejects.toThrow(/Invalid/);
    d.resolve(
      response({ runs: [], invalid_count: 0, total: 1, truncated: false }),
    );
    await Promise.all([a, b]);
  });
  it(`${family}: reset invalidates pending read`, async () => {
    const d = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(d.promise));
    const api = create(async () => "csrf");
    const rejected = expect(api.runs()).rejects.toThrow(/stale/);
    api.reset();
    d.resolve(
      response({ runs: [], invalid_count: 0, total: 0, truncated: false }),
    );
    await rejected;
  });
}

import actual from "./fixtures/individualRecovery.actual-public-v1.json";
import { refreshMot2DTransaction } from "../components/IndividualMot2DRun";
it("real 2D refresh transactions plus concurrent detail retain exact completed identity", async () => {
  const list = deferred<Response>(),
    detail = deferred<Response>();
  const fixture = structuredClone(actual.mot_2d);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.endsWith("/individual-runs")
        ? list.promise.then((r) => r.clone())
        : detail.promise.then((r) => r.clone()),
    ),
  );
  const api = createIndividualMot2DApi(async () => "csrf");
  const manual = refreshMot2DTransaction(
    api,
    "local",
    fixture.summary.display_name,
    "",
    () => true,
  );
  const poll = refreshMot2DTransaction(
    api,
    "local",
    fixture.summary.display_name,
    "",
    () => true,
  );
  const direct = api.run(fixture.summary.id);
  detail.resolve(response(fixture.detail));
  list.resolve(
    response({
      runs: [fixture.summary],
      invalid_count: 0,
      total: 1,
      truncated: false,
    }),
  );
  const results = await Promise.all([manual, poll, direct]);
  expect(
    results.every(
      (r) => r?.id === fixture.summary.id && r.lifecycle === "results_ready",
    ),
  ).toBe(true);
});
it("real SDK concurrent list cannot conceal corrupt detail", async () => {
  const fixture = structuredClone(actual.mot_2d),
    list = deferred<Response>(),
    detail = deferred<Response>();
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.endsWith("/individual-runs")
        ? list.promise.then((r) => r.clone())
        : detail.promise.then((r) => r.clone()),
    ),
  );
  const api = createIndividualMot2DApi(async () => "csrf");
  const rows = api.runs();
  const bad = expect(api.run(fixture.summary.id)).rejects.toThrow(/Invalid/);
  detail.resolve(response({ ...fixture.detail, unexpected: true }));
  list.resolve(
    response({ runs: [], invalid_count: 0, total: 0, truncated: false }),
  );
  await rows;
  await bad;
});
for (const [family, create] of [
  ["zeeman", createIndividualZeemanApi],
  ["mot_2d", createIndividualMot2DApi],
  ["mot_3d", createIndividualMot3DApi],
] as const) {
  it(`${family}: concurrent list and detail preserve real identity, mismatch still rejects`, async () => {
    const fixture = structuredClone(actual[family]);
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/individual-runs")
          ? pending.promise
          : Promise.resolve(response(fixture.detail)),
      ),
    );
    const api = create(async () => "csrf");
    const list = api.runs();
    expect((await api.run(fixture.summary.id)).id).toBe(fixture.summary.id);
    pending.resolve(
      response({
        runs: [fixture.summary],
        invalid_count: 0,
        total: 1,
        truncated: false,
      }),
    );
    expect((await list)[0].id).toBe(fixture.summary.id);
    await expect(api.run("individual-run-" + "a".repeat(24))).rejects.toThrow(
      /match/,
    );
  });
}

import { createElement } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IndividualMot2DRun } from "../components/IndividualMot2DRun";
import {
  rememberIndividualRun,
  forgetIndividualRun,
} from "../features/individual/individualRunRecovery";
it("actual 2D monitor manual Check overlaps autopoll without stale alert or authority replay", async () => {
  const base = structuredClone(actual.mot_2d),
    pending = deferred<Response>();
  const fixture = {
    summary: {
      ...base.summary,
      execution: {
        ...base.summary.execution,
        mode: "local",
        zeus_job_id: null,
      },
    },
    detail: {
      ...base.detail,
      execution: { ...base.detail.execution, mode: "local", zeus_job_id: null },
    },
  };
  const running = structuredClone(fixture.summary);
  Object.assign(running, {
    record_state: "running",
    lifecycle: "running",
    integrity: "active",
    next_action: "wait",
  });
  let lists = 0;
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      requests.push(url);
      if (url.endsWith("/sources"))
        return Promise.resolve(
          response({
            contract_version: "mot-2d-individual-source-catalog-v1",
            sources: [],
            invalid_count: 0,
            total: 0,
            truncated: false,
          }),
        );
      if (url.endsWith("/individual-runs")) {
        lists++;
        return lists === 1
          ? Promise.resolve(
              response({
                runs: [running],
                invalid_count: 0,
                total: 1,
                truncated: false,
              }),
            )
          : pending.promise.then((r) => r.clone());
      }
      const detail =
        lists < 2 ? { ...fixture.detail, ...running } : fixture.detail;
      return Promise.resolve(response(detail));
    }),
  );
  rememberIndividualRun("mot_2d", fixture.summary.display_name, "local");
  try {
    render(
      createElement(IndividualMot2DRun, {
        api: createIndividualMot2DApi(async () => "csrf"),
        onBack: () => {},
      }),
    );
    const check = await screen.findByRole("button", { name: "Check status" });
    await waitFor(() => expect(check).toBeEnabled());
    await waitFor(() => expect(lists).toBe(2), { timeout: 2500 });
    await userEvent.setup().click(check);
    expect(lists).toBe(2);
    pending.resolve(
      response({
        runs: [fixture.summary],
        invalid_count: 0,
        total: 1,
        truncated: false,
      }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Verified results are ready",
      }),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      requests.every(
        (url) => !url.includes("/start") && !url.includes("/confirm"),
      ),
    ).toBe(true);
  } finally {
    cleanup();
    forgetIndividualRun("mot_2d");
  }
});

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  LocalRunPublication,
  observeNewLocalRun,
  useLocalRunPublication,
} from "../features/individual/localRunPublication";

const empty = {
  runs: [] as { display_name: string }[],
  invalid_count: 0,
  truncated: false,
};
const run = { display_name: "new-local" };
const api = () => ({
  runs: vi.fn().mockResolvedValue([]),
  catalog: vi.fn().mockResolvedValue(empty),
});

describe("acknowledged new local publication observation", () => {
  it("has no grace for saved, reloaded or Zeus observations without a new local start", async () => {
    const p = new LocalRunPublication(),
      client = api();
    expect(
      await observeNewLocalRun(client, run.display_name, p, () => true),
    ).toEqual({ summary: null, waiting: false });
    expect(client.catalog).not.toHaveBeenCalled();
  });
  it("allows transient empty clean catalog then ends grace at the first verified entry", async () => {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    expect(
      (await observeNewLocalRun(client, run.display_name, p, () => true))
        .waiting,
    ).toBe(true);
    client.catalog.mockResolvedValueOnce({ ...empty, runs: [run] });
    expect(
      (await observeNewLocalRun(client, run.display_name, p, () => true))
        .summary,
    ).toEqual(run);
    expect(p.active).toBe(false);
    expect(
      (await observeNewLocalRun(client, run.display_name, p, () => true))
        .waiting,
    ).toBe(false);
  });
  it("ends permanent absence on the third successful missing read without restarting anything", async () => {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    const results = [];
    for (let i = 0; i < 4; i++)
      results.push(
        (await observeNewLocalRun(client, run.display_name, p, () => true))
          .waiting,
      );
    expect(results).toEqual([true, true, false, false]);
  });
  it("expires at five seconds and rejects backward clock movement", () => {
    for (const now of [6000, 999]) {
      const p = new LocalRunPublication();
      p.start(run.display_name, 1000);
      expect(p.missing(true, now)).toBe(false);
      expect(p.active).toBe(false);
    }
  });
  it.each([
    { invalid_count: 1, truncated: false },
    { invalid_count: 0, truncated: true },
  ])("does not grace ambiguous or invalid catalogs %j", async (flags) => {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    client.catalog.mockResolvedValue({ ...empty, ...flags });
    expect(
      (await observeNewLocalRun(client, run.display_name, p, () => true))
        .waiting,
    ).toBe(false);
  });
  it("propagates HTTP/schema errors immediately", async () => {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    client.catalog.mockRejectedValue(new Error("invalid schema"));
    await expect(
      observeNewLocalRun(client, run.display_name, p, () => true),
    ).rejects.toThrow("invalid schema");
  });
  it("does not consume a newer observation window for a retired read", async () => {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    expect(
      await observeNewLocalRun(client, run.display_name, p, () => false),
    ).toEqual({ summary: null, waiting: false, retired: true });
    expect(p.missing(true)).toBe(true);
    expect(p.missing(true)).toBe(true);
  });
});

for (const changed of ["mode", "run", "api", "unmount"] as const) {
  it(`retires an active local lease on ${changed} context change and rejects its late read`, async () => {
    const client = api();
    const original = {
      api: client,
      mode: "local" as "local" | "zeus",
      runId: run.display_name,
    };
    const hook = renderHook(
      (props) => useLocalRunPublication(props.api, props.mode, props.runId),
      { initialProps: original },
    );
    act(() => hook.result.current.publication.current.start(run.display_name));
    let resolve!: (value: typeof empty) => void;
    client.catalog.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const retired = observeNewLocalRun(
      client,
      run.display_name,
      hook.result.current.publication.current,
      () => true,
    );
    if (changed === "unmount") hook.unmount();
    else
      hook.rerender({
        ...original,
        ...(changed === "mode"
          ? { mode: "zeus" as const }
          : changed === "run"
            ? { runId: "other-run" }
            : { api: api() }),
      });
    resolve(empty);
    expect(await retired).toEqual({
      summary: null,
      waiting: false,
      retired: true,
    });
    expect(hook.result.current.publication.current.active).toBe(false);
  });
}

it("does not reuse run A's active lease for run B or a Zeus read", async () => {
  for (const [id, mode] of [
    ["other-run", "local"],
    [run.display_name, "zeus"],
  ] as const) {
    const p = new LocalRunPublication(),
      client = api();
    p.start(run.display_name);
    expect(await observeNewLocalRun(client, id, p, () => true, mode)).toEqual({
      summary: null,
      waiting: false,
    });
    expect(p.active).toBe(false);
    expect(client.catalog).not.toHaveBeenCalled();
  }
});

it("rejects a retired read even when a new generation starts the same run ID", async () => {
  const p = new LocalRunPublication(),
    client = api();
  p.start(run.display_name);
  let resolve!: (value: typeof empty) => void;
  client.catalog.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const old = observeNewLocalRun(client, run.display_name, p, () => true);
  p.finish();
  p.start(run.display_name);
  resolve(empty);
  expect(await old).toEqual({ summary: null, waiting: false, retired: true });
  expect(p.missing(true)).toBe(true);
  expect(p.missing(true)).toBe(true);
});

it("rejects a retired context's late HTTP error without masking a current error", async () => {
  const p = new LocalRunPublication(),
    client = api();
  p.start(run.display_name);
  let reject!: (error: Error) => void;
  client.catalog.mockReturnValueOnce(
    new Promise((_done, fail) => {
      reject = fail;
    }),
  );
  const old = observeNewLocalRun(client, run.display_name, p, () => true);
  p.finish();
  reject(new Error("old context HTTP error"));
  expect(await old).toEqual({ summary: null, waiting: false, retired: true });
});

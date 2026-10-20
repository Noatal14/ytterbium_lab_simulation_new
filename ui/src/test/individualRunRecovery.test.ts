import { afterEach, describe, expect, it, vi } from "vitest";
import {
  confirmRememberedZeusRun,
  forgetIndividualRun,
  readRememberedIndividualRun,
  recoveredRunStep,
  recoverIndividualRun,
  rememberIndividualRun,
} from "../features/individual/individualRunRecovery";
import { IndividualZeusApiError } from "../api/clients/individualZeusRecovery";

const row = (overrides: Record<string, unknown> = {}) => ({
  id: `individual-run-${"a".repeat(24)}`,
  display_name: "mot2d-recovery",
  lifecycle: "running",
  record_state: "running",
  execution: { mode: "local" as const },
  ...overrides,
});

describe("individual run recovery", () => {
  afterEach(() => {
    for (const family of ["zeeman", "mot_2d", "mot_3d"] as const)
      forgetIndividualRun(family);
  });

  it.each(["running", "failed"])(
    "recovers a verified %s summary without starting or fetching detail",
    async (state) => {
      rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
      const summary = row({ lifecycle: state, record_state: state });
      const api = { runs: vi.fn(async () => [summary]), run: vi.fn() };
      await expect(recoverIndividualRun("mot_2d", api)).resolves.toEqual(
        summary,
      );
      expect(api.runs).toHaveBeenCalledOnce();
      expect(api.run).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["zeeman" as const, "zeeman-recovery"],
    ["mot_2d" as const, "mot2d-recovery"],
    ["mot_3d" as const, "mot3d-recovery"],
  ])(
    "restores a created local %s run to Run without auto-starting",
    async (family, displayName) => {
      rememberIndividualRun(family, displayName, "local");
      const summary = row({
        display_name: displayName,
        lifecycle: "configured",
        record_state: "configured",
      });
      const startLocal = vi.fn<
        (runId: string) => Promise<{ status: "queued" }>
      >(async () => ({ status: "queued" }));
      const found = await recoverIndividualRun(family, {
        runs: vi.fn(async () => [summary]),
        run: vi.fn(),
      });

      expect(found).not.toBeNull();
      expect(recoveredRunStep(found!)).toBe("run");
      expect(startLocal).not.toHaveBeenCalled();

      await startLocal(displayName);
      expect(startLocal).toHaveBeenCalledOnce();
    },
  );

  it.each([
    ["zeeman" as const, "zeeman-recovery"],
    ["mot_2d" as const, "mot2d-recovery"],
    ["mot_3d" as const, "mot3d-recovery"],
  ])(
    "recovers a local %s run after a lost start response without restarting",
    async (family, displayName) => {
      rememberIndividualRun(family, displayName, "local");
      const startLocal = vi.fn<(runId: string) => Promise<never>>(async () => {
        throw new Error("response lost after local start");
      });
      await expect(startLocal(displayName)).rejects.toThrow(/response lost/);

      const summary = row({
        display_name: displayName,
        lifecycle: "running",
        record_state: "running",
      });
      const found = await recoverIndividualRun(family, {
        runs: vi.fn(async () => [summary]),
        run: vi.fn(),
      });

      expect(found).not.toBeNull();
      expect(recoveredRunStep(found!)).toBe("monitor");
      expect(startLocal).toHaveBeenCalledOnce();
    },
  );

  it.each([
    ["configured", "configured", "run"],
    ["configured", "validated", "run"],
    ["configured", "reviewed", "run"],
    ["queued", "queued", "monitor"],
    ["running", "running", "monitor"],
    ["failed", "failed", "monitor"],
    ["results_ready", "succeeded", "results"],
  ])(
    "maps lifecycle %s / record %s to %s",
    (lifecycle, recordState, expected) => {
      expect(
        recoveredRunStep(row({ lifecycle, record_state: recordState })),
      ).toBe(expected);
    },
  );

  it("re-fetches exact verified detail for a completed run", async () => {
    rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
    const summary = row({
      lifecycle: "results_ready",
      record_state: "succeeded",
    });
    const detail = { ...summary, metrics: { n_survivors: 4 } };
    const api = {
      runs: vi.fn(async () => [summary]),
      run: vi.fn(async () => detail),
    };
    await expect(recoverIndividualRun("mot_2d", api)).resolves.toEqual(detail);
    expect(api.run).toHaveBeenCalledWith(summary.id);
  });

  it.each([
    ["duplicate", [row(), row({ id: `individual-run-${"b".repeat(24)}` })]],
    ["wrong execution context", [row({ execution: { mode: "zeus" } })]],
  ])(
    "fails closed for a %s catalog result and forgets it",
    async (_label, rows) => {
      rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
      const api = { runs: vi.fn(async () => rows), run: vi.fn() };
      await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
        /not restarted/,
      );
      await expect(recoverIndividualRun("mot_2d", api)).resolves.toBeNull();
    },
  );

  it("keeps a remembered run unresolved when it is absent from the current catalog", async () => {
    rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
    const api = { runs: vi.fn(async () => []), run: vi.fn() };
    await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
      /remains remembered/,
    );
    await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
      /remains remembered/,
    );
  });

  it.each([
    ["truncated", { invalid_count: 0, truncated: true }],
    ["invalid", { invalid_count: 2, truncated: false }],
  ])(
    "reports an actionable incomplete-catalog warning for %s metadata",
    async (_label, metadata) => {
      rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
      const api = {
        runs: vi.fn(),
        catalog: vi.fn(async () => ({ runs: [], total: 0, ...metadata })),
        run: vi.fn(),
      };
      await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
        /catalog is incomplete/,
      );
      expect(api.runs).not.toHaveBeenCalled();
      await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
        /remains remembered/,
      );
    },
  );

  it("rejects malformed or wrong-family persisted identity without a catalog request", async () => {
    localStorage.setItem(
      "ytterbium.individual-run.mot_3d.v1",
      JSON.stringify({
        version: 1,
        family: "zeeman",
        display_name: "zeeman-wrong",
        execution_mode: "local",
      }),
    );
    const api = { runs: vi.fn(), run: vi.fn() };
    await expect(recoverIndividualRun("mot_3d", api)).resolves.toBeNull();
    expect(api.runs).not.toHaveBeenCalled();
  });

  it("fails closed when completed detail changes identity", async () => {
    rememberIndividualRun("mot_2d", "mot2d-recovery", "local");
    const summary = row({
      lifecycle: "results_ready",
      record_state: "succeeded",
    });
    const api = {
      runs: vi.fn(async () => [summary]),
      run: vi.fn(async () => ({ ...summary, display_name: "mot2d-other" })),
    };
    await expect(recoverIndividualRun("mot_2d", api)).rejects.toThrow(
      /did not match/,
    );
  });

  it("persists only the safe Zeus username context", () => {
    rememberIndividualRun("mot_2d", "mot2d-recovery", "zeus", "tal.noa");
    expect(readRememberedIndividualRun("mot_2d")).toEqual({
      version: 1,
      family: "mot_2d",
      display_name: "mot2d-recovery",
      execution_mode: "zeus",
      username: "tal.noa",
    });
    expect(() =>
      rememberIndividualRun("mot_2d", "mot2d-recovery", "zeus"),
    ).toThrow(/profile/);
    expect(() =>
      rememberIndividualRun("mot_2d", "mot2d-recovery", "local", "tal.noa"),
    ).toThrow(/local run/);
  });

  it.each([
    ["zeeman" as const, "zeeman-recovery"],
    ["mot_2d" as const, "mot2d-recovery"],
    ["mot_3d" as const, "mot3d-recovery"],
  ])(
    "keeps an ambiguous %s confirmation for one read-only recovery and never resubmits",
    async (family, displayName) => {
      const confirm = vi.fn(async () => {
        throw new Error("response lost after submission");
      });
      await expect(
        confirmRememberedZeusRun(family, displayName, "tal.noa", confirm),
      ).rejects.toThrow(/response lost/);
      expect(confirm).toHaveBeenCalledOnce();
      const summary = row({
        display_name: displayName,
        execution: { mode: "zeus" as const },
      });
      const catalog = vi.fn(async () => ({
        runs: [summary],
        invalid_count: 0,
        total: 1,
        truncated: false,
      }));
      const recoverZeus = vi.fn<
        (
          runId: string,
          username: string | undefined,
        ) => Promise<{ read_only: true }>
      >(async () => ({ read_only: true }));
      const found = await recoverIndividualRun(family, {
        runs: vi.fn(),
        catalog,
        run: vi.fn(),
      });
      const remembered = readRememberedIndividualRun(family);
      expect(found?.display_name).toBe(displayName);
      await recoverZeus(displayName, remembered?.username);
      expect(recoverZeus).toHaveBeenCalledOnce();
      expect(confirm).toHaveBeenCalledOnce();
    },
  );

  it.each([
    ["zeeman" as const, "zeeman-recovery"],
    ["mot_2d" as const, "mot2d-recovery"],
    ["mot_3d" as const, "mot3d-recovery"],
  ])(
    "removes a %s pointer after a definite rejection",
    async (family, displayName) => {
      const confirm = vi.fn(async () => {
        throw new IndividualZeusApiError("confirmation_expired", "expired");
      });
      await expect(
        confirmRememberedZeusRun(family, displayName, "tal.noa", confirm),
      ).rejects.toMatchObject({ code: "confirmation_expired" });
      expect(readRememberedIndividualRun(family)).toBeNull();
    },
  );
  it("fails closed before a Zeus submission when recovery storage is unavailable", async () => {
    const storage = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    const confirm = vi.fn();
    try {
      expect(rememberIndividualRun("mot_3d", "mot3d-storage", "local")).toBe(
        false,
      );
      await expect(
        confirmRememberedZeusRun("mot_3d", "mot3d-storage", "tal.noa", confirm),
      ).rejects.toThrow("Zeus submission was not attempted");
      expect(confirm).not.toHaveBeenCalled();
    } finally {
      storage.mockRestore();
    }
  });
});

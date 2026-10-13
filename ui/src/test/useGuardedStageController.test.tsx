import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useGuardedStageController, type GuardedStageOperations } from "../features/campaign/shared/useGuardedStageController";

const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
type Status = { action: "wait" | "review" | "blocked" | "done" };
type Preview = { token: string };
type Result = { status: "prepared" };

function setup(overrides: Partial<GuardedStageOperations<Status, Preview, Result>> = {}, contextKey = "campaign:profile") {
  const operations = {
    status: vi.fn(async () => ({ action: "review" as const })),
    preview: vi.fn(async () => ({ token: "token" })),
    confirm: vi.fn(async () => ({ status: "prepared" as const })),
    reset: vi.fn(),
    ...overrides,
  };
  const hook = renderHook(({ keyValue }) => useGuardedStageController({ enabled: true, contextKey: keyValue, operations, stateForStatus: (row) => row.action === "review" ? "ready" : row.action === "blocked" ? "blocked" : row.action === "done" ? "success" : "idle", canPreview: (row) => row?.action === "review", isUnknownConfirmation: (error) => error instanceof Error && error.message === "unknown" }), { initialProps: { keyValue: contextKey } });
  return { operations, hook };
}

describe("useGuardedStageController", () => {
  it("does not reset when an inline operations object is recreated", async () => {
    const reset = vi.fn();
    const { result, rerender } = renderHook(({ renderCount }) => {
      void renderCount;
      return useGuardedStageController({
        enabled: true,
        contextKey: "campaign:profile",
        operations: {
          status: async () => ({ action: "review" as const }),
          preview: async () => ({ token: "token" }),
          confirm: async () => ({ status: "prepared" as const }),
          reset,
        },
        stateForStatus: (row) => row.action === "review" ? "ready" : "idle",
        canPreview: (row) => row?.action === "review",
        isUnknownConfirmation: () => false,
      });
    }, { initialProps: { renderCount: 1 } });
    expect(reset).toHaveBeenCalledTimes(1);
    await act(async () => { await result.current.refresh(); });
    expect(result.current.phase).toBe("ready");
    rerender({ renderCount: 2 });
    expect(reset).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("ready");
  });

  it("coalesces synchronous duplicate status, preview, and confirm actions", async () => {
    const status = deferred<Status>(), preview = deferred<Preview>(), confirm = deferred<Result>();
    const { hook, operations } = setup({ status: vi.fn(() => status.promise), preview: vi.fn(() => preview.promise), confirm: vi.fn(() => confirm.promise) });
    act(() => { void hook.result.current.refresh(); void hook.result.current.refresh(); });
    expect(operations.status).toHaveBeenCalledTimes(1); await act(async () => status.resolve({ action: "review" }));
    act(() => { void hook.result.current.review(); void hook.result.current.review(); });
    expect(operations.preview).toHaveBeenCalledTimes(1); await act(async () => preview.resolve({ token: "token" }));
    act(() => { void hook.result.current.confirm(); void hook.result.current.confirm(); });
    expect(operations.confirm).toHaveBeenCalledTimes(1); await act(async () => confirm.resolve({ status: "prepared" }));
    expect(hook.result.current.phase).toBe("success");
    await act(async () => { await hook.result.current.confirm(); });
    expect(operations.confirm).toHaveBeenCalledTimes(1);
  });

  it("retires stale responses after context change and unmount", async () => {
    const first = deferred<Status>(); const { hook } = setup({ status: vi.fn(() => first.promise) });
    act(() => { void hook.result.current.refresh(); });
    hook.rerender({ keyValue: "other:profile" });
    await act(async () => first.resolve({ action: "review" }));
    expect(hook.result.current.status).toBeNull();
    const second = deferred<Status>(); const next = setup({ status: vi.fn(() => second.promise) });
    act(() => { void next.hook.result.current.refresh(); }); next.hook.unmount();
    await act(async () => second.resolve({ action: "review" }));
  });

  it("permits retry after deterministic confirmation rejection", async () => {
    const confirm = vi.fn().mockRejectedValueOnce(new Error("rejected")).mockResolvedValueOnce({ status: "prepared" });
    const { hook } = setup({ confirm });
    await act(async () => { await hook.result.current.refresh(); });
    await act(async () => { await hook.result.current.review(); });
    await act(async () => { await hook.result.current.confirm(); });
    expect(hook.result.current.errorPhase).toBe("confirm_rejected");
    await act(async () => { await hook.result.current.confirm(); });
    expect(confirm).toHaveBeenCalledTimes(2); expect(hook.result.current.phase).toBe("success");
  });

  it("consumes an ambiguous confirmation and refuses retry", async () => {
    const confirm = vi.fn(async () => { throw new Error("unknown"); }); const { hook } = setup({ confirm });
    await act(async () => { await hook.result.current.refresh(); }); await act(async () => { await hook.result.current.review(); });
    await act(async () => { await hook.result.current.confirm(); });
    expect(hook.result.current.errorPhase).toBe("confirm_unknown"); expect(hook.result.current.phase).toBe("blocked");
    await act(async () => { await hook.result.current.confirm(); }); expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("fails closed when a refresh rejects after a ready status", async () => {
    const status = vi.fn()
      .mockResolvedValueOnce({ action: "review" })
      .mockRejectedValueOnce(new Error("status unavailable"));
    const { hook, operations } = setup({ status });
    await act(async () => { await hook.result.current.refresh(); });
    expect(hook.result.current.phase).toBe("ready");
    await act(async () => { await hook.result.current.refresh(); });
    expect(hook.result.current.phase).toBe("idle");
    expect(hook.result.current.status).toBeNull();
    expect(hook.result.current.errorPhase).toBe("status");
    await act(async () => { await hook.result.current.review(); });
    expect(operations.preview).not.toHaveBeenCalled();
  });
});

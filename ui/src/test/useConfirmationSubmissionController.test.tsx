import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ConfirmationSubmissionApi } from "../api/clients/refinement";
import { useConfirmationSubmissionController } from "../features/campaign/controllers/useConfirmationSubmissionController";

const snapshot = {
  profile: {
    host: "zeus.technion.ac.il",
    username: "tal.noa",
    project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
    authentication: "ssh-key-or-agent",
  },
} as any;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function fakeApi(
  overrides: Partial<ConfirmationSubmissionApi> = {},
): ConfirmationSubmissionApi {
  return {
    status: vi.fn(),
    preview: vi.fn(),
    confirm: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  } as ConfirmationSubmissionApi;
}

describe("useConfirmationSubmissionController", () => {
  it("suppresses double-clicks while a review is pending", async () => {
    const pending = deferred<any>();
    const api = fakeApi({ preview: vi.fn(() => pending.promise) });
    const { result } = renderHook(() =>
      useConfirmationSubmissionController({
        campaignId: "campaign",
        snapshot,
        enabled: true,
        api,
      }),
    );
    let first!: Promise<void>;
    await act(async () => {
      first = result.current.review();
      void result.current.review();
    });
    expect(api.preview).toHaveBeenCalledOnce();
    await act(async () => {
      pending.resolve({ preview_token: "token" });
      await first;
    });
    expect(result.current.state).toBe("review");
  });

  it("ignores an older response after campaign context changes", async () => {
    const pending = deferred<any>();
    const firstApi = fakeApi({ preview: vi.fn(() => pending.promise) });
    const secondApi = fakeApi();
    const { result, rerender } = renderHook(
      ({ campaignId, api }) =>
        useConfirmationSubmissionController({
          campaignId,
          snapshot,
          enabled: true,
          api,
        }),
      { initialProps: { campaignId: "campaign-a", api: firstApi } },
    );
    let request!: Promise<void>;
    await act(async () => {
      request = result.current.review();
    });
    rerender({ campaignId: "campaign-b", api: secondApi });
    await act(async () => {
      pending.resolve({ preview_token: "stale-token" });
      await request;
    });
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
  });

  it.each([
    ["disabled", { enabled: false }],
    ["host", { snapshot: { profile: { ...snapshot.profile, host: "other.invalid" } } }],
    ["authentication", { snapshot: { profile: { ...snapshot.profile, authentication: "changed" } } }],
  ])("ignores an older response when %s changes", async (_label, change) => {
    const context = change as { enabled?: boolean; snapshot?: typeof snapshot };
    const pending = deferred<any>();
    const api = fakeApi({ preview: vi.fn(() => pending.promise) });
    const { result, rerender } = renderHook(
      ({ enabled, currentSnapshot }) => useConfirmationSubmissionController({
        campaignId: "campaign", snapshot: currentSnapshot as any, enabled, api,
      }),
      { initialProps: { enabled: true, currentSnapshot: snapshot } },
    );
    let request!: Promise<void>;
    await act(async () => { request = result.current.review(); });
    rerender({
      enabled: context.enabled ?? true,
      currentSnapshot: (context.snapshot ?? snapshot) as any,
    });
    await act(async () => { pending.resolve({ preview_token: "stale" }); await request; });
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
  });
});

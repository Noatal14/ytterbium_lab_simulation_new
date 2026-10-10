import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ZeusSnapshot } from "../api/clients/zeus";
import { useTransferController } from "../features/campaign/controllers/useTransferController";

const snapshot = {
  profile: {
    host: "zeus.technion.ac.il",
    username: "tal.noa",
    project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
    authentication: "ssh-key-or-agent",
  },
} as ZeusSnapshot;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("useTransferController", () => {
  it("does nothing when no Zeus profile is selected", async () => {
    const api = { preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot: null, api }));
    await act(() => result.current.previewTransfer());
    expect(api.preview).not.toHaveBeenCalled();
    expect(result.current.state).toBe("idle");
  });

  it("moves through previewing to review with the exact campaign and profile", async () => {
    const pending = deferred<any>();
    const api = { preview: vi.fn(() => pending.promise), confirm: vi.fn() };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    let request!: Promise<void>;
    act(() => { request = result.current.previewTransfer(); });
    expect(result.current.state).toBe("previewing");
    pending.resolve({ preview_token: "review-token" });
    await act(() => request);
    expect(api.preview).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(result.current.state).toBe("review");
    expect(result.current.preview?.preview_token).toBe("review-token");
  });

  it("returns to idle with an exact preview error", async () => {
    const api = { preview: vi.fn().mockRejectedValue(new Error("destination conflict")), confirm: vi.fn() };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewTransfer());
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBe("destination conflict");
  });

  it("moves through preparing to success using the reviewed token", async () => {
    const confirm = deferred<any>();
    const api = { preview: vi.fn().mockResolvedValue({ preview_token: "review-token" }), confirm: vi.fn(() => confirm.promise) };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewTransfer());
    let request!: Promise<void>;
    act(() => { request = result.current.confirmTransfer(); });
    expect(result.current.state).toBe("preparing");
    confirm.resolve({ campaign_id: "campaign", transferred_count: 1, reused_identical_count: 2 });
    await act(() => request);
    expect(api.confirm).toHaveBeenCalledWith("review-token");
    expect(result.current.state).toBe("success");
    expect(result.current.result?.campaign_id).toBe("campaign");
  });

  it("returns to review after confirm failure and preserves the preview", async () => {
    const api = { preview: vi.fn().mockResolvedValue({ preview_token: "review-token" }), confirm: vi.fn().mockRejectedValue(new Error("copy stopped")) };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewTransfer());
    await act(() => result.current.confirmTransfer());
    expect(result.current.state).toBe("review");
    expect(result.current.error).toBe("copy stopped");
    expect(result.current.preview?.preview_token).toBe("review-token");
  });

  it("resets the active review without rewriting a completed result", async () => {
    const completed = { campaign_id: "campaign", transferred_count: 1, reused_identical_count: 2 };
    const api = { preview: vi.fn().mockResolvedValue({ preview_token: "review-token" }), confirm: vi.fn().mockResolvedValue(completed) };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewTransfer());
    await act(() => result.current.confirmTransfer());
    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
    expect(result.current.error).toBe("");
    expect(result.current.result).toBe(completed);
  });

  it("allows only one preview and one confirmation request at a time", async () => {
    const previewRequest = deferred<any>();
    const confirmRequest = deferred<any>();
    const api = { preview: vi.fn(() => previewRequest.promise), confirm: vi.fn(() => confirmRequest.promise) };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    let firstPreview!: Promise<void>;
    act(() => {
      firstPreview = result.current.previewTransfer();
      void result.current.previewTransfer();
    });
    expect(api.preview).toHaveBeenCalledTimes(1);
    previewRequest.resolve({ preview_token: "review-token" });
    await act(() => firstPreview);
    let firstConfirm!: Promise<void>;
    act(() => {
      firstConfirm = result.current.confirmTransfer();
      void result.current.confirmTransfer();
    });
    expect(api.confirm).toHaveBeenCalledTimes(1);
    confirmRequest.resolve({ campaign_id: "campaign" });
    await act(() => firstConfirm);
  });

  it("retires a pending preview when reset is selected", async () => {
    const pending = deferred<any>();
    const api = { preview: vi.fn(() => pending.promise), confirm: vi.fn() };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    let request!: Promise<void>;
    act(() => { request = result.current.previewTransfer(); });
    act(() => result.current.reset());
    pending.resolve({ preview_token: "stale-token" });
    await act(() => request);
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
  });

  it.each([
    ["campaign", "campaign-b", snapshot],
    ["profile", "campaign-a", { ...snapshot, profile: { ...snapshot.profile, username: "other.user", project_directory: "/home/other.user/ytterbium_lab_simulation_new" } }],
  ] as const)("retires a pending preview when the %s changes", async (_label, nextCampaign, nextSnapshot) => {
    const pending = deferred<any>();
    const api = { preview: vi.fn(() => pending.promise), confirm: vi.fn() };
    const { result, rerender } = renderHook(
      ({ campaignId, value }: { campaignId: string; value: ZeusSnapshot }) => useTransferController({ campaignId, snapshot: value, api }),
      { initialProps: { campaignId: "campaign-a", value: snapshot } },
    );
    let request!: Promise<void>;
    act(() => { request = result.current.previewTransfer(); });
    rerender({ campaignId: nextCampaign, value: nextSnapshot });
    pending.resolve({ preview_token: "stale-token" });
    await act(() => request);
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
    expect(result.current.result).toBeNull();
  });

  it("retires a pending preview when the API instance changes", async () => {
    const pending = deferred<any>();
    const firstApi = { preview: vi.fn(() => pending.promise), confirm: vi.fn() };
    const secondApi = { preview: vi.fn(), confirm: vi.fn() };
    const { result, rerender } = renderHook(
      ({ api }: { api: typeof firstApi }) => useTransferController({ campaignId: "campaign", snapshot, api }),
      { initialProps: { api: firstApi } },
    );
    let request!: Promise<void>;
    act(() => { request = result.current.previewTransfer(); });
    rerender({ api: secondApi });
    pending.resolve({ preview_token: "stale-token" });
    await act(() => request);
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
  });

  it.each(["reset", "campaign", "profile", "api", "unmount"] as const)("retires a pending confirmation after %s", async (boundary) => {
    const pending = deferred<any>();
    const firstApi = { preview: vi.fn().mockResolvedValue({ preview_token: "review-token" }), confirm: vi.fn(() => pending.promise) };
    const secondApi = { preview: vi.fn(), confirm: vi.fn() };
    const { result, rerender, unmount } = renderHook(
      ({ campaignId, value, api }: { campaignId: string; value: ZeusSnapshot; api: typeof firstApi }) => useTransferController({ campaignId, snapshot: value, api }),
      { initialProps: { campaignId: "campaign-a", value: snapshot, api: firstApi } },
    );
    await act(() => result.current.previewTransfer());
    let request!: Promise<void>;
    act(() => { request = result.current.confirmTransfer(); });
    if (boundary === "reset") act(() => result.current.reset());
    else if (boundary === "campaign") rerender({ campaignId: "campaign-b", value: snapshot, api: firstApi });
    else if (boundary === "profile") rerender({ campaignId: "campaign-a", value: { ...snapshot, profile: { ...snapshot.profile, username: "other.user" } }, api: firstApi });
    else if (boundary === "api") rerender({ campaignId: "campaign-a", value: snapshot, api: secondApi });
    else unmount();
    pending.resolve({ campaign_id: "stale-campaign" });
    await act(() => request);
    if (boundary !== "unmount") {
      expect(result.current.state).toBe("idle");
      expect(result.current.result).toBeNull();
    }
  });

  it("releases the in-flight lock after a rejected request", async () => {
    const api = { preview: vi.fn().mockRejectedValueOnce(new Error("temporary")).mockResolvedValueOnce({ preview_token: "retry-token" }), confirm: vi.fn() };
    const { result } = renderHook(() => useTransferController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewTransfer());
    await act(() => result.current.previewTransfer());
    expect(api.preview).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe("review");
    expect(result.current.preview?.preview_token).toBe("retry-token");
  });
});

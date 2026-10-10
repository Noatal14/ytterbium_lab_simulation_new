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
});

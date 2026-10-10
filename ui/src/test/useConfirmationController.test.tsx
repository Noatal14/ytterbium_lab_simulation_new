import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RefinementLifecycleApiError } from "../api/clients/refinement";
import type { ZeusSnapshot } from "../api/clients/zeus";
import { parseRefinementLifecycle } from "../api/schema/domain";
import { useConfirmationController } from "../features/campaign/controllers/useConfirmationController";

const snapshot = { profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } } as ZeusSnapshot;
const readyLifecycle = parseRefinementLifecycle({
  source: "zeus", queried_at: "2026-10-10T10:00:00Z",
  campaign: { id: "campaign", name: "Campaign", stage: "refine" },
  chain: { status: "ready_to_prepare_confirmation", rounds: [1, 2, 3, 4].map((round) => ({ round, job_id: `${round}[].zeus-master`, depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master`, scheduler: { state: "completed_success", task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } } })) },
  validation: { status: "valid", completed_trials: 30, expected_trials: 30, candidate_count: 5 },
  next_action: "review_confirmation_preparation", local_sync: { status: "not_synchronized" },
});
const preparedLifecycle = parseRefinementLifecycle({ ...readyLifecycle, campaign: { ...readyLifecycle.campaign, stage: "confirmation" }, chain: { ...readyLifecycle.chain, status: "confirmation_prepared" }, next_action: "none" });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("useConfirmationController", () => {
  it("refreshes the authoritative lifecycle and recognizes prepared confirmation", async () => {
    const api = { status: vi.fn().mockResolvedValue(preparedLifecycle), preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    expect(api.status).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(result.current.lifecycle).toBe(preparedLifecycle);
    expect(result.current.lifecycleCheck).toBe("ready");
    expect(result.current.state).toBe("success");
  });

  it("clears stale lifecycle and reports refresh failure", async () => {
    const api = { status: vi.fn().mockResolvedValueOnce(readyLifecycle).mockRejectedValueOnce(new Error("status unavailable")), preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.refresh());
    expect(result.current.lifecycle).toBeNull();
    expect(result.current.lifecycleCheck).toBe("error");
    expect(result.current.error).toBe("status unavailable");
  });

  it("reviews only validated ready evidence and confirms the reviewed token", async () => {
    const preview = { preview_token: "confirmation-token" } as any;
    const confirmation = { campaign_id: "campaign" } as any;
    const api = { status: vi.fn().mockResolvedValue(readyLifecycle), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockResolvedValue(confirmation) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewConfirmation());
    expect(api.preview).not.toHaveBeenCalled();
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    expect(api.preview).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(result.current.state).toBe("review");
    await act(() => result.current.confirmConfirmation());
    expect(api.confirm).toHaveBeenCalledWith("confirmation-token");
    expect(result.current.result).toBe(confirmation);
    expect(result.current.state).toBe("success");
    expect(result.current.lifecycle?.campaign.stage).toBe("confirmation");
    expect(result.current.lifecycle?.chain.status).toBe("confirmation_prepared");
    expect(result.current.lifecycle?.validation).toBe(readyLifecycle.validation);
  });

  it("recovers an already-prepared preview from authoritative status", async () => {
    const api = { status: vi.fn().mockResolvedValueOnce(readyLifecycle).mockResolvedValueOnce(preparedLifecycle), preview: vi.fn().mockRejectedValue(new RefinementLifecycleApiError("confirmation_already_prepared", "Already prepared")), confirm: vi.fn() };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycle).toBe(preparedLifecycle);
    expect(result.current.state).toBe("success");
  });

  it("retires a fresh-review failure without automatic retry", async () => {
    const api = { status: vi.fn().mockResolvedValue(readyLifecycle), preview: vi.fn().mockResolvedValue({ preview_token: "token" }), confirm: vi.fn().mockRejectedValue(new RefinementLifecycleApiError("confirmation_expired", "Review expired")) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    await act(() => result.current.confirmConfirmation());
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
    expect(result.current.error).toBe("Review expired");
    expect(api.confirm).toHaveBeenCalledTimes(1);
  });

  it("recovers an already-prepared confirmation from durable status", async () => {
    const api = { status: vi.fn().mockResolvedValueOnce(readyLifecycle).mockResolvedValueOnce(preparedLifecycle), preview: vi.fn().mockResolvedValue({ preview_token: "token" }), confirm: vi.fn().mockRejectedValue(new RefinementLifecycleApiError("confirmation_already_prepared", "Already prepared")) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    await act(() => result.current.confirmConfirmation());
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycle).toBe(preparedLifecycle);
    expect(result.current.state).toBe("success");
    expect(result.current.preview).toBeNull();
  });

  it.each(["success", "failure"] as const)("preserves terminal confirmation warning when recovery status ends in %s", async (recovery) => {
    const status = vi.fn().mockResolvedValueOnce(readyLifecycle);
    if (recovery === "success") status.mockResolvedValueOnce(readyLifecycle);
    else status.mockRejectedValueOnce(new Error("recovery unavailable"));
    const api = { status, preview: vi.fn().mockResolvedValue({ preview_token: "token" }), confirm: vi.fn().mockRejectedValue(new RefinementLifecycleApiError("internal_secret_code", "Manual verification required")) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    await act(() => result.current.confirmConfirmation());
    expect(result.current.state).toBe("terminal");
    expect(result.current.preview).toBeNull();
    expect(result.current.error).toBe("Manual verification required");
    expect(result.current.lifecycleCheck).toBe(recovery === "success" ? "ready" : "error");
  });

  it("preserves lifecycle and completed result when reset", async () => {
    const confirmation = { campaign_id: "campaign" } as any;
    const api = { status: vi.fn().mockResolvedValue(readyLifecycle), preview: vi.fn().mockResolvedValue({ preview_token: "token" }), confirm: vi.fn().mockResolvedValue(confirmation) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    await act(() => result.current.confirmConfirmation());
    const lifecycle = result.current.lifecycle;
    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
    expect(result.current.error).toBe("");
    expect(result.current.result).toBe(confirmation);
    expect(result.current.lifecycle).toBe(lifecycle);
  });

  it("serializes refresh, preview, and confirm requests", async () => {
    const statusRequest = deferred<any>();
    const previewRequest = deferred<any>();
    const confirmRequest = deferred<any>();
    const api = { status: vi.fn(() => statusRequest.promise), preview: vi.fn(() => previewRequest.promise), confirm: vi.fn(() => confirmRequest.promise) };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    let status!: Promise<void>;
    act(() => { status = result.current.refresh(); void result.current.refresh(); void result.current.previewConfirmation(); });
    expect(api.status).toHaveBeenCalledTimes(1);
    expect(api.preview).not.toHaveBeenCalled();
    statusRequest.resolve(readyLifecycle);
    await act(() => status);
    let review!: Promise<void>;
    act(() => { review = result.current.previewConfirmation(); void result.current.previewConfirmation(); });
    expect(api.preview).toHaveBeenCalledTimes(1);
    previewRequest.resolve({ preview_token: "token" });
    await act(() => review);
    let confirmation!: Promise<void>;
    act(() => { confirmation = result.current.confirmConfirmation(); void result.current.confirmConfirmation(); void result.current.refresh(); });
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.status).toHaveBeenCalledTimes(1);
    confirmRequest.resolve({ campaign_id: "campaign" });
    await act(() => confirmation);
  });

  it.each(["reset", "campaign", "profile", "api", "unmount"] as const)("retires a pending confirmation after %s", async (boundary) => {
    const pending = deferred<any>();
    const firstApi = { status: vi.fn().mockResolvedValue(readyLifecycle), preview: vi.fn().mockResolvedValue({ preview_token: "token" }), confirm: vi.fn(() => pending.promise) };
    const secondApi = { status: vi.fn(), preview: vi.fn(), confirm: vi.fn() };
    const { result, rerender, unmount } = renderHook(
      ({ campaignId, value, api }: { campaignId: string; value: ZeusSnapshot; api: typeof firstApi }) => useConfirmationController({ campaignId, snapshot: value, api }),
      { initialProps: { campaignId: "campaign", value: snapshot, api: firstApi } },
    );
    await act(() => result.current.refresh());
    await act(() => result.current.previewConfirmation());
    let request!: Promise<void>;
    act(() => { request = result.current.confirmConfirmation(); });
    if (boundary === "reset") act(() => result.current.reset());
    else if (boundary === "campaign") rerender({ campaignId: "other", value: snapshot, api: firstApi });
    else if (boundary === "profile") rerender({ campaignId: "campaign", value: { ...snapshot, profile: { ...snapshot.profile, username: "other.user" } }, api: firstApi });
    else if (boundary === "api") rerender({ campaignId: "campaign", value: snapshot, api: secondApi });
    else unmount();
    pending.resolve({ campaign_id: "stale" });
    await act(() => request);
    if (boundary !== "unmount") {
      expect(result.current.state).toBe("idle");
      expect(result.current.result).toBeNull();
    }
  });

  it("prevents an older status response from overwriting a newer generation", async () => {
    const pending = deferred<any>();
    const firstApi = { status: vi.fn(() => pending.promise), preview: vi.fn(), confirm: vi.fn() };
    const secondApi = { status: vi.fn().mockResolvedValue(preparedLifecycle), preview: vi.fn(), confirm: vi.fn() };
    const { result, rerender } = renderHook(
      ({ api }: { api: typeof firstApi }) => useConfirmationController({ campaignId: "campaign", snapshot, api }),
      { initialProps: { api: firstApi } },
    );
    let stale!: Promise<void>;
    act(() => { stale = result.current.refresh(); });
    rerender({ api: secondApi });
    await act(() => result.current.refresh());
    pending.resolve(readyLifecycle);
    await act(() => stale);
    expect(result.current.lifecycle).toBe(preparedLifecycle);
    expect(result.current.state).toBe("success");
  });

  it("releases the lock after a rejected refresh", async () => {
    const api = { status: vi.fn().mockRejectedValueOnce(new Error("temporary")).mockResolvedValueOnce(readyLifecycle), preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useConfirmationController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    await act(() => result.current.refresh());
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycle).toBe(readyLifecycle);
    expect(result.current.lifecycleCheck).toBe("ready");
  });
});

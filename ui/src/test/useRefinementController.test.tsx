import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RefinementSubmissionApiError } from "../api/clients/refinement";
import type { ZeusSnapshot } from "../api/clients/zeus";
import { parseRefinementChainStatus, parseRefinementSubmissionPreview, parseRefinementSubmissionResult } from "../api/schema/domain";
import { MOT_2D_SPECIFICATION_V1 } from "../generated/mot2dSpec.v1";
import { useRefinementController } from "../features/campaign/controllers/useRefinementController";

const snapshot = { profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } } as ZeusSnapshot;
const rounds = [1, 2, 3, 4] as const;
const notSubmitted = parseRefinementChainStatus({
  source: "zeus", queried_at: "2026-10-10T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "refine" },
  chain: { status: "not_submitted", dependency: "afterok", rounds: rounds.map((round) => ({ round, state: "not_submitted", job_id: null, depends_on_job_id: null })) },
  next_action: "review_submission", local_sync: { status: "not_synchronized" },
});
const partial = parseRefinementChainStatus({ ...notSubmitted, chain: { ...notSubmitted.chain, status: "partial", rounds: rounds.map((round) => ({ round, state: round === 1 ? "submitted" : "not_submitted", job_id: round === 1 ? "1[].zeus-master" : null, depends_on_job_id: null })) }, next_action: "inspect_zeus" });
const submitted = parseRefinementChainStatus({ ...notSubmitted, queried_at: "2026-10-10T10:05:00Z", chain: { ...notSubmitted.chain, status: "submitted", rounds: rounds.map((round) => ({ round, state: "submitted", job_id: `${round}[].zeus-master`, depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master` })) }, next_action: "none" });
const preview = parseRefinementSubmissionPreview({
  preview_token: "refinement-token", expires_in_seconds: 300,
  campaign: { id: "campaign", name: "Campaign", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "refine", label: "Refinement" },
  chain: { dependency: "afterok", rounds: MOT_2D_SPECIFICATION_V1.stages.refine.cumulative_trial_targets.map((target, index) => ({ round: index + 1, file: MOT_2D_SPECIFICATION_V1.stages.refine.round_job_files[index], cumulative_target: target, kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 72000, depends_on: index === 0 ? null : index })) },
  remote: { host: "zeus.technion.ac.il", project_directory: snapshot.profile.project_directory, commit: "a".repeat(40), branch: "main", dirty: false }, effects: { submit_refinement_chain: true, start_simulation: true, submit_later_stages: false, modify_files: false }, local_sync: { status: "not_synchronized" },
});
const submission = parseRefinementSubmissionResult({ status: "submitted", campaign_id: "campaign", stage: "refine", chain: { status: "submitted", rounds: rounds.map((round) => ({ round, job_id: `${round}[].zeus-master`, depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master` })) }, submitted_at: "2026-10-10T10:05:00Z", local_sync: { status: "not_synchronized" } });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

afterEach(() => vi.useRealTimers());

describe("useRefinementController", () => {
  it("loads authoritative state and blocks partial chains", async () => {
    const api = { status: vi.fn().mockResolvedValue(partial), preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    expect(api.status).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(result.current.status).toBe(partial);
    expect(result.current.check).toBe("ready");
    expect(result.current.state).toBe("blocked");
  });

  it.each([[notSubmitted, "idle"], [submitted, "submitted"]] as const)("maps a direct %s receipt", async (receipt, expected) => {
    const api = { status: vi.fn().mockResolvedValue(receipt), preview: vi.fn(), confirm: vi.fn() };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh());
    expect(result.current.state).toBe(expected);
  });

  it("reviews only after a fresh not-submitted receipt and confirms its exact token", async () => {
    const api = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockResolvedValue(submission) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.previewSubmission());
    expect(api.preview).not.toHaveBeenCalled();
    await act(() => result.current.refresh());
    await act(() => result.current.previewSubmission());
    expect(api.preview).toHaveBeenCalledWith("campaign", snapshot.profile);
    await act(() => result.current.confirmSubmission());
    expect(api.confirm).toHaveBeenCalledWith("refinement-token");
    expect(result.current.state).toBe("submitted");
    expect(result.current.status?.chain.rounds.map((row) => row.job_id)).toEqual(["1[].zeus-master", "2[].zeus-master", "3[].zeus-master", "4[].zeus-master"]);
    expect(result.current.status?.queried_at).toBe(submission.submitted_at);
  });

  it("serializes status, preview, and confirm actions", async () => {
    const statusRequest = deferred<any>(), previewRequest = deferred<any>(), confirmRequest = deferred<any>();
    const api = { status: vi.fn(() => statusRequest.promise), preview: vi.fn(() => previewRequest.promise), confirm: vi.fn(() => confirmRequest.promise) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    let status!: Promise<void>;
    act(() => { status = result.current.refresh(); void result.current.refresh(); void result.current.previewSubmission(); });
    expect(api.status).toHaveBeenCalledOnce();
    statusRequest.resolve(notSubmitted); await act(() => status);
    let review!: Promise<void>;
    act(() => { review = result.current.previewSubmission(); void result.current.previewSubmission(); });
    expect(api.preview).toHaveBeenCalledOnce();
    previewRequest.resolve(preview); await act(() => review);
    let confirm!: Promise<void>;
    act(() => { confirm = result.current.confirmSubmission(); void result.current.confirmSubmission(); void result.current.refresh(); });
    expect(api.confirm).toHaveBeenCalledOnce();
    confirmRequest.resolve(submission); await act(() => confirm);
  });

  it("polls without overlap and a late poll cannot overwrite the final receipt", async () => {
    vi.useFakeTimers();
    const poll = deferred<any>(), confirmation = deferred<any>();
    const api = { status: vi.fn().mockResolvedValueOnce(notSubmitted).mockImplementation(() => poll.promise), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn(() => confirmation.promise) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission());
    let request!: Promise<void>;
    act(() => { request = result.current.confirmSubmission(); });
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(api.status).toHaveBeenCalledTimes(2);
    confirmation.resolve(submission); await act(() => request);
    poll.resolve(partial); await act(async () => { await Promise.resolve(); });
    expect(result.current.state).toBe("submitted");
    expect(result.current.status?.chain.status).toBe("submitted");
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(api.status).toHaveBeenCalledTimes(2);
  });

  it("retires an expired review without retrying submission", async () => {
    const api = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockRejectedValue(new RefinementSubmissionApiError("confirmation_expired", "Expired")) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission()); await act(() => result.current.confirmSubmission());
    expect(result.current.preview).toBeNull();
    expect(result.current.state).toBe("error");
    expect(result.current.error).toContain("expired");
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("preserves an ambiguous submission warning while recovering durable status", async () => {
    const api = { status: vi.fn().mockResolvedValueOnce(notSubmitted).mockResolvedValueOnce(partial), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockRejectedValue(new RefinementSubmissionApiError("submission_outcome_unknown", "Do not retry")) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission()); await act(() => result.current.confirmSubmission());
    expect(result.current.state).toBe("blocked");
    expect(result.current.error).toBe("Do not retry");
    expect(result.current.status).toBe(partial);
  });

  it.each(["not_submitted", "failure"] as const)("keeps ambiguous confirmation blocked when recovery ends in %s", async (recovery) => {
    const status = vi.fn().mockResolvedValueOnce(notSubmitted);
    if (recovery === "not_submitted") status.mockResolvedValueOnce(notSubmitted);
    else status.mockRejectedValueOnce(new Error("status unavailable"));
    const api = { status, preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn().mockRejectedValue(new RefinementSubmissionApiError("refinement_submission_outcome_unknown", "Do not retry")) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission()); await act(() => result.current.confirmSubmission());
    expect(result.current.state).toBe("blocked");
    expect(result.current.error).toBe("Do not retry");
    expect(result.current.check).toBe(recovery === "not_submitted" ? "ready" : "error");
  });

  it("keeps manual preview failure blocked after authoritative recovery", async () => {
    const api = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockRejectedValue(new RefinementSubmissionApiError("refinement_already_started", "Inspect Zeus")), confirm: vi.fn() };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission());
    expect(result.current.state).toBe("blocked");
    expect(result.current.error).toBe("Inspect Zeus");
  });

  it("does not reset or authorize another review while confirmation is in flight", async () => {
    const pending = deferred<any>();
    const api = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn(() => pending.promise) };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission());
    let request!: Promise<void>; act(() => { request = result.current.confirmSubmission(); result.current.reset(); void result.current.previewSubmission(); });
    expect(result.current.state).toBe("submitting");
    expect(api.preview).toHaveBeenCalledOnce();
    pending.resolve(submission); await act(() => request);
    expect(result.current.state).toBe("submitted");
  });

  it("allows an ordinary reviewed preview to be reset", async () => {
    const api = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn() };
    const { result } = renderHook(() => useRefinementController({ campaignId: "campaign", snapshot, api }));
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission());
    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
    expect(result.current.preview).toBeNull();
    expect(result.current.status).toBe(notSubmitted);
    expect(result.current.check).toBe("ready");
  });

  it.each(["campaign", "profile", "api", "unmount"] as const)("retires pending confirmation and polling after %s", async (boundary) => {
    vi.useFakeTimers();
    const pending = deferred<any>();
    const firstApi = { status: vi.fn().mockResolvedValue(notSubmitted), preview: vi.fn().mockResolvedValue(preview), confirm: vi.fn(() => pending.promise) };
    const secondApi = { status: vi.fn(), preview: vi.fn(), confirm: vi.fn() };
    const { result, rerender, unmount } = renderHook(({ campaignId, value, api }: any) => useRefinementController({ campaignId, snapshot: value, api }), { initialProps: { campaignId: "campaign", value: snapshot, api: firstApi } });
    await act(() => result.current.refresh()); await act(() => result.current.previewSubmission());
    let request!: Promise<void>; act(() => { request = result.current.confirmSubmission(); });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    if (boundary === "campaign") rerender({ campaignId: "other", value: snapshot, api: firstApi });
    else if (boundary === "profile") rerender({ campaignId: "campaign", value: { ...snapshot, profile: { ...snapshot.profile, username: "other" } }, api: firstApi });
    else if (boundary === "api") rerender({ campaignId: "campaign", value: snapshot, api: secondApi });
    else unmount();
    pending.resolve(submission); await act(() => request);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    if (boundary !== "unmount") { expect(result.current.state).toBe("idle"); expect(result.current.result).toBeNull(); }
  });
});

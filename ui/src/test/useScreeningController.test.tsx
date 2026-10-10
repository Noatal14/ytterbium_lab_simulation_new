import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScreeningLifecycleApiError, ScreeningSubmissionApiError } from "../api/clients/screening";
import type { ZeusSnapshot } from "../api/clients/zeus";
import { parseRefinementPreview, parseRefinementResult, parseScreeningLifecycle, parseScreeningSubmissionPreview, parseScreeningSubmissionResult, parseSmokeLifecycle } from "../api/schema/domain";
import { MOT_2D_SPECIFICATION_V1 } from "../generated/mot2dSpec.v1";
import { useScreeningController } from "../features/campaign/controllers/useScreeningController";

const snapshot = { profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } } as ZeusSnapshot;
const smokePrepared = parseSmokeLifecycle({ source: "zeus", queried_at: "2026-10-10T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "screen" }, submission: { job_id: "1.zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 }, validation: { status: "valid", points: [{ s0: 1.3, captured: 1, input: 2, efficiency: 0.5 }], artifact_count: 3 }, lifecycle: "screen_prepared", next_action: "none" });
const screeningSubmissionPreview = parseScreeningSubmissionPreview({ preview_token: "submission-token", expires_in_seconds: 300, campaign: { id: "campaign", name: "Campaign", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "screen", label: MOT_2D_SPECIFICATION_V1.stages.screen.label, purpose: "Search broadly." }, job: { file: MOT_2D_SPECIFICATION_V1.stages.screen.job_file, kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 86400 }, remote: { host: "zeus.technion.ac.il", project_directory: snapshot.profile.project_directory, commit: "a".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, smoke: { status: "validated", job_id: "1.zeus-master", point_count: 1 }, effects: { submit_screening: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true });
const screeningSubmissionResult = parseScreeningSubmissionResult({ status: "submitted", campaign_id: "campaign", stage: "screen", job_id: "2[].zeus-master", submitted_at: "2026-10-10T10:01:00Z", later_stages_locked: true });
const ready = parseScreeningLifecycle({ source: "zeus", queried_at: "2026-10-10T11:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "screen" }, submission: { job_id: "2[].zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0, task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } }, validation: { status: "valid", completed_trials: 51, expected_trials: 51, candidate_count: 3 }, lifecycle: "ready_to_prepare_refinement", next_action: "review_refinement_preparation" });
const prepared = parseScreeningLifecycle({ ...ready, queried_at: "2026-10-10T11:01:00Z", campaign: { ...ready.campaign, stage: "refine" }, lifecycle: "refinement_prepared", next_action: "none" });
const candidates = [0, 1, 2].map((index) => ({ s0: 1.3, rank: index + 1, detuning_gamma: -1 + index * 0.01, magnet_radius_m: 0.046 + index * 0.00001, mean_conditional_efficiency: 0.02, source: `screen/s0_1p300000/worker${index}/trials/trial_000${index}.json` }));
const refinementPreview = parseRefinementPreview({ preview_token: "refine-token", expires_in_seconds: 300, campaign: { id: "campaign", name: "Campaign", git_commit: "a".repeat(40), s0_values: [1.3] }, from_stage: "screen", to_stage: "refine", bounds: { detuning_gamma: { low: -2, high: -0.5 }, magnet_radius_m: { low: 0.04, high: 0.06 } }, screening: { job_id: "2[].zeus-master", completed_trials: 51, expected_trials: 51, candidates }, artifacts: { create: MOT_2D_SPECIFICATION_V1.stages.refine.artifacts.slice(0, 7), update: [MOT_2D_SPECIFICATION_V1.stages.refine.artifacts[7]] }, effects: { prepare_refinement: true, submit_refinement: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } });
const refinementResult = parseRefinementResult({ status: "refinement_prepared", campaign_id: "campaign", stage: "refine", artifacts: { created: 7, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } });

function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function services(overrides: Record<string, unknown> = {}) {
  return { submissionApi: { preview: vi.fn().mockResolvedValue(screeningSubmissionPreview), confirm: vi.fn().mockResolvedValue(screeningSubmissionResult), ...(overrides.submissionApi as object) }, lifecycleApi: { status: vi.fn().mockResolvedValue(ready), preview: vi.fn().mockResolvedValue(refinementPreview), confirm: vi.fn().mockResolvedValue(refinementResult), ...(overrides.lifecycleApi as object) } };
}
const props = (api = services()) => ({ campaignId: "campaign", snapshot, smokeLifecycle: smokePrepared, smokeEvidenceFresh: true, ...api });

describe("useScreeningController", () => {
  it("submits only from fresh Smoke evidence and confirms the exact reviewed token", async () => {
    const api = services();
    const { result, rerender } = renderHook((value) => useScreeningController(value), { initialProps: { ...props(api), smokeEvidenceFresh: false } });
    await act(() => result.current.submission.previewSubmission()); expect(api.submissionApi.preview).not.toHaveBeenCalled();
    rerender(props(api)); await act(() => result.current.submission.previewSubmission()); await act(() => result.current.submission.confirmSubmission());
    expect(api.submissionApi.preview).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(api.submissionApi.confirm).toHaveBeenCalledWith("submission-token");
    expect(result.current.submission.result).toBe(screeningSubmissionResult);
  });

  it.each([
    ["confirmation_expired", "error"], ["screening_submission_outcome_unknown", "unknown"], ["screening_already_started", "terminal"], ["unexpected_private_code", "terminal"],
  ])("fails safely for Screening submission code %s", async (code, state) => {
    const api = services({ submissionApi: { confirm: vi.fn().mockRejectedValue(new ScreeningSubmissionApiError(code, "stopped")) } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.submission.previewSubmission()); await act(() => result.current.submission.confirmSubmission()); await act(() => result.current.submission.confirmSubmission());
    expect(result.current.submission.state).toBe(state); expect(result.current.submission.preview).toBeNull(); expect(api.submissionApi.confirm).toHaveBeenCalledOnce();
  });

  it.each(["screening_submission_busy", "zeus_timeout", "zeus_unreachable"])("requires a fresh review after known recoverable Screening error %s", async (code) => {
    const confirm = vi.fn().mockRejectedValue(new ScreeningSubmissionApiError(code, "try again"));
    const api = services({ submissionApi: { confirm } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.submission.previewSubmission()); await act(() => result.current.submission.confirmSubmission()); await act(() => result.current.submission.confirmSubmission());
    expect(result.current.submission.state).toBe("error"); expect(result.current.submission.preview).toBeNull(); expect(confirm).toHaveBeenCalledOnce();
  });

  it("retires a reviewed submission when its upstream evidence changes", async () => {
    const api = services();
    const { result, rerender } = renderHook((value) => useScreeningController(value), { initialProps: props(api) });
    await act(() => result.current.submission.previewSubmission());
    rerender({ ...props(api), smokeEvidenceFresh: false });
    await act(() => result.current.submission.confirmSubmission());
    expect(result.current.submission.preview).toBeNull(); expect(api.submissionApi.confirm).not.toHaveBeenCalled();
  });

  it("cannot resurrect a pending submission preview after upstream evidence changes away and back", async () => {
    const pending = deferred<any>(); const api = services({ submissionApi: { preview: vi.fn(() => pending.promise) } });
    const { result, rerender } = renderHook((value) => useScreeningController(value), { initialProps: props(api) });
    let request!: Promise<void>; act(() => { request = result.current.submission.previewSubmission(); });
    rerender({ ...props(api), smokeEvidenceFresh: false });
    rerender(props(api));
    pending.resolve(screeningSubmissionPreview); await act(() => request);
    expect(result.current.submission.state).toBe("idle"); expect(result.current.submission.preview).toBeNull();
    await act(() => result.current.submission.confirmSubmission()); expect(api.submissionApi.confirm).not.toHaveBeenCalled();
  });

  it("ignores a stale pending preview error after upstream evidence changes away and back", async () => {
    const pending = deferred<any>(); const api = services({ submissionApi: { preview: vi.fn(() => pending.promise) } });
    const { result, rerender } = renderHook((value) => useScreeningController(value), { initialProps: props(api) });
    let request!: Promise<void>; act(() => { request = result.current.submission.previewSubmission(); });
    rerender({ ...props(api), smokeEvidenceFresh: false }); rerender(props(api));
    pending.reject(new ScreeningSubmissionApiError("unexpected_private_code", "stale failure")); await act(() => request);
    expect(result.current.submission.state).toBe("idle"); expect(result.current.submission.error).toBe(""); expect(result.current.submission.preview).toBeNull();
  });

  it("retires a consumed submission review when upstream evidence changes during a failed confirm", async () => {
    const pending = deferred<any>(); const api = services({ submissionApi: { confirm: vi.fn(() => pending.promise) } });
    const { result, rerender } = renderHook((value) => useScreeningController(value), { initialProps: props(api) });
    await act(() => result.current.submission.previewSubmission()); let request!: Promise<void>; act(() => { request = result.current.submission.confirmSubmission(); });
    rerender({ ...props(api), smokeEvidenceFresh: false });
    pending.reject(new ScreeningSubmissionApiError("screening_submission_busy", "try again"));
    await act(() => request);
    expect(result.current.submission.preview).toBeNull(); expect(result.current.submission.state).toBe("error");
  });

  it("loads authoritative lifecycle and clears it after a failed refresh", async () => {
    const api = services(); const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); expect(result.current.lifecycle.value).toBe(ready);
    api.lifecycleApi.status.mockRejectedValueOnce(new Error("offline")); await act(() => result.current.lifecycle.refresh());
    expect(result.current.lifecycle.value).toBeNull(); expect(result.current.lifecycle.check).toBe("error");
  });

  it("prepares Refinement with the exact token and protects success from a late status", async () => {
    const pending = deferred<any>(); const api = services(); const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation());
    api.lifecycleApi.status.mockImplementationOnce(() => pending.promise);
    let refresh!: Promise<void>; act(() => { refresh = result.current.lifecycle.refresh(); });
    expect(api.lifecycleApi.confirm).not.toHaveBeenCalled();
    pending.resolve(ready); await act(() => refresh);
    await act(() => result.current.refinementPreparation.previewPreparation()); await act(() => result.current.refinementPreparation.confirmPreparation());
    expect(api.lifecycleApi.confirm).toHaveBeenCalledWith("refine-token"); expect(result.current.lifecycle.value?.lifecycle).toBe("refinement_prepared");
  });

  it("blocks same-tick Refinement confirmation while a newer lifecycle refresh owns evidence", async () => {
    const pending = deferred<any>(); const api = services(); const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation());
    api.lifecycleApi.status.mockImplementationOnce(() => pending.promise);
    let refresh!: Promise<void>; act(() => { refresh = result.current.lifecycle.refresh(); void result.current.refinementPreparation.confirmPreparation(); });
    expect(api.lifecycleApi.confirm).not.toHaveBeenCalled(); pending.resolve(ready); await act(() => refresh);
    expect(result.current.refinementPreparation.preview).toBeNull();
  });

  it.each(["transition_busy", "zeus_timeout", "scheduler_unavailable"])("keeps reviewed Refinement after known retryable %s", async (code) => {
    const api = services({ lifecycleApi: { confirm: vi.fn().mockRejectedValue(new ScreeningLifecycleApiError(code, "retry")) } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation()); await act(() => result.current.refinementPreparation.confirmPreparation());
    expect(result.current.refinementPreparation.state).toBe("review"); expect(result.current.refinementPreparation.preview).toBe(refinementPreview);
  });

  it("fails closed after an unverified local Refinement confirmation error", async () => {
    const api = services({ lifecycleApi: { confirm: vi.fn().mockRejectedValue(new Error("malformed response")) } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation()); await act(() => result.current.refinementPreparation.confirmPreparation()); await act(() => result.current.refinementPreparation.confirmPreparation());
    expect(result.current.refinementPreparation.state).toBe("terminal"); expect(result.current.refinementPreparation.preview).toBeNull(); expect(api.lifecycleApi.confirm).toHaveBeenCalledOnce();
  });

  it("recovers an already-prepared transition from authoritative status", async () => {
    const status = vi.fn().mockResolvedValueOnce(ready).mockResolvedValueOnce(prepared);
    const api = services({ lifecycleApi: { status, preview: vi.fn().mockRejectedValue(new ScreeningLifecycleApiError("refinement_already_prepared", "prepared")) } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation());
    expect(result.current.lifecycle.value).toBe(prepared); expect(status).toHaveBeenCalledTimes(2);
  });

  it("serializes confirms and ignores reset while mutations are unresolved", async () => {
    const submit = deferred<any>(); const prepare = deferred<any>();
    const api = services({ submissionApi: { confirm: vi.fn(() => submit.promise) }, lifecycleApi: { confirm: vi.fn(() => prepare.promise) } });
    const { result } = renderHook(() => useScreeningController(props(api)));
    await act(() => result.current.submission.previewSubmission()); let first!: Promise<void>; act(() => { first = result.current.submission.confirmSubmission(); void result.current.submission.confirmSubmission(); result.current.submission.reset(); });
    expect(api.submissionApi.confirm).toHaveBeenCalledOnce(); expect(result.current.submission.state).toBe("submitting"); submit.resolve(screeningSubmissionResult); await act(() => first);
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation()); let second!: Promise<void>; act(() => { second = result.current.refinementPreparation.confirmPreparation(); void result.current.refinementPreparation.confirmPreparation(); result.current.refinementPreparation.reset(); });
    expect(api.lifecycleApi.confirm).toHaveBeenCalledOnce(); expect(result.current.refinementPreparation.state).toBe("preparing"); prepare.resolve(refinementResult); await act(() => second);
  });

  it.each(["campaign", "profile", "submissionApi", "lifecycleApi", "unmount"] as const)("retires late work after %s identity change", async (boundary) => {
    const pending = deferred<any>(); const first = services({ lifecycleApi: { confirm: vi.fn(() => pending.promise) } }); const second = services();
    const { result, rerender, unmount } = renderHook((value: any) => useScreeningController(value), { initialProps: props(first) });
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.refinementPreparation.previewPreparation()); let request!: Promise<void>; act(() => { request = result.current.refinementPreparation.confirmPreparation(); });
    if (boundary === "campaign") rerender({ ...props(first), campaignId: "other" });
    else if (boundary === "profile") rerender({ ...props(first), snapshot: { ...snapshot, profile: { ...snapshot.profile, username: "other" } } });
    else if (boundary === "submissionApi") rerender({ ...props(first), submissionApi: second.submissionApi });
    else if (boundary === "lifecycleApi") rerender({ ...props(first), lifecycleApi: second.lifecycleApi });
    else unmount();
    pending.resolve(refinementResult); await act(() => request);
    if (boundary !== "unmount") { expect(result.current.refinementPreparation.state).toBe("idle"); expect(result.current.refinementPreparation.result).toBeNull(); }
  });
});

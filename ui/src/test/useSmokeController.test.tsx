import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SmokeLifecycleApiError, SubmissionApiError } from "../api/clients/smoke";
import type { ZeusSnapshot } from "../api/clients/zeus";
import { parseScreeningPreview, parseScreeningResult, parseSmokeLifecycle, parseSmokeSubmissionPreview, parseSmokeSubmissionResult } from "../api/schema/domain";
import { MOT_2D_SPECIFICATION_V1 } from "../generated/mot2dSpec.v1";
import { useSmokeController } from "../features/campaign/controllers/useSmokeController";

const snapshot = { profile: { host: "zeus.technion.ac.il", username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" } } as ZeusSnapshot;
const point = { s0: 1.3, captured: 1, input: 2, efficiency: 0.5 };
const submissionPreview = parseSmokeSubmissionPreview({ preview_token: "submit-token", expires_in_seconds: 300, campaign: { id: "campaign", name: "Campaign", path: "data/optimization/mot_2d/campaign", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "smoke", label: MOT_2D_SPECIFICATION_V1.stages.smoke.label, purpose: "Validate execution." }, job: { file: MOT_2D_SPECIFICATION_V1.stages.smoke.job_file, kind: "job", task_count: 1, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 }, remote: { host: "zeus.technion.ac.il", project_directory: snapshot.profile.project_directory, commit: "a".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true });
const submissionResult = parseSmokeSubmissionResult({ status: "submitted", campaign_id: "campaign", stage: "smoke", job_id: "1.zeus-master", submitted_at: "2026-10-10T10:00:00Z", later_stages_locked: true });
const ready = parseSmokeLifecycle({ source: "zeus", queried_at: "2026-10-10T10:05:00Z", campaign: { id: "campaign", name: "Campaign", stage: "smoke" }, submission: { job_id: "1.zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 }, validation: { status: "valid", points: [point], artifact_count: 3 }, lifecycle: "ready_to_prepare_screen", next_action: "review_screening_preparation" });
const prepared = parseSmokeLifecycle({ ...ready, queried_at: "2026-10-10T10:06:00Z", campaign: { ...ready.campaign, stage: "screen" }, lifecycle: "screen_prepared", next_action: "none" });
const screeningPreview = parseScreeningPreview({ preview_token: "screen-token", expires_in_seconds: 300, campaign: { id: "campaign", name: "Campaign", git_commit: "a".repeat(40) }, from_stage: "smoke", to_stage: "screen", smoke: { job_id: "1.zeus-master", points: [point], artifact_count: 3 }, artifacts: { create: ["screen/tasks.json", "jobs/02_screen.pbs"], update: ["campaign.json"] }, effects: { prepare_screening: true, submit_screening: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } });
const screeningResult = parseScreeningResult({ status: "screening_prepared", campaign_id: "campaign", stage: "screen", artifacts: { created: 2, updated: 1 }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "not_synchronized" } });

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; }
function api(overrides: Record<string, unknown> = {}) {
  return { submissionApi: { preview: vi.fn().mockResolvedValue(submissionPreview), confirm: vi.fn().mockResolvedValue(submissionResult), ...(overrides.submissionApi as object) }, lifecycleApi: { status: vi.fn().mockResolvedValue(ready), preview: vi.fn().mockResolvedValue(screeningPreview), confirm: vi.fn().mockResolvedValue(screeningResult), ...(overrides.lifecycleApi as object) } };
}

describe("useSmokeController", () => {
  it("submits only the exact reviewed smoke token", async () => {
    const services = api();
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.submission.previewSubmission());
    await act(() => result.current.submission.confirmSubmission());
    expect(services.submissionApi.preview).toHaveBeenCalledWith("campaign", snapshot.profile);
    expect(services.submissionApi.confirm).toHaveBeenCalledWith("submit-token");
    expect(result.current.submission.state).toBe("submitted");
    expect(result.current.submission.result).toBe(submissionResult);
  });

  it.each([
    ["submission_outcome_unknown", "unknown", "Submission outcome could not be verified"],
    ["already_submitted", "terminal", "durable Zeus submission record"],
    ["smoke_already_started", "terminal", "Smoke outputs already exist"],
    ["submission_record_invalid", "terminal", "server message"],
    ["unexpected_private_code", "terminal", "server message"],
  ])("fails closed for smoke submission code %s", async (code, state, message) => {
    const services = api({ submissionApi: { confirm: vi.fn().mockRejectedValue(new SubmissionApiError(code, "server message")) } });
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.submission.previewSubmission()); await act(() => result.current.submission.confirmSubmission());
    expect(result.current.submission.state).toBe(state);
    expect(result.current.submission.error).toContain(message);
  });

  it("uses only a successful current status as fresh evidence", async () => {
    const services = api();
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh());
    expect(result.current.lifecycle.value).toBe(ready);
    expect(result.current.lifecycle.evidenceFresh).toBe(true);
    services.lifecycleApi.status.mockRejectedValueOnce(new Error("unavailable"));
    await act(() => result.current.lifecycle.refresh());
    expect(result.current.lifecycle.value).toBeNull();
    expect(result.current.lifecycle.evidenceFresh).toBe(false);
    expect(result.current.lifecycle.check).toBe("error");
  });

  it("prepares Screening with the reviewed token and marks synthetic evidence stale", async () => {
    const services = api();
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh());
    await act(() => result.current.screeningPreparation.previewPreparation());
    await act(() => result.current.screeningPreparation.confirmPreparation());
    expect(services.lifecycleApi.confirm).toHaveBeenCalledWith("screen-token");
    expect(result.current.screeningPreparation.state).toBe("success");
    expect(result.current.lifecycle.value?.lifecycle).toBe("screen_prepared");
    expect(result.current.lifecycle.evidenceFresh).toBe(false);
  });

  it("recovers an already-prepared transition from authoritative status", async () => {
    const status = vi.fn().mockResolvedValueOnce(ready).mockResolvedValueOnce(prepared);
    const services = api({ lifecycleApi: { status, preview: vi.fn().mockRejectedValue(new SmokeLifecycleApiError("screening_already_prepared", "Already prepared")) } });
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    expect(status).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycle.value).toBe(prepared);
    expect(result.current.screeningPreparation.state).toBe("idle");
  });

  it("serializes submission and preparation mutations", async () => {
    const smoke = deferred<any>(), screen = deferred<any>();
    const services = api({ submissionApi: { confirm: vi.fn(() => smoke.promise) }, lifecycleApi: { confirm: vi.fn(() => screen.promise) } });
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.submission.previewSubmission());
    let smokeRequest!: Promise<void>; act(() => { smokeRequest = result.current.submission.confirmSubmission(); void result.current.submission.confirmSubmission(); result.current.submission.reset(); });
    expect(services.submissionApi.confirm).toHaveBeenCalledOnce(); expect(result.current.submission.state).toBe("submitting");
    smoke.resolve(submissionResult); await act(() => smokeRequest);
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    let screenRequest!: Promise<void>; act(() => { screenRequest = result.current.screeningPreparation.confirmPreparation(); void result.current.screeningPreparation.confirmPreparation(); result.current.screeningPreparation.reset(); });
    expect(services.lifecycleApi.confirm).toHaveBeenCalledOnce(); expect(result.current.screeningPreparation.state).toBe("preparing");
    screen.resolve(screeningResult); await act(() => screenRequest);
  });

  it("retires a reviewed preparation when authoritative lifecycle evidence is refreshed", async () => {
    const services = api();
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh());
    await act(() => result.current.screeningPreparation.previewPreparation());
    expect(result.current.screeningPreparation.state).toBe("review");
    await act(() => result.current.lifecycle.refresh());
    expect(result.current.screeningPreparation.preview).toBeNull();
    expect(result.current.screeningPreparation.state).toBe("idle");
  });

  it("fails closed when Screening confirmation returns an unverified local error", async () => {
    const confirm = vi.fn().mockRejectedValue(new Error("Malformed response after invocation"));
    const services = api({ lifecycleApi: { confirm } });
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    await act(() => result.current.screeningPreparation.confirmPreparation());
    await act(() => result.current.screeningPreparation.confirmPreparation());
    expect(confirm).toHaveBeenCalledOnce();
    expect(result.current.screeningPreparation.state).toBe("terminal");
    expect(result.current.screeningPreparation.preview).toBeNull();
  });

  it.each(["transition_busy", "zeus_timeout", "scheduler_unavailable"])("keeps the reviewed Screening token after known retryable %s", async (code) => {
    const confirm = vi.fn().mockRejectedValue(new SmokeLifecycleApiError(code, "Try again"));
    const services = api({ lifecycleApi: { confirm } });
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    await act(() => result.current.screeningPreparation.confirmPreparation());
    expect(result.current.screeningPreparation.state).toBe("review");
    expect(result.current.screeningPreparation.preview).toBe(screeningPreview);
  });

  it("does not confirm a reviewed transition while a newer lifecycle refresh owns the evidence", async () => {
    const pending = deferred<any>();
    const services = api();
    const { result } = renderHook(() => useSmokeController({ campaignId: "campaign", snapshot, ...services }));
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    services.lifecycleApi.status.mockImplementationOnce(() => pending.promise);
    let refresh!: Promise<void>;
    act(() => { refresh = result.current.lifecycle.refresh(); void result.current.screeningPreparation.confirmPreparation(); });
    expect(services.lifecycleApi.confirm).not.toHaveBeenCalled();
    pending.resolve(ready); await act(() => refresh);
    expect(result.current.screeningPreparation.preview).toBeNull();
    expect(result.current.screeningPreparation.state).toBe("idle");
  });

  it.each(["campaign", "profile", "api", "unmount"] as const)("retires a late smoke confirmation after %s change", async (boundary) => {
    const pending = deferred<any>(); const first = api({ submissionApi: { confirm: vi.fn(() => pending.promise) } }); const second = api();
    const { result, rerender, unmount } = renderHook(({ campaignId, value, services }: any) => useSmokeController({ campaignId, snapshot: value, ...services }), { initialProps: { campaignId: "campaign", value: snapshot, services: first } });
    await act(() => result.current.submission.previewSubmission()); let request!: Promise<void>; act(() => { request = result.current.submission.confirmSubmission(); });
    if (boundary === "campaign") rerender({ campaignId: "other", value: snapshot, services: first });
    else if (boundary === "profile") rerender({ campaignId: "campaign", value: { ...snapshot, profile: { ...snapshot.profile, username: "other" } }, services: first });
    else if (boundary === "api") rerender({ campaignId: "campaign", value: snapshot, services: second });
    else unmount();
    pending.resolve(submissionResult); await act(() => request);
    if (boundary !== "unmount") { expect(result.current.submission.state).toBe("idle"); expect(result.current.submission.result).toBeNull(); }
  });

  it.each(["campaign", "profile", "api", "unmount"] as const)("retires a late Screening confirmation after %s change", async (boundary) => {
    const pending = deferred<any>(); const first = api({ lifecycleApi: { confirm: vi.fn(() => pending.promise) } }); const second = api();
    const { result, rerender, unmount } = renderHook(({ campaignId, value, services }: any) => useSmokeController({ campaignId, snapshot: value, ...services }), { initialProps: { campaignId: "campaign", value: snapshot, services: first } });
    await act(() => result.current.lifecycle.refresh()); await act(() => result.current.screeningPreparation.previewPreparation());
    let request!: Promise<void>; act(() => { request = result.current.screeningPreparation.confirmPreparation(); });
    if (boundary === "campaign") rerender({ campaignId: "other", value: snapshot, services: first });
    else if (boundary === "profile") rerender({ campaignId: "campaign", value: { ...snapshot, profile: { ...snapshot.profile, username: "other" } }, services: first });
    else if (boundary === "api") rerender({ campaignId: "campaign", value: snapshot, services: second });
    else unmount();
    pending.resolve(screeningResult); await act(() => request);
    if (boundary !== "unmount") { expect(result.current.screeningPreparation.state).toBe("idle"); expect(result.current.screeningPreparation.result).toBeNull(); }
  });
});

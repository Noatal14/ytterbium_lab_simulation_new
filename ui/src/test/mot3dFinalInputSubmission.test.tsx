import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import { Mot3DFinalInputSubmissionApiError, parseMot3DFinalInputPreview, parseMot3DFinalInputResult, parseMot3DFinalInputStatus } from "../api/clients/mot3dFinalInputSubmission";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DFinalInputSubmissionController } from "../features/campaign/controllers/useMot3DFinalInputSubmissionController";

const data = (id: string) => structuredClone((successSnapshot.cases.find((entry) => entry.id === id)?.body as { data: Record<string, unknown> }).data);
const campaignId = "mot3d-campaign", commit = "a".repeat(40);
const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
const snapshot = { connection_status: "connected" as const, profile, remote: { project_directory: profile.project_directory, git_commit: commit, branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-12T00:00:00Z", jobs: [] } };
const status = () => parseMot3DFinalInputStatus(data("mot3d-final-input-status"));
const preview = () => parseMot3DFinalInputPreview(data("mot3d-final-input-preview"), { campaignId, commit });
const result = () => parseMot3DFinalInputResult(data("mot3d-final-input-confirm"), campaignId);
const base = { stage: "final_validation_input_generation", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const flow = (overrides: Record<string, unknown> = {}) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...overrides }) as never;

describe("3D final-validation input generation submission", () => {
  it("strictly rejects altered chain, science, effects, and result contracts", () => {
    expect(preview().science.zeeman_seeds).toEqual(Array.from({ length: 20 }, (_, i) => 3035 + i));
    const mutations: Array<(value: Record<string, unknown>) => void> = [
      (v) => { ((v.chain as { steps: Array<Record<string, unknown>> }).steps[0]).tasks = 19; },
      (v) => { ((v.science as { zeeman_seeds: number[] }).zeeman_seeds)[0] = 3034; },
      (v) => { (v.science as Record<string, unknown>).npools = 199; },
      (v) => { (v.effects as Record<string, unknown>).start_final_validation = true; },
      (v) => { (v as Record<string, unknown>).unexpected = true; },
      (v) => { v.preview_token = 42; },
      (v) => { v.preview_token = "bad token"; },
      (v) => { (v.campaign as Record<string, unknown>).name = ""; },
      (v) => { (v.campaign as Record<string, unknown>).git_commit = "z".repeat(40); },
    ];
    for (const mutate of mutations) { const value = data("mot3d-final-input-preview"); mutate(value); expect(() => parseMot3DFinalInputPreview(value, { campaignId, commit })).toThrow(); }
    const badStatus = data("mot3d-final-input-status"); ((badStatus.chain as { jobs: Array<Record<string, unknown>> }).jobs[1]).job_id = "902[].zeus-master";
    expect(() => parseMot3DFinalInputStatus(badStatus)).toThrow();
    for (const [key, value] of [["queried_at", 42], ["queried_at", "not-a-date"]] as const) { const malformed = data("mot3d-final-input-status"); malformed[key] = value; expect(() => parseMot3DFinalInputStatus(malformed)).toThrow(); }
    for (const [key, value] of [["id", 42], ["name", ""]] as const) { const malformed = data("mot3d-final-input-status"); (malformed.campaign as Record<string, unknown>)[key] = value; expect(() => parseMot3DFinalInputStatus(malformed)).toThrow(); }
    const lifecycleType = data("mot3d-final-input-status"); (lifecycleType.chain as Record<string, unknown>).status = { toString: () => "eligible" }; expect(() => parseMot3DFinalInputStatus(lifecycleType)).toThrow();
    const badResult = data("mot3d-final-input-confirm"); badResult.final_validation_started = true;
    expect(() => parseMot3DFinalInputResult(badResult, campaignId)).toThrow();
    const badReceipt = data("mot3d-final-input-preview"); (badReceipt.local_sync as Record<string, unknown>).receipt_sha256 = "x".repeat(64); expect(() => parseMot3DFinalInputPreview(badReceipt, { campaignId, commit })).toThrow();
    const badJob = data("mot3d-final-input-confirm"); ((badJob.chain as { jobs: Array<Record<string, unknown>> }).jobs[2]).job_id = "903[].zeus-master"; expect(() => parseMot3DFinalInputResult(badJob, campaignId)).toThrow();
    const extraResult = data("mot3d-final-input-confirm"); extraResult.unexpected = true; expect(() => parseMot3DFinalInputResult(extraResult, campaignId)).toThrow();
  });

  it.each(["host", "authentication", "username", "project", "commit", "campaign", "enabled", "api", "unmount"])("suppresses deferred status after %s changes", async (change) => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const makeApi = () => ({ status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() }); const initialApi = makeApi();
    const hook = renderHook(({ currentSnapshot, currentCampaign, enabled, api }) => useMot3DFinalInputSubmissionController({ campaignId: currentCampaign, snapshot: currentSnapshot, enabled, api: api as never }), { initialProps: { currentSnapshot: snapshot, currentCampaign: campaignId, enabled: true, api: initialApi } });
    act(() => { void hook.result.current.refresh(); });
    if (change === "unmount") hook.unmount(); else hook.rerender({ currentSnapshot: (change === "host" ? { ...snapshot, profile: { ...profile, host: "other" } } : change === "authentication" ? { ...snapshot, profile: { ...profile, authentication: "other" } } : change === "username" ? { ...snapshot, profile: { ...profile, username: "other" } } : change === "project" ? { ...snapshot, profile: { ...profile, project_directory: "/other" } } : change === "commit" ? { ...snapshot, remote: { ...snapshot.remote, git_commit: "b".repeat(40) } } : snapshot) as typeof snapshot, currentCampaign: change === "campaign" ? "other" : campaignId, enabled: change === "enabled" ? false : true, api: change === "api" ? makeApi() : initialApi });
    await act(async () => resolve(status())); if (change !== "unmount") expect(hook.result.current.status).toBeNull();
  });

  it("deduplicates and consumes an ambiguous confirmation", async () => {
    const api = { status: vi.fn(async () => status()), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DFinalInputSubmissionApiError("final_input_submission_outcome_unknown", "Unknown"); }), reset: vi.fn() };
    const hook = renderHook(() => useMot3DFinalInputSubmissionController({ campaignId, snapshot, enabled: true, api }));
    await act(async () => hook.result.current.refresh()); await act(async () => hook.result.current.review()); await act(async () => { void hook.result.current.confirm(); void hook.result.current.confirm(); });
    expect(api.confirm).toHaveBeenCalledOnce(); expect(hook.result.current.errorPhase).toBe("confirm_unknown"); await act(async () => hook.result.current.confirm()); expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("renders the exact nontechnical chain and truthful completion", () => {
    const view = render(<Mot3DCampaignFlow {...base} finalInputSubmission={flow({ phase: "review", status: status(), preview: preview() })} />);
    expect(screen.getByRole("heading", { name: "Submit final-validation input generation" })).toHaveFocus(); expect(screen.getByText(/20 new ensembles/)).toBeVisible(); expect(screen.getByText(/seeds 43035–43054/)).toBeVisible(); expect(screen.getAllByText("Not submitted")).toHaveLength(2);
    const done = status(); done.chain.status = "completed_success_unvalidated"; done.next_action = "validate_generated_inputs"; done.scheduler.completed_array_tasks = 40; done.scheduler.completed_scalar_jobs = 1; done.chain.jobs = result().chain.jobs;
    view.rerender(<Mot3DCampaignFlow {...base} finalInputSubmission={flow({ phase: "idle", status: done })} />);
    expect(screen.getByText(/not independently verified or synchronized/)).toBeVisible(); expect(screen.getByText(/Final Validation and reporting have not started/)).toBeVisible(); expect(screen.getByText(/Input-generation jobs finished/).closest("div[tabindex='-1']")).toHaveFocus();
    view.rerender(<Mot3DCampaignFlow {...base} finalInputSubmission={flow({ phase: "success", status: status(), result: result() })} />);
    expect(screen.getByText("Input generation is running on Zeus").closest("div[tabindex='-1']")).toHaveFocus();
  });
});


it("renders TEST ONLY final-input reservations separately for all three jobs", () => {
  // Controlled review fixture only: this test never queries or submits to Zeus.
  const reviewed = preview();
  reviewed.science.npools = 10;
  const cores = [1, 10, 1];
  reviewed.chain.steps.forEach((step, index) => {
    step.resources = {ncpus: cores[index], memory_gb: 4, walltime: "01:00:00", vnode: "gd002"};
  });
  render(<Mot3DCampaignFlow {...base} finalInputSubmission={flow({phase: "review", status: status(), preview: reviewed})} />);
  expect(screen.getByText("20 new ensembles, seeds 3035–3054 · 1 CPUs · 4 GB · 01:00:00 · Node gd002")).toBeVisible();
  expect(screen.getByText("20 corresponding jobs, seeds 43035–43054 · 10 CPUs · 4 GB · 01:00:00 · Node gd002")).toBeVisible();
  expect(screen.getByText("One manifest job · 1 CPUs · 4 GB · 01:00:00 · Node gd002")).toBeVisible();
  expect(screen.getByText("10", {selector: "dd"})).toBeVisible();
  expect(screen.queryByText(/200 CPUs/)).not.toBeInTheDocument();
  expect(screen.getAllByText("Not submitted")).toHaveLength(2);
});

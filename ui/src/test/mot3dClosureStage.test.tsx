import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import successSnapshot from "./teamContractFixture";
import { Mot3DClosureSubmissionApiError, parseMot3DClosureSubmissionPreview, parseMot3DClosureSubmissionResult, parseMot3DClosureSubmissionStatus } from "../api/clients/mot3dClosureSubmission";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DClosureSubmissionController } from "../features/campaign/controllers/useMot3DClosureSubmissionController";

const data = (id: string) => structuredClone((successSnapshot.cases.find((entry) => entry.id === id)?.body as { data: Record<string, unknown> }).data);
const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_ui", authentication: "ssh-key-or-agent" as const };
const snapshot = { connection_status: "connected" as const, profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-12T00:00:00Z", jobs: [] } };
const status = () => parseMot3DClosureSubmissionStatus(data("mot3d-closure-status"));
const preview = () => parseMot3DClosureSubmissionPreview(data("mot3d-closure-preview"), { campaignId: "campaign-id", profile });
const result = () => parseMot3DClosureSubmissionResult(data("mot3d-closure-confirm"), "campaign-id");
const base = { stage: "closure", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const flow = (overrides: Record<string, unknown> = {}) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...overrides }) as never;

describe("3D Closure campaign stage", () => {
  it("uses guarded status, review, confirm, and suppresses duplicate actions", async () => {
    let resolveStatus!: (value: ReturnType<typeof status>) => void;
    const api = { status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolveStatus = done; })), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => result()), reset: vi.fn() };
    const hook = renderHook(() => useMot3DClosureSubmissionController({ campaignId: "campaign-id", snapshot, enabled: true, api }));
    act(() => { void hook.result.current.refresh(); void hook.result.current.refresh(); });
    expect(api.status).toHaveBeenCalledOnce();
    await act(async () => resolveStatus(status()));
    expect(hook.result.current.phase).toBe("ready");
    await act(async () => { void hook.result.current.review(); void hook.result.current.review(); });
    expect(api.preview).toHaveBeenCalledOnce();
    await act(async () => { void hook.result.current.confirm(); void hook.result.current.confirm(); });
    expect(api.confirm).toHaveBeenCalledOnce();
    expect(hook.result.current.phase).toBe("success");
  });

  it("suppresses a stale profile response", async () => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const api = { status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() };
    const hook = renderHook(({ current }) => useMot3DClosureSubmissionController({ campaignId: "campaign-id", snapshot: current, enabled: true, api: api as never }), { initialProps: { current: snapshot } });
    act(() => { void hook.result.current.refresh(); });
    hook.rerender({ current: { ...snapshot, profile: { ...profile, username: "changed" } } });
    await act(async () => resolve(status()));
    expect(hook.result.current.status).toBeNull();
  });

  it("blocks an ambiguous confirmation and never retries", async () => {
    const api = { status: vi.fn(async () => status()), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DClosureSubmissionApiError("closure_submission_outcome_unknown", "Unknown outcome"); }), reset: vi.fn() };
    const hook = renderHook(() => useMot3DClosureSubmissionController({ campaignId: "campaign-id", snapshot, enabled: true, api }));
    await act(async () => hook.result.current.refresh());
    await act(async () => hook.result.current.review());
    await act(async () => hook.result.current.confirm());
    expect(hook.result.current.phase).toBe("blocked");
    expect(hook.result.current.errorPhase).toBe("confirm_unknown");
    await act(async () => hook.result.current.confirm());
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("renders prepared review, running refresh, unvalidated completion, and manual recovery", async () => {
    const user = userEvent.setup(), onViewJobs = vi.fn();
    const view = render(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closure={flow({ phase: "ready", status: status() })} />);
    expect(screen.getByText(/Closure is prepared, but not submitted/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Review Closure jobs/ })).toBeEnabled();
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closure={flow({ phase: "review", status: status(), preview: preview() })} />);
    expect(await screen.findByRole("heading", { name: "Submit Closure" })).toHaveFocus();
    expect(screen.getByText(/Scientific validation/)).toBeVisible();
    const running = { ...status(), submission: { ...status().submission, status: "running" as const, chain: result().chain }, scheduler: { ...status().scheduler, completed_array_tasks: 2 }, next_action: "wait" as const };
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closure={flow({ status: running })} />);
    expect(screen.getByText(/No action is needed/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open Zeus jobs" }));
    expect(onViewJobs).toHaveBeenCalledOnce();
    const completed = { ...running, submission: { ...running.submission, status: "completed_success_unvalidated" as const }, scheduler: { ...running.scheduler, completed_array_tasks: 6, completed_merge_jobs: 2 }, next_action: "await_result_synchronization" as const };
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closure={flow({ status: completed })} />);
    expect(screen.getByText(/not been validated or synchronized/)).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closure={flow({ phase: "blocked", error: "Outcome unknown", errorPhase: "confirm_unknown" })} />);
    expect(screen.getByText(/Do not retry/)).toBeVisible();
  });

  it("keeps status failures recoverable through explicit refresh", async () => {
    const refresh = vi.fn();
    render(<Mot3DCampaignFlow {...base} closure={flow({ error: "Zeus could not be reached", errorPhase: "status", refresh })} />);
    await userEvent.click(screen.getByRole("button", { name: "Check Zeus status" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  });
});

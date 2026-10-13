import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import { Mot3DClosureTransitionApiError, parseMot3DClosureTransitionPreview, parseMot3DClosureTransitionResult, parseMot3DClosureTransitionStatus } from "../api/clients/mot3dClosureTransition";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DClosureTransitionController } from "../features/campaign/controllers/useMot3DClosureTransitionController";

const data = (id: string) => structuredClone((successSnapshot.cases.find((entry) => entry.id === id)?.body as { data: Record<string, unknown> }).data);
const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
const snapshot = { connection_status: "connected" as const, profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-12T00:00:00Z", jobs: [] } };
const status = () => parseMot3DClosureTransitionStatus(data("mot3d-closure-transition-status"));
const preview = () => parseMot3DClosureTransitionPreview(data("mot3d-closure-transition-preview"), "campaign-id");
const result = () => parseMot3DClosureTransitionResult(data("mot3d-closure-transition-confirm"), "campaign-id");
const base = { stage: "closure", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const flow = (overrides: Record<string, unknown> = {}) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...overrides }) as never;

describe("3D Closure transition", () => {
  it("strictly decodes status, review, and result mutations", () => {
    expect(status().next_action).toBe("review_transition");
    expect(preview().effects.submit_finalists).toBe(false);
    expect(result().submitted_to_zeus).toBe(false);
    const changed = data("mot3d-closure-transition-preview");
    (changed.effects as Record<string, unknown>).submit_finalists = true;
    expect(() => parseMot3DClosureTransitionPreview(changed, "campaign-id")).toThrow();
    const extra = data("mot3d-closure-transition-status");
    (extra as Record<string, unknown>).unexpected = true;
    expect(() => parseMot3DClosureTransitionStatus(extra)).toThrow();
    const malformed = data("mot3d-closure-transition-confirm");
    (malformed.artifacts as Record<string, unknown>).synchronized = 200;
    expect(() => parseMot3DClosureTransitionResult(malformed, "campaign-id")).toThrow();
  });

  it.each([
    ["status stage", "status", (value: Record<string, unknown>) => { (value.campaign as Record<string, unknown>).stage = "refinement"; }],
    ["extra refinement key", "status", (value: Record<string, unknown>) => { value.refinement = value.closure; }],
    ["missing closure key", "status", (value: Record<string, unknown>) => { delete value.closure; }],
    ["preview from stage", "preview", (value: Record<string, unknown>) => { value.from_stage = "refinement"; }],
    ["preview to stage", "preview", (value: Record<string, unknown>) => { value.to_stage = "closure"; }],
    ["preview renamed effect", "preview", (value: Record<string, unknown>) => { (value.effects as Record<string, unknown>).prepare_closure = true; }],
    ["result status", "result", (value: Record<string, unknown>) => { value.status = "closure_prepared"; }],
    ["result stage", "result", (value: Record<string, unknown>) => { value.stage = "closure"; }],
  ])("rejects altered original %s", (_label, kind, mutate) => {
    const id = kind === "status" ? "mot3d-closure-transition-status" : kind === "preview" ? "mot3d-closure-transition-preview" : "mot3d-closure-transition-confirm";
    const value = data(id); mutate(value);
    expect(() => kind === "status" ? parseMot3DClosureTransitionStatus(value) : kind === "preview" ? parseMot3DClosureTransitionPreview(value, "campaign-id") : parseMot3DClosureTransitionResult(value, "campaign-id")).toThrow();
  });

  it("guards duplicate actions, stale profile responses, and ambiguous confirmation", async () => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const api = { status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DClosureTransitionApiError("closure_transition_outcome_unknown", "Unknown outcome"); }), reset: vi.fn() };
    const hook = renderHook(({ current }) => useMot3DClosureTransitionController({ campaignId: "campaign-id", snapshot: current, enabled: true, api }), { initialProps: { current: snapshot } });
    act(() => { void hook.result.current.refresh(); void hook.result.current.refresh(); });
    expect(api.status).toHaveBeenCalledOnce();
    hook.rerender({ current: { ...snapshot, profile: { ...profile, username: "changed" } } });
    await act(async () => resolve(status()));
    expect(hook.result.current.status).toBeNull();
  });

  it.each(["host", "authentication", "username", "project", "campaign", "enabled", "api", "unmount"])("suppresses a deferred response after %s context changes", async (change) => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const makeApi = () => ({ status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() });
    const initialApi = makeApi();
    const hook = renderHook(({ currentSnapshot, campaignId, enabled, api }) => useMot3DClosureTransitionController({ campaignId, snapshot: currentSnapshot, enabled, api: api as never }), { initialProps: { currentSnapshot: snapshot, campaignId: "campaign-id", enabled: true, api: initialApi } });
    act(() => { void hook.result.current.refresh(); });
    if (change === "unmount") hook.unmount();
    else hook.rerender({
      currentSnapshot: (change === "host" ? { ...snapshot, profile: { ...profile, host: "other-host" } } : change === "authentication" ? { ...snapshot, profile: { ...profile, authentication: "other-auth" } } : change === "username" ? { ...snapshot, profile: { ...profile, username: "changed" } } : change === "project" ? { ...snapshot, profile: { ...profile, project_directory: "/home/tal.noa/other" } } : snapshot) as typeof snapshot,
      campaignId: change === "campaign" ? "other-campaign" : "campaign-id",
      enabled: change === "enabled" ? false : true,
      api: change === "api" ? makeApi() : initialApi,
    });
    await act(async () => resolve(status()));
    if (change !== "unmount") expect(hook.result.current.status).toBeNull();
  });

  it("consumes an ambiguous confirmation and never retries", async () => {
    const api = { status: vi.fn(async () => status()), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DClosureTransitionApiError("closure_transition_outcome_unknown", "Unknown outcome"); }), reset: vi.fn() };
    const hook = renderHook(() => useMot3DClosureTransitionController({ campaignId: "campaign-id", snapshot, enabled: true, api }));
    await act(async () => hook.result.current.refresh());
    await act(async () => hook.result.current.review());
    await act(async () => hook.result.current.confirm());
    expect(hook.result.current.phase).toBe("blocked");
    expect(hook.result.current.errorPhase).toBe("confirm_unknown");
    await act(async () => hook.result.current.confirm());
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("renders explicit no-submit review, recovery, invalid, and no-retry states", async () => {
    const user = userEvent.setup(), onViewJobs = vi.fn();
    const view = render(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closureTransition={flow({ phase: "ready", status: status() })} />);
    expect(screen.getByText(/All Closure artifacts are scientifically valid/)).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closureTransition={flow({ phase: "review", status: status(), preview: preview() })} />);
    expect(await screen.findByRole("heading", { name: /Synchronize Closure/ })).toHaveFocus();
    expect(screen.getByText(/No job or simulation starts/)).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closureTransition={flow({ phase: "success", result: result() })} />);
    expect(screen.getByText(/no final result is being claimed/)).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} onViewJobs={onViewJobs} closureTransition={flow({ phase: "blocked", error: "Outcome unknown", errorPhase: "confirm_unknown" })} />);
    expect(screen.getByText(/Do not retry/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open Zeus jobs" }));
    expect(onViewJobs).toHaveBeenCalledOnce();
  });
});

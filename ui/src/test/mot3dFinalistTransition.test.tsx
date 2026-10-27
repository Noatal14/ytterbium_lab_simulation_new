import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import successSnapshot from "../../../tests/contracts/v1/workflow_api_success.json";
import { createMot3DFinalistTransitionApi, Mot3DFinalistTransitionApiError, parseMot3DFinalistTransitionPreview, parseMot3DFinalistTransitionResult, parseMot3DFinalistTransitionStatus } from "../api/clients/mot3dFinalistTransition";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DFinalistTransitionController } from "../features/campaign/controllers/useMot3DFinalistTransitionController";

const data = (id: string) => structuredClone((successSnapshot.cases.find((entry) => entry.id === id)?.body as { data: Record<string, unknown> }).data);
const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
const snapshot = { connection_status: "connected" as const, profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-12T00:00:00Z", jobs: [] } };
const status = () => parseMot3DFinalistTransitionStatus(data("mot3d-finalist-transition-status"));
const preview = () => parseMot3DFinalistTransitionPreview(data("mot3d-finalist-transition-preview"), "campaign-id");
const result = () => parseMot3DFinalistTransitionResult(data("mot3d-finalist-transition-confirm"), "campaign-id");
const base = { stage: "finalist_selection", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const flow = (overrides: Record<string, unknown> = {}) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...overrides }) as never;

describe("3D Finalist Selection transition", () => {
  it("strictly rejects altered winner, stage, effect, and result contracts", () => {
    expect(preview().winner_selection.winners).toHaveLength(2);
    const mutations: Array<[string, (value: Record<string, unknown>) => void]> = [
      ["from", (v) => { v.from_stage = "closure"; }],
      ["rule", (v) => { (v.winner_selection as Record<string, unknown>).rule = "largest mean"; }],
      ["winner", (v) => { ((v.winner_selection as { winners: Array<Record<string, unknown>> }).winners[0]).candidate_id = "single_pass_finalist_01"; }],
      ["digest", (v) => { (v.winner_selection as Record<string, unknown>).evidence_sha256 = "c".repeat(64); }],
      ["submit", (v) => { (v.effects as Record<string, unknown>).submit_final_validation_inputs = true; }],
    ];
    for (const [, mutate] of mutations) { const value = data("mot3d-finalist-transition-preview"); mutate(value); expect(() => parseMot3DFinalistTransitionPreview(value, "campaign-id")).toThrow(); }
    const wrongStatus = data("mot3d-finalist-transition-status"); (wrongStatus.campaign as Record<string, unknown>).stage = "closure";
    expect(() => parseMot3DFinalistTransitionStatus(wrongStatus)).toThrow();
    for (const suffix of ["00", "04", "99"]) {
      const invalidCandidate = data("mot3d-finalist-transition-preview");
      ((invalidCandidate.winner_selection as { winners: Array<Record<string, unknown>> }).winners[0]).candidate_id = `angled_donut_finalist_${suffix}`;
      expect(() => parseMot3DFinalistTransitionPreview(invalidCandidate, "campaign-id")).toThrow();
    }
    const wrongResult = data("mot3d-finalist-transition-confirm"); wrongResult.stage = "finalist_selection";
    expect(() => parseMot3DFinalistTransitionResult(wrongResult, "campaign-id")).toThrow();
  });

  it.each(["result_artifacts", "expected_result_artifacts"])(
    "rejects Closure counts in original status %s", (field) => {
      const value = data("mot3d-finalist-transition-status");
      (value.validation as Record<string, unknown>)[field] = 200;
      expect(() => parseMot3DFinalistTransitionStatus(value)).toThrow();
    },
  );
  it.each(["result_files", "submission_receipts"])(
    "validates original preview synchronize.%s", (field) => {
      for (const invalid of [0, 200, "1", true, null]) {
        const value = data("mot3d-finalist-transition-preview");
        const artifacts = value.artifacts as Record<string, unknown>;
        (artifacts.synchronize as Record<string, unknown>)[field] = invalid;
        expect(() => parseMot3DFinalistTransitionPreview(value, "campaign-id")).toThrow();
      }
      const value = data("mot3d-finalist-transition-preview");
      (value.artifacts as Record<string, unknown>).synchronize = { result_files: 44 };
      expect(() => parseMot3DFinalistTransitionPreview(value, "campaign-id")).toThrow();
    },
  );
  it.each(["synchronized", "created"])(
    "validates original result artifacts.%s", (field) => {
      for (const invalid of [0, 201, 6, "4", true, null, undefined]) {
        const value = data("mot3d-finalist-transition-confirm");
        (value.artifacts as Record<string, unknown>)[field] = invalid;
        expect(() => parseMot3DFinalistTransitionResult(value, "campaign-id")).toThrow();
      }
    },
  );
  it("preserves valid DTOs without mutating the original replies", () => {
    for (const [id, parse] of [
      ["mot3d-finalist-transition-status", parseMot3DFinalistTransitionStatus],
      ["mot3d-finalist-transition-preview", (v: unknown) => parseMot3DFinalistTransitionPreview(v, "campaign-id")],
      ["mot3d-finalist-transition-confirm", (v: unknown) => parseMot3DFinalistTransitionResult(v, "campaign-id")],
    ] as const) {
      const original = data(id), before = structuredClone(original);
      expect(parse(original)).toEqual(before);
      expect(original).toEqual(before);
    }
  });
  it.each([
    ["running", "not_started", "wait"],
    ["held", "not_started", "inspect_zeus"],
    ["completed_failed", "not_started", "inspect_zeus"],
    ["completed_success_unvalidated", "not_started", "review_transition"],
    ["outcome_unknown", "valid", "inspect_zeus"],
    ["final_validation_input_generation_prepared", "valid", "synchronize_results"],
  ])("preserves the %s lifecycle contract", (lifecycle, validation, nextAction) => {
    const value = data("mot3d-finalist-transition-status");
    (value.finalist_selection as Record<string, unknown>).status = lifecycle;
    if (lifecycle === "running" || lifecycle === "held") {
      (value.scheduler as Record<string, unknown>).completed_array_tasks = 1;
      (value.scheduler as Record<string, unknown>).completed_merge_jobs = 0;
    }
    (value.validation as Record<string, unknown>).status = validation;
    (value.validation as Record<string, unknown>).result_artifacts = validation === "valid" ? 44 : 0;
    if (lifecycle === "final_validation_input_generation_prepared") {
      (value.transition as Record<string, unknown>).status = lifecycle;
    }
    value.next_action = nextAction;
    expect(parseMot3DFinalistTransitionStatus(value)).toEqual(value);
  });
  it("keeps a malformed confirm result uncertain and consumes its token", async () => {
    const invalid = data("mot3d-finalist-transition-confirm");
    (invalid.artifacts as Record<string, unknown>).created = 6;
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({ api_version: 1, data: data("mot3d-finalist-transition-preview") }))
      .mockResolvedValueOnce(Response.json({ api_version: 1, data: invalid }));
    try {
      const api = createMot3DFinalistTransitionApi(async () => "csrf");
      const reviewed = await api.preview("campaign-id", profile);
      await expect(api.confirm(reviewed.preview_token)).rejects.toMatchObject({ code: "finalist_transition_outcome_unknown" });
      await expect(api.confirm(reviewed.preview_token)).rejects.toThrow(/no longer active/);
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally { fetchMock.mockRestore(); }
  });
  it("does not restore a preview context when its response arrives after reset", async () => {
    let resolve!: (response: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockReturnValueOnce(new Promise<Response>((done) => { resolve = done; }));
    try {
      const api = createMot3DFinalistTransitionApi(async () => "csrf");
      const pending = api.preview("campaign-id", profile);
      const rejected = expect(pending).rejects.toThrow(/stale/);
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
      api.reset();
      resolve(Response.json({ api_version: 1, data: data("mot3d-finalist-transition-preview") }));
      await rejected;
      await expect(api.confirm("mot3d-finalist-transition-token")).rejects.toThrow(/no longer active/);
      expect(fetchMock).toHaveBeenCalledOnce();
    } finally { fetchMock.mockRestore(); }
  });
  it.each(["host", "authentication", "username", "project", "campaign", "enabled", "api", "unmount"])("suppresses deferred status after %s changes", async (change) => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const makeApi = () => ({ status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() });
    const initialApi = makeApi();
    const hook = renderHook(({ currentSnapshot, campaignId, enabled, api }) => useMot3DFinalistTransitionController({ campaignId, snapshot: currentSnapshot, enabled, api: api as never }), { initialProps: { currentSnapshot: snapshot, campaignId: "campaign-id", enabled: true, api: initialApi } });
    act(() => { void hook.result.current.refresh(); });
    if (change === "unmount") hook.unmount(); else hook.rerender({ currentSnapshot: (change === "host" ? { ...snapshot, profile: { ...profile, host: "other" } } : change === "authentication" ? { ...snapshot, profile: { ...profile, authentication: "other" } } : change === "username" ? { ...snapshot, profile: { ...profile, username: "other" } } : change === "project" ? { ...snapshot, profile: { ...profile, project_directory: "/other" } } : snapshot) as typeof snapshot, campaignId: change === "campaign" ? "other" : "campaign-id", enabled: change === "enabled" ? false : true, api: change === "api" ? makeApi() : initialApi });
    await act(async () => resolve(status()));
    if (change !== "unmount") expect(hook.result.current.status).toBeNull();
  });

  it("deduplicates and consumes an ambiguous confirmation", async () => {
    const api = { status: vi.fn(async () => status()), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DFinalistTransitionApiError("finalist_transition_outcome_unknown", "Unknown"); }), reset: vi.fn() };
    const hook = renderHook(() => useMot3DFinalistTransitionController({ campaignId: "campaign-id", snapshot, enabled: true, api }));
    await act(async () => hook.result.current.refresh()); await act(async () => hook.result.current.review());
    await act(async () => { void hook.result.current.confirm(); void hook.result.current.confirm(); });
    expect(api.confirm).toHaveBeenCalledOnce(); expect(hook.result.current.errorPhase).toBe("confirm_unknown");
    await act(async () => hook.result.current.confirm()); expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("renders winner evidence, zero-submit review, and prepared truth", () => {
    const view = render(<Mot3DCampaignFlow {...base} finalistTransition={flow({ phase: "review", status: status(), preview: preview() })} />);
    expect(screen.getByRole("heading", { name: /Lock winners/ })).toHaveFocus();
    expect(screen.getByText("angled_donut_finalist_01")).toBeVisible();
    expect(screen.getByText("single_pass_finalist_01")).toBeVisible();
    expect(screen.getByText("None")).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} finalistTransition={flow({ phase: "success", result: result() })} />);
    expect(screen.getByText(/This preparation synchronized the verified evidence and winner lock/)).toBeVisible();
    expect(screen.getByText(/Input generation and Final Validation have separate records/)).toBeVisible();
    expect(screen.queryByText(/final validation has not yet been performed/)).not.toBeInTheDocument();
  });
});

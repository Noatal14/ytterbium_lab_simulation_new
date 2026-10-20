import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createMot3DDiscoveryTransitionApi, parseMot3DDiscoveryTransitionPreview, parseMot3DDiscoveryTransitionResult, parseMot3DDiscoveryTransitionStatus } from "../api/clients/mot3dDiscoveryTransition";
import type { ZeusSnapshot } from "../api/schema/domain";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DDiscoveryTransitionController } from "../features/campaign/controllers/useMot3DDiscoveryTransitionController";

const campaignId = "campaign-id";
const profile = { host: "zeus.technion.ac.il" as const, username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new", authentication: "ssh-key-or-agent" as const };
const chain = { angled_donut: ["100[].zeus-master", "101[].zeus-master"], single_pass: ["200[].zeus-master", "201[].zeus-master", "202[].zeus-master"] };
const status = { source: "zeus", queried_at: "2026-10-12T10:00:00Z", campaign: { id: campaignId, name: "campaign", stage: "discovery" }, discovery: { status: "ready_to_advance", chain }, validation: { status: "valid", completed_trials: 950, expected_trials: 950 }, next_action: "review_transition", local_sync: { status: "not_synchronized", receipt_sha256: null } } as const;
const preview = { preview_token: "token", expires_in_seconds: 300, campaign: { id: campaignId, name: "campaign", git_commit: "a".repeat(40) }, from_stage: "discovery", to_stage: "preliminary_check", discovery: { completed_trials: 950, expected_trials: 950, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { trial_registries: 950, merged_files: 4 }, create: { selection_files: 2, job_files: 4 }, update: ["campaign.json"] }, effects: { synchronize_discovery: true, prepare_preliminary_check: true, submit_preliminary_check: false, start_simulation: false, overwrite_existing: false } } as const;
const result = { status: "preliminary_check_prepared", campaign_id: campaignId, stage: "preliminary_check", artifacts: { synchronized: 954, created: 6, updated: 1, bundle_sha256: "c".repeat(64) }, submitted_to_zeus: false, simulation_started: false, local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } } as const;
const snapshot: ZeusSnapshot = { connection_status: "connected", profile, remote: { project_directory: profile.project_directory, git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available", queried_at: "2026-10-12T10:00:00Z", jobs: [] } };
const preliminary = { state: "idle", status: null, preview: null, result: null, error: "", refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn() } as any;

describe("3D Discovery transition contract", () => {
  it("binds synchronized artifact count to the active workload policy", () => {
    try {
      vi.stubEnv("MODE", "ui-acceptance");
      const miniature = { ...result, artifacts: { ...result.artifacts, synchronized: 28 } };
      expect(parseMot3DDiscoveryTransitionResult(miniature, campaignId).artifacts.synchronized).toBe(28);
      for (const count of [27, 29, 954]) {
        expect(() => parseMot3DDiscoveryTransitionResult({ ...miniature, artifacts: { ...miniature.artifacts, synchronized: count } }, campaignId)).toThrow();
      }
      vi.stubEnv("MODE", "development");
      expect(parseMot3DDiscoveryTransitionResult(result, campaignId).artifacts.synchronized).toBe(954);
      expect(() => parseMot3DDiscoveryTransitionResult(miniature, campaignId)).toThrow();
    } finally {
      vi.unstubAllEnvs();
    }
  });
  it("accepts only the complete verified review and result", () => {
    expect(parseMot3DDiscoveryTransitionStatus(status).next_action).toBe("review_transition");
    expect(parseMot3DDiscoveryTransitionPreview(preview, { campaignId }).artifacts.synchronize.trial_registries).toBe(950);
    expect(parseMot3DDiscoveryTransitionResult(result, campaignId).submitted_to_zeus).toBe(false);
  });
  it.each([
    () => parseMot3DDiscoveryTransitionStatus({ ...status, validation: { ...status.validation, completed_trials: 949 } }),
    () => parseMot3DDiscoveryTransitionStatus({ ...status, next_action: "wait" }),
    () => parseMot3DDiscoveryTransitionStatus({ ...status, local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } }),
    () => parseMot3DDiscoveryTransitionPreview({ ...preview, effects: { ...preview.effects, submit_preliminary_check: true } }, { campaignId }),
    () => parseMot3DDiscoveryTransitionPreview({ ...preview, artifacts: { ...preview.artifacts, create: { selection_files: 2, job_files: 5 } } }, { campaignId }),
    () => parseMot3DDiscoveryTransitionResult({ ...result, simulation_started: true }, campaignId),
    () => parseMot3DDiscoveryTransitionStatus({ ...status, discovery: { ...status.discovery, chain: { ...chain, angled_donut: [chain.angled_donut[0]] } } }),
    () => parseMot3DDiscoveryTransitionStatus({ ...status, discovery: { status: "running", chain }, validation: { status: "not_ready", completed_trials: 1, expected_trials: 950 }, next_action: "wait" }),
  ])("rejects altered transition evidence", (parse) => expect(parse).toThrow());
  it("accepts remote preparation that still requires verified local synchronization", () => {
    const recovering = { ...status, discovery: { status: "preliminary_check_prepared", chain } };
    expect(parseMot3DDiscoveryTransitionStatus(recovering).next_action).toBe("review_transition");
  });
  it("consumes confirmation context before network submission", async () => {
    const responses: unknown[] = [preview, result];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ api_version: 1, data: responses.shift() }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const api = createMot3DDiscoveryTransitionApi(async () => "csrf");
    const reviewed = await api.preview(campaignId, profile);
    await expect(api.confirm(reviewed.preview_token)).resolves.toMatchObject({ status: "preliminary_check_prepared" });
    await expect(api.confirm(reviewed.preview_token)).rejects.toThrow("no longer active");
  });
});

describe("3D Discovery transition controller", () => {
  it("classifies remote-prepared but locally unsynchronized evidence as recoverable", async () => {
    const recovering = { ...status, discovery: { status: "preliminary_check_prepared", chain } } as const;
    const api = { status: vi.fn(async () => recovering), preview: vi.fn(async () => preview), confirm: vi.fn(), reset: vi.fn() } as unknown as ReturnType<typeof createMot3DDiscoveryTransitionApi>;
    const { result: hook } = renderHook(() => useMot3DDiscoveryTransitionController({ campaignId, snapshot, enabled: true, api }));
    await act(async () => { await hook.current.refresh(); });
    expect(hook.current.state).toBe("ready");
    await act(async () => { await hook.current.review(); });
    expect(api.preview).toHaveBeenCalledTimes(1);
    expect(hook.current.state).toBe("review");
  });
  it("suppresses double review and ignores a response after profile change", async () => {
    let resolve!: (value: typeof preview) => void;
    const pending = new Promise<typeof preview>((done) => { resolve = done; });
    const api = { status: vi.fn(async () => status), preview: vi.fn(() => pending), confirm: vi.fn(), reset: vi.fn() } as unknown as ReturnType<typeof createMot3DDiscoveryTransitionApi>;
    const { result: hook, rerender } = renderHook(({ value }) => useMot3DDiscoveryTransitionController({ campaignId, snapshot: value, enabled: true, api }), { initialProps: { value: snapshot } });
    await act(async () => { await hook.current.refresh(); });
    await act(async () => { void hook.current.review(); void hook.current.review(); });
    expect(api.preview).toHaveBeenCalledTimes(1);
    rerender({ value: { ...snapshot, profile: { ...profile, username: "other" } } });
    await act(async () => resolve(preview));
    expect(hook.current.preview).toBeNull();
    expect(hook.current.state).toBe("idle");
  });
});

describe("3D campaign transition view", () => {
  it("requires explicit review and says no job starts", async () => {
    const api = { status: vi.fn(async () => status), preview: vi.fn(async () => preview), confirm: vi.fn(async () => result), reset: vi.fn() } as unknown as ReturnType<typeof createMot3DDiscoveryTransitionApi>;
    const discovery = { state: "submitted", status: { submission: { status: "completed_success" } } } as any;
    function Harness() { const transition = useMot3DDiscoveryTransitionController({ campaignId, snapshot, enabled: true, api }); return <Mot3DCampaignFlow stage="discovery" connected discovery={discovery} transition={transition} preliminary={preliminary} onConnectZeus={vi.fn()} onViewJobs={vi.fn()}/>; }
    render(<Harness/>);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Verify Discovery results" }));
    await user.click(await screen.findByRole("button", { name: "Review synchronization" }));
    expect(await screen.findByRole("heading", { name: "Synchronize verified Discovery evidence" })).toBeInTheDocument();
    expect(screen.getAllByText("None", { selector: "dd" })).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Synchronize and prepare" }));
    expect(await screen.findByText("Preliminary check is prepared")).toBeInTheDocument();
    expect(screen.getByText(/No preliminary-check job has been submitted or started/)).toBeInTheDocument();
  });

  it("renders queued work as no-action and invalid outputs as blocking", () => {
    const discovery = { state: "submitted", status: { submission: { status: "completed_success" } } } as any;
    const base = { state: "idle", preview: null, result: null, error: "", refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn() };
    const queued = { ...base, status: { ...status, discovery: { status: "running", chain }, validation: { status: "not_ready", completed_trials: 0, expected_trials: 950 }, next_action: "wait" } } as any;
    const { rerender } = render(<Mot3DCampaignFlow stage="discovery" connected discovery={discovery} transition={queued} preliminary={preliminary} onConnectZeus={vi.fn()} onViewJobs={vi.fn()}/>);
    expect(screen.getByText("Discovery is still running on Zeus")).toBeInTheDocument();
    expect(screen.getAllByText(/No action is needed/).length).toBeGreaterThan(0);
    const invalid = { ...base, state: "terminal", status: { ...status, discovery: { status: "outputs_invalid", chain }, validation: { status: "invalid", completed_trials: 0, expected_trials: 950 }, next_action: "inspect_zeus" } } as any;
    rerender(<Mot3DCampaignFlow stage="discovery" connected discovery={discovery} transition={invalid} preliminary={preliminary} onConnectZeus={vi.fn()} onViewJobs={vi.fn()}/>);
    expect(screen.getByRole("alert")).toHaveTextContent("Manual verification required");
    expect(screen.queryByRole("button", { name: "Review synchronization" })).not.toBeInTheDocument();
  });

  it("explains crash recovery without implying another remote job", () => {
    const discovery = { state: "submitted", status: { submission: { status: "completed_success" } } } as any;
    const recovery = { state: "ready", preview: null, result: null, error: "", refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), status: { ...status, discovery: { status: "preliminary_check_prepared", chain } } } as any;
    render(<Mot3DCampaignFlow stage="discovery" connected discovery={discovery} transition={recovery} preliminary={preliminary} onConnectZeus={vi.fn()} onViewJobs={vi.fn()}/>);
    expect(screen.getByText("Preliminary check is prepared on Zeus; local synchronization is incomplete")).toBeInTheDocument();
    expect(screen.getByText(/No new job or simulation will start/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review synchronization" })).toBeInTheDocument();
  });
});

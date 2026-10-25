import { act, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  Mot3DFinalValidationCompletionApiError,
  createMot3DFinalValidationCompletionApi,
  parseMot3DFinalValidationCompletionPreview,
  parseMot3DFinalValidationCompletionStatus,
} from "../api/clients/mot3dFinalValidationCompletion";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DFinalValidationCompletionController } from "../features/campaign/controllers/useMot3DFinalValidationCompletionController";
import runningStatus from "./fixtures/c56-final-validation-running-status.json";
import preparedExtensionStatus from "./fixtures/c56-final-validation-prepared-extension-status.json";

const jobs = { dependency: "afterok within each family", families: [{ id: "angled_donut", array_job_id: "610[].zeus-master", merge_job_id: "611.zeus-master" }, { id: "single_pass", array_job_id: "612[].zeus-master", merge_job_id: "613.zeus-master" }] };
const completion = (outcome: "complete" | "final_validation_extension_required" = "complete") => ({ outcome, families: [{ family: "angled_donut", candidate_id: "angled_donut_finalist_02", conditional_efficiency: .5, bootstrap_95_ci: [.495, .505], ci_half_width: .0050000000000000044, precision_target_met: true }, { family: "single_pass", candidate_id: "single_pass_finalist_03", conditional_efficiency: .5, bootstrap_95_ci: outcome === "complete" ? [.495, .505] : [.49, .51], ci_half_width: outcome === "complete" ? .0050000000000000044 : .010000000000000009, precision_target_met: outcome === "complete" }], evidence_sha256: "b".repeat(64) });
const status = () => parseMot3DFinalValidationCompletionStatus({ source: "zeus", campaign: { id: "campaign-id", name: "campaign", stage: "final_validation" }, final_validation: { status: "ready_to_advance", chain: jobs }, scheduler: { completed_array_tasks: 6, expected_array_tasks: 6, completed_merge_jobs: 2, expected_merge_jobs: 2 }, validation: { status: "valid", result_artifacts: 14, expected_result_artifacts: 14, reason_code: null }, completion: { status: "not_completed", detail: null }, next_action: "review_completion", local_sync: { status: "not_synchronized", receipt_sha256: null } });
const terminalStatus = (outcome: "complete" | "final_validation_extension_required" = "final_validation_extension_required") => parseMot3DFinalValidationCompletionStatus({ source: "zeus", campaign: { id: "campaign-id", name: "campaign", stage: outcome }, final_validation: { status: outcome, chain: jobs }, scheduler: { completed_array_tasks: 6, expected_array_tasks: 6, completed_merge_jobs: 2, expected_merge_jobs: 2 }, validation: { status: "valid", result_artifacts: 14, expected_result_artifacts: 14, reason_code: null }, completion: { status: outcome, detail: completion(outcome) }, next_action: outcome === "complete" ? "open_final_report" : "review_extension_required", local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } });
const preview = (outcome: "complete" | "final_validation_extension_required" = "complete") => parseMot3DFinalValidationCompletionPreview({ preview_token: "review-token", expires_in_seconds: 300, campaign: { id: "campaign-id", name: "campaign", git_commit: "a".repeat(40) }, from_stage: "final_validation", to_stage: "complete_or_extension_required", final_validation: { result_artifacts: 14, expected_result_artifacts: 14, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { result_files: 14, submission_receipts: 1 }, create: { terminal_files: 1 }, update: ["campaign.json"], transfer_files: 17 }, effects: { synchronize_final_validation: true, complete_final_validation: true, submit_extension: false, start_simulation: false, overwrite_existing: false }, completion: completion(outcome) }, { campaignId: "campaign-id", commit: "a".repeat(40) });
const flow = (value: Record<string, unknown>) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...value }) as never;
const base = { stage: "final_validation", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const snapshot = { connection_status: "connected" as const, profile: { host: "zeus.technion.ac.il" as const, authentication: "ssh-key-or-agent" as const, username: "tal.noa", project_directory: "/home/tal.noa/project" }, remote: { project_directory: "/home/tal.noa/project", git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-13T00:00:00Z", jobs: [] } };

describe("Final Validation completion", () => {
  it.each(["complete", "final_validation_extension_required"] as const)("accepts remote prepared %s without claiming local synchronization", (outcome) => {
    const value = structuredClone(preparedExtensionStatus);
    value.final_validation.status = outcome;
    value.completion.status = outcome;
    const parsed = parseMot3DFinalValidationCompletionStatus(value);
    expect(parsed.campaign.stage).toBe("final_validation");
    expect(parsed.completion.detail).toBeNull();
    expect(parsed.local_sync).toEqual({ status: "not_synchronized", receipt_sha256: null });
    expect(parsed.next_action).toBe("synchronize_results");
  });

  it.each([
    ["terminal local stage without detail", (v: any): void => { v.campaign.stage = "final_validation_extension_required"; }],
    ["crossed local terminal stage", (v: any): void => { v.campaign.stage = "complete"; }],
    ["synchronized without detail", (v: any): void => { v.campaign.stage = "final_validation_extension_required"; v.local_sync = { status: "synchronized", receipt_sha256: "a".repeat(64) }; v.next_action = "review_extension_required"; }],
    ["receipt before synchronization", (v: any): void => { v.local_sync.receipt_sha256 = "a".repeat(64); }],
    ["synchronized flag before local transition", (v: any): void => { v.local_sync.status = "synchronized"; }],
    ["wrong next action", (v: any): void => { v.next_action = "review_completion"; }],
    ["unvalidated outputs", (v: any): void => { v.validation.status = "not_started"; v.validation.result_artifacts = 0; }],
    ["missing result", (v: any): void => { v.validation.result_artifacts = 13; }],
    ["incomplete simulation tasks", (v: any): void => { v.scheduler.completed_array_tasks = 5; }],
    ["incomplete merge", (v: any): void => { v.scheduler.completed_merge_jobs = 1; }],
    ["wrong completion outcome", (v: any): void => { v.completion.status = "complete"; }],
    ["unknown terminal outcome", (v: any): void => { v.final_validation.status = "other_terminal"; v.completion.status = "other_terminal"; }],
    ["nonterminal with terminal completion", (v: any): void => { v.final_validation.status = "running"; }],
    ["unknown detail shape", (v: any): void => { v.completion.detail = {}; }],
    ["detail before local synchronization", (v: any): void => { v.completion.detail = completion("final_validation_extension_required"); }],
  ] as const)("rejects contradictory prepared status: %s", (_label, mutate) => {
    const value = structuredClone(preparedExtensionStatus);
    mutate(value);
    expect(() => parseMot3DFinalValidationCompletionStatus(value)).toThrow("Invalid Final Validation completion");
  });

  it("retains detailed synchronized terminal outcome and nonterminal stage guards", () => {
    const synchronized = terminalStatus();
    for (const detail of [null, completion("complete"), {}]) {
      expect(() => parseMot3DFinalValidationCompletionStatus({ ...synchronized, completion: { ...synchronized.completion, detail } })).toThrow();
    }
    const waiting = { ...runningStatus, campaign: { ...runningStatus.campaign, stage: "complete" } };
    expect(() => parseMot3DFinalValidationCompletionStatus(waiting)).toThrow();
  });

  it("offers review through the real client/controller for the captured unsynchronized terminal receipt", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => { expect(input).toBe("/api/v1/zeus/mot-3d/final-validation-completion/status"); return new Response(JSON.stringify({ api_version: 1, data: preparedExtensionStatus }), { status: 200, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    const api = createMot3DFinalValidationCompletionApi(async () => "csrf");
    function Harness() {
      const controller = useMot3DFinalValidationCompletionController({ campaignId: preparedExtensionStatus.campaign.id, snapshot, enabled: true, api });
      return <Mot3DCampaignFlow {...base} finalValidationCompletion={controller} />;
    }
    try {
      render(<Harness />);
      await user.click(screen.getByRole("button", { name: "Check sealed results" }));
      expect(await screen.findByRole("button", { name: "Review completion" })).toBeEnabled();
      expect(screen.queryByText("Final Validation extension is required")).not.toBeInTheDocument();
      expect(screen.queryByText("Final report is ready")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Record extension required" })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledOnce();
      expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/zeus/mot-3d/final-validation-completion/status");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("can refresh actual running completion evidence until it becomes reviewable", async () => {
    const user = userEvent.setup();
    const running = parseMot3DFinalValidationCompletionStatus(runningStatus);
    const ready = parseMot3DFinalValidationCompletionStatus({
      ...running,
      final_validation: { ...running.final_validation, status: "ready_to_advance" },
      scheduler: { ...running.scheduler, completed_array_tasks: 6, completed_merge_jobs: 2 },
      validation: { ...running.validation, status: "valid", result_artifacts: 14 },
      next_action: "review_completion",
    });
    const api = { status: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(ready), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() };
    function Harness() {
      const controller = useMot3DFinalValidationCompletionController({ campaignId: running.campaign.id, snapshot, enabled: true, api });
      return <Mot3DCampaignFlow {...base} finalValidationCompletion={controller} />;
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Check sealed results" }));
    expect(await screen.findByText("Waiting for sealed Final Validation results")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Review completion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Synchronize and publish final report" })).not.toBeInTheDocument();
    expect(api.status).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(await screen.findByRole("button", { name: "Review completion" })).toBeEnabled();
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(api.preview).not.toHaveBeenCalled();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it.each([
    ["queued", 3, 0],
    ["completed_success_unvalidated", 6, 2],
  ] as const)("keeps %s completion evidence refreshable without offering publication", async (lifecycle, arrays, merges) => {
    const user = userEvent.setup();
    const waiting = parseMot3DFinalValidationCompletionStatus({
      ...runningStatus,
      final_validation: { ...runningStatus.final_validation, status: lifecycle },
      scheduler: { ...runningStatus.scheduler, completed_array_tasks: arrays, completed_merge_jobs: merges },
    });
    const refresh = vi.fn();
    render(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({ status: waiting, refresh })} />);
    expect(screen.getByText(/Simulation tasks complete:/)).toHaveTextContent(`Simulation tasks complete: ${arrays} of 6. Merge jobs complete: ${merges} of 2. Results still require validation.`);
    expect(screen.queryByRole("button", { name: "Review completion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Synchronize and publish final report" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("strictly binds metrics, decision, evidence and zero-job effects", () => {
    expect(preview().completion.families[0].ci_half_width).toBeCloseTo(.005);
    for (const mutate of [
      (v: any) => v.completion.families[0].ci_half_width = .004,
      (v: any) => v.completion.families[1].precision_target_met = false,
      (v: any) => v.completion.evidence_sha256 = "c".repeat(64),
      (v: any) => v.effects.submit_extension = true,
      (v: any) => v.artifacts.create.terminal_files = 2,
    ]) {
      const value: any = { preview_token: "review-token", expires_in_seconds: 300, campaign: { id: "campaign-id", name: "campaign", git_commit: "a".repeat(40) }, from_stage: "final_validation", to_stage: "complete_or_extension_required", final_validation: { result_artifacts: 14, expected_result_artifacts: 14, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { result_files: 14, submission_receipts: 1 }, create: { terminal_files: 1 }, update: ["campaign.json"], transfer_files: 17 }, effects: { synchronize_final_validation: true, complete_final_validation: true, submit_extension: false, start_simulation: false, overwrite_existing: false }, completion: structuredClone(completion()) };
      mutate(value);
      expect(() => parseMot3DFinalValidationCompletionPreview(value, { campaignId: "campaign-id", commit: "a".repeat(40) })).toThrow();
    }
  });

  it("renders explicit complete and extension reviews without inventing policy", () => {
    const view = render(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({ phase: "review", status: status(), preview: preview() })} />);
    expect(screen.getByRole("heading", { name: "Review the sealed Final Validation result" })).toHaveFocus();
    expect(screen.getAllByText("Pass")).toHaveLength(2);
    expect(screen.getByText(/derived only from the sealed new ensembles/)).toBeVisible();
    expect(screen.getByText("None")).toBeVisible();
    view.rerender(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({ phase: "review", status: status(), preview: preview("final_validation_extension_required") })} />);
    expect(screen.getByText(/Failing family: Single pass/)).toBeVisible();
    expect(screen.getByText(/will not submit one or claim a winner/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /submit extension/i })).not.toBeInTheDocument();
    view.rerender(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({ phase: "success", status: terminalStatus() })} />);
    expect(screen.getByText(/Precision was not established for: Single pass/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /extension/i })).not.toBeInTheDocument();
  });

  it("guards stale context and consumes an ambiguous confirmation exactly once", async () => {
    let resolve!: (value: ReturnType<typeof status>) => void;
    const api = { status: vi.fn(() => new Promise<ReturnType<typeof status>>((done) => { resolve = done; })), preview: vi.fn(async () => preview()), confirm: vi.fn(async () => { throw new Mot3DFinalValidationCompletionApiError("final_validation_completion_outcome_unknown", "Unknown"); }), reset: vi.fn() };
    const hook = renderHook(({ current }) => useMot3DFinalValidationCompletionController({ campaignId: "campaign-id", snapshot: current, enabled: true, api }), { initialProps: { current: snapshot } });
    act(() => { void hook.result.current.refresh(); void hook.result.current.refresh(); });
    expect(api.status).toHaveBeenCalledOnce();
    hook.rerender({ current: { ...snapshot, remote: { ...snapshot.remote, git_commit: "c".repeat(40) } } });
    await act(async () => resolve(status()));
    expect(hook.result.current.status).toBeNull();
    hook.rerender({ current: snapshot });
    api.status.mockResolvedValueOnce(status());
    await act(async () => hook.result.current.refresh());
    await act(async () => hook.result.current.review());
    await act(async () => { void hook.result.current.confirm(); void hook.result.current.confirm(); });
    expect(api.confirm).toHaveBeenCalledOnce();
    expect(hook.result.current.errorPhase).toBe("confirm_unknown");
    await act(async () => hook.result.current.confirm());
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it.each(["complete", "final_validation_extension_required"] as const)("restores controller success from terminal %s status", async (outcome) => {
    const api = { status: vi.fn(async () => terminalStatus(outcome)), preview: vi.fn(async () => preview(outcome)), confirm: vi.fn(), reset: vi.fn() };
    const hook = renderHook(() => useMot3DFinalValidationCompletionController({ campaignId: "campaign-id", snapshot, enabled: true, api }));
    await act(async () => hook.result.current.refresh());
    expect(hook.result.current.phase).toBe("success");
    expect(hook.result.current.status?.completion.detail?.outcome).toBe(outcome);
  });

  it("renders typed invalid output counts and reason through the real status controller", async () => {
    const user = userEvent.setup();
    const invalid = parseMot3DFinalValidationCompletionStatus({
      ...status(),
      final_validation: { ...status().final_validation, status: "completed_success_unvalidated" },
      validation: { status: "scientifically_invalid", result_artifacts: 0, expected_result_artifacts: 14, reason_code: "artifact_registry_mismatch" },
      next_action: "inspect_zeus",
    });
    const api = { status: vi.fn().mockResolvedValueOnce(invalid).mockResolvedValueOnce(terminalStatus()), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() };
    function Harness() {
      const controller = useMot3DFinalValidationCompletionController({ campaignId: invalid.campaign.id, snapshot, enabled: true, api });
      return <Mot3DCampaignFlow {...base} finalValidationCompletion={controller} />;
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Check sealed results" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Final Validation outputs are invalid");
    expect(alert).toHaveTextContent("Validated result artifacts: 0 of 14");
    expect(alert).toHaveTextContent("sealed result files are missing or inconsistent");
    expect(alert).toHaveTextContent("artifact validation, not physical survivors");
    expect(alert).not.toHaveTextContent("outcome is uncertain");
    await user.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(await screen.findByText("Final Validation extension is required")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Review completion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Synchronize|Record extension/ })).not.toBeInTheDocument();
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(api.preview).not.toHaveBeenCalled();
    expect(api.confirm).not.toHaveBeenCalled();
  });
  it("retains uncertainty wording for a genuinely unknown blocked outcome", () => {
    render(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({ phase: "blocked", status: null })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Manual verification required");
    expect(screen.getByRole("alert")).toHaveTextContent("outcome is uncertain. Do not retry");
    expect(screen.queryByText(/Validated result artifacts:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review completion" })).not.toBeInTheDocument();
  });
});

// Genuine final-preview metrics: Mac56 and Windows69 both have a valid zero
// Single-pass efficiency, with fourteen verified artifacts (not zero artifacts).
const capturedPhysicalMetrics = [
  {
    "bootstrap_95_ci": [
      0.5662210784313725,
      0.6741854636591479
    ],
    "candidate_id": "angled_donut_finalist_01",
    "ci_half_width": 0.0539821926138877,
    "conditional_efficiency": 0.6201353637901861,
    "family": "angled_donut",
    "precision_target_met": false
  },
  {
    "bootstrap_95_ci": [
      0,
      0
    ],
    "candidate_id": "single_pass_finalist_01",
    "ci_half_width": 0,
    "conditional_efficiency": 0,
    "family": "single_pass",
    "precision_target_met": true
  }
];
it.each([
  {
    "label": "Mac56",
    "campaign": {
      "git_commit": "6c6209a3986dd3391dbed6cb0cb668b965793ac1",
      "id": "mot_3d-9b8f87352bbf66a53668",
      "name": "TESTONLY_Mac3D_UI_Release_20261023_V2_C56"
    },
    "evidence_sha256": "1ab3184b94e4dda760e1ff28a91c12a03e88f308c33a2ff7d71cc3b420ab5741"
  },
  {
    "label": "Windows69",
    "campaign": {
      "git_commit": "c3c42c95b78324456bfa4d2626776b0b4dc82d43",
      "id": "mot_3d-3b84a83ea93557c6a6e6",
      "name": "TESTONLY_Windows3D_UI_Release_20261024_V2_C69"
    },
    "evidence_sha256": "ec0b3fe2e424b7d08869fa7e0ab5ab75023776609aaaffdc8a53d41a3086c4b1"
  }
])("renders captured $label valid physical zero without treating artifacts as missing", captured => {
  const raw = structuredClone(preview("final_validation_extension_required"));
  raw.campaign = captured.campaign;
  raw.completion = { outcome: "final_validation_extension_required", families: capturedPhysicalMetrics, evidence_sha256: captured.evidence_sha256 } as typeof raw.completion;
  const artifacts = raw.final_validation as { evidence_sha256: string; result_artifacts: number; expected_result_artifacts: number };
  artifacts.evidence_sha256 = captured.evidence_sha256;
  const parsed = parseMot3DFinalValidationCompletionPreview(raw, {campaignId: captured.campaign.id, commit: captured.campaign.git_commit});
  expect(parsed.final_validation).toMatchObject({result_artifacts:14,expected_result_artifacts:14});
  render(<Mot3DCampaignFlow {...base} finalValidationCompletion={flow({phase:"review",status:status(),preview:parsed})}/>);
  const card = screen.getByText("Single pass", {selector:"h4"}).closest("article")!;
  expect(within(card).getByText("0.000000–0.000000")).toBeVisible();
  expect(within(card).getAllByText("0.000000")).toHaveLength(2);
  expect(within(card).getByText("Pass")).toBeVisible();
  expect(screen.getByText("14 of 14")).toBeVisible();
  expect(screen.getByRole("button",{name:"Record extension required"})).toBeVisible();
  expect(screen.queryByRole("button",{name:"Synchronize and publish final report"})).not.toBeInTheDocument();
  expect(screen.getByText(/Failing family: Angled donut/)).toBeVisible();
  expect(() => parseMot3DFinalValidationCompletionPreview({...raw,final_validation:{...artifacts,result_artifacts:0}}, {campaignId:captured.campaign.id,commit:captured.campaign.git_commit})).toThrow();
});


it("recovers a failed completion status through the existing read-only controller without preview or confirmation", async () => {
  const user = userEvent.setup();
  const api = { status: vi.fn().mockRejectedValueOnce(new Error("Zeus connection unavailable")).mockResolvedValueOnce(terminalStatus()), preview: vi.fn(), confirm: vi.fn(), reset: vi.fn() };
  function Harness() {
    const controller = useMot3DFinalValidationCompletionController({ campaignId: "campaign-id", snapshot, enabled: true, api });
    return <Mot3DCampaignFlow {...base} finalValidationCompletion={controller} />;
  }
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Check sealed results" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Zeus connection unavailable");
  expect(screen.queryByRole("button", { name: "Review completion" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open Zeus jobs" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Refresh status" }));
  expect(await screen.findByText("Final Validation extension is required")).toBeVisible();
  expect(api.status).toHaveBeenCalledTimes(2);
  expect(api.preview).not.toHaveBeenCalled();
  expect(api.confirm).not.toHaveBeenCalled();
});

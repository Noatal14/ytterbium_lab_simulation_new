import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  Mot3DFinalValidationCompletionApiError,
  parseMot3DFinalValidationCompletionPreview,
  parseMot3DFinalValidationCompletionStatus,
} from "../api/clients/mot3dFinalValidationCompletion";
import { Mot3DCampaignFlow } from "../features/campaign/Mot3DCampaignFlow";
import { useMot3DFinalValidationCompletionController } from "../features/campaign/controllers/useMot3DFinalValidationCompletionController";
import runningStatus from "./fixtures/c56-final-validation-running-status.json";

const jobs = { dependency: "afterok within each family", families: [{ id: "angled_donut", array_job_id: "610[].zeus-master", merge_job_id: "611.zeus-master" }, { id: "single_pass", array_job_id: "612[].zeus-master", merge_job_id: "613.zeus-master" }] };
const completion = (outcome: "complete" | "final_validation_extension_required" = "complete") => ({ outcome, families: [{ family: "angled_donut", candidate_id: "angled_donut_finalist_02", conditional_efficiency: .5, bootstrap_95_ci: [.495, .505], ci_half_width: .0050000000000000044, precision_target_met: true }, { family: "single_pass", candidate_id: "single_pass_finalist_03", conditional_efficiency: .5, bootstrap_95_ci: outcome === "complete" ? [.495, .505] : [.49, .51], ci_half_width: outcome === "complete" ? .0050000000000000044 : .010000000000000009, precision_target_met: outcome === "complete" }], evidence_sha256: "b".repeat(64) });
const status = () => parseMot3DFinalValidationCompletionStatus({ source: "zeus", campaign: { id: "campaign-id", name: "campaign", stage: "final_validation" }, final_validation: { status: "ready_to_advance", chain: jobs }, scheduler: { completed_array_tasks: 6, expected_array_tasks: 6, completed_merge_jobs: 2, expected_merge_jobs: 2 }, validation: { status: "valid", result_artifacts: 14, expected_result_artifacts: 14, reason_code: null }, completion: { status: "not_completed", detail: null }, next_action: "review_completion", local_sync: { status: "not_synchronized", receipt_sha256: null } });
const terminalStatus = (outcome: "complete" | "final_validation_extension_required" = "final_validation_extension_required") => parseMot3DFinalValidationCompletionStatus({ source: "zeus", campaign: { id: "campaign-id", name: "campaign", stage: outcome }, final_validation: { status: outcome, chain: jobs }, scheduler: { completed_array_tasks: 6, expected_array_tasks: 6, completed_merge_jobs: 2, expected_merge_jobs: 2 }, validation: { status: "valid", result_artifacts: 14, expected_result_artifacts: 14, reason_code: null }, completion: { status: outcome, detail: completion(outcome) }, next_action: outcome === "complete" ? "open_final_report" : "review_extension_required", local_sync: { status: "synchronized", receipt_sha256: "d".repeat(64) } });
const preview = (outcome: "complete" | "final_validation_extension_required" = "complete") => parseMot3DFinalValidationCompletionPreview({ preview_token: "review-token", expires_in_seconds: 300, campaign: { id: "campaign-id", name: "campaign", git_commit: "a".repeat(40) }, from_stage: "final_validation", to_stage: "complete_or_extension_required", final_validation: { result_artifacts: 14, expected_result_artifacts: 14, families: ["angled_donut", "single_pass"], evidence_sha256: "b".repeat(64) }, artifacts: { synchronize: { result_files: 14, submission_receipts: 1 }, create: { terminal_files: 1 }, update: ["campaign.json"], transfer_files: 17 }, effects: { synchronize_final_validation: true, complete_final_validation: true, submit_extension: false, start_simulation: false, overwrite_existing: false }, completion: completion(outcome) }, { campaignId: "campaign-id", commit: "a".repeat(40) });
const flow = (value: Record<string, unknown>) => ({ phase: "idle", status: null, preview: null, result: null, error: "", errorPhase: null, refresh: vi.fn(), review: vi.fn(), confirm: vi.fn(), reset: vi.fn(), ...value }) as never;
const base = { stage: "final_validation", connected: true, discovery: {} as never, transition: {} as never, preliminary: {} as never, onConnectZeus: vi.fn(), onViewJobs: vi.fn() };
const snapshot = { connection_status: "connected" as const, profile: { host: "zeus.technion.ac.il" as const, authentication: "ssh-key-or-agent" as const, username: "tal.noa", project_directory: "/home/tal.noa/project" }, remote: { project_directory: "/home/tal.noa/project", git_commit: "a".repeat(40), branch: "main", dirty: false }, scheduler: { status: "available" as const, queried_at: "2026-10-13T00:00:00Z", jobs: [] } };

describe("Final Validation completion", () => {
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
});

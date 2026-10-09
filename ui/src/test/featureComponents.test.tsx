import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MOT_2D_SPECIFICATION_V1 } from "../generated/mot2dSpec.v1";
import { CandidateTable } from "../features/shared/CandidateTable";
import { JobResources } from "../features/shared/JobResources";
import { ManualVerification } from "../features/shared/ActionError";
import { ReviewEffects } from "../features/shared/ReviewEffects";
import { SmokePointsTable } from "../features/campaign/SmokeStage";
import { ScreeningFacts } from "../features/campaign/ScreeningStage";
import { ScreeningFlow } from "../features/campaign/ScreeningFlow";
import { SmokeFlow } from "../features/campaign/SmokeFlow";
import { RefinementFlow } from "../features/campaign/RefinementFlow";
import { ConfirmationStage } from "../features/campaign/ConfirmationStage";
import type { ScreeningSubmissionPreview } from "../api/clients/screening";
import type { SmokeLifecycle, SmokeSubmissionPreview } from "../api/clients/smoke";
import type { ConfirmationPreview, RefinementChainStatus, RefinementLifecycle, RefinementSubmissionPreview } from "../api/clients/refinement";

const noop = () => undefined;
const smokeLifecycle: SmokeLifecycle = {
  source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "c", name: "C", stage: "smoke" }, submission: { job_id: "1.zeus-master" },
  scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 }, validation: { status: "valid", points: [{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }], artifact_count: 3 }, lifecycle: "ready_to_prepare_screen", next_action: "review_screening_preparation",
};
const smokePreview: SmokeSubmissionPreview = {
  preview_token: "token", expires_in_seconds: 300, campaign: { id: "c", name: "C", path: "campaigns/c", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "smoke", label: "Smoke check", purpose: "Validate execution." },
  job: { file: "jobs/01_smoke.pbs", kind: "job", task_count: 1, queue: "zeus_combined_q", cores_per_task: 1, memory_per_task_bytes: 68719476736, walltime_seconds: 1200 }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/t/c", commit: "a".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, effects: { submit_smoke: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
};
const screeningPreview: ScreeningSubmissionPreview = {
  preview_token: "token", expires_in_seconds: 300, campaign: { id: "c", name: "C", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "screen", label: "Screening", purpose: "Find candidates." },
  job: { file: "jobs/02_screen.pbs", kind: "array", task_count: 3, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 86400 }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/t/c", commit: "a".repeat(40), branch: "main", dirty: false }, inputs: { verified_count: 72, status: "ready" }, smoke: { status: "validated", job_id: "1.zeus-master", point_count: 1 }, effects: { submit_screening: true, submit_later_stages: false, modify_files: false }, later_stages_locked: true,
};
const chainStatus: RefinementChainStatus = { source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "c", name: "C", stage: "refine" }, chain: { status: "not_submitted", dependency: "afterok", rounds: [1, 2, 3, 4].map((round) => ({ round: round as 1 | 2 | 3 | 4, state: "not_submitted" as const, job_id: null, depends_on_job_id: null })) }, next_action: "review_submission", local_sync: { status: "not_synchronized" } };
const chainPreview: RefinementSubmissionPreview = { preview_token: "token", expires_in_seconds: 300, campaign: { id: "c", name: "C", git_commit: "a".repeat(40), s0_values: [1.3] }, stage: { id: "refine", label: "Refinement" }, chain: { dependency: "afterok", rounds: MOT_2D_SPECIFICATION_V1.stages.refine.cumulative_trial_targets.map((target, index) => ({ round: (index + 1) as 1 | 2 | 3 | 4, file: MOT_2D_SPECIFICATION_V1.stages.refine.round_job_files[index], cumulative_target: target, kind: "array" as const, task_count: 3, array_throttle: 3 as const, queue: "zeus_combined_q" as const, cores_per_task: 200 as const, memory_per_task_bytes: 68719476736 as const, walltime_seconds: 72000 as const, depends_on: index === 0 ? null : index })) }, remote: { host: "zeus.technion.ac.il", project_directory: "/home/t/c", commit: "a".repeat(40), branch: "main", dirty: false }, effects: { submit_refinement_chain: true, start_simulation: true, submit_later_stages: false, modify_files: false }, local_sync: { status: "not_synchronized" } };
const refinementLifecycle: RefinementLifecycle = { source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "c", name: "C", stage: "refine" }, chain: { status: "ready_to_prepare_confirmation", rounds: [1, 2, 3, 4].map((round) => ({ round: round as 1 | 2 | 3 | 4, job_id: `${round}[].zeus-master`, depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master`, scheduler: { state: "completed_success" as const, task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } } })) }, validation: { status: "valid", completed_trials: 30, expected_trials: 30, candidate_count: 5 }, next_action: "review_confirmation_preparation", local_sync: { status: "not_synchronized" } };
const confirmationPreview: ConfirmationPreview = { preview_token: "token", expires_in_seconds: 300, campaign: { id: "c", name: "C", git_commit: "a".repeat(40), s0_values: [1.3] }, from_stage: "refine", to_stage: "confirmation", bounds: { detuning_gamma: { low: -2, high: 0 }, magnet_radius_m: { low: 0.03, high: 0.08 } }, refinement: { round_job_ids: ["1[].zeus-master", "2[].zeus-master", "3[].zeus-master", "4[].zeus-master"], completed_trials: 30, expected_trials: 30, candidates: [] }, artifacts: { create: ["refined_candidates.json", "confirmation/tasks.json", "jobs/04_confirmation.pbs"], update: ["campaign.json"] }, job: { file: "jobs/04_confirmation.pbs", kind: "array", task_count: 5, array_throttle: 3, queue: "zeus_combined_q", cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 36000 }, effects: { prepare_confirmation: true, submit_confirmation: false, start_simulation: false, overwrite_existing: false }, local_sync: { status: "not_synchronized" } };

describe("shared workflow presentation", () => {
  it("labels candidate estimates without presenting them as final performance", () => {
    render(<CandidateTable caption="Selected candidates from Refinement" estimateLabel="Refinement estimate" candidates={[{ source: "candidate.json", s0: 1.3, rank: 1, detuning_gamma: -0.8, magnet_radius_m: 0.046, mean_conditional_efficiency: 0.027 }]} />);
    expect(screen.getByRole("table", { name: "Selected candidates from Refinement" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Refinement estimate" })).toBeVisible();
    expect(screen.getByText("2.7%")).toBeVisible();
  });

  it("keeps manual verification actionable and accessible", () => {
    const onViewJobs = vi.fn();
    render(<ManualVerification title="Manual verification required" message="Automatic retry is blocked." onViewJobs={onViewJobs} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Automatic retry is blocked.");
    fireEvent.click(screen.getByRole("button", { name: "View Zeus jobs" }));
    expect(onViewJobs).toHaveBeenCalledOnce();
  });

  it("renders exact resource and effect facts", () => {
    render(<><div data-testid="resources"><JobResources job={{ cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 36000 }} /></div><ReviewEffects>{[<>Does not submit a Zeus job.</>, <>Does not start a simulation.</>]}</ReviewEffects></>);
    expect(screen.getByTestId("resources")).toHaveTextContent("200 cores · 64 GB · 10 h");
    expect(screen.getByText("Does not submit a Zeus job.")).toBeVisible();
  });

  it("renders smoke and Screening evidence as stage-specific facts", () => {
    render(<><SmokePointsTable points={[{ s0: 1.3, captured: 0, input: 2, efficiency: 0 }]} /><ScreeningFacts lifecycle={{ source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "c", name: "C", stage: "screen" }, submission: { job_id: "1[].zeus-master" }, scheduler: { state: "running", raw_state: "R", exit_status: null, task_count: 3, counts: { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 } }, validation: { status: "not_ready", completed_trials: 0, expected_trials: 51, candidate_count: 0 }, lifecycle: "screen_running", next_action: "wait" }} /></>);
    expect(screen.getByRole("table", { name: "Validated smoke points" })).toHaveTextContent("0 of 2");
    expect(screen.getByText((_, element) => element?.tagName === "DD" && element.textContent === "0 of 51")).toBeVisible();
  });

  it("keeps validated Smoke evidence visible when its submission action fails", () => {
    render(<SmokeFlow visible canSubmit submissionState="error" submissionPreview={null} submissionResult={null} submissionError="Submission stopped." lifecycle={smokeLifecycle} lifecycleCheck="ready" lifecycleError="" screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Submission stopped.");
    expect(screen.getByRole("table", { name: "Validated smoke points" })).toBeVisible();
  });

  it("moves focus into the Smoke submission review", () => {
    const view = render(<SmokeFlow visible canSubmit submissionState="idle" submissionPreview={null} submissionResult={null} submissionError="" lifecycle={null} lifecycleCheck="idle" lifecycleError="" screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    view.rerender(<SmokeFlow visible canSubmit submissionState="review" submissionPreview={smokePreview} submissionResult={null} submissionError="" lifecycle={null} lifecycleCheck="idle" lifecycleError="" screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Submit smoke check to Zeus" })).toHaveFocus();
  });

  it("keeps Screening status evidence visible when its submission action fails", () => {
    render(<ScreeningFlow visible evidenceFresh smokeCheck="ready" submitState="error" submitPreview={null} submitResult={null} submitError="Submission stopped." lifecycle={{ source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "c", name: "C", stage: "screen" }, submission: { job_id: "2[].zeus-master" }, scheduler: { state: "running", raw_state: "R", exit_status: null, task_count: 3, counts: { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 } }, validation: { status: "not_ready", completed_trials: 0, expected_trials: 51, candidate_count: 0 }, lifecycle: "screen_running", next_action: "wait" }} lifecycleCheck="ready" lifecycleError="" prepareState="idle" preparePreview={null} prepareResult={null} prepareError="" onRefreshSmoke={noop} onPreviewSubmit={noop} onConfirmSubmit={noop} onResetSubmit={noop} onRefreshLifecycle={noop} onPreviewPrepare={noop} onConfirmPrepare={noop} onResetPrepare={noop} onViewJobs={noop} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Submission stopped.");
    expect(screen.getByText("Array tasks")).toBeVisible();
  });

  it("moves focus into the Screening submission review", () => {
    const common = { visible: true, evidenceFresh: true, smokeCheck: "ready" as const, submitResult: null, submitError: "", lifecycle: null, lifecycleCheck: "idle" as const, lifecycleError: "", prepareState: "idle" as const, preparePreview: null, prepareResult: null, prepareError: "", onRefreshSmoke: noop, onPreviewSubmit: noop, onConfirmSubmit: noop, onResetSubmit: noop, onRefreshLifecycle: noop, onPreviewPrepare: noop, onConfirmPrepare: noop, onResetPrepare: noop, onViewJobs: noop };
    const view = render(<ScreeningFlow {...common} submitState="idle" submitPreview={null} />);
    view.rerender(<ScreeningFlow {...common} submitState="review" submitPreview={screeningPreview} />);
    expect(screen.getByRole("heading", { name: "Submit Screening to Zeus" })).toHaveFocus();
  });

  it("keeps the durable Refinement receipt visible and focuses a blocked error", () => {
    render(<RefinementFlow visible status={{ ...chainStatus, chain: { ...chainStatus.chain, status: "partial" }, next_action: "inspect_zeus" }} check="ready" state="blocked" preview={null} result={null} error="Automatic retry is blocked." onRefresh={noop} onPreview={noop} onConfirm={noop} onReset={noop} onViewJobs={noop} />);
    expect(screen.getByText("Round 1")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveFocus();
  });

  it("moves focus into the Refinement submission review", () => {
    const common = { visible: true, status: chainStatus, check: "ready" as const, result: null, error: "", onRefresh: noop, onPreview: noop, onConfirm: noop, onReset: noop, onViewJobs: noop };
    const view = render(<RefinementFlow {...common} state="idle" preview={null} />);
    view.rerender(<RefinementFlow {...common} state="review" preview={chainPreview} />);
    expect(screen.getByRole("heading", { name: "Submit four-round Refinement chain" })).toHaveFocus();
  });

  it("owns Confirmation lifecycle and review focus", () => {
    const common = { visible: true, lifecycle: refinementLifecycle, result: null, error: "", onRefresh: noop, onPreview: noop, onConfirm: noop, onReset: noop, onViewJobs: noop };
    const view = render(<ConfirmationStage {...common} lifecycleCheck="idle" state="idle" preview={null} />);
    view.rerender(<ConfirmationStage {...common} lifecycleCheck="ready" state="idle" preview={null} />);
    expect(screen.getByRole("heading", { name: "Refinement results validated" })).toHaveFocus();
    view.rerender(<ConfirmationStage {...common} lifecycleCheck="ready" state="review" preview={confirmationPreview} />);
    expect(screen.getByRole("heading", { name: "Prepare Confirmation on Zeus" })).toHaveFocus();
  });

  it("focuses Confirmation errors without hiding validated lifecycle evidence", () => {
    render(<ConfirmationStage visible lifecycle={refinementLifecycle} lifecycleCheck="ready" state="terminal" preview={null} result={null} error="Manual verification required." onRefresh={noop} onPreview={noop} onConfirm={noop} onReset={noop} onViewJobs={noop} />);
    expect(screen.getByText("Validated trials:")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveFocus();
  });
});

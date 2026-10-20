import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MOT_2D_SPECIFICATION_V1 } from "../generated/mot2dSpec.v1";
import { CandidateTable } from "../features/shared/CandidateTable";
import { JobResources } from "../features/shared/JobResources";
import { ManualVerification } from "../features/shared/ActionError";
import { ReviewEffects } from "../features/shared/ReviewEffects";
import { SmokePointsTable } from "../features/campaign/SmokeStage";
import { ScreeningFacts } from "../features/campaign/ScreeningStage";
import { ScreeningFlow } from "../features/campaign/ScreeningFlow";
import { ReviewedResources } from "../features/campaign/Mot3DCampaignFlow";
import { SmokeFlow } from "../features/campaign/SmokeFlow";
import { RefinementFlow } from "../features/campaign/RefinementFlow";
import { ConfirmationStage } from "../features/campaign/ConfirmationStage";
import type { ScreeningSubmissionPreview } from "../api/clients/screening";
import type { SmokeLifecycle, SmokeSubmissionPreview } from "../api/clients/smoke";
import type { ConfirmationPreview, RefinementChainStatus, RefinementLifecycle, RefinementSubmissionPreview } from "../api/clients/refinement";
import { parseConfirmationResult, parseRefinementChainStatus, parseRefinementLifecycle, parseRefinementSubmissionResult, parseScreeningLifecycle, parseScreeningResult, parseSmokeLifecycle } from "../api/schema/domain";

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
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      render(<><div data-testid="resources"><JobResources job={{ cores_per_task: 200, memory_per_task_bytes: 68719476736, walltime_seconds: 36000 }} /></div><ReviewEffects effects={[<>Does not submit a Zeus job.</>, <>Does not start a simulation.</>]} /></>);
      expect(screen.getByTestId("resources")).toHaveTextContent("200 cores · 64 GiB · 10 h");
      expect(screen.getByText("Does not submit a Zeus job.")).toBeVisible();
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
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
    expect(screen.getByText(/read-only check of the scheduler and validated smoke artifacts/)).toBeVisible();
    expect(screen.queryByText(/scientifically validated smoke/)).not.toBeInTheDocument();
  });

  it("keeps the last validated Smoke evidence visible when a refresh fails", () => {
    render(<SmokeFlow visible canSubmit={false} submissionState="idle" submissionPreview={null} submissionResult={null} submissionError="" lifecycle={smokeLifecycle} lifecycleCheck="error" lifecycleError="The latest Zeus status check failed." screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The latest Zeus status check failed.",
    );
    expect(screen.getByRole("alert")).toHaveFocus();
    expect(screen.getByRole("table", { name: "Validated smoke points" })).toBeVisible();
  });

  it("moves focus into the Smoke submission review", () => {
    const view = render(<SmokeFlow visible canSubmit submissionState="idle" submissionPreview={null} submissionResult={null} submissionError="" lifecycle={null} lifecycleCheck="idle" lifecycleError="" screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    view.rerender(<SmokeFlow visible canSubmit submissionState="review" submissionPreview={smokePreview} submissionResult={null} submissionError="" lifecycle={null} lifecycleCheck="idle" lifecycleError="" screeningState="idle" screeningPreview={null} screeningResult={null} screeningError="" onPreviewSubmission={noop} onConfirmSubmission={noop} onResetSubmission={noop} onRefreshLifecycle={noop} onPreviewScreening={noop} onConfirmScreening={noop} onResetScreening={noop} onViewJobs={noop} />);
    expect(screen.getByRole("heading", { name: "Submit smoke check to Zeus" })).toHaveFocus();
  });

  it("keeps the Screening preparation receipt visible and focused after Smoke evidence advances or clears", () => {
    const screeningResult = parseScreeningResult({
      status: "screening_prepared",
      campaign_id: "c",
      stage: "screen",
      artifacts: { created: 2, updated: 1 },
      submitted_to_zeus: false,
      simulation_started: false,
      local_sync: { status: "not_synchronized" },
    });
    const screenPrepared = parseSmokeLifecycle({
      ...smokeLifecycle,
      campaign: { ...smokeLifecycle.campaign, stage: "screen" },
      lifecycle: "screen_prepared",
      next_action: "none",
    });
    const props = {
      visible: true,
      canSubmit: false,
      submissionState: "idle" as const,
      submissionPreview: null,
      submissionResult: null,
      submissionError: "",
      lifecycleCheck: "ready" as const,
      lifecycleError: "",
      screeningState: "success" as const,
      screeningPreview: null,
      screeningResult,
      screeningError: "",
      onPreviewSubmission: noop,
      onConfirmSubmission: noop,
      onResetSubmission: noop,
      onRefreshLifecycle: noop,
      onPreviewScreening: noop,
      onConfirmScreening: noop,
      onResetScreening: noop,
      onViewJobs: noop,
    };
    const view = render(<SmokeFlow {...props} lifecycle={smokeLifecycle} />);
    const receipt = screen.getByRole("status");
    expect(receipt).toHaveFocus();
    expect(receipt).toHaveTextContent(
      "No Screening job was submitted and no simulation started.",
    );

    view.rerender(<SmokeFlow {...props} lifecycle={screenPrepared} />);
    expect(screen.getByText("Screening prepared on Zeus")).toBeVisible();
    expect(receipt).toHaveFocus();

    view.rerender(<SmokeFlow {...props} lifecycle={null} />);
    expect(screen.getByText("Screening prepared on Zeus")).toBeVisible();
    expect(receipt).toHaveFocus();
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

  it("keeps the submitted Refinement receipt visible and focused after its status snapshot clears", () => {
    const rounds = [1, 2, 3, 4].map((round) => ({
      round: round as 1 | 2 | 3 | 4,
      job_id: `${round}[].zeus-master`,
      depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master`,
    }));
    const status = parseRefinementChainStatus({
      ...chainStatus,
      chain: {
        status: "submitted",
        dependency: "afterok",
        rounds: rounds.map((round) => ({ ...round, state: "submitted" })),
      },
      next_action: "none",
    });
    const result = parseRefinementSubmissionResult({
      status: "submitted",
      campaign_id: "c",
      stage: "refine",
      chain: { status: "submitted", rounds },
      submitted_at: "2026-10-09T10:05:00Z",
      local_sync: { status: "not_synchronized" },
    });
    const props = {
      visible: true,
      check: "ready" as const,
      state: "submitted" as const,
      preview: null,
      result,
      error: "",
      onRefresh: noop,
      onPreview: noop,
      onConfirm: noop,
      onReset: noop,
      onViewJobs: noop,
    };
    const view = render(<RefinementFlow {...props} status={status} />);
    const receipt = screen
      .getByText("All four Zeus acknowledgements were recorded. Later rounds wait for the previous round to succeed.")
      .closest('[role="status"]');
    expect(receipt).toHaveFocus();
    expect(receipt).toHaveTextContent(
      "no action is needed and it is safe to close this application",
    );

    view.rerender(<RefinementFlow {...props} status={null} />);
    expect(screen.getByText("Refinement chain submitted")).toBeVisible();
    expect(receipt).toHaveFocus();
  });

  it("recovers the complete submitted Refinement receipt from authoritative status without an in-memory result", () => {
    const status = parseRefinementChainStatus({
      ...chainStatus,
      chain: {
        status: "submitted",
        dependency: "afterok",
        rounds: [1, 2, 3, 4].map((round) => ({
          round,
          state: "submitted",
          job_id: `${round}[].zeus-master`,
          depends_on_job_id:
            round === 1 ? null : `${round - 1}[].zeus-master`,
        })),
      },
      next_action: "none",
    });
    render(
      <RefinementFlow
        visible
        status={status}
        check="ready"
        state="submitted"
        preview={null}
        result={null}
        error=""
        onRefresh={noop}
        onPreview={noop}
        onConfirm={noop}
        onReset={noop}
        onViewJobs={noop}
      />,
    );

    const receipt = screen
      .getByText(
        "All four Zeus acknowledgements were recorded. Later rounds wait for the previous round to succeed.",
      )
      .closest('[role="status"]');
    expect(receipt).toHaveFocus();
    expect(within(receipt as HTMLElement).getAllByRole("listitem")).toHaveLength(
      4,
    );
    expect(within(receipt as HTMLElement).getAllByRole("listitem")[0]).toHaveTextContent(
      "Round 1: 1[].zeus-master",
    );
    expect(within(receipt as HTMLElement).getAllByRole("listitem")[1]).toHaveTextContent(
      "Round 2: 2[].zeus-master · afterok 1[].zeus-master",
    );
    expect(within(receipt as HTMLElement).getAllByRole("listitem")[2]).toHaveTextContent(
      "Round 3: 3[].zeus-master · afterok 2[].zeus-master",
    );
    expect(within(receipt as HTMLElement).getAllByRole("listitem")[3]).toHaveTextContent(
      "Round 4: 4[].zeus-master · afterok 3[].zeus-master",
    );
    expect(receipt).toHaveTextContent(
      "No later campaign stage was submitted. Zeus runs independently; no action is needed and it is safe to close this application.",
    );
    expect(
      screen.queryByRole("button", { name: "Review Refinement submission" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /^Submit four Refinement rounds$/,
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps a blocked Refinement outcome focused when its durable receipt disappears", () => {
    const partial = parseRefinementChainStatus({
      ...chainStatus,
      chain: {
        status: "partial",
        dependency: "afterok",
        rounds: [
          { round: 1, state: "submitted", job_id: "1[].zeus-master", depends_on_job_id: null },
          { round: 2, state: "not_submitted", job_id: null, depends_on_job_id: null },
          { round: 3, state: "not_submitted", job_id: null, depends_on_job_id: null },
          { round: 4, state: "not_submitted", job_id: null, depends_on_job_id: null },
        ],
      },
      next_action: "inspect_zeus",
    });
    const props = {
      visible: true,
      check: "ready" as const,
      state: "blocked" as const,
      preview: null,
      result: null,
      error: "Automatic retry is blocked.",
      onRefresh: noop,
      onPreview: noop,
      onConfirm: noop,
      onReset: noop,
      onViewJobs: noop,
    };
    const view = render(<RefinementFlow {...props} status={partial} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveFocus();

    view.rerender(<RefinementFlow {...props} status={null} check="error" />);
    expect(alert).toBeVisible();
    expect(alert).toHaveFocus();
    expect(screen.getByRole("button", { name: "View Zeus jobs" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Review again" })).not.toBeInTheDocument();
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

  it("keeps terminal Confirmation authority focused when lifecycle evidence disappears and refresh fails", () => {
    const props = {
      visible: true,
      state: "terminal" as const,
      preview: null,
      result: null,
      error: "The Confirmation outcome requires manual verification.",
      onRefresh: noop,
      onPreview: noop,
      onConfirm: noop,
      onReset: noop,
      onViewJobs: noop,
    };
    const view = render(
      <ConfirmationStage
        {...props}
        lifecycle={refinementLifecycle}
        lifecycleCheck="ready"
      />,
    );
    const terminalAlert = screen
      .getByText("Confirmation state needs manual verification")
      .closest('[role="alert"]');
    expect(terminalAlert).toHaveFocus();

    view.rerender(
      <ConfirmationStage
        {...props}
        lifecycle={null}
        lifecycleCheck="error"
      />,
    );

    expect(terminalAlert).toBeVisible();
    expect(terminalAlert).toHaveFocus();
    expect(terminalAlert).toHaveTextContent(
      "Automatic retry is blocked even if a fresh status check is unavailable.",
    );
    expect(screen.getByRole("button", { name: "View Zeus jobs" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Review again" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review Confirmation preparation" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the Confirmation preparation outcome visible and focused after lifecycle advances or clears", () => {
    const result = parseConfirmationResult({
      status: "confirmation_prepared",
      campaign_id: "c",
      stage: "confirmation",
      artifacts: { created: 3, updated: 1 },
      submitted_to_zeus: false,
      simulation_started: false,
      local_sync: { status: "not_synchronized" },
    });
    const prepared = parseRefinementLifecycle({
      ...refinementLifecycle,
      campaign: { ...refinementLifecycle.campaign, stage: "confirmation" },
      chain: { ...refinementLifecycle.chain, status: "confirmation_prepared" },
      next_action: "none",
    });
    const props = {
      visible: true,
      lifecycleCheck: "ready" as const,
      state: "success" as const,
      preview: null,
      result,
      error: "",
      onRefresh: noop,
      onPreview: noop,
      onConfirm: noop,
      onReset: noop,
      onViewJobs: noop,
    };
    const view = render(
      <ConfirmationStage {...props} lifecycle={refinementLifecycle} />,
    );
    const receipt = screen
      .getByText("Confirmation prepared on Zeus")
      .closest('[role="status"]');
    expect(receipt).toHaveFocus();
    expect(receipt).toHaveTextContent(
      "No Confirmation job was submitted and no simulation started.",
    );

    view.rerender(<ConfirmationStage {...props} lifecycle={prepared} />);
    expect(screen.getByText("Confirmation prepared on Zeus")).toBeVisible();
    expect(receipt).toHaveFocus();

    view.rerender(<ConfirmationStage {...props} lifecycle={null} />);
    expect(screen.getByText("Confirmation prepared on Zeus")).toBeVisible();
    expect(receipt).toHaveFocus();
  });
});

describe("stage action visibility matrix", () => {
  const buttonNames = () => screen.getAllByRole("button").map((button) => button.textContent?.trim()).sort();
  const smokeProps = {
    visible: true,
    canSubmit: false,
    submissionState: "idle" as const,
    submissionPreview: null,
    submissionResult: null,
    submissionError: "",
    lifecycleCheck: "ready" as const,
    lifecycleError: "",
    screeningState: "idle" as const,
    screeningPreview: null,
    screeningResult: null,
    screeningError: "",
    onPreviewSubmission: noop,
    onConfirmSubmission: noop,
    onResetSubmission: noop,
    onRefreshLifecycle: noop,
    onPreviewScreening: noop,
    onConfirmScreening: noop,
    onResetScreening: noop,
    onViewJobs: noop,
  };

  it.each([
    ["queued", "queued", "queued", "not_ready", "wait", ["Refresh smoke status"]],
    ["running", "running", "running", "not_ready", "wait", ["Refresh smoke status"]],
    ["awaiting outputs", "awaiting_outputs", "completed_success", "not_ready", "wait", ["Refresh smoke status"]],
    ["held", "held_attention", "held_attention", "not_ready", "inspect_on_zeus", ["Refresh smoke status", "View Zeus jobs"]],
    ["failed", "failed", "completed_failed", "not_ready", "inspect_on_zeus", ["Refresh smoke status", "View Zeus jobs"]],
    ["invalid outputs", "outputs_invalid", "completed_success", "invalid", "inspect_on_zeus", ["Refresh smoke status", "View Zeus jobs"]],
    ["unknown", "unknown", "unknown", "not_ready", "inspect_on_zeus", ["Refresh smoke status", "View Zeus jobs"]],
    ["ready", "ready_to_prepare_screen", "completed_success", "valid", "review_screening_preparation", ["Refresh smoke status", "Review screening preparation"]],
    ["success", "screen_prepared", "completed_success", "valid", "none", ["Refresh smoke status"]],
  ] as const)("shows only safe Smoke actions for %s", (_label, lifecycle, schedulerState, validation, nextAction, expectedButtons) => {
    const raw = {
      ...smokeLifecycle,
      campaign: { ...smokeLifecycle.campaign, stage: lifecycle === "screen_prepared" ? "screen" : "smoke" },
      scheduler: {
        state: schedulerState,
        raw_state: schedulerState === "queued" ? "Q" : schedulerState === "running" ? "R" : schedulerState === "held_attention" ? "H" : schedulerState === "unknown" ? "?" : "F",
        exit_status: ["queued", "running", "held_attention", "unknown"].includes(schedulerState) ? null : schedulerState === "completed_failed" ? 1 : 0,
      },
      validation: validation === "valid" ? smokeLifecycle.validation : { status: validation, points: [], artifact_count: 0 },
      lifecycle,
      next_action: nextAction,
    };
    const value = parseSmokeLifecycle(raw);
    render(<SmokeFlow {...smokeProps} lifecycle={value} />);
    expect(buttonNames()).toEqual([...expectedButtons].sort());
  });

  const screeningProps = {
    visible: true,
    evidenceFresh: true,
    smokeCheck: "ready" as const,
    submitState: "submitted" as const,
    submitPreview: null,
    submitResult: null,
    submitError: "",
    lifecycleCheck: "ready" as const,
    lifecycleError: "",
    prepareState: "idle" as const,
    preparePreview: null,
    prepareResult: null,
    prepareError: "",
    onRefreshSmoke: noop,
    onPreviewSubmit: noop,
    onConfirmSubmit: noop,
    onResetSubmit: noop,
    onRefreshLifecycle: noop,
    onPreviewPrepare: noop,
    onConfirmPrepare: noop,
    onResetPrepare: noop,
    onViewJobs: noop,
  };

  it.each([
    ["running", "screen_running", "running", "not_ready", "wait", ["Refresh Screening status"]],
    ["held", "screen_held", "held", "not_ready", "inspect_zeus", ["Refresh Screening status", "View Zeus jobs"]],
    ["unknown", "screen_status_unknown", "unknown", "not_ready", "inspect_zeus", ["Refresh Screening status", "View Zeus jobs"]],
    ["invalid outputs", "outputs_invalid", "completed_success", "invalid", "inspect_zeus", ["Refresh Screening status", "View Zeus jobs"]],
    ["ready", "ready_to_prepare_refinement", "completed_success", "valid", "review_refinement_preparation", ["Refresh Screening status", "Review Refinement preparation"]],
    ["success", "refinement_prepared", "completed_success", "valid", "none", ["Refresh Screening status"]],
  ] as const)("shows only safe Screening actions for %s", (_label, lifecycle, schedulerState, validation, nextAction, expectedButtons) => {
    const active = schedulerState === "running" ? { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 }
      : schedulerState === "held" ? { queued: 0, running: 0, held: 3, succeeded: 0, failed: 0 }
      : schedulerState === "unknown" ? { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 }
      : { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 };
    const raw = {
      source: "zeus" as const,
      queried_at: "2026-10-09T10:00:00Z",
      campaign: { id: "c", name: "C", stage: lifecycle === "refinement_prepared" ? "refine" as const : "screen" as const },
      submission: { job_id: "2[].zeus-master" },
      scheduler: { state: schedulerState, raw_state: schedulerState === "running" ? "R" : schedulerState === "held" ? "H" : schedulerState === "unknown" ? "?" : "F", exit_status: schedulerState === "completed_success" ? 0 : null, task_count: 3, counts: active },
      validation: validation === "valid" ? { status: "valid" as const, completed_trials: 51, expected_trials: 51, candidate_count: 3 } : { status: validation, completed_trials: 0, expected_trials: 51, candidate_count: 0 },
      lifecycle,
      next_action: nextAction,
    };
    const value = parseScreeningLifecycle(raw);
    render(<ScreeningFlow {...screeningProps} lifecycle={value} />);
    expect(buttonNames()).toEqual([...expectedButtons].sort());
  });

  it.each([
    ["ready", "not_submitted", ["not_submitted", "not_submitted", "not_submitted", "not_submitted"], ["Refresh chain status", "Review Refinement submission"]],
    ["partial", "partial", ["submitted", "not_submitted", "not_submitted", "not_submitted"], ["Refresh chain status", "View Zeus jobs"]],
    ["unknown outcome", "outcome_unknown", ["submitted", "unknown", "not_submitted", "not_submitted"], ["Refresh chain status", "View Zeus jobs"]],
    ["success", "submitted", ["submitted", "submitted", "submitted", "submitted"], ["Refresh chain status", "View in Zeus jobs"]],
  ] as const)("shows only safe Refinement-chain actions for %s", (_label, status, states, expectedButtons) => {
    let previousId: string | null = null;
    const rounds = states.map((state, index) => {
      const jobId = state === "submitted" ? `${index + 1}[].zeus-master` : null;
      const round = {
        round: (index + 1) as 1 | 2 | 3 | 4,
        state,
        job_id: jobId,
        depends_on_job_id: state === "submitted" || state === "unknown" ? (index === 0 ? null : previousId) : null,
      };
      if (jobId) previousId = jobId;
      return round;
    });
    const value = parseRefinementChainStatus({
      ...chainStatus,
      chain: { ...chainStatus.chain, status, rounds },
      next_action: status === "not_submitted" ? "review_submission" : status === "submitted" ? "none" : "inspect_zeus",
    });
    render(
      <RefinementFlow
        visible
        status={value}
        check="ready"
        state={status === "partial" || status === "outcome_unknown" ? "blocked" : status === "submitted" ? "submitted" : "idle"}
        preview={null}
        result={null}
        error=""
        onRefresh={noop}
        onPreview={noop}
        onConfirm={noop}
        onReset={noop}
        onViewJobs={noop}
      />,
    );
    expect(buttonNames()).toEqual([...expectedButtons].sort());
  });

  it.each([
    ["running", "running", "running", "not_ready", "wait", ["Refresh Refinement status"]],
    ["held", "held", "held", "not_ready", "inspect_zeus", ["Refresh Refinement status", "View Zeus jobs"]],
    ["unknown", "status_unknown", "unknown", "not_ready", "inspect_zeus", ["Refresh Refinement status", "View Zeus jobs"]],
    ["invalid outputs", "outputs_invalid", "completed_success", "invalid", "inspect_zeus", ["Refresh Refinement status", "View Zeus jobs"]],
    ["ready", "ready_to_prepare_confirmation", "completed_success", "valid", "review_confirmation_preparation", ["Refresh Refinement status", "Review Confirmation preparation"]],
    ["success", "confirmation_prepared", "completed_success", "valid", "none", ["Refresh Refinement status"]],
  ] as const)("shows only safe Confirmation-preparation actions for %s", (_label, status, activeState, validation, nextAction, expectedButtons) => {
    const rounds = refinementLifecycle.chain.rounds.map((round, index) => {
      const state = index === 0 ? activeState : activeState === "completed_success" ? "completed_success" : "queued";
      const counts = state === "running" ? { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 }
        : state === "held" ? { queued: 0, running: 0, held: 3, succeeded: 0, failed: 0 }
        : state === "unknown" ? { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 }
        : state === "queued" ? { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 }
        : { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 };
      return { ...round, scheduler: { ...round.scheduler, state, counts } };
    });
    const raw = {
      ...refinementLifecycle,
      campaign: { ...refinementLifecycle.campaign, stage: status === "confirmation_prepared" ? "confirmation" : "refine" },
      chain: { ...refinementLifecycle.chain, status, rounds },
      validation: validation === "valid" ? refinementLifecycle.validation : { status: validation, completed_trials: 0, expected_trials: 30, candidate_count: 0 },
      next_action: nextAction,
    };
    const lifecycle = parseRefinementLifecycle(raw);
    render(<ConfirmationStage visible lifecycle={lifecycle} lifecycleCheck="ready" state={status === "confirmation_prepared" ? "success" : "idle"} preview={null} result={null} error="" onRefresh={noop} onPreview={noop} onConfirm={noop} onReset={noop} onViewJobs={noop} />);
    expect(buttonNames()).toEqual([...expectedButtons].sort());
  });
});


it("shows the reviewed heavy-stage reservation and per-family concurrency cap", () => {
  render(<ReviewedResources resources={{array:{ncpus_per_task:100,memory_gb_per_task:64,walltime:"01:00:00",vnode:"gd002",array_throttle:1},merge:{ncpus:1,memory_gb:4,walltime:"01:00:00",vnode:"gd002"}}} />);
  expect(screen.getByText("100 CPUs · 64 GiB · 01:00:00 · Node gd002")).toBeVisible();
  expect(screen.getByText("Maximum concurrent array tasks per family").nextElementSibling).toHaveTextContent(/^1$/);
});

it("labels the actual 8589934592-byte reservation as 8 GiB without changing resource values",()=>{
 const job={cores_per_task:10,memory_per_task_bytes:8_589_934_592,walltime_seconds:3600};
 render(<div data-testid="binary-reservation"><JobResources job={job}/></div>);
 expect(screen.getByTestId("binary-reservation")).toHaveTextContent("10 cores · 8 GiB · 1 h");
 expect(screen.getByTestId("binary-reservation")).not.toHaveTextContent(/8 GB/);
 expect(job).toEqual({cores_per_task:10,memory_per_task_bytes:8_589_934_592,walltime_seconds:3600});
});

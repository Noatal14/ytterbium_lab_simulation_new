import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  parseConfirmationSubmissionPreview,
  parseConfirmationSubmissionResult,
  parseConfirmationSubmissionStatus,
} from "../api/schema/domain";
import { ConfirmationSubmissionView } from "../features/campaign/confirmation/ConfirmationSubmissionView";

const previewValue = {
  preview_token: "review-token",
  expires_in_seconds: 300,
  campaign: {
    id: "campaign-id",
    name: "Campaign",
    git_commit: "a".repeat(40),
    s0_values: [1.3],
  },
  stage: { id: "confirmation", label: "Confirmation" },
  job: {
    file: "jobs/04_confirmation.pbs",
    kind: "array",
    task_count: 5,
    array_throttle: 3,
    queue: "zeus_combined_q",
    cores_per_task: 200,
    memory_per_task_bytes: 68_719_476_736,
    walltime_seconds: 36_000,
  },
  remote: {
    host: "zeus.technion.ac.il",
    project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
    commit: "a".repeat(40),
    branch: "main",
    dirty: false,
  },
  effects: {
    submit_confirmation: true,
    start_simulation: true,
    submit_later_stages: false,
    modify_campaign_files: false,
    record_submission_receipt: true,
  },
  local_sync: { status: "not_synchronized" },
};

describe("Confirmation submission contract", () => {
  it("strictly binds the frozen array shape and rejects extra or inconsistent data", () => {
    expect(
      parseConfirmationSubmissionPreview(previewValue).job.task_count,
    ).toBe(5);
    expect(() =>
      parseConfirmationSubmissionPreview({ ...previewValue, secret: true }),
    ).toThrow();
    expect(() =>
      parseConfirmationSubmissionPreview({
        ...previewValue,
        job: { ...previewValue.job, task_count: 6 },
      }),
    ).toThrow();
    expect(() =>
      parseConfirmationSubmissionStatus({
        source: "zeus",
        queried_at: "2026-10-08T00:00:00Z",
        campaign: {
          id: "campaign-id",
          name: "Campaign",
          stage: "confirmation",
        },
        submission: { status: "running", job_id: null },
        next_action: "wait",
        local_sync: { status: "not_synchronized" },
      }),
    ).toThrow();
    expect(() =>
      parseConfirmationSubmissionResult({
        status: "submitted",
        campaign_id: "campaign-id",
        stage: "confirmation",
        job_id: "not-an-array-job",
        submitted_at: "2026-10-08T00:00:00Z",
        local_sync: { status: "not_synchronized" },
      }),
    ).toThrow();
  });

  it("requires an explicit final action and explains its closed scope", () => {
    const confirm = vi.fn();
    render(
      <ConfirmationSubmissionView
        enabled
        state="review"
        status={null}
        preview={parseConfirmationSubmissionPreview(previewValue)}
        result={null}
        error=""
        onRefresh={vi.fn()}
        onReview={vi.fn()}
        onConfirm={confirm}
        onReset={vi.fn()}
        onViewJobs={vi.fn()}
      />,
    );
    expect(
      screen.getByText(/does not submit Sensitivity or Production/i),
    ).toBeVisible();
    expect(screen.getByText(/not the sealed final performance estimate/i)).toBeVisible();
    expect(document.activeElement).toHaveTextContent("Submit Confirmation array");
    expect(screen.getByText(/5 · throttle 3/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Submit Confirmation to Zeus" }),
    );
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("blocks retry and directs unknown outcomes to manual inspection", () => {
    render(
      <ConfirmationSubmissionView
        enabled
        state="terminal"
        status={null}
        preview={null}
        result={null}
        error="The scheduler outcome is unknown. Do not submit again."
        onRefresh={vi.fn()}
        onReview={vi.fn()}
        onConfirm={vi.fn()}
        onReset={vi.fn()}
        onViewJobs={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Do not submit again");
    expect(document.activeElement).toBe(screen.getByRole("alert"));
    expect(
      screen.getByRole("button", { name: "View Zeus jobs" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /submit confirmation/i }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["queued", "wait"],
    ["running", "wait"],
    ["held", "inspect_zeus"],
    ["completed_success", "validate_outputs"],
    ["completed_failed", "inspect_zeus"],
    ["status_unknown", "inspect_zeus"],
  ])("strictly accepts the tracked %s scheduler lifecycle", (status, nextAction) => {
    expect(parseConfirmationSubmissionStatus({
      source: "zeus", queried_at: "2026-10-08T00:00:00Z",
      campaign: { id: "campaign-id", name: "Campaign", stage: "confirmation" },
      submission: { status, job_id: "123[].zeus-master" },
      next_action: nextAction, local_sync: { status: "not_synchronized" },
    }).submission.status).toBe(status);
  });
});

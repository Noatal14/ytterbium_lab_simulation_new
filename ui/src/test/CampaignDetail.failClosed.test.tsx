import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CampaignDetail } from "../features/campaign/CampaignDetail";
import { RefinementLifecycleApiError, RefinementSubmissionApiError } from "../api/clients/refinement";
import { ScreeningLifecycleApiError, ScreeningSubmissionApiError } from "../api/clients/screening";
import { SmokeLifecycleApiError, SubmissionApiError } from "../api/clients/smoke";

vi.mock("../features/campaign/TransferStage", () => ({ TransferStage: () => null }));
vi.mock("../features/campaign/SmokeStage", () => ({ SmokePointsTable: () => null }));
vi.mock("../features/campaign/ScreeningStage", () => ({ ScreeningFacts: () => null }));
vi.mock("../features/campaign/RefinementStage", () => ({ RefinementReceipt: () => null }));

vi.mock("../features/campaign/SmokeFlow", () => ({
  SmokeFlow: (props: any) => <section>
    <button onClick={props.onRefreshLifecycle}>refresh smoke</button>
    <button onClick={props.onPreviewSubmission}>review smoke</button>
    {props.submissionState === "review" && <button onClick={props.onConfirmSubmission}>confirm smoke</button>}
    <button onClick={props.onPreviewScreening}>review screening preparation</button>
    {props.screeningState === "review" && <button onClick={props.onConfirmScreening}>confirm screening preparation</button>}
    <output data-testid="smoke-submission-state">{props.submissionState}</output>
    <output data-testid="screening-preparation-state">{props.screeningState}</output>
  </section>,
}));

vi.mock("../features/campaign/ScreeningFlow", () => ({
  ScreeningFlow: (props: any) => <section>
    <button onClick={props.onRefreshLifecycle}>refresh screening</button>
    <button onClick={props.onPreviewSubmit}>review screening submission</button>
    {props.submitState === "review" && <button onClick={props.onConfirmSubmit}>confirm screening submission</button>}
    <button onClick={props.onPreviewPrepare}>review refinement preparation</button>
    {props.prepareState === "review" && <button onClick={props.onConfirmPrepare}>confirm refinement preparation</button>}
    <output data-testid="screening-submission-state">{props.submitState}</output>
    <output data-testid="refinement-preparation-state">{props.prepareState}</output>
  </section>,
}));

vi.mock("../features/campaign/RefinementFlow", () => ({
  RefinementFlow: (props: any) => <section>
    <button onClick={props.onRefresh}>refresh refinement chain</button>
    <button onClick={props.onPreview}>review refinement chain</button>
    {props.state === "review" && <button onClick={props.onConfirm}>confirm refinement chain</button>}
    <output data-testid="refinement-chain-state">{props.state}</output>
  </section>,
}));

vi.mock("../features/campaign/ConfirmationStage", () => ({
  ConfirmationStage: (props: any) => <section>
    <button onClick={props.onRefresh}>refresh refinement lifecycle</button>
    <button onClick={props.onPreview}>review confirmation preparation</button>
    {props.state === "review" && <button onClick={props.onConfirm}>confirm confirmation preparation</button>}
    <output data-testid="confirmation-preparation-state">{props.state}</output>
  </section>,
}));

const campaign = {
  id: "campaign", name: "Campaign", family: "mot_2d", stage: "smoke", path: "data/optimization/mot_2d/campaign",
  trust: "trusted-current", scientific_role: "campaign", progress: [], warnings: [], next_plan: null,
  remote_preparation: { status: "ready" },
};
const profile = { username: "tal.noa", project_directory: "/home/tal.noa/ytterbium_lab_simulation_new" };
const preview = { preview_token: "token" };

function renderDetail(target: string) {
  const unknown = (kind: string) => {
    if (target !== kind) return Promise.resolve({});
    const ErrorType = {
      smoke: SubmissionApiError,
      screenPrepare: SmokeLifecycleApiError,
      screenSubmit: ScreeningSubmissionApiError,
      refinePrepare: ScreeningLifecycleApiError,
      refineChain: RefinementSubmissionApiError,
      confirmation: RefinementLifecycleApiError,
    }[kind]!;
    return Promise.reject(new ErrorType("internal_secret_code", "Internal details must not permit a retry."));
  };
  render(<CampaignDetail
    campaign={campaign as any}
    onBack={vi.fn()}
    transfer={{ preview: vi.fn(), confirm: vi.fn() } as any}
    submission={{ preview: async () => preview, confirm: () => unknown("smoke") } as any}
    lifecycle={{ status: async () => ({
      source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: target === "screenPrepare" ? "smoke" : "screen" },
      submission: { job_id: "1.zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 },
      validation: { status: "valid", points: [], artifact_count: 0 }, lifecycle: target === "screenPrepare" ? "ready_to_prepare_screen" : "screen_prepared", next_action: target === "screenPrepare" ? "review_screening_preparation" : "none",
    }), preview: async () => preview, confirm: () => unknown("screenPrepare") } as any}
    screeningSubmission={{ preview: async () => preview, confirm: () => unknown("screenSubmit") } as any}
    screeningLifecycle={{ status: async () => ({ source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "screen" }, submission: { job_id: "2[].zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0, task_count: 3, counts: { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 } }, validation: { status: "valid", completed_trials: 51, expected_trials: 51, candidate_count: 3 }, lifecycle: "ready_to_prepare_refinement", next_action: "review_refinement_preparation" }), preview: async () => preview, confirm: () => unknown("refinePrepare") } as any}
    refinementSubmission={{ status: async () => ({ source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "refine" }, chain: { status: "not_submitted", dependency: "afterok", rounds: [] }, next_action: "review_submission", local_sync: { status: "not_synchronized" } }), preview: async () => preview, confirm: () => unknown("refineChain") } as any}
    refinementLifecycle={{ status: async () => ({ source: "zeus", queried_at: "2026-10-09T10:00:00Z", campaign: { id: "campaign", name: "Campaign", stage: "refine" }, chain: { status: "ready_to_prepare_confirmation", rounds: [] }, validation: { status: "valid", completed_trials: 30, expected_trials: 30, candidate_count: 5 }, next_action: "review_confirmation_preparation", local_sync: { status: "not_synchronized" } }), preview: async () => preview, confirm: () => unknown("confirmation") } as any}
    zeusSnapshot={{ profile } as any}
    onConnectZeus={vi.fn()}
    onViewJobs={vi.fn()}
  />);
}

describe("state-changing confirmations fail closed on unknown typed server errors", () => {
  it.each([
    ["smoke", null, "review smoke", "confirm smoke", "smoke-submission-state", "terminal"],
    ["screenPrepare", "refresh smoke", "review screening preparation", "confirm screening preparation", "screening-preparation-state", "terminal"],
    ["screenSubmit", "refresh smoke", "review screening submission", "confirm screening submission", "screening-submission-state", "terminal"],
    ["refinePrepare", "refresh screening", "review refinement preparation", "confirm refinement preparation", "refinement-preparation-state", "terminal"],
    ["refineChain", "refresh refinement chain", "review refinement chain", "confirm refinement chain", "refinement-chain-state", "blocked"],
    ["confirmation", "refresh refinement lifecycle", "review confirmation preparation", "confirm confirmation preparation", "confirmation-preparation-state", "terminal"],
  ])("blocks %s and retires its reviewed confirmation", async (target, refreshLabel, reviewLabel, confirmLabel, stateId, blockedState) => {
    const user = userEvent.setup();
    renderDetail(target);
    if (refreshLabel) await user.click(screen.getByRole("button", { name: refreshLabel }));
    await user.click(screen.getByRole("button", { name: reviewLabel }));
    const confirmButton = await screen.findByRole("button", { name: confirmLabel });
    await user.click(confirmButton);
    await waitFor(() => expect(screen.getByTestId(stateId)).toHaveTextContent(blockedState));
    expect(screen.queryByRole("button", { name: confirmLabel })).not.toBeInTheDocument();
  });
});

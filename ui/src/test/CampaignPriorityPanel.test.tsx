import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CampaignPriorityPanel } from "../features/campaign/CampaignPriorityPanel";
import { parseRefinementChainStatus, parseRefinementLifecycle, parseScreeningLifecycle, parseSmokeLifecycle, parseSmokeSubmissionResult } from "../api/schema/domain";
import { campaignFixture } from "./campaignFixture";
import type { Campaign } from "../api/clients/campaign";

const smoke = parseSmokeLifecycle({ source: "zeus", queried_at: "2026-10-10T10:00:00Z", campaign: { id: campaignFixture.id, name: campaignFixture.name, stage: "screen" }, submission: { job_id: "1.zeus-master" }, scheduler: { state: "completed_success", raw_state: "F", exit_status: 0 }, validation: { status: "valid", points: [{ s0: 1.3, captured: 1, input: 2, efficiency: 0.5 }], artifact_count: 3 }, lifecycle: "screen_prepared", next_action: "none" });
function screeningFixture(lifecycle: "screen_queued" | "screen_running" | "screen_held" | "screen_failed" | "screen_status_unknown" | "awaiting_outputs" | "outputs_invalid" | "ready_to_prepare_refinement" | "refinement_prepared") {
  const map = {
    screen_queued: ["queued", { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 }, "not_ready", "wait", "screen"],
    screen_running: ["running", { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 }, "not_ready", "wait", "screen"],
    screen_held: ["held", { queued: 0, running: 0, held: 3, succeeded: 0, failed: 0 }, "not_ready", "inspect_zeus", "screen"],
    screen_failed: ["completed_failed", { queued: 0, running: 0, held: 0, succeeded: 0, failed: 3 }, "not_ready", "inspect_zeus", "screen"],
    screen_status_unknown: ["unknown", { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 }, "not_ready", "inspect_zeus", "screen"],
    awaiting_outputs: ["completed_success", { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 }, "not_ready", "wait", "screen"],
    outputs_invalid: ["completed_success", { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 }, "invalid", "inspect_zeus", "screen"],
    ready_to_prepare_refinement: ["completed_success", { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 }, "valid", "review_refinement_preparation", "screen"],
    refinement_prepared: ["completed_success", { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 }, "valid", "none", "refine"],
  }[lifecycle] as [any, any, any, any, any];
  const valid = map[2] === "valid";
  return parseScreeningLifecycle({ source: "zeus", queried_at: "2026-10-10T11:00:00Z", campaign: { id: campaignFixture.id, name: campaignFixture.name, stage: map[4] }, submission: { job_id: "2[].zeus-master" }, scheduler: { state: map[0], raw_state: "X", exit_status: map[0] === "completed_success" ? 0 : map[0] === "completed_failed" ? 1 : null, task_count: 3, counts: map[1] }, validation: { status: map[2], completed_trials: valid ? 51 : 0, expected_trials: 51, candidate_count: valid ? 3 : 0 }, lifecycle, next_action: map[3] });
}
function chainFixture(status: "not_submitted" | "submitting" | "submitted" | "partial" | "outcome_unknown") {
  const states = status === "submitted" ? ["submitted", "submitted", "submitted", "submitted"] : status === "partial" ? ["submitted", "not_submitted", "not_submitted", "not_submitted"] : status === "submitting" ? ["pending", "not_submitted", "not_submitted", "not_submitted"] : status === "outcome_unknown" ? ["unknown", "not_submitted", "not_submitted", "not_submitted"] : ["not_submitted", "not_submitted", "not_submitted", "not_submitted"];
  let previous: string | null = null;
  const rounds = states.map((state, index) => { const submitted = state === "submitted"; const uncertain = state === "pending" || state === "unknown"; const job = submitted || uncertain ? `${index + 1}[].zeus-master` : null; const row = { round: index + 1, state, job_id: job, depends_on_job_id: submitted || uncertain ? previous : null }; if (submitted) previous = job; return row; });
  const action = status === "not_submitted" ? "review_submission" : status === "submitting" ? "wait" : status === "submitted" ? "none" : "inspect_zeus";
  return parseRefinementChainStatus({ source: "zeus", queried_at: "2026-10-10T12:00:00Z", campaign: { id: campaignFixture.id, name: campaignFixture.name, stage: "refine" }, chain: { status, dependency: "afterok", rounds }, next_action: action, local_sync: { status: "not_synchronized" } });
}
function confirmationFixture(status: "queued" | "running" | "held" | "failed" | "status_unknown" | "awaiting_outputs" | "outputs_invalid" | "ready_to_prepare_confirmation" | "confirmation_prepared") {
  const activeState = status === "queued" ? "queued" : status === "running" ? "running" : status === "held" ? "held" : status === "failed" ? "completed_failed" : status === "status_unknown" ? "unknown" : "completed_success";
  const rows = [1, 2, 3, 4].map((round) => { const state = round === 1 ? activeState : activeState === "completed_success" ? "completed_success" : "queued"; const counts = state === "queued" ? { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 } : state === "running" ? { queued: 0, running: 3, held: 0, succeeded: 0, failed: 0 } : state === "held" ? { queued: 0, running: 0, held: 3, succeeded: 0, failed: 0 } : state === "completed_failed" ? { queued: 0, running: 0, held: 0, succeeded: 0, failed: 3 } : state === "unknown" ? { queued: 3, running: 0, held: 0, succeeded: 0, failed: 0 } : { queued: 0, running: 0, held: 0, succeeded: 3, failed: 0 }; return { round, job_id: `${round}[].zeus-master`, depends_on_job_id: round === 1 ? null : `${round - 1}[].zeus-master`, scheduler: { state, task_count: 3, counts } }; });
  const valid = ["ready_to_prepare_confirmation", "confirmation_prepared"].includes(status); const invalid = status === "outputs_invalid";
  const action = ["queued", "running", "awaiting_outputs"].includes(status) ? "wait" : ["held", "failed", "status_unknown", "outputs_invalid"].includes(status) ? "inspect_zeus" : status === "ready_to_prepare_confirmation" ? "review_confirmation_preparation" : "none";
  return parseRefinementLifecycle({ source: "zeus", queried_at: "2026-10-10T13:00:00Z", campaign: { id: campaignFixture.id, name: campaignFixture.name, stage: status === "confirmation_prepared" ? "confirmation" : "refine" }, chain: { status, rounds: rows }, validation: { status: valid ? "valid" : invalid ? "invalid" : "not_ready", completed_trials: valid ? 30 : 0, expected_trials: 30, candidate_count: valid ? 5 : 0 }, next_action: action, local_sync: { status: "not_synchronized" } });
}
const screening = screeningFixture("ready_to_prepare_refinement");
const chain = chainFixture("not_submitted");
const confirmation = confirmationFixture("ready_to_prepare_confirmation");
const submission = parseSmokeSubmissionResult({ status: "submitted", campaign_id: campaignFixture.id, stage: "smoke", job_id: "1.zeus-master", submitted_at: "2026-10-10T09:00:00Z", later_stages_locked: true });
const base = { campaign: campaignFixture, transferState: "idle" as const, submissionState: "idle" as const, submissionResult: null, submissionError: "", submissionTerminalCode: null, remoteState: null, remoteEvidenceFresh: false, screenSubmitState: "idle" as const, screenState: null, chainStatus: null, refinementLifecycle: null, copyStatus: "", onCopyCommand: vi.fn() };

describe("CampaignPriorityPanel", () => {
  it("preserves stage precedence from Confirmation through Smoke", () => {
    const view = render(<CampaignPriorityPanel {...base} remoteState={smoke} screenState={screening} chainStatus={chain} refinementLifecycle={confirmation} />);
    expect(screen.getByRole("heading", { name: "Action required" })).toBeVisible(); expect(screen.getByText(/30 trials passed validation/)).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} screenState={screening} chainStatus={chain} />);
    expect(screen.getByText(/four-round chain is prepared/)).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} screenState={screening} />);
    expect(screen.getByText(/51 Screening trials and 3 selected candidates/)).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh />);
    expect(screen.getByText(/submission is ready for review/)).toBeVisible();
  });

  it("distinguishes fresh and synthetic screen-prepared evidence", () => {
    const view = render(<CampaignPriorityPanel {...base} remoteState={smoke} />);
    expect(screen.getByRole("heading", { name: "Refresh Zeus status" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh />);
    expect(screen.getByRole("heading", { name: "Action required" })).toBeVisible();
  });

  it("keeps authoritative Smoke content above local submission state", () => {
    render(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh submissionState="terminal" submissionError="local error" />);
    expect(screen.getByText(/screening files are ready on Zeus/)).toBeVisible(); expect(screen.queryByText("local error")).not.toBeInTheDocument();
  });

  it.each([["submitted", "No action needed"], ["terminal", "Check Zeus jobs before continuing"], ["unknown", "Check Zeus jobs before continuing"]] as const)("keeps Smoke content while Screening submission %s controls the heading", (state, heading) => {
    render(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh screenSubmitState={state} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    expect(screen.getByText(state === "submitted" ? "Screening has been submitted successfully." : "The screening files are ready on Zeus. No screening job was submitted and no simulation started.")).toBeVisible();
  });

  it("renders submitted Smoke job details without lifecycle evidence", () => {
    render(<CampaignPriorityPanel {...base} submissionState="submitted" submissionResult={submission} />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible(); expect(screen.getByText(/job 1.zeus-master/)).toBeVisible();
  });

  it("preserves command visibility, exact bytes, and copy status", () => {
    const onCopy = vi.fn(); render(<CampaignPriorityPanel {...base} onCopyCommand={onCopy} copyStatus="Command copied." />);
    expect(screen.getByText("qsub data/example.pbs")).toBeVisible(); fireEvent.click(screen.getByRole("button", { name: "Copy command" })); expect(onCopy).toHaveBeenCalledOnce(); expect(screen.getByRole("status")).toHaveTextContent("Command copied.");
  });

  it.each([
    ["submitted", "No action needed"], ["unknown", "Check Zeus jobs before continuing"], ["terminal", "Check Zeus jobs before continuing"],
  ] as const)("maps Screening submission %s without later evidence", (state, heading) => {
    render(<CampaignPriorityPanel {...base} screenSubmitState={state} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  });

  it("preserves Smoke submission and local fallback ordering", () => {
    const view = render(<CampaignPriorityPanel {...base} submissionState="terminal" submissionTerminalCode="already_submitted" />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} submissionState="terminal" submissionTerminalCode="submission_record_invalid" />);
    expect(screen.getByRole("heading", { name: "Check Zeus jobs before continuing" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} transferState="success" />);
    expect(screen.getByRole("heading", { name: "Smoke check ready for review" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, remote_preparation: { status: "unavailable", reason_code: "campaign-validation-failed" } }} />);
    expect(screen.getByRole("heading", { name: "Zeus preparation is unavailable" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, trust: "legacy-incomplete" }} />);
    expect(screen.getByRole("heading", { name: "Inspection only" })).toBeVisible();
  });

  it.each([
    ["not_submitted", "Action required"], ["submitting", "No action needed"], ["submitted", "No action needed"], ["partial", "Manual verification required"], ["outcome_unknown", "Manual verification required"],
  ] as const)("maps Refinement chain %s", (status, heading) => {
    render(<CampaignPriorityPanel {...base} chainStatus={chainFixture(status)} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  });

  it.each([
    ["screen_running", "No action needed"], ["awaiting_outputs", "No action needed"], ["ready_to_prepare_refinement", "Action required"], ["refinement_prepared", "Refinement is prepared"], ["screen_failed", "Screening needs attention"], ["outputs_invalid", "Screening needs attention"],
  ] as const)("maps Screening lifecycle %s", (lifecycle, heading) => {
    render(<CampaignPriorityPanel {...base} screenState={screeningFixture(lifecycle)} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  });

  it.each([
    ["running", "No action needed"], ["awaiting_outputs", "No action needed"], ["ready_to_prepare_confirmation", "Action required"], ["confirmation_prepared", "Confirmation is prepared"], ["failed", "Refinement needs attention"], ["status_unknown", "Refinement needs attention"],
  ] as const)("maps Confirmation lifecycle %s", (status, heading) => {
    render(<CampaignPriorityPanel {...base} refinementLifecycle={confirmationFixture(status)} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  });

  it("freezes blocked styling and the priority heading accessibility contract", () => {
    const failedSmoke = { ...smoke, campaign: { ...smoke.campaign, stage: "smoke" as const }, scheduler: { ...smoke.scheduler, state: "completed_failed" as const, exit_status: 1 }, validation: { status: "not_ready" as const, points: [], artifact_count: 0 }, lifecycle: "failed" as const, next_action: "inspect_on_zeus" as const };
    const view = render(<CampaignPriorityPanel {...base} remoteState={failedSmoke} />);
    let section = screen.getByRole("heading", { name: "Smoke check needs attention" }).closest("section");
    expect(section).toHaveClass("priority-panel--blocked"); expect(section).toHaveAttribute("aria-labelledby", "priority-heading"); expect(section?.querySelectorAll("#priority-heading")).toHaveLength(1);
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh />);
    section = screen.getByRole("heading", { name: "Action required" }).closest("section"); expect(section).not.toHaveClass("priority-panel--blocked");
    view.rerender(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, trust: "legacy-incomplete" }} />);
    expect(screen.getByRole("heading", { name: "Inspection only" }).closest("section")).toHaveClass("priority-panel--blocked");
    view.rerender(<CampaignPriorityPanel {...base} screenState={screeningFixture("screen_failed")} />);
    expect(screen.getByRole("heading", { name: "Screening needs attention" }).closest("section")).not.toHaveClass("priority-panel--blocked");
  });

  it.each([
    ["no plan", { next_plan: null }], ["untrusted", { trust: "legacy-incomplete" }], ["unavailable", { remote_preparation: { status: "unavailable", reason_code: "campaign-validation-failed" } }], ["smoke stage", { stage: "smoke" }], ["refine stage", { stage: "refine" }],
  ])("hides the command for %s", (_label, override) => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, ...override } as Campaign} />);
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
  });

  it.each(["submitted", "unknown", "terminal"] as const)("hides the command for Smoke submission state %s", (state) => {
    render(<CampaignPriorityPanel {...base} submissionState={state} />); expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
  });

  it("hides the command when authoritative Smoke state exists but preserves it for recoverable UI errors", () => {
    const view = render(<CampaignPriorityPanel {...base} remoteState={smoke} />); expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    view.rerender(<CampaignPriorityPanel {...base} submissionState="error" />); expect(screen.getByRole("button", { name: "Copy command" })).toBeVisible();
  });

  it("preserves both command scope labels", () => {
    const view = render(<CampaignPriorityPanel {...base} />); expect(screen.getByText("Remote submission · copy only")).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, next_plan: { ...campaignFixture.next_plan!, operation_scope: "local-mutation" } }} />);
    expect(screen.getByText("Local state change · copy only")).toBeVisible();
  });

  it("covers legacy and trusted-no-plan local fallbacks", () => {
    const view = render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, remote_preparation: { status: "legacy-local-only", reason_code: "fixed-checkout-path" } }} />);
    expect(screen.getByRole("heading", { name: "Recreate this campaign before using Zeus" })).toBeVisible(); expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, next_plan: null }} />);
    expect(screen.getByRole("heading", { name: "No action available" })).toBeVisible();
  });

  it("keeps dynamic authoritative Smoke and Screening facts", () => {
    const readySmoke = parseSmokeLifecycle({ ...smoke, campaign: { ...smoke.campaign, stage: "smoke" }, lifecycle: "ready_to_prepare_screen", next_action: "review_screening_preparation" });
    const view = render(<CampaignPriorityPanel {...base} remoteState={readySmoke} />);
    expect(screen.getByText(/All 3 smoke artifacts/)).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} screenState={screeningFixture("screen_running")} />);
    expect(screen.getByText(/Screening array/)).toHaveTextContent("2[].zeus-master");
  });
});

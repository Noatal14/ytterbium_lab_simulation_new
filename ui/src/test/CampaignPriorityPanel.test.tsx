import actualHeldInputs from "./fixtures/c56-final-inputs-held-status.json";
import { parseMot3DFinalValidationTransitionStatus } from "../api/clients/mot3dFinalValidationTransition";
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
    expect(screen.getByText(/Use Check Screening status to recover any existing job/)).toBeVisible();
  });

  it("distinguishes fresh and synthetic screen-prepared evidence", () => {
    const view = render(<CampaignPriorityPanel {...base} remoteState={smoke} />);
    expect(screen.getByRole("heading", { name: "Refresh Zeus status" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh />);
    expect(screen.getByRole("heading", { name: "Check Screening status" })).toBeVisible();
  });

  it("keeps authoritative Smoke content above local submission state", () => {
    render(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh submissionState="terminal" submissionError="local error" />);
    expect(screen.getByText(/does not establish whether Screening or a later stage has been submitted/)).toBeVisible(); expect(screen.queryByText("local error")).not.toBeInTheDocument();
  });

  it("does not infer an absent Screening job from an upstream-only Smoke snapshot", () => {
    const view = render(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh />);
    expect(screen.getByRole("heading", { name: "Check Screening status" })).toBeVisible();
    expect(screen.getByText(/Latest checked stage on Zeus/)).toBeVisible();
    expect(screen.getByText(/does not establish whether Screening or a later stage has been submitted/)).toBeVisible();
    expect(screen.queryByText(/No Screening job (?:was|has been) submitted/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/submission is ready for review/)).not.toBeInTheDocument();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh screenSubmitState="submitted" />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible();
    expect(screen.getByText("Screening has been submitted successfully.")).toBeVisible();
    expect(screen.queryByText(/does not establish whether Screening/)).not.toBeInTheDocument();
    view.rerender(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh screenState={screeningFixture("screen_running")} />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible();
    expect(screen.getByText(/2\[\].zeus-master/)).toBeVisible();
    expect(screen.queryByText(/Latest checked stage on Zeus/)).not.toBeInTheDocument();
  });

  it("describes a preliminary-check status read without implying submission", () => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, family: "mot_3d", stage: "preliminary_check" }} preliminaryCheckState="checking" />);
    expect(screen.getByRole("heading", { name: "Checking Zeus status" })).toBeVisible();
    expect(screen.getByText(/No submission has been reviewed or started by this check/)).toBeVisible();
  });

  it("keeps actual known input-generation held priority neutral without hiding uncertainty", () => {
    const status = parseMot3DFinalValidationTransitionStatus(actualHeldInputs);
    const campaign = {...campaignFixture, ...status.campaign, family:"mot_3d"} as Campaign;
    const view = render(<CampaignPriorityPanel {...base} campaign={campaign} mot3DLateKind="transition" mot3DLatePhase="idle" mot3DLateLifecycle={status.final_validation_input_generation.status} mot3DLateNextAction={status.next_action}/>);
    expect(screen.getByRole("heading",{name:"Input generation is held on Zeus"})).toBeVisible();
    expect(screen.getByText(/Refresh the read-only status below/)).toBeVisible();
    expect(screen.queryByText("Manual verification required")).not.toBeInTheDocument();
    for (const lifecycle of ["status_unknown", "completed_failed", "outcome_unknown", "outputs_invalid"]) {
      view.rerender(<CampaignPriorityPanel {...base} campaign={campaign} mot3DLateKind="transition" mot3DLatePhase="blocked" mot3DLateLifecycle={lifecycle} mot3DLateNextAction="inspect_zeus"/>);
      expect(screen.getByRole("heading",{name:"Manual verification required"})).toBeVisible();
    }
    view.rerender(<CampaignPriorityPanel {...base} campaign={campaign} mot3DLateKind="transition" mot3DLatePhase="blocked" mot3DLateLifecycle="held" mot3DLateNextAction="inspect_zeus"/>);
    expect(screen.getByRole("heading",{name:"Manual verification required"})).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{...campaign,stage:"closure"}} mot3DLateKind="transition" mot3DLatePhase="idle" mot3DLateLifecycle="held" mot3DLateNextAction="inspect_zeus"/>);
    expect(screen.getByRole("heading",{name:"Manual verification required"})).toBeVisible();
  });

  it.each([
    ["closure", "Review Closure"],
    ["finalist_selection", "Review Finalist Selection"],
    ["final_validation_input_generation", "Review Final-validation input generation"],
    ["final_validation", "Review Final Validation"],
  ])("routes the 3D %s priority through its stage controller", (stage, heading) => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, family: "mot_3d", stage } as Campaign} mot3DLatePhase="ready" mot3DLateNextAction="review_submission" />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Zeus preparation is unavailable" })).not.toBeInTheDocument();
  });

  it.each([
    ["complete", "open_final_report", "Final report is ready", /derived only from the new sealed ensembles/],
    ["final_validation_extension_required", "review_extension_required", "Precision target not met", /No winner or final-performance claim is available/],
  ])("restores the authoritative %s terminal priority after reload", (stage, _nextAction, heading, copy) => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, family: "mot_3d", stage } as Campaign} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    expect(screen.getByText(copy)).toBeVisible();
    expect(screen.queryByText(/Zeus preparation is unavailable/)).not.toBeInTheDocument();
  });

  it("blocks every 3D action when the campaign contract is untrusted", () => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, family: "mot_3d", stage: "closure", trust: "legacy-incomplete" } as Campaign} mot3DLatePhase="ready" mot3DLateNextAction="review_submission" />);
    expect(screen.getByRole("heading", { name: "Inspection only" })).toBeVisible();
    expect(screen.queryByText("Review Closure")).not.toBeInTheDocument();
  });

  it.each(["closure", "finalist_selection", "final_validation_input_generation", "final_validation"])("maps authoritative late-stage lifecycles for %s", (stage) => {
    const lateCampaign = { ...campaignFixture, family: "mot_3d", stage } as Campaign;
    const view = render(<CampaignPriorityPanel {...base} campaign={lateCampaign} mot3DLateLifecycle="submitted" />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} mot3DLateLifecycle="running" />);
    expect(screen.getByRole("heading", { name: "No action needed" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} mot3DLateLifecycle="completed_success_unvalidated" />);
    expect(screen.getByRole("heading", { name: "Scientific validation and synchronization required" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} mot3DLateLifecycle="partial" />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
    view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} mot3DLateLifecycle="outcome_unknown" />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
  });

  it.each([
    ["closure", "finalist_selection_prepared", "Finalist Selection is prepared"],
    ["finalist_selection", "final_validation_input_generation_prepared", "final-validation input generation is prepared"],
    ["final_validation_input_generation", "final_validation_prepared", "Final Validation is prepared"],
    ["final_validation", "final_validation_prepared", "final result validation is prepared"],
  ])("maps the prepared transition at %s", (stage, lifecycle, heading) => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...campaignFixture, family: "mot_3d", stage } as Campaign} mot3DLateKind="transition" mot3DLateLifecycle={lifecycle} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    expect(screen.getByText(/This transition prepared .* without submitting a later job or starting a simulation/)).toBeVisible();
    expect(screen.queryByText(/No later job was submitted or simulation started/)).not.toBeInTheDocument();
  });

  it.each([["submitted", "No action needed"], ["terminal", "Check Zeus jobs before continuing"], ["unknown", "Check Zeus jobs before continuing"]] as const)("keeps Smoke content while Screening submission %s controls the heading", (state, heading) => {
    render(<CampaignPriorityPanel {...base} remoteState={smoke} remoteEvidenceFresh screenSubmitState={state} />);
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    expect(screen.getByText(state === "submitted" ? "Screening has been submitted successfully." : "This preparation made the Screening files ready on Zeus without submitting a Screening job or starting a simulation.")).toBeVisible();
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
    section = screen.getByRole("heading", { name: "Check Screening status" }).closest("section"); expect(section).not.toHaveClass("priority-panel--blocked");
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


it("qualifies miniature Discovery and completed reports as TEST ONLY evidence", () => {
  vi.stubEnv("MODE", "ui-acceptance");
  try {
    const campaign = {...campaignFixture,family:"mot_3d",stage:"discovery"} as Campaign;
    const view = render(<CampaignPriorityPanel {...base} campaign={campaign} mot3DTransitionState="ready"/>);
    expect(screen.getByText(/TEST ONLY: all 24 Discovery trials passed physical evidence validation/)).toBeVisible();
    expect(screen.queryByText(/950 Discovery trials/)).not.toBeInTheDocument();
    view.rerender(<CampaignPriorityPanel {...base} campaign={{...campaign,stage:"complete"}}/>);
    expect(screen.getByRole("heading",{name:"TEST ONLY report is ready"})).toBeVisible();
    expect(screen.getByText(/not eligible for scientific promotion/)).toBeVisible();
  } finally { vi.unstubAllEnvs(); }
});

// Real public coordinator DTOs from the genuine full receiver protocol; only
// scheduler lifecycle/next_action pairs vary to exercise priority presentation.
import recoveryCapture from "./fixtures/CampaignDetail.readonlyRecovery.v1.json";
import { parseSensitivitySubmissionStatus, parseProductionSubmissionStatus, parseFinalizationStatus, parseProductionStatus } from "../api/schema/domain";
import type { SensitivityPriorityFlow, ProductionPriorityFlow } from "../features/campaign/late2DPriority";
function captured(parser: string) { return structuredClone(recoveryCapture.responses.find(row => row.parser === parser)!.value); }
const emptyOperation = { state: "idle" as const, status: null, result: null, error: "" };
function laterSensitivity(status: "running" | "status_unknown" = "running"): SensitivityPriorityFlow {
  const raw = captured("parseSensitivitySubmissionStatus") as unknown as Record<string, unknown>;
  raw.submission = { status, job_id: "70018[].zeus-master" };
  raw.next_action = status === "running" ? "wait" : "inspect_zeus";
  return { preparation: emptyOperation, submission: { ...emptyOperation, status: parseSensitivitySubmissionStatus(raw), state: status === "running" ? "success" : "terminal" } };
}
function laterProduction(status: "running" | "status_unknown" = "running"): ProductionPriorityFlow {
  const raw = captured("parseProductionSubmissionStatus") as unknown as Record<string, unknown>;
  raw.submission = { status, job_id: "70019[].zeus-master" };
  raw.next_action = status === "running" ? "wait" : "inspect_zeus";
  return { preparation: emptyOperation, finalization: emptyOperation, submission: { ...emptyOperation, status: parseProductionSubmissionStatus(raw), state: status === "running" ? "success" : "terminal" } };
}
const lateCampaign = { ...campaignFixture, id: laterSensitivity().submission.status!.campaign.id };
describe("latest authoritative 2D priority", () => {
  it("keeps historical Confirmation unknown behind actual Sensitivity running evidence", () => {
    render(<CampaignPriorityPanel {...base} campaign={lateCampaign} confirmationSubmitState="terminal" sensitivityFlow={laterSensitivity()} />);
    expect(screen.getByRole("heading", { name: "Sensitivity is running" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Manual verification required" })).not.toBeInTheDocument();
    expect(screen.getByText(/Earlier stage warnings remain historical/)).toBeVisible();
  });
  it("gives Production priority over both historical Confirmation and Sensitivity uncertainty", () => {
    render(<CampaignPriorityPanel {...base} campaign={lateCampaign} confirmationSubmitState="terminal" sensitivityFlow={laterSensitivity("status_unknown")} productionFlow={laterProduction()} />);
    expect(screen.getByRole("heading", { name: "Production is running" })).toBeVisible();
  });
  it("reopens authoritative completed results above earlier unknown warnings", () => {
    const flow = laterProduction();
    flow.finalization = { ...emptyOperation, state: "success", status: parseFinalizationStatus(captured("parseFinalizationStatus")) };
    render(<CampaignPriorityPanel {...base} campaign={lateCampaign} confirmationSubmitState="terminal" sensitivityFlow={laterSensitivity("status_unknown")} productionFlow={flow} />);
    expect(screen.getByRole("heading", { name: "Final report is ready" })).toBeVisible();
  });
  it.each(["Sensitivity", "Production"])("retains manual inspection for current %s uncertainty", stage => {
    render(<CampaignPriorityPanel {...base} campaign={lateCampaign} confirmationSubmitState="terminal" sensitivityFlow={laterSensitivity(stage === "Sensitivity" ? "status_unknown" : "running")} productionFlow={stage === "Production" ? laterProduction("status_unknown") : undefined} />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
    expect(screen.getByText(new RegExp(stage+" is the latest verified"))).toBeVisible();
    expect(screen.queryByRole("heading", { name: "No action needed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
  });
  it("ignores other-campaign DTOs and local later-stage hints", () => {
    render(<CampaignPriorityPanel {...base} campaign={{ ...lateCampaign, id: "other-campaign", stage: "complete" }} confirmationSubmitState="terminal" sensitivityFlow={laterSensitivity()} productionFlow={laterProduction()} />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Final report is ready" })).not.toBeInTheDocument();
  });
  it("does not hide unknown Confirmation without later evidence", () => {
    render(<CampaignPriorityPanel {...base} confirmationSubmitState="terminal" />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
  });
  it("preserves later-stage read errors as inspection, even with an older running DTO", () => {
    const flow=laterSensitivity();flow.submission.error="Status read could not be verified";
    render(<CampaignPriorityPanel {...base} campaign={lateCampaign} sensitivityFlow={flow} />);
    expect(screen.getByRole("heading", { name: "Manual verification required" })).toBeVisible();
  });
});

it("prefers a newer full Sensitivity validator over an older unknown submission observation", () => {
  const sensitivity=laterSensitivity("status_unknown");
  sensitivity.submission.status={...sensitivity.submission.status!,queried_at:"2026-10-20T01:00:00Z"};
  const raw=structuredClone(captured("parseProductionStatus")) as unknown as import("../api/schema/domain").ProductionStatus;
  const count=raw.sensitivity.scheduler.task_count;
  const status=parseProductionStatus({...raw,queried_at:"2026-10-20T02:00:00Z",campaign:{...raw.campaign,stage:"sensitivity"},sensitivity:{...raw.sensitivity,status:"running",scheduler:{...raw.sensitivity.scheduler,state:"running",counts:{queued:0,running:count,held:0,succeeded:0,failed:0}}},validation:{...raw.validation,status:"not_ready",completed_points:0},next_action:"wait"});
  const production:ProductionPriorityFlow={submission:emptyOperation,finalization:emptyOperation,preparation:{...emptyOperation,status}};
  const view=render(<CampaignPriorityPanel {...base} campaign={lateCampaign} sensitivityFlow={sensitivity} productionFlow={production} />);
  expect(screen.getByRole("heading",{name:"Sensitivity is running"})).toBeVisible();
  sensitivity.submission.status={...sensitivity.submission.status!,queried_at:"2026-10-20T03:00:00Z"};
  view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} sensitivityFlow={sensitivity} productionFlow={production} />);
  expect(screen.getByRole("heading",{name:"Manual verification required"})).toBeVisible();
  sensitivity.submission.status={...sensitivity.submission.status!,queried_at:"2026-10-20T01:00:00Z"};
  sensitivity.submission.error="Fresh status read failed";
  view.rerender(<CampaignPriorityPanel {...base} campaign={lateCampaign} sensitivityFlow={sensitivity} productionFlow={production} />);
  expect(screen.getByRole("heading",{name:"Manual verification required"})).toBeVisible();
});

/** Actual public P23 DTOs through strict parsers and real presentation components.
 * No transport, physical solver, SSH or scheduler is executed by this test.
 */
import { createRef } from "react";
import { render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import captured from "./fixtures/historicalReceipts.actualP23.json";
import success from "./teamContractFixture";
import * as domain from "../api/schema/domain";
import { CampaignPriorityPanel } from "../features/campaign/CampaignPriorityPanel";
import { TransferStage } from "../features/campaign/TransferStage";
import { SmokeSubmissionSection } from "../features/campaign/smoke/SmokeSubmissionSection";
import { ScreeningPreparationSection } from "../features/campaign/smoke/ScreeningPreparationSection";
import { ScreeningSubmissionSection } from "../features/campaign/screening/ScreeningSubmissionSection";
import { RefinementPreparationSection } from "../features/campaign/screening/RefinementPreparationSection";
import { RefinementSubmissionView } from "../features/campaign/refinement/RefinementSubmissionView";
import { ConfirmationPreparationView } from "../features/campaign/confirmation/ConfirmationPreparationView";
import { ConfirmationSubmissionView } from "../features/campaign/confirmation/ConfirmationSubmissionView";
import { SensitivityStage } from "../features/campaign/SensitivityStage";
import { ProductionStage } from "../features/campaign/ProductionStage";
import type { useSensitivityController } from "../features/campaign/controllers/useSensitivityController";
import type { useProductionController } from "../features/campaign/controllers/useProductionController";

const button = () => createRef<HTMLButtonElement>();
const heading = () => createRef<HTMLHeadingElement>();
const panel = () => createRef<HTMLDivElement>();
const data = (id: string) => structuredClone(success.cases.find(row => row.id === id)!.body.data) as Record<string, unknown>;
afterEach(() => vi.unstubAllEnvs());
it("keeps actual historical receipt effects scoped while the later Confirmation job is running", () => {
  vi.stubEnv("MODE", "ui-acceptance");
  const original = JSON.stringify(captured);
  const current = domain.parseSensitivityStatus(structuredClone(captured.current_confirmation_running));
  const r = captured.receipts;
  const transfer = domain.parseTransferResult(r.transfer);
  const smoke = domain.parseSmokeSubmissionResult(r.smoke);
  const screenPrep = domain.parseScreeningResult(r.screen_preparation);
  const screenSubmit = domain.parseScreeningSubmissionResult(r.screen_submission);
  const refinePrep = domain.parseRefinementResult(r.refinement_preparation);
  const refineSubmit = domain.parseRefinementSubmissionResult(r.refinement_submission);
  const confirmationPrep = domain.parseConfirmationResult(r.confirmation_preparation);
  const confirmationSubmit = domain.parseConfirmationSubmissionResult(r.confirmation_submission);
  const campaign = domain.parseCampaign({ ...data("campaign-detail"), id: current.campaign.id, name: current.campaign.name, kind: "mot_2d_ui_acceptance_v1", scientific_role: "acceptance-only" });
  const action = vi.fn();
  const flow = { preparation: { state: "idle" as const, status: current, result: null, error: "", lastObservation: "status" as const }, submission: { state: "idle" as const, status: null, result: null, error: "" } };
  render(<>
    <CampaignPriorityPanel campaign={campaign} transferState="success" submissionState="submitted" submissionResult={smoke} submissionError="" submissionTerminalCode={null} remoteState={null} remoteEvidenceFresh={false} screenSubmitState="submitted" screenState={null} chainStatus={null} refinementLifecycle={null} sensitivityFlow={flow} copyStatus="" onCopyCommand={action} />
    <TransferStage visible snapshot={null} state="success" preview={null} result={transfer} error="" buttonRef={button()} headingRef={heading()} successRef={panel()} errorRef={panel()} onConnect={action} onPreview={action} onConfirm={action} onReset={action} />
    <SmokeSubmissionSection canSubmit submissionState="submitted" submissionPreview={null} submissionResult={smoke} submissionError="" submissionButton={button()} submissionHeading={heading()} submissionSuccess={panel()} submissionErrorPanel={panel()} onPreviewSubmission={action} onConfirmSubmission={action} onResetSubmission={action} onViewJobs={action} />
    <ScreeningPreparationSection lifecycle={null} screeningState="success" screeningPreview={null} screeningResult={screenPrep} screeningError="" screeningButton={button()} screeningHeading={heading()} screeningSuccess={panel()} screeningErrorPanel={panel()} onPreviewScreening={action} onConfirmScreening={action} onResetScreening={action} onViewJobs={action} />
    <ScreeningSubmissionSection evidenceFresh smokeCheck="ready" submitState="submitted" submitPreview={null} submitResult={screenSubmit} submitError="" lifecycle={null} submitButton={button()} submitHeading={heading()} submitPanel={panel()} onRefreshSmoke={action} onPreviewSubmit={action} onConfirmSubmit={action} onResetSubmit={action} onViewJobs={action} />
    <RefinementPreparationSection lifecycle={null} prepareState="success" preparePreview={null} prepareResult={refinePrep} prepareError="" prepareButton={button()} prepareHeading={heading()} preparePanel={panel()} onPreviewPrepare={action} onConfirmPrepare={action} onResetPrepare={action} onViewJobs={action} />
    <RefinementSubmissionView status={null} state="submitted" preview={null} result={refineSubmit} button={button()} heading={heading()} panel={panel()} onPreview={action} onConfirm={action} onReset={action} onViewJobs={action} />
    <ConfirmationPreparationView lifecycle={null} state="success" preview={null} result={confirmationPrep} error="" lifecycleCheck="ready" heading={heading()} button={button()} panel={panel()} onPreview={action} onConfirm={action} onReset={action} onViewJobs={action} />
    <ConfirmationSubmissionView enabled state="submitted" status={null} preview={null} result={confirmationSubmit} error="" onRefresh={action} onReview={action} onConfirm={action} onReset={action} onViewJobs={action} />
  </>);
  const priority = within(document.querySelector('section[aria-labelledby="priority-heading"]') as HTMLElement);
  expect(priority.getByRole("heading", { name: "Confirmation is running" })).toBeVisible();
  const confirmation = within(document.querySelector('section[aria-labelledby="confirmation-submit-heading"]') as HTMLElement);
  expect(confirmation.getByText(current.confirmation.job_id!)).toBeVisible();
  expect(confirmationSubmit.job_id).toBe(current.confirmation.job_id);
  expect(screen.getByText("This transfer did not start a simulation or submit a Zeus job.")).toBeVisible();
  for (const stage of ["Screening", "Refinement", "Confirmation"]) expect(screen.getByText(`This preparation step did not submit a ${stage} job or start a simulation.`)).toBeVisible();
  expect(screen.getByText(/This receipt records only the four Refinement submissions/)).toBeVisible();
  expect(screen.getByText(/This receipt records only the Screening submission/)).toBeVisible();
  expect(screen.queryByText(/No (?:later campaign stage|later stage|Confirmation job|Refinement job|Screening job) was submitted/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Screening remains locked|Sensitivity stays locked/)).not.toBeInTheDocument();
  expect(action).not.toHaveBeenCalled();
  expect(JSON.stringify(captured)).toBe(original);
});
it.each(["development", "ui-acceptance"])("scopes persistent later preparation receipts to their own operation in %s", mode => {
  vi.stubEnv("MODE", mode);
  const action = vi.fn();
  const idle = { state: "idle", status: null, preview: null, result: null, error: "", refresh: action, review: action, confirm: action, reset: action, lastObservation: null };
  const sensitivity = { preparation: { ...idle, state: "success", result: domain.parseSensitivityResult(data("sensitivity-confirm")) }, submission: { ...idle, state: "success", result: domain.parseSensitivitySubmissionResult(data("sensitivity-submit-confirm")) } } as ReturnType<typeof useSensitivityController>;
  const production = { preparation: { ...idle, state: "success", result: domain.parseProductionResult(data("production-confirm")) }, submission: idle, finalization: idle } as ReturnType<typeof useProductionController>;
  render(<><SensitivityStage visible flow={sensitivity} onViewJobs={action} /><ProductionStage visible flow={production} onViewJobs={action} /></>);
  expect(screen.getByText(/This preparation made the Sensitivity array available for a separate submission review/)).toBeVisible();
  expect(screen.getByText(/This preparation made the sealed Production array available for a separate submission review/)).toBeVisible();
  expect(screen.queryByText(/Production stays locked/)).not.toBeInTheDocument();
  expect(action).not.toHaveBeenCalled();
});
it.each([
  ["development", "final_validation"], ["ui-acceptance", "final_validation"],
  ["development", "final_validation_input_generation"], ["ui-acceptance", "final_validation_input_generation"],
] as const)("keeps 3D preparation receipts historical beside a running %s %s stage", async (mode, stage) => {
  vi.stubEnv("MODE", mode);
  const { Mot3DCampaignFlow } = await import("../features/campaign/Mot3DCampaignFlow");
  const { parseMot3DFinalistTransitionResult } = await import("../api/clients/mot3dFinalistTransition");
  const { parseMot3DFinalValidationTransitionResult } = await import("../api/clients/mot3dFinalValidationTransition");
  const { parseMot3DFinalValidationSubmissionStatus } = await import("../api/clients/mot3dFinalValidationSubmission");
  const { parseMot3DFinalInputStatus } = await import("../api/clients/mot3dFinalInputSubmission");
  const current = data("mot3d-final-validation-status");
  const submission = current.submission as { status: string; chain: { families: { id: string; array_job_id: string | null; merge_job_id: string | null }[] } };
  submission.status = "running";
  submission.chain.families.forEach((family, index) => { family.array_job_id = `${901 + 2 * index}[].zeus-master`; family.merge_job_id = `${902 + 2 * index}.zeus-master`; });
  current.next_action = "wait";
  const validationStatus = parseMot3DFinalValidationSubmissionStatus(current);
  const generation = data("mot3d-final-input-status");
  const chain = generation.chain as { status: string; jobs: { job_id: string | null }[] };
  chain.status = "running";
  chain.jobs.forEach((job, index) => { job.job_id = `${911 + index}${index < 2 ? "[]" : ""}.zeus-master`; });
  generation.next_action = "wait";
  const inputStatus = parseMot3DFinalInputStatus(generation);
  const original = JSON.stringify({ validationStatus, inputStatus });
  const action = vi.fn();
  const idle = { state: "idle" as const, phase: "idle" as const, errorPhase: null, status: null, preview: null, result: null, error: "", refresh: action, review: action, confirm: action, reset: action };
  const props = {
    stage, connected: true, discovery: idle, transition: idle, preliminary: idle,
    finalistTransition: { ...idle, phase: "success" as const, result: parseMot3DFinalistTransitionResult(data("mot3d-finalist-transition-confirm"), "campaign-id") },
    finalValidationTransition: { ...idle, phase: "success" as const, result: parseMot3DFinalValidationTransitionResult(data("mot3d-final-validation-transition-confirm"), "campaign-id") },
    finalInputSubmission: { ...idle, phase: "success" as const, status: inputStatus },
    finalValidation: { ...idle, phase: "success" as const, status: validationStatus },
    onConnectZeus: action, onViewJobs: action,
  };
  render(<Mot3DCampaignFlow {...props} />);
  if (stage === "final_validation") {
    expect(screen.getByText("Final Validation is prepared")).toBeVisible();
    expect(screen.getByText(/This preparation verified and synchronized the frozen inputs/)).toBeVisible();
    expect(screen.getByText("Final Validation is running on Zeus")).toBeVisible();
  } else {
    expect(screen.getByText("Final-validation inputs are prepared")).toBeVisible();
    expect(screen.getByText(/This preparation synchronized the verified evidence and winner lock/)).toBeVisible();
    const live = within(document.querySelector('section[aria-labelledby="mot3d-final-input-heading"]') as HTMLElement);
    expect(live.getByText(/running/i)).toBeVisible();
    for (const job of inputStatus.chain.jobs) expect(live.getByText(job.job_id!)).toBeVisible();
  }
  expect(screen.queryByText(/there is no Final Validation result yet|final validation has not yet been performed|No validation job was submitted/)).not.toBeInTheDocument();
  expect(JSON.stringify({ validationStatus, inputStatus })).toBe(original);
  expect(action).not.toHaveBeenCalled();
});

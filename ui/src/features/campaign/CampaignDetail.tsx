import { AlertTriangle, ArrowLeft, CheckCircle2, Clipboard, Clock3, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Campaign } from "../../api/clients/campaign";
import { RefinementLifecycleApiError, RefinementSubmissionApiError, type ConfirmationPreview, type ConfirmationResult, type RefinementChainStatus, type RefinementLifecycle, type RefinementLifecycleApi, type RefinementSubmissionApi, type RefinementSubmissionPreview, type RefinementSubmissionResult } from "../../api/clients/refinement";
import { ScreeningLifecycleApiError, ScreeningSubmissionApiError, type RefinementPreview, type RefinementResult, type ScreeningLifecycle, type ScreeningLifecycleApi, type ScreeningSubmissionApi, type ScreeningSubmissionPreview, type ScreeningSubmissionResult } from "../../api/clients/screening";
import { SmokeLifecycleApiError, SubmissionApiError, type ScreeningPreview, type ScreeningResult, type SmokeLifecycle, type SmokeLifecycleApi, type SmokeSubmissionPreview, type SmokeSubmissionResult, type SubmissionApi } from "../../api/clients/smoke";
import type { TransferApi, ZeusSnapshot, ZeusTransferPreview, ZeusTransferResult } from "../../api/clients/zeus";
import { errorHasSemantic, requiresManualVerification } from "../../api/errorSemantics";
import { ConfirmationStage } from "./ConfirmationStage";
import { TransferStage } from "./TransferStage";
import { SmokePointsTable } from "./SmokeStage";
import { ScreeningFacts } from "./ScreeningStage";
import { RefinementReceipt } from "./RefinementStage";
import { RefinementFlow } from "./RefinementFlow";
import { ScreeningFlow } from "./ScreeningFlow";
import { SmokeFlow } from "./SmokeFlow";

const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

const timestamp = (value: string) => new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value));

export function CampaignDetail({ campaign, onBack, transfer, submission, lifecycle, screeningSubmission, screeningLifecycle, refinementSubmission, refinementLifecycle, zeusSnapshot, onConnectZeus, onViewJobs }: { campaign: Campaign; onBack: () => void; transfer: TransferApi; submission: SubmissionApi; lifecycle: SmokeLifecycleApi; screeningSubmission: ScreeningSubmissionApi; screeningLifecycle: ScreeningLifecycleApi; refinementSubmission: RefinementSubmissionApi; refinementLifecycle: RefinementLifecycleApi; zeusSnapshot: ZeusSnapshot | null; onConnectZeus: () => void; onViewJobs: () => void }) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const [copyStatus, setCopyStatus] = useState("");
  const [transferState, setTransferState] = useState<"idle" | "previewing" | "review" | "preparing" | "success">("idle");
  const [transferPreview, setTransferPreview] = useState<ZeusTransferPreview | null>(null);
  const [transferResult, setTransferResult] = useState<ZeusTransferResult | null>(null);
  const [transferError, setTransferError] = useState("");
  const [submissionState, setSubmissionState] = useState<"idle" | "previewing" | "review" | "submitting" | "submitted" | "unknown" | "terminal" | "error">("idle");
  const [submissionPreview, setSubmissionPreview] = useState<SmokeSubmissionPreview | null>(null);
  const [submissionResult, setSubmissionResult] = useState<SmokeSubmissionResult | null>(null);
  const [submissionError, setSubmissionError] = useState("");
  const [submissionTerminalCode, setSubmissionTerminalCode] = useState<"already_submitted" | "smoke_already_started" | "submission_record_invalid" | null>(null);
  const [remoteState, setRemoteState] = useState<SmokeLifecycle | null>(null);
  const [remoteCheck, setRemoteCheck] = useState<"idle" | "checking" | "ready" | "error">("idle");
  const [remoteError, setRemoteError] = useState("");
  const [remoteEvidenceFresh, setRemoteEvidenceFresh] = useState(false);
  const [screeningState, setScreeningState] = useState<"idle" | "previewing" | "review" | "preparing" | "success" | "terminal">("idle");
  const [screeningPreview, setScreeningPreview] = useState<ScreeningPreview | null>(null);
  const [screeningResult, setScreeningResult] = useState<ScreeningResult | null>(null);
  const [screeningError, setScreeningError] = useState("");
  const [screenSubmitState, setScreenSubmitState] = useState<"idle" | "previewing" | "review" | "submitting" | "submitted" | "unknown" | "terminal" | "error">("idle");
  const [screenSubmitPreview, setScreenSubmitPreview] = useState<ScreeningSubmissionPreview | null>(null);
  const [screenSubmitResult, setScreenSubmitResult] = useState<ScreeningSubmissionResult | null>(null);
  const [screenSubmitError, setScreenSubmitError] = useState("");
  const [screenState, setScreenState] = useState<ScreeningLifecycle | null>(null);
  const [screenCheck, setScreenCheck] = useState<"idle" | "checking" | "ready" | "error">("idle");
  const [screenError, setScreenError] = useState("");
  const [refineState, setRefineState] = useState<"idle" | "previewing" | "review" | "preparing" | "success" | "terminal">("idle");
  const [refinePreview, setRefinePreview] = useState<RefinementPreview | null>(null);
  const [refineResult, setRefineResult] = useState<RefinementResult | null>(null);
  const [refineError, setRefineError] = useState("");
  const [chainStatus, setChainStatus] = useState<RefinementChainStatus | null>(null);
  const [chainCheck, setChainCheck] = useState<"idle" | "checking" | "ready" | "error">("idle");
  const [chainState, setChainState] = useState<"idle" | "previewing" | "review" | "submitting" | "submitted" | "blocked" | "error">("idle");
  const [chainPreview, setChainPreview] = useState<RefinementSubmissionPreview | null>(null);
  const [chainResult, setChainResult] = useState<RefinementSubmissionResult | null>(null);
  const [chainError, setChainError] = useState("");
  const [refinementLifecycleState, setRefinementLifecycleState] = useState<RefinementLifecycle | null>(null);
  const [refinementLifecycleCheck, setRefinementLifecycleCheck] = useState<"idle" | "checking" | "ready" | "error">("idle");
  const [confirmationState, setConfirmationState] = useState<"idle" | "previewing" | "review" | "preparing" | "success" | "terminal">("idle");
  const [confirmationPreview, setConfirmationPreview] = useState<ConfirmationPreview | null>(null);
  const [confirmationResult, setConfirmationResult] = useState<ConfirmationResult | null>(null);
  const [confirmationError, setConfirmationError] = useState("");
  const title = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const successPanel = useRef<HTMLDivElement>(null);
  const errorPanel = useRef<HTMLDivElement>(null);
  const submissionRequestActive = useRef(false);
  const screenSubmitRequestActive = useRef(false);
  const chainRequestActive = useRef(false);
  const previousTransferState = useRef(transferState);
  useEffect(() => { title.current?.focus(); }, []);
  useEffect(() => {
    const previous = previousTransferState.current;
    if (transferError) errorPanel.current?.focus();
    else if (transferState === "review") reviewHeading.current?.focus();
    else if (transferState === "success") successPanel.current?.focus();
    else if (transferState === "idle" && previous !== "idle") reviewButton.current?.focus();
    previousTransferState.current = transferState;
  }, [transferState, transferError]);
  async function copyCommand() {
    try { await navigator.clipboard.writeText(command); setCopyStatus("Command copied."); }
    catch { setCopyStatus("Copy failed. Select the command text and copy it manually."); }
  }
  async function previewTransfer() {
    if (!zeusSnapshot) return;
    setTransferState("previewing"); setTransferError("");
    try { setTransferPreview(await transfer.preview(campaign.id, zeusSnapshot.profile)); setTransferState("review"); }
    catch (error) { setTransferError(error instanceof Error ? error.message : "Zeus preparation preview failed safely."); setTransferState("idle"); }
  }
  async function confirmTransfer() {
    if (!transferPreview) return;
    setTransferState("preparing"); setTransferError("");
    try { setTransferResult(await transfer.confirm(transferPreview.preview_token)); setTransferState("success"); }
    catch (error) { setTransferError(error instanceof Error ? error.message : "Zeus preparation failed safely."); setTransferState("review"); }
  }
  async function previewSubmission() {
    if (!zeusSnapshot || submissionRequestActive.current) return;
    submissionRequestActive.current = true;
    setSubmissionState("previewing"); setSubmissionError("");
    try { setSubmissionPreview(await submission.preview(campaign.id, zeusSnapshot.profile)); setSubmissionState("review"); }
    catch (error) {
      if (error instanceof SubmissionApiError && errorHasSemantic("smoke_submission", error.code, "outcome_unknown")) {
        setSubmissionError("Submission outcome could not be verified. Do not submit again. Check Zeus jobs first."); setSubmissionState("unknown");
      } else if (error instanceof SubmissionApiError && errorHasSemantic("smoke_submission", error.code, "manual_verification")) {
        const code = error.code as "already_submitted" | "smoke_already_started" | "submission_record_invalid";
        setSubmissionTerminalCode(code);
        setSubmissionError(code === "already_submitted" ? "This smoke stage already has a durable Zeus submission record. Do not submit it again." : code === "smoke_already_started" ? "Smoke outputs already exist on Zeus. Do not submit this stage again; inspect the jobs and campaign status." : error.message);
        setSubmissionState("terminal");
      } else { setSubmissionError(error instanceof Error ? error.message : "Smoke submission review stopped safely."); setSubmissionState(error instanceof SubmissionApiError && requiresManualVerification("smoke_submission", error.code) ? "terminal" : "error"); }
    }
    finally { submissionRequestActive.current = false; }
  }
  async function confirmSubmission() {
    if (!submissionPreview || submissionRequestActive.current) return;
    submissionRequestActive.current = true;
    setSubmissionState("submitting"); setSubmissionError("");
    try { setSubmissionResult(await submission.confirm(submissionPreview.preview_token)); setSubmissionState("submitted"); }
    catch (error) {
      if (error instanceof SubmissionApiError && errorHasSemantic("smoke_submission", error.code, "outcome_unknown")) {
        setSubmissionError("Submission outcome could not be verified. Do not submit again. Check Zeus jobs first.");
        setSubmissionState("unknown");
      } else if (error instanceof SubmissionApiError && errorHasSemantic("smoke_submission", error.code, "manual_verification")) {
        const code = error.code as "already_submitted" | "smoke_already_started" | "submission_record_invalid";
        setSubmissionTerminalCode(code);
        setSubmissionError(code === "already_submitted" ? "This smoke stage already has a durable Zeus submission record. Do not submit it again." : code === "smoke_already_started" ? "Smoke outputs already exist on Zeus. Do not submit this stage again; inspect the jobs and campaign status." : error.message);
        setSubmissionState("terminal");
      } else {
        setSubmissionError(error instanceof Error ? error.message : "Smoke submission stopped safely.");
        setSubmissionState(error instanceof SubmissionApiError && requiresManualVerification("smoke_submission", error.code) ? "terminal" : "error");
      }
    }
    finally { submissionRequestActive.current = false; }
  }
  async function refreshRemoteStatus() {
    if (!zeusSnapshot || remoteCheck === "checking") return;
    setRemoteCheck("checking"); setRemoteError(""); setScreeningError("");
    try { setRemoteState(await lifecycle.status(campaign.id, zeusSnapshot.profile)); setRemoteEvidenceFresh(true); setRemoteCheck("ready"); }
    catch (error) { setRemoteState(null); setRemoteEvidenceFresh(false); setRemoteError(error instanceof Error ? error.message : "The smoke status check stopped safely."); setRemoteCheck("error"); }
  }
  async function previewScreening() {
    if (!zeusSnapshot || !remoteState || remoteState.lifecycle !== "ready_to_prepare_screen") return;
    setScreeningState("previewing"); setScreeningError("");
    try { setScreeningPreview(await lifecycle.preview(campaign.id, zeusSnapshot.profile)); setScreeningState("review"); }
    catch (error) {
      if (error instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", error.code, "already_prepared")) { setScreeningPreview(null); setScreeningState("idle"); await refreshRemoteStatus(); return; }
      const terminal = error instanceof SmokeLifecycleApiError && requiresManualVerification("smoke_transition", error.code);
      setScreeningError(error instanceof Error ? error.message : "Screening preparation review stopped safely."); setScreeningState(terminal ? "terminal" : "idle");
    }
  }
  async function confirmScreening() {
    if (!screeningPreview) return;
    setScreeningState("preparing"); setScreeningError("");
    try { setScreeningResult(await lifecycle.confirm(screeningPreview.preview_token)); setScreeningState("success"); setRemoteEvidenceFresh(false); setRemoteState((current) => current ? { ...current, campaign: { ...current.campaign, stage: "screen" }, lifecycle: "screen_prepared", next_action: "none" } : current); }
    catch (error) {
      if (error instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", error.code, "already_prepared")) { setScreeningPreview(null); setScreeningState("idle"); await refreshRemoteStatus(); return; }
      const retryReview = error instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", error.code, "fresh_review");
      const terminal = error instanceof SmokeLifecycleApiError && requiresManualVerification("smoke_transition", error.code);
      setScreeningError(error instanceof Error ? error.message : "Screening preparation stopped safely.");
      if (retryReview) { setScreeningPreview(null); setScreeningState("idle"); }
      else setScreeningState(terminal ? "terminal" : "review");
    }
  }
  async function previewScreenSubmission() {
    if (!zeusSnapshot || !remoteEvidenceFresh || remoteState?.lifecycle !== "screen_prepared" || screenSubmitRequestActive.current) return;
    screenSubmitRequestActive.current = true; setScreenSubmitState("previewing"); setScreenSubmitError("");
    try { setScreenSubmitPreview(await screeningSubmission.preview(campaign.id, zeusSnapshot.profile)); setScreenSubmitState("review"); }
    catch (error) { setScreenSubmitError(error instanceof Error ? error.message : "Screening submission review stopped safely."); setScreenSubmitState(error instanceof ScreeningSubmissionApiError && requiresManualVerification("screen_submission", error.code) ? "terminal" : "error"); }
    finally { screenSubmitRequestActive.current = false; }
  }
  async function confirmScreenSubmission() {
    if (!screenSubmitPreview || screenSubmitRequestActive.current) return;
    screenSubmitRequestActive.current = true; setScreenSubmitState("submitting"); setScreenSubmitError("");
    try { setScreenSubmitResult(await screeningSubmission.confirm(screenSubmitPreview.preview_token)); setScreenSubmitState("submitted"); }
    catch (error) {
      const code = error instanceof ScreeningSubmissionApiError ? error.code : "";
      if (errorHasSemantic("screen_submission", code, "fresh_review")) { setScreenSubmitPreview(null); setScreenSubmitError(code === "local_files_changed" ? "The campaign files changed after review. Start a fresh review before submitting." : "The review expired or is no longer valid. Start a fresh review before submitting."); setScreenSubmitState("error"); }
      else if (errorHasSemantic("screen_submission", code, "outcome_unknown")) { setScreenSubmitError("The submission outcome could not be verified. Do not submit again; inspect Zeus jobs."); setScreenSubmitState("unknown"); }
      else if (errorHasSemantic("screen_submission", code, "manual_verification")) { setScreenSubmitError(error instanceof Error ? error.message : "The Screening submission needs manual verification."); setScreenSubmitState("terminal"); }
      else { setScreenSubmitError(error instanceof Error ? error.message : "Screening submission stopped safely."); setScreenSubmitState(error instanceof ScreeningSubmissionApiError && requiresManualVerification("screen_submission", code) ? "terminal" : "error"); }
    } finally { screenSubmitRequestActive.current = false; }
  }
  async function refreshScreenStatus() {
    if (!zeusSnapshot || screenCheck === "checking") return;
    setScreenCheck("checking"); setScreenError(""); setRefineError("");
    try { setScreenState(await screeningLifecycle.status(campaign.id, zeusSnapshot.profile)); setScreenCheck("ready"); }
    catch (error) { setScreenState(null); setScreenError(error instanceof Error ? error.message : "The Screening status check stopped safely."); setScreenCheck("error"); }
  }
  async function previewRefinement() {
    if (!zeusSnapshot || screenState?.lifecycle !== "ready_to_prepare_refinement") return;
    setRefineState("previewing"); setRefineError("");
    try { setRefinePreview(await screeningLifecycle.preview(campaign.id, zeusSnapshot.profile)); setRefineState("review"); }
    catch (error) { if (error instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", error.code, "already_prepared")) { setRefinePreview(null); setRefineState("idle"); await refreshScreenStatus(); return; } const terminal = error instanceof ScreeningLifecycleApiError && requiresManualVerification("refinement_transition", error.code); setRefineError(error instanceof Error ? error.message : "Refinement preparation review stopped safely."); setRefineState(terminal ? "terminal" : "idle"); }
  }
  async function confirmRefinement() {
    if (!refinePreview) return;
    setRefineState("preparing"); setRefineError("");
    try { setRefineResult(await screeningLifecycle.confirm(refinePreview.preview_token)); setRefineState("success"); setScreenState((current) => current ? { ...current, campaign: { ...current.campaign, stage: "refine" }, lifecycle: "refinement_prepared", next_action: "none" } : current); }
    catch (error) { if (error instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", error.code, "already_prepared")) { setRefinePreview(null); setRefineState("idle"); await refreshScreenStatus(); return; } const fresh = error instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", error.code, "fresh_review"); const terminal = error instanceof ScreeningLifecycleApiError && requiresManualVerification("refinement_transition", error.code); setRefineError(error instanceof Error ? error.message : "Refinement preparation stopped safely."); if (fresh) { setRefinePreview(null); setRefineState("idle"); } else setRefineState(terminal ? "terminal" : "review"); }
  }
  async function refreshChainStatus() {
    if (!zeusSnapshot || chainCheck === "checking") return;
    setChainCheck("checking"); setChainError("");
    try { const result = await refinementSubmission.status(campaign.id, zeusSnapshot.profile); setChainStatus(result); setChainCheck("ready"); if (["partial", "outcome_unknown"].includes(result.chain.status)) setChainState("blocked"); else if (result.chain.status === "submitted") setChainState("submitted"); }
    catch (error) { setChainStatus(null); setChainError(error instanceof Error ? error.message : "The Refinement chain status check stopped safely."); setChainCheck("error"); }
  }
  async function previewChainSubmission() {
    if (!zeusSnapshot || chainStatus?.chain.status !== "not_submitted" || chainRequestActive.current) return;
    chainRequestActive.current = true; setChainState("previewing"); setChainError("");
    try { setChainPreview(await refinementSubmission.preview(campaign.id, zeusSnapshot.profile)); setChainState("review"); }
    catch (error) { const code = error instanceof RefinementSubmissionApiError ? error.code : ""; const blocked = error instanceof RefinementSubmissionApiError && requiresManualVerification("refinement_submission", code); setChainError(error instanceof Error ? error.message : "Refinement chain review stopped safely."); setChainState(blocked ? "blocked" : "error"); if (blocked) await refreshChainStatus(); }
    finally { chainRequestActive.current = false; }
  }
  async function confirmChainSubmission() {
    if (!zeusSnapshot || !chainPreview || chainRequestActive.current) return;
    chainRequestActive.current = true; setChainState("submitting"); setChainError("");
    const poll = window.setInterval(() => { void refinementSubmission.status(campaign.id, zeusSnapshot.profile).then(setChainStatus).catch(() => undefined); }, 1000);
    try { const result = await refinementSubmission.confirm(chainPreview.preview_token); setChainResult(result); setChainState("submitted"); setChainStatus({ source: "zeus", queried_at: result.submitted_at, campaign: { id: result.campaign_id, name: chainPreview.campaign.name, stage: "refine" }, chain: { status: "submitted", dependency: "afterok", rounds: result.chain.rounds.map((row) => ({ ...row, state: "submitted" })) }, next_action: "none", local_sync: { status: "not_synchronized" } }); }
    catch (error) { const code = error instanceof RefinementSubmissionApiError ? error.code : ""; if (errorHasSemantic("refinement_submission", code, "fresh_review")) { setChainPreview(null); setChainError(code === "local_files_changed" ? "The remote files changed after review. Start a fresh review." : "The review expired or is no longer valid. Start a fresh review."); setChainState("error"); } else { setChainError(error instanceof Error ? error.message : "The Refinement chain outcome needs manual verification."); setChainState("blocked"); await refreshChainStatus(); } }
    finally { window.clearInterval(poll); chainRequestActive.current = false; }
  }
  async function refreshRefinementLifecycle(preserveError = false) {
    if (!zeusSnapshot || refinementLifecycleCheck === "checking") return;
    setRefinementLifecycleCheck("checking"); if (!preserveError) setConfirmationError("");
    try { const result = await refinementLifecycle.status(campaign.id, zeusSnapshot.profile); setRefinementLifecycleState(result); setRefinementLifecycleCheck("ready"); if (result.chain.status === "confirmation_prepared") setConfirmationState("success"); }
    catch (error) { setRefinementLifecycleState(null); if (!preserveError) setConfirmationError(error instanceof Error ? error.message : "The Refinement status check stopped safely."); setRefinementLifecycleCheck("error"); }
  }
  async function previewConfirmation() {
    if (!zeusSnapshot || refinementLifecycleState?.chain.status !== "ready_to_prepare_confirmation") return;
    setConfirmationState("previewing"); setConfirmationError("");
    try { setConfirmationPreview(await refinementLifecycle.preview(campaign.id, zeusSnapshot.profile)); setConfirmationState("review"); }
    catch (error) { if (error instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", error.code, "already_prepared")) { setConfirmationPreview(null); setConfirmationState("idle"); await refreshRefinementLifecycle(); return; } const terminal = error instanceof RefinementLifecycleApiError && requiresManualVerification("confirmation_transition", error.code); setConfirmationError(error instanceof Error ? error.message : "Confirmation preparation review stopped safely."); setConfirmationState(terminal ? "terminal" : "idle"); }
  }
  async function confirmConfirmation() {
    if (!confirmationPreview) return;
    setConfirmationState("preparing"); setConfirmationError("");
    try { setConfirmationResult(await refinementLifecycle.confirm(confirmationPreview.preview_token)); setConfirmationState("success"); setRefinementLifecycleState((current) => current ? { ...current, campaign: { ...current.campaign, stage: "confirmation" }, chain: { ...current.chain, status: "confirmation_prepared" }, next_action: "none" } : current); }
    catch (error) { if (error instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", error.code, "already_prepared")) { setConfirmationPreview(null); setConfirmationState("idle"); await refreshRefinementLifecycle(); return; } const fresh = error instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", error.code, "fresh_review"); setConfirmationError(error instanceof Error ? error.message : "The Confirmation preparation outcome could not be verified. Do not retry automatically."); setConfirmationPreview(null); setConfirmationState(fresh ? "idle" : "terminal"); if (!fresh) await refreshRefinementLifecycle(true); }
  }
  const remoteLifecycle = remoteState?.lifecycle;
  const screenLifecycle = screenState?.lifecycle;
  const chainPriority = chainStatus?.chain.status === "not_submitted" ? "Action required" : ["submitting", "submitted"].includes(chainStatus?.chain.status ?? "") ? "No action needed" : ["partial", "outcome_unknown"].includes(chainStatus?.chain.status ?? "") ? "Manual verification required" : null;
  const screenPriority = chainPriority ?? (screenLifecycle === "ready_to_prepare_refinement" ? "Action required" : ["screen_queued", "screen_running", "awaiting_outputs"].includes(screenLifecycle ?? "") ? "No action needed" : screenLifecycle === "refinement_prepared" ? "Refinement is prepared" : screenLifecycle ? "Screening needs attention" : null);
  const refinementPriority = refinementLifecycleState?.chain.status === "ready_to_prepare_confirmation" ? "Action required" : ["queued", "running", "awaiting_outputs"].includes(refinementLifecycleState?.chain.status ?? "") ? "No action needed" : refinementLifecycleState?.chain.status === "confirmation_prepared" ? "Confirmation is prepared" : refinementLifecycleState ? "Refinement needs attention" : null;
  const remotePriority = refinementPriority ?? screenPriority ?? (screenSubmitState === "submitted" ? "No action needed" : ["unknown", "terminal"].includes(screenSubmitState) ? "Check Zeus jobs before continuing" : remoteLifecycle === "ready_to_prepare_screen" ? "Action required" : ["queued", "running", "awaiting_outputs"].includes(remoteLifecycle ?? "") ? "No action needed" : remoteLifecycle === "screen_prepared" ? (remoteEvidenceFresh ? "Action required" : "Refresh Zeus status") : remoteLifecycle ? "Smoke check needs attention" : null);
  return <main id="main" className="detail-page">
    <button className="text-button back-button" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to campaigns</button>
    <header className="detail-hero"><p className="eyebrow">{campaign.family === "mot_2d" ? "2D-MOT campaign" : "3D-MOT campaign"}</p><h1 ref={title} tabIndex={-1}>{campaign.name}</h1><p className="path-text">{campaign.path}</p><div className="detail-badges"><span>{words(campaign.scientific_role)}</span><span className={trusted ? "badge-ok" : "badge-blocked"}>{words(campaign.trust)}</span></div></header>
    <section className={`priority-panel ${remoteLifecycle && !["queued", "running", "awaiting_outputs", "ready_to_prepare_screen", "screen_prepared"].includes(remoteLifecycle) ? "priority-panel--blocked" : trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`} aria-labelledby="priority-heading">
      <p className="eyebrow">Current priority</p><h2 id="priority-heading">{remotePriority ?? (submissionState === "submitted" || (submissionState === "terminal" && submissionTerminalCode === "already_submitted") ? "No action needed" : ["unknown", "terminal"].includes(submissionState) ? "Check Zeus jobs before continuing" : transferState === "success" ? "Smoke check ready for review" : campaign.remote_preparation.status === "legacy-local-only" ? "Recreate this campaign before using Zeus" : campaign.remote_preparation.status === "unavailable" ? "Zeus preparation is unavailable" : trusted ? (campaign.next_plan ? "Command available for review" : "No action available") : "Inspection only")}</h2>
      {refinementLifecycleState ? <><p><strong>Current stage on Zeus:</strong> {refinementLifecycleState.chain.status === "confirmation_prepared" ? "Confirmation prepared" : "Refinement"}.</p>{["queued", "running", "awaiting_outputs"].includes(refinementLifecycleState.chain.status) && <p>Zeus continues independently. No action is needed; refresh later.</p>}{refinementLifecycleState.chain.status === "ready_to_prepare_confirmation" && <p>All four rounds and {refinementLifecycleState.validation.completed_trials} trials passed validation. Review Confirmation preparation below.</p>}{refinementLifecycleState.chain.status === "confirmation_prepared" && <p>Confirmation files are prepared. No job was submitted.</p>}{["held", "failed", "status_unknown", "outputs_invalid"].includes(refinementLifecycleState.chain.status) && <p>Refinement cannot advance safely. Inspect Zeus before continuing.</p>}</> : chainStatus ? <><p><strong>Current stage on Zeus:</strong> Refinement.</p>{chainStatus.chain.status === "not_submitted" && <p>The four-round chain is prepared and ready for explicit submission review.</p>}{chainStatus.chain.status === "submitting" && <p>Zeus is acknowledging the dependency chain. Do not retry or close until the outcome is resolved.</p>}{chainStatus.chain.status === "submitted" && <p>All four Refinement rounds have durable Zeus job IDs. They will run in order after each previous round succeeds.</p>}{["partial", "outcome_unknown"].includes(chainStatus.chain.status) && <p>The chain is only partially confirmed or its outcome is uncertain. Automatic retry is blocked; inspect Zeus manually.</p>}</> : screenState ? <><p><strong>Current stage on Zeus:</strong> {screenLifecycle === "refinement_prepared" ? "Refinement prepared" : "Screening"}.</p>{["screen_queued", "screen_running"].includes(screenLifecycle ?? "") && <><p>Screening array <code>{screenState.submission.job_id}</code> is {screenLifecycle === "screen_queued" ? "queued" : "running"}. Zeus continues independently; you can safely close this application.</p><p>Refinement remains locked until all Screening results are complete and validated.</p></>}{screenLifecycle === "awaiting_outputs" && <p>The Screening array completed successfully and Zeus is still publishing its expected outputs. No action is needed; refresh later.</p>}{screenLifecycle === "ready_to_prepare_refinement" && <><p>All {screenState.validation.completed_trials} Screening trials and {screenState.validation.candidate_count} selected candidates passed validation.</p><p>Review the Refinement preparation below. This does not submit another job.</p></>}{screenLifecycle === "refinement_prepared" && <><p>Refinement preparation completed successfully.</p><p>The authoritative transition details are recorded below.</p></>}{["screen_held", "screen_failed", "screen_status_unknown", "outputs_invalid"].includes(screenLifecycle ?? "") && <p>The Screening stage cannot advance safely. Inspect Zeus before continuing.</p>}</> : remoteState ? <>
        <p><strong>Current stage on Zeus:</strong> {remoteLifecycle === "screen_prepared" ? "Screening prepared" : "Smoke check"}.</p>
        {["queued", "running"].includes(remoteLifecycle ?? "") && <><p>Job {remoteState.submission.job_id} is {remoteLifecycle}. Zeus continues independently; you can safely close this application.</p><p>Screening remains locked until every smoke output is complete and validated.</p></>}
        {remoteLifecycle === "awaiting_outputs" && <><p>Job {remoteState.submission.job_id} completed successfully. Zeus is still publishing the expected smoke output files.</p><p>No action is needed. Refresh later; Screening remains locked until every output is present and validated.</p></>}
        {remoteLifecycle === "ready_to_prepare_screen" && <><p>All {remoteState.validation.artifact_count} smoke artifacts passed the frozen scientific checks.</p><p>The smoke check confirms execution and data integrity. Its capture values are not a performance result.</p></>}
        {remoteLifecycle === "screen_prepared" && screenSubmitState === "submitted" ? <><p>Screening has been submitted successfully.</p><p>No later stage was submitted; full details are recorded below.</p></> : remoteLifecycle === "screen_prepared" && <><p>The screening files are ready on Zeus. No screening job was submitted and no simulation started.</p><p>{remoteEvidenceFresh ? "A fresh Zeus check confirms that the submission is ready for review." : "Refresh the Zeus status before reviewing submission; this local transition is not evidence of remote readiness."}</p><p>The local campaign record has not been synchronized; Zeus is the current source of truth.</p></>}
        {remoteLifecycle === "held_attention" && <p>The smoke job is held. Inspect the scheduler details on Zeus before continuing.</p>}
        {remoteLifecycle === "failed" && <p>The smoke job ended unsuccessfully. Screening cannot be prepared.</p>}
        {remoteLifecycle === "outputs_invalid" && <p>The job completed, but its smoke outputs did not pass scientific validation. Screening cannot be prepared.</p>}
        {remoteLifecycle === "unknown" && <p>The scheduler state could not be verified. Do not submit or advance this campaign again.</p>}
      </> : submissionState === "submitted" && submissionResult ? <><p><strong>Current stage:</strong> Smoke check.</p><p>Smoke check submitted as job {submissionResult.job_id}. You can safely close the application while Zeus runs it.</p><p>Screening remains locked until the smoke outputs are complete and validated.</p></> : submissionState === "unknown" ? <><p>The scheduler response was interrupted, so another submission could create duplicate work.</p><p>Do not submit again. Check the Zeus jobs page first.</p></> : submissionState === "terminal" ? <><p>{submissionError}</p><p>Submission controls are disabled. Check Zeus jobs before making another decision.</p></> : campaign.remote_preparation.status === "legacy-local-only" ? <><p>This campaign was created with file locations tied to another computer. Its existing records remain available for inspection, but the application cannot safely prepare or submit it on Zeus.</p><p>Create a new campaign from the same validated input source. Nothing in this campaign will be changed or deleted.</p></> : campaign.remote_preparation.status === "unavailable" ? <p>This campaign does not pass the required portability and validation checks. It remains available for inspection, but no Zeus action is offered.</p> : <><p><strong>Current prepared stage:</strong> {words(campaign.stage)}. This describes local workflow preparation; it does not mean a Zeus job is running.</p><p><strong>Scheduler status:</strong> not checked.</p></>}
      {campaign.next_plan && trusted && campaign.remote_preparation.status === "ready" && !["smoke", "refine"].includes(campaign.stage) && !remoteState && !["submitted", "unknown", "terminal"].includes(submissionState) && <><div className="copy-command"><div><span className="command-scope">{campaign.next_plan.operation_scope === "local-mutation" ? "Local state change" : "Remote submission"} · copy only</span><code>{command}</code></div><button type="button" className="secondary-button" onClick={copyCommand}><Clipboard aria-hidden="true" /> Copy command</button></div><p className="copy-status" role="status">{copyStatus}</p></>}
    </section>
    <TransferStage visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && !remoteState} snapshot={zeusSnapshot} state={transferState} preview={transferPreview} result={transferResult} error={transferError} buttonRef={reviewButton} headingRef={reviewHeading} successRef={successPanel} errorRef={errorPanel} onConnect={onConnectZeus} onPreview={() => void previewTransfer()} onConfirm={() => void confirmTransfer()} onReset={() => { setTransferError(""); setTransferPreview(null); setTransferState("idle"); }} />
    <SmokeFlow visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && Boolean(zeusSnapshot)} canSubmit={transferState === "success"} submissionState={submissionState} submissionPreview={submissionPreview} submissionResult={submissionResult} submissionError={submissionError} lifecycle={remoteState} lifecycleCheck={remoteCheck} lifecycleError={remoteError} screeningState={screeningState} screeningPreview={screeningPreview} screeningResult={screeningResult} screeningError={screeningError} onPreviewSubmission={() => void previewSubmission()} onConfirmSubmission={() => void confirmSubmission()} onResetSubmission={() => { setSubmissionError(""); setSubmissionPreview(null); setSubmissionState("idle"); }} onRefreshLifecycle={() => void refreshRemoteStatus()} onPreviewScreening={() => void previewScreening()} onConfirmScreening={() => void confirmScreening()} onResetScreening={() => { setScreeningPreview(null); setScreeningError(""); setScreeningState("idle"); }} onViewJobs={onViewJobs} />
    <ScreeningFlow visible={Boolean(remoteState?.lifecycle === "screen_prepared" || screenSubmitState === "submitted" || screenState)} evidenceFresh={remoteEvidenceFresh} smokeCheck={remoteCheck} submitState={screenSubmitState} submitPreview={screenSubmitPreview} submitResult={screenSubmitResult} submitError={screenSubmitError} lifecycle={screenState} lifecycleCheck={screenCheck} lifecycleError={screenError} prepareState={refineState} preparePreview={refinePreview} prepareResult={refineResult} prepareError={refineError} onRefreshSmoke={() => void refreshRemoteStatus()} onPreviewSubmit={() => void previewScreenSubmission()} onConfirmSubmit={() => void confirmScreenSubmission()} onResetSubmit={() => { setScreenSubmitError(""); setScreenSubmitPreview(null); setScreenSubmitState("idle"); }} onRefreshLifecycle={() => void refreshScreenStatus()} onPreviewPrepare={() => void previewRefinement()} onConfirmPrepare={() => void confirmRefinement()} onResetPrepare={() => { setRefineError(""); setRefinePreview(null); setRefineState("idle"); }} onViewJobs={onViewJobs} />
    <RefinementFlow visible={Boolean(screenState?.lifecycle === "refinement_prepared" || refineState === "success" || campaign.stage === "refine" || chainStatus) && Boolean(zeusSnapshot)} status={chainStatus} check={chainCheck} state={chainState} preview={chainPreview} result={chainResult} error={chainError} onRefresh={() => void refreshChainStatus()} onPreview={() => void previewChainSubmission()} onConfirm={() => void confirmChainSubmission()} onReset={() => { setChainError(""); setChainPreview(null); setChainState("idle"); }} onViewJobs={onViewJobs} />
    <ConfirmationStage visible={Boolean(chainStatus?.chain.status === "submitted" || chainResult || refinementLifecycleState || campaign.stage === "refine") && Boolean(zeusSnapshot)} lifecycle={refinementLifecycleState} lifecycleCheck={refinementLifecycleCheck} state={confirmationState} preview={confirmationPreview} result={confirmationResult} error={confirmationError} onRefresh={() => void refreshRefinementLifecycle()} onPreview={() => void previewConfirmation()} onConfirm={() => void confirmConfirmation()} onReset={() => { setConfirmationError(""); setConfirmationPreview(null); setConfirmationState("idle"); }} onViewJobs={onViewJobs} />
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

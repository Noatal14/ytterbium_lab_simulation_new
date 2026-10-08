import { AlertTriangle, ArrowLeft, CheckCircle2, Clipboard, Clock3, FolderSearch, LoaderCircle, RefreshCw, Server, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ScreeningSubmissionApiError, SmokeLifecycleApiError, SubmissionApiError, type Campaign, type ScreeningPreview, type ScreeningResult, type ScreeningSubmissionApi, type ScreeningSubmissionPreview, type ScreeningSubmissionResult, type SmokeLifecycle, type SmokeLifecycleApi, type SmokeSubmissionPreview, type SmokeSubmissionResult, type SubmissionApi, type TransferApi, type ZeusSnapshot, type ZeusTransferPreview, type ZeusTransferResult } from "../api/campaigns";

type ListProps = { campaigns: Campaign[]; invalidCount: number; loading: boolean; error: string | null; onOpen: (id: string) => void; restoreFocusId?: string | null };
const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

export function CampaignExplorer({ campaigns, invalidCount, loading, error, onOpen, restoreFocusId = null }: ListProps) {
  useEffect(() => {
    if (restoreFocusId) document.getElementById(`open-${restoreFocusId}`)?.focus();
  }, [restoreFocusId]);
  return <section className="section-block" id="existing-campaigns" aria-labelledby="existing-heading" aria-busy={loading}>
    <div className="section-heading"><h2 id="existing-heading">Existing campaigns</h2><p>Inspect local campaign records and validated outputs. Scheduler activity is not checked in this milestone.</p></div>
    {loading && <div className="state-panel" role="status">Looking for campaign records…</div>}
    {error && <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true" /> {error}</div>}
    {!loading && !error && campaigns.length === 0 && <div className="state-panel"><FolderSearch aria-hidden="true" /><div><strong>No campaign records found</strong><p>Create workflows arrive in a later milestone. This page only inspects campaigns already stored in the project.</p></div></div>}
    {invalidCount > 0 && <p className="warning-banner"><ShieldAlert aria-hidden="true" /> {invalidCount} unreadable or unsupported campaign {invalidCount === 1 ? "record was" : "records were"} omitted.</p>}
    <div className="campaign-list">{campaigns.map((campaign) => <article className="inspection-card" key={campaign.id}>
      <div><span className="type-label">{campaign.family === "mot_2d" ? "2D MOT" : "3D MOT"}</span>{campaign.remote_preparation.status !== "ready" && <span className="status-badge">{campaign.remote_preparation.status === "legacy-local-only" ? "Local-only campaign" : "Zeus preparation unavailable"}</span>}<h3>{campaign.name}</h3><p className="path-text">{campaign.path}</p></div>
      <dl className="campaign-facts"><div><dt>Prepared stage</dt><dd>{words(campaign.stage)}</dd></div><div><dt>Evidence role</dt><dd>{words(campaign.scientific_role)}</dd></div><div><dt>Trust</dt><dd>{words(campaign.trust)}</dd></div></dl>
      <button id={`open-${campaign.id}`} className="secondary-button" type="button" onClick={() => onOpen(campaign.id)}>Open campaign</button>
    </article>)}</div>
  </section>;
}

const bytes = (value: number) => new Intl.NumberFormat("en", { style: "unit", unit: value >= 1_000_000 ? "megabyte" : "kilobyte", unitDisplay: "short", maximumFractionDigits: 1 }).format(value / (value >= 1_000_000 ? 1_000_000 : 1_000));
const timestamp = (value: string) => new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value));

export function CampaignDetail({ campaign, onBack, transfer, submission, lifecycle, screeningSubmission, zeusSnapshot, onConnectZeus, onViewJobs }: { campaign: Campaign; onBack: () => void; transfer: TransferApi; submission: SubmissionApi; lifecycle: SmokeLifecycleApi; screeningSubmission: ScreeningSubmissionApi; zeusSnapshot: ZeusSnapshot | null; onConnectZeus: () => void; onViewJobs: () => void }) {
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
  const [submissionTerminalCode, setSubmissionTerminalCode] = useState<"already_submitted" | "smoke_already_started" | null>(null);
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
  const title = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const successPanel = useRef<HTMLDivElement>(null);
  const errorPanel = useRef<HTMLDivElement>(null);
  const submissionButton = useRef<HTMLButtonElement>(null);
  const submissionHeading = useRef<HTMLHeadingElement>(null);
  const submissionSuccess = useRef<HTMLDivElement>(null);
  const submissionErrorPanel = useRef<HTMLDivElement>(null);
  const submissionRequestActive = useRef(false);
  const remoteStatusHeading = useRef<HTMLHeadingElement>(null);
  const remoteErrorPanel = useRef<HTMLDivElement>(null);
  const screeningButton = useRef<HTMLButtonElement>(null);
  const screeningHeading = useRef<HTMLHeadingElement>(null);
  const screeningSuccess = useRef<HTMLDivElement>(null);
  const screeningErrorPanel = useRef<HTMLDivElement>(null);
  const screenSubmitButton = useRef<HTMLButtonElement>(null);
  const screenSubmitHeading = useRef<HTMLHeadingElement>(null);
  const screenSubmitPanel = useRef<HTMLDivElement>(null);
  const screenSubmitRequestActive = useRef(false);
  const previousTransferState = useRef(transferState);
  const previousSubmissionState = useRef(submissionState);
  const previousRemoteCheck = useRef(remoteCheck);
  const previousScreeningState = useRef(screeningState);
  const previousScreenSubmitState = useRef(screenSubmitState);
  useEffect(() => { title.current?.focus(); }, []);
  useEffect(() => {
    const previous = previousTransferState.current;
    if (transferError) errorPanel.current?.focus();
    else if (transferState === "review") reviewHeading.current?.focus();
    else if (transferState === "success") successPanel.current?.focus();
    else if (transferState === "idle" && previous !== "idle") reviewButton.current?.focus();
    previousTransferState.current = transferState;
  }, [transferState, transferError]);
  useEffect(() => {
    const previous = previousSubmissionState.current;
    if (submissionError) submissionErrorPanel.current?.focus();
    else if (submissionState === "review") submissionHeading.current?.focus();
    else if (submissionState === "submitted") submissionSuccess.current?.focus();
    else if (submissionState === "idle" && previous === "review") submissionButton.current?.focus();
    previousSubmissionState.current = submissionState;
  }, [submissionState, submissionError]);
  useEffect(() => {
    if (remoteError) remoteErrorPanel.current?.focus();
    else if (remoteCheck === "ready" && previousRemoteCheck.current !== "ready") remoteStatusHeading.current?.focus();
    previousRemoteCheck.current = remoteCheck;
  }, [remoteCheck, remoteError]);
  useEffect(() => {
    if (screeningError) screeningErrorPanel.current?.focus();
    else if (screeningState === "review") screeningHeading.current?.focus();
    else if (screeningState === "success") screeningSuccess.current?.focus();
    else if (screeningState === "idle" && previousScreeningState.current === "review") screeningButton.current?.focus();
    previousScreeningState.current = screeningState;
  }, [screeningState, screeningError]);
  useEffect(() => {
    const previous = previousScreenSubmitState.current;
    if (screenSubmitState === "review") screenSubmitHeading.current?.focus();
    else if (["submitted", "unknown", "terminal", "error"].includes(screenSubmitState)) screenSubmitPanel.current?.focus();
    else if (screenSubmitState === "idle" && previous === "review") screenSubmitButton.current?.focus();
    previousScreenSubmitState.current = screenSubmitState;
  }, [screenSubmitState]);
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
      if (error instanceof SubmissionApiError && error.code === "submission_outcome_unknown") {
        setSubmissionError("Submission outcome could not be verified. Do not submit again. Check Zeus jobs first."); setSubmissionState("unknown");
      } else if (error instanceof SubmissionApiError && ["already_submitted", "smoke_already_started"].includes(error.code)) {
        const code = error.code as "already_submitted" | "smoke_already_started";
        setSubmissionTerminalCode(code);
        setSubmissionError(code === "already_submitted" ? "This smoke stage already has a durable Zeus submission record. Do not submit it again." : "Smoke outputs already exist on Zeus. Do not submit this stage again; inspect the jobs and campaign status.");
        setSubmissionState("terminal");
      } else { setSubmissionError(error instanceof Error ? error.message : "Smoke submission review stopped safely."); setSubmissionState("error"); }
    }
    finally { submissionRequestActive.current = false; }
  }
  async function confirmSubmission() {
    if (!submissionPreview || submissionRequestActive.current) return;
    submissionRequestActive.current = true;
    setSubmissionState("submitting"); setSubmissionError("");
    try { setSubmissionResult(await submission.confirm(submissionPreview.preview_token)); setSubmissionState("submitted"); }
    catch (error) {
      if (error instanceof SubmissionApiError && error.code === "submission_outcome_unknown") {
        setSubmissionError("Submission outcome could not be verified. Do not submit again. Check Zeus jobs first.");
        setSubmissionState("unknown");
      } else if (error instanceof SubmissionApiError && ["already_submitted", "smoke_already_started"].includes(error.code)) {
        const code = error.code as "already_submitted" | "smoke_already_started";
        setSubmissionTerminalCode(code);
        setSubmissionError(code === "already_submitted" ? "This smoke stage already has a durable Zeus submission record. Do not submit it again." : "Smoke outputs already exist on Zeus. Do not submit this stage again; inspect the jobs and campaign status.");
        setSubmissionState("terminal");
      } else {
        setSubmissionError(error instanceof Error ? error.message : "Smoke submission stopped safely.");
        setSubmissionState("error");
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
      if (error instanceof SmokeLifecycleApiError && error.code === "screening_already_prepared") { setScreeningPreview(null); setScreeningState("idle"); await refreshRemoteStatus(); return; }
      const terminal = error instanceof SmokeLifecycleApiError && ["transition_conflict", "transition_outcome_unknown"].includes(error.code);
      setScreeningError(error instanceof Error ? error.message : "Screening preparation review stopped safely."); setScreeningState(terminal ? "terminal" : "idle");
    }
  }
  async function confirmScreening() {
    if (!screeningPreview) return;
    setScreeningState("preparing"); setScreeningError("");
    try { setScreeningResult(await lifecycle.confirm(screeningPreview.preview_token)); setScreeningState("success"); setRemoteEvidenceFresh(false); setRemoteState((current) => current ? { ...current, campaign: { ...current.campaign, stage: "screen" }, lifecycle: "screen_prepared", next_action: "none" } : current); }
    catch (error) {
      if (error instanceof SmokeLifecycleApiError && error.code === "screening_already_prepared") { setScreeningPreview(null); setScreeningState("idle"); await refreshRemoteStatus(); return; }
      const retryReview = error instanceof SmokeLifecycleApiError && ["confirmation_expired", "confirmation_invalid", "local_files_changed"].includes(error.code);
      const terminal = error instanceof SmokeLifecycleApiError && ["transition_conflict", "transition_outcome_unknown"].includes(error.code);
      setScreeningError(error instanceof Error ? error.message : "Screening preparation stopped safely.");
      if (retryReview) { setScreeningPreview(null); setScreeningState("idle"); }
      else setScreeningState(terminal ? "terminal" : "review");
    }
  }
  async function previewScreenSubmission() {
    if (!zeusSnapshot || !remoteEvidenceFresh || remoteState?.lifecycle !== "screen_prepared" || screenSubmitRequestActive.current) return;
    screenSubmitRequestActive.current = true; setScreenSubmitState("previewing"); setScreenSubmitError("");
    try { setScreenSubmitPreview(await screeningSubmission.preview(campaign.id, zeusSnapshot.profile)); setScreenSubmitState("review"); }
    catch (error) { setScreenSubmitError(error instanceof Error ? error.message : "Screening submission review stopped safely."); setScreenSubmitState(error instanceof ScreeningSubmissionApiError && ["screening_submission_outcome_unknown", "screening_submission_record_invalid", "screening_already_submitted", "screening_already_started"].includes(error.code) ? "terminal" : "error"); }
    finally { screenSubmitRequestActive.current = false; }
  }
  async function confirmScreenSubmission() {
    if (!screenSubmitPreview || screenSubmitRequestActive.current) return;
    screenSubmitRequestActive.current = true; setScreenSubmitState("submitting"); setScreenSubmitError("");
    try { setScreenSubmitResult(await screeningSubmission.confirm(screenSubmitPreview.preview_token)); setScreenSubmitState("submitted"); }
    catch (error) {
      const code = error instanceof ScreeningSubmissionApiError ? error.code : "";
      if (["confirmation_expired", "confirmation_invalid", "local_files_changed"].includes(code)) { setScreenSubmitPreview(null); setScreenSubmitError(code === "local_files_changed" ? "The campaign files changed after review. Start a fresh review before submitting." : "The review expired or is no longer valid. Start a fresh review before submitting."); setScreenSubmitState("error"); }
      else if (code === "screening_submission_outcome_unknown") { setScreenSubmitError("The submission outcome could not be verified. Do not submit again; inspect Zeus jobs."); setScreenSubmitState("unknown"); }
      else if (["screening_submission_record_invalid", "screening_already_submitted", "screening_already_started", "transition_conflict"].includes(code)) { setScreenSubmitError(error instanceof Error ? error.message : "The Screening submission needs manual verification."); setScreenSubmitState("terminal"); }
      else { setScreenSubmitError(error instanceof Error ? error.message : "Screening submission stopped safely."); setScreenSubmitState("error"); }
    } finally { screenSubmitRequestActive.current = false; }
  }
  const remoteLifecycle = remoteState?.lifecycle;
  const remotePriority = screenSubmitState === "submitted" ? "No action needed" : ["unknown", "terminal"].includes(screenSubmitState) ? "Check Zeus jobs before continuing" : remoteLifecycle === "ready_to_prepare_screen" ? "Action required" : ["queued", "running", "awaiting_outputs"].includes(remoteLifecycle ?? "") ? "No action needed" : remoteLifecycle === "screen_prepared" ? (remoteEvidenceFresh ? "Action required" : "Refresh Zeus status") : remoteLifecycle ? "Smoke check needs attention" : null;
  return <main id="main" className="detail-page">
    <button className="text-button back-button" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to campaigns</button>
    <header className="detail-hero"><p className="eyebrow">{campaign.family === "mot_2d" ? "2D-MOT campaign" : "3D-MOT campaign"}</p><h1 ref={title} tabIndex={-1}>{campaign.name}</h1><p className="path-text">{campaign.path}</p><div className="detail-badges"><span>{words(campaign.scientific_role)}</span><span className={trusted ? "badge-ok" : "badge-blocked"}>{words(campaign.trust)}</span></div></header>
    <section className={`priority-panel ${remoteLifecycle && !["queued", "running", "awaiting_outputs", "ready_to_prepare_screen", "screen_prepared"].includes(remoteLifecycle) ? "priority-panel--blocked" : trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`} aria-labelledby="priority-heading">
      <p className="eyebrow">Current priority</p><h2 id="priority-heading">{remotePriority ?? (submissionState === "submitted" || (submissionState === "terminal" && submissionTerminalCode === "already_submitted") ? "No action needed" : ["unknown", "terminal"].includes(submissionState) ? "Check Zeus jobs before continuing" : transferState === "success" ? "Smoke check ready for review" : campaign.remote_preparation.status === "legacy-local-only" ? "Recreate this campaign before using Zeus" : campaign.remote_preparation.status === "unavailable" ? "Zeus preparation is unavailable" : trusted ? (campaign.next_plan ? "Command available for review" : "No action available") : "Inspection only")}</h2>
      {remoteState ? <>
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
      {campaign.next_plan && trusted && campaign.remote_preparation.status === "ready" && campaign.stage !== "smoke" && !remoteState && !["submitted", "unknown", "terminal"].includes(submissionState) && <><div className="copy-command"><div><span className="command-scope">{campaign.next_plan.operation_scope === "local-mutation" ? "Local state change" : "Remote submission"} · copy only</span><code>{command}</code></div><button type="button" className="secondary-button" onClick={copyCommand}><Clipboard aria-hidden="true" /> Copy command</button></div><p className="copy-status" role="status">{copyStatus}</p></>}
    </section>
    {campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && !remoteState && <section className="section-block" aria-labelledby="prepare-heading"><div className="section-heading"><h2 id="prepare-heading">Prepare campaign on Zeus</h2><p>Review and transfer the exact campaign inputs. The preview checks the destination again and never starts a simulation or submits a job.</p></div>
      {!zeusSnapshot && <div className="state-panel"><Server aria-hidden="true" /><div><strong>Connect to Zeus first</strong><p>A read-only connection profile is required before the application can inspect the destination.</p><button className="secondary-button compact-action" type="button" onClick={onConnectZeus}>Open Zeus connection</button></div></div>}
      {zeusSnapshot && transferState === "idle" && <div className="prepare-card"><div><strong>Zeus connection profile selected</strong><p>{zeusSnapshot.profile.username} · {zeusSnapshot.profile.project_directory}</p><p>The destination, Git commit, working tree, and file hashes will be checked again during review.</p></div><button ref={reviewButton} className="secondary-button" type="button" onClick={() => void previewTransfer()}>Review Zeus preparation</button></div>}
      {transferState === "previewing" && <div className="state-panel" role="status"><LoaderCircle aria-hidden="true" /><div><strong>Inspecting the Zeus destination</strong><p>No files are being changed.</p></div></div>}
      {transferPreview && ["review", "preparing"].includes(transferState) && <div className="transfer-review"><div className="section-heading"><h3 ref={reviewHeading} tabIndex={-1}>Review preparation</h3><p>Only missing files will be copied. Existing identical files will be reused; any conflicting file blocks preparation.</p></div><dl className="transfer-facts"><div><dt>Destination</dt><dd>{transferPreview.destination.campaign_directory}</dd></div><div><dt>Campaign commit</dt><dd><code>{transferPreview.campaign.git_commit.slice(0, 12)}</code></dd></div><div><dt>Zeeman ensembles</dt><dd>{transferPreview.artifacts.ensemble_count}</dd></div><div><dt>Total artifacts</dt><dd>{transferPreview.artifacts.total_count}</dd></div><div><dt>Missing — will copy</dt><dd>{transferPreview.artifacts.missing_count} · {bytes(transferPreview.artifacts.missing_bytes)}</dd></div><div><dt>Already identical — will reuse</dt><dd>{transferPreview.artifacts.identical_count}</dd></div><div><dt>Total validated size</dt><dd>{bytes(transferPreview.artifacts.total_bytes)}</dd></div></dl><ul className="effect-list"><li><CheckCircle2 aria-hidden="true" /> Existing files will never be overwritten.</li><li><CheckCircle2 aria-hidden="true" /> No simulation will start.</li><li><CheckCircle2 aria-hidden="true" /> No Zeus job will be submitted.</li></ul><div className="form-actions"><button className="text-button" type="button" disabled={transferState === "preparing"} onClick={() => { setTransferError(""); setTransferPreview(null); setTransferState("idle"); }}>Cancel</button><button className="primary-button" type="button" disabled={transferState === "preparing"} onClick={() => void confirmTransfer()}>{transferState === "preparing" ? <><LoaderCircle aria-hidden="true" /> Preparing…</> : "Prepare campaign on Zeus"}</button></div></div>}
      {transferState === "success" && transferResult && <div ref={successPanel} className="connection-panel connection-panel--connected" role="status" tabIndex={-1}><CheckCircle2 aria-hidden="true" /><div><strong>Campaign prepared on Zeus</strong><p>{transferResult.transferred_count} files copied; {transferResult.reused_identical_count} identical files reused.</p><p>No simulation was started and no Zeus job was submitted.</p></div></div>}
      {transferError && <div ref={errorPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>Zeus preparation stopped safely</strong><p>{transferError}</p></div></div>}
    </section>}
    {campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && transferState === "success" && <section className="section-block" aria-labelledby="submit-heading"><div className="section-heading"><h2 id="submit-heading">Submit the smoke check</h2><p>Review the exact scheduler request before any real work is sent to Zeus.</p></div>
      {submissionState === "idle" && !submissionError && <div className="prepare-card"><div><strong>Campaign inputs are prepared</strong><p>The submission review independently checks the remote code, campaign files, and scheduler state again.</p></div><button ref={submissionButton} className="primary-button" type="button" onClick={() => void previewSubmission()}>Review smoke submission</button></div>}
      {submissionState === "previewing" && <div className="state-panel" role="status" aria-busy="true"><LoaderCircle aria-hidden="true" /><div><strong>Reviewing the smoke submission</strong><p>No job is being submitted.</p></div></div>}
      {submissionPreview && ["review", "submitting"].includes(submissionState) && <div className="transfer-review" aria-busy={submissionState === "submitting"}><div className="section-heading"><p className="eyebrow">Final review</p><h3 ref={submissionHeading} tabIndex={-1}>Submit smoke check to Zeus</h3><p>This submits only the small smoke check for this 2D-MOT campaign. It verifies that the campaign can start correctly before expensive optimization work is unlocked.</p></div><dl className="transfer-facts"><div><dt>Campaign</dt><dd>{submissionPreview.campaign.name}</dd></div><div><dt>Stage</dt><dd>{submissionPreview.stage.label}</dd></div><div><dt>Purpose</dt><dd>{submissionPreview.stage.purpose}</dd></div><div><dt>Scheduler request</dt><dd>{submissionPreview.job.kind === "array" ? `1 array job · ${submissionPreview.job.task_count} tasks · one per fixed s₀ value` : "1 PBS job · 1 task"}</dd></div><div><dt>Fixed s₀ values</dt><dd>{submissionPreview.campaign.s0_values.join(", ")}</dd></div><div><dt>Queue</dt><dd><code>{submissionPreview.job.queue}</code></dd></div><div><dt>Resources per task</dt><dd>1 CPU core · 64 GB memory</dd></div><div><dt>Walltime limit per task</dt><dd>20 minutes</dd></div><div><dt>Job file</dt><dd><code>{submissionPreview.job.file}</code></dd></div><div><dt>Remote code</dt><dd>Ready · exact commit <code>{submissionPreview.remote.commit.slice(0, 12)}</code> · clean tracked worktree</dd></div><div><dt>Campaign inputs</dt><dd>Ready · all {submissionPreview.inputs.verified_count} artifacts verified</dd></div><div><dt>Later stages</dt><dd>Locked until smoke outputs are complete and validated</dd></div></dl><ul className="effect-list"><li><CheckCircle2 aria-hidden="true" /> Submits only the smoke check.</li><li><CheckCircle2 aria-hidden="true" /> Does not submit screening or any later stage.</li><li><CheckCircle2 aria-hidden="true" /> Does not modify campaign inputs or code.</li></ul><div className="submission-attention"><strong>Attention</strong><p>Selecting Submit sends real work to Zeus. The application will record the returned job ID and will not submit again automatically.</p></div><div className="form-actions"><button className="text-button" type="button" disabled={submissionState === "submitting"} onClick={() => { setSubmissionError(""); setSubmissionPreview(null); setSubmissionState("idle"); }}>Back</button><button className="primary-button" type="button" disabled={submissionState === "submitting"} onClick={() => void confirmSubmission()}>{submissionState === "submitting" ? <><LoaderCircle aria-hidden="true" /> Submitting…</> : "Submit smoke check to Zeus"}</button></div></div>}
      {submissionState === "submitted" && submissionResult && <div ref={submissionSuccess} className="connection-panel connection-panel--connected" role="status" tabIndex={-1}><CheckCircle2 aria-hidden="true" /><div><strong>Smoke check submitted</strong><p>Zeus job {submissionResult.job_id} was recorded. No later stage was submitted.</p><p>Screening remains locked until the smoke outputs are complete and validated.</p><button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View in Zeus jobs</button></div></div>}
      {submissionError && <div ref={submissionErrorPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>{submissionState === "unknown" ? "Submission outcome needs verification" : submissionState === "terminal" ? "Smoke stage will not be resubmitted" : "Smoke submission stopped safely"}</strong><p>{submissionError}</p>{["unknown", "terminal"].includes(submissionState) ? <button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View Zeus jobs</button> : <button className="secondary-button compact-action" type="button" onClick={() => { setSubmissionError(""); setSubmissionPreview(null); setSubmissionState("idle"); }}>Review again</button>}</div></div>}
    </section>}
    {campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && zeusSnapshot && <section className="section-block" aria-labelledby="remote-smoke-heading">
      <div className="section-heading"><h2 id="remote-smoke-heading">Smoke check on Zeus</h2><p>Request a fresh, read-only check of the scheduler and scientifically validated smoke outputs.</p></div>
      <div className="remote-status-toolbar"><div><strong>Zeus is the execution source</strong><p>{remoteState ? <>Last checked <time dateTime={remoteState.queried_at}>{timestamp(remoteState.queried_at)}</time>.</> : "No current smoke snapshot is loaded."}</p></div><button className="secondary-button" type="button" disabled={remoteCheck === "checking"} onClick={() => void refreshRemoteStatus()}>{remoteCheck === "checking" ? <><LoaderCircle aria-hidden="true" /> Checking…</> : <><RefreshCw aria-hidden="true" /> {remoteState ? "Refresh smoke status" : "Check smoke status"}</>}</button></div>
      <div className="sr-only" aria-live="polite">{remoteCheck === "checking" ? "Checking smoke status on Zeus." : remoteState ? `Smoke lifecycle: ${words(remoteState.lifecycle)}.` : ""}</div>
      {remoteState && <div className={`remote-status-card remote-status-card--${remoteState.lifecycle}`}><div className="remote-status-title"><Clock3 aria-hidden="true" /><div><h3 ref={remoteStatusHeading} tabIndex={-1}>{remoteLifecycle === "ready_to_prepare_screen" ? "Smoke outputs validated" : remoteLifecycle === "screen_prepared" ? "Screening preparation complete" : `Smoke check ${words(remoteLifecycle ?? "unknown")}`}</h3><p>Job <code>{remoteState.submission.job_id}</code> · scheduler state: {words(remoteState.scheduler.state)}</p></div></div>
        {remoteState.validation.status === "valid" && <><p className="validation-note"><CheckCircle2 aria-hidden="true" /> All {remoteState.validation.artifact_count} expected artifacts passed the frozen design and provenance checks. A zero-capture smoke point is valid: this stage checks execution integrity, not performance.</p><div className="smoke-points" role="region" aria-label="Validated smoke points" tabIndex={0}><table><caption>Validated smoke points</caption><thead><tr><th scope="col">Fixed s₀</th><th scope="col">Captured</th><th scope="col">Efficiency</th></tr></thead><tbody>{remoteState.validation.points.map((point) => <tr key={point.s0}><td>{point.s0}</td><td>{point.captured} of {point.input}</td><td>{new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 }).format(point.efficiency)}</td></tr>)}</tbody></table></div></>}
        {["held_attention", "failed", "outputs_invalid", "unknown"].includes(remoteLifecycle ?? "") && <div className="status-actions"><button className="secondary-button" type="button" onClick={onViewJobs}>View Zeus jobs</button></div>}
      </div>}
      {remoteError && <div ref={remoteErrorPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>Smoke status is unavailable</strong><p>{remoteError}</p><p>No previous snapshot is being used as evidence. Try a fresh check or inspect Zeus jobs.</p><button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View Zeus jobs</button></div></div>}
    </section>}
    {remoteState?.lifecycle === "ready_to_prepare_screen" && <section className="section-block" aria-labelledby="screening-heading"><div className="section-heading"><h2 id="screening-heading">Prepare the screening stage</h2><p>Review the exact remote file transition. This does not submit screening or start a simulation.</p></div>
      {screeningState === "idle" && <div className="prepare-card"><div><strong>Validated smoke evidence is ready</strong><p>Preparation creates the task registry and PBS file, then records Screening as the prepared stage on Zeus.</p></div><button ref={screeningButton} className="primary-button" type="button" onClick={() => void previewScreening()}>Review screening preparation</button></div>}
      {screeningState === "previewing" && <div className="state-panel" role="status" aria-busy="true"><LoaderCircle aria-hidden="true" /><div><strong>Reviewing the screening transition</strong><p>No files are being changed and no job is being submitted.</p></div></div>}
      {screeningPreview && ["review", "preparing"].includes(screeningState) && <div className="transfer-review" aria-busy={screeningState === "preparing"}><div className="section-heading"><p className="eyebrow">Final review</p><h3 ref={screeningHeading} tabIndex={-1}>Prepare Screening on Zeus</h3><p>The smoke check passed for every fixed s₀ value. Review the complete file change before continuing.</p></div><dl className="transfer-facts"><div><dt>Campaign</dt><dd>{screeningPreview.campaign.name}</dd></div><div><dt>Transition</dt><dd>Smoke check → Screening</dd></div><div><dt>Validated smoke job</dt><dd><code>{screeningPreview.smoke.job_id}</code></dd></div><div><dt>Validated smoke artifacts</dt><dd>{screeningPreview.smoke.artifact_count}</dd></div><div><dt>Create</dt><dd>{screeningPreview.artifacts.create.map((path) => <code className="stacked-code" key={path}>{path}</code>)}</dd></div><div><dt>Update</dt><dd>{screeningPreview.artifacts.update.map((path) => <code className="stacked-code" key={path}>{path}</code>)}</dd></div><div><dt>Exact code</dt><dd><code>{screeningPreview.campaign.git_commit.slice(0, 12)}</code></dd></div><div><dt>Local record</dt><dd>Not synchronized after this remote transition</dd></div></dl><ul className="effect-list"><li><CheckCircle2 aria-hidden="true" /> Prepares only the Screening files.</li><li><CheckCircle2 aria-hidden="true" /> Does not submit a Zeus job.</li><li><CheckCircle2 aria-hidden="true" /> Does not start a simulation.</li><li><CheckCircle2 aria-hidden="true" /> Does not overwrite existing files.</li></ul><div className="submission-attention"><strong>Attention</strong><p>This changes the remote campaign from Smoke check to Screening. You will review the Screening job separately before it can be submitted.</p></div><div className="form-actions"><button className="text-button" type="button" disabled={screeningState === "preparing"} onClick={() => { setScreeningPreview(null); setScreeningError(""); setScreeningState("idle"); }}>Back</button><button className="primary-button" type="button" disabled={screeningState === "preparing"} onClick={() => void confirmScreening()}>{screeningState === "preparing" ? <><LoaderCircle aria-hidden="true" /> Preparing…</> : "Prepare Screening on Zeus"}</button></div></div>}
      {screeningError && <div ref={screeningErrorPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>{screeningState === "terminal" ? "Screening state needs manual verification" : "Screening preparation stopped safely"}</strong><p>{screeningError}</p>{screeningState === "terminal" && <button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View Zeus jobs</button>}</div></div>}
    </section>}
    {screeningState === "success" && screeningResult && <section className="section-block" aria-labelledby="screening-success-heading"><div ref={screeningSuccess} className="connection-panel connection-panel--connected" role="status" tabIndex={-1}><CheckCircle2 aria-hidden="true" /><div><strong id="screening-success-heading">Screening prepared on Zeus</strong><p>{screeningResult.artifacts.created} files created and {screeningResult.artifacts.updated} campaign record updated.</p><p>No Screening job was submitted and no simulation started.</p><p>Zeus is current; the local campaign record has not been synchronized.</p></div></div></section>}
    {remoteState?.lifecycle === "screen_prepared" && screenSubmitState !== "submitted" && <section className="section-block" aria-labelledby="screen-submit-section-heading"><div className="section-heading"><h2 id="screen-submit-section-heading">Submit Screening</h2><p>Submission is a separate guarded action. Review the exact PBS array before sending any work to Zeus.</p></div>
      {!remoteEvidenceFresh && <div className="prepare-card"><div><strong>Fresh Zeus evidence required</strong><p>The prepared state shown above was created locally in this session or is no longer fresh enough for submission review.</p></div><button className="secondary-button" type="button" disabled={remoteCheck === "checking"} onClick={() => void refreshRemoteStatus()}>{remoteCheck === "checking" ? <><LoaderCircle aria-hidden="true" /> Checking…</> : <><RefreshCw aria-hidden="true" /> Refresh Zeus status</>}</button></div>}
      {remoteEvidenceFresh && screenSubmitState === "idle" && <div className="prepare-card"><div><strong>Screening is prepared and verified on Zeus</strong><p>A review will revalidate the remote checkout, smoke evidence, inputs, and scheduler request. It will not submit anything.</p></div><button ref={screenSubmitButton} className="primary-button" type="button" onClick={() => void previewScreenSubmission()}>Review Screening submission</button></div>}
      {screenSubmitState === "previewing" && <div className="state-panel" role="status" aria-busy="true"><LoaderCircle aria-hidden="true" /><div><strong>Reviewing the Screening submission</strong><p>No job is being submitted.</p></div></div>}
      {screenSubmitPreview && ["review", "submitting"].includes(screenSubmitState) && <div className="transfer-review" aria-busy={screenSubmitState === "submitting"}><div className="section-heading"><p className="eyebrow">Final review</p><h3 ref={screenSubmitHeading} tabIndex={-1}>Submit Screening to Zeus</h3><p>{screenSubmitPreview.stage.purpose}</p></div><dl className="transfer-facts"><div><dt>Campaign</dt><dd>{screenSubmitPreview.campaign.name}</dd></div><div><dt>Stage</dt><dd>{screenSubmitPreview.stage.label}</dd></div><div><dt>Fixed s₀ values</dt><dd>{screenSubmitPreview.campaign.s0_values.join(", ")}</dd></div><div><dt>PBS file</dt><dd><code>{screenSubmitPreview.job.file}</code></dd></div><div><dt>Scheduler request</dt><dd>1 array job · {screenSubmitPreview.job.task_count} tasks</dd></div><div><dt>Concurrent-task limit</dt><dd>At most {screenSubmitPreview.job.array_throttle} tasks at once</dd></div><div><dt>Queue</dt><dd><code>{screenSubmitPreview.job.queue}</code></dd></div><div><dt>Resources per task</dt><dd>{screenSubmitPreview.job.cores_per_task} CPU cores · {Math.round(screenSubmitPreview.job.memory_per_task_bytes / 1024 ** 3)} GB memory</dd></div><div><dt>Walltime limit per task</dt><dd>{screenSubmitPreview.job.walltime_seconds / 3600} hours</dd></div><div><dt>Validated smoke job</dt><dd><code>{screenSubmitPreview.smoke.job_id}</code> · {screenSubmitPreview.smoke.point_count} points</dd></div><div><dt>Remote code</dt><dd>Branch {screenSubmitPreview.remote.branch} · exact commit <code>{screenSubmitPreview.remote.commit.slice(0, 12)}</code> · clean worktree</dd></div><div><dt>Campaign inputs</dt><dd>Ready · all {screenSubmitPreview.inputs.verified_count} artifacts verified</dd></div></dl><ul className="effect-list"><li><CheckCircle2 aria-hidden="true" /> Submits Screening only.</li><li><CheckCircle2 aria-hidden="true" /> Does not submit any later stage.</li><li><CheckCircle2 aria-hidden="true" /> Does not modify campaign files.</li><li><CheckCircle2 aria-hidden="true" /> Later stages remain locked.</li></ul><div className="submission-attention"><strong>One real Zeus submission</strong><p>Confirming performs exactly one <code>qsub</code> for this PBS array. Nothing is submitted automatically.</p></div><div className="form-actions"><button className="text-button" type="button" disabled={screenSubmitState === "submitting"} onClick={() => { setScreenSubmitPreview(null); setScreenSubmitError(""); setScreenSubmitState("idle"); }}>Back</button><button className="primary-button" type="button" disabled={screenSubmitState === "submitting"} onClick={() => void confirmScreenSubmission()}>{screenSubmitState === "submitting" ? <><LoaderCircle aria-hidden="true" /> Submitting…</> : "Submit Screening to Zeus"}</button></div></div>}
      {screenSubmitError && <div ref={screenSubmitPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>{screenSubmitState === "unknown" ? "Submission outcome needs manual verification" : screenSubmitState === "terminal" ? "Screening will not be submitted again" : "Screening submission stopped safely"}</strong><p>{screenSubmitError}</p>{["unknown", "terminal"].includes(screenSubmitState) ? <button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View Zeus jobs</button> : <button className="secondary-button compact-action" type="button" onClick={() => { setScreenSubmitError(""); setScreenSubmitPreview(null); setScreenSubmitState("idle"); }}>Review again</button>}</div></div>}
    </section>}
    {screenSubmitState === "submitted" && screenSubmitResult && <section className="section-block" aria-labelledby="screen-submit-success-heading"><div ref={screenSubmitPanel} className="connection-panel connection-panel--connected" role="status" tabIndex={-1}><CheckCircle2 aria-hidden="true" /><div><strong id="screen-submit-success-heading">Screening submitted</strong><p>Zeus job <code>{screenSubmitResult.job_id}</code> was recorded at <time dateTime={screenSubmitResult.submitted_at}>{timestamp(screenSubmitResult.submitted_at)}</time>.</p><p>No later stage was submitted. Zeus continues independently; no action is needed and it is safe to close this application.</p><button className="secondary-button compact-action" type="button" onClick={onViewJobs}>View in Zeus jobs</button></div></div></section>}
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

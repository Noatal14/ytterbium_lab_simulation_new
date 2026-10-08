import { AlertTriangle, ArrowLeft, CheckCircle2, Clipboard, FolderSearch, LoaderCircle, Server, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Campaign, TransferApi, ZeusSnapshot, ZeusTransferPreview, ZeusTransferResult } from "../api/campaigns";

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

export function CampaignDetail({ campaign, onBack, transfer, zeusSnapshot, onConnectZeus }: { campaign: Campaign; onBack: () => void; transfer: TransferApi; zeusSnapshot: ZeusSnapshot | null; onConnectZeus: () => void }) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const [copyStatus, setCopyStatus] = useState("");
  const [transferState, setTransferState] = useState<"idle" | "previewing" | "review" | "preparing" | "success">("idle");
  const [transferPreview, setTransferPreview] = useState<ZeusTransferPreview | null>(null);
  const [transferResult, setTransferResult] = useState<ZeusTransferResult | null>(null);
  const [transferError, setTransferError] = useState("");
  const title = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const successPanel = useRef<HTMLDivElement>(null);
  const errorPanel = useRef<HTMLDivElement>(null);
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
  return <main id="main" className="detail-page">
    <button className="text-button back-button" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to campaigns</button>
    <header className="detail-hero"><p className="eyebrow">{campaign.family === "mot_2d" ? "2D-MOT campaign" : "3D-MOT campaign"}</p><h1 ref={title} tabIndex={-1}>{campaign.name}</h1><p className="path-text">{campaign.path}</p><div className="detail-badges"><span>{words(campaign.scientific_role)}</span><span className={trusted ? "badge-ok" : "badge-blocked"}>{words(campaign.trust)}</span></div></header>
    <section className={`priority-panel ${trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{campaign.remote_preparation.status === "legacy-local-only" ? "Recreate this campaign before using Zeus" : campaign.remote_preparation.status === "unavailable" ? "Zeus preparation is unavailable" : trusted ? (campaign.next_plan ? "Command available for review" : "No action available") : "Inspection only"}</h2>{campaign.remote_preparation.status === "legacy-local-only" ? <><p>This campaign was created with file locations tied to another computer. Its existing records remain available for inspection, but the application cannot safely prepare or submit it on Zeus.</p><p>Create a new campaign from the same validated input source. Nothing in this campaign will be changed or deleted.</p></> : campaign.remote_preparation.status === "unavailable" ? <p>This campaign does not pass the required portability and validation checks. It remains available for inspection, but no Zeus action is offered.</p> : <><p><strong>Current prepared stage:</strong> {words(campaign.stage)}. This describes local workflow preparation; it does not mean a Zeus job is running.</p><p><strong>Scheduler status:</strong> not checked.</p></>}{campaign.next_plan && trusted && campaign.remote_preparation.status === "ready" && <><div className="copy-command"><div><span className="command-scope">{campaign.next_plan.operation_scope === "local-mutation" ? "Local state change" : "Remote submission"} · copy only</span><code>{command}</code></div><button type="button" className="secondary-button" onClick={copyCommand}><Clipboard aria-hidden="true" /> Copy command</button></div><p className="copy-status" role="status">{copyStatus}</p></>}</section>
    {campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && <section className="section-block" aria-labelledby="prepare-heading"><div className="section-heading"><h2 id="prepare-heading">Prepare campaign on Zeus</h2><p>Review and transfer the exact campaign inputs. The preview checks the destination again and never starts a simulation or submits a job.</p></div>
      {!zeusSnapshot && <div className="state-panel"><Server aria-hidden="true" /><div><strong>Connect to Zeus first</strong><p>A read-only connection profile is required before the application can inspect the destination.</p><button className="secondary-button compact-action" type="button" onClick={onConnectZeus}>Open Zeus connection</button></div></div>}
      {zeusSnapshot && transferState === "idle" && <div className="prepare-card"><div><strong>Zeus connection profile selected</strong><p>{zeusSnapshot.profile.username} · {zeusSnapshot.profile.project_directory}</p><p>The destination, Git commit, working tree, and file hashes will be checked again during review.</p></div><button ref={reviewButton} className="secondary-button" type="button" onClick={() => void previewTransfer()}>Review Zeus preparation</button></div>}
      {transferState === "previewing" && <div className="state-panel" role="status"><LoaderCircle aria-hidden="true" /><div><strong>Inspecting the Zeus destination</strong><p>No files are being changed.</p></div></div>}
      {transferPreview && ["review", "preparing"].includes(transferState) && <div className="transfer-review"><div className="section-heading"><h3 ref={reviewHeading} tabIndex={-1}>Review preparation</h3><p>Only missing files will be copied. Existing identical files will be reused; any conflicting file blocks preparation.</p></div><dl className="transfer-facts"><div><dt>Destination</dt><dd>{transferPreview.destination.campaign_directory}</dd></div><div><dt>Campaign commit</dt><dd><code>{transferPreview.campaign.git_commit.slice(0, 12)}</code></dd></div><div><dt>Zeeman ensembles</dt><dd>{transferPreview.artifacts.ensemble_count}</dd></div><div><dt>Total artifacts</dt><dd>{transferPreview.artifacts.total_count}</dd></div><div><dt>Missing — will copy</dt><dd>{transferPreview.artifacts.missing_count} · {bytes(transferPreview.artifacts.missing_bytes)}</dd></div><div><dt>Already identical — will reuse</dt><dd>{transferPreview.artifacts.identical_count}</dd></div><div><dt>Total validated size</dt><dd>{bytes(transferPreview.artifacts.total_bytes)}</dd></div></dl><ul className="effect-list"><li><CheckCircle2 aria-hidden="true" /> Existing files will never be overwritten.</li><li><CheckCircle2 aria-hidden="true" /> No simulation will start.</li><li><CheckCircle2 aria-hidden="true" /> No Zeus job will be submitted.</li></ul><div className="form-actions"><button className="text-button" type="button" disabled={transferState === "preparing"} onClick={() => { setTransferError(""); setTransferPreview(null); setTransferState("idle"); }}>Cancel</button><button className="primary-button" type="button" disabled={transferState === "preparing"} onClick={() => void confirmTransfer()}>{transferState === "preparing" ? <><LoaderCircle aria-hidden="true" /> Preparing…</> : "Prepare campaign on Zeus"}</button></div></div>}
      {transferState === "success" && transferResult && <div ref={successPanel} className="connection-panel connection-panel--connected" role="status" tabIndex={-1}><CheckCircle2 aria-hidden="true" /><div><strong>Campaign prepared on Zeus</strong><p>{transferResult.transferred_count} files copied; {transferResult.reused_identical_count} identical files reused.</p><p>No simulation was started and no Zeus job was submitted.</p></div></div>}
      {transferError && <div ref={errorPanel} className="state-panel state-panel--error" role="alert" tabIndex={-1}><AlertTriangle aria-hidden="true" /><div><strong>Zeus preparation stopped safely</strong><p>{transferError}</p></div></div>}
    </section>}
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

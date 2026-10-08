import { AlertTriangle, ArrowLeft, Clipboard, FolderSearch, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Campaign } from "../api/campaigns";

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

export function CampaignDetail({ campaign, onBack }: { campaign: Campaign; onBack: () => void }) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const [copyStatus, setCopyStatus] = useState("");
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus(); }, []);
  async function copyCommand() {
    try { await navigator.clipboard.writeText(command); setCopyStatus("Command copied."); }
    catch { setCopyStatus("Copy failed. Select the command text and copy it manually."); }
  }
  return <main id="main" className="detail-page">
    <button className="text-button back-button" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to campaigns</button>
    <header className="detail-hero"><p className="eyebrow">{campaign.family === "mot_2d" ? "2D-MOT campaign" : "3D-MOT campaign"}</p><h1 ref={title} tabIndex={-1}>{campaign.name}</h1><p className="path-text">{campaign.path}</p><div className="detail-badges"><span>{words(campaign.scientific_role)}</span><span className={trusted ? "badge-ok" : "badge-blocked"}>{words(campaign.trust)}</span></div></header>
    <section className={`priority-panel ${trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{campaign.remote_preparation.status === "legacy-local-only" ? "Recreate this campaign before using Zeus" : campaign.remote_preparation.status === "unavailable" ? "Zeus preparation is unavailable" : trusted ? (campaign.next_plan ? "Command available for review" : "No action available") : "Inspection only"}</h2>{campaign.remote_preparation.status === "legacy-local-only" ? <><p>This campaign was created with file locations tied to another computer. Its existing records remain available for inspection, but the application cannot safely prepare or submit it on Zeus.</p><p>Create a new campaign from the same validated input source. Nothing in this campaign will be changed or deleted.</p></> : campaign.remote_preparation.status === "unavailable" ? <p>This campaign does not pass the required portability and validation checks. It remains available for inspection, but no Zeus action is offered.</p> : <><p><strong>Current prepared stage:</strong> {words(campaign.stage)}. This describes local workflow preparation; it does not mean a Zeus job is running.</p><p><strong>Scheduler status:</strong> not checked.</p></>}{campaign.next_plan && trusted && campaign.remote_preparation.status === "ready" && <><div className="copy-command"><div><span className="command-scope">{campaign.next_plan.operation_scope === "local-mutation" ? "Local state change" : "Remote submission"} · copy only</span><code>{command}</code></div><button type="button" className="secondary-button" onClick={copyCommand}><Clipboard aria-hidden="true" /> Copy command</button></div><p className="copy-status" role="status">{copyStatus}</p></>}</section>
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

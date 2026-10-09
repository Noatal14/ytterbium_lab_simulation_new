import { AlertTriangle, FolderSearch, ShieldAlert } from "lucide-react";
import { useEffect } from "react";
import type { Campaign } from "../api/clients/campaign";

type Props = { campaigns: Campaign[]; invalidCount: number; loading: boolean; error: string | null; onRetry?: () => void; onOpen: (id: string) => void; restoreFocusId?: string | null };
const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

export function CampaignExplorer({ campaigns, invalidCount, loading, error, onRetry, onOpen, restoreFocusId = null }: Props) {
  useEffect(() => { if (restoreFocusId) document.getElementById(`open-${restoreFocusId}`)?.focus(); }, [restoreFocusId]);
  return <section className="section-block" id="existing-campaigns" aria-labelledby="existing-heading" aria-busy={loading}>
    <div className="section-heading"><h2 id="existing-heading">Existing campaigns</h2><p>Inspect local campaign records and validated outputs. Scheduler activity is not checked in this milestone.</p></div>
    {loading && <div className="state-panel" role="status">Looking for campaign records…</div>}
    {error && <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>Campaign list unavailable</strong><p>{error}</p>{onRetry && <button className="secondary-button compact-action" type="button" onClick={onRetry}>Retry campaign list</button>}</div></div>}
    {!loading && !error && campaigns.length === 0 && <div className="state-panel"><FolderSearch aria-hidden="true" /><div><strong>No campaign records found</strong><p>Create workflows arrive in a later milestone. This page only inspects campaigns already stored in the project.</p></div></div>}
    {invalidCount > 0 && <p className="warning-banner"><ShieldAlert aria-hidden="true" /> {invalidCount} unreadable or unsupported campaign {invalidCount === 1 ? "record was" : "records were"} omitted.</p>}
    <div className="campaign-list">{campaigns.map((campaign) => <article className="inspection-card" key={campaign.id}>
      <div><span className="type-label">{campaign.family === "mot_2d" ? "2D MOT" : "3D MOT"}</span>{campaign.remote_preparation.status !== "ready" && <span className="status-badge">{campaign.remote_preparation.status === "legacy-local-only" ? "Local-only campaign" : "Zeus preparation unavailable"}</span>}<h3>{campaign.name}</h3><p className="path-text">{campaign.path}</p></div>
      <dl className="campaign-facts"><div><dt>Prepared stage</dt><dd>{words(campaign.stage)}</dd></div><div><dt>Evidence role</dt><dd>{words(campaign.scientific_role)}</dd></div><div><dt>Trust</dt><dd>{words(campaign.trust)}</dd></div></dl>
      <button id={`open-${campaign.id}`} className="secondary-button" type="button" onClick={() => onOpen(campaign.id)}>Open campaign</button>
    </article>)}</div>
  </section>;
}

export { CampaignDetail } from "../features/campaign/CampaignDetail";

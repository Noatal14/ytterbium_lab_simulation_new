import { CheckCircle2, GitBranch, Server } from "lucide-react";
import { useRef, useState } from "react";
import type { Campaign, CampaignApi, CreationApi } from "./api/clients/campaign";
import type { RefinementLifecycleApi, RefinementSubmissionApi } from "./api/clients/refinement";
import type { ScreeningLifecycleApi, ScreeningSubmissionApi } from "./api/clients/screening";
import type { SmokeLifecycleApi, SubmissionApi } from "./api/clients/smoke";
import type { TransferApi, ZeusApi, ZeusSnapshot } from "./api/clients/zeus";
import { createWorkflowApiClient, type WorkflowApiClient } from "./api/workflowClient";
import { AppHeader } from "./components/AppHeader";
import { CampaignCard } from "./components/CampaignCard";
import { CampaignDetail, CampaignExplorer } from "./components/CampaignExplorer";
import { CampaignCreation } from "./components/CampaignCreation";
import { ZeusJobs } from "./components/ZeusJobs";
import { homeFixture } from "./content/home";
import { useCampaignQuery } from "./hooks/useCampaignQuery";

type AppProps = { client?: WorkflowApiClient; api?: CampaignApi; creation?: CreationApi; zeus?: ZeusApi; transfer?: TransferApi; submission?: SubmissionApi; lifecycle?: SmokeLifecycleApi; screeningSubmission?: ScreeningSubmissionApi; screeningLifecycle?: ScreeningLifecycleApi; refinementSubmission?: RefinementSubmissionApi; refinementLifecycle?: RefinementLifecycleApi };

export function App(props: AppProps = {}) {
  const [client] = useState(() => props.client ?? createWorkflowApiClient());
  const api = props.api ?? client.campaign;
  const creation = props.creation ?? client.creation;
  const zeus = props.zeus ?? client.zeus;
  const transfer = props.transfer ?? client.transfer;
  const submission = props.submission ?? client.submission;
  const lifecycle = props.lifecycle ?? client.smokeLifecycle;
  const screeningSubmission = props.screeningSubmission ?? client.screeningSubmission;
  const screeningLifecycle = props.screeningLifecycle ?? client.screeningLifecycle;
  const refinementSubmission = props.refinementSubmission ?? client.refinementSubmission;
  const refinementLifecycle = props.refinementLifecycle ?? client.refinementLifecycle;
  const { campaigns, invalidCount, loading, error: listError, refresh: refreshCampaigns } = useCampaignQuery(api);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [restoreCampaignFocus, setRestoreCampaignFocus] = useState<string | null>(null);
  const [page, setPage] = useState<"home" | "jobs">("home");
  const [zeusSnapshot, setZeusSnapshot] = useState<ZeusSnapshot | null>(null);
  const detailRequest = useRef(0);

  async function openCampaign(id: string) {
    const request = ++detailRequest.current;
    setDetailError(null); setRestoreCampaignFocus(null);
    try { const campaign = await api.get(id); if (request === detailRequest.current) setSelected(campaign); }
    catch { if (request === detailRequest.current) setDetailError("That campaign could not be opened safely. The campaign list is still available."); }
  }
  function leaveDetail(nextPage: "home" | "jobs" = "home") { detailRequest.current += 1; client.reset(); setDetailError(null); setCreating(false); setSelected(null); setPage(nextPage); }
  function startCreation() { detailRequest.current += 1; client.reset(); setDetailError(null); setSelected(null); setCreating(true); }

  return <div className="app-frame">
    <AppHeader page={page} onNavigate={(nextPage) => leaveDetail(nextPage)} />
    {page === "jobs" ? <ZeusJobs campaigns={campaigns} api={zeus} loading={loading} error={listError} onInspect={(id) => { setPage("home"); void openCampaign(id); }} savedSnapshot={zeusSnapshot} onSnapshot={setZeusSnapshot} /> : creating ? <CampaignCreation api={creation} onCreated={() => void refreshCampaigns()} onCancel={() => { client.reset(); setCreating(false); setDetailError(null); }} onInspect={(id) => { client.reset(); setCreating(false); void refreshCampaigns(); void openCampaign(id); }} /> : selected ? <CampaignDetail campaign={selected} transfer={transfer} submission={submission} lifecycle={lifecycle} screeningSubmission={screeningSubmission} screeningLifecycle={screeningLifecycle} refinementSubmission={refinementSubmission} refinementLifecycle={refinementLifecycle} zeusSnapshot={zeusSnapshot} onConnectZeus={() => { client.reset(); setSelected(null); setPage("jobs"); }} onViewJobs={() => { client.reset(); setZeusSnapshot(null); setSelected(null); setPage("jobs"); }} onBack={() => { detailRequest.current += 1; client.reset(); setDetailError(null); setRestoreCampaignFocus(selected.id); setSelected(null); }} /> : <main id="main">
      <section className="hero" aria-labelledby="page-title"><p className="eyebrow">Welcome</p><h1 id="page-title">Run or inspect a campaign</h1><p className="hero-copy">A campaign follows several ordered steps. This application will guide you through each one and explain when your input is needed.</p><dl className="status-row" aria-label="Sample environment status"><div className="status-pill"><dt><GitBranch aria-hidden="true" /> {homeFixture.environment.branchLabel}</dt><dd>{homeFixture.environment.branchValue}</dd></div><div className="status-pill"><dt><Server aria-hidden="true" /> {homeFixture.environment.zeusLabel}</dt><dd>{homeFixture.environment.zeusValue}</dd></div></dl></section>
      {detailError && <div className="state-panel state-panel--error" role="alert"><div><strong>Campaign details are unavailable</strong><p>{detailError}</p><button className="secondary-button compact-action" type="button" onClick={() => setDetailError(null)}>Dismiss</button></div></div>}
      <CampaignExplorer campaigns={campaigns} invalidCount={invalidCount} loading={loading} error={listError} onRetry={() => void refreshCampaigns()} onOpen={openCampaign} restoreFocusId={restoreCampaignFocus} />
      <section className="section-block" id="campaigns" aria-labelledby="start-heading"><div className="section-heading"><h2 id="start-heading">Start a campaign</h2><p>Configure and review a local campaign before creating any files.</p></div><div className="campaign-grid">{homeFixture.campaigns.map((campaign) => <CampaignCard key={campaign.id} {...campaign} onStart={campaign.id === "mot-2d" ? startCreation : undefined} />)}</div></section>
      <section className="section-block" aria-labelledby="workflow-heading"><div className="section-heading"><h2 id="workflow-heading">How a campaign works</h2><p>The application guides you through each transition and checks that it is safe to continue.</p></div><ol className="steps">{homeFixture.steps.map((step) => <li key={step.number}><span className="step-number">{step.number}</span><strong>{step.title}</strong><p>{step.description}</p></li>)}</ol></section>
      <p className="read-only-note"><CheckCircle2 aria-hidden="true" /> Local 2D campaign setup is available. Zeus is contacted only after an explicit connection or preparation action; jobs are never submitted automatically.</p>
    </main>}
    <footer>Local application · Zeus actions require explicit review and confirmation</footer>
  </div>;
}

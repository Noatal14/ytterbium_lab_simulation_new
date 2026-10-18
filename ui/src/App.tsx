import { zeusTestMode } from "./api/zeusEnvironment";
import { CheckCircle2, Server } from "lucide-react";
import { useRef, useState } from "react";
import type { Campaign, CampaignApi, CreationApi } from "./api/clients/campaign";
import type { ConfirmationSubmissionApi, RefinementLifecycleApi, RefinementSubmissionApi } from "./api/clients/refinement";
import type { ScreeningLifecycleApi, ScreeningSubmissionApi } from "./api/clients/screening";
import type { SmokeLifecycleApi, SubmissionApi } from "./api/clients/smoke";
import type { TransferApi, ZeusApi, ZeusSnapshot } from "./api/clients/zeus";
import { createWorkflowApiClient, type WorkflowApiClient } from "./api/workflowClient";
import { AppHeader } from "./components/AppHeader";
import { CampaignCard } from "./components/CampaignCard";
import { CampaignDetail, CampaignExplorer } from "./components/CampaignExplorer";
import { CampaignCreation } from "./components/CampaignCreation";
import { ZeusJobs } from "./components/ZeusJobs";
import { IndividualZeemanRun } from "./components/IndividualZeemanRun";
import type { IndividualZeemanApi } from "./api/clients/individualZeeman";
import { IndividualMot2DRun } from "./components/IndividualMot2DRun";
import type { IndividualMot2DApi } from "./api/clients/individualMot2D";
import type { SensitivityApi, SensitivitySubmissionApi } from "./api/clients/sensitivity";
import type { FinalizationApi, ProductionApi, ProductionSubmissionApi } from "./api/clients/production";
import { homeFixture } from "./content/home";
import { useCampaignQuery } from "./hooks/useCampaignQuery";
import { Mot3DCampaignCreation } from "./components/Mot3DCampaignCreation";
import type { Mot3DBootstrapApi } from "./api/clients/mot3d";
import type { Mot3DDiscoveryApi } from "./api/clients/mot3dDiscovery";
import { IndividualMot3DRun } from "./components/IndividualMot3DRun";
import type { IndividualMot3DApi } from "./api/clients/individualMot3D";

type AppProps = { client?: WorkflowApiClient; api?: CampaignApi; creation?: CreationApi; zeus?: ZeusApi; transfer?: TransferApi; submission?: SubmissionApi; lifecycle?: SmokeLifecycleApi; screeningSubmission?: ScreeningSubmissionApi; screeningLifecycle?: ScreeningLifecycleApi; refinementSubmission?: RefinementSubmissionApi; refinementLifecycle?: RefinementLifecycleApi; confirmationSubmission?: ConfirmationSubmissionApi; sensitivity?: SensitivityApi; sensitivitySubmission?: SensitivitySubmissionApi; production?: ProductionApi; productionSubmission?: ProductionSubmissionApi; finalization?: FinalizationApi; individualZeeman?: IndividualZeemanApi; individualMot2D?: IndividualMot2DApi; individualMot3D?: IndividualMot3DApi; mot3DBootstrap?: Mot3DBootstrapApi; mot3DDiscovery?: Mot3DDiscoveryApi };

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
  const confirmationSubmission = props.confirmationSubmission ?? client.confirmationSubmission;
  const sensitivity = props.sensitivity ?? client.sensitivity;
  const sensitivitySubmission = props.sensitivitySubmission ?? client.sensitivitySubmission;
  const production = props.production ?? client.production;
  const productionSubmission = props.productionSubmission ?? client.productionSubmission;
  const finalization = props.finalization ?? client.finalization;
  const individualZeeman = props.individualZeeman ?? client.individualZeeman;
  const individualMot2D = props.individualMot2D ?? client.individualMot2D;
  const individualMot3D = props.individualMot3D ?? client.individualMot3D;
  const mot3DBootstrap = props.mot3DBootstrap ?? client.mot3DBootstrap;
  const mot3DDiscovery = props.mot3DDiscovery ?? client.mot3DDiscovery;
  const { campaigns, invalidCount, loading, error: listError, refresh: refreshCampaigns } = useCampaignQuery(api);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [creating3D, setCreating3D] = useState(false);
  const [individualRun, setIndividualRun] = useState<"zeeman"|"mot_2d"|"mot_3d"|null>(null);
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
  function leaveDetail(nextPage: "home" | "jobs" = "home") { detailRequest.current += 1; client.reset(); setDetailError(null); setCreating(false); setCreating3D(false); setIndividualRun(null); setSelected(null); setPage(nextPage); }
  function startCreation() { detailRequest.current += 1; client.reset(); setDetailError(null); setSelected(null); setCreating(true); }

  return <div className="app-frame">
    {zeusTestMode() && <div className="state-panel" role="status"><strong>Isolated Zeus test environment</strong><p>Individual simulations use a separate test checkout and Python environment. Campaign actions are unavailable here.</p></div>}
    <AppHeader page={page} onNavigate={(nextPage) => leaveDetail(nextPage)} />
    {page === "jobs" ? <ZeusJobs campaigns={zeusTestMode() ? [] : campaigns} api={zeus} loading={loading} error={listError} onInspect={(id) => { setPage("home"); void openCampaign(id); }} savedSnapshot={zeusSnapshot} onSnapshot={setZeusSnapshot} /> : individualRun === "zeeman" ? <IndividualZeemanRun api={individualZeeman} onBack={() => { client.reset(); setIndividualRun(null); }} /> : individualRun === "mot_2d" ? <IndividualMot2DRun api={individualMot2D} onBack={() => { client.reset(); setIndividualRun(null); }} /> : individualRun === "mot_3d" ? <IndividualMot3DRun api={individualMot3D} onBack={() => { client.reset(); setIndividualRun(null); }} /> : creating3D ? <Mot3DCampaignCreation api={mot3DBootstrap} onCreated={() => void refreshCampaigns()} onBack={() => { client.reset(); setCreating3D(false); }} /> : creating ? <CampaignCreation api={creation} onCreated={() => void refreshCampaigns()} onCancel={() => { client.reset(); setCreating(false); setDetailError(null); }} onInspect={(id) => { client.reset(); setCreating(false); void refreshCampaigns(); void openCampaign(id); }} /> : selected ? <CampaignDetail campaign={selected} transfer={transfer} submission={submission} lifecycle={lifecycle} screeningSubmission={screeningSubmission} screeningLifecycle={screeningLifecycle} refinementSubmission={refinementSubmission} refinementLifecycle={refinementLifecycle} confirmationSubmission={confirmationSubmission} sensitivity={sensitivity} sensitivitySubmission={sensitivitySubmission} production={production} productionSubmission={productionSubmission} finalization={finalization} mot3DDiscovery={mot3DDiscovery} zeusSnapshot={zeusSnapshot} onConnectZeus={() => { client.reset(); setSelected(null); setPage("jobs"); }} onViewJobs={() => { client.reset(); setZeusSnapshot(null); setSelected(null); setPage("jobs"); }} onBack={() => { detailRequest.current += 1; client.reset(); setDetailError(null); setRestoreCampaignFocus(selected.id); setSelected(null); }} /> : <main id="main">
      <section className="hero" aria-labelledby="page-title"><p className="eyebrow">Welcome</p><h1 id="page-title">Run or inspect a campaign</h1><p className="hero-copy">A campaign follows several ordered steps. This application will guide you through each one and explain when your input is needed.</p></section>
      {detailError && <div className="state-panel state-panel--error" role="alert"><div><strong>Campaign details are unavailable</strong><p>{detailError}</p><button className="secondary-button compact-action" type="button" onClick={() => setDetailError(null)}>Dismiss</button></div></div>}
      {!zeusTestMode() && <CampaignExplorer campaigns={campaigns} invalidCount={invalidCount} loading={loading} error={listError} onRetry={() => void refreshCampaigns()} onOpen={openCampaign} restoreFocusId={restoreCampaignFocus} />}
      <section className="section-block" aria-labelledby="individual-heading"><div className="section-heading"><h2 id="individual-heading">Run one simulation</h2><p>Explore one reviewed setup without starting an optimization campaign.</p></div><div className="campaign-grid"><article className="single-run-card"><div><span className="type-label">Available now</span><h3>Zeeman simulation</h3><p>Choose particle count, random seed, retention, and execution location.</p></div><button className="primary-button" type="button" onClick={() => { client.reset(); setIndividualRun("zeeman"); }}><Server aria-hidden="true" /> Configure Zeeman run</button></article><article className="single-run-card"><div><span className="type-label">Available now</span><h3>2D-MOT simulation</h3><p>Select verified Zeeman survivors, MOT controls, retention, and execution location.</p></div><button className="primary-button" type="button" onClick={() => { client.reset(); setIndividualRun("mot_2d"); }}><Server aria-hidden="true" /> Configure 2D-MOT run</button></article><article className="single-run-card"><div><span className="type-label">Configuration available</span><h3>3D-MOT simulation</h3><p>Select saved 2D-MOT survivors and review an angled-donut or single-pass setup.</p></div><button className="primary-button" type="button" onClick={() => { client.reset(); setIndividualRun("mot_3d"); }}><Server aria-hidden="true" /> Configure 3D-MOT run</button></article></div></section>
      {!zeusTestMode() && <section className="section-block" id="campaigns" aria-labelledby="start-heading"><div className="section-heading"><h2 id="start-heading">Start a campaign</h2><p>Configure and review a local campaign before creating any files.</p></div><div className="campaign-grid">{homeFixture.campaigns.map((campaign) => <CampaignCard key={campaign.id} {...campaign} onStart={campaign.id === "mot-2d" ? startCreation : () => { client.reset(); setCreating3D(true); }} />)}</div></section>}
      <section className="section-block" aria-labelledby="workflow-heading"><div className="section-heading"><h2 id="workflow-heading">How a campaign works</h2><p>The application guides you through each transition and checks that it is safe to continue.</p></div><ol className="steps">{homeFixture.steps.map((step) => <li key={step.number}><span className="step-number">{step.number}</span><strong>{step.title}</strong><p>{step.description}</p></li>)}</ol></section>
      <p className="read-only-note"><CheckCircle2 aria-hidden="true" /> Local 2D campaign setup is available. Zeus is contacted only after an explicit connection or preparation action; jobs are never submitted automatically.</p>
    </main>}
    <footer>Local application · Zeus actions require explicit review and confirmation</footer>
  </div>;
}

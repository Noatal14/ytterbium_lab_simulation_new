import { CheckCircle2, GitBranch, Server } from "lucide-react";
import { useEffect, useState } from "react";
import { campaignApi, type Campaign, type CampaignApi } from "./api/campaigns";
import { AppHeader } from "./components/AppHeader";
import { CampaignCard } from "./components/CampaignCard";
import { CampaignDetail, CampaignExplorer } from "./components/CampaignExplorer";
import { homeFixture } from "./fixtures/home";

export function App({ api = campaignApi }: { api?: CampaignApi }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [invalidCount, setInvalidCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [restoreCampaignFocus, setRestoreCampaignFocus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.list().then((result) => {
      if (!active) return;
      setCampaigns(result.campaigns);
      setInvalidCount(result.invalid_count);
      setLoading(false);
    }).catch(() => {
      if (!active) return;
      setError("Campaign records are unavailable. Start the local read-only service and try again.");
      setLoading(false);
    });
    return () => { active = false; };
  }, [api]);

  async function openCampaign(id: string) {
    try { setRestoreCampaignFocus(null); setSelected(await api.get(id)); }
    catch { setError("That campaign could not be opened safely."); }
  }

  return <div className="app-frame">
    <AppHeader />
    {selected ? <CampaignDetail campaign={selected} onBack={() => { setRestoreCampaignFocus(selected.id); setSelected(null); }} /> : <main id="main">
      <section className="hero" aria-labelledby="page-title"><p className="eyebrow">Welcome</p><h1 id="page-title">Run or inspect a campaign</h1><p className="hero-copy">A campaign follows several ordered steps. This application will guide you through each one and explain when your input is needed.</p><dl className="status-row" aria-label="Sample environment status"><div className="status-pill"><dt><GitBranch aria-hidden="true" /> {homeFixture.environment.branchLabel}</dt><dd>{homeFixture.environment.branchValue}</dd></div><div className="status-pill"><dt><Server aria-hidden="true" /> {homeFixture.environment.zeusLabel}</dt><dd>{homeFixture.environment.zeusValue}</dd></div></dl></section>
      <CampaignExplorer campaigns={campaigns} invalidCount={invalidCount} loading={loading} error={error} onOpen={openCampaign} restoreFocusId={restoreCampaignFocus} />
      <section className="section-block" id="campaigns" aria-labelledby="start-heading"><div className="section-heading"><h2 id="start-heading">Start a campaign</h2><p>Campaign creation is planned for the next milestone.</p></div><div className="campaign-grid">{homeFixture.campaigns.map((campaign) => <CampaignCard key={campaign.id} {...campaign} />)}</div></section>
      <section className="section-block" aria-labelledby="workflow-heading"><div className="section-heading"><h2 id="workflow-heading">How a campaign works</h2><p>The application guides you through each transition and checks that it is safe to continue.</p></div><ol className="steps">{homeFixture.steps.map((step) => <li key={step.number}><span className="step-number">{step.number}</span><strong>{step.title}</strong><p>{step.description}</p></li>)}</ol></section>
      <p className="read-only-note"><CheckCircle2 aria-hidden="true" /> This version is read-only. It cannot create campaigns, run commands, contact Zeus, or submit jobs.</p>
    </main>}
    <footer>Local application · Scheduler status is not checked</footer>
  </div>;
}

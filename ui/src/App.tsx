import { CheckCircle2, FolderOpen, GitBranch, Server } from "lucide-react";
import { AppHeader } from "./components/AppHeader";
import { CampaignCard } from "./components/CampaignCard";
import { homeFixture } from "./fixtures/home";

export function App() {
  return (
    <div className="app-frame">
      <AppHeader />
      <main id="main">
        <section className="hero" aria-labelledby="page-title">
          <p className="eyebrow">Welcome</p>
          <h1 id="page-title">Run a new campaign</h1>
          <p className="hero-copy">A campaign follows several ordered steps. This application will guide you through each one and explain when your input is needed.</p>
          <dl className="status-row" aria-label="Sample environment status">
            <div className="status-pill">
              <dt><GitBranch aria-hidden="true" /> {homeFixture.environment.branchLabel}</dt>
              <dd>{homeFixture.environment.branchValue}</dd>
            </div>
            <div className="status-pill">
              <dt><Server aria-hidden="true" /> {homeFixture.environment.zeusLabel}</dt>
              <dd>{homeFixture.environment.zeusValue}</dd>
            </div>
          </dl>
        </section>

        <section className="section-block" id="campaigns" aria-labelledby="start-heading">
          <div className="section-heading">
            <h2 id="start-heading">Start a campaign</h2>
            <p>Choose the campaign that matches the validated input you already have.</p>
          </div>
          <div className="campaign-grid">
            {homeFixture.campaigns.map((campaign) => <CampaignCard key={campaign.id} {...campaign} />)}
          </div>
        </section>

        <section className="section-block" aria-labelledby="workflow-heading">
          <div className="section-heading">
            <h2 id="workflow-heading">How a campaign works</h2>
            <p>The application guides you through each transition and checks that it is safe to continue.</p>
          </div>
          <ol className="steps">
            {homeFixture.steps.map((step) => (
              <li key={step.number}>
                <span className="step-number">{step.number}</span>
                <strong>{step.title}</strong>
                <p>{step.description}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="existing-card" aria-labelledby="existing-heading">
          <span className="existing-icon" aria-hidden="true"><FolderOpen /></span>
          <div>
            <h2 id="existing-heading">Already have a campaign?</h2>
            <p>Open an existing campaign directory to inspect its progress and continue from the next validated step.</p>
          </div>
          <button type="button" className="secondary-button" disabled aria-describedby="open-existing-explanation">Open existing campaign · Milestone 2</button>
          <p className="action-explanation" id="open-existing-explanation">Campaign discovery is not enabled in this read-only milestone.</p>
        </section>

        <p className="read-only-note"><CheckCircle2 aria-hidden="true" /> This first version is a read-only preview. It cannot create campaigns or submit jobs.</p>
      </main>
      <footer id="zeus">Local application · No campaign is active</footer>
    </div>
  );
}

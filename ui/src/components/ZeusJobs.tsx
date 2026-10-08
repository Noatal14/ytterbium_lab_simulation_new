import { AlertTriangle, CheckCircle2, Clock3, CloudOff, LoaderCircle, PlayCircle, Server, ShieldCheck } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Campaign } from "../api/campaigns";

export type LocalJobRecord = {
  id: string;
  campaignId: string;
  name: string;
  rawState: "Q" | "R" | "F" | "X" | "H";
  state: "queued" | "running" | "completed" | "blocked";
  exitStatus: number | null;
  recordedAt: string;
};

function readiness(campaign: Campaign) {
  if (campaign.trust !== "trusted-current" || campaign.progress.some((row) => ["unknown", "inconsistent"].includes(row.status))) {
    return { label: "Blocked", tone: "blocked", detail: "This campaign is not trusted enough to show a job plan." };
  }
  if (campaign.progress.some((row) => row.status === "in-progress")) {
    return { label: "Partial local outputs", tone: "attention", detail: "Scheduler state is unknown. Check Zeus outside this application before deciding what to do." };
  }
  if (campaign.next_plan?.operation_scope === "remote-submission") {
    return { label: "Ready to copy", tone: "ready", detail: "A submission command can be previewed and copied from campaign inspection. It is never run here." };
  }
  if (campaign.next_plan?.operation_scope === "local-mutation") {
    return { label: "Ready to advance locally", tone: "ready", detail: "The next local workflow command can be copied from campaign inspection." };
  }
  return { label: "No job action available", tone: "neutral", detail: "There is no safe job action in the local campaign record." };
}

const jobIcon = { queued: Clock3, running: PlayCircle, completed: CheckCircle2, blocked: AlertTriangle };

export function ZeusJobs({ campaigns, jobs = [], loading, error, onInspect }: { campaigns: Campaign[]; jobs?: LocalJobRecord[]; loading: boolean; error: string | null; onInspect: (id: string) => void }) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus(); }, []);
  return <main id="main" className="jobs-page">
    <section className="detail-hero" aria-labelledby="jobs-title">
      <p className="eyebrow">Zeus jobs</p>
      <h1 id="jobs-title" tabIndex={-1} ref={title}>Monitor job readiness safely</h1>
      <p className="hero-copy">Review locally recorded job information and campaign readiness. This page does not connect to Zeus, refresh scheduler data, or submit work.</p>
      <div className="connection-panel" role="status">
        <CloudOff aria-hidden="true" />
        <div><strong>Zeus connection: Not configured</strong><p>Scheduler state is unavailable and may be stale. No action is required here.</p></div>
      </div>
    </section>

    <section className="section-block" aria-labelledby="job-status-heading">
      <div className="section-heading"><h2 id="job-status-heading">Recorded job status</h2><p>Statuses appear only when they were supplied by a local record. Raw PBS state is preserved for clarity.</p></div>
      <div className="job-legend" aria-label="Job status key">
        <span><i className="job-dot job-dot--queued" />Queued</span><span><i className="job-dot job-dot--running" />Running</span><span><i className="job-dot job-dot--completed" />Completed</span><span><i className="job-dot job-dot--blocked" />Blocked or held</span>
      </div>
      {jobs.length === 0 ? <div className="state-panel"><Server aria-hidden="true" /><div><strong>No locally recorded Zeus jobs</strong><p>Connect-and-refresh support belongs to a later, separately approved milestone.</p></div></div> : <div className="job-list">{jobs.map((job) => {
        const Icon = jobIcon[job.state];
        return <article className={`job-card job-card--${job.state}`} key={job.id}>
          <Icon aria-hidden="true" />
          <div><p className="type-label">{job.state}</p><h3>{job.name}</h3><p>Job {job.id} · Raw PBS state {job.rawState}</p><small>Recorded {job.recordedAt}</small></div>
          <p className="job-guidance">{job.state === "running" ? "No action needed while this job is running." : job.state === "queued" ? "No action needed while this job waits in the queue." : job.state === "completed" && job.exitStatus === 0 ? "Recorded as finished successfully. Campaign outputs still require validation." : "Attention is required outside this application."}</p>
        </article>;
      })}</div>}
    </section>

    <section className="section-block" aria-labelledby="readiness-heading">
      <div className="section-heading"><h2 id="readiness-heading">Campaign job readiness</h2><p>Readiness comes from validated local campaign files, not from the Zeus scheduler.</p></div>
      {loading ? <div className="state-panel"><LoaderCircle aria-hidden="true" /><div><strong>Checking local campaign records</strong><p>No remote connection is being made.</p></div></div> : error ? <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>Campaign readiness is unavailable</strong><p>{error}</p></div></div> : campaigns.length === 0 ? <div className="state-panel"><ShieldCheck aria-hidden="true" /><div><strong>No campaigns available</strong><p>Create or import a campaign before reviewing job readiness.</p></div></div> : <div className="readiness-list">{campaigns.map((campaign) => {
        const state = readiness(campaign);
        return <article className="readiness-card" key={campaign.id}>
          <div><p className="type-label">Current stage: {campaign.stage.replaceAll("_", " ")}</p><h3>{campaign.name}</h3><p>{state.detail}</p></div>
          <span className={`readiness-badge readiness-badge--${state.tone}`}>{state.label}</span>
          <button className="secondary-button" type="button" onClick={() => onInspect(campaign.id)}>Inspect campaign</button>
        </article>;
      })}</div>}
    </section>

    <p className="read-only-note"><ShieldCheck aria-hidden="true" /> Viewing or copying a plan is not submission. This page cannot run SSH, qsub, or any scheduler command.</p>
  </main>;
}

import { AlertTriangle, CheckCircle2, CircleHelp, Clock3, CloudOff, LoaderCircle, PlayCircle, Server, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ZeusApiError, type Campaign, type ZeusApi, type ZeusJob, type ZeusSnapshot } from "../api/campaigns";

function readiness(campaign: Campaign) {
  if (campaign.trust !== "trusted-current" || campaign.progress.some((row) => ["unknown", "inconsistent"].includes(row.status))) return { label: "Blocked", tone: "blocked", detail: "This campaign is not trusted enough to show a job plan." };
  if (campaign.progress.some((row) => row.status === "in-progress")) return { label: "Partial local outputs", tone: "attention", detail: "Scheduler state is unknown. Refresh Zeus status before deciding what to do." };
  if (campaign.next_plan?.operation_scope === "remote-submission") return { label: "Ready to copy", tone: "ready", detail: "A submission command can be previewed and copied from campaign inspection. It is never run here." };
  if (campaign.next_plan?.operation_scope === "local-mutation") return { label: "Ready to advance locally", tone: "ready", detail: "The next local workflow command can be copied from campaign inspection." };
  return { label: "No job action available", tone: "neutral", detail: "There is no safe job action in the local campaign record." };
}

const statusCopy: Record<ZeusJob["state"], { label: string; tone: string; guidance: string }> = {
  queued: { label: "Queued", tone: "queued", guidance: "No action needed while this job waits in the queue." },
  running: { label: "Running", tone: "running", guidance: "No action needed while this job is running." },
  held_attention: { label: "Held — attention needed", tone: "blocked", guidance: "A hold always needs attention. Recorded dependencies are shown only as context and do not prove that waiting is safe." },
  completed_success: { label: "Finished successfully", tone: "completed", guidance: "The scheduler reports success. Campaign outputs still require validation." },
  completed_failed: { label: "Finished with an error", tone: "blocked", guidance: "The scheduler reports a nonzero exit status. Inspect it on Zeus." },
  unknown: { label: "Unknown", tone: "blocked", guidance: "The raw PBS state could not be interpreted safely." },
};
const jobIcon = { queued: Clock3, running: PlayCircle, held_attention: AlertTriangle, completed_success: CheckCircle2, completed_failed: AlertTriangle, unknown: AlertTriangle };
const errorTitle: Record<string, string> = {
  zeus_authentication_required: "SSH authentication is required", zeus_host_key_untrusted: "Zeus host key is not trusted", zeus_timeout: "Zeus did not respond in time", zeus_unreachable: "Zeus could not be reached", remote_project_missing: "Remote project directory was not found", scheduler_unavailable: "The Zeus scheduler is unavailable", malformed_remote_response: "Zeus returned an unreadable response", zeus_check_failed: "The Zeus check failed safely", invalid_session: "The local session expired", invalid_csrf: "The local request could not be verified", rate_limited: "Please wait before checking again",
};

export function ZeusJobs({ campaigns, api, loading, error, onInspect }: { campaigns: Campaign[]; api: ZeusApi; loading: boolean; error: string | null; onInspect: (id: string) => void }) {
  const title = useRef<HTMLHeadingElement>(null);
  const [username, setUsername] = useState("");
  const [snapshot, setSnapshot] = useState<ZeusSnapshot | null>(null);
  const [connection, setConnection] = useState<"not_configured" | "checking" | "connected" | "error">("not_configured");
  const [connectionError, setConnectionError] = useState<{ code: string; message: string } | null>(null);
  const cleanUsername = username.trim();
  const usernameValid = /^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(cleanUsername);
  const usernameInvalid = cleanUsername.length > 0 && !usernameValid;
  const projectDirectory = usernameValid ? `/home/${cleanUsername}/ytterbium_lab_simulation_new` : "";
  useEffect(() => { title.current?.focus(); }, []);

  async function checkZeus() {
    if (!usernameValid) return;
    setConnection("checking"); setConnectionError(null);
    try { setSnapshot(await api.snapshot(cleanUsername, projectDirectory)); setConnection("connected"); }
    catch (caught) {
      const issue = caught instanceof ZeusApiError ? caught : new ZeusApiError("check_failed", "The read-only Zeus check failed safely.");
      setSnapshot(null); setConnectionError({ code: issue.code, message: issue.message }); setConnection("error");
    }
  }
  const stale = snapshot ? Date.now() - Date.parse(snapshot.scheduler.queried_at) > 5 * 60_000 : false;

  return <main id="main" className="jobs-page">
    <section className="detail-hero" aria-labelledby="jobs-title"><p className="eyebrow">Zeus jobs</p><h1 id="jobs-title" tabIndex={-1} ref={title}>Monitor jobs safely</h1><p className="hero-copy">Connect only when you choose to perform a read-only status check. The application cannot submit, cancel, or change a Zeus job.</p></section>

    <section className="connection-setup" aria-labelledby="connection-heading">
      <div className="section-heading"><h2 id="connection-heading">Connect to Zeus</h2><p>Enter your Technion username. The project directory is derived automatically.</p></div>
      <div className="connection-form">
        <div className="connection-field connection-field--username"><label htmlFor="technion-username">Technion username</label><input id="technion-username" value={username} onChange={(event) => { setUsername(event.target.value); setSnapshot(null); setConnection("not_configured"); setConnectionError(null); }} autoComplete="username" placeholder="for example, tal.noa" aria-invalid={usernameInvalid} aria-describedby={usernameInvalid ? "username-error" : undefined} /></div>
        <div className="connection-field connection-field--directory"><label htmlFor="remote-directory">Remote project directory</label><input id="remote-directory" value={projectDirectory} readOnly placeholder="Derived from your username" /></div>
        {usernameInvalid && <p id="username-error" className="field-error username-error" role="status">Enter the username you use to sign in to Technion services.</p>}
        <div className="authentication-note"><strong>Authentication <span className="help"><button type="button" aria-label="About SSH authentication"><CircleHelp aria-hidden="true" /></button><span role="tooltip">Uses an existing key loaded in your active SSH agent. An operating-system credential store may remember its passphrase, but the SSH agent supplies the key. The application never sees or stores your password, passphrase, or private key.</span></span></strong><p>Existing key loaded in the active SSH agent. No password is accepted or stored.</p><details className="connection-guide"><summary>First time connecting? View setup guide</summary><ol><li>Connect this computer to the Technion VPN.</li><li>Create a dedicated SSH key on this computer, not inside Zeus.</li><li>Load the private key into the active SSH agent. Your operating system may also remember its passphrase.</li><li>Before accepting any first terminal connection to <code>zeus.technion.ac.il</code>, compare the displayed server fingerprint with an official Technion source or administrator. Continue only if it matches; never disable host-key checking.</li><li>Follow the official Technion instructions to install only the <code>.pub</code> public key in your Zeus account. A terminal or portal may request your Zeus password; this application never will.</li><li>Return here and select <strong>Connect and check status</strong>.</li></ol><p>Never paste your Zeus password, private key, or key passphrase into this application, documentation, or chat.</p></details></div>
        <button className="primary-button" type="button" disabled={!usernameValid || connection === "checking"} onClick={() => void checkZeus()}>{connection === "checking" ? <><LoaderCircle aria-hidden="true" /> Checking…</> : snapshot ? "Refresh status" : "Connect and check status"}</button>
      </div>
      {connection === "not_configured" && <div className="connection-panel" role="status"><CloudOff aria-hidden="true" /><div><strong>Not connected</strong><p>No request is made until you select Connect and check status.</p></div></div>}
      {connection === "checking" && <div className="connection-panel" role="status"><LoaderCircle aria-hidden="true" /><div><strong>Checking Zeus read-only status</strong><p>No job will be submitted, cancelled, or changed.</p></div></div>}
      {connection === "error" && connectionError && <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>{errorTitle[connectionError.code] ?? "Zeus status is unavailable"}</strong><p>{connectionError.message}</p></div></div>}
      {connection === "connected" && snapshot && <div className={`connection-panel connection-panel--connected${stale ? " connection-panel--stale" : ""}`} role="status"><CheckCircle2 aria-hidden="true" /><div><strong>{stale ? "Connected — snapshot is stale" : "Connected — read-only snapshot received"}</strong><p>Branch {snapshot.remote.branch} · {snapshot.remote.dirty ? "Remote working tree has changes" : "Remote working tree is clean"}</p><p>Last checked: {new Date(snapshot.scheduler.queried_at).toLocaleString()}. Status does not update automatically.</p></div></div>}
    </section>

    <section className="section-block" aria-labelledby="job-status-heading"><div className="section-heading"><h2 id="job-status-heading">Zeus job status</h2><p>Raw PBS state and exit status are shown alongside the safe interpretation.</p></div>
      {!snapshot ? <div className="state-panel"><Server aria-hidden="true" /><div><strong>No Zeus snapshot loaded</strong><p>Connect above to request a read-only status snapshot.</p></div></div> : snapshot.scheduler.jobs.length === 0 ? <div className="state-panel"><Server aria-hidden="true" /><div><strong>No jobs were returned</strong><p>The scheduler check completed successfully.</p></div></div> : <div className="job-list">{snapshot.scheduler.jobs.map((job) => { const status = statusCopy[job.state]; const Icon = jobIcon[job.state]; return <article className={`job-card job-card--${status.tone}`} key={job.id}><Icon aria-hidden="true" /><div><p className="type-label">{status.label}</p><h3>{job.name}</h3><p>Job {job.id} · Raw PBS state {job.raw_state}{job.exit_status === null ? "" : ` · Exit ${job.exit_status}`}</p>{job.walltime && <small>Walltime {job.walltime}</small>}{job.dependencies.length > 0 && <small>Recorded dependencies: {job.dependencies.join(", ")} (context only)</small>}</div><p className="job-guidance">{status.guidance}</p></article>; })}</div>}
    </section>

    <section className="section-block" aria-labelledby="readiness-heading"><div className="section-heading"><h2 id="readiness-heading">Campaign job readiness</h2><p>Readiness comes from validated local campaign files and remains separate from scheduler status.</p></div>
      {loading ? <div className="state-panel"><LoaderCircle aria-hidden="true" /><div><strong>Checking local campaign records</strong><p>No Zeus connection is being made.</p></div></div> : error ? <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>Campaign readiness is unavailable</strong><p>{error}</p></div></div> : campaigns.length === 0 ? <div className="state-panel"><ShieldCheck aria-hidden="true" /><div><strong>No campaigns available</strong><p>Create or import a campaign before reviewing job readiness.</p></div></div> : <div className="readiness-list">{campaigns.map((campaign) => { const state = readiness(campaign); return <article className="readiness-card" key={campaign.id}><div><p className="type-label">Current stage: {campaign.stage.replaceAll("_", " ")}</p><h3>{campaign.name}</h3><p>{state.detail}</p></div><span className={`readiness-badge readiness-badge--${state.tone}`}>{state.label}</span><button className="secondary-button" type="button" onClick={() => onInspect(campaign.id)}>Inspect campaign</button></article>; })}</div>}
    </section>
    <p className="read-only-note"><ShieldCheck aria-hidden="true" /> This page performs read-only checks only. It cannot run qsub, qdel, or any scheduler mutation.</p>
  </main>;
}

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import type { useMot3DDiscoveryController } from "./controllers/useMot3DDiscoveryController";
import type { useMot3DDiscoveryTransitionController } from "./controllers/useMot3DDiscoveryTransitionController";
import { Mot3DDiscoveryStage } from "./Mot3DDiscoveryStage";

export function Mot3DCampaignFlow({ stage, connected, discovery, transition, onConnectZeus, onViewJobs }: {
  stage: string;
  connected: boolean;
  discovery: ReturnType<typeof useMot3DDiscoveryController>;
  transition: ReturnType<typeof useMot3DDiscoveryTransitionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const transitionVisible = stage === "preliminary_check" || discovery.status?.submission.status === "completed_success" || Boolean(transition.status || transition.preview || transition.result || transition.error);
  return <>
    <Mot3DDiscoveryStage visible={stage === "discovery"} connected={connected} flow={discovery} onConnectZeus={onConnectZeus} onViewJobs={onViewJobs}/>
    <Mot3DDiscoveryTransitionStage visible={transitionVisible} connected={connected} flow={transition} onConnectZeus={onConnectZeus} onViewJobs={onViewJobs}/>
  </>;
}

function Mot3DDiscoveryTransitionStage({ visible, connected, flow, onConnectZeus, onViewJobs }: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DDiscoveryTransitionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") reviewHeading.current?.focus();
    else if (["ready", "prepared", "terminal"].includes(flow.state) || flow.error) focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.discovery.status;
  const recoveryRequired = lifecycle === "preliminary_check_prepared" && flow.status?.local_sync.status === "not_synchronized";
  const attention = ["held", "completed_failed", "outputs_invalid", "status_unknown"].includes(lifecycle ?? "") || flow.status?.validation.status === "invalid" || flow.state === "terminal";
  const waiting = ["queued", "running", "completed_success_unvalidated"].includes(lifecycle ?? "");
  return <section className="section-block" aria-labelledby="mot3d-transition-heading">
    <div className="section-heading">
      <p className="eyebrow">Discovery result verification</p>
      <h2 id="mot3d-transition-heading">Prepare the independent preliminary check</h2>
      <p>Scheduler completion is not scientific validation. The application first retrieves a bounded, hash-verified Discovery result set, validates all 950 trial records, and only then prepares the next stage locally.</p>
    </div>
    <div ref={focus} tabIndex={-1}>
      {!connected && <div className="prepare-card"><div><strong>Connect to Zeus to verify Discovery</strong><p>Connecting and checking status do not submit or start any jobs.</p></div><button className="primary-button" onClick={onConnectZeus}>Connect to Zeus</button></div>}
      {connected && !flow.status && flow.state === "idle" && <div className="prepare-card"><div><strong>Verify the completed Discovery outputs</strong><p>The scheduler has finished. Scientific validation and local preparation have not happened yet.</p></div><button className="primary-button" onClick={() => void flow.refresh()}>Verify Discovery results</button></div>}
      {(flow.state === "checking" || flow.state === "synchronizing") && <Busy title={flow.state === "checking" ? "Checking and validating Discovery evidence" : "Synchronizing verified evidence and preparing the next stage"}/>} 
      {waiting && !attention && flow.state === "idle" && <div className="state-panel" role="status"><strong>{lifecycle === "completed_success_unvalidated" ? "Discovery finished; validation is still in progress" : "Discovery is still running on Zeus"}</strong><p>No action is needed. Refresh status later; the next stage stays locked until all expected outputs pass validation.</p><div className="form-actions"><button className="secondary-button" onClick={() => void flow.refresh()}>Refresh status</button><button className="text-button" onClick={onViewJobs}>Open Zeus jobs</button></div></div>}
      {flow.state === "ready" && flow.status?.validation.status === "valid" && <div className="prepare-card"><div><strong>{recoveryRequired ? "Preliminary check is prepared on Zeus; local synchronization is incomplete" : "All 950 Discovery trials are scientifically valid"}</strong><p>{recoveryRequired ? "Review the verified remote evidence to finish the interrupted local synchronization. No new job or simulation will start." : "The evidence can now be reviewed before it is synchronized and the preliminary-check files are created."}</p></div><button className="primary-button" onClick={() => void flow.review()}>Review synchronization</button></div>}
      {flow.preview && flow.state === "review" && <div className="review-panel"><p className="eyebrow">Explicit review</p><h3 ref={reviewHeading} tabIndex={-1}>Synchronize verified Discovery evidence</h3><p>This copies only the bounded, verified campaign evidence and prepares the independent preliminary check. It does not submit a Zeus job or start a simulation.</p><dl className="transfer-facts"><div><dt>Validated trial records</dt><dd>950 of 950</dd></div><div><dt>Merged evidence files</dt><dd>4 verified files</dd></div><div><dt>Candidate selections</dt><dd>2 files, one per family</dd></div><div><dt>Preliminary-check job files</dt><dd>4 files</dd></div><div><dt>Jobs submitted</dt><dd>None</dd></div><div><dt>Simulations started</dt><dd>None</dd></div></dl><p className="review-note">If synchronization is interrupted, the campaign remains blocked until its receipt and complete file set can be verified. Existing files are never silently overwritten.</p><div className="form-actions"><button className="secondary-button" onClick={flow.reset}>Back</button><button className="primary-button" onClick={() => void flow.confirm()}>Synchronize and prepare</button></div></div>}
      {flow.state === "prepared" && !flow.error && <div className="state-panel state-panel--success" role="status"><strong>Preliminary check is prepared</strong><p>Discovery evidence is synchronized and receipt-verified. No preliminary-check job has been submitted or started.</p><p>The next milestone will add a separate explicit review before those jobs can be submitted.</p></div>}
      {attention && !flow.error && <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true"/><div><strong>Manual verification required</strong><p>The Discovery outcome or scientific evidence is not safely actionable. Do not synchronize, advance, or submit again. Inspect the existing Zeus jobs and outputs.</p><div className="form-actions"><button className="secondary-button" onClick={() => void flow.refresh()}>Check status again</button><button className="text-button" onClick={onViewJobs}>Open Zeus jobs</button></div></div></div>}
      {flow.error && <div className="state-panel state-panel--error" role="alert"><AlertTriangle aria-hidden="true"/><div><strong>Discovery preparation stopped safely</strong><p>{flow.error}</p><p>No later job was submitted. Verify the existing evidence before trying another action.</p><button className="text-button" onClick={onViewJobs}>Open Zeus jobs</button></div></div>}
    </div>
  </section>;
}

function Busy({ title }: { title: string }) { return <div className="state-panel" role="status" aria-live="polite"><LoaderCircle className="spin" aria-hidden="true"/><div><strong>{title}</strong><p>No additional action is needed while this check completes.</p></div></div>; }

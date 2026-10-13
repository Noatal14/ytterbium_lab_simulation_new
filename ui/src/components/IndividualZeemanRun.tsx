import { ArrowLeft, CheckCircle2, CircleHelp, LoaderCircle, Play, Server, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { IndividualRun, IndividualZeemanApi, ZeemanMode, ZeemanPreview } from "../api/clients/individualZeeman";
import { ZEEMAN_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../generated/zeemanIndividualSpec.v1";
import { RunProgressPanel } from "./RunProgressPanel";

type Props = { api: IndividualZeemanApi; onBack: () => void };
type Step = "configure" | "review" | "run" | "monitor" | "results";
const steps: { id: Step; label: string }[] = [
  { id: "configure", label: "Configure" }, { id: "review", label: "Review" },
  { id: "run", label: "Run" }, { id: "monitor", label: "Monitor" }, { id: "results", label: "Results" },
];
const help: Record<string, string> = {
  particle_count: "The number of atoms generated at the start of this simulation. This computer supports up to 1,000; Zeus supports up to 50,000.",
  seed: "A whole number that makes the random sampling reproducible. Reusing the same reviewed settings and seed reproduces the same random inputs.",
  retain: "When selected, the surviving particle states are kept with the result. Otherwise only the summary metrics are retained.",
  mode: "Local uses this computer with a bounded worker pool. Zeus submits one scalar job only after a second explicit review.",
  npools: "The number of CPU worker processes used on this computer. Choose a value that fits the number of CPU cores available to you.",
  mot_2d_boundary: "The Zeeman simulation includes the entrance boundary of the downstream 2D MOT. These controls default to the winning 2D-MOT campaign values and may be changed for an individual run.",
  locked: "These are the complete scientific and numerical settings frozen by the reviewed laboratory policy. This screen cannot change them.",
};

function Help({ name }: { name: keyof typeof help }) { return <span className="help"><button type="button" aria-label={`Help for ${name}`}><CircleHelp aria-hidden="true" /></button><span role="tooltip">{help[name]}</span></span>; }
export function userVisibleLockedSettings(value: Record<string, unknown>) {
  const copy = structuredClone(value);
  const hideInternalControls = (item: unknown): void => {
    if (Array.isArray(item)) item.forEach(hideInternalControls);
    else if (item && typeof item === "object") {
      const row = item as Record<string, unknown>;
      delete row.swap_polarization;
      Object.values(row).forEach(hideInternalControls);
    }
  };
  hideInternalControls(copy);
  return copy;
}
function userMessage(error: unknown) { return error instanceof Error && error.message ? error.message : "The request could not be completed safely."; }
export function particleCountAfterModeChange(current: number, from: ZeemanMode, to: ZeemanMode) {
  const defaults = spec.particle_count.default_by_execution_mode;
  const maximums = spec.particle_count.maximum_by_execution_mode;
  return current === defaults[from] || current > maximums[to] ? defaults[to] : current;
}
export function monitorCopy(state: string | undefined) {
  if (!state) return { title: "Check run progress", message: "Select Check status to read the current verified progress.", attention: false };
  if (state === "configured") return { title: "Nothing is running yet", message: "Action is required: validate and review this configured run before starting it.", attention: true };
  if (state === "validated") return { title: "Validation is complete", message: "Action is required: review the validated settings before starting the run.", attention: true };
  if (state === "reviewed") return { title: "Ready to start", message: "Action is required: start the reviewed run when you are ready.", attention: true };
  if (state === "queued") return { title: "Run is queued", message: "The run was submitted and is waiting for an execution slot. No action is required.", attention: false };
  if (state === "submitted") return { title: "Run was submitted", message: "Zeus accepted the job. It may be queued or starting; no action is required.", attention: false };
  if (state === "running") return { title: "Run is in progress", message: "The simulation is currently running. No action is required.", attention: false };
  if (state === "succeeded") return { title: "Run completed", message: "The result passed verification and is ready to inspect.", attention: false };
  if (state === "failed") return { title: "Run failed safely", message: "Action is required: inspect the safe failure details before deciding what to do next.", attention: true };
  if (state === "outcome_unknown") return { title: "Zeus outcome needs attention", message: "Action is required: inspect the execution on its original system. Do not submit it again.", attention: true };
  if (state === "cancelled") return { title: "Run was cancelled", message: "No simulation result was produced. Start a new reviewed run if one is still needed.", attention: true };
  return { title: "Status is not recognized", message: "Action is required: stop and inspect the run record safely.", attention: true };
}

export function IndividualZeemanRun({ api, onBack }: Props) {
  const [step, setStep] = useState<Step>("configure");
  const [particles, setParticles] = useState<number>(spec.particle_count.default_by_execution_mode.local); const [seed, setSeed] = useState<number>(spec.seed.default);
  const [mot2dS0, setMot2dS0] = useState<number>(spec.mot_2d_controls.s0.default);
  const [mot2dDetuning, setMot2dDetuning] = useState<number>(spec.mot_2d_controls.detuning_gamma.default);
  const [mot2dRadiusMm, setMot2dRadiusMm] = useState<number>(1000 * spec.mot_2d_controls.magnet_radius_m.default);
  const [npools, setNpools] = useState<number>(spec.worker_policy.local.default);
  const [retain, setRetain] = useState(true); const [mode, setMode] = useState<ZeemanMode>("local");
  const [preview, setPreview] = useState<ZeemanPreview | null>(null); const [runId, setRunId] = useState<string | null>(null);
  const [username, setUsername] = useState(""); const [run, setRun] = useState<IndividualRun | null>(null);
  const [zeusPreviewToken, setZeusPreviewToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const request = useRef(0); const title = useRef<HTMLHeadingElement>(null);
  const stepIndex = steps.findIndex((item) => item.id === step);
  const requestBody = useMemo(() => ({ particle_count: particles, seed, mot_2d_s0: mot2dS0, mot_2d_detuning_gamma: mot2dDetuning, mot_2d_magnet_radius_m: mot2dRadiusMm / 1000, npools, retain_particle_states: retain, execution_mode: mode }), [particles, seed, mot2dS0, mot2dDetuning, mot2dRadiusMm, npools, retain, mode]);
  useEffect(() => { title.current?.focus(); }, [step]);

  async function validate() { const id = ++request.current; setBusy(true); setError(null); try { const value = await api.preview(requestBody); if (id === request.current) { setPreview({ ...value, plan: { ...value.plan, resolved_configuration: userVisibleLockedSettings(value.plan.resolved_configuration) } }); setStep("review"); } } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  async function create() { if (!preview) return; const id = ++request.current; setBusy(true); setError(null); try { const value = await api.confirm(preview.preview_token); if (id === request.current) { setRunId(value.run_id); setStep("run"); } } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  async function startLocal() { if (!runId) return; const id = ++request.current; setBusy(true); setError(null); try { await api.startLocal(runId); if (id === request.current) setStep("monitor"); } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  async function reviewZeus() { if (!runId) return; const id = ++request.current; setBusy(true); setError(null); try { const reviewed = await api.previewZeus(runId, username); if (typeof reviewed.preview_token !== "string") throw new Error("The Zeus submission review was invalid."); if (id === request.current) setZeusPreviewToken(reviewed.preview_token); } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  async function submitZeus() { if (!zeusPreviewToken) return; const id = ++request.current; setBusy(true); setError(null); try { await api.confirmZeus(zeusPreviewToken); if (id === request.current) setStep("monitor"); } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  async function refresh() { if (!runId) return; const id = ++request.current; setBusy(true); setError(null); try { if (mode === "zeus") await api.refreshZeus(runId, username); const summary = (await api.runs()).find((item) => item.display_name === runId) ?? null; if (!summary) throw new Error("The run has not appeared in the verified run list yet."); const found = summary.lifecycle === "results_ready" ? await api.run(summary.id) : summary; if (id === request.current) { setRun(found); if (found.lifecycle === "results_ready") setStep("results"); } } catch (caught) { if (id === request.current) setError(userMessage(caught)); } finally { if (id === request.current) setBusy(false); } }
  useEffect(() => { if (step !== "monitor" || mode !== "local" || !runId) return; let active = true, inFlight = false; const poll = async () => { if (inFlight) return; inFlight = true; try { const summary = (await api.runs()).find((item) => item.display_name === runId); if (active && summary) { const found = summary.lifecycle === "results_ready" ? await api.run(summary.id) : summary; if (active) { setRun(found); if (found.lifecycle === "results_ready") setStep("results"); } } } finally { inFlight = false; } }; const timer = window.setInterval(() => void poll(), 1000); return () => { active = false; window.clearInterval(timer); }; }, [api, mode, runId, step]);
  const particleMaximum = spec.particle_count.maximum_by_execution_mode[mode];
  const localWorkerMaximum = Math.min(spec.worker_policy.local.maximum, navigator.hardwareConcurrency || spec.worker_policy.local.default, particles);
  const valid = Number.isInteger(particles) && particles >= spec.particle_count.minimum && particles <= particleMaximum && Number.isInteger(seed) && seed >= spec.seed.minimum && seed <= spec.seed.maximum && mot2dS0 >= spec.mot_2d_controls.s0.minimum && mot2dS0 <= spec.mot_2d_controls.s0.maximum && mot2dDetuning >= spec.mot_2d_controls.detuning_gamma.minimum && mot2dDetuning <= spec.mot_2d_controls.detuning_gamma.maximum && mot2dRadiusMm >= 1000 * spec.mot_2d_controls.magnet_radius_m.minimum && mot2dRadiusMm <= 1000 * spec.mot_2d_controls.magnet_radius_m.maximum && Number.isInteger(npools) && (mode === "local" ? npools >= spec.worker_policy.local.minimum && npools <= localWorkerMaximum : npools === spec.worker_policy.zeus.fixed);
  function changeMode(next: ZeemanMode) { setParticles((current) => particleCountAfterModeChange(current, mode, next)); setNpools(next === "local" ? spec.worker_policy.local.default : spec.worker_policy.zeus.fixed); setMode(next); }

  return <main id="main" className="individual-run-page">
    <button className="text-button back-button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to home</button>
    <header className="detail-hero"><p className="eyebrow">Individual simulation · Zeeman</p><h1 ref={title} tabIndex={-1}>Run one Zeeman simulation</h1><p>Choose the run settings. The application validates them, shows every locked scientific setting, and asks before any work starts.</p></header>
    <ol className="run-stepper" aria-label="Run progress">{steps.map((item, index) => <li key={item.id} className={index < stepIndex ? "complete" : index === stepIndex ? "current" : "pending"} aria-current={index === stepIndex ? "step" : undefined}><span>{index < stepIndex ? <CheckCircle2 aria-hidden="true" /> : index + 1}</span>{item.label}</li>)}</ol>
    {error && <div className="state-panel state-panel--error" role="alert"><div><strong>Action needed</strong><p>{error}</p></div></div>}
    <div aria-live="polite" className="sr-only">{busy ? "Working" : `Current step: ${step}`}</div>

    {step === "configure" && <form className="creation-form" onSubmit={(event) => { event.preventDefault(); if (valid && !busy) void validate(); }}>
      <div className="run-form-grid"><div className="form-field"><label htmlFor="particle-count">Particle count <Help name="particle_count" /></label><input id="particle-count" type="number" min={spec.particle_count.minimum} max={particleMaximum} step="1" value={particles} onChange={(event) => setParticles(event.currentTarget.valueAsNumber)} /></div>
      <div className="form-field"><label htmlFor="random-seed">Random seed <Help name="seed" /></label><input id="random-seed" type="number" min={spec.seed.minimum} max={spec.seed.maximum} step="1" value={seed} onChange={(event) => setSeed(event.currentTarget.valueAsNumber)} /></div>
      {mode === "local" && <div className="form-field"><label htmlFor="zeeman-npools">CPU worker processes <Help name="npools" /></label><input id="zeeman-npools" type="number" min={spec.worker_policy.local.minimum} max={localWorkerMaximum} step="1" value={npools} onChange={(event) => setNpools(event.currentTarget.valueAsNumber)} /></div>}</div>
      <details className="advanced-settings"><summary>2D-MOT boundary settings <Help name="mot_2d_boundary" /></summary><div className="run-form-grid"><div className="form-field"><label htmlFor="zeeman-mot2d-s0">Saturation parameter (s₀)</label><input id="zeeman-mot2d-s0" type="number" min={spec.mot_2d_controls.s0.minimum} max={spec.mot_2d_controls.s0.maximum} step="0.01" value={mot2dS0} onChange={(event) => setMot2dS0(event.currentTarget.valueAsNumber)} /></div><div className="form-field"><label htmlFor="zeeman-mot2d-detuning">Detuning (Γ)</label><input id="zeeman-mot2d-detuning" type="number" min={spec.mot_2d_controls.detuning_gamma.minimum} max={spec.mot_2d_controls.detuning_gamma.maximum} step="any" value={mot2dDetuning} onChange={(event) => setMot2dDetuning(event.currentTarget.valueAsNumber)} /></div><div className="form-field"><label htmlFor="zeeman-mot2d-radius">Magnet radius (mm)</label><input id="zeeman-mot2d-radius" type="number" min={1000 * spec.mot_2d_controls.magnet_radius_m.minimum} max={1000 * spec.mot_2d_controls.magnet_radius_m.maximum} step="any" value={mot2dRadiusMm} onChange={(event) => setMot2dRadiusMm(event.currentTarget.valueAsNumber)} /></div></div></details>
      <fieldset><legend>Where should it run? <Help name="mode" /></legend><div className="choice-row"><label><input type="radio" name="mode" checked={mode === "local"} onChange={() => changeMode("local")} /> This computer</label><label><input type="radio" name="mode" checked={mode === "zeus"} onChange={() => changeMode("zeus")} /> Zeus</label></div></fieldset>
      <label className="check-control"><input type="checkbox" checked={retain} onChange={(event) => setRetain(event.currentTarget.checked)} /><span><strong>Keep survivor particle states</strong><small>Required only if you want to inspect or reuse the particle states later.</small></span><Help name="retain" /></label>
      <div className="form-actions"><button className="primary-button" disabled={!valid || busy}>{busy ? "Validating…" : "Validate and review"}</button></div>
    </form>}

    {step === "review" && preview && <section className="run-stage" aria-labelledby="review-title"><div className="section-heading"><h2 id="review-title">Validated run plan</h2><p>No files have been created and no work has started.</p></div><div className="scientific-role-note"><strong>Scientific role: individual only</strong><p>This run is for inspection or individual follow-up. Even when particle states are retained, they are not validated campaign inputs unless a separate campaign-input validation accepts them.</p></div><div className="review-grid"><article className="review-card"><h3>Your choices</h3><dl><div><dt>Particles</dt><dd>{preview.plan.particle_count.toLocaleString()}</dd></div><div><dt>Seed</dt><dd>{preview.plan.seed}</dd></div><div><dt>2D-MOT boundary</dt><dd>s₀ {preview.plan.mot_2d_s0} · {preview.plan.mot_2d_detuning_gamma} Γ · {(1000 * preview.plan.mot_2d_magnet_radius_m).toFixed(3)} mm</dd></div><div><dt>CPU workers</dt><dd>{preview.plan.npools}</dd></div><div><dt>Execution</dt><dd>{preview.plan.execution_mode === "local" ? "This computer" : "Zeus"}</dd></div><div><dt>Particle states</dt><dd>{preview.plan.retain_particle_states ? "Keep after completion" : "Do not keep"}</dd></div></dl></article><article className="review-card"><h3>Locked scientific settings <Help name="locked" /></h3><p>Canonical laboratory and numerical settings are frozen for this run.</p><details><summary>View all locked settings</summary><pre className="settings-json">{JSON.stringify(preview.plan.resolved_configuration, null, 2)}</pre></details></article></div><div className="form-actions"><button className="secondary-button" onClick={() => { setPreview(null); setStep("configure"); }}>Change choices</button><button className="primary-button" disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create reviewed run"}</button></div></section>}

    {step === "run" && runId && <section className="run-stage"><div className="action-banner"><ShieldCheck aria-hidden="true" /><div><strong>Reviewed run is ready</strong><p>Nothing is running yet. Start only when you are ready.</p></div></div>{mode === "zeus" && <div className="form-field zeus-run-profile"><label htmlFor="zeus-username">Technion username<span>Used to connect with your existing SSH key. The remote project directory is derived automatically.</span></label><input id="zeus-username" value={username} placeholder="for example, tal.noa" pattern="[A-Za-z][A-Za-z0-9._-]{0,31}" disabled={zeusPreviewToken !== null} onChange={(event) => setUsername(event.currentTarget.value)} /></div>}{zeusPreviewToken && <div className="submission-attention" role="status"><strong>One scalar Zeus job is ready for confirmation</strong><p>The frozen package was checked. Confirm below to submit exactly one job; no later job is submitted automatically.</p></div>}<div className="form-actions">{mode === "local" ? <button className="primary-button" disabled={busy} onClick={() => void startLocal()}><Play aria-hidden="true" /> {busy ? "Starting…" : "Start on this computer"}</button> : zeusPreviewToken ? <><button className="secondary-button" disabled={busy} onClick={() => setZeusPreviewToken(null)}>Change connection</button><button className="primary-button" disabled={busy} onClick={() => void submitZeus()}><Server aria-hidden="true" /> {busy ? "Submitting…" : "Confirm and submit one Zeus job"}</button></> : <button className="primary-button" disabled={busy || !/^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(username)} onClick={() => void reviewZeus()}><Server aria-hidden="true" /> {busy ? "Checking…" : "Review Zeus submission"}</button>}</div></section>}

    {step === "monitor" && <section className="run-stage">{(() => { const copy = monitorCopy(run?.record_state); return <div className={`action-banner${copy.attention ? " action-banner--attention" : " action-banner--running"}`}><LoaderCircle className={busy ? "spin" : ""} aria-hidden="true" /><div><strong>{copy.title}</strong><p>{copy.message}</p></div></div>; })()}{mode === "local" && <RunProgressPanel progress={run?.execution.progress ?? null} />}{run && <dl className="monitor-facts"><div><dt>Status</dt><dd>{run.record_state.replaceAll("_", " ")}</dd></div><div><dt>Execution</dt><dd>{run.execution.mode === "local" ? "This computer" : `Zeus${run.execution.zeus_job_id ? ` · ${run.execution.zeus_job_id}` : ""}`}</dd></div><div><dt>Particle states</dt><dd>{run.retention.status.replaceAll("_", " ")}</dd></div></dl>}<div className="form-actions"><button className="secondary-button" disabled={busy} onClick={() => void refresh()}>{busy ? "Checking…" : "Check status"}</button></div></section>}

    {step === "results" && run && <section className="run-stage"><div className="success-panel"><CheckCircle2 aria-hidden="true" /><h2>Verified results are ready</h2><p>The run completed and its result package passed integrity checks.</p></div><div className="scientific-role-note"><strong>Scientific role: individual only</strong><p>These results support inspection or individual follow-up. Retained particle states are not validated campaign inputs unless they pass a separate campaign-input validation.</p></div><div className="review-grid"><article className="review-card"><h3>Summary</h3><dl>{Object.entries(run.metrics ?? {}).map(([key, value]) => <div key={key}><dt>{key === "elapsed_s" ? "Runtime" : key.replaceAll("_", " ")}</dt><dd>{key === "elapsed_s" && typeof value === "number" ? `${value.toFixed(3)} s` : String(value)}</dd></div>)}</dl></article><article className="review-card"><h3>Saved output</h3><p>{run.retention.status === "retained" ? "Survivor particle states were retained with this result." : "Only summary results were retained, as requested."}</p></article></div></section>}
  </main>;
}

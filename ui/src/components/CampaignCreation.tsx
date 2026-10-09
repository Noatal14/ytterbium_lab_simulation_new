import { ArrowLeft, HelpCircle, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { creationApi, type CreationApi, type CreationPreview, type CreationResult, type ZeemanSource } from "../api/campaigns";

type Values = { name: string; slug: string; sourceId: string; s0: string };

function Help({ label, children }: { label: string; children: string }) {
  return <span className="help"><button type="button" aria-label={label}><HelpCircle aria-hidden="true" /></button><span role="tooltip">{children}</span></span>;
}

export function CampaignCreation({ onCancel, onInspect, onCreated, api = creationApi }: { onCancel: () => void; onInspect: (id: string) => void; onCreated?: (result: CreationResult) => void; api?: CreationApi }) {
  const [step, setStep] = useState<"configure" | "review" | "success">("configure");
  const [values, setValues] = useState<Values>({ name: "", slug: "", sourceId: "", s0: "" });
  const [sources, setSources] = useState<ZeemanSource[]>([]);
  const [sourceState, setSourceState] = useState<"loading" | "ready" | "error">("loading");
  const [csrf, setCsrf] = useState("");
  const [preview, setPreview] = useState<CreationPreview | null>(null);
  const [result, setResult] = useState<CreationResult | null>(null);
  const [actionState, setActionState] = useState<"idle" | "busy">("idle");
  const [actionError, setActionError] = useState("");
  const title = useRef<HTMLHeadingElement>(null);
  const parsed = useMemo(() => values.s0.split(/[\s,]+/).filter(Boolean).map(Number), [values.s0]);
  const validS0 = parsed.length > 0 && parsed.length <= 16 && parsed.every((value) => Number.isFinite(value) && value > 0);
  const valid = values.name.trim() && /^[a-z0-9][a-z0-9._-]{0,63}$/.test(values.slug) && values.sourceId && validS0;
  const field = (key: keyof Values) => ({ value: values[key], onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setValues({ ...values, [key]: event.target.value }) });
  async function loadLocalInputs() {
    setSourceState("loading"); setActionError("");
    try {
      const [rows, token] = await Promise.all([api.sources(), api.session()]);
      setSources(rows); setCsrf(token); setSourceState("ready");
    } catch {
      setSources([]); setCsrf(""); setSourceState("error");
    }
  }
  useEffect(() => { void loadLocalInputs(); }, [api]);
  useEffect(() => { if (step !== "configure") title.current?.focus(); }, [step]);
  async function review() { setActionState("busy"); setActionError(""); try { const row = await api.preview({ name: values.name.trim(), slug: values.slug, source_id: values.sourceId, s0_values: [...new Set(parsed)] }, csrf); setPreview(row); setStep("review"); } catch (error) { setActionError(error instanceof Error ? error.message : "Preview failed safely."); } finally { setActionState("idle"); } }
  async function create() { const token = preview?.preview_token; if (typeof token !== "string") return; setActionState("busy"); setActionError(""); try { const created = await api.confirm(token, csrf); setResult(created); onCreated?.(created); setStep("success"); } catch (error) { setActionError(error instanceof Error ? error.message : "Creation failed safely."); } finally { setActionState("idle"); } }
  if (step === "success") return <main id="main" className="creation-page"><header className="success-panel"><ShieldCheck aria-hidden="true" /><p className="eyebrow">Local creation complete</p><h1 ref={title} tabIndex={-1}>Campaign created and validated</h1><p>The campaign record and initial smoke-job file were created locally. No simulation was run and no work was submitted to Zeus.</p><code>{String(result?.path ?? "")}</code><button className="primary-button" type="button" onClick={onCancel}>Return to campaigns</button></header></main>;
  if (step === "review") return <main id="main" className="creation-page"><button className="text-button back-button" onClick={() => { setPreview(null); setStep("configure"); }}><ArrowLeft aria-hidden="true" /> Back to configuration</button><header className="detail-hero"><p className="eyebrow">2D-MOT campaign · Review</p><h1 ref={title} tabIndex={-1}>Review before creating</h1><p>Nothing has been created and no Zeus work will be submitted.</p></header>{preview?.duplicate ? <section className="priority-panel priority-panel--blocked"><h2>Equivalent campaign already exists</h2><p>Inspect the existing campaign instead of repeating the same frozen design.</p>{preview.duplicate.campaign_id && <button className="primary-button" type="button" onClick={() => onInspect(preview.duplicate!.campaign_id!)}>Inspect existing campaign</button>}</section> : <><section className="review-grid">
    <div className="review-card"><h2>Campaign</h2><dl><div><dt>Name</dt><dd>{values.name}</dd></div><div><dt>Output</dt><dd>data/optimization/mot_2d/{values.slug}</dd></div><div><dt>Fixed s₀</dt><dd>{[...new Set(parsed)].join(", ")}</dd></div></dl></div>
    <div className="review-card"><h2>Scientific safeguards <Help label="Explain scientific safeguards">The campaign freezes the code revision, physical-model hash, exact input ensembles, seeds, solver, timesteps, bounds and trial budgets so later stages cannot silently change the design.</Help></h2><dl><div><dt>Solver <Help label="Explain RK4StHybridCustom">RK4StHybridCustom samples photon counts from a Poisson distribution below 15 expected photons per timestep, with event-matched isotropic recoil, and uses a Gaussian approximation at higher counts.</Help></dt><dd>RK4StHybridCustom</dd></div><div><dt>Screening timestep <Help label="Explain screening timestep">The 1.25 µs timestep is used for broad screening and refinement to reduce runtime.</Help></dt><dd>1.25 µs</dd></div><div><dt>Final timestep <Help label="Explain final timestep">The finer 0.625 µs timestep is used for confirmation, sensitivity and sealed final validation.</Help></dt><dd>0.625 µs</dd></div></dl></div>
    <div className="review-card"><h2>Frozen creation plan</h2><dl><div><dt>Validated inputs</dt><dd>{preview?.provenance.input_count} Zeeman ensembles</dd></div><div><dt>Initial stage</dt><dd>Smoke check</dd></div><div><dt>Files</dt><dd>{preview?.plan?.files.join(", ")}</dd></div><div><dt>Code revision</dt><dd>{preview?.provenance.commit.slice(0, 8)}</dd></div></dl></div>
  </section><section className="priority-panel" aria-labelledby="create-heading"><p className="eyebrow">Final confirmation</p><h2 id="create-heading">Create local campaign files</h2><p>This will create the campaign record and initial smoke-job file only. It will not run a simulation, connect to Zeus, or submit a job.</p>{actionError && <p role="alert" className="field-error">{actionError}</p>}<button className="primary-button" onClick={create} disabled={actionState === "busy"}>{actionState === "busy" ? "Creating…" : "Create campaign"}</button></section></>}</main>;
  return <main id="main" className="creation-page"><button className="text-button back-button" onClick={onCancel}><ArrowLeft aria-hidden="true" /> Back to home</button><header className="detail-hero"><p className="eyebrow">2D-MOT campaign · Configure</p><h1>Create a 2D-MOT campaign</h1><p>Choose the frozen inputs and fixed laser intensities. You will review the full scientific design before any local files are created.</p></header><form className="creation-form" onSubmit={(event) => { event.preventDefault(); if (valid) void review(); }}>
    <label>Campaign name<span>A readable name shown in the application.</span><input {...field("name")} placeholder="For example: Fixed s0 1.3 campaign" required /></label>
    <label>Campaign folder<span>A new folder created under data/optimization/mot_2d/.</span><input {...field("slug")} placeholder="for example: s0_1p3_20261008" pattern="[a-z0-9][a-z0-9._-]{0,63}" required /></label>
    <div className="form-field"><label>Zeeman ensemble source<span>Select the folder containing the Zeeman survivor states used as the initial states before the 2D MOT. Sources come from data/particle_states/after_zeeman/…</span><select {...field("sourceId")} required disabled={sourceState !== "ready" || sources.length === 0}><option value="">{sourceState === "loading" ? "Validating local sources…" : sourceState === "error" ? "Local source service is unavailable" : sources.length === 0 ? "No validated sources found" : "Select a validated source"}</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.path}</option>)}</select></label>{sourceState === "error" && <small className="field-error" role="alert">The local campaign service is not available. Start the application with <code>npm run dev</code>, then retry. <button type="button" className="inline-retry" onClick={() => void loadLocalInputs()}>Retry</button></small>}{sourceState === "ready" && sources.length === 0 && <small className="field-warning" role="status">The service is connected, but no folder contains all 35 validated Zeeman ensembles.</small>}</div>
    <label>Fixed s₀ values<span>Enter one or more positive values separated by commas. Each value gets its own detuning/radius optimization.</span><input {...field("s0")} placeholder="1.3 or 1.2, 1.3, 1.4" inputMode="decimal" required />{values.s0 && !validS0 && <small className="field-error">Enter between 1 and 16 positive finite values.</small>}</label>
    {actionError && <p role="alert" className="field-error">{actionError}</p>}<div className="form-actions"><button type="button" className="text-button" onClick={onCancel}>Cancel</button><button type="submit" className="primary-button" disabled={!valid || actionState === "busy"}>{actionState === "busy" ? "Validating…" : "Review campaign"}</button></div>
  </form><p className="read-only-note"><ShieldCheck aria-hidden="true" /> Review does not create files or submit work.</p></main>;
}

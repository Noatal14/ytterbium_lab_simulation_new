import { ArrowLeft, Clock3, ShieldCheck, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Mot3DBootstrapApi,
  Mot3DBootstrapPreview,
  Mot3DBootstrapResult,
  Mot3DBootstrapStatus,
} from "../api/clients/mot3d";

type Step =
  "loading" | "configure" | "review" | "success" | "error";

export function Mot3DCampaignCreation({
  api,
  onBack,
  onCreated,
}: {
  api: Mot3DBootstrapApi;
  onBack: () => void;
  onCreated?: () => void;
}) {
  const [step, setStep] = useState<Step>("loading");
  const [status, setStatus] = useState<Mot3DBootstrapStatus | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [campaignName, setCampaignName] = useState("");
  const [preview, setPreview] = useState<Mot3DBootstrapPreview | null>(null);
  const [result, setResult] = useState<Mot3DBootstrapResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const generation = useRef(0);
  const busyRef = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const validName = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(campaignName);

  const load = useCallback(async () => {
    const request = ++generation.current;
    setStep("loading");
    setMessage("");
    try {
      const next = await api.status();
      if (request !== generation.current) return;
      setStatus(next);
      setStep("configure");
    } catch (error) {
      if (request !== generation.current) return;
      setMessage(
        error instanceof Error
          ? error.message
          : "3D campaign readiness could not be checked safely.",
      );
      setStep("error");
    }
  }, [api]);

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
      busyRef.current = false;
      api.reset();
    };
  }, [api, load]);
  useEffect(() => {
    if (step !== "loading") heading.current?.focus();
  }, [step]);

  async function review() {
    if (busyRef.current) return;
    busyRef.current = true;
    const request = ++generation.current;
    setBusy(true);
    setMessage("");
    try {
      const next = await api.preview(sourceId, campaignName);
      if (request !== generation.current) return;
      setPreview(next);
      setStep("review");
    } catch (error) {
      if (request === generation.current)
        setMessage(
          error instanceof Error
            ? error.message
            : "The 3D campaign could not be reviewed safely.",
        );
    } finally {
      if (request === generation.current) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  async function confirm() {
    if (!preview || busyRef.current) return;
    busyRef.current = true;
    const request = ++generation.current;
    setBusy(true);
    setMessage("");
    try {
      const next = await api.confirm(
        preview.preview_token,
        preview.campaign.name,
      );
      if (request !== generation.current) return;
      setResult(next);
      setStep("success");
      onCreated?.();
    } catch (error) {
      if (request === generation.current)
        setMessage(
          error instanceof Error
            ? error.message
            : "The 3D campaign was not created.",
        );
    } finally {
      if (request === generation.current) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  const back = (
    <button type="button" className="text-button back-button" onClick={onBack}>
      <ArrowLeft aria-hidden="true" /> Back to home
    </button>
  );
  if (step === "loading")
    return (
      <main id="main" className="creation-page" aria-live="polite">
        {back}
        <section className="state-panel">
          <Clock3 aria-hidden="true" />
          <div>
            <strong>Checking 3D campaign readiness…</strong>
            <p>
              The application is validating the frozen pragmatic timestep
              policy and completed 2D inputs.
            </p>
          </div>
        </section>
      </main>
    );
  if (step === "error")
    return (
      <main id="main" className="creation-page">
        {back}
        <section className="state-panel state-panel--error" role="alert">
          <div>
            <h1 ref={heading} tabIndex={-1}>
              3D campaign readiness is unavailable
            </h1>
            <p>{message}</p>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void load()}
            >
              Try again
            </button>
          </div>
        </section>
      </main>
    );
  if (step === "success")
    return (
      <main id="main" className="creation-page">
        {back}
        <header className="success-panel">
          <ShieldCheck aria-hidden="true" />
          <p className="eyebrow">3D-MOT campaign</p>
          <h1 ref={heading} tabIndex={-1}>
            Discovery campaign prepared
          </h1>
          <p>
            <strong>{result?.campaign_name}</strong> was created from the
            reviewed, sealed 2D handoff. No job was submitted to Zeus.
          </p>
          <p>
            Discovery is a broad comparison of the angled-donut and single-pass
            families. It does not select a final design or report final
            performance.
          </p>
          <button type="button" className="primary-button" onClick={onBack}>
            Return to campaigns
          </button>
        </header>
      </main>
    );
  if (step === "review" && preview)
    return (
      <main id="main" className="creation-page">
        <button
          type="button"
          className="text-button back-button"
          onClick={() => {
            generation.current += 1;
            busyRef.current = false;
            api.reset();
            setPreview(null);
            setMessage("");
            setStep("configure");
          }}
        >
          <ArrowLeft aria-hidden="true" /> Back to configuration
        </button>
        <header className="detail-hero">
          <p className="eyebrow">3D-MOT campaign · Review</p>
          <h1 ref={heading} tabIndex={-1}>
            Review the Discovery bootstrap
          </h1>
          <p>Nothing has been created and no work has been submitted.</p>
        </header>
        <section className="review-grid">
          <div className="review-card">
            <h2>Completed 2D handoff</h2>
            <dl>
              <div>
                <dt>Campaign</dt>
                <dd>{preview.source.campaign_name}</dd>
              </div>
              <div>
                <dt>Fixed s₀</dt>
                <dd>{preview.source.s0}</dd>
              </div>
              <div>
                <dt>Sealed ensembles</dt>
                <dd>{preview.source.sealed_ensemble_count}</dd>
              </div>
              <div>
                <dt>Evidence fingerprint</dt>
                <dd>
                  <code>
                    {preview.source.provenance_fingerprint.slice(0, 12)}
                  </code>
                </dd>
              </div>
            </dl>
          </div>
          <div className="review-card">
            <h2>Locked numerical design</h2>
            <dl>
              <div>
                <dt>Solver</dt>
                <dd>{preview.discovery.solver}</dd>
              </div>
              <div>
                <dt>Search-stage timestep</dt>
                <dd>{preview.discovery.screening_dt_s * 1_000_000} µs</dd>
              </div>
              <div>
                <dt>Sealed final-validation timestep</dt>
                <dd>{preview.discovery.production_dt_s * 1_000_000} µs</dd>
              </div>
              <div>
                <dt>Convergence claim</dt>
                <dd>Not established</dd>
              </div>
              <div>
                <dt>Input roles</dt>
                <dd>12 Discovery · 4 Refinement · 4 preliminary check</dd>
              </div>
            </dl>
          </div>
          <div className="review-card">
            <TriangleAlert aria-hidden="true" />
            <h2>Pragmatic timestep policy</h2>
            <p>
              The one-off study was inconclusive. The reviewed policy uses 10
              µs to make the search stages practical and 5 µs only for the
              sealed final validation. It is not evidence that 10 µs has
              converged.
            </p>
          </div>
          <div className="review-card">
            <h2>What this creates</h2>
            <p>
              A frozen local campaign record and the existing Discovery job
              chain for both geometry families.
            </p>
            <p>
              It does not rerun timestep validation, start a simulation, or
              submit a job.
            </p>
          </div>
        </section>
        <section className="priority-panel">
          <div>
            <p className="eyebrow">Explicit confirmation</p>
            <h2>Create the local Discovery campaign</h2>
            <p>
              Discovery explores broad candidates. Later stages remain locked
              until its outputs pass their own validation.
            </p>
            {message && (
              <p className="field-error" role="alert">
                {message}
              </p>
            )}
            <button
              type="button"
              className="primary-button"
              disabled={busy}
              onClick={() => void confirm()}
            >
              {busy ? "Creating…" : "Create Discovery campaign"}
            </button>
          </div>
        </section>
      </main>
    );
  return (
    <main id="main" className="creation-page">
      {back}
      <header className="detail-hero">
        <p className="eyebrow">3D-MOT campaign · Configure</p>
        <h1 ref={heading} tabIndex={-1}>
          Create a 3D-MOT Discovery campaign
        </h1>
        <p>
          Select a completed canonical 2D campaign. The application uses only
          its sealed survivor ensembles and the reviewed pragmatic 3D timestep
          policy. This always creates a new campaign; an older inconclusive 3D
          campaign cannot be resumed or reused.
        </p>
      </header>
      <section className="state-panel" aria-labelledby="timestep-policy-heading">
        <TriangleAlert aria-hidden="true" />
        <div>
          <h2 id="timestep-policy-heading">Pragmatic timestep policy</h2>
          <p>
            Search stages use 10 µs. Sealed final validation uses 5 µs.
            All campaign evaluations run to 50 ms.
            These values are locked and cannot be changed here.
          </p>
          <p>
            The one-off study was inconclusive, so timestep convergence is not
            established.
          </p>
        </div>
      </section>
      <form
        className="creation-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (sourceId && validName && !busy) void review();
        }}
      >
        <label>
          Completed 2D-MOT campaign
          <span>
            Only completed campaigns whose 20 sealed ensembles pass the handoff
            checks are available.
          </span>
          <select
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            required
          >
            <option value="">Select a completed 2D campaign</option>
            {status?.sources.map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {source.campaign_name} · s₀ {source.s0} · 20 sealed ensembles
              </option>
            ))}
          </select>
        </label>
        <label>
          3D campaign name
          <span>
            Must name a new campaign folder. Existing or older inconclusive 3D
            campaigns are rejected. Letters, numbers, dots, underscores and
            hyphens are allowed.
          </span>
          <input
            value={campaignName}
            onChange={(event) => setCampaignName(event.target.value)}
            placeholder="for example: mot_3d_s0_1p3_20261012"
            required
          />
        </label>
        {status?.sources.length === 0 && (
          <p className="field-warning" role="status">
            No completed canonical 2D campaign is currently eligible for the 3D
            handoff.
          </p>
        )}
        {message && (
          <p className="field-error" role="alert">
            {message}
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="text-button" onClick={onBack}>
            Cancel
          </button>
          <button
            type="submit"
            className="primary-button"
            disabled={!sourceId || !validName || busy}
          >
            {busy ? "Validating…" : "Review campaign"}
          </button>
        </div>
      </form>
      <p className="read-only-note">
        <ShieldCheck aria-hidden="true" /> The timestep policy is read-only.
        Review does not create files or submit work.
      </p>
    </main>
  );
}

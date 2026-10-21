import { useEffect, useRef } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { useProductionController } from "./controllers/useProductionController";
import { JobResources } from "../shared/JobResources";
const percent = (value: number) => (100 * value).toFixed(3) + "%";
export function ProductionStage({
  visible,
  flow,
  onViewJobs,
}: {
  visible: boolean;
  flow: ReturnType<typeof useProductionController>;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (
      flow.preparation.state === "review" ||
      flow.preparation.error ||
      flow.submission.state === "review" ||
      flow.submission.error ||
      flow.finalization.state === "review" ||
      flow.finalization.state === "success" ||
      flow.finalization.error
    )
      focus.current?.focus();
  }, [
    flow.preparation.state,
    flow.preparation.error,
    flow.submission.state,
    flow.submission.error,
    flow.finalization.state,
    flow.finalization.error,
  ]);
  if (!visible) return null;
  const p = flow.preparation,
    s = flow.submission,
    f = flow.finalization,
    ready = !p.error && p.status?.sensitivity.status === "ready_to_prepare_production",
    prepared =
      p.state === "success" ||
      p.status?.sensitivity.status === "production_prepared",
    submitted = s.state === "success" || Boolean(s.status),
    finalResults = !f.error ? f.result?.results ??
      (f.state === "success" && f.status?.production.status === "campaign_complete"
        ? f.status.results : undefined) : undefined;
  return (
    <section className="section-block" aria-labelledby="production-heading">
      <div className="section-heading">
        <p className="eyebrow">Final stage: Production</p>
        <h2 id="production-heading">
          Validate Sensitivity and run sealed Production
        </h2>
        <p>
          Production uses exactly 20 frozen, previously unseen Zeeman/MOT seed
          pairs for each fixed s₀. These sealed ensembles provide the campaign's
          unbiased final performance estimate.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!prepared && p.state === "idle" && (
          <div className="prepare-card">
            <div>
              <strong>
                {ready
                  ? "All Sensitivity outputs are valid"
                  : "Check the Sensitivity results"}
              </strong>
              <p>
                Every expected local-neighborhood result must match the frozen
                design and provenance before Production can be prepared.
              </p>
            </div>
            <div className="form-actions">
              <button
                className="secondary-button"
                onClick={() => void p.refresh()}
              >
                Check Sensitivity results
              </button>
              {ready && (
                <button
                  className="primary-button"
                  onClick={() => void p.review()}
                >
                  Review Production preparation
                </button>
              )}
            </div>
          </div>
        )}
        {p.state === "checking" && (
          <Busy title="Validating Sensitivity outputs" />
        )}
        {p.preview && p.state === "review" && (
          <Review
            title="Prepare sealed Production"
            description="This creates the frozen 20-ensemble-per-s₀ task plan and PBS file. It does not submit or start simulations."
            back={p.reset}
            confirm={() => void p.confirm()}
            confirmLabel="Prepare Production files"
          >
            <dl className="transfer-facts">
              <div>
                <dt>Validated Sensitivity points</dt>
                <dd>
                  {p.preview.sensitivity.completed_points} of{" "}
                  {p.preview.sensitivity.expected_points}
                </dd>
              </div>
              <div>
                <dt>Sealed ensemble tasks</dt>
                <dd>{p.preview.job.task_count}</dd>
              </div>
              <div>
                <dt>Resources</dt>
                <dd>
                  <JobResources job={p.preview.job} />
                </dd>
              </div>
            </dl>
          </Review>
        )}
        {p.state === "confirming" && (
          <Busy title="Preparing reviewed Production files" />
        )}
        {prepared && (
          <Success
            title="Production is prepared"
            text="This preparation made the sealed Production array available for a separate submission review."
          />
        )}
        {p.error && (
          <Failure
            title={
              p.state === "terminal"
                ? "Manual verification required"
                : "Production preparation could not be verified"
            }
            text={p.error}
            refresh={() => void p.refresh()}
          />
        )}
        {prepared && (
          <>
            <div className="section-heading">
              <h3>Run sealed Production on Zeus</h3>
              <p>
                Review and explicitly submit only this final Production array.
              </p>
            </div>
            {s.state === "idle" && (
              <div className="prepare-card">
                <div>
                  <strong>Production is prepared, but not submitted</strong>
                </div>
                <div className="form-actions">
                  <button
                    className="secondary-button"
                    onClick={() => void s.refresh()}
                  >
                    Check Zeus status
                  </button>
                  <button
                    className="primary-button"
                    disabled={Boolean(s.error)}
                    onClick={() => void s.review()}
                  >
                    Review Production job
                  </button>
                </div>
              </div>
            )}
            {s.state === "checking" && (
              <Busy title="Checking Production on Zeus" />
            )}
            {s.preview && s.state === "review" && (
              <Review
                title="Submit sealed Production array"
                description="This starts only the frozen Production tasks. It does not finalize the campaign automatically."
                back={s.reset}
                confirm={() => void s.confirm()}
                confirmLabel="Submit Production to Zeus"
              >
                <dl className="transfer-facts">
                  <div>
                    <dt>Array tasks</dt>
                    <dd>
                      {s.preview.job.task_count} · throttle{" "}
                      {s.preview.job.array_throttle}
                    </dd>
                  </div>
                  <div>
                    <dt>Resources</dt>
                    <dd>
                      <JobResources job={s.preview.job} />
                    </dd>
                  </div>
                </dl>
              </Review>
            )}
            {s.state === "confirming" && (
              <Busy title="Submitting the reviewed Production array" />
            )}
            {submitted && (
              <Success
                title={
                  s.status?.submission.status === "completed_success"
                    ? "Production finished on Zeus"
                    : "Production is tracked on Zeus"
                }
                text={`Job ${s.result?.job_id ?? s.status?.submission.job_id ?? "receipt pending"}. Final results stay locked until every sealed output and retained state file passes validation.`}
              />
            )}{" "}
            {s.error && (
              <Failure
                title="Manual verification required"
                text={s.error}
                refresh={() => void s.refresh()}
                action={onViewJobs}
              />
            )}
          </>
        )}
        {submitted && (
          <>
            <div className="section-heading">
              <h3>Validate and finalize the campaign</h3>
              <p>
                Finalization verifies all JSON records, retained NumPy states,
                metadata, hashes, shapes, parameters, solver, timestep, commit,
                profile and source identity. It submits no job.
              </p>
            </div>
            {!finalResults && f.state === "idle" && (
              <div className="prepare-card">
                <div>
                  <strong>
                    {f.status?.production.status === "ready_to_finalize"
                      ? "All sealed outputs are valid"
                      : "Check sealed Production outputs"}
                  </strong>
                </div>
                <div className="form-actions">
                  <button
                    className="secondary-button"
                    onClick={() => void f.refresh()}
                  >
                    Check Production results
                  </button>
                  {!f.error && f.status?.production.status === "ready_to_finalize" && (
                    <button
                      className="primary-button"
                      onClick={() => void f.review()}
                    >
                      Review final results
                    </button>
                  )}
                </div>
              </div>
            )}
            {f.state === "checking" && (
              <Busy title="Validating every sealed Production output" />
            )}
            {f.preview && f.state === "review" && (
              <Review
                title="Finalize this campaign"
                description="Review the sealed estimates below. Confirming records the validated report and marks the campaign complete; it does not run or submit anything."
                back={f.reset}
                confirm={() => void f.confirm()}
                confirmLabel="Finalize campaign"
              >
                <Results rows={f.preview.results} />
              </Review>
            )}
            {f.state === "confirming" && (
              <Busy title="Recording the validated final report" />
            )}
            {finalResults && (
              <div className="transfer-review">
                <div className="section-heading">
                  <p className="eyebrow">Campaign complete</p>
                  <h3>Sealed final results</h3>
                  <p>
                    These are unbiased estimates from the frozen sealed
                    ensembles. A warning about robustness or near-optimality
                    means that claim was not established; it does not invalidate
                    the reported best tested result.
                  </p>
                </div>
                <Results rows={finalResults} />
              </div>
            )}
            {f.error && (
              <Failure
                title="Finalization could not be verified"
                text={f.error}
                refresh={() => void f.refresh()}
                action={onViewJobs}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}
function Busy({ title }: { title: string }) {
  return (
    <div className="state-panel" role="status" aria-busy="true">
      <LoaderCircle aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>No automatic submission occurs.</p>
      </div>
    </div>
  );
}
function Success({ title, text }: { title: string; text: string }) {
  return (
    <div className="state-panel state-panel--success" role="status">
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
    </div>
  );
}
function Failure({
  title,
  text,
  action,
  refresh,
}: {
  title: string;
  text: string;
  action?: () => void;
  refresh?: () => void;
}) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
        {refresh && <><p>Check the current status before taking further action. Do not retry or submit again automatically.</p><button className="secondary-button compact-action" onClick={refresh}>Check current status</button></>}
        {action && (
          <button className="secondary-button compact-action" onClick={action}>
            View Zeus jobs
          </button>
        )}
      </div>
    </div>
  );
}
function Review({
  title,
  description,
  children,
  back,
  confirm,
  confirmLabel,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  back: () => void;
  confirm: () => void;
  confirmLabel: string;
}) {
  return (
    <div className="transfer-review">
      <div className="section-heading">
        <p className="eyebrow">Explicit review</p>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      {children}
      <div className="form-actions">
        <button className="text-button" onClick={back}>
          Back
        </button>
        <button className="primary-button" onClick={confirm}>
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
function Results({
  rows,
}: {
  rows: import("../../api/schema/domain").FinalCampaignResult[];
}) {
  return (
    <div className="campaign-grid">
      {rows.map((row) => (
        <article className="campaign-card" key={row.s0}>
          <p className="eyebrow">Fixed s₀ {row.s0}</p>
          <h4>
            {percent(row.prediction.pooled_conditional_efficiency)} conditional
            capture
          </h4>
          <p>
            95% cluster-aware interval:{" "}
            {percent(row.prediction.predicted_95_interval_fraction[0])}–
            {percent(row.prediction.predicted_95_interval_fraction[1])}
          </p>
          <dl className="transfer-facts">
            <div>
              <dt>Sealed ensembles</dt>
              <dd>{row.n_ensembles}</dd>
            </div>
            <div>
              <dt>Selected Zeeman survivors</dt>
              <dd>{row.total_input.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Captured atoms</dt>
              <dd>{row.total_survivors.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Target uncertainty</dt>
              <dd>{row.target_uncertainty_passes ? "Met" : "Not met"}</dd>
            </div>
          </dl>
          {row.warnings.length > 0 && (
            <div className="state-panel state-panel--warning">
              <strong>Scientific qualifications</strong>
              <ul>
                {row.warnings.map((w) => (
                  <li key={w}>{w.replaceAll("_", " ")}</li>
                ))}
              </ul>
            </div>
          )}
          <p>
            <strong>Retained outputs:</strong>{" "}
            {row.output_suitability === "acceptance_only"
              ? "TEST ONLY acceptance testing; not eligible for scientific use."
              : "eligible as validated 3D campaign input."}
          </p>
          <details>
            <summary>Technical provenance</summary>
            <p>
              Cluster-aware bootstrap:{" "}
              {row.prediction.bootstrap_replicates.toLocaleString()} draws.
            </p>
            <p>
              Solver-selected parameters: detuning{" "}
              {row.recommended_parameters.detuning_gamma} Γ; magnet radius{" "}
              {(1000 * row.recommended_parameters.magnet_radius).toFixed(3)} mm.
            </p>
          </details>
        </article>
      ))}
    </div>
  );
}

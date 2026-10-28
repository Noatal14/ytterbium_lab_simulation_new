import { useEffect, useRef } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { useProductionController } from "./controllers/useProductionController";
import { JobResources } from "../shared/JobResources";
import type { FinalCampaignResult } from "../../api/schema/domain";
const percent = (value: number) => (100 * value).toFixed(3) + "%";
function resultLabels(rows: FinalCampaignResult[]) {
  const acceptanceCount = rows.filter(row => row.output_suitability === "acceptance_only").length;
  const includesAcceptance = acceptanceCount > 0;
  const acceptanceOnly = includesAcceptance && acceptanceCount === rows.length;
  return {
    includesAcceptance,
    scientificOnly: rows.length > 0 && !includesAcceptance,
    title: acceptanceOnly ? "TEST ONLY sealed results" : includesAcceptance ? "Sealed results — includes TEST ONLY outputs" : "Sealed final results",
    description: acceptanceOnly
      ? "These results verify the acceptance workflow. They are not scientific performance estimates."
      : includesAcceptance
        ? "These results include TEST ONLY acceptance outputs. Read each row's suitability; no combined scientific performance claim is made."
        : "These are unbiased estimates from the frozen sealed ensembles. A warning about robustness or near-optimality means that claim was not established; it does not invalidate the reported best tested result.",
    reviewTitle: acceptanceOnly ? "Finalize TEST ONLY results" : includesAcceptance ? "Finalize results including TEST ONLY outputs" : "Finalize this campaign",
    reviewDescription: includesAcceptance
      ? "Review each row's suitability below. Confirming records the report, including TEST ONLY outputs, and marks the campaign complete; it does not run or submit anything."
      : "Review the sealed estimates below. Confirming records the validated report and marks the campaign complete; it does not run or submit anything.",
  };
}
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
      flow.finalization.state === "terminal" ||
      flow.finalization.error ||
      flow.collection?.state === "review" || flow.collection?.state === "success" || Boolean(flow.collection?.error)
    )
      focus.current?.focus();
  }, [
    flow.preparation.state,
    flow.preparation.error,
    flow.submission.state,
    flow.submission.error,
    flow.finalization.state,
    flow.finalization.error,
    flow.collection?.state, flow.collection?.error,
  ]);
  if (!visible) return null;
  const p = flow.preparation,
    s = flow.submission,
    f = flow.finalization,
    c = flow.collection,
    ready = !p.error && p.status?.sensitivity.status === "ready_to_prepare_production",
    prepared =
      p.state === "success" ||
      p.status?.sensitivity.status === "production_prepared",
    submitted = s.state === "success" || Boolean(s.status),
    finalResults = f.state === "success" && !f.error ? f.result?.results ??
      (f.state === "success" && f.status?.production.status === "campaign_complete"
        ? f.status.results : undefined) : undefined;
  const observedRows = (["review", "confirming"].includes(f.state) ? f.preview?.results : undefined)
    ?? finalResults ?? f.status?.results ?? [];
  const labels = resultLabels(observedRows), finalLabels = resultLabels(finalResults ?? []);
  return (
    <section className="section-block" aria-labelledby="production-heading">
      <div className="section-heading">
        <p className="eyebrow">Final stage: Production</p>
        <h2 id="production-heading">
          Validate Sensitivity and run sealed Production
        </h2>
        <p>
          Production uses exactly 20 frozen, previously unseen Zeeman/MOT seed
          pairs for each fixed s₀.{" "}
          {labels.includesAcceptance
            ? "TEST ONLY outputs exercise the workflow and do not establish scientific performance. Each row states its allowed use."
            : labels.scientificOnly
              ? "These sealed ensembles provide the campaign's unbiased final performance estimate."
              : "Each result's recorded output suitability determines its allowed use."}
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
                title={labels.reviewTitle}
                description={labels.reviewDescription}
                back={f.reset}
                confirm={() => void f.confirm()}
                confirmLabel="Finalize campaign"
              >
                <Results rows={f.preview.results} />
              </Review>
            )}
            {f.state === "confirming" && (
              <Busy title={labels.includesAcceptance ? "Recording the report including TEST ONLY outputs" : "Recording the validated final report"} />
            )}
            {finalResults && (
              <div className="transfer-review">
                <div className="section-heading">
                  <p className="eyebrow">Campaign complete</p>
                  <h3>{finalLabels.title}</h3>
                  <p>{finalLabels.description}</p>
                </div>
                <Results rows={finalResults} />
              </div>
            )}
            {finalResults && c && <LocalCollection operation={c} synchronized={f.status?.local_sync.status === "synchronized"} />}
            {f.state === "terminal" && !f.error && (
              <Failure
                title={f.status?.production.status === "outputs_invalid"
                  ? "Sealed Production outputs failed validation"
                  : f.status?.production.status === "held" ? "Production job is held"
                    : f.status?.production.status === "failed" ? "Production job failed"
                      : "Production job status is unknown"}
                text={f.status?.production.status === "outputs_invalid"
                  ? `Missing or invalid output artifacts prevent finalization. ${f.status.validation.completed_ensembles} of ${f.status.validation.expected_ensembles} output ensembles are verified; these counts describe validated outputs, not surviving atoms.`
                  : f.status?.production.status === "held"
                    ? "Zeus reports that the Production job is held. Final results remain unavailable until the job and its outputs can be verified."
                    : f.status?.production.status === "failed"
                      ? "Zeus reports that the Production job failed. Final results cannot be published from this status."
                      : "The Production job status could not be established. No completed result or safe retry is established."}
                refresh={() => void f.refresh()}
                action={onViewJobs}
              />
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
  rows: FinalCampaignResult[];
}) {
  return (
    <div className="campaign-grid">
      {rows.map((row) => (
        <article className="campaign-card" key={row.s0}>
          <p className="eyebrow">{row.output_suitability === "acceptance_only" ? "TEST ONLY diagnostics · " : ""}Fixed s₀ {row.s0}</p>
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
              <strong>{row.output_suitability === "acceptance_only" ? "Acceptance diagnostics" : "Scientific qualifications"}</strong>
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
              : "Scientific output suitability is recorded. The normal 3D source catalogue checks locally validated outputs; remote completion alone does not provide local inputs."}
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

function LocalCollection({
  operation: c,
  synchronized,
}: {
  operation: ReturnType<typeof useProductionController>["collection"];
  synchronized: boolean;
}) {
  const collected =
    !c.error &&
    ((c.state === "idle" && c.lastObservation === null && synchronized) ||
      (c.state === "success" &&
        (c.lastObservation === "confirm"
          ? c.result?.local_sync.status === "synchronized"
          : c.status?.local_sync.status === "synchronized")));
  return (
    <section aria-label="Local collection">
      <div className="section-heading">
        <h3>Collect completed outputs on this computer</h3>
        <p>
          Remote finalization and local collection are separate. Collection
          submits no job and runs no simulation.
        </p>
      </div>
      {collected ? (
        <Success
          title="Local collection verified"
          text="The completed outputs and synchronization receipt are verified locally. The normal 3D source catalogue independently checks input eligibility, including whether ensembles contain surviving atoms."
        />
      ) : (
        <>
          {c.state === "idle" &&
            !c.error &&
            (!c.status ||
              c.status.production.status === "campaign_complete") && (
              <div className="prepare-card">
                <div>
                  <strong>Completed on Zeus — local collection not verified</strong>
                  <p>
                    Review the exact files and sizes before collecting the
                    verified outputs.
                  </p>
                </div>
                <button
                  className="primary-button"
                  onClick={() => void c.review()}
                >
                  Review local collection
                </button>
              </div>
            )}
          {c.state === "idle" &&
            !c.error &&
            c.status &&
            c.status.production.status !== "campaign_complete" && (
              <Failure
                title="Completed outputs are not established by the latest status"
                text="Check the current status before reviewing local collection."
                refresh={() => void c.refresh()}
              />
            )}
          {c.state === "checking" && (
            <Busy title="Checking completed outputs and local collection" />
          )}
          {c.state === "confirming" && (
            <Busy title="Collecting the reviewed verified outputs" />
          )}
          {c.state === "review" && c.preview && (
            <Review
              title="Review local collection"
              description="Collect only this verified output registry. No job is submitted and no simulation starts."
              back={c.reset}
              confirm={() => void c.confirm()}
              confirmLabel="Collect verified outputs"
            >
              <dl className="transfer-facts">
                <div>
                  <dt>Files</dt>
                  <dd>{c.preview.artifacts.file_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Total bytes</dt>
                  <dd>{c.preview.artifacts.total_bytes.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Largest file</dt>
                  <dd>
                    {c.preview.artifacts.maximum_file_bytes.toLocaleString()}{" "}
                    bytes
                  </dd>
                </div>
                <div>
                  <dt>Disposition</dt>
                  <dd>
                    {c.preview.artifacts.create.length} new ·{" "}
                    {c.preview.artifacts.identical.length} already identical ·{" "}
                    {c.preview.artifacts.update.length} campaign manifest update
                  </dd>
                </div>
                <div>
                  <dt>Finalization receipt SHA-256</dt>
                  <dd>
                    <code>{c.preview.source.finalization_receipt_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>Complete manifest SHA-256</dt>
                  <dd>
                    <code>{c.preview.source.complete_manifest_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>Registry SHA-256</dt>
                  <dd>
                    <code>{c.preview.source.registry_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>Bundle SHA-256</dt>
                  <dd>
                    <code>{c.preview.source.bundle_sha256}</code>
                  </dd>
                </div>
              </dl>
              <details>
                <summary>Exact reviewed files</summary>
                <ul>
                  {c.preview.artifacts.files.map((file) => (
                    <li key={file.path}>
                      <code>{file.path}</code> · {file.size.toLocaleString()}{" "}
                      bytes · SHA-256 <code>{file.sha256}</code>
                    </li>
                  ))}
                </ul>
              </details>
            </Review>
          )}
          {(c.error || c.state === "terminal") && (
            <Failure
              title="Local collection could not be verified"
              text={
                c.error ||
                "The latest authoritative status does not establish valid completed outputs. No local synchronization is claimed."
              }
              refresh={() => void c.refresh()}
            />
          )}
        </>
      )}
    </section>
  );
}

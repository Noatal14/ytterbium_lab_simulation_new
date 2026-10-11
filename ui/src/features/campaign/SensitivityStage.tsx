import { useEffect, useRef } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { useSensitivityController } from "./controllers/useSensitivityController";
import { JobResources } from "../shared/JobResources";
export function SensitivityStage({
  visible,
  flow,
  onViewJobs,
}: {
  visible: boolean;
  flow: ReturnType<typeof useSensitivityController>;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (
      flow.preparation.state === "review" ||
      flow.preparation.state === "success" ||
      flow.preparation.error ||
      flow.submission.state === "review" ||
      flow.submission.state === "success" ||
      flow.submission.error
    )
      focus.current?.focus();
  }, [
    flow.preparation.state,
    flow.preparation.error,
    flow.submission.state,
    flow.submission.error,
  ]);
  if (!visible) return null;
  const p = flow.preparation,
    s = flow.submission,
    remote = p.status?.confirmation.status;
  return (
    <section className="section-block" aria-labelledby="sensitivity-heading">
      <div className="section-heading">
        <p className="eyebrow">Next stage: Sensitivity</p>
        <h2 id="sensitivity-heading">
          Validate Confirmation and prepare Sensitivity
        </h2>
        <p>
          Sensitivity evaluates the selected Confirmation candidate across the
          frozen local neighborhoods. It does not by itself establish robustness
          and is not the sealed final performance estimate; Production remains
          locked until this stage is complete and validated.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {p.state === "idle" && !p.result && (
          <div className="prepare-card">
            <div>
              <strong>
                {remote === "ready_to_prepare_sensitivity"
                  ? "All Confirmation outputs are valid"
                  : "Check the Confirmation results"}
              </strong>
              <p>
                Every expected held-out result must match the frozen design and
                provenance before Sensitivity can be prepared.
              </p>
            </div>
            <div className="form-actions">
              <button
                className="secondary-button"
                onClick={() => void p.refresh()}
              >
                Check Confirmation results
              </button>
              {remote === "ready_to_prepare_sensitivity" && (
                <button
                  className="primary-button"
                  onClick={() => void p.review()}
                >
                  Review Sensitivity preparation
                </button>
              )}
            </div>
          </div>
        )}
        {p.state === "checking" && (
          <div className="state-panel" role="status" aria-busy="true">
            <LoaderCircle aria-hidden="true" />
            <div>
              <strong>Validating Confirmation outputs</strong>
              <p>
                No files are changed and no job is submitted during this check.
              </p>
            </div>
          </div>
        )}
        {p.preview && p.state === "review" && (
          <div className="transfer-review">
            <div className="section-heading">
              <p className="eyebrow">Preparation review</p>
              <h3>Prepare Sensitivity</h3>
              <p>
                This creates the selected-candidate record, task plan, and exact
                Sensitivity PBS file. It does not submit or start simulations.
              </p>
            </div>
            <dl className="transfer-facts">
              <div>
                <dt>Validated Confirmation points</dt>
                <dd>
                  {p.preview.confirmation.completed_points} of{" "}
                  {p.preview.confirmation.expected_points}
                </dd>
              </div>
              <div>
                <dt>Sensitivity tasks</dt>
                <dd>{p.preview.job.task_count}</dd>
              </div>
              <div>
                <dt>Resources</dt>
                <dd>
                  <JobResources job={p.preview.job} />
                </dd>
              </div>
            </dl>
            <div className="form-actions">
              <button className="text-button" onClick={p.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void p.confirm()}
              >
                Prepare Sensitivity files
              </button>
            </div>
          </div>
        )}
        {p.state === "confirming" && (
          <div className="state-panel" role="status" aria-busy="true">
            <LoaderCircle aria-hidden="true" />
            <div>
              <strong>Preparing reviewed files</strong>
            </div>
          </div>
        )}
        {(p.state === "success" || p.result) && (
          <div className="state-panel state-panel--success" role="status">
            <div>
              <strong>Sensitivity is prepared</strong>
              <p>
                The exact Sensitivity array can now be reviewed before
                submission.
              </p>
            </div>
          </div>
        )}
        {p.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>
                {p.state === "terminal"
                  ? "Manual verification required"
                  : "Sensitivity preparation stopped safely"}
              </strong>
              <p>{p.error}</p>
            </div>
          </div>
        )}
        {(p.state === "success" ||
          p.status?.confirmation.status === "sensitivity_prepared") && (
          <>
            <div className="section-heading">
              <h3>Run Sensitivity on Zeus</h3>
              <p>
                Review the exact prepared array before explicitly submitting it.
              </p>
            </div>
            {s.state === "idle" && (
              <div className="prepare-card">
                <div>
                  <strong>Sensitivity is prepared, but not submitted</strong>
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
                    onClick={() => void s.review()}
                  >
                    Review Sensitivity job
                  </button>
                </div>
              </div>
            )}
            {s.state === "checking" && (
              <div className="state-panel" role="status" aria-busy="true">
                <LoaderCircle aria-hidden="true" />
                <div>
                  <strong>Checking the reviewed operation</strong>
                </div>
              </div>
            )}
            {s.preview && s.state === "review" && (
              <div className="transfer-review">
                <div className="section-heading">
                  <p className="eyebrow">Final review</p>
                  <h3>Submit Sensitivity array</h3>
                  <p>
                    This starts only Sensitivity. Production is not submitted.
                  </p>
                </div>
                <dl className="transfer-facts">
                  <div>
                    <dt>Job file</dt>
                    <dd>
                      <code>{s.preview.job.file}</code>
                    </dd>
                  </div>
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
                <div className="form-actions">
                  <button className="text-button" onClick={s.reset}>
                    Back
                  </button>
                  <button
                    className="primary-button"
                    onClick={() => void s.confirm()}
                  >
                    Submit Sensitivity to Zeus
                  </button>
                </div>
              </div>
            )}
            {s.state === "confirming" && (
              <div className="state-panel" role="status" aria-busy="true">
                <LoaderCircle aria-hidden="true" />
                <div>
                  <strong>Submitting the reviewed array</strong>
                  <p>Do not retry while the scheduler receipt is unknown.</p>
                </div>
              </div>
            )}
            {s.state === "success" && (
              <div className="state-panel state-panel--success" role="status">
                <div>
                  <strong>
                    {s.status?.submission.status === "completed_success"
                      ? "Sensitivity finished on Zeus"
                      : "Sensitivity is tracked on Zeus"}
                  </strong>
                  <p>
                    Job{" "}
                    <code>
                      {s.result?.job_id ?? s.status?.submission.job_id}
                    </code>
                    . Production stays locked until every expected output passes
                    validation.
                  </p>
                  <button
                    className="secondary-button compact-action"
                    onClick={onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                </div>
              </div>
            )}
            {s.error && (
              <div className="state-panel state-panel--error" role="alert">
                <AlertTriangle aria-hidden="true" />
                <div>
                  <strong>Manual verification required</strong>
                  <p>{s.error}</p>
                  <button
                    className="secondary-button compact-action"
                    onClick={onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

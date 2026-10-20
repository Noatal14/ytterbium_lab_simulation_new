import { campaignConfirmationParticles } from "../../../api/campaignPolicy";
import { useEffect, useRef } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import type {
  ConfirmationSubmissionPreview,
  ConfirmationSubmissionResult,
  ConfirmationSubmissionStatus,
} from "../../../api/schema/domain";
import type { ConfirmationSubmissionUiState } from "../controllers/useConfirmationSubmissionController";
import { JobResources } from "../../shared/JobResources";
import { ReviewEffects } from "../../shared/ReviewEffects";

export function ConfirmationSubmissionView({
  enabled,
  state,
  status,
  preview,
  result,
  error,
  onRefresh,
  onReview,
  onConfirm,
  onReset,
  onViewJobs,
}: {
  enabled: boolean;
  state: ConfirmationSubmissionUiState;
  status: ConfirmationSubmissionStatus | null;
  preview: ConfirmationSubmissionPreview | null;
  result: ConfirmationSubmissionResult | null;
  error: string;
  onRefresh: () => void;
  onReview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  const reviewRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (state === "review") reviewRef.current?.focus();
    else if (state === "submitted") resultRef.current?.focus();
    else if (error) errorRef.current?.focus();
  }, [state, error]);
  const schedulerStatus = status?.submission.status;
  const trackedTitle =
    schedulerStatus === "completed_success"
      ? "Confirmation finished on Zeus"
      : schedulerStatus === "running"
        ? "Confirmation is running on Zeus"
        : schedulerStatus === "queued"
          ? "Confirmation is queued on Zeus"
          : "Confirmation submitted";
  const trackedMessage =
    schedulerStatus === "completed_success"
      ? "The scheduler reports that every array task completed successfully. The outputs must still pass validation."
      : schedulerStatus === "running"
        ? "At least one array task is running. No submission action is needed."
        : schedulerStatus === "queued"
          ? "The array is waiting in the scheduler. No submission action is needed."
          : "The reviewed array is now tracked on Zeus.";
  if (!enabled) return null;
  return (
    <section
      className="section-block"
      aria-labelledby="confirmation-submit-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Current stage: Confirmation</p>
        <h2 id="confirmation-submit-heading">Run Confirmation on Zeus</h2>
        <p>
          The prepared candidate array is submitted only after you review and
          confirm this exact job.
        </p>
      </div>
      {state === "idle" && (
        <div className="prepare-card">
          <div>
            <strong>Confirmation is prepared, but not submitted</strong>
            <p>
              Check Zeus first, or review the exact array job before submitting.
            </p>
          </div>
          <div className="form-actions">
            <button
              className="secondary-button"
              type="button"
              onClick={onRefresh}
            >
              Check Zeus status
            </button>
            <button className="primary-button" type="button" onClick={onReview}>
              Review Confirmation job
            </button>
          </div>
        </div>
      )}
      {state === "checking" && (
        <div className="state-panel" role="status" aria-busy="true">
          <LoaderCircle aria-hidden="true" />
          <div>
            <strong>Checking the reviewed operation</strong>
            <p>No job is submitted during this check.</p>
          </div>
        </div>
      )}
      {preview && state === "review" && (
        <div className="transfer-review" ref={reviewRef} tabIndex={-1}>
          <div className="section-heading">
            <p className="eyebrow">Final review</p>
            <h3>Submit Confirmation array</h3>
            <p>
              This action starts the Confirmation simulations on Zeus. It does
              not submit Sensitivity or Production.
            </p>
            <p>
              Confirmation evaluates one selected candidate on five frozen
              held-out ensembles, using {campaignConfirmationParticles().toLocaleString("en")} particles per ensemble and the
              final RK4StHybridCustom solver at a 0.625 µs timestep. This is a
              selection check, not the sealed final performance estimate.
            </p>
          </div>
          <dl className="transfer-facts">
            <div>
              <dt>Job file</dt>
              <dd>
                <code>{preview.job.file}</code>
              </dd>
            </div>
            <div>
              <dt>Array tasks</dt>
              <dd>
                {preview.job.task_count} · throttle {preview.job.array_throttle}
              </dd>
            </div>
            <div>
              <dt>Resources</dt>
              <dd>
                <JobResources job={preview.job} />
              </dd>
            </div>
            <div>
              <dt>Remote checkout</dt>
              <dd>{preview.remote.branch} · clean reviewed commit</dd>
            </div>
          </dl>
          <ReviewEffects
            effects={[
              <>Submits exactly the prepared Confirmation array.</>,
              <>Starts Confirmation simulations on Zeus.</>,
              <>Does not submit later campaign stages.</>,
              <>
                Keeps the prepared campaign artifacts unchanged while recording
                durable submission-receipt metadata.
              </>,
              <>An unknown scheduler outcome blocks automatic retry.</>,
            ]}
          />
          <div className="form-actions">
            <button className="text-button" type="button" onClick={onReset}>
              Back
            </button>
            <button
              className="primary-button"
              type="button"
              onClick={onConfirm}
            >
              Submit Confirmation to Zeus
            </button>
          </div>
        </div>
      )}
      {state === "submitting" && (
        <div className="state-panel" role="status" aria-busy="true">
          <LoaderCircle aria-hidden="true" />
          <div>
            <strong>Submitting the reviewed job</strong>
            <p>Wait for the scheduler receipt. Do not click again.</p>
          </div>
        </div>
      )}
      {state === "submitted" && (
        <div className="state-panel state-panel--success" role="status" ref={resultRef} tabIndex={-1}>
          <div>
            <strong>{trackedTitle}</strong>
            <p>
              Job <code>{result?.job_id ?? status?.submission.job_id}</code>. {trackedMessage}
            </p>
            <p>
              Sensitivity stays locked until every expected Confirmation output
              passes the frozen-design and provenance checks.
            </p>
            <button
              className="secondary-button compact-action"
              type="button"
              onClick={onViewJobs}
            >
              View Zeus jobs
            </button>
          </div>
        </div>
      )}
      {error && (
        <div className="state-panel state-panel--error" role="alert" ref={errorRef} tabIndex={-1}>
          <AlertTriangle aria-hidden="true" />
          <div>
            <strong>
              {state === "terminal"
                ? "Manual verification required"
                : "Confirmation submission stopped safely"}
            </strong>
            <p>{error}</p>
            <div className="form-actions">
              <button
                className="secondary-button compact-action"
                type="button"
                onClick={onViewJobs}
              >
                View Zeus jobs
              </button>
              {state !== "terminal" && (
                <button className="text-button" type="button" onClick={onReset}>
                  Try a fresh review
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

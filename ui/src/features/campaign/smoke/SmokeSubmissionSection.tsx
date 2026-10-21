import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import type { RefObject } from "react";
import type {
  SmokeSubmissionPreview,
  SmokeSubmissionResult,
} from "../../../api/clients/smoke";
import type { SmokeSubmitState } from "../controllers/useSmokeController";

export function SmokeSubmissionSection({
  canSubmit,
  submissionState,
  submissionPreview,
  submissionResult,
  submissionError,
  submissionButton,
  submissionHeading,
  submissionSuccess,
  submissionErrorPanel,
  onPreviewSubmission,
  onConfirmSubmission,
  onResetSubmission,
  onViewJobs,
}: {
  canSubmit: boolean;
  submissionState: SmokeSubmitState;
  submissionPreview: SmokeSubmissionPreview | null;
  submissionResult: SmokeSubmissionResult | null;
  submissionError: string;
  submissionButton: RefObject<HTMLButtonElement>;
  submissionHeading: RefObject<HTMLHeadingElement>;
  submissionSuccess: RefObject<HTMLDivElement>;
  submissionErrorPanel: RefObject<HTMLDivElement>;
  onPreviewSubmission: () => void;
  onConfirmSubmission: () => void;
  onResetSubmission: () => void;
  onViewJobs: () => void;
}) {
  return (
    <>
      {canSubmit && (
        <section className="section-block" aria-labelledby="submit-heading">
          <div className="section-heading">
            <h2 id="submit-heading">Submit the smoke check</h2>
            <p>
              Review the exact scheduler request before any real work is sent to
              Zeus.
            </p>
          </div>
          {submissionState === "idle" && !submissionError && (
            <div className="prepare-card">
              <div>
                <strong>Campaign inputs are prepared</strong>
                <p>
                  The submission review independently checks the remote code,
                  campaign files, and scheduler state again.
                </p>
              </div>
              <button
                ref={submissionButton}
                className="primary-button"
                type="button"
                onClick={onPreviewSubmission}
              >
                Review smoke submission
              </button>
            </div>
          )}
          {submissionState === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing the smoke submission</strong>
                <p>No job is being submitted.</p>
              </div>
            </div>
          )}
          {submissionPreview &&
            ["review", "submitting"].includes(submissionState) && (
              <div
                className="transfer-review"
                aria-busy={submissionState === "submitting"}
              >
                <div className="section-heading">
                  <p className="eyebrow">Final review</p>
                  <h3 ref={submissionHeading} tabIndex={-1}>
                    Submit smoke check to Zeus
                  </h3>
                  <p>
                    This submits only the small smoke check for this 2D-MOT
                    campaign. It verifies that the campaign can start correctly
                    before expensive optimization work is unlocked.
                  </p>
                </div>
                <dl className="transfer-facts">
                  <div>
                    <dt>Campaign</dt>
                    <dd>{submissionPreview.campaign.name}</dd>
                  </div>
                  <div>
                    <dt>Stage</dt>
                    <dd>{submissionPreview.stage.label}</dd>
                  </div>
                  <div>
                    <dt>Purpose</dt>
                    <dd>{submissionPreview.stage.purpose}</dd>
                  </div>
                  <div>
                    <dt>Scheduler request</dt>
                    <dd>
                      {submissionPreview.job.kind === "array"
                        ? `1 array job · ${submissionPreview.job.task_count} tasks · one per fixed s₀ value`
                        : "1 PBS job · 1 task"}
                    </dd>
                  </div>
                  <div>
                    <dt>Fixed s₀ values</dt>
                    <dd>{submissionPreview.campaign.s0_values.join(", ")}</dd>
                  </div>
                  <div>
                    <dt>Queue</dt>
                    <dd>
                      <code>{submissionPreview.job.queue}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Resources per task</dt>
                    <dd>{submissionPreview.job.cores_per_task} CPU {submissionPreview.job.cores_per_task === 1 ? "core" : "cores"} · {Math.round(submissionPreview.job.memory_per_task_bytes / 1024 ** 3)} GiB memory</dd>
                  </div>
                  <div>
                    <dt>Walltime limit per task</dt>
                    <dd>{submissionPreview.job.walltime_seconds / 60} minutes</dd>
                  </div>
                  <div>
                    <dt>Job file</dt>
                    <dd>
                      <code>{submissionPreview.job.file}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Remote code</dt>
                    <dd>
                      Ready · exact commit{" "}
                      <code>
                        {submissionPreview.remote.commit.slice(0, 12)}
                      </code>{" "}
                      · clean tracked worktree
                    </dd>
                  </div>
                  <div>
                    <dt>Campaign inputs</dt>
                    <dd>
                      Ready · all {submissionPreview.inputs.verified_count}{" "}
                      artifacts verified
                    </dd>
                  </div>
                  <div>
                    <dt>Later stages</dt>
                    <dd>
                      Locked until smoke outputs are complete and validated
                    </dd>
                  </div>
                </dl>
                <ul className="effect-list">
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Submits only the smoke
                    check.
                  </li>
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Does not submit
                    screening or any later stage.
                  </li>
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Does not modify campaign
                    inputs or code.
                  </li>
                </ul>
                <div className="submission-attention">
                  <strong>Attention</strong>
                  <p>
                    Selecting Submit sends real work to Zeus. The application
                    will record the returned job ID and will not submit again
                    automatically.
                  </p>
                </div>
                <div className="form-actions">
                  <button
                    className="text-button"
                    type="button"
                    disabled={submissionState === "submitting"}
                    onClick={onResetSubmission}
                  >
                    Back
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={submissionState === "submitting"}
                    onClick={onConfirmSubmission}
                  >
                    {submissionState === "submitting" ? (
                      <>
                        <LoaderCircle aria-hidden="true" /> Submitting…
                      </>
                    ) : (
                      "Submit smoke check to Zeus"
                    )}
                  </button>
                </div>
              </div>
            )}
          {submissionState === "submitted" && submissionResult && (
            <div
              ref={submissionSuccess}
              className="connection-panel connection-panel--connected"
              role="status"
              tabIndex={-1}
            >
              <CheckCircle2 aria-hidden="true" />
              <div>
                <strong>Smoke check submitted</strong>
                <p>
                  Zeus job {submissionResult.job_id} was recorded. No later
                  stage was submitted.
                </p>
                <p>
                  Screening remains locked until the smoke outputs are complete
                  and validated.
                </p>
                <button
                  className="secondary-button compact-action"
                  type="button"
                  onClick={onViewJobs}
                >
                  View in Zeus jobs
                </button>
              </div>
            </div>
          )}
          {submissionError && (
            <div
              ref={submissionErrorPanel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {submissionState === "unknown"
                    ? "Submission outcome needs verification"
                    : submissionState === "terminal"
                      ? "Smoke stage will not be resubmitted"
                      : "Smoke submission could not be verified"}
                </strong>
                <p>{submissionError}</p>
                {["unknown", "terminal"].includes(submissionState) ? (
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                ) : (
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={onResetSubmission}
                  >
                    Review again
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}

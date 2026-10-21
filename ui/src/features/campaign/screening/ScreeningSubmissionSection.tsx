import { AlertTriangle, CheckCircle2, LoaderCircle, RefreshCw } from "lucide-react";
import type { RefObject } from "react";
import type {
  ScreeningLifecycle,
  ScreeningSubmissionPreview,
  ScreeningSubmissionResult,
} from "../../../api/clients/screening";
import type {
  ScreeningCheckState as CheckState,
  ScreeningSubmitState as SubmitState,
} from "../controllers/useScreeningController";

const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export function ScreeningSubmissionSection({
  evidenceFresh,
  smokeCheck,
  submitState,
  submitPreview,
  submitResult,
  submitError,
  lifecycle,
  submitButton,
  submitHeading,
  submitPanel,
  onRefreshSmoke,
  onPreviewSubmit,
  onConfirmSubmit,
  onResetSubmit,
  onViewJobs,
}: {
  evidenceFresh: boolean;
  smokeCheck: CheckState;
  submitState: SubmitState;
  submitPreview: ScreeningSubmissionPreview | null;
  submitResult: ScreeningSubmissionResult | null;
  submitError: string;
  lifecycle: ScreeningLifecycle | null;
  submitButton: RefObject<HTMLButtonElement>;
  submitHeading: RefObject<HTMLHeadingElement>;
  submitPanel: RefObject<HTMLDivElement>;
  onRefreshSmoke: () => void;
  onPreviewSubmit: () => void;
  onConfirmSubmit: () => void;
  onResetSubmit: () => void;
  onViewJobs: () => void;
}) {
  return (
    <>
      {submitState !== "submitted" && (
        <section
          className="section-block"
          aria-labelledby="screen-submit-section-heading"
        >
          <div className="section-heading">
            <h2 id="screen-submit-section-heading">Submit Screening</h2>
            <p>
              Submission is a separate guarded action. Review the exact PBS
              array before sending any work to Zeus.
            </p>
          </div>
          {!evidenceFresh && (
            <div className="prepare-card">
              <div>
                <strong>Fresh Zeus evidence required</strong>
                <p>
                  The prepared state shown above was created locally in this
                  session or is no longer fresh enough for submission review.
                </p>
              </div>
              <button
                className="secondary-button"
                type="button"
                disabled={smokeCheck === "checking"}
                onClick={onRefreshSmoke}
              >
                {smokeCheck === "checking" ? (
                  <>
                    <LoaderCircle aria-hidden="true" /> Checking…
                  </>
                ) : (
                  <>
                    <RefreshCw aria-hidden="true" /> Refresh Zeus status
                  </>
                )}
              </button>
            </div>
          )}
          {evidenceFresh && submitState === "idle" && (
            <div className="prepare-card">
              <div>
                <strong>Screening is prepared and verified on Zeus</strong>
                <p>
                  A review will revalidate the remote checkout, smoke evidence,
                  inputs, and scheduler request. It will not submit anything.
                </p>
              </div>
              <button
                ref={submitButton}
                className="primary-button"
                type="button"
                onClick={onPreviewSubmit}
              >
                Review Screening submission
              </button>
            </div>
          )}
          {submitState === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing the Screening submission</strong>
                <p>No job is being submitted.</p>
              </div>
            </div>
          )}
          {submitPreview && ["review", "submitting"].includes(submitState) && (
            <div
              className="transfer-review"
              aria-busy={submitState === "submitting"}
            >
              <div className="section-heading">
                <p className="eyebrow">Final review</p>
                <h3 ref={submitHeading} tabIndex={-1}>
                  Submit Screening to Zeus
                </h3>
                <p>{submitPreview.stage.purpose}</p>
              </div>
              <dl className="transfer-facts">
                <div>
                  <dt>Campaign</dt>
                  <dd>{submitPreview.campaign.name}</dd>
                </div>
                <div>
                  <dt>Stage</dt>
                  <dd>{submitPreview.stage.label}</dd>
                </div>
                <div>
                  <dt>Fixed s₀ values</dt>
                  <dd>{submitPreview.campaign.s0_values.join(", ")}</dd>
                </div>
                <div>
                  <dt>PBS file</dt>
                  <dd>
                    <code>{submitPreview.job.file}</code>
                  </dd>
                </div>
                <div>
                  <dt>Scheduler request</dt>
                  <dd>1 array job · {submitPreview.job.task_count} tasks</dd>
                </div>
                <div>
                  <dt>Concurrent-task limit</dt>
                  <dd>
                    At most {submitPreview.job.array_throttle} tasks at once
                  </dd>
                </div>
                <div>
                  <dt>Queue</dt>
                  <dd>
                    <code>{submitPreview.job.queue}</code>
                  </dd>
                </div>
                <div>
                  <dt>Resources per task</dt>
                  <dd>
                    {submitPreview.job.cores_per_task} CPU cores ·{" "}
                    {Math.round(
                      submitPreview.job.memory_per_task_bytes / 1024 ** 3,
                    )}{" "}
                    GiB memory
                  </dd>
                </div>
                <div>
                  <dt>Walltime limit per task</dt>
                  <dd>{submitPreview.job.walltime_seconds / 3600} hours</dd>
                </div>
                <div>
                  <dt>Validated smoke job</dt>
                  <dd>
                    <code>{submitPreview.smoke.job_id}</code> ·{" "}
                    {submitPreview.smoke.point_count} points
                  </dd>
                </div>
                <div>
                  <dt>Remote code</dt>
                  <dd>
                    Branch {submitPreview.remote.branch} · exact commit{" "}
                    <code>{submitPreview.remote.commit.slice(0, 12)}</code> ·
                    clean worktree
                  </dd>
                </div>
                <div>
                  <dt>Campaign inputs</dt>
                  <dd>
                    Ready · all {submitPreview.inputs.verified_count} artifacts
                    verified
                  </dd>
                </div>
              </dl>
              <ul className="effect-list">
                <li>
                  <CheckCircle2 aria-hidden="true" /> Submits Screening only.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Does not submit any later
                  stage.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Does not modify campaign
                  files.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Later stages remain
                  locked.
                </li>
              </ul>
              <div className="submission-attention">
                <strong>One real Zeus submission</strong>
                <p>
                  Confirming performs exactly one <code>qsub</code> for this PBS
                  array. Nothing is submitted automatically.
                </p>
              </div>
              <div className="form-actions">
                <button
                  className="text-button"
                  type="button"
                  disabled={submitState === "submitting"}
                  onClick={onResetSubmit}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={submitState === "submitting"}
                  onClick={onConfirmSubmit}
                >
                  {submitState === "submitting" ? (
                    <>
                      <LoaderCircle aria-hidden="true" /> Submitting…
                    </>
                  ) : (
                    "Submit Screening to Zeus"
                  )}
                </button>
              </div>
            </div>
          )}
          {submitError && (
            <div
              ref={submitPanel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {submitState === "unknown"
                    ? "Submission outcome needs manual verification"
                    : submitState === "terminal"
                      ? "Screening will not be submitted again"
                      : "Screening submission could not be verified"}
                </strong>
                <p>{submitError}</p>
                {["unknown", "terminal"].includes(submitState) ? (
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
                    onClick={onResetSubmit}
                  >
                    Review again
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      )}
      {submitState === "submitted" && submitResult && !lifecycle && (
        <section
          className="section-block"
          aria-labelledby="screen-submit-success-heading"
        >
          <div
            ref={submitPanel}
            className="connection-panel connection-panel--connected"
            role="status"
            tabIndex={-1}
          >
            <CheckCircle2 aria-hidden="true" />
            <div>
              <strong id="screen-submit-success-heading">
                Screening submitted
              </strong>
              <p>
                Zeus job <code>{submitResult.job_id}</code> was recorded at{" "}
                <time dateTime={submitResult.submitted_at}>
                  {timestamp(submitResult.submitted_at)}
                </time>
                .
              </p>
              <p>
                This receipt records only the Screening submission. Later
                stages have separate receipts. Zeus continues independently;
                it is safe to close this application.
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
        </section>
      )}
    </>
  );
}

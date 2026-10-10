import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type {
  ScreeningPreview,
  ScreeningResult,
  SmokeLifecycle,
  SmokeSubmissionPreview,
  SmokeSubmissionResult,
} from "../../api/clients/smoke";
import { SmokePointsTable } from "./SmokeStage";
import type { ScreeningPreparationState, SmokeCheckState, SmokeSubmitState } from "./controllers/useSmokeController";
const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
export function SmokeFlow({
  visible,
  canSubmit,
  submissionState,
  submissionPreview,
  submissionResult,
  submissionError,
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  screeningState,
  screeningPreview,
  screeningResult,
  screeningError,
  onPreviewSubmission,
  onConfirmSubmission,
  onResetSubmission,
  onRefreshLifecycle,
  onPreviewScreening,
  onConfirmScreening,
  onResetScreening,
  onViewJobs,
}: {
  visible: boolean;
  canSubmit: boolean;
  submissionState: SmokeSubmitState;
  submissionPreview: SmokeSubmissionPreview | null;
  submissionResult: SmokeSubmissionResult | null;
  submissionError: string;
  lifecycle: SmokeLifecycle | null;
  lifecycleCheck: SmokeCheckState;
  lifecycleError: string;
  screeningState: ScreeningPreparationState;
  screeningPreview: ScreeningPreview | null;
  screeningResult: ScreeningResult | null;
  screeningError: string;
  onPreviewSubmission: () => void;
  onConfirmSubmission: () => void;
  onResetSubmission: () => void;
  onRefreshLifecycle: () => void;
  onPreviewScreening: () => void;
  onConfirmScreening: () => void;
  onResetScreening: () => void;
  onViewJobs: () => void;
}) {
  const submissionButton = useRef<HTMLButtonElement>(null);
  const submissionHeading = useRef<HTMLHeadingElement>(null);
  const submissionSuccess = useRef<HTMLDivElement>(null);
  const submissionErrorPanel = useRef<HTMLDivElement>(null);
  const lifecycleHeading = useRef<HTMLHeadingElement>(null);
  const lifecycleErrorPanel = useRef<HTMLDivElement>(null);
  const screeningButton = useRef<HTMLButtonElement>(null);
  const screeningHeading = useRef<HTMLHeadingElement>(null);
  const screeningSuccess = useRef<HTMLDivElement>(null);
  const screeningErrorPanel = useRef<HTMLDivElement>(null);
  const previousSubmissionState = useRef(submissionState);
  const previousLifecycleCheck = useRef(lifecycleCheck);
  const previousScreeningState = useRef(screeningState);
  useEffect(() => {
    const previous = previousSubmissionState.current;
    if (submissionError) submissionErrorPanel.current?.focus();
    else if (submissionState === "review") submissionHeading.current?.focus();
    else if (submissionState === "submitted")
      submissionSuccess.current?.focus();
    else if (submissionState === "idle" && previous === "review")
      submissionButton.current?.focus();
    previousSubmissionState.current = submissionState;
  }, [submissionState, submissionError]);
  useEffect(() => {
    if (lifecycleError) lifecycleErrorPanel.current?.focus();
    else if (
      lifecycleCheck === "ready" &&
      previousLifecycleCheck.current !== "ready"
    )
      lifecycleHeading.current?.focus();
    previousLifecycleCheck.current = lifecycleCheck;
  }, [lifecycleCheck, lifecycleError]);
  useEffect(() => {
    if (screeningError) screeningErrorPanel.current?.focus();
    else if (screeningState === "review") screeningHeading.current?.focus();
    else if (screeningState === "success") screeningSuccess.current?.focus();
    else if (
      screeningState === "idle" &&
      previousScreeningState.current === "review"
    )
      screeningButton.current?.focus();
    previousScreeningState.current = screeningState;
  }, [screeningState, screeningError]);
  if (!visible) return null;
  const remoteLifecycle = lifecycle?.lifecycle;
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
                    <dd>{submissionPreview.job.cores_per_task} CPU {submissionPreview.job.cores_per_task === 1 ? "core" : "cores"} · {Math.round(submissionPreview.job.memory_per_task_bytes / 1024 ** 3)} GB memory</dd>
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
                      : "Smoke submission stopped safely"}
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
      <section className="section-block" aria-labelledby="remote-smoke-heading">
        <div className="section-heading">
          <h2 id="remote-smoke-heading">Smoke check on Zeus</h2>
          <p>
            Request a fresh, read-only check of the scheduler and scientifically
            validated smoke outputs.
          </p>
        </div>
        <div className="remote-status-toolbar">
          <div>
            <strong>Zeus is the execution source</strong>
            <p>
              {lifecycle ? (
                <>
                  Last checked{" "}
                  <time dateTime={lifecycle.queried_at}>
                    {timestamp(lifecycle.queried_at)}
                  </time>
                  .
                </>
              ) : (
                "No current smoke snapshot is loaded."
              )}
            </p>
          </div>
          <button
            className="secondary-button"
            type="button"
            disabled={lifecycleCheck === "checking"}
            onClick={onRefreshLifecycle}
          >
            {lifecycleCheck === "checking" ? (
              <>
                <LoaderCircle aria-hidden="true" /> Checking…
              </>
            ) : (
              <>
                <RefreshCw aria-hidden="true" />{" "}
                {lifecycle ? "Refresh smoke status" : "Check smoke status"}
              </>
            )}
          </button>
        </div>
        <div className="sr-only" aria-live="polite">
          {lifecycleCheck === "checking"
            ? "Checking smoke status on Zeus."
            : lifecycle
              ? `Smoke lifecycle: ${words(lifecycle.lifecycle)}.`
              : ""}
        </div>
        {lifecycle && (
          <div
            className={`remote-status-card remote-status-card--${lifecycle.lifecycle}`}
          >
            <div className="remote-status-title">
              <Clock3 aria-hidden="true" />
              <div>
                <h3 ref={lifecycleHeading} tabIndex={-1}>
                  {remoteLifecycle === "ready_to_prepare_screen"
                    ? "Smoke outputs validated"
                    : remoteLifecycle === "screen_prepared"
                      ? "Screening preparation complete"
                      : `Smoke check ${words(remoteLifecycle ?? "unknown")}`}
                </h3>
                <p>
                  Job <code>{lifecycle.submission.job_id}</code> · scheduler
                  state: {words(lifecycle.scheduler.state)}
                </p>
              </div>
            </div>
            {lifecycle.validation.status === "valid" && (
              <>
                <p className="validation-note">
                  <CheckCircle2 aria-hidden="true" /> All{" "}
                  {lifecycle.validation.artifact_count} expected artifacts
                  passed the frozen design and provenance checks. A zero-capture
                  smoke point is valid: this stage checks execution integrity,
                  not performance.
                </p>
                <SmokePointsTable points={lifecycle.validation.points} />
              </>
            )}
            {[
              "held_attention",
              "failed",
              "outputs_invalid",
              "unknown",
            ].includes(remoteLifecycle ?? "") && (
              <div className="status-actions">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={onViewJobs}
                >
                  View Zeus jobs
                </button>
              </div>
            )}
          </div>
        )}
        {lifecycleError && (
          <div
            ref={lifecycleErrorPanel}
            className="state-panel state-panel--error"
            role="alert"
            tabIndex={-1}
          >
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Smoke status is unavailable</strong>
              <p>{lifecycleError}</p>
              <p>
                No previous snapshot is being used as evidence. Try a fresh
                check or inspect Zeus jobs.
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
      </section>
      {remoteLifecycle === "ready_to_prepare_screen" && (
        <section className="section-block" aria-labelledby="screening-heading">
          <div className="section-heading">
            <h2 id="screening-heading">Prepare the screening stage</h2>
            <p>
              Review the exact remote file transition. This does not submit
              screening or start a simulation.
            </p>
          </div>
          {screeningState === "idle" && (
            <div className="prepare-card">
              <div>
                <strong>Validated smoke evidence is ready</strong>
                <p>
                  Preparation creates the task registry and PBS file, then
                  records Screening as the prepared stage on Zeus.
                </p>
              </div>
              <button
                ref={screeningButton}
                className="primary-button"
                type="button"
                onClick={onPreviewScreening}
              >
                Review screening preparation
              </button>
            </div>
          )}
          {screeningState === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing the screening transition</strong>
                <p>No files are being changed and no job is being submitted.</p>
              </div>
            </div>
          )}
          {screeningPreview &&
            ["review", "preparing"].includes(screeningState) && (
              <div
                className="transfer-review"
                aria-busy={screeningState === "preparing"}
              >
                <div className="section-heading">
                  <p className="eyebrow">Final review</p>
                  <h3 ref={screeningHeading} tabIndex={-1}>
                    Prepare Screening on Zeus
                  </h3>
                  <p>
                    The smoke check passed for every fixed s₀ value. Review the
                    complete file change before continuing.
                  </p>
                </div>
                <dl className="transfer-facts">
                  <div>
                    <dt>Campaign</dt>
                    <dd>{screeningPreview.campaign.name}</dd>
                  </div>
                  <div>
                    <dt>Transition</dt>
                    <dd>Smoke check → Screening</dd>
                  </div>
                  <div>
                    <dt>Validated smoke job</dt>
                    <dd>
                      <code>{screeningPreview.smoke.job_id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Validated smoke artifacts</dt>
                    <dd>{screeningPreview.smoke.artifact_count}</dd>
                  </div>
                  <div>
                    <dt>Create</dt>
                    <dd>
                      {screeningPreview.artifacts.create.map((path) => (
                        <code className="stacked-code" key={path}>
                          {path}
                        </code>
                      ))}
                    </dd>
                  </div>
                  <div>
                    <dt>Update</dt>
                    <dd>
                      {screeningPreview.artifacts.update.map((path) => (
                        <code className="stacked-code" key={path}>
                          {path}
                        </code>
                      ))}
                    </dd>
                  </div>
                  <div>
                    <dt>Exact code</dt>
                    <dd>
                      <code>
                        {screeningPreview.campaign.git_commit.slice(0, 12)}
                      </code>
                    </dd>
                  </div>
                  <div>
                    <dt>Local record</dt>
                    <dd>Not synchronized after this remote transition</dd>
                  </div>
                </dl>
                <ul className="effect-list">
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Prepares only the
                    Screening files.
                  </li>
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Does not submit a Zeus
                    job.
                  </li>
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Does not start a
                    simulation.
                  </li>
                  <li>
                    <CheckCircle2 aria-hidden="true" /> Stops if conflicting
                    stage artifacts exist; otherwise advances the campaign
                    record only after all stage files are safely prepared.
                  </li>
                </ul>
                <div className="submission-attention">
                  <strong>Attention</strong>
                  <p>
                    This changes the remote campaign from Smoke check to
                    Screening. You will review the Screening job separately
                    before it can be submitted.
                  </p>
                </div>
                <div className="form-actions">
                  <button
                    className="text-button"
                    type="button"
                    disabled={screeningState === "preparing"}
                    onClick={onResetScreening}
                  >
                    Back
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={screeningState === "preparing"}
                    onClick={onConfirmScreening}
                  >
                    {screeningState === "preparing" ? (
                      <>
                        <LoaderCircle aria-hidden="true" /> Preparing…
                      </>
                    ) : (
                      "Prepare Screening on Zeus"
                    )}
                  </button>
                </div>
              </div>
            )}
          {screeningError && (
            <div
              ref={screeningErrorPanel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {screeningState === "terminal"
                    ? "Screening state needs manual verification"
                    : "Screening preparation stopped safely"}
                </strong>
                <p>{screeningError}</p>
                {screeningState === "terminal" && (
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      )}
      {screeningState === "success" && screeningResult && (
        <section
          className="section-block"
          aria-labelledby="screening-success-heading"
        >
          <div
            ref={screeningSuccess}
            className="connection-panel connection-panel--connected"
            role="status"
            tabIndex={-1}
          >
            <CheckCircle2 aria-hidden="true" />
            <div>
              <strong id="screening-success-heading">
                Screening prepared on Zeus
              </strong>
              <p>
                {screeningResult.artifacts.created} files created and{" "}
                {screeningResult.artifacts.updated} campaign record updated.
              </p>
              <p>No Screening job was submitted and no simulation started.</p>
              <p>
                Zeus is current; the local campaign record has not been
                synchronized.
              </p>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

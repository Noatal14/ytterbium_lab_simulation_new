import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type {
  RefinementPreview,
  RefinementResult,
  ScreeningLifecycle,
  ScreeningSubmissionPreview,
  ScreeningSubmissionResult,
} from "../../api/clients/screening";
import { ScreeningFacts } from "./ScreeningStage";
import type { RefinementPreparationState as PrepareState, ScreeningCheckState as CheckState, ScreeningSubmitState as SubmitState } from "./controllers/useScreeningController";
const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
export function ScreeningFlow({
  visible,
  evidenceFresh,
  smokeCheck,
  submitState,
  submitPreview,
  submitResult,
  submitError,
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  prepareState,
  preparePreview,
  prepareResult,
  prepareError,
  onRefreshSmoke,
  onPreviewSubmit,
  onConfirmSubmit,
  onResetSubmit,
  onRefreshLifecycle,
  onPreviewPrepare,
  onConfirmPrepare,
  onResetPrepare,
  onViewJobs,
}: {
  visible: boolean;
  evidenceFresh: boolean;
  smokeCheck: CheckState;
  submitState: SubmitState;
  submitPreview: ScreeningSubmissionPreview | null;
  submitResult: ScreeningSubmissionResult | null;
  submitError: string;
  lifecycle: ScreeningLifecycle | null;
  lifecycleCheck: CheckState;
  lifecycleError: string;
  prepareState: PrepareState;
  preparePreview: RefinementPreview | null;
  prepareResult: RefinementResult | null;
  prepareError: string;
  onRefreshSmoke: () => void;
  onPreviewSubmit: () => void;
  onConfirmSubmit: () => void;
  onResetSubmit: () => void;
  onRefreshLifecycle: () => void;
  onPreviewPrepare: () => void;
  onConfirmPrepare: () => void;
  onResetPrepare: () => void;
  onViewJobs: () => void;
}) {
  const submitButton = useRef<HTMLButtonElement>(null);
  const submitHeading = useRef<HTMLHeadingElement>(null);
  const submitPanel = useRef<HTMLDivElement>(null);
  const statusHeading = useRef<HTMLHeadingElement>(null);
  const statusErrorPanel = useRef<HTMLDivElement>(null);
  const prepareButton = useRef<HTMLButtonElement>(null);
  const prepareHeading = useRef<HTMLHeadingElement>(null);
  const preparePanel = useRef<HTMLDivElement>(null);
  const previousSubmitState = useRef(submitState);
  const previousCheck = useRef(lifecycleCheck);
  const previousPrepareState = useRef(prepareState);
  useEffect(() => {
    const previous = previousSubmitState.current;
    if (submitState === "review") submitHeading.current?.focus();
    else if (
      ["submitted", "unknown", "terminal", "error"].includes(submitState)
    )
      submitPanel.current?.focus();
    else if (submitState === "idle" && previous === "review")
      submitButton.current?.focus();
    previousSubmitState.current = submitState;
  }, [submitState]);
  useEffect(() => {
    if (lifecycleError) statusErrorPanel.current?.focus();
    else if (lifecycleCheck === "ready" && previousCheck.current !== "ready")
      statusHeading.current?.focus();
    previousCheck.current = lifecycleCheck;
  }, [lifecycleCheck, lifecycleError]);
  useEffect(() => {
    const previous = previousPrepareState.current;
    if (prepareState === "review") prepareHeading.current?.focus();
    else if (["success", "terminal"].includes(prepareState) || prepareError)
      preparePanel.current?.focus();
    else if (prepareState === "idle" && previous === "review")
      prepareButton.current?.focus();
    previousPrepareState.current = prepareState;
  }, [prepareState, prepareError]);
  if (!visible) return null;
  const screenLifecycle = lifecycle?.lifecycle;
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
                    GB memory
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
                      : "Screening submission stopped safely"}
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
                No later stage was submitted. Zeus continues independently; no
                action is needed and it is safe to close this application.
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
      <section
        className="section-block"
        aria-labelledby="screen-status-heading"
      >
        <div className="section-heading">
          <h2 id="screen-status-heading">Screening on Zeus</h2>
          <p>
            Request a fresh, read-only check of the Screening array and its
            scientifically validated outputs. This also recovers a durable
            Screening submission after reopening the application.
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
                "No current Screening snapshot is loaded."
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
                {lifecycle
                  ? "Refresh Screening status"
                  : "Check Screening status"}
              </>
            )}
          </button>
        </div>
        <div className="sr-only" aria-live="polite">
          {lifecycleCheck === "checking"
            ? "Checking Screening status on Zeus."
            : lifecycle
              ? `Screening lifecycle: ${words(lifecycle.lifecycle)}.`
              : ""}
        </div>
        {lifecycle && (
          <div
            className={`remote-status-card remote-status-card--${screenLifecycle}`}
          >
            <div className="remote-status-title">
              <Clock3 aria-hidden="true" />
              <div>
                <h3 ref={statusHeading} tabIndex={-1}>
                  {screenLifecycle === "ready_to_prepare_refinement"
                    ? "Screening results validated"
                    : screenLifecycle === "refinement_prepared"
                      ? "Refinement preparation complete"
                      : words(screenLifecycle ?? "unknown")}
                </h3>
                <p>
                  Array job <code>{lifecycle.submission.job_id}</code> ·
                  scheduler state: {words(lifecycle.scheduler.state)}
                </p>
              </div>
            </div>
            <ScreeningFacts lifecycle={lifecycle} />
            {lifecycle.validation.status === "valid" && (
              <p className="validation-note">
                <CheckCircle2 aria-hidden="true" /> All expected trials passed
                the frozen design and provenance checks.{" "}
                {lifecycle.validation.candidate_count} candidates were selected
                for Refinement review.
              </p>
            )}
            {[
              "screen_held",
              "screen_failed",
              "screen_status_unknown",
              "outputs_invalid",
            ].includes(screenLifecycle ?? "") && (
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
            ref={statusErrorPanel}
            className="state-panel state-panel--error"
            role="alert"
            tabIndex={-1}
          >
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Screening status is unavailable</strong>
              <p>{lifecycleError}</p>
              <p>
                No previous snapshot is used as evidence. Try a fresh check or
                inspect Zeus jobs.
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
      {screenLifecycle === "ready_to_prepare_refinement" && (
        <section className="section-block" aria-labelledby="refine-heading">
          <div className="section-heading">
            <h2 id="refine-heading">Prepare Refinement</h2>
            <p>
              Review the exact candidate selection and files. This preparation
              does not submit a job or start a simulation.
            </p>
          </div>
          {prepareState === "idle" && (
            <div className="prepare-card">
              <div>
                <strong>Validated Screening results are ready</strong>
                <p>
                  The preview freezes the three selected candidates per fixed s₀
                  value and shows every file that will be created.
                </p>
              </div>
              <button
                ref={prepareButton}
                className="primary-button"
                type="button"
                onClick={onPreviewPrepare}
              >
                Review Refinement preparation
              </button>
            </div>
          )}
          {prepareState === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing Refinement preparation</strong>
                <p>No files are being changed and no job is being submitted.</p>
              </div>
            </div>
          )}
          {preparePreview && ["review", "preparing"].includes(prepareState) && (
            <div
              className="transfer-review"
              aria-busy={prepareState === "preparing"}
            >
              <div className="section-heading">
                <p className="eyebrow">Final review</p>
                <h3 ref={prepareHeading} tabIndex={-1}>
                  Prepare Refinement on Zeus
                </h3>
                <p>
                  These candidates are selected from completed Screening trials.
                  Their reported efficiencies are Screening estimates, not final
                  performance measurements.
                </p>
              </div>
              <dl className="transfer-facts">
                <div>
                  <dt>Campaign</dt>
                  <dd>{preparePreview.campaign.name}</dd>
                </div>
                <div>
                  <dt>Transition</dt>
                  <dd>Screening → Refinement</dd>
                </div>
                <div>
                  <dt>Validated Screening array</dt>
                  <dd>
                    <code>{preparePreview.screening.job_id}</code>
                  </dd>
                </div>
                <div>
                  <dt>Completed trials</dt>
                  <dd>
                    {preparePreview.screening.completed_trials} of{" "}
                    {preparePreview.screening.expected_trials}
                  </dd>
                </div>
                <div>
                  <dt>Selected candidates</dt>
                  <dd>
                    {preparePreview.screening.candidates.length} · three per
                    fixed s₀
                  </dd>
                </div>
                <div>
                  <dt>Frozen detuning bounds</dt>
                  <dd>
                    {preparePreview.bounds.detuning_gamma.low} to{" "}
                    {preparePreview.bounds.detuning_gamma.high} Γ
                  </dd>
                </div>
                <div>
                  <dt>Frozen radius bounds</dt>
                  <dd>
                    {(preparePreview.bounds.magnet_radius_m.low * 1000).toFixed(
                      1,
                    )}{" "}
                    to{" "}
                    {(
                      preparePreview.bounds.magnet_radius_m.high * 1000
                    ).toFixed(1)}{" "}
                    mm
                  </dd>
                </div>
                <div>
                  <dt>Files created</dt>
                  <dd>
                    {preparePreview.artifacts.create.map((path) => (
                      <code className="stacked-code" key={path}>
                        {path}
                      </code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>File updated</dt>
                  <dd>
                    <code>{preparePreview.artifacts.update[0]}</code>
                  </dd>
                </div>
                <div>
                  <dt>Exact code</dt>
                  <dd>
                    <code>
                      {preparePreview.campaign.git_commit.slice(0, 12)}
                    </code>
                  </dd>
                </div>
                <div>
                  <dt>Local record</dt>
                  <dd>Not synchronized after this remote transition</dd>
                </div>
              </dl>
              <div
                className="smoke-points"
                role="region"
                aria-label="Selected Screening candidates"
                tabIndex={0}
              >
                <table>
                  <caption>Selected candidates from Screening</caption>
                  <thead>
                    <tr>
                      <th scope="col">Fixed s₀</th>
                      <th scope="col">Rank</th>
                      <th scope="col">Detuning</th>
                      <th scope="col">Magnet radius</th>
                      <th scope="col">Screening estimate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preparePreview.screening.candidates.map((candidate) => (
                      <tr key={candidate.source}>
                        <td>{candidate.s0}</td>
                        <td>{candidate.rank}</td>
                        <td>{candidate.detuning_gamma.toFixed(3)} Γ</td>
                        <td>
                          {(candidate.magnet_radius_m * 1000).toFixed(3)} mm
                        </td>
                        <td>
                          {new Intl.NumberFormat("en", {
                            style: "percent",
                            maximumFractionDigits: 2,
                          }).format(candidate.mean_conditional_efficiency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="effect-list">
                <li>
                  <CheckCircle2 aria-hidden="true" /> Prepares only Refinement
                  files.
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
                  <CheckCircle2 aria-hidden="true" /> Stops if conflicting stage
                  artifacts exist; otherwise advances the campaign record only
                  after all stage files are safely prepared.
                </li>
              </ul>
              <div className="submission-attention">
                <strong>Remote file transition only</strong>
                <p>
                  Confirming creates seven files and updates the remote campaign
                  record. Refinement submission will require a separate review
                  later.
                </p>
              </div>
              <div className="form-actions">
                <button
                  className="text-button"
                  type="button"
                  disabled={prepareState === "preparing"}
                  onClick={onResetPrepare}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={prepareState === "preparing"}
                  onClick={onConfirmPrepare}
                >
                  {prepareState === "preparing" ? (
                    <>
                      <LoaderCircle aria-hidden="true" /> Preparing…
                    </>
                  ) : (
                    "Prepare Refinement on Zeus"
                  )}
                </button>
              </div>
            </div>
          )}
          {prepareError && (
            <div
              ref={preparePanel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {prepareState === "terminal"
                    ? "Refinement state needs manual verification"
                    : "Refinement preparation stopped safely"}
                </strong>
                <p>{prepareError}</p>
                {prepareState === "terminal" ? (
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
                    onClick={onResetPrepare}
                  >
                    Review again
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      )}
      {prepareState === "success" && prepareResult && (
        <section
          className="section-block"
          aria-labelledby="refine-success-heading"
        >
          <div
            ref={preparePanel}
            className="connection-panel connection-panel--connected"
            role="status"
            tabIndex={-1}
          >
            <CheckCircle2 aria-hidden="true" />
            <div>
              <strong id="refine-success-heading">
                Refinement prepared on Zeus
              </strong>
              <p>
                {prepareResult.artifacts.created} files created and{" "}
                {prepareResult.artifacts.updated} campaign record updated.
              </p>
              <p>No Refinement job was submitted and no simulation started.</p>
              <p>
                Zeus is authoritative; the local campaign record has not been
                synchronized.
              </p>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

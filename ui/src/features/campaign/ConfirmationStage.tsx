import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type {
  ConfirmationPreview,
  ConfirmationResult,
  RefinementLifecycle,
} from "../../api/clients/refinement";
import { CandidateTable } from "../shared/CandidateTable";
import { JobResources } from "../shared/JobResources";
import { ManualVerification } from "../shared/ActionError";
import { ReviewEffects } from "../shared/ReviewEffects";
import { StatusSnapshot } from "../shared/StatusSnapshot";
const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
export type ConfirmationUiState =
  | "idle"
  | "previewing"
  | "review"
  | "preparing"
  | "success"
  | "terminal";
export function ConfirmationStage(props: {
  visible: boolean;
  lifecycle: RefinementLifecycle | null;
  lifecycleCheck: "idle" | "checking" | "ready" | "error";
  state: ConfirmationUiState;
  preview: ConfirmationPreview | null;
  result: ConfirmationResult | null;
  error: string;
  onRefresh: () => void;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  const lifecycleHeading = useRef<HTMLHeadingElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const previousLifecycleCheck = useRef(props.lifecycleCheck);
  const previousState = useRef(props.state);
  useEffect(() => {
    if (
      props.lifecycleCheck === "ready" &&
      previousLifecycleCheck.current !== "ready"
    )
      lifecycleHeading.current?.focus();
    previousLifecycleCheck.current = props.lifecycleCheck;
  }, [props.lifecycleCheck]);
  useEffect(() => {
    const previous = previousState.current;
    if (props.state === "review") heading.current?.focus();
    else if (["success", "terminal"].includes(props.state) || props.error)
      panel.current?.focus();
    else if (props.state === "idle" && previous === "review")
      button.current?.focus();
    previousState.current = props.state;
  }, [props.state, props.error]);
  if (!props.visible) return null;
  const lifecycle = props.lifecycle;
  return (
    <>
      <section
        className="section-block"
        aria-labelledby="refinement-lifecycle-heading"
      >
        <div className="section-heading">
          <h2 id="refinement-lifecycle-heading">Refinement progress on Zeus</h2>
          <p>
            Request a fresh read-only snapshot of all four dependent arrays and
            their validated results.
          </p>
        </div>
        <StatusSnapshot
          source="Zeus is the execution source"
          checkedAt={
            lifecycle ? (
              <>
                Last checked{" "}
                <time dateTime={lifecycle.queried_at}>
                  {timestamp(lifecycle.queried_at)}
                </time>
                .
              </>
            ) : (
              "No current Refinement snapshot is loaded."
            )
          }
          checking={props.lifecycleCheck === "checking"}
          onRefresh={props.onRefresh}
          refreshLabel={
            lifecycle ? "Refresh Refinement status" : "Check Refinement status"
          }
          liveText={
            props.lifecycleCheck === "checking"
              ? "Checking Refinement status on Zeus."
              : lifecycle
                ? `Refinement lifecycle: ${words(lifecycle.chain.status)}.`
                : ""
          }
        />
        {lifecycle && (
          <div
            className={`remote-status-card remote-status-card--${lifecycle.chain.status}`}
          >
            <div className="remote-status-title">
              <Clock3 aria-hidden="true" />
              <div>
                <h3 ref={lifecycleHeading} tabIndex={-1}>
                  {lifecycle.chain.status === "ready_to_prepare_confirmation"
                    ? "Refinement results validated"
                    : lifecycle.chain.status === "confirmation_prepared"
                      ? "Confirmation preparation complete"
                      : words(lifecycle.chain.status)}
                </h3>
                <p>Source: Zeus · local record not synchronized</p>
              </div>
            </div>
            <ol className="chain-rounds" aria-label="Refinement round progress">
              {lifecycle.chain.rounds.map((round) => (
                <li key={round.round}>
                  <strong>Round {round.round}</strong>
                  <code>{round.job_id}</code>
                  <span>{words(round.scheduler.state)}</span>
                  {round.depends_on_job_id && (
                    <small>afterok {round.depends_on_job_id}</small>
                  )}
                  <small>
                    {round.scheduler.counts.succeeded} of{" "}
                    {round.scheduler.task_count} tasks succeeded
                  </small>
                </li>
              ))}
            </ol>
            <p>
              <strong>Validated trials:</strong>{" "}
              {lifecycle.validation.completed_trials} of{" "}
              {lifecycle.validation.expected_trials}
            </p>
            {lifecycle.validation.status === "valid" && (
              <p className="validation-note">
                <CheckCircle2 aria-hidden="true" /> All final Refinement trials
                passed frozen-design and provenance checks.{" "}
                {lifecycle.validation.candidate_count} candidates are ready for
                Confirmation review.
              </p>
            )}
            {["held", "failed", "status_unknown", "outputs_invalid"].includes(
              lifecycle.chain.status,
            ) && (
              <div className="submission-attention">
                <strong>Automatic advancement is blocked</strong>
                <p>
                  Inspect the exact jobs on Zeus. This snapshot cannot authorize
                  Confirmation preparation.
                </p>
                <button
                  className="secondary-button compact-action"
                  type="button"
                  onClick={props.onViewJobs}
                >
                  View Zeus jobs
                </button>
              </div>
            )}
          </div>
        )}
        {props.lifecycleCheck === "error" && props.error && (
          <div
            ref={panel}
            className="state-panel state-panel--error"
            role="alert"
            tabIndex={-1}
          >
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Refinement status is unavailable</strong>
              <p>{props.error}</p>
              <p>No stale snapshot is used as evidence.</p>
            </div>
          </div>
        )}
      </section>
      {lifecycle?.chain.status === "ready_to_prepare_confirmation" && (
        <section
          className="section-block"
          aria-labelledby="confirmation-heading"
        >
          <div className="section-heading">
            <h2 id="confirmation-heading">Prepare Confirmation</h2>
            <p>
              Review the selected candidates and exact files. This preparation
              does not submit a job or start a simulation.
            </p>
          </div>
          {props.state === "idle" && (
            <div className="prepare-card">
              <div>
                <strong>Validated Refinement results are ready</strong>
                <p>
                  The preview shows five candidates per fixed s₀ and labels
                  their Refinement efficiencies as selection estimates.
                </p>
              </div>
              <button
                ref={button}
                className="primary-button"
                type="button"
                onClick={props.onPreview}
              >
                Review Confirmation preparation
              </button>
            </div>
          )}
          {props.state === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing Confirmation preparation</strong>
                <p>No files are being changed and no job is being submitted.</p>
              </div>
            </div>
          )}
          {props.preview && ["review", "preparing"].includes(props.state) && (
            <div
              className="transfer-review"
              aria-busy={props.state === "preparing"}
            >
              <div className="section-heading">
                <p className="eyebrow">Final review</p>
                <h3 ref={heading} tabIndex={-1}>
                  Prepare Confirmation on Zeus
                </h3>
                <p>
                  These are Refinement selection estimates, not final sealed
                  performance measurements.
                </p>
              </div>
              <dl className="transfer-facts">
                <div>
                  <dt>Transition</dt>
                  <dd>Refinement → Confirmation</dd>
                </div>
                <div>
                  <dt>Validated trials</dt>
                  <dd>
                    {props.preview.refinement.completed_trials} of{" "}
                    {props.preview.refinement.expected_trials}
                  </dd>
                </div>
                <div>
                  <dt>Selected candidates</dt>
                  <dd>
                    {props.preview.refinement.candidates.length} · five per
                    fixed s₀
                  </dd>
                </div>
                <div>
                  <dt>Refinement jobs</dt>
                  <dd>
                    {props.preview.refinement.round_job_ids.map((id) => (
                      <code className="stacked-code" key={id}>
                        {id}
                      </code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>Files created</dt>
                  <dd>
                    {props.preview.artifacts.create.map((path) => (
                      <code className="stacked-code" key={path}>
                        {path}
                      </code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>File updated</dt>
                  <dd>
                    <code>{props.preview.artifacts.update[0]}</code>
                  </dd>
                </div>
                <div>
                  <dt>Prepared job</dt>
                  <dd>
                    <code>{props.preview.job.file}</code> ·{" "}
                    {props.preview.job.task_count} tasks · throttle{" "}
                    {props.preview.job.array_throttle}
                  </dd>
                </div>
                <div>
                  <dt>Resources</dt>
                  <dd>
                    <JobResources job={props.preview.job} />
                  </dd>
                </div>
              </dl>
              <CandidateTable
                candidates={props.preview.refinement.candidates}
                caption="Selected candidates from Refinement"
                estimateLabel="Refinement estimate"
              />
              <ReviewEffects>
                {[
                  <>Prepares only Confirmation files.</>,
                  <>Does not submit a Zeus job.</>,
                  <>Does not start a simulation.</>,
                  <>
                    Stops if conflicting stage artifacts exist; otherwise
                    advances the campaign record only after all stage files are
                    safely prepared.
                  </>,
                ]}
              </ReviewEffects>
              <div className="form-actions">
                <button
                  className="text-button"
                  type="button"
                  disabled={props.state === "preparing"}
                  onClick={props.onReset}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={props.state === "preparing"}
                  onClick={props.onConfirm}
                >
                  {props.state === "preparing" ? (
                    <>
                      <LoaderCircle aria-hidden="true" /> Preparing…
                    </>
                  ) : (
                    "Prepare Confirmation on Zeus"
                  )}
                </button>
              </div>
            </div>
          )}
          {props.error &&
            props.state !== "terminal" &&
            props.lifecycleCheck !== "error" && (
              <div
                ref={panel}
                className="state-panel state-panel--error"
                role="alert"
                tabIndex={-1}
              >
                <AlertTriangle aria-hidden="true" />
                <div>
                  <strong>Confirmation preparation stopped safely</strong>
                  <p>{props.error}</p>
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={props.onReset}
                  >
                    Review again
                  </button>
                </div>
              </div>
            )}
        </section>
      )}
      {props.state === "terminal" && props.error && (
        <section
          className="section-block"
          aria-labelledby="confirmation-terminal-heading"
        >
          <ManualVerification
            title="Confirmation state needs manual verification"
            message={`${props.error} The reviewed preview is no longer usable. Automatic retry is blocked even if a fresh status check is unavailable.`}
            onViewJobs={props.onViewJobs}
            panelRef={panel}
          />
        </section>
      )}
      {props.state === "success" && props.result && (
        <section
          className="section-block"
          aria-labelledby="confirmation-success-heading"
        >
          <div
            ref={panel}
            className="connection-panel connection-panel--connected"
            role="status"
            tabIndex={-1}
          >
            <CheckCircle2 aria-hidden="true" />
            <div>
              <strong id="confirmation-success-heading">
                Confirmation prepared on Zeus
              </strong>
              <p>
                {props.result.artifacts.created} files created and{" "}
                {props.result.artifacts.updated} campaign record updated.
              </p>
              <p>
                No Confirmation job was submitted and no simulation started.
              </p>
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

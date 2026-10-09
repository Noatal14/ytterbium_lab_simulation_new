import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useRef, type RefObject } from "react";
import type {
  RefinementChainStatus,
  RefinementSubmissionPreview,
  RefinementSubmissionResult,
} from "../../api/clients/refinement";
import { RefinementReceipt } from "./RefinementStage";
const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
export type ChainUiState =
  | "idle"
  | "previewing"
  | "review"
  | "submitting"
  | "submitted"
  | "blocked"
  | "error";
export function RefinementFlow(props: {
  visible: boolean;
  status: RefinementChainStatus | null;
  check: "idle" | "checking" | "ready" | "error";
  state: ChainUiState;
  preview: RefinementSubmissionPreview | null;
  result: RefinementSubmissionResult | null;
  error: string;
  onRefresh: () => void;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  const button = useRef<HTMLButtonElement>(null),
    heading = useRef<HTMLHeadingElement>(null),
    panel = useRef<HTMLDivElement>(null),
    previous = useRef(props.state);
  useEffect(() => {
    if (props.state === "review") heading.current?.focus();
    else if (["submitted", "blocked", "error"].includes(props.state))
      panel.current?.focus();
    else if (props.state === "idle" && previous.current === "review")
      button.current?.focus();
    previous.current = props.state;
  }, [props.state]);
  if (!props.visible) return null;
  return (
    <>
      {
        <section
          className="section-block"
          aria-labelledby="chain-status-heading"
        >
          <div className="section-heading">
            <h2 id="chain-status-heading">Refinement chain on Zeus</h2>
            <p>
              Load the durable remote receipt before reviewing or recovering
              this four-round submission.
            </p>
          </div>
          <div className="remote-status-toolbar">
            <div>
              <strong>Zeus is the chain source of truth</strong>
              <p>
                {props.status ? (
                  <>
                    Last checked{" "}
                    <time dateTime={props.status.queried_at}>
                      {timestamp(props.status.queried_at)}
                    </time>
                    .
                  </>
                ) : (
                  "No current chain receipt is loaded."
                )}
              </p>
            </div>
            <button
              className="secondary-button"
              type="button"
              disabled={props.check === "checking"}
              onClick={props.onRefresh}
            >
              {props.check === "checking" ? (
                <>
                  <LoaderCircle aria-hidden="true" /> Checking…
                </>
              ) : (
                <>
                  <RefreshCw aria-hidden="true" />{" "}
                  {props.status ? "Refresh chain status" : "Check chain status"}
                </>
              )}
            </button>
          </div>
          <div className="sr-only" aria-live="polite">
            {props.check === "checking"
              ? "Checking Refinement chain status."
              : props.status
                ? `Refinement chain ${words(props.status.chain.status)}.`
                : ""}
          </div>
          {props.status && (
            <div
              className={`remote-status-card remote-status-card--${props.status.chain.status}`}
            >
              <div className="remote-status-title">
                <Clock3 aria-hidden="true" />
                <div>
                  <h3 tabIndex={-1}>
                    {props.status.chain.status === "not_submitted"
                      ? "Refinement is ready for submission review"
                      : props.status.chain.status === "submitted"
                        ? "Refinement chain submitted"
                        : props.status.chain.status === "submitting"
                          ? "Submission acknowledgements in progress"
                          : "Refinement chain needs manual verification"}
                  </h3>
                  <p>
                    Dependency policy: <code>afterok</code> · local record not
                    synchronized
                  </p>
                </div>
              </div>
              <RefinementReceipt status={props.status} />
              {["partial", "outcome_unknown"].includes(
                props.status.chain.status,
              ) && (
                <div className="submission-attention">
                  <strong>Automatic retry is blocked</strong>
                  <p>
                    Confirmed job IDs remain real and are not rolled back.
                    Inspect Zeus before taking any further action.
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
          {props.error && (
            <div
              ref={panel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {props.state === "blocked"
                    ? "Refinement chain needs manual verification"
                    : "Chain status is unavailable"}
                </strong>
                <p>{props.error}</p>
                {props.state === "blocked" ? (
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={props.onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                ) : (
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={props.onReset}
                  >
                    Review again
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      }
      {props.status?.chain.status === "not_submitted" && (
        <section
          className="section-block"
          aria-labelledby="chain-submit-heading"
        >
          <div className="section-heading">
            <h2 id="chain-submit-heading">Submit the Refinement chain</h2>
            <p>
              Review all four PBS arrays and their dependencies before any real
              work is sent to Zeus.
            </p>
          </div>
          {props.state === "idle" && (
            <div className="prepare-card">
              <div>
                <strong>
                  Fresh Zeus receipt confirms no rounds are submitted
                </strong>
                <p>
                  Only this guarded review can submit the chain. The legacy
                  shell script is not offered as an action.
                </p>
              </div>
              <button
                ref={button}
                className="primary-button"
                type="button"
                onClick={props.onPreview}
              >
                Review Refinement submission
              </button>
            </div>
          )}
          {props.state === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing four Refinement rounds</strong>
                <p>No job is being submitted.</p>
              </div>
            </div>
          )}
          {props.preview && ["review", "submitting"].includes(props.state) && (
            <div
              className="transfer-review"
              aria-busy={props.state === "submitting"}
            >
              <div className="section-heading">
                <p className="eyebrow">Final review</p>
                <h3 ref={heading} tabIndex={-1}>
                  Submit four-round Refinement chain
                </h3>
                <p>
                  Each array is submitted only after the preceding
                  acknowledgement is clear. Later rounds remain held by{" "}
                  <code>afterok</code> until the previous round succeeds.
                </p>
              </div>
              <ol className="chain-review" aria-label="Four Refinement rounds">
                {props.preview.chain.rounds.map((round, index) => (
                  <li key={round.round}>
                    <div className="round-number">{round.round}</div>
                    <div>
                      <h4>
                        Round {round.round} · cumulative target{" "}
                        {round.cumulative_target}
                      </h4>
                      <code>{round.file}</code>
                      <p>
                        {round.task_count} array tasks · throttle{" "}
                        {round.array_throttle} · {round.cores_per_task} CPU
                        cores and{" "}
                        {Math.round(round.memory_per_task_bytes / 1024 ** 3)} GB
                        per task · {round.walltime_seconds / 3600} h limit
                      </p>
                      <p>
                        {index === 0
                          ? "Starts when scheduled."
                          : `Submitted with afterok dependency on round ${round.depends_on}.`}
                      </p>
                    </div>
                    {index < 3 && (
                      <span className="dependency-arrow" aria-hidden="true">
                        ↓
                      </span>
                    )}
                  </li>
                ))}
              </ol>
              <ul className="effect-list">
                <li>
                  <CheckCircle2 aria-hidden="true" /> Performs exactly four{" "}
                  <code>qsub</code> calls if every acknowledgement is clear.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Starts the Refinement
                  simulations through PBS; no direct simulation command is run.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Does not submit
                  Confirmation or any later stage.
                </li>
                <li>
                  <CheckCircle2 aria-hidden="true" /> Does not modify campaign
                  files.
                </li>
              </ul>
              <div className="submission-attention">
                <strong>Four real Zeus submissions</strong>
                <p>
                  If any acknowledgement is missing or ambiguous, submission
                  stops immediately. Confirmed earlier jobs remain real; there
                  is no rollback and automatic retry is blocked.
                </p>
              </div>
              <div className="form-actions">
                <button
                  className="text-button"
                  type="button"
                  disabled={props.state === "submitting"}
                  onClick={props.onReset}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={props.state === "submitting"}
                  onClick={props.onConfirm}
                >
                  {props.state === "submitting" ? (
                    <>
                      <LoaderCircle aria-hidden="true" /> Submitting chain…
                    </>
                  ) : (
                    "Submit four Refinement rounds"
                  )}
                </button>
              </div>
              {props.state === "submitting" && (
                <div
                  className="submission-progress"
                  role="status"
                  aria-live="polite"
                >
                  <strong>Waiting for Zeus acknowledgements</strong>
                  <p>
                    {props.status?.chain.rounds.filter(
                      (round) => round.state === "submitted",
                    ).length ?? 0}{" "}
                    of 4 rounds have confirmed job IDs. Do not retry or close
                    this page while the result is resolving.
                  </p>
                </div>
              )}
            </div>
          )}
        </section>
      )}
      {props.state === "submitted" &&
        (props.result || props.status?.chain.status === "submitted") && (
          <section
            className="section-block"
            aria-labelledby="chain-success-heading"
          >
            <div
              ref={panel}
              className="connection-panel connection-panel--connected"
              role="status"
              tabIndex={-1}
            >
              <CheckCircle2 aria-hidden="true" />
              <div>
                <strong id="chain-success-heading">
                  Refinement chain submitted
                </strong>
                <p>
                  All four Zeus acknowledgements were recorded. Later rounds
                  wait for the previous round to succeed.
                </p>
                <ol className="job-id-list">
                  {(
                    props.result?.chain.rounds ?? props.status!.chain.rounds
                  ).map((round) => (
                    <li key={round.round}>
                      Round {round.round}: <code>{round.job_id}</code>
                      {round.depends_on_job_id && (
                        <>
                          {" "}
                          · afterok <code>{round.depends_on_job_id}</code>
                        </>
                      )}
                    </li>
                  ))}
                </ol>
                <p>
                  No later campaign stage was submitted. Zeus runs
                  independently; no action is needed and it is safe to close
                  this application.
                </p>
                <button
                  className="secondary-button compact-action"
                  type="button"
                  onClick={props.onViewJobs}
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

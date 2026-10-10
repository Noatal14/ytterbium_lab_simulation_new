import { CheckCircle2, LoaderCircle } from "lucide-react";
import type { RefObject } from "react";
import type {
  RefinementChainStatus,
  RefinementSubmissionPreview,
  RefinementSubmissionResult,
} from "../../../api/clients/refinement";
import type { ChainUiState } from "../controllers/useRefinementController";

export function RefinementSubmissionView({
  status,
  state,
  preview,
  result,
  button,
  heading,
  panel,
  onPreview,
  onConfirm,
  onReset,
  onViewJobs,
}: {
  status: RefinementChainStatus | null;
  state: ChainUiState;
  preview: RefinementSubmissionPreview | null;
  result: RefinementSubmissionResult | null;
  button: RefObject<HTMLButtonElement>;
  heading: RefObject<HTMLHeadingElement>;
  panel: RefObject<HTMLDivElement>;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  return (
    <>
      {status?.chain.status === "not_submitted" && (
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
          {state === "idle" && (
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
                onClick={onPreview}
              >
                Review Refinement submission
              </button>
            </div>
          )}
          {state === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing four Refinement rounds</strong>
                <p>No job is being submitted.</p>
              </div>
            </div>
          )}
          {preview && ["review", "submitting"].includes(state) && (
            <div
              className="transfer-review"
              aria-busy={state === "submitting"}
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
                {preview.chain.rounds.map((round, index) => (
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
                  disabled={state === "submitting"}
                  onClick={onReset}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={state === "submitting"}
                  onClick={onConfirm}
                >
                  {state === "submitting" ? (
                    <>
                      <LoaderCircle aria-hidden="true" /> Submitting chain…
                    </>
                  ) : (
                    "Submit four Refinement rounds"
                  )}
                </button>
              </div>
              {state === "submitting" && (
                <div
                  className="submission-progress"
                  role="status"
                  aria-live="polite"
                >
                  <strong>Waiting for Zeus acknowledgements</strong>
                  <p>
                    {status?.chain.rounds.filter(
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
      {state === "submitted" &&
        (result || status?.chain.status === "submitted") && (
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
                    result?.chain.rounds ?? status!.chain.rounds
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

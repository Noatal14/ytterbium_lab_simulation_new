import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import type { RefObject } from "react";
import type { RefinementLifecycle } from "../../../api/clients/refinement";
import { StatusSnapshot } from "../../shared/StatusSnapshot";
import type { ConfirmationLifecycleCheck } from "../controllers/useConfirmationController";

const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export function ConfirmationLifecycleSection({
  lifecycle,
  lifecycleCheck,
  error,
  lifecycleHeading,
  panel,
  onRefresh,
  onViewJobs,
}: {
  lifecycle: RefinementLifecycle | null;
  lifecycleCheck: ConfirmationLifecycleCheck;
  error: string;
  lifecycleHeading: RefObject<HTMLHeadingElement>;
  panel: RefObject<HTMLDivElement>;
  onRefresh: () => void;
  onViewJobs: () => void;
}) {
  return (
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
        checking={lifecycleCheck === "checking"}
        onRefresh={onRefresh}
        refreshLabel={
          lifecycle ? "Refresh Refinement status" : "Check Refinement status"
        }
        liveText={
          lifecycleCheck === "checking"
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
                onClick={onViewJobs}
              >
                View Zeus jobs
              </button>
            </div>
          )}
        </div>
      )}
      {lifecycleCheck === "error" && error && (
        <div
          ref={panel}
          className="state-panel state-panel--error"
          role="alert"
          tabIndex={-1}
        >
          <AlertTriangle aria-hidden="true" />
          <div>
            <strong>Refinement status is unavailable</strong>
            <p>{error}</p>
            <p>No stale snapshot is used as evidence.</p>
          </div>
        </div>
      )}
    </section>
  );
}

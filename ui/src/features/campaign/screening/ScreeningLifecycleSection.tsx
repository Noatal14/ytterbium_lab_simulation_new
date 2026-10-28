import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import type { RefObject } from "react";
import type { ScreeningLifecycle } from "../../../api/clients/screening";
import type { ScreeningCheckState as CheckState } from "../controllers/useScreeningController";
import { ScreeningFacts } from "../ScreeningStage";

const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export function ScreeningLifecycleSection({
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  statusHeading,
  statusErrorPanel,
  onRefreshLifecycle,
  onViewJobs,
}: {
  lifecycle: ScreeningLifecycle | null;
  lifecycleCheck: CheckState;
  lifecycleError: string;
  statusHeading: RefObject<HTMLHeadingElement>;
  statusErrorPanel: RefObject<HTMLDivElement>;
  onRefreshLifecycle: () => void;
  onViewJobs: () => void;
}) {
  const screenLifecycle = lifecycle?.lifecycle;
  return (
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
      {!lifecycle && lifecycleCheck === "ready" && !lifecycleError && (
        <div className="remote-status-card">
          <h3 ref={statusHeading} tabIndex={-1}>Screening has not been submitted</h3>
          <p>No Screening submission is recorded. Review the prepared job before submitting it.</p>
        </div>
      )}
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
  );
}

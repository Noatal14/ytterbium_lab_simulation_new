import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import type { RefObject } from "react";
import type { SmokeLifecycle } from "../../../api/clients/smoke";
import type { SmokeCheckState } from "../controllers/useSmokeController";
import { SmokePointsTable } from "../SmokeStage";

const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export function SmokeLifecycleSection({
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  lifecycleHeading,
  lifecycleErrorPanel,
  onRefreshLifecycle,
  onViewJobs,
}: {
  lifecycle: SmokeLifecycle | null;
  lifecycleCheck: SmokeCheckState;
  lifecycleError: string;
  lifecycleHeading: RefObject<HTMLHeadingElement>;
  lifecycleErrorPanel: RefObject<HTMLDivElement>;
  onRefreshLifecycle: () => void;
  onViewJobs: () => void;
}) {
  const remoteLifecycle = lifecycle?.lifecycle;
  return (
    <section className="section-block" aria-labelledby="remote-smoke-heading">
      <div className="section-heading">
        <h2 id="remote-smoke-heading">Smoke check on Zeus</h2>
        <p>
          Request a fresh, read-only check of the scheduler and validated
          smoke artifacts.
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
  );
}

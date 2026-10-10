import { AlertTriangle, Clock3, LoaderCircle, RefreshCw } from "lucide-react";
import type { RefObject } from "react";
import type { RefinementChainStatus } from "../../../api/clients/refinement";
import { RefinementReceipt } from "../RefinementStage";
import type {
  ChainLifecycleCheck,
  ChainUiState,
} from "../controllers/useRefinementController";

const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const timestamp = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export function RefinementStatusSection({
  status,
  check,
  state,
  error,
  panel,
  onRefresh,
  onReset,
  onViewJobs,
}: {
  status: RefinementChainStatus | null;
  check: ChainLifecycleCheck;
  state: ChainUiState;
  error: string;
  panel: RefObject<HTMLDivElement>;
  onRefresh: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
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
                {status ? (
                  <>
                    Last checked{" "}
                    <time dateTime={status.queried_at}>
                      {timestamp(status.queried_at)}
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
              disabled={check === "checking"}
              onClick={onRefresh}
            >
              {check === "checking" ? (
                <>
                  <LoaderCircle aria-hidden="true" /> Checking…
                </>
              ) : (
                <>
                  <RefreshCw aria-hidden="true" />{" "}
                  {status ? "Refresh chain status" : "Check chain status"}
                </>
              )}
            </button>
          </div>
          <div className="sr-only" aria-live="polite">
            {check === "checking"
              ? "Checking Refinement chain status."
              : status
                ? `Refinement chain ${words(status.chain.status)}.`
                : ""}
          </div>
          {status && (
            <div
              className={`remote-status-card remote-status-card--${status.chain.status}`}
            >
              <div className="remote-status-title">
                <Clock3 aria-hidden="true" />
                <div>
                  <h3 tabIndex={-1}>
                    {status.chain.status === "not_submitted"
                      ? "Refinement is ready for submission review"
                      : status.chain.status === "submitted"
                        ? "Refinement chain submitted"
                        : status.chain.status === "submitting"
                          ? "Submission acknowledgements in progress"
                          : "Refinement chain needs manual verification"}
                  </h3>
                  <p>
                    Dependency policy: <code>afterok</code> · local record not
                    synchronized
                  </p>
                </div>
              </div>
              <RefinementReceipt status={status} />
              {["partial", "outcome_unknown"].includes(
                status.chain.status,
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
                    onClick={onViewJobs}
                  >
                    View Zeus jobs
                  </button>
                </div>
              )}
            </div>
          )}
          {error && (
            <div
              ref={panel}
              className="state-panel state-panel--error"
              role="alert"
              tabIndex={-1}
            >
              <AlertTriangle aria-hidden="true" />
              <div>
                <strong>
                  {state === "blocked"
                    ? "Refinement chain needs manual verification"
                    : "Chain status is unavailable"}
                </strong>
                <p>{error}</p>
                {state === "blocked" ? (
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
                    onClick={onReset}
                  >
                    Review again
                  </button>
                )}
              </div>
            </div>
          )}
        </section>
      }
    </>
  );
}

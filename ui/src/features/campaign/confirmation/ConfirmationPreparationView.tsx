import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import type { RefObject } from "react";
import type {
  ConfirmationPreview,
  ConfirmationResult,
  RefinementLifecycle,
} from "../../../api/clients/refinement";
import { CandidateTable } from "../../shared/CandidateTable";
import { JobResources } from "../../shared/JobResources";
import { ManualVerification } from "../../shared/ActionError";
import { ReviewEffects } from "../../shared/ReviewEffects";
import type {
  ConfirmationLifecycleCheck,
  ConfirmationUiState,
} from "../controllers/useConfirmationController";

export function ConfirmationPreparationView({
  lifecycle,
  state,
  preview,
  result,
  error,
  lifecycleCheck,
  heading,
  button,
  panel,
  onPreview,
  onConfirm,
  onReset,
  onViewJobs,
}: {
  lifecycle: RefinementLifecycle | null;
  state: ConfirmationUiState;
  preview: ConfirmationPreview | null;
  result: ConfirmationResult | null;
  error: string;
  lifecycleCheck: ConfirmationLifecycleCheck;
  heading: RefObject<HTMLHeadingElement>;
  button: RefObject<HTMLButtonElement>;
  panel: RefObject<HTMLDivElement>;
  onPreview: () => void;
  onConfirm: () => void;
  onReset: () => void;
  onViewJobs: () => void;
}) {
  return (
    <>
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
          {state === "idle" && (
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
                onClick={onPreview}
              >
                Review Confirmation preparation
              </button>
            </div>
          )}
          {state === "previewing" && (
            <div className="state-panel" role="status" aria-busy="true">
              <LoaderCircle aria-hidden="true" />
              <div>
                <strong>Reviewing Confirmation preparation</strong>
                <p>No files are being changed and no job is being submitted.</p>
              </div>
            </div>
          )}
          {preview && ["review", "preparing"].includes(state) && (
            <div
              className="transfer-review"
              aria-busy={state === "preparing"}
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
                    {preview.refinement.completed_trials} of{" "}
                    {preview.refinement.expected_trials}
                  </dd>
                </div>
                <div>
                  <dt>Selected candidates</dt>
                  <dd>
                    {preview.refinement.candidates.length} · five per
                    fixed s₀
                  </dd>
                </div>
                <div>
                  <dt>Refinement jobs</dt>
                  <dd>
                    {preview.refinement.round_job_ids.map((id) => (
                      <code className="stacked-code" key={id}>
                        {id}
                      </code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>Files created</dt>
                  <dd>
                    {preview.artifacts.create.map((path) => (
                      <code className="stacked-code" key={path}>
                        {path}
                      </code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>File updated</dt>
                  <dd>
                    <code>{preview.artifacts.update[0]}</code>
                  </dd>
                </div>
                <div>
                  <dt>Prepared job</dt>
                  <dd>
                    <code>{preview.job.file}</code> ·{" "}
                    {preview.job.task_count} tasks · throttle{" "}
                    {preview.job.array_throttle}
                  </dd>
                </div>
                <div>
                  <dt>Resources</dt>
                  <dd>
                    <JobResources job={preview.job} />
                  </dd>
                </div>
              </dl>
              <CandidateTable
                candidates={preview.refinement.candidates}
                caption="Selected candidates from Refinement"
                estimateLabel="Refinement estimate"
              />
              <ReviewEffects
                effects={[
                  <>Prepares only Confirmation files.</>,
                  <>Does not submit a Zeus job.</>,
                  <>Does not start a simulation.</>,
                  <>
                    Stops if conflicting stage artifacts exist; otherwise
                    advances the campaign record only after all stage files are
                    safely prepared.
                  </>,
                ]}
              />
              <div className="form-actions">
                <button
                  className="text-button"
                  type="button"
                  disabled={state === "preparing"}
                  onClick={onReset}
                >
                  Back
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={state === "preparing"}
                  onClick={onConfirm}
                >
                  {state === "preparing" ? (
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
          {error &&
            state !== "terminal" &&
            lifecycleCheck !== "error" && (
              <div
                ref={panel}
                className="state-panel state-panel--error"
                role="alert"
                tabIndex={-1}
              >
                <AlertTriangle aria-hidden="true" />
                <div>
                  <strong>Confirmation preparation could not be verified</strong>
                  <p>{error}</p>
                  <button
                    className="secondary-button compact-action"
                    type="button"
                    onClick={onReset}
                  >
                    Review again
                  </button>
                </div>
              </div>
            )}
        </section>
      )}
      {state === "terminal" && error && (
        <section
          className="section-block"
          aria-labelledby="confirmation-terminal-heading"
        >
          <ManualVerification
            title="Confirmation state needs manual verification"
            message={`${error} The reviewed preview is no longer usable. Automatic retry is blocked even if a fresh status check is unavailable.`}
            onViewJobs={onViewJobs}
            panelRef={panel}
          />
        </section>
      )}
      {state === "success" && result && (
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
                {result.artifacts.created} files created and{" "}
                {result.artifacts.updated} campaign record updated.
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

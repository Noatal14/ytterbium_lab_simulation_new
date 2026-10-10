import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import type { RefObject } from "react";
import type {
  ScreeningPreview,
  ScreeningResult,
  SmokeLifecycle,
} from "../../../api/clients/smoke";
import type { ScreeningPreparationState } from "../controllers/useSmokeController";

export function ScreeningPreparationSection({
  lifecycle,
  screeningState,
  screeningPreview,
  screeningResult,
  screeningError,
  screeningButton,
  screeningHeading,
  screeningSuccess,
  screeningErrorPanel,
  onPreviewScreening,
  onConfirmScreening,
  onResetScreening,
  onViewJobs,
}: {
  lifecycle: SmokeLifecycle | null;
  screeningState: ScreeningPreparationState;
  screeningPreview: ScreeningPreview | null;
  screeningResult: ScreeningResult | null;
  screeningError: string;
  screeningButton: RefObject<HTMLButtonElement>;
  screeningHeading: RefObject<HTMLHeadingElement>;
  screeningSuccess: RefObject<HTMLDivElement>;
  screeningErrorPanel: RefObject<HTMLDivElement>;
  onPreviewScreening: () => void;
  onConfirmScreening: () => void;
  onResetScreening: () => void;
  onViewJobs: () => void;
}) {
  const remoteLifecycle = lifecycle?.lifecycle;
  return (
    <>
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

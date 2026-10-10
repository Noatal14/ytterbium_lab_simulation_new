import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import type { RefObject } from "react";
import type {
  RefinementPreview,
  RefinementResult,
  ScreeningLifecycle,
} from "../../../api/clients/screening";
import type { RefinementPreparationState as PrepareState } from "../controllers/useScreeningController";

export function RefinementPreparationSection({
  lifecycle,
  prepareState,
  preparePreview,
  prepareResult,
  prepareError,
  prepareButton,
  prepareHeading,
  preparePanel,
  onPreviewPrepare,
  onConfirmPrepare,
  onResetPrepare,
  onViewJobs,
}: {
  lifecycle: ScreeningLifecycle | null;
  prepareState: PrepareState;
  preparePreview: RefinementPreview | null;
  prepareResult: RefinementResult | null;
  prepareError: string;
  prepareButton: RefObject<HTMLButtonElement>;
  prepareHeading: RefObject<HTMLHeadingElement>;
  preparePanel: RefObject<HTMLDivElement>;
  onPreviewPrepare: () => void;
  onConfirmPrepare: () => void;
  onResetPrepare: () => void;
  onViewJobs: () => void;
}) {
  const screenLifecycle = lifecycle?.lifecycle;
  return (
    <>
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

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import type { useMot3DDiscoveryController } from "./controllers/useMot3DDiscoveryController";

export function Mot3DDiscoveryStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DDiscoveryController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (
      flow.state === "review" ||
      flow.state === "submitted" ||
      flow.state === "terminal" ||
      flow.error
    )
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.submission.status;
  const needsAttention =
    lifecycle === "held" ||
    lifecycle === "completed_failed" ||
    lifecycle === "status_unknown" ||
    lifecycle === "outcome_unknown";
  const tracked =
    flow.state === "submitted" ||
    lifecycle === "submitted" ||
    lifecycle === "queued" ||
    lifecycle === "running" ||
    lifecycle === "completed_success";
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-discovery-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Current stage: Discovery</p>
        <h2 id="mot3d-discovery-heading">Compare broad 3D-MOT candidates</h2>
        <p>
          Discovery runs the frozen angled-donut and single-pass search chains
          using the approved 3D timestep and the sealed 2D-MOT handoff. It
          narrows the search; it is not a final design or performance estimate.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>Connect to Zeus before reviewing Discovery</strong>
              <p>
                The application will inspect the exact prepared chain. It will
                not submit anything during connection or status checks.
              </p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && flow.state === "idle" && !tracked && !needsAttention && (
          <div className="prepare-card">
            <div>
              <strong>Discovery is prepared, but not submitted</strong>
              <p>
                Review the exact five-array dependency chain before any Zeus job
                starts.
              </p>
            </div>
            <div className="form-actions">
              <button
                className="secondary-button"
                onClick={() => void flow.refresh()}
              >
                Check Zeus status
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review Discovery jobs
              </button>
            </div>
          </div>
        )}
        {flow.state === "checking" && (
          <Busy title="Checking the frozen Discovery chain" />
        )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3>Submit the Discovery chain</h3>
            <p>
              Exactly five array jobs will be submitted: two angled-donut rounds
              and three single-pass rounds, each with three tasks. Dependencies
              apply only within each family.
            </p>
            <dl className="transfer-facts">
              <div><dt>Reservation per task</dt><dd>{flow.preview.resources.array.ncpus_per_task} CPU cores · {flow.preview.resources.array.memory_gb_per_task} GB · {flow.preview.resources.array.walltime}</dd></div>
              {flow.preview.resources.array.vnode && <div><dt>Test compute node</dt><dd>{flow.preview.resources.array.vnode}</dd></div>}
              <div><dt>Search workload</dt><dd>{flow.preview.science.total_trials} trials · {flow.preview.science.input_ensembles} discovery ensembles · {flow.preview.science.particles_per_ensemble} atoms per ensemble</dd></div>
              <div><dt>Particles per trial</dt><dd>{flow.preview.science.total_particles_per_trial} atoms · {flow.preview.science.npools} worker pools</dd></div>
              <div><dt>Physical protocol</dt><dd>{flow.preview.science.dt_s * 1e6} µs · {flow.preview.science.t_max_s * 1000} ms · {flow.preview.science.solver}</dd></div>

              <div>
                <dt>Angled donut</dt>
                <dd>2 arrays × 3 tasks · final trial targets per worker: {flow.preview.science.final_trial_targets.angled_donut.join(" / ")}</dd>
              </div>
              <div>
                <dt>Single pass</dt>
                <dd>3 arrays × 3 tasks · final trial targets per worker: {flow.preview.science.final_trial_targets.single_pass.join(" / ")}</dd>
              </div>
              <div>
                <dt>Smoke jobs</dt>
                <dd>Not submitted</dd>
              </div>
              <div>
                <dt>Later 3D stages</dt>
                <dd>Not submitted</dd>
              </div>
              <div>
                <dt>Remote branch</dt>
                <dd>{flow.preview.remote.branch}</dd>
              </div>
            </dl>
            <p className="review-note">
              A durable submission receipt will be recorded. The prepared
              campaign files are not modified.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Submit Discovery to Zeus
              </button>
            </div>
          </div>
        )}
        {flow.state === "submitting" && (
          <Busy title="Submitting the reviewed Discovery chain" />
        )}
        {tracked && !needsAttention && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>
              {lifecycle === "completed_success"
                ? "Discovery jobs finished on Zeus"
                : "Discovery is tracked on Zeus"}
            </strong>
            <p>
              {lifecycle === "completed_success"
                ? "The scheduler completed all five arrays. This is not yet scientific validation; verify the Discovery evidence below before the next stage can be prepared."
                : "Zeus continues independently. No action is needed while the arrays are queued or running."}
            </p>
            <div className="form-actions">
              <button
                className="secondary-button"
                onClick={() => void flow.refresh()}
              >
                Refresh status
              </button>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {needsAttention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Manual verification required</strong>
              <p>
                Zeus did not report a safely actionable Discovery state. Do
                not submit the chain again. Inspect the existing jobs and
                resolve their status before continuing.
              </p>
              <div className="form-actions">
                <button
                  className="secondary-button"
                  onClick={() => void flow.refresh()}
                >
                  Check status again
                </button>
                <button className="text-button" onClick={onViewJobs}>
                  Open Zeus jobs
                </button>
              </div>
            </div>
          </div>
        )}
        {flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Manual verification required</strong>
              <p>{flow.error}</p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {connected && !flow.status && flow.state === "idle" && (
          <p className="helper-text">
            If the Zeus connection is unavailable,{" "}
            <button className="inline-button" onClick={onConnectZeus}>
              configure Zeus access
            </button>
            .
          </p>
        )}
      </div>
    </section>
  );
}

function Busy({ title }: { title: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>No additional action is needed while this check completes.</p>
      </div>
    </div>
  );
}

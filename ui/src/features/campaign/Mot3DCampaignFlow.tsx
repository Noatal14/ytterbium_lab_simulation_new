import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import type { useMot3DDiscoveryController } from "./controllers/useMot3DDiscoveryController";
import type { useMot3DDiscoveryTransitionController } from "./controllers/useMot3DDiscoveryTransitionController";
import type { useMot3DPreliminaryCheckController } from "./controllers/useMot3DPreliminaryCheckController";
import type { useMot3DPreliminaryTransitionController } from "./controllers/useMot3DPreliminaryTransitionController";
import type { useMot3DRefinementSubmissionController } from "./controllers/useMot3DRefinementSubmissionController";
import type { useMot3DRefinementTransitionController } from "./controllers/useMot3DRefinementTransitionController";
import { Mot3DDiscoveryStage } from "./Mot3DDiscoveryStage";

export function Mot3DCampaignFlow({
  stage,
  connected,
  discovery,
  transition,
  preliminary,
  preliminaryTransition,
  refinement,
  refinementTransition,
  onConnectZeus,
  onViewJobs,
}: {
  stage: string;
  connected: boolean;
  discovery: ReturnType<typeof useMot3DDiscoveryController>;
  transition: ReturnType<typeof useMot3DDiscoveryTransitionController>;
  preliminary: ReturnType<typeof useMot3DPreliminaryCheckController>;
  preliminaryTransition?: ReturnType<
    typeof useMot3DPreliminaryTransitionController
  >;
  refinement?: ReturnType<typeof useMot3DRefinementSubmissionController>;
  refinementTransition?: ReturnType<
    typeof useMot3DRefinementTransitionController
  >;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const transitionVisible =
    stage === "discovery" ||
    discovery.status?.submission.status === "completed_success" ||
    Boolean(
      transition.status ||
      transition.preview ||
      transition.result ||
      transition.error,
    );
  return (
    <>
      <Mot3DDiscoveryStage
        visible={stage === "discovery"}
        connected={connected}
        flow={discovery}
        onConnectZeus={onConnectZeus}
        onViewJobs={onViewJobs}
      />
      <Mot3DDiscoveryTransitionStage
        visible={transitionVisible}
        connected={connected}
        flow={transition}
        onConnectZeus={onConnectZeus}
        onViewJobs={onViewJobs}
      />
      <Mot3DPreliminaryCheckStage
        visible={
          stage === "preliminary_check" ||
          Boolean(
            preliminary.status ||
            preliminary.preview ||
            preliminary.result ||
            preliminary.error,
          )
        }
        connected={connected}
        flow={preliminary}
        onConnectZeus={onConnectZeus}
        onViewJobs={onViewJobs}
      />
      {preliminaryTransition && (
        <Mot3DPreliminaryTransitionStage
          visible={
            stage === "refinement" ||
            preliminary.status?.submission.status ===
              "completed_success_unvalidated" ||
            Boolean(
              preliminaryTransition.status ||
              preliminaryTransition.preview ||
              preliminaryTransition.result ||
              preliminaryTransition.error,
            )
          }
          connected={connected}
          flow={preliminaryTransition}
          onConnectZeus={onConnectZeus}
          onViewJobs={onViewJobs}
        />
      )}
      {refinement && (
        <Mot3DRefinementSubmissionStage
          visible={
            stage === "refinement" ||
            Boolean(
              refinement.status ||
              refinement.preview ||
              refinement.result ||
              refinement.error,
            )
          }
          connected={connected}
          flow={refinement}
          onConnectZeus={onConnectZeus}
          onViewJobs={onViewJobs}
        />
      )}
      {refinementTransition && (
        <Mot3DRefinementTransitionStage
        visible={
          stage === "refinement" ||
          stage === "closure" ||
            refinement?.status?.submission.status ===
              "completed_success_unvalidated" ||
            Boolean(
              refinementTransition.status ||
              refinementTransition.preview ||
              refinementTransition.result ||
              refinementTransition.error,
            )
          }
          connected={connected}
          flow={refinementTransition}
          onConnectZeus={onConnectZeus}
          onViewJobs={onViewJobs}
        />
      )}
    </>
  );
}

function Mot3DRefinementTransitionStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DRefinementTransitionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null),
    heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") heading.current?.focus();
    else if (
      ["ready", "prepared", "terminal"].includes(flow.state) ||
      flow.error
    )
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.refinement.status,
    invalid = flow.status?.validation.status === "scientifically_invalid",
    validUnknown =
      lifecycle === "outcome_unknown" &&
      flow.status?.validation.status === "valid",
    attention =
      flow.state === "terminal" ||
      invalid ||
      [
        "not_submitted",
        "held",
        "completed_failed",
        "status_unknown",
        "partial",
        "outcome_unknown",
      ].includes(lifecycle ?? ""),
    waiting = ["submitted", "queued", "running"].includes(lifecycle ?? ""),
    schedulerOnly =
      lifecycle === "completed_success_unvalidated" &&
      flow.status?.validation.status === "not_started",
    recovery =
      lifecycle === "closure_prepared" &&
      flow.status?.local_sync.status === "not_synchronized";
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-refinement-transition-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Refinement result verification</p>
        <h2 id="mot3d-refinement-transition-heading">
          Validate results and prepare Closure
        </h2>
        <p>
          Scheduler completion alone is not scientific validation. The complete
          Refinement result set must pass verification before Closure is
          prepared.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>Connect to Zeus to verify Refinement results</strong>
              <p>Connecting and checking status do not submit or start jobs.</p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && !flow.status && flow.state === "idle" && (
          <div className="prepare-card">
            <div>
              <strong>Verify the completed Refinement outputs</strong>
              <p>
                The scheduler has finished. Scientific validation and local
                synchronization have not happened yet.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.refresh()}
            >
              Verify Refinement results
            </button>
          </div>
        )}
        {(flow.state === "checking" || flow.state === "synchronizing") && (
          <Busy
            title={
              flow.state === "checking"
                ? "Checking Refinement evidence"
                : "Synchronizing verified results and preparing Closure"
            }
          />
        )}{" "}
        {waiting && !attention && (
          <div className="state-panel" role="status">
            <strong>Refinement is still running on Zeus</strong>
            <p>
              No action is needed. Closure remains locked until the complete
              result set passes validation.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={() => void flow.refresh()}>
                Refresh status
              </button>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {schedulerOnly && (
          <div className="prepare-card">
            <div>
              <strong>
                Jobs finished; scientific validation is still required
              </strong>
              <p>
                Review the bounded result verification before preparing Closure.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.review()}
            >
              Review verification
            </button>
          </div>
        )}
        {flow.state === "ready" &&
          flow.status?.validation.status === "valid" && (
            <div className="prepare-card">
              <div>
                <strong>
                  {recovery
                    ? "Closure is prepared on Zeus; local synchronization is incomplete"
                    : "All 200 Refinement result artifacts are scientifically valid"}
                </strong>
                <p>
                  Review the verified evidence before it is synchronized. No
                  Closure job will start.
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review synchronization
              </button>
            </div>
          )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3 ref={heading} tabIndex={-1}>
              Synchronize results and prepare Closure
            </h3>
            <p>
              This transfers only the verified registry and prepares Closure
              files. It does not submit a job or start a simulation.
            </p>
            <dl className="transfer-facts">
              <div>
                <dt>Scientific artifacts</dt>
                <dd>200 of 200</dd>
              </div>
              <div>
                <dt>Submission receipts</dt>
                <dd>1 verified receipt</dd>
              </div>
              <div>
                <dt>Closure selections</dt>
                <dd>2 files</dd>
              </div>
              <div>
                <dt>Closure job files</dt>
                <dd>4 files</dd>
              </div>
              <div>
                <dt>Jobs submitted</dt>
                <dd>None</dd>
              </div>
              <div>
                <dt>Simulations started</dt>
                <dd>None</dd>
              </div>
            </dl>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Synchronize and prepare Closure
              </button>
            </div>
          </div>
        )}
        {flow.state === "prepared" && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>Closure is prepared</strong>
            <p>
              All verified Refinement evidence is synchronized. No Closure job
              has been submitted or started.
            </p>
          </div>
        )}
        {attention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>
                {invalid
                  ? "Refinement evidence is scientifically invalid"
                  : "Manual verification required"}
              </strong>
              <p>
                {invalid
                  ? "The expected result set failed scientific validation. Closure remains blocked."
                  : validUnknown
                    ? "All 200 artifacts passed validation, but the transition outcome is unknown. Do not retry; inspect Zeus manually."
                    : "The scheduler or transition outcome is not safely actionable. Do not retry; inspect Zeus manually."}
              </p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Closure preparation stopped safely</strong>
              <p>{flow.error}</p>
              <p>
                {flow.errorPhase === "confirm"
                  ? "The outcome may be uncertain. Do not retry; inspect Zeus first."
                  : "No transition was confirmed. Check status before reviewing again."}
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Mot3DRefinementSubmissionStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DRefinementSubmissionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") reviewHeading.current?.focus();
    else if (["tracked", "terminal"].includes(flow.state) || flow.error)
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.submission.status;
  const attention =
    flow.state === "terminal" ||
    [
      "partial",
      "held",
      "completed_failed",
      "status_unknown",
      "outcome_unknown",
    ].includes(lifecycle ?? "");
  const waiting =
    ["submitted", "queued", "running"].includes(lifecycle ?? "") ||
    (flow.state === "tracked" && Boolean(flow.result) && !flow.status);
  const finished = lifecycle === "completed_success_unvalidated";
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-refinement-submit-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Current stage: Refinement</p>
        <h2 id="mot3d-refinement-submit-heading">
          Run the focused candidate comparison
        </h2>
        <p>
          Refinement evaluates the narrowed candidate sets. It supports later
          selection and is not final scientific validation.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>Connect to Zeus before reviewing Refinement</strong>
              <p>Connection and status checks do not submit or start jobs.</p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && flow.state === "idle" && !flow.status && (
          <div className="prepare-card">
            <div>
              <strong>Check Zeus before reviewing Refinement</strong>
              <p>
                This read-only check verifies that no Refinement submission
                already exists.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.refresh()}
            >
              Check Zeus status
            </button>
          </div>
        )}
        {connected &&
          flow.state === "idle" &&
          flow.status?.next_action === "review_submission" && (
            <div className="prepare-card">
              <div>
                <strong>Refinement is prepared, but not submitted</strong>
                <p>
                  Review the exact four-job plan before any simulation starts.
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review Refinement jobs
              </button>
            </div>
          )}
        {(flow.state === "checking" || flow.state === "submitting") && (
          <Busy
            title={
              flow.state === "checking"
                ? "Checking the Refinement submission"
                : "Submitting the reviewed Refinement jobs"
            }
          />
        )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3 ref={reviewHeading} tabIndex={-1}>
              Submit Refinement
            </h3>
            <p>
              Each family has one three-task simulation array followed by one
              merge job. The two families remain independent.
            </p>
            <dl className="transfer-facts">
              <div>
                <dt>Angled donut</dt>
                <dd>3-task array + merge</dd>
              </div>
              <div>
                <dt>Single pass</dt>
                <dd>3-task array + merge</dd>
              </div>
              <div>
                <dt>Zeus submissions</dt>
                <dd>4 jobs total</dd>
              </div>
              <div>
                <dt>Input ensembles</dt>
                <dd>4 · 3,000 particles total</dd>
              </div>
              <div>
                <dt>Candidate evaluations</dt>
                <dd>16 per family · 3 recoil seeds</dd>
              </div>
              <div>
                <dt>Later stages</dt>
                <dd>Not submitted</dd>
              </div>
            </dl>
            <p className="review-note">
              Submitting starts only the reviewed Refinement simulations and
              records a durable receipt. It does not submit a later stage.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Submit Refinement to Zeus
              </button>
            </div>
          </div>
        )}
        {waiting && !attention && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>Refinement is running on Zeus</strong>
            <p>
              No action is needed while the reviewed arrays and merge jobs are
              queued or running. Zeus continues independently.
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
        {finished && !flow.error && (
          <div className="state-panel" role="status">
            <strong>Refinement jobs finished on Zeus</strong>
            <p>
              The scheduler completed all four jobs, but their scientific
              outputs have not been validated or synchronized locally. No later
              stage has started.
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
        {attention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Manual verification required</strong>
              <p>
                The submission is partial or Zeus did not report a safely
                actionable outcome. Do not submit again. Inspect the existing
                jobs before continuing.
              </p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Refinement submission stopped safely</strong>
              <p>{flow.error}</p>
              <p>
                {flow.errorPhase === "submit_unknown"
                  ? "The submission outcome may be uncertain. Do not retry; inspect Zeus first."
                  : "No submission was confirmed by this action. Check Zeus status before reviewing again."}
              </p>
              <div className="form-actions">
                <button
                  className="secondary-button"
                  onClick={() => void flow.refresh()}
                >
                  Check Zeus status
                </button>
                <button className="text-button" onClick={onViewJobs}>
                  Open Zeus jobs
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Mot3DPreliminaryTransitionStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DPreliminaryTransitionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") reviewHeading.current?.focus();
    else if (
      ["ready", "prepared", "terminal"].includes(flow.state) ||
      flow.error
    )
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.preliminary.status;
  const invalid = flow.status?.validation.status === "scientifically_invalid";
  const validUnknown =
    lifecycle === "outcome_unknown" &&
    flow.status?.validation.status === "valid";
  const attention =
    flow.state === "terminal" ||
    invalid ||
    [
      "not_submitted",
      "held",
      "completed_failed",
      "status_unknown",
      "partial",
      "outcome_unknown",
    ].includes(lifecycle ?? "");
  const waiting = ["submitted", "queued", "running"].includes(lifecycle ?? "");
  const schedulerOnly =
    lifecycle === "completed_success_unvalidated" &&
    flow.status?.validation.status === "not_started";
  const recovery =
    lifecycle === "refinement_prepared" &&
    flow.status?.local_sync.status === "not_synchronized";
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-preliminary-transition-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Preliminary-check result verification</p>
        <h2 id="mot3d-preliminary-transition-heading">
          Validate results and prepare Refinement
        </h2>
        <p>
          Scheduler completion alone is not scientific validation. The
          application verifies the complete held-out result set before preparing
          the focused Refinement stage.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>
                Connect to Zeus to verify preliminary-check results
              </strong>
              <p>Connecting and checking status do not submit or start jobs.</p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && !flow.status && flow.state === "idle" && (
          <div className="prepare-card">
            <div>
              <strong>Verify the completed preliminary-check outputs</strong>
              <p>
                The scheduler has finished. Scientific validation and local
                synchronization have not happened yet.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.refresh()}
            >
              Verify preliminary-check results
            </button>
          </div>
        )}
        {(flow.state === "checking" || flow.state === "synchronizing") && (
          <Busy
            title={
              flow.state === "checking"
                ? "Checking preliminary-check evidence"
                : "Synchronizing verified results and preparing Refinement"
            }
          />
        )}
        {waiting && !attention && (
          <div className="state-panel" role="status">
            <strong>Preliminary check is still running on Zeus</strong>
            <p>
              No action is needed. Refinement remains locked until all four jobs
              finish and the complete output set passes validation.
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
        {schedulerOnly && flow.state === "ready" && (
          <div className="prepare-card">
            <div>
              <strong>
                Jobs finished; scientific validation is still required
              </strong>
              <p>
                Review the bounded result transfer. This action validates 152
                expected result files before preparing Refinement.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.review()}
            >
              Review results and prepare Refinement
            </button>
          </div>
        )}
        {flow.state === "ready" &&
          flow.status?.validation.status === "valid" && (
            <div className="prepare-card">
              <div>
                <strong>
                  {recovery
                    ? "Refinement is prepared on Zeus; local synchronization is incomplete"
                    : "All 152 preliminary-check results are scientifically valid"}
                </strong>
                <p>
                  {recovery
                    ? "Review the verified evidence to finish synchronization. No job or simulation will start."
                    : "Review the verified files and exact local changes before Refinement is prepared."}
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review synchronization
              </button>
            </div>
          )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3 ref={reviewHeading} tabIndex={-1}>
              {recovery
                ? "Finish Refinement synchronization"
                : "Synchronize results and prepare Refinement"}
            </h3>
            <p>
              The application transfers only the allowlisted, hash-verified
              evidence, validates both geometry families, and prepares the next
              stage. It does not submit a job or start a simulation.
            </p>
            <dl className="transfer-facts">
              <div>
                <dt>Validated result files</dt>
                <dd>152 of 152</dd>
              </div>
              <div>
                <dt>Submission receipts</dt>
                <dd>1 verified receipt</dd>
              </div>
              <div>
                <dt>Files transferred</dt>
                <dd>160 bounded files</dd>
              </div>
              <div>
                <dt>Refinement selections</dt>
                <dd>2 files</dd>
              </div>
              <div>
                <dt>Refinement job files</dt>
                <dd>4 files</dd>
              </div>
              <div>
                <dt>Jobs submitted</dt>
                <dd>None</dd>
              </div>
            </dl>
            <p className="review-note">
              Existing files are never silently overwritten. An interrupted
              synchronization remains blocked until its receipt and complete
              file set are verified.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Synchronize and prepare Refinement
              </button>
            </div>
          </div>
        )}
        {flow.state === "prepared" && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>Refinement is prepared</strong>
            <p>
              The preliminary-check evidence is scientifically validated,
              synchronized, and receipt-verified. No Refinement job has been
              submitted or started.
            </p>
          </div>
        )}
        {attention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>
                {invalid
                  ? "Preliminary-check evidence is scientifically invalid"
                  : "Manual verification required"}
              </strong>
              <p>
                {invalid
                  ? "The expected result set failed scientific validation. Refinement remains blocked and there is no override in the application."
                  : validUnknown
                    ? "All 152 scientific result artifacts passed validation, but the transition outcome is unknown. Do not retry; inspect Zeus and the campaign state manually."
                    : "The scheduler or transition outcome is not safely actionable. Do not retry or advance; inspect the existing Zeus jobs and outputs."}
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
              <strong>Refinement preparation stopped safely</strong>
              <p>{flow.error}</p>
              <p>
                {flow.errorPhase === "confirm"
                  ? "The synchronization outcome may be uncertain. Do not retry; inspect Zeus and the local campaign state first."
                  : "No synchronization was confirmed by this check. Refresh the verified status before reviewing again."}
              </p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Mot3DPreliminaryCheckStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DPreliminaryCheckController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") reviewHeading.current?.focus();
    else if (["tracked", "terminal"].includes(flow.state) || flow.error)
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.submission.status;
  const attention =
    flow.state === "terminal" ||
    [
      "partial",
      "held",
      "completed_failed",
      "status_unknown",
      "outcome_unknown",
    ].includes(lifecycle ?? "");
  const waiting =
    ["submitted", "queued", "running"].includes(lifecycle ?? "") ||
    (flow.state === "tracked" && Boolean(flow.result) && !flow.status);
  const schedulerFinished = lifecycle === "completed_success_unvalidated";
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-preliminary-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Current stage: Preliminary check</p>
        <h2 id="mot3d-preliminary-heading">
          Test leading candidates on held-out inputs
        </h2>
        <p>
          This stage compares the selected candidates on four independent input
          ensembles. It supports later selection; it is not final validation or
          a performance claim.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>
                Connect to Zeus before reviewing the preliminary check
              </strong>
              <p>Connection and status checks do not submit or start jobs.</p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && flow.state === "idle" && !flow.status && (
          <div className="prepare-card">
            <div>
              <strong>Check Zeus before reviewing the preliminary check</strong>
              <p>
                This read-only check verifies that no preliminary-check
                submission already exists.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.refresh()}
            >
              Check Zeus status
            </button>
          </div>
        )}
        {connected &&
          flow.state === "idle" &&
          flow.status?.next_action === "review_submission" && (
            <div className="prepare-card">
              <div>
                <strong>
                  Preliminary check is prepared, but not submitted
                </strong>
                <p>
                  Review the exact four-job plan before any simulation starts.
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review preliminary-check jobs
              </button>
            </div>
          )}
        {(flow.state === "checking" || flow.state === "submitting") && (
          <Busy
            title={
              flow.state === "checking"
                ? "Checking the preliminary-check submission"
                : "Submitting the reviewed preliminary-check jobs"
            }
          />
        )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3 ref={reviewHeading} tabIndex={-1}>
              Submit the preliminary check
            </h3>
            <p>
              Each family has one three-task simulation array followed by one
              merge job. The two families remain independent.
            </p>
            <dl className="transfer-facts">
              <div>
                <dt>Angled donut</dt>
                <dd>3-task array + merge</dd>
              </div>
              <div>
                <dt>Single pass</dt>
                <dd>3-task array + merge</dd>
              </div>
              <div>
                <dt>Zeus submissions</dt>
                <dd>4 jobs total</dd>
              </div>
              <div>
                <dt>Held-out inputs</dt>
                <dd>4 ensembles · 600 particles</dd>
              </div>
              <div>
                <dt>Candidate evaluations</dt>
                <dd>12 per family · 3 recoil seeds</dd>
              </div>
              <div>
                <dt>Later stages</dt>
                <dd>Not submitted</dd>
              </div>
            </dl>
            <p className="review-note">
              Submitting starts these simulations on Zeus and records a durable
              receipt. It does not submit refinement or any later stage.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Submit preliminary check to Zeus
              </button>
            </div>
          </div>
        )}
        {waiting && !attention && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>Preliminary check is running on Zeus</strong>
            <p>
              No action is needed while the reviewed arrays and merge jobs are
              queued or running. Zeus continues independently.
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
        {schedulerFinished && !flow.error && (
          <div className="state-panel" role="status">
            <strong>Preliminary-check jobs finished on Zeus</strong>
            <p>
              The scheduler completed the four jobs, but their scientific
              outputs have not yet been validated or synchronized locally. No
              later stage has started.
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
        {attention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Manual verification required</strong>
              <p>
                The submission is partial or Zeus did not report a safely
                actionable outcome. Do not submit again. Inspect the existing
                jobs before continuing.
              </p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
        {flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Preliminary-check submission stopped safely</strong>
              <p>{flow.error}</p>
              <p>
                {flow.errorPhase === "submit"
                  ? "The submission outcome may be uncertain. Do not retry; inspect Zeus first."
                  : "No submission was confirmed by this action. Check Zeus status before reviewing again."}
              </p>
              <div className="form-actions">
                <button
                  className="secondary-button"
                  onClick={() => void flow.refresh()}
                >
                  Check Zeus status
                </button>
                <button className="text-button" onClick={onViewJobs}>
                  Open Zeus jobs
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Mot3DDiscoveryTransitionStage({
  visible,
  connected,
  flow,
  onConnectZeus,
  onViewJobs,
}: {
  visible: boolean;
  connected: boolean;
  flow: ReturnType<typeof useMot3DDiscoveryTransitionController>;
  onConnectZeus: () => void;
  onViewJobs: () => void;
}) {
  const focus = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.state === "review") reviewHeading.current?.focus();
    else if (
      ["ready", "prepared", "terminal"].includes(flow.state) ||
      flow.error
    )
      focus.current?.focus();
  }, [flow.state, flow.error]);
  if (!visible) return null;
  const lifecycle = flow.status?.discovery.status;
  const recoveryRequired =
    lifecycle === "preliminary_check_prepared" &&
    flow.status?.local_sync.status === "not_synchronized";
  const attention =
    ["held", "completed_failed", "outputs_invalid", "status_unknown"].includes(
      lifecycle ?? "",
    ) ||
    flow.status?.validation.status === "invalid" ||
    flow.state === "terminal";
  const waiting = [
    "queued",
    "running",
    "completed_success_unvalidated",
  ].includes(lifecycle ?? "");
  return (
    <section
      className="section-block"
      aria-labelledby="mot3d-transition-heading"
    >
      <div className="section-heading">
        <p className="eyebrow">Discovery result verification</p>
        <h2 id="mot3d-transition-heading">
          Prepare the independent preliminary check
        </h2>
        <p>
          Scheduler completion is not scientific validation. The application
          first retrieves a bounded, hash-verified Discovery result set,
          validates all 950 trial records, and only then prepares the next stage
          locally.
        </p>
      </div>
      <div ref={focus} tabIndex={-1}>
        {!connected && (
          <div className="prepare-card">
            <div>
              <strong>Connect to Zeus to verify Discovery</strong>
              <p>
                Connecting and checking status do not submit or start any jobs.
              </p>
            </div>
            <button className="primary-button" onClick={onConnectZeus}>
              Connect to Zeus
            </button>
          </div>
        )}
        {connected && !flow.status && flow.state === "idle" && (
          <div className="prepare-card">
            <div>
              <strong>Verify the completed Discovery outputs</strong>
              <p>
                The scheduler has finished. Scientific validation and local
                preparation have not happened yet.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void flow.refresh()}
            >
              Verify Discovery results
            </button>
          </div>
        )}
        {(flow.state === "checking" || flow.state === "synchronizing") && (
          <Busy
            title={
              flow.state === "checking"
                ? "Checking and validating Discovery evidence"
                : "Synchronizing verified evidence and preparing the next stage"
            }
          />
        )}
        {waiting && !attention && flow.state === "idle" && (
          <div className="state-panel" role="status">
            <strong>
              {lifecycle === "completed_success_unvalidated"
                ? "Discovery finished; validation is still in progress"
                : "Discovery is still running on Zeus"}
            </strong>
            <p>
              No action is needed. Refresh status later; the next stage stays
              locked until all expected outputs pass validation.
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
        {flow.state === "ready" &&
          flow.status?.validation.status === "valid" && (
            <div className="prepare-card">
              <div>
                <strong>
                  {recoveryRequired
                    ? "Preliminary check is prepared on Zeus; local synchronization is incomplete"
                    : "All 950 Discovery trials are scientifically valid"}
                </strong>
                <p>
                  {recoveryRequired
                    ? "Review the verified remote evidence to finish the interrupted local synchronization. No new job or simulation will start."
                    : "The evidence can now be reviewed before it is synchronized and the preliminary-check files are created."}
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() => void flow.review()}
              >
                Review synchronization
              </button>
            </div>
          )}
        {flow.preview && flow.state === "review" && (
          <div className="review-panel">
            <p className="eyebrow">Explicit review</p>
            <h3 ref={reviewHeading} tabIndex={-1}>
              Synchronize verified Discovery evidence
            </h3>
            <p>
              This copies only the bounded, verified campaign evidence and
              prepares the independent preliminary check. It does not submit a
              Zeus job or start a simulation.
            </p>
            <dl className="transfer-facts">
              <div>
                <dt>Validated trial records</dt>
                <dd>950 of 950</dd>
              </div>
              <div>
                <dt>Merged evidence files</dt>
                <dd>4 verified files</dd>
              </div>
              <div>
                <dt>Candidate selections</dt>
                <dd>2 files, one per family</dd>
              </div>
              <div>
                <dt>Preliminary-check job files</dt>
                <dd>4 files</dd>
              </div>
              <div>
                <dt>Jobs submitted</dt>
                <dd>None</dd>
              </div>
              <div>
                <dt>Simulations started</dt>
                <dd>None</dd>
              </div>
            </dl>
            <p className="review-note">
              If synchronization is interrupted, the campaign remains blocked
              until its receipt and complete file set can be verified. Existing
              files are never silently overwritten.
            </p>
            <div className="form-actions">
              <button className="secondary-button" onClick={flow.reset}>
                Back
              </button>
              <button
                className="primary-button"
                onClick={() => void flow.confirm()}
              >
                Synchronize and prepare
              </button>
            </div>
          </div>
        )}
        {flow.state === "prepared" && !flow.error && (
          <div className="state-panel state-panel--success" role="status">
            <strong>Preliminary check is prepared</strong>
            <p>
              Discovery evidence is synchronized and receipt-verified. No
              preliminary-check job has been submitted or started.
            </p>
            <p>
              The next milestone will add a separate explicit review before
              those jobs can be submitted.
            </p>
          </div>
        )}
        {attention && !flow.error && (
          <div className="state-panel state-panel--error" role="alert">
            <AlertTriangle aria-hidden="true" />
            <div>
              <strong>Manual verification required</strong>
              <p>
                The Discovery outcome or scientific evidence is not safely
                actionable. Do not synchronize, advance, or submit again.
                Inspect the existing Zeus jobs and outputs.
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
              <strong>Discovery preparation stopped safely</strong>
              <p>{flow.error}</p>
              <p>
                No later job was submitted. Verify the existing evidence before
                trying another action.
              </p>
              <button className="text-button" onClick={onViewJobs}>
                Open Zeus jobs
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Busy({ title }: { title: string }) {
  return (
    <div className="state-panel" role="status" aria-live="polite">
      <LoaderCircle className="spin" aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>No additional action is needed while this check completes.</p>
      </div>
    </div>
  );
}

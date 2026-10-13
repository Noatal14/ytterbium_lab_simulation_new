import { Clipboard } from "lucide-react";
import type { Campaign } from "../../api/clients/campaign";
import type {
  RefinementChainStatus,
  RefinementLifecycle,
} from "../../api/clients/refinement";
import type { ScreeningLifecycle } from "../../api/clients/screening";
import type {
  SmokeLifecycle,
  SmokeSubmissionResult,
} from "../../api/clients/smoke";
import type { TransferUiState } from "./controllers/useTransferController";
import type { ScreeningSubmitState } from "./controllers/useScreeningController";
import type {
  SmokeSubmitState,
  SmokeTerminalCode,
} from "./controllers/useSmokeController";
import type { ConfirmationSubmissionUiState } from "./controllers/useConfirmationSubmissionController";
import type { Mot3DDiscoveryUiState } from "./controllers/useMot3DDiscoveryController";
import type { Mot3DDiscoveryLifecycle } from "../../api/clients/mot3dDiscovery";
import type { Mot3DDiscoveryTransitionLifecycle } from "../../api/clients/mot3dDiscoveryTransition";
import type { Mot3DDiscoveryTransitionUiState } from "./controllers/useMot3DDiscoveryTransitionController";
import type { PreliminaryCheckLifecycle } from "../../api/clients/mot3dPreliminaryCheck";
import type { PreliminaryCheckUiState } from "./controllers/useMot3DPreliminaryCheckController";
import type { Mot3DPreliminaryTransitionLifecycle } from "../../api/clients/mot3dPreliminaryTransition";
import type { Mot3DPreliminaryTransitionUiState } from "./controllers/useMot3DPreliminaryTransitionController";
import type { Mot3DRefinementSubmissionLifecycle } from "../../api/clients/mot3dRefinementSubmission";
import type { Mot3DRefinementSubmissionUiState } from "./controllers/useMot3DRefinementSubmissionController";
import type { Mot3DRefinementTransitionLifecycle } from "../../api/clients/mot3dRefinementTransition";
import type { Mot3DRefinementTransitionUiState } from "./controllers/useMot3DRefinementTransitionController";
import type { GuardedStagePhase } from "./shared/useGuardedStageController";

const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");

export function CampaignPriorityPanel({
  campaign,
  transferState,
  submissionState,
  submissionResult,
  submissionError,
  submissionTerminalCode,
  remoteState,
  remoteEvidenceFresh,
  screenSubmitState,
  screenState,
  chainStatus,
  refinementLifecycle,
  confirmationSubmitState = "idle",
  confirmationSubmitJobId = null,
  mot3DDiscoveryState = "idle",
  mot3DDiscoveryLifecycle = null,
  mot3DTransitionState = "idle",
  mot3DTransitionLifecycle = null,
  preliminaryCheckState = "idle",
  preliminaryCheckLifecycle = null,
  preliminaryTransitionState = "idle",
  preliminaryTransitionLifecycle = null,
  mot3DRefinementState = "idle",
  mot3DRefinementLifecycle = null,
  mot3DRefinementTransitionState = "idle",
  mot3DRefinementTransitionLifecycle = null,
  mot3DLatePhase = "idle",
  mot3DLateKind = "submission",
  mot3DLateLifecycle = null,
  mot3DLateNextAction = null,
  copyStatus,
  onCopyCommand,
}: {
  campaign: Campaign;
  transferState: TransferUiState;
  submissionState: SmokeSubmitState;
  submissionResult: SmokeSubmissionResult | null;
  submissionError: string;
  submissionTerminalCode: SmokeTerminalCode;
  remoteState: SmokeLifecycle | null;
  remoteEvidenceFresh: boolean;
  screenSubmitState: ScreeningSubmitState;
  screenState: ScreeningLifecycle | null;
  chainStatus: RefinementChainStatus | null;
  refinementLifecycle: RefinementLifecycle | null;
  confirmationSubmitState?: ConfirmationSubmissionUiState;
  confirmationSubmitJobId?: string | null;
  mot3DDiscoveryState?: Mot3DDiscoveryUiState;
  mot3DDiscoveryLifecycle?: Mot3DDiscoveryLifecycle | null;
  mot3DTransitionState?: Mot3DDiscoveryTransitionUiState;
  mot3DTransitionLifecycle?: Mot3DDiscoveryTransitionLifecycle | null;
  preliminaryCheckState?: PreliminaryCheckUiState;
  preliminaryCheckLifecycle?: PreliminaryCheckLifecycle | null;
  preliminaryTransitionState?: Mot3DPreliminaryTransitionUiState;
  preliminaryTransitionLifecycle?: Mot3DPreliminaryTransitionLifecycle | null;
  mot3DRefinementState?: Mot3DRefinementSubmissionUiState;
  mot3DRefinementLifecycle?: Mot3DRefinementSubmissionLifecycle | null;
  mot3DRefinementTransitionState?: Mot3DRefinementTransitionUiState;
  mot3DRefinementTransitionLifecycle?: Mot3DRefinementTransitionLifecycle | null;
  mot3DLatePhase?: GuardedStagePhase;
  mot3DLateKind?: "submission" | "transition";
  mot3DLateLifecycle?: string | null;
  mot3DLateNextAction?: string | null;
  copyStatus: string;
  onCopyCommand: () => void;
}) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const remoteLifecycle = remoteState?.lifecycle;
  const screenLifecycle = screenState?.lifecycle;
  const chainPriority =
    chainStatus?.chain.status === "not_submitted"
      ? "Action required"
      : ["submitting", "submitted"].includes(chainStatus?.chain.status ?? "")
        ? "No action needed"
        : ["partial", "outcome_unknown"].includes(
              chainStatus?.chain.status ?? "",
            )
          ? "Manual verification required"
          : null;
  const screenPriority =
    chainPriority ??
    (screenLifecycle === "ready_to_prepare_refinement"
      ? "Action required"
      : ["screen_queued", "screen_running", "awaiting_outputs"].includes(
            screenLifecycle ?? "",
          )
        ? "No action needed"
        : screenLifecycle === "refinement_prepared"
          ? "Refinement is prepared"
          : screenLifecycle
            ? "Screening needs attention"
            : null);
  const refinementPriority =
    refinementLifecycle?.chain.status === "ready_to_prepare_confirmation"
      ? "Action required"
      : ["queued", "running", "awaiting_outputs"].includes(
            refinementLifecycle?.chain.status ?? "",
          )
        ? "No action needed"
        : refinementLifecycle?.chain.status === "confirmation_prepared"
          ? "Confirmation is prepared"
          : refinementLifecycle
            ? "Refinement needs attention"
            : null;
  const confirmationSubmissionPriority =
    confirmationSubmitState === "submitted"
      ? "No action needed"
      : confirmationSubmitState === "terminal"
        ? "Manual verification required"
        : confirmationSubmitState === "review"
          ? "Action required"
          : ["checking", "submitting"].includes(confirmationSubmitState)
            ? "No action needed"
            : null;
  const remotePriority =
    confirmationSubmissionPriority ??
    refinementPriority ??
    screenPriority ??
    (screenSubmitState === "submitted"
      ? "No action needed"
      : ["unknown", "terminal"].includes(screenSubmitState)
        ? "Check Zeus jobs before continuing"
        : remoteLifecycle === "ready_to_prepare_screen"
          ? "Action required"
          : ["queued", "running", "awaiting_outputs"].includes(
                remoteLifecycle ?? "",
              )
            ? "No action needed"
            : remoteLifecycle === "screen_prepared"
              ? remoteEvidenceFresh
                ? "Action required"
                : "Refresh Zeus status"
              : remoteLifecycle
                ? "Smoke check needs attention"
                : null);

  if (campaign.family === "mot_3d" && !trusted) {
    return <section className="priority-panel priority-panel--blocked" aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">Inspection only</h2><p>This campaign does not pass the current 3D workflow contract. No status, submission, synchronization, or advance action is available.</p></section>;
  }

  if (campaign.family === "mot_3d" && ["closure", "finalist_selection", "final_validation_input_generation", "final_validation"].includes(campaign.stage)) {
    const labels: Record<string, [string, string]> = {
      closure: ["Closure", "Finalist Selection"],
      finalist_selection: ["Finalist Selection", "final-validation input generation"],
      final_validation_input_generation: ["Final-validation input generation", "Final Validation"],
      final_validation: ["Final Validation", "final result validation"],
    };
    const [current, next] = labels[campaign.stage];
    const manual = ["partial", "outcome_unknown", "held", "completed_failed", "status_unknown", "outputs_invalid"].includes(mot3DLateLifecycle ?? "");
    const active = ["submitted", "queued", "running"].includes(mot3DLateLifecycle ?? "");
    const validationRequired = ["completed_success_unvalidated", "ready_to_advance"].includes(mot3DLateLifecycle ?? "");
    const prepared = ["finalist_selection_prepared", "final_validation_input_generation_prepared", "final_validation_prepared"].includes(mot3DLateLifecycle ?? "");
    const blocked = mot3DLatePhase === "blocked" || manual || mot3DLateNextAction === "inspect_zeus";
    const review = ["ready", "reviewing", "review"].includes(mot3DLatePhase);
    const success = prepared || mot3DLatePhase === "success" || Boolean(mot3DLateNextAction?.startsWith("open_"));
    const busy = ["checking", "confirming"].includes(mot3DLatePhase);
    return <section className={`priority-panel ${blocked ? "priority-panel--blocked" : ""}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{blocked ? "Manual verification required" : success ? `${next} is prepared` : validationRequired ? "Scientific validation and synchronization required" : active ? "No action needed" : review ? `Review ${current}` : busy ? `Checking ${current}` : `Check ${current} status`}</h2><p><strong>Current stage:</strong> {current}.</p><p>{blocked ? "The remote outcome or scientific evidence is not safely actionable. Do not retry automatically; inspect Zeus manually." : success ? `The verified transition prepared ${next}. No later job was submitted or simulation started.` : validationRequired ? "The scheduler chain finished, but its outputs still require stage-specific scientific validation and synchronization before the campaign can advance." : active ? `The reviewed ${current} jobs are submitted, queued, or running on Zeus. Wait for completion; do not submit again.` : review ? `Review the exact stage-specific ${mot3DLateKind} evidence and effects below before confirming. Scheduler completion alone is not scientific validation.` : busy ? "The application is checking or confirming the stage-specific operation. Do not start another action." : `Use the ${current} controls below to check the authoritative stage status.`}</p></section>;
  }

  if (campaign.family === "mot_3d" && campaign.stage === "refinement") {
    if (mot3DRefinementTransitionState!=="idle"||mot3DRefinementTransitionLifecycle){const blocked=mot3DRefinementTransitionState==="terminal"||["not_submitted","held","completed_failed","status_unknown","partial","outcome_unknown"].includes(mot3DRefinementTransitionLifecycle??"");const prepared=mot3DRefinementTransitionState==="prepared"||mot3DRefinementTransitionLifecycle==="closure_prepared";const ready=["ready","review"].includes(mot3DRefinementTransitionState);return <section className={`priority-panel ${blocked?"priority-panel--blocked":""}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{blocked?"Manual verification required":prepared?"Closure is prepared":ready?"Scientific validation and synchronization required":"No action needed"}</h2><p><strong>Current stage:</strong> Refinement.</p><p>{blocked?"The Refinement evidence or transition outcome is not safely actionable. Inspect Zeus before continuing.":prepared?"Verified results are synchronized and Closure files are ready. No Closure job has started.":ready?"Review the verified result set before synchronization prepares Closure.":"The application is checking or synchronizing evidence. No additional action is needed."}</p></section>}
    const blocked = mot3DRefinementState === "terminal" || ["partial", "held", "completed_failed", "status_unknown", "outcome_unknown"].includes(mot3DRefinementLifecycle ?? "");
    const checking = mot3DRefinementState === "checking";
    const active = mot3DRefinementState === "submitting" || ["submitted", "queued", "running"].includes(mot3DRefinementLifecycle ?? "");
    const finished = mot3DRefinementLifecycle === "completed_success_unvalidated";
    const reviewing = mot3DRefinementState === "review";
    return <section className={`priority-panel ${blocked ? "priority-panel--blocked" : ""}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{blocked ? "Manual verification required" : checking ? "Checking Zeus status" : active ? "No action needed" : finished ? "Scientific validation is still required" : reviewing ? "Review Refinement submission" : "Check and review Refinement"}</h2><p><strong>Current stage:</strong> Refinement.</p><p>{blocked ? "The submission is partial or its outcome is not safely known. Do not submit again; inspect Zeus jobs manually." : checking ? "The application is reading the current scheduler state. No submission has been reviewed or started by this check." : active ? "The reviewed Refinement jobs are being submitted, queued, or run on Zeus. No additional action is needed." : finished ? "The scheduler finished, but the scientific outputs have not yet been validated or synchronized. No later stage has started." : "Check Zeus status, then review the exact four-job plan before starting Refinement."}</p></section>;
  }

  if (campaign.family === "mot_3d" && campaign.stage === "preliminary_check") {
    if (preliminaryTransitionState !== "idle" || preliminaryTransitionLifecycle) {
      const blocked = preliminaryTransitionState === "terminal" || ["not_submitted", "held", "completed_failed", "status_unknown", "partial", "outcome_unknown"].includes(preliminaryTransitionLifecycle ?? "");
      const prepared = preliminaryTransitionState === "prepared" || preliminaryTransitionLifecycle === "refinement_prepared";
      const ready = preliminaryTransitionState === "ready" || preliminaryTransitionState === "review";
      return <section className={`priority-panel ${blocked ? "priority-panel--blocked" : ""}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{blocked ? "Manual verification required" : prepared ? "Refinement is prepared" : ready ? "Scientific validation and synchronization required" : preliminaryTransitionState === "checking" || preliminaryTransitionState === "synchronizing" ? "Verifying preliminary-check evidence" : "No action needed"}</h2><p><strong>Current stage:</strong> Preliminary check.</p><p>{blocked ? "The preliminary-check evidence or transition outcome is not safely actionable. Inspect Zeus before continuing." : prepared ? "The verified results are synchronized and Refinement files are ready. No Refinement job has been submitted or started." : ready ? "Review the verified result set before the application synchronizes it and prepares Refinement." : "The application is checking or synchronizing evidence. No additional action is needed while it completes."}</p></section>;
    }
    const attention = preliminaryCheckState === "terminal" || ["partial", "held", "completed_failed", "status_unknown", "outcome_unknown"].includes(preliminaryCheckLifecycle ?? "");
    const checking = preliminaryCheckState === "checking";
    const active = preliminaryCheckState === "submitting" || ["submitted", "queued", "running"].includes(preliminaryCheckLifecycle ?? "");
    const finished = preliminaryCheckLifecycle === "completed_success_unvalidated";
    return <section className={`priority-panel ${attention ? "priority-panel--blocked" : ""}`} aria-labelledby="priority-heading"><p className="eyebrow">Current priority</p><h2 id="priority-heading">{attention ? "Manual verification required" : checking ? "Checking Zeus status" : active ? "No action needed" : finished ? "Scientific validation is still required" : "Review preliminary-check submission"}</h2><p><strong>Current stage:</strong> Preliminary check.</p><p>{attention ? "The submission is partial or its outcome is not safely known. Do not submit again; inspect Zeus jobs manually." : checking ? "The application is reading the current scheduler state. No submission has been reviewed or started by this check." : active ? "The reviewed preliminary-check jobs are being submitted, queued, or run on Zeus. No additional action is needed." : finished ? "The scheduler finished, but the scientific outputs have not yet been validated or synchronized. No later stage has started." : "Check Zeus status, then review the exact four-job plan before starting the held-out candidate comparison."}</p></section>;
  }

  if (campaign.family === "mot_3d" && campaign.stage === "discovery") {
    const transitionAttention = mot3DTransitionState === "terminal" || ["held", "completed_failed", "outputs_invalid", "status_unknown"].includes(mot3DTransitionLifecycle ?? "");
    const transitionWaiting = ["queued", "running", "completed_success_unvalidated"].includes(mot3DTransitionLifecycle ?? "");
    const transitionReady = mot3DTransitionState === "ready" || mot3DTransitionState === "review";
    const transitionPrepared = mot3DTransitionState === "prepared" || mot3DTransitionLifecycle === "preliminary_check_prepared";
    const terminal =
      mot3DDiscoveryState === "terminal" ||
      [
        "held",
        "completed_failed",
        "status_unknown",
        "outcome_unknown",
      ].includes(mot3DDiscoveryLifecycle ?? "");
    const active =
      mot3DDiscoveryState === "submitting" ||
      ["submitted", "queued", "running"].includes(
        mot3DDiscoveryLifecycle ?? "",
      );
    return (
      <section
        className={`priority-panel ${terminal ? "priority-panel--blocked" : ""}`}
        aria-labelledby="priority-heading"
      >
        <p className="eyebrow">Current priority</p>
        <h2 id="priority-heading">
          {transitionAttention
            ? "Manual verification required"
            : transitionPrepared
              ? "Preliminary check is prepared"
              : transitionReady
                ? "Action required"
                : transitionWaiting
                  ? "No action needed"
          : terminal
            ? "Manual verification required"
            : active
              ? "No action needed"
              : mot3DDiscoveryLifecycle === "completed_success"
                ? "Discovery outputs await the next validated stage"
                : "Review Discovery submission"}
        </h2>
        <p>
          <strong>Current stage:</strong> Discovery.
        </p>
        <p>
          {transitionAttention
            ? "Discovery evidence is not safely actionable. Do not advance or submit again; inspect the existing Zeus jobs and outputs."
            : transitionPrepared
              ? "Verified Discovery evidence is synchronized and the preliminary-check files are ready. No preliminary-check job has been submitted."
              : transitionReady
                ? "All 950 Discovery trials passed scientific validation. Review the synchronization and local preparation below."
                : transitionWaiting
                  ? "Discovery is still running or awaiting complete scientific validation. No action is needed until the verified evidence is ready."
          : terminal
            ? "The scheduler outcome is not safe to infer. Do not submit again; inspect Zeus jobs manually."
            : active
              ? "Zeus is running the reviewed five-array Discovery chain. No action is needed while it continues."
              : "The broad angled-donut and single-pass comparison is prepared. Review it below before any job is submitted."}
        </p>
      </section>
    );
  }

  if (confirmationSubmissionPriority) {
    return (
      <section
        className={`priority-panel ${confirmationSubmitState === "terminal" ? "priority-panel--blocked" : ""}`}
        aria-labelledby="priority-heading"
      >
        <p className="eyebrow">Current priority</p>
        <h2 id="priority-heading">{confirmationSubmissionPriority}</h2>
        {confirmationSubmitState === "submitted" && (
          <>
            <p>
              <strong>Current stage on Zeus:</strong> Confirmation.
            </p>
            <p>
              The Confirmation array was submitted
              {confirmationSubmitJobId ? (
                <>
                  {" "}
                  as <code>{confirmationSubmitJobId}</code>
                </>
              ) : null}
              . Zeus continues independently; no action is needed.
            </p>
            <p>
              Sensitivity remains locked until all expected Confirmation outputs
              pass frozen-design and provenance validation.
            </p>
          </>
        )}
        {confirmationSubmitState === "terminal" && (
          <>
            <p>
              <strong>Current stage:</strong> Confirmation submission.
            </p>
            <p>
              The scheduler outcome cannot be established safely. Do not submit
              again; inspect Zeus jobs manually.
            </p>
          </>
        )}
        {confirmationSubmitState === "review" && (
          <>
            <p>
              <strong>Current stage:</strong> Confirmation prepared.
            </p>
            <p>
              The exact Confirmation array is ready for explicit final review
              below. No job has been submitted.
            </p>
            <p>
              It tests one selected candidate on five frozen held-out ensembles
              with 10,000 particles each and the final RK4StHybridCustom solver
              at 0.625 µs. It is not the sealed final performance estimate.
            </p>
          </>
        )}
        {confirmationSubmitState === "checking" && (
          <p>
            The application is checking the frozen Confirmation submission. No
            job is submitted during this check.
          </p>
        )}
        {confirmationSubmitState === "submitting" && (
          <p>
            Wait for the scheduler receipt. Do not submit again or close this
            page yet.
          </p>
        )}
      </section>
    );
  }

  return (
    <section
      className={`priority-panel ${remoteLifecycle && !["queued", "running", "awaiting_outputs", "ready_to_prepare_screen", "screen_prepared"].includes(remoteLifecycle) ? "priority-panel--blocked" : trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`}
      aria-labelledby="priority-heading"
    >
      <p className="eyebrow">Current priority</p>
      <h2 id="priority-heading">
        {remotePriority ??
          (submissionState === "submitted" ||
          (submissionState === "terminal" &&
            submissionTerminalCode === "already_submitted")
            ? "No action needed"
            : ["unknown", "terminal"].includes(submissionState)
              ? "Check Zeus jobs before continuing"
              : transferState === "success"
                ? "Smoke check ready for review"
                : campaign.remote_preparation.status === "legacy-local-only"
                  ? "Recreate this campaign before using Zeus"
                  : campaign.remote_preparation.status === "unavailable"
                    ? "Zeus preparation is unavailable"
                    : trusted
                      ? campaign.next_plan
                        ? "Command available for review"
                        : "No action available"
                      : "Inspection only")}
      </h2>
      {refinementLifecycle ? (
        <>
          <p>
            <strong>Current stage on Zeus:</strong>{" "}
            {refinementLifecycle.chain.status === "confirmation_prepared"
              ? "Confirmation prepared"
              : "Refinement"}
            .
          </p>
          {["queued", "running", "awaiting_outputs"].includes(
            refinementLifecycle.chain.status,
          ) && (
            <p>
              Zeus continues independently. No action is needed; refresh later.
            </p>
          )}
          {refinementLifecycle.chain.status ===
            "ready_to_prepare_confirmation" && (
            <p>
              All four rounds and{" "}
              {refinementLifecycle.validation.completed_trials} trials passed
              validation. Review Confirmation preparation below.
            </p>
          )}
          {refinementLifecycle.chain.status === "confirmation_prepared" && (
            <p>Confirmation files are prepared. No job was submitted.</p>
          )}
          {["held", "failed", "status_unknown", "outputs_invalid"].includes(
            refinementLifecycle.chain.status,
          ) && (
            <p>
              Refinement cannot advance safely. Inspect Zeus before continuing.
            </p>
          )}
        </>
      ) : chainStatus ? (
        <>
          <p>
            <strong>Current stage on Zeus:</strong> Refinement.
          </p>
          {chainStatus.chain.status === "not_submitted" && (
            <p>
              The four-round chain is prepared and ready for explicit submission
              review.
            </p>
          )}
          {chainStatus.chain.status === "submitting" && (
            <p>
              Zeus is acknowledging the dependency chain. Do not retry or close
              until the outcome is resolved.
            </p>
          )}
          {chainStatus.chain.status === "submitted" && (
            <p>
              All four Refinement rounds have durable Zeus job IDs. They will
              run in order after each previous round succeeds.
            </p>
          )}
          {["partial", "outcome_unknown"].includes(
            chainStatus.chain.status,
          ) && (
            <p>
              The chain is only partially confirmed or its outcome is uncertain.
              Automatic retry is blocked; inspect Zeus manually.
            </p>
          )}
        </>
      ) : screenState ? (
        <>
          <p>
            <strong>Current stage on Zeus:</strong>{" "}
            {screenLifecycle === "refinement_prepared"
              ? "Refinement prepared"
              : "Screening"}
            .
          </p>
          {["screen_queued", "screen_running"].includes(
            screenLifecycle ?? "",
          ) && (
            <>
              <p>
                Screening array <code>{screenState.submission.job_id}</code> is{" "}
                {screenLifecycle === "screen_queued" ? "queued" : "running"}.
                Zeus continues independently; you can safely close this
                application.
              </p>
              <p>
                Refinement remains locked until all Screening results are
                complete and validated.
              </p>
            </>
          )}
          {screenLifecycle === "awaiting_outputs" && (
            <p>
              The Screening array completed successfully and Zeus is still
              publishing its expected outputs. No action is needed; refresh
              later.
            </p>
          )}
          {screenLifecycle === "ready_to_prepare_refinement" && (
            <>
              <p>
                All {screenState.validation.completed_trials} Screening trials
                and {screenState.validation.candidate_count} selected candidates
                passed validation.
              </p>
              <p>
                Review the Refinement preparation below. This does not submit
                another job.
              </p>
            </>
          )}
          {screenLifecycle === "refinement_prepared" && (
            <>
              <p>Refinement preparation completed successfully.</p>
              <p>The authoritative transition details are recorded below.</p>
            </>
          )}
          {[
            "screen_held",
            "screen_failed",
            "screen_status_unknown",
            "outputs_invalid",
          ].includes(screenLifecycle ?? "") && (
            <p>
              The Screening stage cannot advance safely. Inspect Zeus before
              continuing.
            </p>
          )}
        </>
      ) : remoteState ? (
        <>
          <p>
            <strong>Current stage on Zeus:</strong>{" "}
            {remoteLifecycle === "screen_prepared"
              ? "Screening prepared"
              : "Smoke check"}
            .
          </p>
          {["queued", "running"].includes(remoteLifecycle ?? "") && (
            <>
              <p>
                Job {remoteState.submission.job_id} is {remoteLifecycle}. Zeus
                continues independently; you can safely close this application.
              </p>
              <p>
                Screening remains locked until every smoke output is complete
                and validated.
              </p>
            </>
          )}
          {remoteLifecycle === "awaiting_outputs" && (
            <>
              <p>
                Job {remoteState.submission.job_id} completed successfully. Zeus
                is still publishing the expected smoke output files.
              </p>
              <p>
                No action is needed. Refresh later; Screening remains locked
                until every output is present and validated.
              </p>
            </>
          )}
          {remoteLifecycle === "ready_to_prepare_screen" && (
            <>
              <p>
                All {remoteState.validation.artifact_count} smoke artifacts
                passed the frozen scientific checks.
              </p>
              <p>
                The smoke check confirms execution and data integrity. Its
                capture values are not a performance result.
              </p>
            </>
          )}
          {remoteLifecycle === "screen_prepared" &&
          screenSubmitState === "submitted" ? (
            <>
              <p>Screening has been submitted successfully.</p>
              <p>
                No later stage was submitted; full details are recorded below.
              </p>
            </>
          ) : (
            remoteLifecycle === "screen_prepared" && (
              <>
                <p>
                  The screening files are ready on Zeus. No screening job was
                  submitted and no simulation started.
                </p>
                <p>
                  {remoteEvidenceFresh
                    ? "A fresh Zeus check confirms that the submission is ready for review."
                    : "Refresh the Zeus status before reviewing submission; this local transition is not evidence of remote readiness."}
                </p>
                <p>
                  The local campaign record has not been synchronized; Zeus is
                  the current source of truth.
                </p>
              </>
            )
          )}
          {remoteLifecycle === "held_attention" && (
            <p>
              The smoke job is held. Inspect the scheduler details on Zeus
              before continuing.
            </p>
          )}
          {remoteLifecycle === "failed" && (
            <p>
              The smoke job ended unsuccessfully. Screening cannot be prepared.
            </p>
          )}
          {remoteLifecycle === "outputs_invalid" && (
            <p>
              The job completed, but its smoke outputs did not pass scientific
              validation. Screening cannot be prepared.
            </p>
          )}
          {remoteLifecycle === "unknown" && (
            <p>
              The scheduler state could not be verified. Do not submit or
              advance this campaign again.
            </p>
          )}
        </>
      ) : submissionState === "submitted" && submissionResult ? (
        <>
          <p>
            <strong>Current stage:</strong> Smoke check.
          </p>
          <p>
            Smoke check submitted as job {submissionResult.job_id}. You can
            safely close the application while Zeus runs it.
          </p>
          <p>
            Screening remains locked until the smoke outputs are complete and
            validated.
          </p>
        </>
      ) : submissionState === "unknown" ? (
        <>
          <p>
            The scheduler response was interrupted, so another submission could
            create duplicate work.
          </p>
          <p>Do not submit again. Check the Zeus jobs page first.</p>
        </>
      ) : submissionState === "terminal" ? (
        <>
          <p>{submissionError}</p>
          <p>
            Submission controls are disabled. Check Zeus jobs before making
            another decision.
          </p>
        </>
      ) : campaign.remote_preparation.status === "legacy-local-only" ? (
        <>
          <p>
            This campaign was created with file locations tied to another
            computer. Its existing records remain available for inspection, but
            the application cannot safely prepare or submit it on Zeus.
          </p>
          <p>
            Create a new campaign from the same validated input source. Nothing
            in this campaign will be changed or deleted.
          </p>
        </>
      ) : campaign.remote_preparation.status === "unavailable" ? (
        <p>
          This campaign does not pass the required portability and validation
          checks. It remains available for inspection, but no Zeus action is
          offered.
        </p>
      ) : (
        <>
          <p>
            <strong>Current prepared stage:</strong> {words(campaign.stage)}.
            This describes local workflow preparation; it does not mean a Zeus
            job is running.
          </p>
          <p>
            <strong>Scheduler status:</strong> not checked.
          </p>
        </>
      )}
      {campaign.next_plan &&
        trusted &&
        campaign.remote_preparation.status === "ready" &&
        !["smoke", "refine"].includes(campaign.stage) &&
        !remoteState &&
        !["submitted", "unknown", "terminal"].includes(submissionState) && (
          <>
            <div className="copy-command">
              <div>
                <span className="command-scope">
                  {campaign.next_plan.operation_scope === "local-mutation"
                    ? "Local state change"
                    : "Remote submission"}{" "}
                  · copy only
                </span>
                <code>{command}</code>
              </div>
              <button
                type="button"
                className="secondary-button"
                onClick={onCopyCommand}
              >
                <Clipboard aria-hidden="true" /> Copy command
              </button>
            </div>
            <p className="copy-status" role="status">
              {copyStatus}
            </p>
          </>
        )}
    </section>
  );
}

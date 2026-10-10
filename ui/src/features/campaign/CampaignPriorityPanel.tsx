import { Clipboard } from "lucide-react";
import type { Campaign } from "../../api/clients/campaign";
import type { RefinementChainStatus, RefinementLifecycle } from "../../api/clients/refinement";
import type { ScreeningLifecycle } from "../../api/clients/screening";
import type { SmokeLifecycle, SmokeSubmissionResult } from "../../api/clients/smoke";
import type { TransferUiState } from "./controllers/useTransferController";
import type { ScreeningSubmitState } from "./controllers/useScreeningController";
import type { SmokeSubmitState, SmokeTerminalCode } from "./controllers/useSmokeController";

const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

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
  copyStatus: string;
  onCopyCommand: () => void;
}) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const remoteLifecycle = remoteState?.lifecycle;
  const screenLifecycle = screenState?.lifecycle;
  const chainPriority = chainStatus?.chain.status === "not_submitted" ? "Action required" : ["submitting", "submitted"].includes(chainStatus?.chain.status ?? "") ? "No action needed" : ["partial", "outcome_unknown"].includes(chainStatus?.chain.status ?? "") ? "Manual verification required" : null;
  const screenPriority = chainPriority ?? (screenLifecycle === "ready_to_prepare_refinement" ? "Action required" : ["screen_queued", "screen_running", "awaiting_outputs"].includes(screenLifecycle ?? "") ? "No action needed" : screenLifecycle === "refinement_prepared" ? "Refinement is prepared" : screenLifecycle ? "Screening needs attention" : null);
  const refinementPriority = refinementLifecycle?.chain.status === "ready_to_prepare_confirmation" ? "Action required" : ["queued", "running", "awaiting_outputs"].includes(refinementLifecycle?.chain.status ?? "") ? "No action needed" : refinementLifecycle?.chain.status === "confirmation_prepared" ? "Confirmation is prepared" : refinementLifecycle ? "Refinement needs attention" : null;
  const remotePriority = refinementPriority ?? screenPriority ?? (screenSubmitState === "submitted" ? "No action needed" : ["unknown", "terminal"].includes(screenSubmitState) ? "Check Zeus jobs before continuing" : remoteLifecycle === "ready_to_prepare_screen" ? "Action required" : ["queued", "running", "awaiting_outputs"].includes(remoteLifecycle ?? "") ? "No action needed" : remoteLifecycle === "screen_prepared" ? (remoteEvidenceFresh ? "Action required" : "Refresh Zeus status") : remoteLifecycle ? "Smoke check needs attention" : null);

  return <section className={`priority-panel ${remoteLifecycle && !["queued", "running", "awaiting_outputs", "ready_to_prepare_screen", "screen_prepared"].includes(remoteLifecycle) ? "priority-panel--blocked" : trusted && campaign.remote_preparation.status === "ready" ? "" : "priority-panel--blocked"}`} aria-labelledby="priority-heading">
    <p className="eyebrow">Current priority</p><h2 id="priority-heading">{remotePriority ?? (submissionState === "submitted" || (submissionState === "terminal" && submissionTerminalCode === "already_submitted") ? "No action needed" : ["unknown", "terminal"].includes(submissionState) ? "Check Zeus jobs before continuing" : transferState === "success" ? "Smoke check ready for review" : campaign.remote_preparation.status === "legacy-local-only" ? "Recreate this campaign before using Zeus" : campaign.remote_preparation.status === "unavailable" ? "Zeus preparation is unavailable" : trusted ? (campaign.next_plan ? "Command available for review" : "No action available") : "Inspection only")}</h2>
    {refinementLifecycle ? <><p><strong>Current stage on Zeus:</strong> {refinementLifecycle.chain.status === "confirmation_prepared" ? "Confirmation prepared" : "Refinement"}.</p>{["queued", "running", "awaiting_outputs"].includes(refinementLifecycle.chain.status) && <p>Zeus continues independently. No action is needed; refresh later.</p>}{refinementLifecycle.chain.status === "ready_to_prepare_confirmation" && <p>All four rounds and {refinementLifecycle.validation.completed_trials} trials passed validation. Review Confirmation preparation below.</p>}{refinementLifecycle.chain.status === "confirmation_prepared" && <p>Confirmation files are prepared. No job was submitted.</p>}{["held", "failed", "status_unknown", "outputs_invalid"].includes(refinementLifecycle.chain.status) && <p>Refinement cannot advance safely. Inspect Zeus before continuing.</p>}</> : chainStatus ? <><p><strong>Current stage on Zeus:</strong> Refinement.</p>{chainStatus.chain.status === "not_submitted" && <p>The four-round chain is prepared and ready for explicit submission review.</p>}{chainStatus.chain.status === "submitting" && <p>Zeus is acknowledging the dependency chain. Do not retry or close until the outcome is resolved.</p>}{chainStatus.chain.status === "submitted" && <p>All four Refinement rounds have durable Zeus job IDs. They will run in order after each previous round succeeds.</p>}{["partial", "outcome_unknown"].includes(chainStatus.chain.status) && <p>The chain is only partially confirmed or its outcome is uncertain. Automatic retry is blocked; inspect Zeus manually.</p>}</> : screenState ? <><p><strong>Current stage on Zeus:</strong> {screenLifecycle === "refinement_prepared" ? "Refinement prepared" : "Screening"}.</p>{["screen_queued", "screen_running"].includes(screenLifecycle ?? "") && <><p>Screening array <code>{screenState.submission.job_id}</code> is {screenLifecycle === "screen_queued" ? "queued" : "running"}. Zeus continues independently; you can safely close this application.</p><p>Refinement remains locked until all Screening results are complete and validated.</p></>}{screenLifecycle === "awaiting_outputs" && <p>The Screening array completed successfully and Zeus is still publishing its expected outputs. No action is needed; refresh later.</p>}{screenLifecycle === "ready_to_prepare_refinement" && <><p>All {screenState.validation.completed_trials} Screening trials and {screenState.validation.candidate_count} selected candidates passed validation.</p><p>Review the Refinement preparation below. This does not submit another job.</p></>}{screenLifecycle === "refinement_prepared" && <><p>Refinement preparation completed successfully.</p><p>The authoritative transition details are recorded below.</p></>}{["screen_held", "screen_failed", "screen_status_unknown", "outputs_invalid"].includes(screenLifecycle ?? "") && <p>The Screening stage cannot advance safely. Inspect Zeus before continuing.</p>}</> : remoteState ? <>
      <p><strong>Current stage on Zeus:</strong> {remoteLifecycle === "screen_prepared" ? "Screening prepared" : "Smoke check"}.</p>
      {["queued", "running"].includes(remoteLifecycle ?? "") && <><p>Job {remoteState.submission.job_id} is {remoteLifecycle}. Zeus continues independently; you can safely close this application.</p><p>Screening remains locked until every smoke output is complete and validated.</p></>}
      {remoteLifecycle === "awaiting_outputs" && <><p>Job {remoteState.submission.job_id} completed successfully. Zeus is still publishing the expected smoke output files.</p><p>No action is needed. Refresh later; Screening remains locked until every output is present and validated.</p></>}
      {remoteLifecycle === "ready_to_prepare_screen" && <><p>All {remoteState.validation.artifact_count} smoke artifacts passed the frozen scientific checks.</p><p>The smoke check confirms execution and data integrity. Its capture values are not a performance result.</p></>}
      {remoteLifecycle === "screen_prepared" && screenSubmitState === "submitted" ? <><p>Screening has been submitted successfully.</p><p>No later stage was submitted; full details are recorded below.</p></> : remoteLifecycle === "screen_prepared" && <><p>The screening files are ready on Zeus. No screening job was submitted and no simulation started.</p><p>{remoteEvidenceFresh ? "A fresh Zeus check confirms that the submission is ready for review." : "Refresh the Zeus status before reviewing submission; this local transition is not evidence of remote readiness."}</p><p>The local campaign record has not been synchronized; Zeus is the current source of truth.</p></>}
      {remoteLifecycle === "held_attention" && <p>The smoke job is held. Inspect the scheduler details on Zeus before continuing.</p>}
      {remoteLifecycle === "failed" && <p>The smoke job ended unsuccessfully. Screening cannot be prepared.</p>}
      {remoteLifecycle === "outputs_invalid" && <p>The job completed, but its smoke outputs did not pass scientific validation. Screening cannot be prepared.</p>}
      {remoteLifecycle === "unknown" && <p>The scheduler state could not be verified. Do not submit or advance this campaign again.</p>}
    </> : submissionState === "submitted" && submissionResult ? <><p><strong>Current stage:</strong> Smoke check.</p><p>Smoke check submitted as job {submissionResult.job_id}. You can safely close the application while Zeus runs it.</p><p>Screening remains locked until the smoke outputs are complete and validated.</p></> : submissionState === "unknown" ? <><p>The scheduler response was interrupted, so another submission could create duplicate work.</p><p>Do not submit again. Check the Zeus jobs page first.</p></> : submissionState === "terminal" ? <><p>{submissionError}</p><p>Submission controls are disabled. Check Zeus jobs before making another decision.</p></> : campaign.remote_preparation.status === "legacy-local-only" ? <><p>This campaign was created with file locations tied to another computer. Its existing records remain available for inspection, but the application cannot safely prepare or submit it on Zeus.</p><p>Create a new campaign from the same validated input source. Nothing in this campaign will be changed or deleted.</p></> : campaign.remote_preparation.status === "unavailable" ? <p>This campaign does not pass the required portability and validation checks. It remains available for inspection, but no Zeus action is offered.</p> : <><p><strong>Current prepared stage:</strong> {words(campaign.stage)}. This describes local workflow preparation; it does not mean a Zeus job is running.</p><p><strong>Scheduler status:</strong> not checked.</p></>}
    {campaign.next_plan && trusted && campaign.remote_preparation.status === "ready" && !["smoke", "refine"].includes(campaign.stage) && !remoteState && !["submitted", "unknown", "terminal"].includes(submissionState) && <><div className="copy-command"><div><span className="command-scope">{campaign.next_plan.operation_scope === "local-mutation" ? "Local state change" : "Remote submission"} · copy only</span><code>{command}</code></div><button type="button" className="secondary-button" onClick={onCopyCommand}><Clipboard aria-hidden="true" /> Copy command</button></div><p className="copy-status" role="status">{copyStatus}</p></>}
  </section>;
}

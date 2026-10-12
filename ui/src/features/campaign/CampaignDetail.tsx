import { ArrowLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Campaign } from "../../api/clients/campaign";
import { confirmationSubmissionApi, type ConfirmationSubmissionApi, type RefinementLifecycleApi, type RefinementSubmissionApi } from "../../api/clients/refinement";
import type { ScreeningLifecycleApi, ScreeningSubmissionApi } from "../../api/clients/screening";
import type { SmokeLifecycleApi, SubmissionApi } from "../../api/clients/smoke";
import type { TransferApi, ZeusSnapshot } from "../../api/clients/zeus";
import { ConfirmationStage } from "./ConfirmationStage";
import { TransferStage } from "./TransferStage";
import { RefinementFlow } from "./RefinementFlow";
import { ScreeningFlow } from "./ScreeningFlow";
import { SmokeFlow } from "./SmokeFlow";
import { useTransferController } from "./controllers/useTransferController";
import { useConfirmationController } from "./controllers/useConfirmationController";
import { useConfirmationSubmissionController } from "./controllers/useConfirmationSubmissionController";
import { useRefinementController } from "./controllers/useRefinementController";
import { useSmokeController } from "./controllers/useSmokeController";
import { useScreeningController } from "./controllers/useScreeningController";
import { CampaignPriorityPanel } from "./CampaignPriorityPanel";
import { sensitivityApi, sensitivitySubmissionApi, type SensitivityApi, type SensitivitySubmissionApi } from "../../api/clients/sensitivity";
import { useSensitivityController } from "./controllers/useSensitivityController";
import { SensitivityStage } from "./SensitivityStage";
import { finalizationApi, productionApi, productionSubmissionApi, type FinalizationApi, type ProductionApi, type ProductionSubmissionApi } from "../../api/clients/production";
import { useProductionController } from "./controllers/useProductionController";
import { ProductionStage } from "./ProductionStage";
import { mot3DDiscoveryApi, type Mot3DDiscoveryApi } from "../../api/clients/mot3dDiscovery";
import { useMot3DDiscoveryController } from "./controllers/useMot3DDiscoveryController";
import { mot3DDiscoveryTransitionApi, type Mot3DDiscoveryTransitionApi } from "../../api/clients/mot3dDiscoveryTransition";
import { useMot3DDiscoveryTransitionController } from "./controllers/useMot3DDiscoveryTransitionController";
import { Mot3DCampaignFlow } from "./Mot3DCampaignFlow";
import { preliminaryCheckApi, type PreliminaryCheckApi } from "../../api/clients/mot3dPreliminaryCheck";
import { useMot3DPreliminaryCheckController } from "./controllers/useMot3DPreliminaryCheckController";
import { mot3DPreliminaryTransitionApi, type Mot3DPreliminaryTransitionApi } from "../../api/clients/mot3dPreliminaryTransition";
import { useMot3DPreliminaryTransitionController } from "./controllers/useMot3DPreliminaryTransitionController";

const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

export function CampaignDetail({ campaign, onBack, transfer, submission, lifecycle, screeningSubmission, screeningLifecycle, refinementSubmission, refinementLifecycle, confirmationSubmission=confirmationSubmissionApi, sensitivity=sensitivityApi, sensitivitySubmission=sensitivitySubmissionApi, production=productionApi, productionSubmission=productionSubmissionApi, finalization=finalizationApi, mot3DDiscovery=mot3DDiscoveryApi, mot3DDiscoveryTransition=mot3DDiscoveryTransitionApi, preliminaryCheck=preliminaryCheckApi, mot3DPreliminaryTransition=mot3DPreliminaryTransitionApi, zeusSnapshot, onConnectZeus, onViewJobs }: { campaign: Campaign; onBack: () => void; transfer: TransferApi; submission: SubmissionApi; lifecycle: SmokeLifecycleApi; screeningSubmission: ScreeningSubmissionApi; screeningLifecycle: ScreeningLifecycleApi; refinementSubmission: RefinementSubmissionApi; refinementLifecycle: RefinementLifecycleApi; confirmationSubmission?: ConfirmationSubmissionApi; sensitivity?: SensitivityApi; sensitivitySubmission?: SensitivitySubmissionApi; production?:ProductionApi; productionSubmission?:ProductionSubmissionApi; finalization?:FinalizationApi; mot3DDiscovery?: Mot3DDiscoveryApi; mot3DDiscoveryTransition?: Mot3DDiscoveryTransitionApi; preliminaryCheck?: PreliminaryCheckApi; mot3DPreliminaryTransition?: Mot3DPreliminaryTransitionApi; zeusSnapshot: ZeusSnapshot | null; onConnectZeus: () => void; onViewJobs: () => void }) {
  const trusted = campaign.trust === "trusted-current";
  const command = campaign.next_plan?.display_command ?? "";
  const [copyStatus, setCopyStatus] = useState("");
  const transferController = useTransferController({ campaignId: campaign.id, snapshot: zeusSnapshot, api: transfer });
  const { state: transferState, preview: transferPreview, result: transferResult, error: transferError } = transferController;
  const smokeController = useSmokeController({ campaignId: campaign.id, snapshot: zeusSnapshot, submissionApi: submission, lifecycleApi: lifecycle });
  const { state: submissionState, preview: submissionPreview, result: submissionResult, error: submissionError, terminalCode: submissionTerminalCode } = smokeController.submission;
  const { value: remoteState, check: remoteCheck, error: remoteError, evidenceFresh: remoteEvidenceFresh } = smokeController.lifecycle;
  const { state: screeningState, preview: screeningPreview, result: screeningResult, error: screeningError } = smokeController.screeningPreparation;
  const screeningController = useScreeningController({ campaignId: campaign.id, snapshot: zeusSnapshot, smokeLifecycle: remoteState, smokeEvidenceFresh: remoteEvidenceFresh, submissionApi: screeningSubmission, lifecycleApi: screeningLifecycle });
  const { state: screenSubmitState, preview: screenSubmitPreview, result: screenSubmitResult, error: screenSubmitError } = screeningController.submission;
  const { value: screenState, check: screenCheck, error: screenError } = screeningController.lifecycle;
  const { state: refineState, preview: refinePreview, result: refineResult, error: refineError } = screeningController.refinementPreparation;
  const refinementController = useRefinementController({ campaignId: campaign.id, snapshot: zeusSnapshot, api: refinementSubmission });
  const { status: chainStatus, check: chainCheck, state: chainState, preview: chainPreview, result: chainResult, error: chainError } = refinementController;
  const confirmationController = useConfirmationController({ campaignId: campaign.id, snapshot: zeusSnapshot, api: refinementLifecycle });
  const { lifecycle: refinementLifecycleState, lifecycleCheck: refinementLifecycleCheck, state: confirmationState, preview: confirmationPreview, result: confirmationResult, error: confirmationError } = confirmationController;
  const confirmationSubmit = useConfirmationSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:confirmationState==="success"||refinementLifecycleState?.chain.status==="confirmation_prepared"||campaign.stage==="confirmation",api:confirmationSubmission});
  const sensitivityFlow=useSensitivityController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:Boolean(confirmationSubmit.result||confirmationSubmit.status||campaign.stage==="confirmation"||campaign.stage==="sensitivity"),api:sensitivity,submissionApi:sensitivitySubmission});
  const productionFlow=useProductionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:Boolean(sensitivityFlow.submission.result||sensitivityFlow.submission.status||campaign.stage==="sensitivity"||campaign.stage==="production"||campaign.stage==="complete"),api:production,submissionApi:productionSubmission,finalizationApi:finalization});
  const mot3DDiscoveryFlow=useMot3DDiscoveryController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:campaign.family==="mot_3d"&&campaign.stage==="discovery",api:mot3DDiscovery});
  const mot3DDiscoveryTransitionFlow=useMot3DDiscoveryTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:campaign.family==="mot_3d"&&(campaign.stage==="discovery"||campaign.stage==="preliminary_check"),api:mot3DDiscoveryTransition});
  const preliminaryCheckFlow=useMot3DPreliminaryCheckController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:campaign.family==="mot_3d"&&campaign.stage==="preliminary_check",api:preliminaryCheck});
  const mot3DPreliminaryTransitionFlow=useMot3DPreliminaryTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:campaign.family==="mot_3d"&&(campaign.stage==="preliminary_check"||campaign.stage==="refinement"),api:mot3DPreliminaryTransition});
  const title = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const successPanel = useRef<HTMLDivElement>(null);
  const errorPanel = useRef<HTMLDivElement>(null);
  const previousTransferState = useRef(transferState);
  useEffect(() => { title.current?.focus(); }, []);
  useEffect(() => {
    const previous = previousTransferState.current;
    if (transferError) errorPanel.current?.focus();
    else if (transferState === "review") reviewHeading.current?.focus();
    else if (transferState === "success") successPanel.current?.focus();
    else if (transferState === "idle" && previous !== "idle") reviewButton.current?.focus();
    previousTransferState.current = transferState;
  }, [transferState, transferError]);
  async function copyCommand() {
    try { await navigator.clipboard.writeText(command); setCopyStatus("Command copied."); }
    catch { setCopyStatus("Copy failed. Select the command text and copy it manually."); }
  }
  return <main id="main" className="detail-page">
    <button className="text-button back-button" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to campaigns</button>
    <header className="detail-hero"><p className="eyebrow">{campaign.family === "mot_2d" ? "2D-MOT campaign" : "3D-MOT campaign"}</p><h1 ref={title} tabIndex={-1}>{campaign.name}</h1><p className="path-text">{campaign.path}</p><div className="detail-badges"><span>{words(campaign.scientific_role)}</span><span className={trusted ? "badge-ok" : "badge-blocked"}>{words(campaign.trust)}</span></div></header>
    <CampaignPriorityPanel campaign={campaign} transferState={transferState} submissionState={submissionState} submissionResult={submissionResult} submissionError={submissionError} submissionTerminalCode={submissionTerminalCode} remoteState={remoteState} remoteEvidenceFresh={remoteEvidenceFresh} screenSubmitState={screenSubmitState} screenState={screenState} chainStatus={chainStatus} refinementLifecycle={refinementLifecycleState} confirmationSubmitState={confirmationSubmit.state} confirmationSubmitJobId={confirmationSubmit.result?.job_id ?? confirmationSubmit.status?.submission.job_id ?? null} mot3DDiscoveryState={mot3DDiscoveryFlow.state} mot3DDiscoveryLifecycle={mot3DDiscoveryFlow.status?.submission.status ?? null} mot3DTransitionState={mot3DDiscoveryTransitionFlow.state} mot3DTransitionLifecycle={mot3DDiscoveryTransitionFlow.status?.discovery.status ?? null} preliminaryCheckState={preliminaryCheckFlow.state} preliminaryCheckLifecycle={preliminaryCheckFlow.status?.submission.status ?? null} preliminaryTransitionState={mot3DPreliminaryTransitionFlow.state} preliminaryTransitionLifecycle={mot3DPreliminaryTransitionFlow.status?.preliminary.status ?? null} copyStatus={copyStatus} onCopyCommand={() => void copyCommand()} />
    <TransferStage visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && !remoteState} snapshot={zeusSnapshot} state={transferState} preview={transferPreview} result={transferResult} error={transferError} buttonRef={reviewButton} headingRef={reviewHeading} successRef={successPanel} errorRef={errorPanel} onConnect={onConnectZeus} onPreview={() => void transferController.previewTransfer()} onConfirm={() => void transferController.confirmTransfer()} onReset={transferController.reset} />
    <SmokeFlow visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && Boolean(zeusSnapshot)} canSubmit={transferState === "success"} submissionState={submissionState} submissionPreview={submissionPreview} submissionResult={submissionResult} submissionError={submissionError} lifecycle={remoteState} lifecycleCheck={remoteCheck} lifecycleError={remoteError} screeningState={screeningState} screeningPreview={screeningPreview} screeningResult={screeningResult} screeningError={screeningError} onPreviewSubmission={() => void smokeController.submission.previewSubmission()} onConfirmSubmission={() => void smokeController.submission.confirmSubmission()} onResetSubmission={smokeController.submission.reset} onRefreshLifecycle={() => void smokeController.lifecycle.refresh()} onPreviewScreening={() => void smokeController.screeningPreparation.previewPreparation()} onConfirmScreening={() => void smokeController.screeningPreparation.confirmPreparation()} onResetScreening={smokeController.screeningPreparation.reset} onViewJobs={onViewJobs} />
    <ScreeningFlow visible={campaign.family === "mot_2d" && Boolean(remoteState?.lifecycle === "screen_prepared" || screenSubmitState === "submitted" || screenState)} evidenceFresh={remoteEvidenceFresh} smokeCheck={remoteCheck} submitState={screenSubmitState} submitPreview={screenSubmitPreview} submitResult={screenSubmitResult} submitError={screenSubmitError} lifecycle={screenState} lifecycleCheck={screenCheck} lifecycleError={screenError} prepareState={refineState} preparePreview={refinePreview} prepareResult={refineResult} prepareError={refineError} onRefreshSmoke={() => void smokeController.lifecycle.refresh()} onPreviewSubmit={() => void screeningController.submission.previewSubmission()} onConfirmSubmit={() => void screeningController.submission.confirmSubmission()} onResetSubmit={screeningController.submission.reset} onRefreshLifecycle={() => void screeningController.lifecycle.refresh()} onPreviewPrepare={() => void screeningController.refinementPreparation.previewPreparation()} onConfirmPrepare={() => void screeningController.refinementPreparation.confirmPreparation()} onResetPrepare={screeningController.refinementPreparation.reset} onViewJobs={onViewJobs} />
    <RefinementFlow visible={campaign.family === "mot_2d" && Boolean(screenState?.lifecycle === "refinement_prepared" || refineState === "success" || campaign.stage === "refine" || chainStatus) && Boolean(zeusSnapshot)} status={chainStatus} check={chainCheck} state={chainState} preview={chainPreview} result={chainResult} error={chainError} onRefresh={() => void refinementController.refresh()} onPreview={() => void refinementController.previewSubmission()} onConfirm={() => void refinementController.confirmSubmission()} onReset={refinementController.reset} onViewJobs={onViewJobs} />
    <ConfirmationStage visible={campaign.family === "mot_2d" && Boolean(chainStatus?.chain.status === "submitted" || chainResult || refinementLifecycleState || campaign.stage === "refine" || campaign.stage === "confirmation") && Boolean(zeusSnapshot)} lifecycle={refinementLifecycleState} lifecycleCheck={refinementLifecycleCheck} state={confirmationState} preview={confirmationPreview} result={confirmationResult} error={confirmationError} onRefresh={() => void confirmationController.refresh()} onPreview={() => void confirmationController.previewConfirmation()} onConfirm={() => void confirmationController.confirmConfirmation()} onReset={confirmationController.reset} onViewJobs={onViewJobs} submissionEnabled={confirmationState==="success"||refinementLifecycleState?.chain.status==="confirmation_prepared"||campaign.stage==="confirmation"} submission={confirmationSubmit} />
    <SensitivityStage visible={campaign.family === "mot_2d" && Boolean(zeusSnapshot)&&(Boolean(confirmationSubmit.result||confirmationSubmit.status)||campaign.stage==="confirmation"||campaign.stage==="sensitivity")} flow={sensitivityFlow} onViewJobs={onViewJobs}/>
    <ProductionStage visible={campaign.family === "mot_2d" && Boolean(zeusSnapshot)&&(Boolean(sensitivityFlow.submission.result||sensitivityFlow.submission.status)||campaign.stage==="sensitivity"||campaign.stage==="production"||campaign.stage==="complete")} flow={productionFlow} onViewJobs={onViewJobs}/>
    {campaign.family === "mot_3d" && (
      <Mot3DCampaignFlow
        stage={campaign.stage}
        connected={Boolean(zeusSnapshot)}
        discovery={mot3DDiscoveryFlow}
        transition={mot3DDiscoveryTransitionFlow}
        preliminary={preliminaryCheckFlow}
        preliminaryTransition={mot3DPreliminaryTransitionFlow}
        onConnectZeus={onConnectZeus}
        onViewJobs={onViewJobs}
      />
    )}
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

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
import { mot3DRefinementSubmissionApi, type Mot3DRefinementSubmissionApi } from "../../api/clients/mot3dRefinementSubmission";
import { useMot3DRefinementSubmissionController } from "./controllers/useMot3DRefinementSubmissionController";
import { mot3DRefinementTransitionApi, type Mot3DRefinementTransitionApi } from "../../api/clients/mot3dRefinementTransition";
import { useMot3DRefinementTransitionController } from "./controllers/useMot3DRefinementTransitionController";
import { mot3DClosureSubmissionApi, type Mot3DClosureSubmissionApi } from "../../api/clients/mot3dClosureSubmission";
import { useMot3DClosureSubmissionController } from "./controllers/useMot3DClosureSubmissionController";
import { mot3DClosureTransitionApi, type Mot3DClosureTransitionApi } from "../../api/clients/mot3dClosureTransition";
import { useMot3DClosureTransitionController } from "./controllers/useMot3DClosureTransitionController";
import { mot3DFinalistSubmissionApi, type Mot3DFinalistSubmissionApi } from "../../api/clients/mot3dFinalistSubmission";
import { useMot3DFinalistSubmissionController } from "./controllers/useMot3DFinalistSubmissionController";
import { mot3DFinalistTransitionApi, type Mot3DFinalistTransitionApi } from "../../api/clients/mot3dFinalistTransition";
import { useMot3DFinalistTransitionController } from "./controllers/useMot3DFinalistTransitionController";
import { mot3DFinalInputSubmissionApi, type Mot3DFinalInputSubmissionApi } from "../../api/clients/mot3dFinalInputSubmission";
import { useMot3DFinalInputSubmissionController } from "./controllers/useMot3DFinalInputSubmissionController";
import { mot3DFinalValidationTransitionApi, type Mot3DFinalValidationTransitionApi } from "../../api/clients/mot3dFinalValidationTransition";
import { useMot3DFinalValidationTransitionController } from "./controllers/useMot3DFinalValidationTransitionController";
import { mot3DFinalValidationSubmissionApi } from "../../api/clients/mot3dFinalValidationSubmission";
import { useMot3DFinalValidationSubmissionController } from "./controllers/useMot3DFinalValidationSubmissionController";

const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");

export function CampaignDetail({ campaign, onBack, transfer, submission, lifecycle, screeningSubmission, screeningLifecycle, refinementSubmission, refinementLifecycle, confirmationSubmission=confirmationSubmissionApi, sensitivity=sensitivityApi, sensitivitySubmission=sensitivitySubmissionApi, production=productionApi, productionSubmission=productionSubmissionApi, finalization=finalizationApi, mot3DDiscovery=mot3DDiscoveryApi, mot3DDiscoveryTransition=mot3DDiscoveryTransitionApi, preliminaryCheck=preliminaryCheckApi, mot3DPreliminaryTransition=mot3DPreliminaryTransitionApi, mot3DRefinementSubmission=mot3DRefinementSubmissionApi, mot3DRefinementTransition=mot3DRefinementTransitionApi, mot3DClosureSubmission=mot3DClosureSubmissionApi, mot3DClosureTransition=mot3DClosureTransitionApi, mot3DFinalistSubmission=mot3DFinalistSubmissionApi, mot3DFinalistTransition=mot3DFinalistTransitionApi, mot3DFinalInputSubmission=mot3DFinalInputSubmissionApi, mot3DFinalValidationTransition=mot3DFinalValidationTransitionApi, zeusSnapshot, onConnectZeus, onViewJobs }: { campaign: Campaign; onBack: () => void; transfer: TransferApi; submission: SubmissionApi; lifecycle: SmokeLifecycleApi; screeningSubmission: ScreeningSubmissionApi; screeningLifecycle: ScreeningLifecycleApi; refinementSubmission: RefinementSubmissionApi; refinementLifecycle: RefinementLifecycleApi; confirmationSubmission?: ConfirmationSubmissionApi; sensitivity?: SensitivityApi; sensitivitySubmission?: SensitivitySubmissionApi; production?:ProductionApi; productionSubmission?:ProductionSubmissionApi; finalization?:FinalizationApi; mot3DDiscovery?: Mot3DDiscoveryApi; mot3DDiscoveryTransition?: Mot3DDiscoveryTransitionApi; preliminaryCheck?: PreliminaryCheckApi; mot3DPreliminaryTransition?: Mot3DPreliminaryTransitionApi; mot3DRefinementSubmission?:Mot3DRefinementSubmissionApi; mot3DRefinementTransition?:Mot3DRefinementTransitionApi; mot3DClosureSubmission?:Mot3DClosureSubmissionApi; mot3DClosureTransition?:Mot3DClosureTransitionApi; mot3DFinalistSubmission?:Mot3DFinalistSubmissionApi; mot3DFinalistTransition?:Mot3DFinalistTransitionApi; mot3DFinalInputSubmission?:Mot3DFinalInputSubmissionApi; mot3DFinalValidationTransition?:Mot3DFinalValidationTransitionApi; zeusSnapshot: ZeusSnapshot | null; onConnectZeus: () => void; onViewJobs: () => void }) {
  const trusted = campaign.trust === "trusted-current";
  const current3D = campaign.family === "mot_3d" && trusted;
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
  const mot3DDiscoveryFlow=useMot3DDiscoveryController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="discovery",api:mot3DDiscovery});
  const mot3DDiscoveryTransitionFlow=useMot3DDiscoveryTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="discovery"||campaign.stage==="preliminary_check"),api:mot3DDiscoveryTransition});
  const preliminaryCheckFlow=useMot3DPreliminaryCheckController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="preliminary_check",api:preliminaryCheck});
  const mot3DPreliminaryTransitionFlow=useMot3DPreliminaryTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="preliminary_check"||campaign.stage==="refinement"),api:mot3DPreliminaryTransition});
  const mot3DRefinementSubmissionFlow=useMot3DRefinementSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="refinement",api:mot3DRefinementSubmission});
  const mot3DRefinementTransitionFlow=useMot3DRefinementTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="refinement"||campaign.stage==="closure"),api:mot3DRefinementTransition});
  const mot3DClosureSubmissionFlow=useMot3DClosureSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="closure",api:mot3DClosureSubmission});
  const mot3DClosureTransitionFlow=useMot3DClosureTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="closure"||campaign.stage==="finalist_selection"),api:mot3DClosureTransition});
  const mot3DFinalistSubmissionFlow=useMot3DFinalistSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="finalist_selection",api:mot3DFinalistSubmission});
  const mot3DFinalistTransitionFlow=useMot3DFinalistTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="finalist_selection"||campaign.stage==="final_validation_input_generation"),api:mot3DFinalistTransition});
  const mot3DFinalInputSubmissionFlow=useMot3DFinalInputSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="final_validation_input_generation",api:mot3DFinalInputSubmission});
  const mot3DFinalValidationTransitionFlow=useMot3DFinalValidationTransitionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&(campaign.stage==="final_validation_input_generation"||campaign.stage==="final_validation"),api:mot3DFinalValidationTransition});
  const mot3DFinalValidationSubmissionFlow=useMot3DFinalValidationSubmissionController({campaignId:campaign.id,snapshot:zeusSnapshot,enabled:current3D&&campaign.stage==="final_validation",api:mot3DFinalValidationSubmissionApi});
  const late3DFlow = campaign.stage === "closure"
    ? (mot3DClosureTransitionFlow.phase !== "idle" || mot3DClosureTransitionFlow.status ? mot3DClosureTransitionFlow : mot3DClosureSubmissionFlow)
    : campaign.stage === "finalist_selection"
      ? (mot3DFinalistTransitionFlow.phase !== "idle" || mot3DFinalistTransitionFlow.status ? mot3DFinalistTransitionFlow : mot3DFinalistSubmissionFlow)
      : campaign.stage === "final_validation_input_generation"
        ? (mot3DFinalValidationTransitionFlow.phase !== "idle" || mot3DFinalValidationTransitionFlow.status ? mot3DFinalValidationTransitionFlow : mot3DFinalInputSubmissionFlow)
        : campaign.stage === "final_validation"
          ? (mot3DFinalValidationSubmissionFlow.phase !== "idle" || mot3DFinalValidationSubmissionFlow.status ? mot3DFinalValidationSubmissionFlow : mot3DFinalValidationTransitionFlow)
          : null;
  const late3DTransition = late3DFlow === mot3DClosureTransitionFlow || late3DFlow === mot3DFinalistTransitionFlow || late3DFlow === mot3DFinalValidationTransitionFlow;
  const late3DLifecycle = late3DFlow === mot3DClosureSubmissionFlow
    ? mot3DClosureSubmissionFlow.status?.submission.status
    : late3DFlow === mot3DFinalistSubmissionFlow
      ? mot3DFinalistSubmissionFlow.status?.submission.status
      : late3DFlow === mot3DFinalInputSubmissionFlow
        ? mot3DFinalInputSubmissionFlow.status?.chain.status
        : late3DFlow === mot3DFinalValidationSubmissionFlow
          ? mot3DFinalValidationSubmissionFlow.status?.submission.status
        : late3DFlow === mot3DClosureTransitionFlow
          ? mot3DClosureTransitionFlow.status?.closure.status
          : late3DFlow === mot3DFinalistTransitionFlow
            ? mot3DFinalistTransitionFlow.status?.finalist_selection.status
            : late3DFlow === mot3DFinalValidationTransitionFlow
              ? mot3DFinalValidationTransitionFlow.status?.final_validation_input_generation.status
              : null;
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
    <CampaignPriorityPanel campaign={campaign} transferState={transferState} submissionState={submissionState} submissionResult={submissionResult} submissionError={submissionError} submissionTerminalCode={submissionTerminalCode} remoteState={remoteState} remoteEvidenceFresh={remoteEvidenceFresh} screenSubmitState={screenSubmitState} screenState={screenState} chainStatus={chainStatus} refinementLifecycle={refinementLifecycleState} confirmationSubmitState={confirmationSubmit.state} confirmationSubmitJobId={confirmationSubmit.result?.job_id ?? confirmationSubmit.status?.submission.job_id ?? null} mot3DDiscoveryState={mot3DDiscoveryFlow.state} mot3DDiscoveryLifecycle={mot3DDiscoveryFlow.status?.submission.status ?? null} mot3DTransitionState={mot3DDiscoveryTransitionFlow.state} mot3DTransitionLifecycle={mot3DDiscoveryTransitionFlow.status?.discovery.status ?? null} preliminaryCheckState={preliminaryCheckFlow.state} preliminaryCheckLifecycle={preliminaryCheckFlow.status?.submission.status ?? null} preliminaryTransitionState={mot3DPreliminaryTransitionFlow.state} preliminaryTransitionLifecycle={mot3DPreliminaryTransitionFlow.status?.preliminary.status ?? null} mot3DRefinementState={mot3DRefinementSubmissionFlow.state} mot3DRefinementLifecycle={mot3DRefinementSubmissionFlow.status?.submission.status ?? null} mot3DRefinementTransitionState={mot3DRefinementTransitionFlow.state} mot3DRefinementTransitionLifecycle={mot3DRefinementTransitionFlow.status?.refinement.status ?? null} mot3DLatePhase={late3DFlow?.phase ?? "idle"} mot3DLateKind={late3DTransition ? "transition" : "submission"} mot3DLateLifecycle={late3DLifecycle ?? null} mot3DLateNextAction={late3DFlow?.status?.next_action ?? null} copyStatus={copyStatus} onCopyCommand={() => void copyCommand()} />
    <TransferStage visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && !remoteState} snapshot={zeusSnapshot} state={transferState} preview={transferPreview} result={transferResult} error={transferError} buttonRef={reviewButton} headingRef={reviewHeading} successRef={successPanel} errorRef={errorPanel} onConnect={onConnectZeus} onPreview={() => void transferController.previewTransfer()} onConfirm={() => void transferController.confirmTransfer()} onReset={transferController.reset} />
    <SmokeFlow visible={campaign.family === "mot_2d" && trusted && campaign.remote_preparation.status === "ready" && campaign.stage === "smoke" && Boolean(zeusSnapshot)} canSubmit={transferState === "success"} submissionState={submissionState} submissionPreview={submissionPreview} submissionResult={submissionResult} submissionError={submissionError} lifecycle={remoteState} lifecycleCheck={remoteCheck} lifecycleError={remoteError} screeningState={screeningState} screeningPreview={screeningPreview} screeningResult={screeningResult} screeningError={screeningError} onPreviewSubmission={() => void smokeController.submission.previewSubmission()} onConfirmSubmission={() => void smokeController.submission.confirmSubmission()} onResetSubmission={smokeController.submission.reset} onRefreshLifecycle={() => void smokeController.lifecycle.refresh()} onPreviewScreening={() => void smokeController.screeningPreparation.previewPreparation()} onConfirmScreening={() => void smokeController.screeningPreparation.confirmPreparation()} onResetScreening={smokeController.screeningPreparation.reset} onViewJobs={onViewJobs} />
    <ScreeningFlow visible={campaign.family === "mot_2d" && Boolean(remoteState?.lifecycle === "screen_prepared" || screenSubmitState === "submitted" || screenState)} evidenceFresh={remoteEvidenceFresh} smokeCheck={remoteCheck} submitState={screenSubmitState} submitPreview={screenSubmitPreview} submitResult={screenSubmitResult} submitError={screenSubmitError} lifecycle={screenState} lifecycleCheck={screenCheck} lifecycleError={screenError} prepareState={refineState} preparePreview={refinePreview} prepareResult={refineResult} prepareError={refineError} onRefreshSmoke={() => void smokeController.lifecycle.refresh()} onPreviewSubmit={() => void screeningController.submission.previewSubmission()} onConfirmSubmit={() => void screeningController.submission.confirmSubmission()} onResetSubmit={screeningController.submission.reset} onRefreshLifecycle={() => void screeningController.lifecycle.refresh()} onPreviewPrepare={() => void screeningController.refinementPreparation.previewPreparation()} onConfirmPrepare={() => void screeningController.refinementPreparation.confirmPreparation()} onResetPrepare={screeningController.refinementPreparation.reset} onViewJobs={onViewJobs} />
    <RefinementFlow visible={campaign.family === "mot_2d" && Boolean(screenState?.lifecycle === "refinement_prepared" || refineState === "success" || campaign.stage === "refine" || chainStatus) && Boolean(zeusSnapshot)} status={chainStatus} check={chainCheck} state={chainState} preview={chainPreview} result={chainResult} error={chainError} onRefresh={() => void refinementController.refresh()} onPreview={() => void refinementController.previewSubmission()} onConfirm={() => void refinementController.confirmSubmission()} onReset={refinementController.reset} onViewJobs={onViewJobs} />
    <ConfirmationStage visible={campaign.family === "mot_2d" && Boolean(chainStatus?.chain.status === "submitted" || chainResult || refinementLifecycleState || campaign.stage === "refine" || campaign.stage === "confirmation") && Boolean(zeusSnapshot)} lifecycle={refinementLifecycleState} lifecycleCheck={refinementLifecycleCheck} state={confirmationState} preview={confirmationPreview} result={confirmationResult} error={confirmationError} onRefresh={() => void confirmationController.refresh()} onPreview={() => void confirmationController.previewConfirmation()} onConfirm={() => void confirmationController.confirmConfirmation()} onReset={confirmationController.reset} onViewJobs={onViewJobs} submissionEnabled={confirmationState==="success"||refinementLifecycleState?.chain.status==="confirmation_prepared"||campaign.stage==="confirmation"} submission={confirmationSubmit} />
    <SensitivityStage visible={campaign.family === "mot_2d" && Boolean(zeusSnapshot)&&(Boolean(confirmationSubmit.result||confirmationSubmit.status)||campaign.stage==="confirmation"||campaign.stage==="sensitivity")} flow={sensitivityFlow} onViewJobs={onViewJobs}/>
    <ProductionStage visible={campaign.family === "mot_2d" && Boolean(zeusSnapshot)&&(Boolean(sensitivityFlow.submission.result||sensitivityFlow.submission.status)||campaign.stage==="sensitivity"||campaign.stage==="production"||campaign.stage==="complete")} flow={productionFlow} onViewJobs={onViewJobs}/>
    {current3D && (
      <Mot3DCampaignFlow
        stage={campaign.stage}
        connected={Boolean(zeusSnapshot)}
        discovery={mot3DDiscoveryFlow}
        transition={mot3DDiscoveryTransitionFlow}
        preliminary={preliminaryCheckFlow}
        preliminaryTransition={mot3DPreliminaryTransitionFlow}
        refinement={mot3DRefinementSubmissionFlow}
        refinementTransition={mot3DRefinementTransitionFlow}
        closure={mot3DClosureSubmissionFlow}
        closureTransition={mot3DClosureTransitionFlow}
        finalist={mot3DFinalistSubmissionFlow}
        finalistTransition={mot3DFinalistTransitionFlow}
        finalInputSubmission={mot3DFinalInputSubmissionFlow}
        finalValidationTransition={mot3DFinalValidationTransitionFlow}
        finalValidation={mot3DFinalValidationSubmissionFlow}
        onConnectZeus={onConnectZeus}
        onViewJobs={onViewJobs}
      />
    )}
    <section className="section-block" aria-labelledby="timeline-heading"><div className="section-heading"><h2 id="timeline-heading">Campaign timeline</h2><p>Progress reflects validated local output files only.</p></div><div className="timeline-legend" aria-label="Timeline color legend"><span><i className="dot dot--empty" /> Not started</span><span><i className="dot dot--active" /> Partial output</span><span><i className="dot dot--complete" /> Complete</span><span><i className="dot dot--blocked" /> Unknown or inconsistent</span></div>{campaign.progress.length ? <ol className="timeline">{campaign.progress.map((stage) => <li className={`timeline-item timeline-item--${stage.status}`} key={stage.stage}><span className="timeline-marker" aria-hidden="true" /><div><strong>{words(stage.stage)}</strong><p>{stage.expected === null ? `${stage.completed} validated outputs; expected total unavailable` : `${stage.completed} of ${stage.expected} validated outputs`}</p><span className="sr-only">Status: {words(stage.status)}</span></div></li>)}</ol> : <div className="state-panel">No validated stage progress is available.</div>}</section>
    {campaign.warnings.length > 0 && <section className="section-block" aria-labelledby="warnings-heading"><div className="section-heading"><h2 id="warnings-heading">Checks and warnings</h2></div><ul className="warning-list">{campaign.warnings.map((warning, index) => <li className={`warning warning--${warning.severity}`} key={`${warning.message}-${index}`}><strong>{warning.severity}</strong><span>{warning.message}</span></li>)}</ul></section>}
  </main>;
}

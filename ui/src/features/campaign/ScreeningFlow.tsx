import { useEffect, useRef } from "react";
import type {
  RefinementPreview,
  RefinementResult,
  ScreeningLifecycle,
  ScreeningSubmissionPreview,
  ScreeningSubmissionResult,
} from "../../api/clients/screening";
import type {
  RefinementPreparationState as PrepareState,
  ScreeningCheckState as CheckState,
  ScreeningSubmitState as SubmitState,
} from "./controllers/useScreeningController";
import { RefinementPreparationSection } from "./screening/RefinementPreparationSection";
import { ScreeningLifecycleSection } from "./screening/ScreeningLifecycleSection";
import { ScreeningSubmissionSection } from "./screening/ScreeningSubmissionSection";
export function ScreeningFlow({
  visible,
  evidenceFresh,
  smokeCheck,
  submitState,
  submitPreview,
  submitResult,
  submitError,
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  prepareState,
  preparePreview,
  prepareResult,
  prepareError,
  onRefreshSmoke,
  onPreviewSubmit,
  onConfirmSubmit,
  onResetSubmit,
  onRefreshLifecycle,
  onPreviewPrepare,
  onConfirmPrepare,
  onResetPrepare,
  onViewJobs,
}: {
  visible: boolean;
  evidenceFresh: boolean;
  smokeCheck: CheckState;
  submitState: SubmitState;
  submitPreview: ScreeningSubmissionPreview | null;
  submitResult: ScreeningSubmissionResult | null;
  submitError: string;
  lifecycle: ScreeningLifecycle | null;
  lifecycleCheck: CheckState;
  lifecycleError: string;
  prepareState: PrepareState;
  preparePreview: RefinementPreview | null;
  prepareResult: RefinementResult | null;
  prepareError: string;
  onRefreshSmoke: () => void;
  onPreviewSubmit: () => void;
  onConfirmSubmit: () => void;
  onResetSubmit: () => void;
  onRefreshLifecycle: () => void;
  onPreviewPrepare: () => void;
  onConfirmPrepare: () => void;
  onResetPrepare: () => void;
  onViewJobs: () => void;
}) {
  const submitButton = useRef<HTMLButtonElement>(null);
  const submitHeading = useRef<HTMLHeadingElement>(null);
  const submitPanel = useRef<HTMLDivElement>(null);
  const statusHeading = useRef<HTMLHeadingElement>(null);
  const statusErrorPanel = useRef<HTMLDivElement>(null);
  const prepareButton = useRef<HTMLButtonElement>(null);
  const prepareHeading = useRef<HTMLHeadingElement>(null);
  const preparePanel = useRef<HTMLDivElement>(null);
  const previousSubmitState = useRef(submitState);
  const previousCheck = useRef(lifecycleCheck);
  const previousPrepareState = useRef(prepareState);
  useEffect(() => {
    const previous = previousSubmitState.current;
    if (submitState === "review") submitHeading.current?.focus();
    else if (
      ["submitted", "unknown", "terminal", "error"].includes(submitState)
    )
      submitPanel.current?.focus();
    else if (submitState === "idle" && previous === "review")
      submitButton.current?.focus();
    previousSubmitState.current = submitState;
  }, [submitState]);
  useEffect(() => {
    if (lifecycleError) statusErrorPanel.current?.focus();
    else if (lifecycleCheck === "ready" && previousCheck.current !== "ready")
      statusHeading.current?.focus();
    previousCheck.current = lifecycleCheck;
  }, [lifecycleCheck, lifecycleError]);
  useEffect(() => {
    const previous = previousPrepareState.current;
    if (prepareState === "review") prepareHeading.current?.focus();
    else if (["success", "terminal"].includes(prepareState) || prepareError)
      preparePanel.current?.focus();
    else if (prepareState === "idle" && previous === "review")
      prepareButton.current?.focus();
    previousPrepareState.current = prepareState;
  }, [prepareState, prepareError]);
  if (!visible) return null;
  return (
    <>
      <ScreeningSubmissionSection
        evidenceFresh={evidenceFresh}
        smokeCheck={smokeCheck}
        submitState={submitState}
        submitPreview={submitPreview}
        submitResult={submitResult}
        submitError={submitError}
        lifecycle={lifecycle}
        submitButton={submitButton}
        submitHeading={submitHeading}
        submitPanel={submitPanel}
        onRefreshSmoke={onRefreshSmoke}
        onPreviewSubmit={onPreviewSubmit}
        onConfirmSubmit={onConfirmSubmit}
        onResetSubmit={onResetSubmit}
        onViewJobs={onViewJobs}
      />
      <ScreeningLifecycleSection
        lifecycle={lifecycle}
        lifecycleCheck={lifecycleCheck}
        lifecycleError={lifecycleError}
        statusHeading={statusHeading}
        statusErrorPanel={statusErrorPanel}
        onRefreshLifecycle={onRefreshLifecycle}
        onViewJobs={onViewJobs}
      />
      <RefinementPreparationSection
        lifecycle={lifecycle}
        prepareState={prepareState}
        preparePreview={preparePreview}
        prepareResult={prepareResult}
        prepareError={prepareError}
        prepareButton={prepareButton}
        prepareHeading={prepareHeading}
        preparePanel={preparePanel}
        onPreviewPrepare={onPreviewPrepare}
        onConfirmPrepare={onConfirmPrepare}
        onResetPrepare={onResetPrepare}
        onViewJobs={onViewJobs}
      />
    </>
  );
}

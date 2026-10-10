import { useEffect, useRef } from "react";
import type {
  ScreeningPreview,
  ScreeningResult,
  SmokeLifecycle,
  SmokeSubmissionPreview,
  SmokeSubmissionResult,
} from "../../api/clients/smoke";
import type {
  ScreeningPreparationState,
  SmokeCheckState,
  SmokeSubmitState,
} from "./controllers/useSmokeController";
import { ScreeningPreparationSection } from "./smoke/ScreeningPreparationSection";
import { SmokeLifecycleSection } from "./smoke/SmokeLifecycleSection";
import { SmokeSubmissionSection } from "./smoke/SmokeSubmissionSection";

export function SmokeFlow({
  visible,
  canSubmit,
  submissionState,
  submissionPreview,
  submissionResult,
  submissionError,
  lifecycle,
  lifecycleCheck,
  lifecycleError,
  screeningState,
  screeningPreview,
  screeningResult,
  screeningError,
  onPreviewSubmission,
  onConfirmSubmission,
  onResetSubmission,
  onRefreshLifecycle,
  onPreviewScreening,
  onConfirmScreening,
  onResetScreening,
  onViewJobs,
}: {
  visible: boolean;
  canSubmit: boolean;
  submissionState: SmokeSubmitState;
  submissionPreview: SmokeSubmissionPreview | null;
  submissionResult: SmokeSubmissionResult | null;
  submissionError: string;
  lifecycle: SmokeLifecycle | null;
  lifecycleCheck: SmokeCheckState;
  lifecycleError: string;
  screeningState: ScreeningPreparationState;
  screeningPreview: ScreeningPreview | null;
  screeningResult: ScreeningResult | null;
  screeningError: string;
  onPreviewSubmission: () => void;
  onConfirmSubmission: () => void;
  onResetSubmission: () => void;
  onRefreshLifecycle: () => void;
  onPreviewScreening: () => void;
  onConfirmScreening: () => void;
  onResetScreening: () => void;
  onViewJobs: () => void;
}) {
  const submissionButton = useRef<HTMLButtonElement>(null);
  const submissionHeading = useRef<HTMLHeadingElement>(null);
  const submissionSuccess = useRef<HTMLDivElement>(null);
  const submissionErrorPanel = useRef<HTMLDivElement>(null);
  const lifecycleHeading = useRef<HTMLHeadingElement>(null);
  const lifecycleErrorPanel = useRef<HTMLDivElement>(null);
  const screeningButton = useRef<HTMLButtonElement>(null);
  const screeningHeading = useRef<HTMLHeadingElement>(null);
  const screeningSuccess = useRef<HTMLDivElement>(null);
  const screeningErrorPanel = useRef<HTMLDivElement>(null);
  const previousSubmissionState = useRef(submissionState);
  const previousLifecycleCheck = useRef(lifecycleCheck);
  const previousScreeningState = useRef(screeningState);
  useEffect(() => {
    const previous = previousSubmissionState.current;
    if (submissionError) submissionErrorPanel.current?.focus();
    else if (submissionState === "review") submissionHeading.current?.focus();
    else if (submissionState === "submitted")
      submissionSuccess.current?.focus();
    else if (submissionState === "idle" && previous === "review")
      submissionButton.current?.focus();
    previousSubmissionState.current = submissionState;
  }, [submissionState, submissionError]);
  useEffect(() => {
    if (lifecycleError) lifecycleErrorPanel.current?.focus();
    else if (
      lifecycleCheck === "ready" &&
      previousLifecycleCheck.current !== "ready"
    )
      lifecycleHeading.current?.focus();
    previousLifecycleCheck.current = lifecycleCheck;
  }, [lifecycleCheck, lifecycleError]);
  useEffect(() => {
    if (screeningError) screeningErrorPanel.current?.focus();
    else if (screeningState === "review") screeningHeading.current?.focus();
    else if (screeningState === "success") screeningSuccess.current?.focus();
    else if (
      screeningState === "idle" &&
      previousScreeningState.current === "review"
    )
      screeningButton.current?.focus();
    previousScreeningState.current = screeningState;
  }, [screeningState, screeningError]);
  if (!visible) return null;
  return (
    <>
      <SmokeSubmissionSection
        canSubmit={canSubmit}
        submissionState={submissionState}
        submissionPreview={submissionPreview}
        submissionResult={submissionResult}
        submissionError={submissionError}
        submissionButton={submissionButton}
        submissionHeading={submissionHeading}
        submissionSuccess={submissionSuccess}
        submissionErrorPanel={submissionErrorPanel}
        onPreviewSubmission={onPreviewSubmission}
        onConfirmSubmission={onConfirmSubmission}
        onResetSubmission={onResetSubmission}
        onViewJobs={onViewJobs}
      />
      <SmokeLifecycleSection
        lifecycle={lifecycle}
        lifecycleCheck={lifecycleCheck}
        lifecycleError={lifecycleError}
        lifecycleHeading={lifecycleHeading}
        lifecycleErrorPanel={lifecycleErrorPanel}
        onRefreshLifecycle={onRefreshLifecycle}
        onViewJobs={onViewJobs}
      />
      <ScreeningPreparationSection
        lifecycle={lifecycle}
        screeningState={screeningState}
        screeningPreview={screeningPreview}
        screeningResult={screeningResult}
        screeningError={screeningError}
        screeningButton={screeningButton}
        screeningHeading={screeningHeading}
        screeningSuccess={screeningSuccess}
        screeningErrorPanel={screeningErrorPanel}
        onPreviewScreening={onPreviewScreening}
        onConfirmScreening={onConfirmScreening}
        onResetScreening={onResetScreening}
        onViewJobs={onViewJobs}
      />
    </>
  );
}

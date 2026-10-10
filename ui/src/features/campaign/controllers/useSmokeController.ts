import { useEffect, useRef, useState } from "react";
import {
  SmokeLifecycleApiError,
  SubmissionApiError,
  type ScreeningPreview,
  type ScreeningResult,
  type SmokeLifecycle,
  type SmokeLifecycleApi,
  type SmokeSubmissionPreview,
  type SmokeSubmissionResult,
  type SubmissionApi,
} from "../../../api/clients/smoke";
import type { ZeusSnapshot } from "../../../api/clients/zeus";
import { errorHasSemantic, requiresManualVerification } from "../../../api/errorSemantics";

export type SmokeSubmitState = "idle" | "previewing" | "review" | "submitting" | "submitted" | "unknown" | "terminal" | "error";
export type SmokeCheckState = "idle" | "checking" | "ready" | "error";
export type ScreeningPreparationState = "idle" | "previewing" | "review" | "preparing" | "success" | "terminal";
export type SmokeTerminalCode = "already_submitted" | "smoke_already_started" | "submission_record_invalid" | null;

export function useSmokeController({
  campaignId,
  snapshot,
  submissionApi,
  lifecycleApi,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  submissionApi: SubmissionApi;
  lifecycleApi: SmokeLifecycleApi;
}) {
  const [submissionState, setSubmissionState] = useState<SmokeSubmitState>("idle");
  const [submissionPreview, setSubmissionPreview] = useState<SmokeSubmissionPreview | null>(null);
  const [submissionResult, setSubmissionResult] = useState<SmokeSubmissionResult | null>(null);
  const [submissionError, setSubmissionError] = useState("");
  const [submissionTerminalCode, setSubmissionTerminalCode] = useState<SmokeTerminalCode>(null);
  const [lifecycle, setLifecycle] = useState<SmokeLifecycle | null>(null);
  const [lifecycleCheck, setLifecycleCheck] = useState<SmokeCheckState>("idle");
  const [lifecycleError, setLifecycleError] = useState("");
  const [evidenceFresh, setEvidenceFresh] = useState(false);
  const [preparationState, setPreparationState] = useState<ScreeningPreparationState>("idle");
  const [preparationPreview, setPreparationPreview] = useState<ScreeningPreview | null>(null);
  const [preparationResult, setPreparationResult] = useState<ScreeningResult | null>(null);
  const [preparationError, setPreparationError] = useState("");

  const generation = useRef(0);
  const submissionRequestActive = useRef(false);
  const submissionConfirmActive = useRef(false);
  const lifecycleEpoch = useRef(0);
  const lifecycleOwner = useRef<number | null>(null);
  const preparationRequestActive = useRef(false);
  const preparationConfirmActive = useRef(false);

  useEffect(() => {
    generation.current += 1;
    lifecycleEpoch.current += 1;
    submissionRequestActive.current = false;
    submissionConfirmActive.current = false;
    lifecycleOwner.current = null;
    preparationRequestActive.current = false;
    preparationConfirmActive.current = false;
    setSubmissionState("idle"); setSubmissionPreview(null); setSubmissionResult(null); setSubmissionError(""); setSubmissionTerminalCode(null);
    setLifecycle(null); setLifecycleCheck("idle"); setLifecycleError(""); setEvidenceFresh(false);
    setPreparationState("idle"); setPreparationPreview(null); setPreparationResult(null); setPreparationError("");
    return () => {
      generation.current += 1;
      lifecycleEpoch.current += 1;
      submissionRequestActive.current = false;
      submissionConfirmActive.current = false;
      lifecycleOwner.current = null;
      preparationRequestActive.current = false;
      preparationConfirmActive.current = false;
    };
  }, [submissionApi, lifecycleApi, campaignId, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  async function refreshLifecycleWithin(requestGeneration: number, preservePreparationError: boolean) {
    if (!snapshot) return;
    const requestEpoch = ++lifecycleEpoch.current;
    lifecycleOwner.current = requestEpoch;
    setLifecycleCheck("checking");
    setLifecycleError("");
    if (!preservePreparationError) setPreparationError("");
    try {
      const next = await lifecycleApi.status(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration || lifecycleEpoch.current !== requestEpoch) return;
      setLifecycle(next);
      setEvidenceFresh(true);
      setLifecycleCheck("ready");
    } catch (cause) {
      if (generation.current !== requestGeneration || lifecycleEpoch.current !== requestEpoch) return;
      setLifecycle(null);
      setEvidenceFresh(false);
      setLifecycleError(cause instanceof Error ? cause.message : "The smoke status check stopped safely.");
      setLifecycleCheck("error");
    } finally {
      if (lifecycleOwner.current === requestEpoch) lifecycleOwner.current = null;
    }
  }

  async function refreshLifecycle() {
    if (!snapshot || lifecycleOwner.current !== null || preparationRequestActive.current) return;
    if (preparationPreview) {
      setPreparationPreview(null);
      setPreparationError("");
      setPreparationState("idle");
    }
    const requestGeneration = generation.current;
    await refreshLifecycleWithin(requestGeneration, false);
  }

  async function previewSubmission() {
    if (!snapshot || submissionRequestActive.current) return;
    submissionRequestActive.current = true;
    const requestGeneration = generation.current;
    setSubmissionState("previewing"); setSubmissionError(""); setSubmissionTerminalCode(null);
    try {
      const next = await submissionApi.preview(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setSubmissionPreview(next); setSubmissionState("review");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      handleSubmissionError(cause);
    } finally {
      if (generation.current === requestGeneration) submissionRequestActive.current = false;
    }
  }

  function handleSubmissionError(cause: unknown) {
    if (cause instanceof SubmissionApiError && errorHasSemantic("smoke_submission", cause.code, "outcome_unknown")) {
      setSubmissionError("Submission outcome could not be verified. Do not submit again. Check Zeus jobs first.");
      setSubmissionState("unknown");
      return;
    }
    if (cause instanceof SubmissionApiError && errorHasSemantic("smoke_submission", cause.code, "manual_verification")) {
      const code = cause.code as Exclude<SmokeTerminalCode, null>;
      setSubmissionTerminalCode(code);
      setSubmissionError(code === "already_submitted" ? "This smoke stage already has a durable Zeus submission record. Do not submit it again." : code === "smoke_already_started" ? "Smoke outputs already exist on Zeus. Do not submit this stage again; inspect the jobs and campaign status." : cause.message);
      setSubmissionState("terminal");
      return;
    }
    const terminal = cause instanceof SubmissionApiError && requiresManualVerification("smoke_submission", cause.code);
    setSubmissionError(cause instanceof Error ? cause.message : "Smoke submission stopped safely.");
    setSubmissionState(terminal ? "terminal" : "error");
  }

  async function confirmSubmission() {
    if (!submissionPreview || submissionRequestActive.current) return;
    submissionRequestActive.current = true;
    submissionConfirmActive.current = true;
    const requestGeneration = generation.current;
    setSubmissionState("submitting"); setSubmissionError(""); setSubmissionTerminalCode(null);
    try {
      const next = await submissionApi.confirm(submissionPreview.preview_token);
      if (generation.current !== requestGeneration) return;
      setSubmissionResult(next); setSubmissionState("submitted");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      handleSubmissionError(cause);
    } finally {
      if (generation.current === requestGeneration) {
        submissionConfirmActive.current = false;
        submissionRequestActive.current = false;
      }
    }
  }

  function resetSubmission() {
    if (submissionRequestActive.current || submissionConfirmActive.current) return;
    setSubmissionError(""); setSubmissionPreview(null); setSubmissionTerminalCode(null); setSubmissionState("idle");
  }

  async function previewPreparation() {
    if (!snapshot || lifecycle?.lifecycle !== "ready_to_prepare_screen" || lifecycleOwner.current !== null || preparationRequestActive.current) return;
    preparationRequestActive.current = true;
    const requestGeneration = generation.current;
    setPreparationState("previewing"); setPreparationError("");
    try {
      const next = await lifecycleApi.preview(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setPreparationPreview(next); setPreparationState("review");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", cause.code, "already_prepared")) {
        setPreparationPreview(null); setPreparationState("idle");
        await refreshLifecycleWithin(requestGeneration, false);
        return;
      }
      const terminal = cause instanceof SmokeLifecycleApiError && requiresManualVerification("smoke_transition", cause.code);
      setPreparationError(cause instanceof Error ? cause.message : "Screening preparation review stopped safely.");
      setPreparationState(terminal ? "terminal" : "idle");
    } finally {
      if (generation.current === requestGeneration) preparationRequestActive.current = false;
    }
  }

  async function confirmPreparation() {
    if (!preparationPreview || lifecycleOwner.current !== null || preparationRequestActive.current) return;
    preparationRequestActive.current = true;
    preparationConfirmActive.current = true;
    const requestGeneration = generation.current;
    setPreparationState("preparing"); setPreparationError("");
    try {
      const next = await lifecycleApi.confirm(preparationPreview.preview_token);
      if (generation.current !== requestGeneration) return;
      lifecycleEpoch.current += 1;
      lifecycleOwner.current = null;
      setPreparationResult(next); setPreparationState("success"); setEvidenceFresh(false);
      setLifecycleCheck("ready");
      setLifecycle((current) => current ? { ...current, campaign: { ...current.campaign, stage: "screen" }, lifecycle: "screen_prepared", next_action: "none" } : current);
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", cause.code, "already_prepared")) {
        setPreparationPreview(null); setPreparationState("idle");
        await refreshLifecycleWithin(requestGeneration, false);
        return;
      }
      const fresh = cause instanceof SmokeLifecycleApiError && errorHasSemantic("smoke_transition", cause.code, "fresh_review");
      const terminal = !(cause instanceof SmokeLifecycleApiError) || requiresManualVerification("smoke_transition", cause.code);
      setPreparationError(cause instanceof Error ? cause.message : "Screening preparation stopped safely.");
      if (fresh) { setPreparationPreview(null); setPreparationState("idle"); }
      else if (terminal) { setPreparationPreview(null); setPreparationState("terminal"); }
      else setPreparationState("review");
    } finally {
      if (generation.current === requestGeneration) {
        preparationConfirmActive.current = false;
        preparationRequestActive.current = false;
      }
    }
  }

  function resetPreparation() {
    if (preparationRequestActive.current || preparationConfirmActive.current) return;
    setPreparationPreview(null); setPreparationError(""); setPreparationState("idle");
  }

  return {
    submission: { state: submissionState, preview: submissionPreview, result: submissionResult, error: submissionError, terminalCode: submissionTerminalCode, previewSubmission, confirmSubmission, reset: resetSubmission },
    lifecycle: { value: lifecycle, check: lifecycleCheck, error: lifecycleError, evidenceFresh, refresh: refreshLifecycle },
    screeningPreparation: { state: preparationState, preview: preparationPreview, result: preparationResult, error: preparationError, previewPreparation, confirmPreparation, reset: resetPreparation },
  };
}

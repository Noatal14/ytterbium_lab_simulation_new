import { useEffect, useRef, useState } from "react";
import {
  ScreeningLifecycleApiError,
  ScreeningSubmissionApiError,
  type RefinementPreview,
  type RefinementResult,
  type ScreeningLifecycle,
  type ScreeningLifecycleApi,
  type ScreeningSubmissionApi,
  type ScreeningSubmissionPreview,
  type ScreeningSubmissionResult,
} from "../../../api/clients/screening";
import type { SmokeLifecycle } from "../../../api/clients/smoke";
import type { ZeusSnapshot } from "../../../api/clients/zeus";
import { errorHasSemantic, requiresManualVerification } from "../../../api/errorSemantics";

export type ScreeningSubmitState = "idle" | "previewing" | "review" | "submitting" | "submitted" | "unknown" | "terminal" | "error";
export type ScreeningCheckState = "idle" | "checking" | "ready" | "error";
export type RefinementPreparationState = "idle" | "previewing" | "review" | "preparing" | "success" | "terminal";

const smokeAuthorityKey = (lifecycle: SmokeLifecycle | null, evidenceFresh: boolean) =>
  evidenceFresh && lifecycle
    ? [lifecycle.queried_at, lifecycle.campaign.stage, lifecycle.lifecycle, lifecycle.submission.job_id].join("|")
    : "unavailable";

export function useScreeningController({
  campaignId,
  snapshot,
  smokeLifecycle,
  smokeEvidenceFresh,
  submissionApi,
  lifecycleApi,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  smokeLifecycle: SmokeLifecycle | null;
  smokeEvidenceFresh: boolean;
  submissionApi: ScreeningSubmissionApi;
  lifecycleApi: ScreeningLifecycleApi;
}) {
  const [submissionState, setSubmissionState] = useState<ScreeningSubmitState>("idle");
  const [submissionPreview, setSubmissionPreview] = useState<ScreeningSubmissionPreview | null>(null);
  const [submissionResult, setSubmissionResult] = useState<ScreeningSubmissionResult | null>(null);
  const [submissionError, setSubmissionError] = useState("");
  const [lifecycle, setLifecycle] = useState<ScreeningLifecycle | null>(null);
  const [lifecycleCheck, setLifecycleCheck] = useState<ScreeningCheckState>("idle");
  const [lifecycleError, setLifecycleError] = useState("");
  const [preparationState, setPreparationState] = useState<RefinementPreparationState>("idle");
  const [preparationPreview, setPreparationPreview] = useState<RefinementPreview | null>(null);
  const [preparationResult, setPreparationResult] = useState<RefinementResult | null>(null);
  const [preparationError, setPreparationError] = useState("");

  const generation = useRef(0);
  const submissionActive = useRef(false);
  const submissionConfirmActive = useRef(false);
  const lifecycleEpoch = useRef(0);
  const lifecycleOwner = useRef<number | null>(null);
  const preparationActive = useRef(false);
  const preparationConfirmActive = useRef(false);
  const authorityKey = smokeAuthorityKey(smokeLifecycle, smokeEvidenceFresh);
  const authorityKeyRef = useRef(authorityKey);
  const authorityEpoch = useRef(0);
  const reviewedAuthorityKey = useRef<string | null>(null);
  const reviewedAuthorityEpoch = useRef<number | null>(null);

  if (authorityKeyRef.current !== authorityKey) {
    authorityKeyRef.current = authorityKey;
    authorityEpoch.current += 1;
  }

  useEffect(() => {
    generation.current += 1;
    lifecycleEpoch.current += 1;
    submissionActive.current = false;
    submissionConfirmActive.current = false;
    lifecycleOwner.current = null;
    preparationActive.current = false;
    preparationConfirmActive.current = false;
    setSubmissionState("idle"); setSubmissionPreview(null); setSubmissionResult(null); setSubmissionError("");
    setLifecycle(null); setLifecycleCheck("idle"); setLifecycleError("");
    setPreparationState("idle"); setPreparationPreview(null); setPreparationResult(null); setPreparationError("");
    return () => {
      generation.current += 1;
      lifecycleEpoch.current += 1;
      submissionActive.current = false;
      submissionConfirmActive.current = false;
      lifecycleOwner.current = null;
      preparationActive.current = false;
      preparationConfirmActive.current = false;
    };
  }, [submissionApi, lifecycleApi, campaignId, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  useEffect(() => {
    if (submissionConfirmActive.current) return;
    reviewedAuthorityKey.current = null;
    reviewedAuthorityEpoch.current = null;
    setSubmissionPreview(null);
    setSubmissionError("");
    setSubmissionState((current) => ["submitted", "unknown", "terminal"].includes(current) ? current : "idle");
  }, [authorityKey]);

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
      setLifecycleCheck("ready");
    } catch (cause) {
      if (generation.current !== requestGeneration || lifecycleEpoch.current !== requestEpoch) return;
      setLifecycle(null);
      setLifecycleError(cause instanceof Error ? cause.message : "The Screening status check stopped safely.");
      setLifecycleCheck("error");
    } finally {
      if (lifecycleOwner.current === requestEpoch) lifecycleOwner.current = null;
    }
  }

  async function refreshLifecycle() {
    if (!snapshot || lifecycleOwner.current !== null || preparationActive.current) return;
    if (preparationPreview) {
      setPreparationPreview(null);
      setPreparationError("");
      setPreparationState("idle");
    }
    await refreshLifecycleWithin(generation.current, false);
  }

  async function previewSubmission() {
    if (!snapshot || !smokeEvidenceFresh || smokeLifecycle?.lifecycle !== "screen_prepared" || submissionActive.current) return;
    submissionActive.current = true;
    const requestGeneration = generation.current;
    const requestAuthorityKey = authorityKeyRef.current;
    const requestAuthorityEpoch = authorityEpoch.current;
    setSubmissionState("previewing"); setSubmissionError("");
    try {
      const next = await submissionApi.preview(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration
        || authorityKeyRef.current !== requestAuthorityKey
        || authorityEpoch.current !== requestAuthorityEpoch
        || !smokeEvidenceFresh
        || smokeLifecycle?.lifecycle !== "screen_prepared") return;
      reviewedAuthorityKey.current = requestAuthorityKey;
      reviewedAuthorityEpoch.current = requestAuthorityEpoch;
      setSubmissionPreview(next); setSubmissionState("review");
    } catch (cause) {
      if (generation.current !== requestGeneration
        || authorityKeyRef.current !== requestAuthorityKey
        || authorityEpoch.current !== requestAuthorityEpoch
        || !smokeEvidenceFresh
        || smokeLifecycle?.lifecycle !== "screen_prepared") return;
      setSubmissionError(cause instanceof Error ? cause.message : "Screening submission review stopped safely.");
      const terminal = cause instanceof ScreeningSubmissionApiError && requiresManualVerification("screen_submission", cause.code);
      setSubmissionState(terminal ? "terminal" : "error");
    } finally {
      if (generation.current === requestGeneration) submissionActive.current = false;
    }
  }

  async function confirmSubmission() {
    if (!submissionPreview
      || submissionActive.current
      || !smokeEvidenceFresh
      || smokeLifecycle?.lifecycle !== "screen_prepared"
      || reviewedAuthorityKey.current !== authorityKeyRef.current
      || reviewedAuthorityEpoch.current !== authorityEpoch.current) return;
    submissionActive.current = true;
    submissionConfirmActive.current = true;
    const requestGeneration = generation.current;
    setSubmissionState("submitting"); setSubmissionError("");
    try {
      const next = await submissionApi.confirm(submissionPreview.preview_token);
      if (generation.current !== requestGeneration) return;
      setSubmissionResult(next); setSubmissionState("submitted");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      const code = cause instanceof ScreeningSubmissionApiError ? cause.code : "";
      const fresh = errorHasSemantic("screen_submission", code, "fresh_review");
      const unknown = errorHasSemantic("screen_submission", code, "outcome_unknown");
      const terminal = !(cause instanceof ScreeningSubmissionApiError) || requiresManualVerification("screen_submission", code);
      setSubmissionError(fresh ? (code === "local_files_changed" ? "The campaign files changed after review. Start a fresh review before submitting." : "The review expired or is no longer valid. Start a fresh review before submitting.") : unknown ? "The submission outcome could not be verified. Do not submit again; inspect Zeus jobs." : cause instanceof Error ? cause.message : "Screening submission stopped safely.");
      if (fresh) { reviewedAuthorityKey.current = null; reviewedAuthorityEpoch.current = null; setSubmissionPreview(null); setSubmissionState("error"); }
      else if (unknown) { reviewedAuthorityKey.current = null; reviewedAuthorityEpoch.current = null; setSubmissionPreview(null); setSubmissionState("unknown"); }
      else if (terminal) { reviewedAuthorityKey.current = null; reviewedAuthorityEpoch.current = null; setSubmissionPreview(null); setSubmissionState("terminal"); }
      else {
        reviewedAuthorityKey.current = null;
        reviewedAuthorityEpoch.current = null;
        setSubmissionPreview(null);
        setSubmissionState("error");
      }
    } finally {
      if (generation.current === requestGeneration) {
        submissionConfirmActive.current = false;
        submissionActive.current = false;
      }
    }
  }

  function resetSubmission() {
    if (submissionActive.current || submissionConfirmActive.current) return;
    reviewedAuthorityKey.current = null;
    reviewedAuthorityEpoch.current = null;
    setSubmissionError(""); setSubmissionPreview(null); setSubmissionState("idle");
  }

  async function previewPreparation() {
    if (!snapshot || lifecycle?.lifecycle !== "ready_to_prepare_refinement" || lifecycleOwner.current !== null || preparationActive.current) return;
    preparationActive.current = true;
    const requestGeneration = generation.current;
    setPreparationState("previewing"); setPreparationError("");
    try {
      const next = await lifecycleApi.preview(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setPreparationPreview(next); setPreparationState("review");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", cause.code, "already_prepared")) {
        setPreparationPreview(null); setPreparationState("idle");
        await refreshLifecycleWithin(requestGeneration, false);
        return;
      }
      const terminal = cause instanceof ScreeningLifecycleApiError && requiresManualVerification("refinement_transition", cause.code);
      setPreparationError(cause instanceof Error ? cause.message : "Refinement preparation review stopped safely.");
      setPreparationState(terminal ? "terminal" : "idle");
    } finally {
      if (generation.current === requestGeneration) preparationActive.current = false;
    }
  }

  async function confirmPreparation() {
    if (!preparationPreview || lifecycleOwner.current !== null || preparationActive.current) return;
    preparationActive.current = true;
    preparationConfirmActive.current = true;
    const requestGeneration = generation.current;
    setPreparationState("preparing"); setPreparationError("");
    try {
      const next = await lifecycleApi.confirm(preparationPreview.preview_token);
      if (generation.current !== requestGeneration) return;
      lifecycleEpoch.current += 1;
      lifecycleOwner.current = null;
      setPreparationResult(next); setPreparationState("success"); setLifecycleCheck("ready");
      setLifecycle((current) => current ? { ...current, campaign: { ...current.campaign, stage: "refine" }, lifecycle: "refinement_prepared", next_action: "none" } : current);
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", cause.code, "already_prepared")) {
        setPreparationPreview(null); setPreparationState("idle");
        await refreshLifecycleWithin(requestGeneration, false);
        return;
      }
      const fresh = cause instanceof ScreeningLifecycleApiError && errorHasSemantic("refinement_transition", cause.code, "fresh_review");
      const terminal = !(cause instanceof ScreeningLifecycleApiError) || requiresManualVerification("refinement_transition", cause.code);
      setPreparationError(cause instanceof Error ? cause.message : "Refinement preparation stopped safely.");
      if (fresh) { setPreparationPreview(null); setPreparationState("idle"); }
      else if (terminal) { setPreparationPreview(null); setPreparationState("terminal"); }
      else setPreparationState("review");
    } finally {
      if (generation.current === requestGeneration) {
        preparationConfirmActive.current = false;
        preparationActive.current = false;
      }
    }
  }

  function resetPreparation() {
    if (preparationActive.current || preparationConfirmActive.current) return;
    setPreparationError(""); setPreparationPreview(null); setPreparationState("idle");
  }

  return {
    submission: { state: submissionState, preview: submissionPreview, result: submissionResult, error: submissionError, previewSubmission, confirmSubmission, reset: resetSubmission },
    lifecycle: { value: lifecycle, check: lifecycleCheck, error: lifecycleError, refresh: refreshLifecycle },
    refinementPreparation: { state: preparationState, preview: preparationPreview, result: preparationResult, error: preparationError, previewPreparation, confirmPreparation, reset: resetPreparation },
  };
}

import { useEffect, useRef, useState } from "react";
import { type ConfirmationSubmissionApi } from "../../../api/clients/refinement";
import { ConfirmationSubmissionApiError } from "../../../api/http/errors";
import type {
  ConfirmationSubmissionPreview,
  ConfirmationSubmissionResult,
  ConfirmationSubmissionStatus,
} from "../../../api/schema/domain";
import type { ZeusSnapshot } from "../../../api/clients/zeus";
import { requiresManualVerification } from "../../../api/errorSemantics";

export type ConfirmationSubmissionUiState =
  "idle" | "checking" | "review" | "submitting" | "submitted" | "terminal";
export function useConfirmationSubmissionController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: ConfirmationSubmissionApi;
}) {
  const [state, setState] = useState<ConfirmationSubmissionUiState>("idle"),
    [status, setStatus] = useState<ConfirmationSubmissionStatus | null>(null),
    [preview, setPreview] = useState<ConfirmationSubmissionPreview | null>(
      null,
    ),
    [result, setResult] = useState<ConfirmationSubmissionResult | null>(null),
    [error, setError] = useState("");
  const generation = useRef(0),
    active = useRef(false);
  useEffect(() => {
    generation.current += 1;
    active.current = false;
    api.reset?.();
    setState("idle");
    setStatus(null);
    setPreview(null);
    setResult(null);
    setError("");
    return () => {
      generation.current += 1;
      active.current = false;
    };
  }, [
    api,
    campaignId,
    enabled,
    snapshot?.profile.host,
    snapshot?.profile.username,
    snapshot?.profile.project_directory,
    snapshot?.profile.authentication,
  ]);
  async function refresh() {
    if (!snapshot || !enabled || active.current) return;
    active.current = true;
    const g = generation.current;
    setState("checking");
    setError("");
    try {
      const value = await api.status(campaignId, snapshot.profile);
      if (generation.current !== g) return;
      setStatus(value);
      const tracked = ["queued", "running", "completed_success"].includes(
        value.submission.status,
      );
      const manual = [
        "outcome_unknown",
        "held",
        "completed_failed",
        "status_unknown",
      ].includes(value.submission.status);
      setState(tracked ? "submitted" : manual ? "terminal" : "idle");
      if (manual)
        setError(
          "Confirmation requires manual Zeus verification. Do not submit again; inspect the tracked job.",
        );
    } catch (cause) {
      if (generation.current !== g) return;
      setState("idle");
      setError(
        cause instanceof Error
          ? cause.message
          : "Confirmation status could not be checked safely.",
      );
    } finally {
      if (generation.current === g) active.current = false;
    }
  }
  async function review() {
    if (!snapshot || !enabled || active.current) return;
    active.current = true;
    const g = generation.current;
    setState("checking");
    setError("");
    try {
      const value = await api.preview(campaignId, snapshot.profile);
      if (generation.current !== g) return;
      setPreview(value);
      setState("review");
    } catch (cause) {
      if (generation.current !== g) return;
      const terminal =
        cause instanceof ConfirmationSubmissionApiError &&
        requiresManualVerification("confirmation_submission", cause.code);
      setError(
        cause instanceof Error
          ? cause.message
          : "Confirmation submission review stopped safely.",
      );
      setState(terminal ? "terminal" : "idle");
    } finally {
      if (generation.current === g) active.current = false;
    }
  }
  async function confirm() {
    if (!preview || active.current) return;
    active.current = true;
    const g = generation.current;
    setState("submitting");
    setError("");
    try {
      const value = await api.confirm(preview.preview_token);
      if (generation.current !== g) return;
      setResult(value);
      setPreview(null);
      setState("submitted");
    } catch (cause) {
      if (generation.current !== g) return;
      setPreview(null);
      setError(
        cause instanceof Error
          ? cause.message
          : "The Confirmation submission outcome could not be verified. Do not retry automatically.",
      );
      setState("terminal");
    } finally {
      if (generation.current === g) active.current = false;
    }
  }
  function reset() {
    generation.current += 1;
    active.current = false;
    api.reset?.();
    setPreview(null);
    setError("");
    setState("idle");
  }
  return {
    state,
    status,
    preview,
    result,
    error,
    refresh,
    review,
    confirm,
    reset,
  };
}

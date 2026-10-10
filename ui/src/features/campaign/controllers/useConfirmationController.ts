import { useState } from "react";
import { RefinementLifecycleApiError, type ConfirmationPreview, type ConfirmationResult, type RefinementLifecycle, type RefinementLifecycleApi } from "../../../api/clients/refinement";
import type { ZeusSnapshot } from "../../../api/clients/zeus";
import { errorHasSemantic, requiresManualVerification } from "../../../api/errorSemantics";

export type ConfirmationUiState = "idle" | "previewing" | "review" | "preparing" | "success" | "terminal";
export type ConfirmationLifecycleCheck = "idle" | "checking" | "ready" | "error";

export function useConfirmationController({ campaignId, snapshot, api }: { campaignId: string; snapshot: ZeusSnapshot | null; api: RefinementLifecycleApi }) {
  const [lifecycle, setLifecycle] = useState<RefinementLifecycle | null>(null);
  const [lifecycleCheck, setLifecycleCheck] = useState<ConfirmationLifecycleCheck>("idle");
  const [state, setState] = useState<ConfirmationUiState>("idle");
  const [preview, setPreview] = useState<ConfirmationPreview | null>(null);
  const [result, setResult] = useState<ConfirmationResult | null>(null);
  const [error, setError] = useState("");

  async function refresh(preserveError = false) {
    if (!snapshot || lifecycleCheck === "checking") return;
    setLifecycleCheck("checking");
    if (!preserveError) setError("");
    try {
      const next = await api.status(campaignId, snapshot.profile);
      setLifecycle(next);
      setLifecycleCheck("ready");
      if (next.chain.status === "confirmation_prepared") setState("success");
    } catch (cause) {
      setLifecycle(null);
      if (!preserveError) setError(cause instanceof Error ? cause.message : "The Refinement status check stopped safely.");
      setLifecycleCheck("error");
    }
  }

  async function previewConfirmation() {
    if (!snapshot || lifecycle?.chain.status !== "ready_to_prepare_confirmation") return;
    setState("previewing");
    setError("");
    try {
      setPreview(await api.preview(campaignId, snapshot.profile));
      setState("review");
    } catch (cause) {
      if (cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "already_prepared")) {
        setPreview(null);
        setState("idle");
        await refresh();
        return;
      }
      const terminal = cause instanceof RefinementLifecycleApiError && requiresManualVerification("confirmation_transition", cause.code);
      setError(cause instanceof Error ? cause.message : "Confirmation preparation review stopped safely.");
      setState(terminal ? "terminal" : "idle");
    }
  }

  async function confirmConfirmation() {
    if (!preview) return;
    setState("preparing");
    setError("");
    try {
      setResult(await api.confirm(preview.preview_token));
      setState("success");
      setLifecycle((current) => current ? { ...current, campaign: { ...current.campaign, stage: "confirmation" }, chain: { ...current.chain, status: "confirmation_prepared" }, next_action: "none" } : current);
    } catch (cause) {
      if (cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "already_prepared")) {
        setPreview(null);
        setState("idle");
        await refresh();
        return;
      }
      const fresh = cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "fresh_review");
      setError(cause instanceof Error ? cause.message : "The Confirmation preparation outcome could not be verified. Do not retry automatically.");
      setPreview(null);
      setState(fresh ? "idle" : "terminal");
      if (!fresh) await refresh(true);
    }
  }

  function reset() {
    setError("");
    setPreview(null);
    setState("idle");
  }

  return { lifecycle, lifecycleCheck, state, preview, result, error, refresh, previewConfirmation, confirmConfirmation, reset };
}

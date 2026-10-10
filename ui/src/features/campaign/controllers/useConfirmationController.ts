import { useEffect, useRef, useState } from "react";
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
  const generation = useRef(0);
  const requestActive = useRef(false);

  useEffect(() => {
    generation.current += 1;
    requestActive.current = false;
    setLifecycle(null);
    setLifecycleCheck("idle");
    setState("idle");
    setPreview(null);
    setResult(null);
    setError("");
    return () => { generation.current += 1; requestActive.current = false; };
  }, [api, campaignId, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  async function refreshWithin(requestGeneration: number, preserveError: boolean) {
    if (!snapshot) return;
    setLifecycleCheck("checking");
    if (!preserveError) setError("");
    try {
      const next = await api.status(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setLifecycle(next);
      setLifecycleCheck("ready");
      if (next.chain.status === "confirmation_prepared") setState("success");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      setLifecycle(null);
      if (!preserveError) setError(cause instanceof Error ? cause.message : "The Refinement status check stopped safely.");
      setLifecycleCheck("error");
    }
  }

  async function refresh() {
    if (!snapshot || requestActive.current) return;
    requestActive.current = true;
    const requestGeneration = generation.current;
    try { await refreshWithin(requestGeneration, false); }
    finally { if (generation.current === requestGeneration) requestActive.current = false; }
  }

  async function previewConfirmation() {
    if (!snapshot || lifecycle?.chain.status !== "ready_to_prepare_confirmation" || requestActive.current) return;
    requestActive.current = true;
    const requestGeneration = generation.current;
    setState("previewing");
    setError("");
    try {
      const nextPreview = await api.preview(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setPreview(nextPreview);
      setState("review");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "already_prepared")) {
        setPreview(null);
        setState("idle");
        await refreshWithin(requestGeneration, false);
        return;
      }
      const terminal = cause instanceof RefinementLifecycleApiError && requiresManualVerification("confirmation_transition", cause.code);
      setError(cause instanceof Error ? cause.message : "Confirmation preparation review stopped safely.");
      setState(terminal ? "terminal" : "idle");
    } finally {
      if (generation.current === requestGeneration) requestActive.current = false;
    }
  }

  async function confirmConfirmation() {
    if (!preview || requestActive.current) return;
    requestActive.current = true;
    const requestGeneration = generation.current;
    setState("preparing");
    setError("");
    try {
      const nextResult = await api.confirm(preview.preview_token);
      if (generation.current !== requestGeneration) return;
      setResult(nextResult);
      setState("success");
      setLifecycle((current) => current ? { ...current, campaign: { ...current.campaign, stage: "confirmation" }, chain: { ...current.chain, status: "confirmation_prepared" }, next_action: "none" } : current);
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      if (cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "already_prepared")) {
        setPreview(null);
        setState("idle");
        await refreshWithin(requestGeneration, false);
        return;
      }
      const fresh = cause instanceof RefinementLifecycleApiError && errorHasSemantic("confirmation_transition", cause.code, "fresh_review");
      setError(cause instanceof Error ? cause.message : "The Confirmation preparation outcome could not be verified. Do not retry automatically.");
      setPreview(null);
      setState(fresh ? "idle" : "terminal");
      if (!fresh) await refreshWithin(requestGeneration, true);
    } finally {
      if (generation.current === requestGeneration) requestActive.current = false;
    }
  }

  function reset() {
    generation.current += 1;
    requestActive.current = false;
    setError("");
    setPreview(null);
    setState("idle");
  }

  return { lifecycle, lifecycleCheck, state, preview, result, error, refresh, previewConfirmation, confirmConfirmation, reset };
}

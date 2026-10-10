import { useEffect, useRef, useState } from "react";
import { RefinementSubmissionApiError, type RefinementChainStatus, type RefinementSubmissionApi, type RefinementSubmissionPreview, type RefinementSubmissionResult } from "../../../api/clients/refinement";
import type { ZeusSnapshot } from "../../../api/clients/zeus";
import { errorHasSemantic, requiresManualVerification } from "../../../api/errorSemantics";

export type ChainUiState = "idle" | "previewing" | "review" | "submitting" | "submitted" | "blocked" | "error";
export type ChainLifecycleCheck = "idle" | "checking" | "ready" | "error";

export function useRefinementController({ campaignId, snapshot, api }: { campaignId: string; snapshot: ZeusSnapshot | null; api: RefinementSubmissionApi }) {
  const [status, setStatus] = useState<RefinementChainStatus | null>(null);
  const [check, setCheck] = useState<ChainLifecycleCheck>("idle");
  const [state, setState] = useState<ChainUiState>("idle");
  const [preview, setPreview] = useState<RefinementSubmissionPreview | null>(null);
  const [result, setResult] = useState<RefinementSubmissionResult | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const requestActive = useRef(false);
  const submissionActive = useRef(false);
  const pollActive = useRef(false);
  const pollEpoch = useRef(0);
  const pollTimer = useRef<number | null>(null);

  function stopPolling() {
    pollEpoch.current += 1;
    pollActive.current = false;
    if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    pollTimer.current = null;
  }

  useEffect(() => {
    generation.current += 1;
    requestActive.current = false;
    submissionActive.current = false;
    stopPolling();
    setStatus(null); setCheck("idle"); setState("idle"); setPreview(null); setResult(null); setError("");
    return () => { generation.current += 1; requestActive.current = false; submissionActive.current = false; stopPolling(); };
  }, [api, campaignId, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  async function refreshWithin(requestGeneration: number, preserveError: boolean) {
    if (!snapshot) return;
    setCheck("checking");
    if (!preserveError) setError("");
    try {
      const next = await api.status(campaignId, snapshot.profile);
      if (generation.current !== requestGeneration) return;
      setStatus(next); setCheck("ready");
      if (["partial", "outcome_unknown"].includes(next.chain.status)) setState("blocked");
      else if (next.chain.status === "submitted") setState("submitted");
      else setState(preserveError ? "blocked" : "idle");
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      setStatus(null);
      setState(preserveError ? "blocked" : "idle");
      if (!preserveError) setError(cause instanceof Error ? cause.message : "The Refinement chain status check stopped safely.");
      setCheck("error");
    }
  }

  async function refresh() {
    if (!snapshot || requestActive.current) return;
    requestActive.current = true;
    const requestGeneration = generation.current;
    try { await refreshWithin(requestGeneration, false); }
    finally { if (generation.current === requestGeneration) requestActive.current = false; }
  }

  async function previewSubmission() {
    if (!snapshot || status?.chain.status !== "not_submitted" || requestActive.current) return;
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
      const code = cause instanceof RefinementSubmissionApiError ? cause.code : "";
      const blocked = cause instanceof RefinementSubmissionApiError && requiresManualVerification("refinement_submission", code);
      setError(cause instanceof Error ? cause.message : "Refinement chain review stopped safely.");
      setState(blocked ? "blocked" : "error");
      if (blocked) await refreshWithin(requestGeneration, true);
    } finally {
      if (generation.current === requestGeneration) requestActive.current = false;
    }
  }

  async function confirmSubmission() {
    if (!snapshot || !preview || requestActive.current) return;
    requestActive.current = true;
    submissionActive.current = true;
    const requestGeneration = generation.current;
    setState("submitting");
    setError("");
    const activePollEpoch = ++pollEpoch.current;
    pollTimer.current = window.setInterval(() => {
      if (pollActive.current || generation.current !== requestGeneration || pollEpoch.current !== activePollEpoch) return;
      pollActive.current = true;
      void api.status(campaignId, snapshot.profile).then((next) => {
        if (generation.current === requestGeneration && pollEpoch.current === activePollEpoch) setStatus(next);
      }).catch(() => undefined).finally(() => {
        if (generation.current === requestGeneration && pollEpoch.current === activePollEpoch) pollActive.current = false;
      });
    }, 1000);
    try {
      const next = await api.confirm(preview.preview_token);
      if (generation.current !== requestGeneration) return;
      stopPolling();
      setResult(next);
      setState("submitted");
      setStatus({ source: "zeus", queried_at: next.submitted_at, campaign: { id: next.campaign_id, name: preview.campaign.name, stage: "refine" }, chain: { status: "submitted", dependency: "afterok", rounds: next.chain.rounds.map((row) => ({ ...row, state: "submitted" })) }, next_action: "none", local_sync: { status: "not_synchronized" } });
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      stopPolling();
      const code = cause instanceof RefinementSubmissionApiError ? cause.code : "";
      if (errorHasSemantic("refinement_submission", code, "fresh_review")) {
        setPreview(null);
        setError(code === "local_files_changed" ? "The remote files changed after review. Start a fresh review." : "The review expired or is no longer valid. Start a fresh review.");
        setState("error");
      } else {
        setError(cause instanceof Error ? cause.message : "The Refinement chain outcome needs manual verification.");
        setState("blocked");
        await refreshWithin(requestGeneration, true);
      }
    } finally {
      if (generation.current === requestGeneration) {
        stopPolling();
        submissionActive.current = false;
        requestActive.current = false;
      }
    }
  }

  function reset() {
    if (submissionActive.current) return;
    generation.current += 1;
    requestActive.current = false;
    stopPolling();
    setError("");
    setPreview(null);
    setCheck(status ? "ready" : "idle");
    setState("idle");
  }

  return { status, check, state, preview, result, error, refresh, previewSubmission, confirmSubmission, reset };
}

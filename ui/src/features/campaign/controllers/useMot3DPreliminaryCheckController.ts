import { useEffect, useRef, useState } from "react";
import type { PreliminaryCheckApi, PreliminaryCheckPreview, PreliminaryCheckResult, PreliminaryCheckStatus } from "../../../api/clients/mot3dPreliminaryCheck";
import type { ZeusSnapshot } from "../../../api/schema/domain";

export type PreliminaryCheckUiState = "idle" | "checking" | "review" | "submitting" | "tracked" | "terminal";
export function useMot3DPreliminaryCheckController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: PreliminaryCheckApi }) {
  const [state, setState] = useState<PreliminaryCheckUiState>("idle"); const [status, setStatus] = useState<PreliminaryCheckStatus | null>(null); const [preview, setPreview] = useState<PreliminaryCheckPreview | null>(null); const [result, setResult] = useState<PreliminaryCheckResult | null>(null); const [error, setError] = useState(""); const [errorPhase, setErrorPhase] = useState<"inspect" | "submit" | null>(null); const generation = useRef(0); const busy = useRef(false);
  useEffect(() => { generation.current += 1; busy.current = false; api.reset(); setState("idle"); setStatus(null); setPreview(null); setResult(null); setError(""); setErrorPhase(null); return () => { generation.current += 1; busy.current = false; }; }, [api, campaignId, enabled, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);
  const stateFor = (value: PreliminaryCheckStatus): PreliminaryCheckUiState => value.next_action === "inspect_zeus" ? "terminal" : value.submission.status === "not_submitted" ? "idle" : "tracked";
  async function run(kind: "status" | "preview" | "confirm") {
    if (!enabled || !snapshot || busy.current || (kind === "preview" && status?.next_action !== "review_submission" && status !== null) || (kind === "confirm" && !preview)) return;
    busy.current = true; const current = generation.current; setState(kind === "confirm" ? "submitting" : "checking"); setError(""); setErrorPhase(null);
    try { if (kind === "status") { const value = await api.status(campaignId, snapshot.profile); if (generation.current !== current) return; setStatus(value); setState(stateFor(value)); } else if (kind === "preview") { const value = await api.preview(campaignId, snapshot.profile); if (generation.current !== current) return; setPreview(value); setState("review"); } else { const value = await api.confirm(preview!.preview_token); if (generation.current !== current) return; setResult(value); setStatus(null); setPreview(null); setState("tracked"); } } catch (cause) { if (generation.current !== current) return; setPreview(null); setError(cause instanceof Error ? cause.message : "Preliminary-check submission could not be verified."); setErrorPhase(kind === "confirm" ? "submit" : "inspect"); setState(kind !== "preview" ? "terminal" : status ? stateFor(status) : "idle"); } finally { if (generation.current === current) busy.current = false; }
  }
  function reset() { generation.current += 1; busy.current = false; api.reset(); setPreview(null); setError(""); setErrorPhase(null); setState(status ? stateFor(status) : "idle"); }
  return { state, status, preview, result, error, errorPhase, refresh: () => run("status"), review: () => run("preview"), confirm: () => run("confirm"), reset };
}

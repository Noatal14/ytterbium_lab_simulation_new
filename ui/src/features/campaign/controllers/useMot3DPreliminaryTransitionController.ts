import { useEffect, useRef, useState } from "react";
import type { Mot3DPreliminaryTransitionApi, Mot3DPreliminaryTransitionPreview, Mot3DPreliminaryTransitionResult, Mot3DPreliminaryTransitionStatus } from "../../../api/clients/mot3dPreliminaryTransition";
import type { ZeusSnapshot } from "../../../api/schema/domain";

export type Mot3DPreliminaryTransitionUiState = "idle" | "checking" | "ready" | "review" | "synchronizing" | "prepared" | "terminal";

export function useMot3DPreliminaryTransitionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DPreliminaryTransitionApi }) {
  const [state, setState] = useState<Mot3DPreliminaryTransitionUiState>("idle");
  const [status, setStatus] = useState<Mot3DPreliminaryTransitionStatus | null>(null);
  const [preview, setPreview] = useState<Mot3DPreliminaryTransitionPreview | null>(null);
  const [result, setResult] = useState<Mot3DPreliminaryTransitionResult | null>(null);
  const [error, setError] = useState("");
  const [errorPhase, setErrorPhase] = useState<"inspect" | "confirm" | null>(null);
  const generation = useRef(0); const busy = useRef(false);
  useEffect(() => { generation.current += 1; busy.current = false; api.reset(); setState("idle"); setStatus(null); setPreview(null); setResult(null); setError(""); setErrorPhase(null); return () => { generation.current += 1; busy.current = false; }; }, [api, campaignId, enabled, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);
  const stateFor = (value: Mot3DPreliminaryTransitionStatus): Mot3DPreliminaryTransitionUiState => value.next_action === "review_transition" || value.next_action === "synchronize_results" ? "ready" : value.next_action === "open_refinement" ? "prepared" : value.next_action === "inspect_zeus" ? "terminal" : "idle";
  async function run(kind: "status" | "preview" | "confirm") {
    if (!enabled || !snapshot || busy.current || (kind === "preview" && !["review_transition", "synchronize_results"].includes(status?.next_action ?? "")) || (kind === "confirm" && !preview)) return;
    busy.current = true; const current = generation.current; setState(kind === "confirm" ? "synchronizing" : "checking"); setError(""); setErrorPhase(null);
    try {
      if (kind === "status") { const value = await api.status(campaignId, snapshot.profile); if (generation.current !== current) return; setStatus(value); setState(stateFor(value)); }
      else if (kind === "preview") { const value = await api.preview(campaignId, snapshot.profile); if (generation.current !== current) return; setPreview(value); setState("review"); }
      else { const value = await api.confirm(preview!.preview_token); if (generation.current !== current) return; setResult(value); setPreview(null); setState("prepared"); }
    } catch (cause) { if (generation.current !== current) return; setPreview(null); setError(cause instanceof Error ? cause.message : "Preliminary-check synchronization stopped safely."); setErrorPhase(kind === "confirm" ? "confirm" : "inspect"); setState(kind === "confirm" ? "terminal" : status ? stateFor(status) : "idle"); }
    finally { if (generation.current === current) busy.current = false; }
  }
  function reset() { generation.current += 1; busy.current = false; api.reset(); setPreview(null); setError(""); setErrorPhase(null); setState(status ? stateFor(status) : "idle"); }
  return { state, status, preview, result, error, errorPhase, refresh: () => run("status"), review: () => run("preview"), confirm: () => run("confirm"), reset };
}

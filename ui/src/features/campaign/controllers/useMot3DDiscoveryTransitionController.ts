import { useEffect, useRef, useState } from "react";
import type { Mot3DDiscoveryTransitionApi, Mot3DDiscoveryTransitionPreview, Mot3DDiscoveryTransitionResult, Mot3DDiscoveryTransitionStatus } from "../../../api/clients/mot3dDiscoveryTransition";
import type { ZeusSnapshot } from "../../../api/schema/domain";

export type Mot3DDiscoveryTransitionUiState = "idle" | "checking" | "ready" | "review" | "synchronizing" | "prepared" | "terminal";

export function useMot3DDiscoveryTransitionController({ campaignId, snapshot, enabled, api }: { campaignId: string; snapshot: ZeusSnapshot | null; enabled: boolean; api: Mot3DDiscoveryTransitionApi }) {
  const [state, setState] = useState<Mot3DDiscoveryTransitionUiState>("idle");
  const [status, setStatus] = useState<Mot3DDiscoveryTransitionStatus | null>(null);
  const [preview, setPreview] = useState<Mot3DDiscoveryTransitionPreview | null>(null);
  const [result, setResult] = useState<Mot3DDiscoveryTransitionResult | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const busy = useRef(false);

  useEffect(() => {
    generation.current += 1; busy.current = false; api.reset();
    setState("idle"); setStatus(null); setPreview(null); setResult(null); setError("");
    return () => { generation.current += 1; busy.current = false; };
  }, [api, campaignId, enabled, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  const stateFor = (value: Mot3DDiscoveryTransitionStatus): Mot3DDiscoveryTransitionUiState =>
    value.next_action === "review_transition" ? "ready" : value.discovery.status === "preliminary_check_prepared" ? "prepared" : ["held", "completed_failed", "outputs_invalid", "status_unknown"].includes(value.discovery.status) || value.validation.status === "invalid" ? "terminal" : "idle";

  async function run(kind: "status" | "preview" | "confirm") {
    if (!enabled || !snapshot || busy.current || (kind === "preview" && status?.next_action !== "review_transition") || (kind === "confirm" && !preview)) return;
    busy.current = true;
    const current = generation.current;
    setState(kind === "confirm" ? "synchronizing" : "checking"); setError("");
    try {
      if (kind === "status") {
        const value = await api.status(campaignId, snapshot.profile);
        if (generation.current !== current) return;
        setStatus(value); setState(stateFor(value));
      } else if (kind === "preview") {
        const value = await api.preview(campaignId, snapshot.profile);
        if (generation.current !== current) return;
        setPreview(value); setState("review");
      } else {
        const value = await api.confirm(preview!.preview_token);
        if (generation.current !== current) return;
        setResult(value); setPreview(null); setState("prepared");
      }
    } catch (cause) {
      if (generation.current !== current) return;
      setPreview(null); setError(cause instanceof Error ? cause.message : "Discovery synchronization stopped safely.");
      setState(kind === "confirm" ? "terminal" : status ? stateFor(status) : "idle");
    } finally { if (generation.current === current) busy.current = false; }
  }
  function reset() { generation.current += 1; busy.current = false; api.reset(); setPreview(null); setError(""); setState(status ? stateFor(status) : "idle"); }
  return { state, status, preview, result, error, refresh: () => run("status"), review: () => run("preview"), confirm: () => run("confirm"), reset };
}

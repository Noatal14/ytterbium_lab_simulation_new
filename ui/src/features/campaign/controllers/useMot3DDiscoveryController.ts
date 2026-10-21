import { useEffect, useRef, useState } from "react";
import type {
  Mot3DDiscoveryApi,
  Mot3DDiscoveryPreview,
  Mot3DDiscoveryResult,
  Mot3DDiscoveryStatus,
} from "../../../api/clients/mot3dDiscovery";
import type { ZeusSnapshot } from "../../../api/schema/domain";

export type Mot3DDiscoveryUiState =
  "idle" | "checking" | "review" | "submitting" | "submitted" | "terminal";

export function useMot3DDiscoveryController({
  campaignId,
  snapshot,
  enabled,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: Mot3DDiscoveryApi;
}) {
  const [state, setState] = useState<Mot3DDiscoveryUiState>("idle");
  const [status, setStatus] = useState<Mot3DDiscoveryStatus | null>(null);
  const [preview, setPreview] = useState<Mot3DDiscoveryPreview | null>(null);
  const [result, setResult] = useState<Mot3DDiscoveryResult | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const busy = useRef(false);

  useEffect(() => {
    generation.current += 1;
    busy.current = false;
    api.reset();
    setState("idle");
    setStatus(null);
    setPreview(null);
    setResult(null);
    setError("");
    return () => {
      generation.current += 1;
      busy.current = false;
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

  async function run(kind: "status" | "preview" | "confirm") {
    if (
      !enabled ||
      !snapshot ||
      busy.current ||
      (kind === "confirm" && !preview)
    )
      return;
    busy.current = true;
    const current = generation.current;
    setState(kind === "confirm" ? "submitting" : "checking");
    setError("");
    try {
      if (kind === "status") {
        const value = await api.status(campaignId, snapshot.profile);
        if (generation.current !== current) return;
        setStatus(value);
        setState(
          [
            "held",
            "completed_failed",
            "status_unknown",
            "outcome_unknown",
          ].includes(value.submission.status)
            ? "terminal"
            : value.submission.status === "not_submitted"
              ? "idle"
              : "submitted",
        );
      } else if (kind === "preview") {
        const value = await api.preview(campaignId, snapshot.profile);
        if (generation.current !== current) return;
        setPreview(value);
        setState("review");
      } else {
        const value = await api.confirm(preview!.preview_token);
        if (generation.current !== current) return;
        setResult(value);
        setPreview(null);
        setState("submitted");
      }
    } catch (cause) {
      if (generation.current !== current) return;
      setPreview(null);
      setError(
        cause instanceof Error ? cause.message : "3D Discovery could not be verified.",
      );
      setState(kind !== "preview" ? "terminal" : "idle");
    } finally {
      if (generation.current === current) busy.current = false;
    }
  }
  function reset() {
    generation.current += 1;
    busy.current = false;
    api.reset();
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
    refresh: () => run("status"),
    review: () => run("preview"),
    confirm: () => run("confirm"),
    reset,
  };
}

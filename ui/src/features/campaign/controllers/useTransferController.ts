import { useEffect, useRef, useState } from "react";
import type { TransferApi, ZeusSnapshot, ZeusTransferPreview, ZeusTransferResult } from "../../../api/clients/zeus";

export type TransferUiState = "idle" | "previewing" | "review" | "preparing" | "success";

export function useTransferController({
  campaignId,
  snapshot,
  api,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  api: TransferApi;
}) {
  const [state, setState] = useState<TransferUiState>("idle");
  const [preview, setPreview] = useState<ZeusTransferPreview | null>(null);
  const [result, setResult] = useState<ZeusTransferResult | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const requestActive = useRef(false);

  useEffect(() => {
    generation.current += 1;
    requestActive.current = false;
    setState("idle");
    setPreview(null);
    setResult(null);
    setError("");
    return () => { generation.current += 1; requestActive.current = false; };
  }, [api, campaignId, snapshot?.profile.host, snapshot?.profile.username, snapshot?.profile.project_directory, snapshot?.profile.authentication]);

  async function previewTransfer() {
    if (!snapshot || requestActive.current) return;
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
      setError(cause instanceof Error ? cause.message : "Zeus preparation preview failed safely.");
      setState("idle");
    } finally {
      if (generation.current === requestGeneration) requestActive.current = false;
    }
  }

  async function confirmTransfer() {
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
    } catch (cause) {
      if (generation.current !== requestGeneration) return;
      setError(cause instanceof Error ? cause.message : "Zeus preparation failed safely.");
      setState("review");
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

  return { state, preview, result, error, previewTransfer, confirmTransfer, reset };
}

import { useState } from "react";
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

  async function previewTransfer() {
    if (!snapshot) return;
    setState("previewing");
    setError("");
    try {
      setPreview(await api.preview(campaignId, snapshot.profile));
      setState("review");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Zeus preparation preview failed safely.");
      setState("idle");
    }
  }

  async function confirmTransfer() {
    if (!preview) return;
    setState("preparing");
    setError("");
    try {
      setResult(await api.confirm(preview.preview_token));
      setState("success");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Zeus preparation failed safely.");
      setState("review");
    }
  }

  function reset() {
    setError("");
    setPreview(null);
    setState("idle");
  }

  return { state, preview, result, error, previewTransfer, confirmTransfer, reset };
}

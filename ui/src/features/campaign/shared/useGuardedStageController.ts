import { useCallback, useEffect, useRef, useState } from "react";

export type GuardedStagePhase =
  | "idle"
  | "checking"
  | "ready"
  | "reviewing"
  | "review"
  | "confirming"
  | "success"
  | "blocked";

export type GuardedStageErrorPhase =
  | "status"
  | "preview"
  | "confirm_rejected"
  | "confirm_unknown";

export type GuardedStageOperations<Status, Preview, Result> = {
  status: () => Promise<Status>;
  preview: () => Promise<Preview>;
  confirm: (preview: Preview) => Promise<Result>;
  reset: () => void;
};

type Options<Status, Preview, Result> = {
  enabled: boolean;
  contextKey: string;
  operations: GuardedStageOperations<Status, Preview, Result>;
  stateForStatus: (status: Status) => "idle" | "ready" | "blocked" | "success";
  canPreview: (status: Status | null) => boolean;
  isUnknownConfirmation: (error: unknown) => boolean;
};

export function useGuardedStageController<Status, Preview, Result>({
  enabled,
  contextKey,
  operations,
  stateForStatus,
  canPreview,
  isUnknownConfirmation,
}: Options<Status, Preview, Result>) {
  const [phase, setPhase] = useState<GuardedStagePhase>("idle");
  const [status, setStatus] = useState<Status | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [errorPhase, setErrorPhase] = useState<GuardedStageErrorPhase | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  const reviewBlocked = useRef(false);
  const consumedPreview = useRef<Preview | null>(null);
  const operationsRef = useRef(operations);
  operationsRef.current = operations;

  const clear = useCallback(() => {
    generation.current += 1;
    busy.current = false;
    consumedPreview.current = null;
    reviewBlocked.current = false;
    operationsRef.current.reset();
    setPhase("idle");
    setStatus(null);
    setPreview(null);
    setResult(null);
    setError("");
    setErrorPhase(null);
  }, []);

  useEffect(() => {
    clear();
    return () => {
      generation.current += 1;
      busy.current = false;
      consumedPreview.current = null;
    };
  }, [clear, contextKey, enabled]);

  const run = useCallback(async (kind: "status" | "preview" | "confirm") => {
    if (!enabled || busy.current) return;
    if (kind === "preview" && (reviewBlocked.current || !canPreview(status))) return;
    if (kind === "confirm" && (!preview || consumedPreview.current === preview)) return;
    busy.current = true;
    const current = generation.current;
    setError("");
    setErrorPhase(null);
    setPhase(kind === "status" ? "checking" : kind === "preview" ? "reviewing" : "confirming");
    const reviewed = kind === "confirm" ? preview : null;
    if (reviewed) consumedPreview.current = reviewed;
    try {
      if (kind === "status") {
        const next = await operations.status();
        if (current !== generation.current) return;
        reviewBlocked.current = false;
        setStatus(next);
        setPhase(stateForStatus(next));
      } else if (kind === "preview") {
        const next = await operations.preview();
        if (current !== generation.current) return;
        setPreview(next);
        setPhase("review");
      } else {
        const next = await operations.confirm(reviewed as Preview);
        if (current !== generation.current) return;
        setResult(next);
        setPreview(null);
        setPhase("success");
      }
    } catch (cause) {
      if (current !== generation.current) return;
      const unknown = kind === "confirm" && isUnknownConfirmation(cause);
      if (unknown || kind === "status") reviewBlocked.current = true;
      if (kind === "status") {
        setStatus(null);
        setPreview(null);
      }
      setError(cause instanceof Error ? cause.message : "The operation could not be verified.");
      setErrorPhase(kind === "status" ? "status" : kind === "preview" ? "preview" : unknown ? "confirm_unknown" : "confirm_rejected");
      if (kind === "confirm" && !unknown) consumedPreview.current = null;
      setPhase(unknown ? "blocked" : kind === "status" ? "idle" : status ? stateForStatus(status) : "idle");
    } finally {
      if (current === generation.current) busy.current = false;
    }
  }, [canPreview, enabled, isUnknownConfirmation, operations, preview, stateForStatus, status]);

  return {
    phase,
    status,
    preview,
    result,
    error,
    errorPhase,
    refresh: () => run("status"),
    review: () => run("preview"),
    confirm: () => run("confirm"),
    reset: clear,
  };
}

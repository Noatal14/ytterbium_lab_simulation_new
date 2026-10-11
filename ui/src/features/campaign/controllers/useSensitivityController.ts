import { useEffect, useRef, useState } from "react";
import type {
  SensitivityApi,
  SensitivitySubmissionApi,
} from "../../../api/clients/sensitivity";
import type {
  SensitivityPreview,
  SensitivityResult,
  SensitivityStatus,
  SensitivitySubmissionPreview,
  SensitivitySubmissionResult,
  SensitivitySubmissionStatus,
  ZeusSnapshot,
} from "../../../api/schema/domain";
type State =
  "idle" | "checking" | "review" | "confirming" | "success" | "terminal";
function useOperation<TStatus, TPreview, TResult>(args: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: {
    status: (id: string, p: ZeusSnapshot["profile"]) => Promise<TStatus>;
    preview: (id: string, p: ZeusSnapshot["profile"]) => Promise<TPreview>;
    confirm: (token: string) => Promise<TResult>;
    reset: () => void;
  };
  token: (p: TPreview) => string;
  terminal: (s: TStatus) => boolean;
  complete: (s: TStatus) => boolean;
}) {
  const [state, setState] = useState<State>("idle"),
    [status, setStatus] = useState<TStatus | null>(null),
    [preview, setPreview] = useState<TPreview | null>(null),
    [result, setResult] = useState<TResult | null>(null),
    [error, setError] = useState("");
  const gen = useRef(0),
    busy = useRef(false);
  useEffect(() => {
    gen.current++;
    busy.current = false;
    args.api.reset();
    setState("idle");
    setStatus(null);
    setPreview(null);
    setResult(null);
    setError("");
    return () => {
      // Cleanup must invalidate every request started during this generation.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      gen.current++;
      busy.current = false;
    };
  }, [
    args.api,
    args.campaignId,
    args.enabled,
    args.snapshot?.profile.host,
    args.snapshot?.profile.username,
    args.snapshot?.profile.project_directory,
    args.snapshot?.profile.authentication,
  ]);
  async function run(kind: "status" | "preview" | "confirm") {
    if (
      !args.snapshot ||
      !args.enabled ||
      busy.current ||
      (kind === "confirm" && !preview)
    )
      return;
    busy.current = true;
    const g = gen.current;
    setState(kind === "confirm" ? "confirming" : "checking");
    setError("");
    try {
      if (kind === "status") {
        const v = await args.api.status(args.campaignId, args.snapshot.profile);
        if (gen.current !== g) return;
        setStatus(v);
        setState(
          args.terminal(v) ? "terminal" : args.complete(v) ? "success" : "idle",
        );
      } else if (kind === "preview") {
        const v = await args.api.preview(
          args.campaignId,
          args.snapshot.profile,
        );
        if (gen.current !== g) return;
        setPreview(v);
        setState("review");
      } else {
        const v = await args.api.confirm(args.token(preview!));
        if (gen.current !== g) return;
        setResult(v);
        setPreview(null);
        setState("success");
      }
    } catch (c) {
      if (gen.current !== g) return;
      setPreview(null);
      setError(
        c instanceof Error ? c.message : "The operation stopped safely.",
      );
      setState(kind === "confirm" ? "terminal" : "idle");
    } finally {
      if (gen.current === g) busy.current = false;
    }
  }
  function reset() {
    gen.current++;
    busy.current = false;
    args.api.reset();
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
export function useSensitivityController({
  campaignId,
  snapshot,
  enabled,
  api,
  submissionApi,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: SensitivityApi;
  submissionApi: SensitivitySubmissionApi;
}) {
  const preparation = useOperation<
    SensitivityStatus,
    SensitivityPreview,
    SensitivityResult
  >({
    campaignId,
    snapshot,
    enabled,
    api,
    token: (p) => p.preview_token,
    terminal: (s) =>
      ["failed", "held", "status_unknown", "outputs_invalid"].includes(
        s.confirmation.status,
      ),
    complete: (s) => s.confirmation.status === "sensitivity_prepared",
  });
  const submission = useOperation<
    SensitivitySubmissionStatus,
    SensitivitySubmissionPreview,
    SensitivitySubmissionResult
  >({
    campaignId,
    snapshot,
    enabled:
      enabled &&
      (preparation.state === "success" ||
        preparation.status?.confirmation.status === "sensitivity_prepared"),
    api: submissionApi,
    token: (p) => p.preview_token,
    terminal: (s) =>
      [
        "held",
        "completed_failed",
        "status_unknown",
        "outcome_unknown",
      ].includes(s.submission.status),
    complete: (s) =>
      ["queued", "running", "completed_success"].includes(s.submission.status),
  });
  return { preparation, submission };
}

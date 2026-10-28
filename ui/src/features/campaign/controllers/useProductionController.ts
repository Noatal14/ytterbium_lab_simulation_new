import { useEffect, useMemo, useRef, useState } from "react";
import { finalizationCollectionApi } from "../../../api/clients/production";
import type {
  FinalizationApi,
  FinalizationCollectionApi,
  ProductionApi,
  ProductionSubmissionApi,
} from "../../../api/clients/production";
import type {
  FinalizationPreview,
  FinalizationResult,
  FinalizationStatus,
  FinalizationCollectionPreview,
  FinalizationCollectionResult,
  ProductionPreview,
  ProductionResult,
  ProductionStatus,
  ProductionSubmissionPreview,
  ProductionSubmissionResult,
  ProductionSubmissionStatus,
  ZeusSnapshot,
} from "../../../api/schema/domain";
type State =
  "idle" | "checking" | "review" | "confirming" | "success" | "terminal";
function useOperation<TStatus, TPreview, TResult>(args: {
  campaignId: string;
  contextKey?: string;
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
  reviewable?: (status: TStatus | null) => boolean;
}) {
  const context = useMemo(
    () => ({
      api: args.api,
      id: args.campaignId,
      key: args.contextKey,
      enabled: args.enabled,
      host: args.snapshot?.profile.host,
      username: args.snapshot?.profile.username,
      directory: args.snapshot?.profile.project_directory,
      authentication: args.snapshot?.profile.authentication,
      commit: args.snapshot?.remote.git_commit,
    }),
    [
      args.api,
      args.campaignId,
      args.contextKey,
      args.enabled,
      args.snapshot?.profile.host,
      args.snapshot?.profile.username,
      args.snapshot?.profile.project_directory,
      args.snapshot?.profile.authentication,
      args.snapshot?.remote.git_commit,
    ],
  );
  const currentContext = useRef(context);
  currentContext.current = context;
  const [state, setState] = useState<State>("idle"),
    [status, setStatus] = useState<TStatus | null>(null),
    [preview, setPreview] = useState<TPreview | null>(null),
    [result, setResult] = useState<TResult | null>(null),
    [error, setError] = useState("");
  const [lastObservation, setLastObservation] = useState<
    "status" | "confirm" | null
  >(null);
  const gen = useRef(0),
    busy = useRef(false);
  const reviewBlocked = useRef(false);
  const reviewToken = useRef<string | null>(null);
  const observedStatus = useRef<TStatus | null>(status);
  observedStatus.current = status;
  useEffect(() => {
    gen.current++;
    busy.current = false;
    args.api.reset();
    reviewBlocked.current = false;
    reviewToken.current = null;
    observedStatus.current = null;
    setState("idle");
    setStatus(null);
    setLastObservation(null);
    setPreview(null);
    setResult(null);
    setError("");
    return () => {
      // Cleanup must invalidate every request started during this generation.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      gen.current++;
      busy.current = false;
    };
  }, [context, args.api]);
  async function run(kind: "status" | "preview" | "confirm") {
    if (
      currentContext.current !== context ||
      !args.snapshot ||
      !args.enabled ||
      busy.current ||
      (kind === "preview" &&
        (reviewBlocked.current ||
          (args.reviewable && !args.reviewable(observedStatus.current)))) ||
      (kind === "confirm" &&
        (!preview || reviewToken.current !== args.token(preview)))
    )
      return;
    busy.current = true;
    reviewToken.current = null;
    const g = gen.current;
    setState(kind === "confirm" ? "confirming" : "checking");
    setError("");
    try {
      if (kind === "status") {
        const v = await args.api.status(args.campaignId, args.snapshot.profile);
        if (gen.current !== g || currentContext.current !== context) return;
        reviewBlocked.current = false;
        observedStatus.current = v;
        setStatus(v);
        setLastObservation("status");
        setState(
          args.terminal(v) ? "terminal" : args.complete(v) ? "success" : "idle",
        );
      } else if (kind === "preview") {
        const v = await args.api.preview(
          args.campaignId,
          args.snapshot.profile,
        );
        if (gen.current !== g || currentContext.current !== context) return;
        reviewToken.current = args.token(v);
        setPreview(v);
        setState("review");
      } else {
        const v = await args.api.confirm(args.token(preview!));
        if (gen.current !== g || currentContext.current !== context) return;
        setResult(v);
        setLastObservation("confirm");
        setPreview(null);
        setState("success");
      }
    } catch (c) {
      if (gen.current !== g || currentContext.current !== context) return;
      reviewBlocked.current = true;
      setPreview(null);
      setError(
        c instanceof Error
          ? c.message
          : kind === "confirm"
            ? "The operation outcome is unknown. Check the current campaign status. Do not retry or submit again automatically."
            : "The operation could not be verified.",
      );
      setState(kind === "confirm" ? "terminal" : "idle");
    } finally {
      if (gen.current === g && currentContext.current === context)
        busy.current = false;
    }
  }
  function reset() {
    if (currentContext.current !== context) return;
    gen.current++;
    busy.current = false;
    args.api.reset();
    reviewBlocked.current = false;
    reviewToken.current = null;
    setPreview(null);
    setError("");
    setState("idle");
  }
  return {
    state,
    lastObservation,
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
export function useProductionController({
  campaignId,
  snapshot,
  enabled,
  api,
  submissionApi,
  finalizationApi,
  collectionApi = finalizationCollectionApi,
  contextKey,
}: {
  campaignId: string;
  snapshot: ZeusSnapshot | null;
  enabled: boolean;
  api: ProductionApi;
  submissionApi: ProductionSubmissionApi;
  finalizationApi: FinalizationApi;
  collectionApi?: FinalizationCollectionApi;
  contextKey?: string;
}) {
  const preparation = useOperation<
    ProductionStatus,
    ProductionPreview,
    ProductionResult
  >({
    campaignId,
    contextKey,
    snapshot,
    enabled,
    api,
    token: (p) => p.preview_token,
    terminal: (s) =>
      ["held", "failed", "status_unknown", "outputs_invalid"].includes(
        s.sensitivity.status,
      ),
    complete: (s) => s.sensitivity.status === "production_prepared",
  });
  const submission = useOperation<
    ProductionSubmissionStatus,
    ProductionSubmissionPreview,
    ProductionSubmissionResult
  >({
    campaignId,
    contextKey,
    snapshot,
    enabled:
      enabled &&
      (preparation.state === "success" ||
        preparation.status?.sensitivity.status === "production_prepared"),
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
  const finalization = useOperation<
    FinalizationStatus,
    FinalizationPreview,
    FinalizationResult
  >({
    campaignId,
    contextKey,
    snapshot,
    enabled:
      enabled && (submission.state === "success" || Boolean(submission.status)),
    api: finalizationApi,
    token: (p) => p.preview_token,
    terminal: (s) =>
      ["held", "failed", "status_unknown", "outputs_invalid"].includes(
        s.production.status,
      ),
    complete: (s) => s.production.status === "campaign_complete",
  });
  const collection = useOperation<
    FinalizationStatus,
    FinalizationCollectionPreview,
    FinalizationCollectionResult
  >({
    campaignId,
    contextKey,
    snapshot,
    enabled:
      enabled &&
      finalization.state === "success" &&
      (finalization.status?.production.status === "campaign_complete" ||
        finalization.result?.status === "campaign_complete"),
    api: collectionApi,
    token: (p) => p.preview_token,
    reviewable: (s) =>
      s === null ||
      (s.production.status === "campaign_complete" &&
        s.local_sync.status === "not_synchronized"),
    terminal: (s) =>
      ["held", "failed", "status_unknown", "outputs_invalid"].includes(
        s.production.status,
      ),
    complete: (s) =>
      s.production.status === "campaign_complete" &&
      s.local_sync.status === "synchronized",
  });
  return { preparation, submission, finalization, collection };
}

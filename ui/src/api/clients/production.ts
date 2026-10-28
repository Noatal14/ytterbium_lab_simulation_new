import { isKnownServerError, type ServerErrorDomain } from "../errorSemantics";
import { postData } from "../http/envelope";
import {
  ProductionApiError,
  ProductionSubmissionApiError,
  FinalizationApiError,
} from "../http/errors";
import { creationApi } from "./campaign";
import {
  parseProductionPreview,
  parseProductionResult,
  parseProductionStatus,
  parseProductionSubmissionPreview,
  parseProductionSubmissionResult,
  parseProductionSubmissionStatus,
  parseFinalizationPreview,
  parseFinalizationResult,
  parseFinalizationStatus,
  parseFinalizationCollectionPreview,
  parseFinalizationCollectionResult,
  type FinalizationCollectionPreview,
  type FinalizationCollectionResult,
  type ProductionPreview,
  type ProductionResult,
  type ProductionStatus,
  type ProductionSubmissionPreview,
  type ProductionSubmissionResult,
  type ProductionSubmissionStatus,
  type FinalizationPreview,
  type FinalizationResult,
  type FinalizationStatus,
  type ZeusSnapshot,
} from "../schema/domain";
type Session = () => Promise<string>;
type Profile = ZeusSnapshot["profile"];
const confirmationPreflightCodes = new Set(["unsupported_query", "session_unavailable", "untrusted_origin", "invalid_campaign_id", "not_found", "method_not_allowed", "invalid_preview", "invalid_request_target", "untrusted_host", "invalid_session", "invalid_csrf"]);
const request = (campaign_id: string, p: Profile) => ({
  campaign_id,
  username: p.username,
  project_directory: p.project_directory,
});
function transitionApi<TS, TP, TR>(
  session: Session,
  paths: { status: string; preview: string; confirm: string },
  parse: {
    status: (v: Record<string, unknown>) => TS;
    preview: (v: Record<string, unknown>) => TP;
    result: (v: Record<string, unknown>) => TR;
  },
  ErrorType: new (code: string, message: string) => Error,
  label: string,
  domain: ServerErrorDomain,
  outcomeCode: string,
  verifyResult?: (preview: TP, result: TR) => boolean,
) {
  const contexts = new Map<string, { campaignId: string; csrf: string; preview: TP }>();
  let generation = 0;
  return {
    async status(id: string, p: Profile) {
      const activeGeneration = generation;
      const csrf = await session(),
        v = parse.status(
          await postData(
            paths.status,
            request(id, p),
            csrf,
            (e) => new ErrorType(e.code, e.message),
          ),
        );
      if (activeGeneration !== generation) throw new Error(`${label} response is stale.`);
      if ((v as { campaign: { id: string } }).campaign.id !== id)
        throw new Error(`${label} status did not match the selected campaign.`);
      return v;
    },
    async preview(id: string, p: Profile) {
      const activeGeneration = generation;
      const csrf = await session(),
        v = parse.preview(
          await postData(
            paths.preview,
            request(id, p),
            csrf,
            (e) => new ErrorType(e.code, e.message),
          ),
        ),
        token = (v as { preview_token: string }).preview_token;
      if (activeGeneration !== generation) throw new Error(`${label} response is stale.`);
      if ((v as { campaign: { id: string } }).campaign.id !== id)
        throw new Error(`${label} review did not match the selected campaign.`);
      contexts.set(token, { campaignId: id, csrf, preview: v });
      return v;
    },
    async confirm(token: string) {
      const c = contexts.get(token);
      if (!c) throw new Error(`The ${label} review is no longer active.`);
      contexts.delete(token);
      const activeGeneration = generation;
      try {
      const v = parse.result(
        await postData(
          paths.confirm,
          { preview_token: token },
          c.csrf,
          (e) => new ErrorType(e.code, e.message),
        ),
      );
      if (activeGeneration !== generation || verifyResult && !verifyResult(c.preview, v)) throw new Error(`${label} result could not be verified.`);
      if ((v as { campaign_id: string }).campaign_id !== c.campaignId)
        throw new Error(`${label} result did not match the reviewed campaign.`);
      return v;
      } catch (cause) {
        const code = cause && typeof cause === "object" && "code" in cause ? cause.code : undefined;
        if (isKnownServerError(domain, code) || typeof code === "string" && confirmationPreflightCodes.has(code)) throw cause;
        throw new ErrorType(outcomeCode, "The operation outcome is unknown. Check the current campaign status. Do not retry or submit again automatically.");
      }
    },
    reset() {
      generation++;
      contexts.clear();
    },
  };
}
export function createProductionApi(session: Session) {
  return transitionApi<ProductionStatus, ProductionPreview, ProductionResult>(
    session,
    {
      status: "/api/v1/zeus/sensitivity-results/status",
      preview: "/api/v1/zeus/production/preview",
      confirm: "/api/v1/zeus/production/confirm",
    },
    {
      status: parseProductionStatus,
      preview: parseProductionPreview,
      result: parseProductionResult,
    },
    ProductionApiError,
    "Production preparation",
    "production_transition",
    "transition_outcome_unknown",
  );
}
export function createProductionSubmissionApi(session: Session) {
  return transitionApi<
    ProductionSubmissionStatus,
    ProductionSubmissionPreview,
    ProductionSubmissionResult
  >(
    session,
    {
      status: "/api/v1/zeus/submissions/production/status",
      preview: "/api/v1/zeus/submissions/production/preview",
      confirm: "/api/v1/zeus/submissions/production/confirm",
    },
    {
      status: parseProductionSubmissionStatus,
      preview: parseProductionSubmissionPreview,
      result: parseProductionSubmissionResult,
    },
    ProductionSubmissionApiError,
    "Production submission",
    "production_submission",
    "production_submission_outcome_unknown",
  );
}
export function createFinalizationApi(session: Session) {
  return transitionApi<
    FinalizationStatus,
    FinalizationPreview,
    FinalizationResult
  >(
    session,
    {
      status: "/api/v1/zeus/production-results/status",
      preview: "/api/v1/zeus/finalization/preview",
      confirm: "/api/v1/zeus/finalization/confirm",
    },
    {
      status: parseFinalizationStatus,
      preview: parseFinalizationPreview,
      result: parseFinalizationResult,
    },
    FinalizationApiError,
    "campaign finalization",
    "finalization",
    "finalization_outcome_unknown",
  );
}
export type ProductionApi = ReturnType<typeof createProductionApi>;
export type ProductionSubmissionApi = ReturnType<
  typeof createProductionSubmissionApi
>;
export type FinalizationApi = ReturnType<typeof createFinalizationApi>;
export const productionApi = createProductionApi(() => creationApi.session());
export const productionSubmissionApi = createProductionSubmissionApi(() =>
  creationApi.session(),
);
export const finalizationApi = createFinalizationApi(() =>
  creationApi.session(),
);

export function createFinalizationCollectionApi(session: Session) {
  return transitionApi<
    FinalizationStatus,
    FinalizationCollectionPreview,
    FinalizationCollectionResult
  >(
    session,
    {
      status: "/api/v1/zeus/production-results/status",
      preview: "/api/v1/zeus/finalization/collection/preview",
      confirm: "/api/v1/zeus/finalization/collection/confirm",
    },
    {
      status: parseFinalizationStatus,
      preview: parseFinalizationCollectionPreview,
      result: parseFinalizationCollectionResult,
    },
    FinalizationApiError,
    "local collection",
    "finalization",
    "collection_outcome_unknown",
    (preview, result) =>
      result.artifacts.created === preview.artifacts.create.length &&
      result.artifacts.identical === preview.artifacts.identical.length,
  );
}
export type FinalizationCollectionApi = ReturnType<
  typeof createFinalizationCollectionApi
>;
export const finalizationCollectionApi = createFinalizationCollectionApi(() =>
  creationApi.session(),
);

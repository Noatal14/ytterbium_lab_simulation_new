import { postData } from "../http/envelope";
import {
  ConfirmationSubmissionApiError,
  RefinementLifecycleApiError,
  RefinementSubmissionApiError,
} from "../http/errors";
import { synthesizedUncertainty } from "../errorSemantics";
import {
  parseConfirmationPreview,
  parseConfirmationResult,
  parseConfirmationSubmissionPreview,
  parseConfirmationSubmissionResult,
  parseConfirmationSubmissionStatus,
  parseRefinementChainStatus,
  parseRefinementLifecycle,
  parseRefinementSubmissionPreview,
  parseRefinementSubmissionResult,
  type ConfirmationPreview,
  type ConfirmationResult,
  type ConfirmationSubmissionPreview,
  type ConfirmationSubmissionResult,
  type ConfirmationSubmissionStatus,
  type RefinementChainStatus,
  type RefinementLifecycle,
  type RefinementSubmissionPreview,
  type RefinementSubmissionResult,
  type ZeusSnapshot,
} from "../schema/domain";
import { creationApi } from "./campaign";
export {
  RefinementLifecycleApiError,
  RefinementSubmissionApiError,
} from "../http/errors";
export {
  roundTiesToEven,
  type ConfirmationPreview,
  type ConfirmationResult,
  type RefinementChainStatus,
  type RefinementLifecycle,
  type RefinementSubmissionPreview,
  type RefinementSubmissionResult,
} from "../schema/domain";
type Session = () => Promise<string>;
type Context = { campaignId: string; csrf: string };
export function createRefinementSubmissionApi(session: Session) {
  const contexts = new Map<string, Context>();
  return {
    async status(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<RefinementChainStatus> {
      const csrf = await session();
      const value = parseRefinementChainStatus(
        await postData(
          "/api/v1/zeus/submissions/refinement/status",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new RefinementSubmissionApiError(e.code, e.message),
        ),
      );
      if (value.campaign.id !== campaign_id)
        throw new Error(
          "Refinement chain status did not match the selected campaign.",
        );
      return value;
    },
    async preview(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<RefinementSubmissionPreview> {
      const csrf = await session();
      const value = parseRefinementSubmissionPreview(
        await postData(
          "/api/v1/zeus/submissions/refinement/preview",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new RefinementSubmissionApiError(e.code, e.message),
        ),
      );
      if (
        value.campaign.id !== campaign_id ||
        value.remote.project_directory !== profile.project_directory
      )
        throw new Error(
          "Refinement preview did not match the selected campaign.",
        );
      contexts.set(value.preview_token, { campaignId: campaign_id, csrf });
      return value;
    },
    async confirm(preview_token: string): Promise<RefinementSubmissionResult> {
      const context = contexts.get(preview_token);
      if (!context)
        throw new Error(
          "The Refinement submission preview is no longer active.",
        );
      contexts.delete(preview_token);
      try {
        const value = parseRefinementSubmissionResult(
          await postData(
            "/api/v1/zeus/submissions/refinement/confirm",
            { preview_token },
            context.csrf,
            (e) => new RefinementSubmissionApiError(e.code, e.message),
          ),
        );
        if (value.campaign_id !== context.campaignId)
          throw new Error(
            "Refinement result did not match the reviewed campaign.",
          );
        return value;
      } catch (error) {
        if (error instanceof RefinementSubmissionApiError) throw error;
        throw new RefinementSubmissionApiError(
          synthesizedUncertainty.refinement_submission,
          "The chain outcome could not be verified. Do not retry automatically.",
        );
      }
    },
    reset() {
      contexts.clear();
    },
  };
}
export function createRefinementLifecycleApi(session: Session) {
  const contexts = new Map<string, Context>();
  return {
    async status(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<RefinementLifecycle> {
      const csrf = await session();
      const value = parseRefinementLifecycle(
        await postData(
          "/api/v1/zeus/refinement-chain/status",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new RefinementLifecycleApiError(e.code, e.message),
        ),
      );
      if (value.campaign.id !== campaign_id)
        throw new Error(
          "Refinement lifecycle did not match the selected campaign.",
        );
      return value;
    },
    async preview(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<ConfirmationPreview> {
      const csrf = await session();
      const value = parseConfirmationPreview(
        await postData(
          "/api/v1/zeus/confirmation/preview",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new RefinementLifecycleApiError(e.code, e.message),
        ),
      );
      if (value.campaign.id !== campaign_id)
        throw new Error(
          "Confirmation preview did not match the selected campaign.",
        );
      contexts.set(value.preview_token, { campaignId: campaign_id, csrf });
      return value;
    },
    async confirm(preview_token: string): Promise<ConfirmationResult> {
      const context = contexts.get(preview_token);
      if (!context)
        throw new Error("The Confirmation preview is no longer active.");
      contexts.delete(preview_token);
      const value = parseConfirmationResult(
        await postData(
          "/api/v1/zeus/confirmation/confirm",
          { preview_token },
          context.csrf,
          (e) => new RefinementLifecycleApiError(e.code, e.message),
        ),
      );
      if (value.campaign_id !== context.campaignId)
        throw new Error(
          "Confirmation result did not match the reviewed campaign.",
        );
      return value;
    },
    reset() {
      contexts.clear();
    },
  };
}
export function createConfirmationSubmissionApi(session: Session) {
  const contexts = new Map<string, Context>();
  return {
    async status(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<ConfirmationSubmissionStatus> {
      const csrf = await session();
      const value = parseConfirmationSubmissionStatus(
        await postData(
          "/api/v1/zeus/submissions/confirmation/status",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new ConfirmationSubmissionApiError(e.code, e.message),
        ),
      );
      if (value.campaign.id !== campaign_id)
        throw new Error(
          "Confirmation submission status did not match the selected campaign.",
        );
      return value;
    },
    async preview(
      campaign_id: string,
      profile: ZeusSnapshot["profile"],
    ): Promise<ConfirmationSubmissionPreview> {
      const csrf = await session();
      const value = parseConfirmationSubmissionPreview(
        await postData(
          "/api/v1/zeus/submissions/confirmation/preview",
          {
            campaign_id,
            username: profile.username,
            project_directory: profile.project_directory,
          },
          csrf,
          (e) => new ConfirmationSubmissionApiError(e.code, e.message),
        ),
      );
      if (
        value.campaign.id !== campaign_id ||
        value.remote.project_directory !== profile.project_directory
      )
        throw new Error(
          "Confirmation submission preview did not match the reviewed campaign or Zeus connection.",
        );
      contexts.set(value.preview_token, { campaignId: campaign_id, csrf });
      return value;
    },
    async confirm(
      preview_token: string,
    ): Promise<ConfirmationSubmissionResult> {
      const context = contexts.get(preview_token);
      if (!context)
        throw new Error(
          "The Confirmation submission preview is no longer active.",
        );
      contexts.delete(preview_token);
      try {
        const value = parseConfirmationSubmissionResult(
          await postData(
            "/api/v1/zeus/submissions/confirmation/confirm",
            { preview_token },
            context.csrf,
            (e) => new ConfirmationSubmissionApiError(e.code, e.message),
          ),
        );
        if (value.campaign_id !== context.campaignId)
          throw new Error(
            "Confirmation submission result did not match the reviewed campaign.",
          );
        return value;
      } catch (error) {
        if (error instanceof ConfirmationSubmissionApiError) throw error;
        throw new ConfirmationSubmissionApiError(
          synthesizedUncertainty.confirmation_submission,
          "The Confirmation job outcome could not be verified. Do not retry automatically.",
        );
      }
    },
    reset() {
      contexts.clear();
    },
  };
}
export type RefinementSubmissionApi = Pick<
  ReturnType<typeof createRefinementSubmissionApi>,
  "status" | "preview" | "confirm"
>;
export type RefinementLifecycleApi = Pick<
  ReturnType<typeof createRefinementLifecycleApi>,
  "status" | "preview" | "confirm"
>;
export type ConfirmationSubmissionApi = Pick<
  ReturnType<typeof createConfirmationSubmissionApi>,
  "status" | "preview" | "confirm" | "reset"
>;
export const refinementSubmissionApi = createRefinementSubmissionApi(() =>
  creationApi.session(),
);
export const refinementLifecycleApi = createRefinementLifecycleApi(() =>
  creationApi.session(),
);
export const confirmationSubmissionApi = createConfirmationSubmissionApi(() =>
  creationApi.session(),
);

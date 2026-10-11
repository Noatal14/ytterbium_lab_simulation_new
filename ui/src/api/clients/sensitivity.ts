import { postData } from "../http/envelope";
import {
  SensitivityApiError,
  SensitivitySubmissionApiError,
} from "../http/errors";
import { creationApi } from "./campaign";
import {
  parseSensitivityPreview,
  parseSensitivityResult,
  parseSensitivityStatus,
  parseSensitivitySubmissionPreview,
  parseSensitivitySubmissionResult,
  parseSensitivitySubmissionStatus,
  type SensitivityPreview,
  type SensitivityResult,
  type SensitivityStatus,
  type SensitivitySubmissionPreview,
  type SensitivitySubmissionResult,
  type SensitivitySubmissionStatus,
  type ZeusSnapshot,
} from "../schema/domain";
type Session = () => Promise<string>;
type Profile = ZeusSnapshot["profile"];
const request = (campaign_id: string, p: Profile) => ({
  campaign_id,
  username: p.username,
  project_directory: p.project_directory,
});
export function createSensitivityApi(session: Session) {
  const contexts = new Map<string, { campaignId: string; csrf: string }>();
  return {
    async status(id: string, p: Profile): Promise<SensitivityStatus> {
      const csrf = await session(),
        v = parseSensitivityStatus(
          await postData(
            "/api/v1/zeus/confirmation-results/status",
            request(id, p),
            csrf,
            (e) => new SensitivityApiError(e.code, e.message),
          ),
        );
      if (v.campaign.id !== id)
        throw new Error(
          "Sensitivity status did not match the selected campaign.",
        );
      return v;
    },
    async preview(id: string, p: Profile): Promise<SensitivityPreview> {
      const csrf = await session(),
        v = parseSensitivityPreview(
          await postData(
            "/api/v1/zeus/sensitivity/preview",
            request(id, p),
            csrf,
            (e) => new SensitivityApiError(e.code, e.message),
          ),
        );
      if (v.campaign.id !== id)
        throw new Error(
          "Sensitivity review did not match the selected campaign.",
        );
      contexts.set(v.preview_token, { campaignId: id, csrf });
      return v;
    },
    async confirm(token: string): Promise<SensitivityResult> {
      const c = contexts.get(token);
      if (!c)
        throw new Error(
          "The Sensitivity preparation review is no longer active.",
        );
      contexts.delete(token);
      const v = parseSensitivityResult(
        await postData(
          "/api/v1/zeus/sensitivity/confirm",
          { preview_token: token },
          c.csrf,
          (e) => new SensitivityApiError(e.code, e.message),
        ),
      );
      if (v.campaign_id !== c.campaignId)
        throw new Error(
          "Sensitivity result did not match the reviewed campaign.",
        );
      return v;
    },
    reset() {
      contexts.clear();
    },
  };
}
export function createSensitivitySubmissionApi(session: Session) {
  const contexts = new Map<string, { campaignId: string; csrf: string }>();
  return {
    async status(id: string, p: Profile): Promise<SensitivitySubmissionStatus> {
      const csrf = await session(),
        v = parseSensitivitySubmissionStatus(
          await postData(
            "/api/v1/zeus/submissions/sensitivity/status",
            request(id, p),
            csrf,
            (e) => new SensitivitySubmissionApiError(e.code, e.message),
          ),
        );
      if (v.campaign.id !== id)
        throw new Error(
          "Sensitivity submission status did not match the selected campaign.",
        );
      return v;
    },
    async preview(
      id: string,
      p: Profile,
    ): Promise<SensitivitySubmissionPreview> {
      const csrf = await session(),
        v = parseSensitivitySubmissionPreview(
          await postData(
            "/api/v1/zeus/submissions/sensitivity/preview",
            request(id, p),
            csrf,
            (e) => new SensitivitySubmissionApiError(e.code, e.message),
          ),
        );
      if (
        v.campaign.id !== id ||
        v.remote.project_directory !== p.project_directory
      )
        throw new Error(
          "Sensitivity submission review did not match the selected campaign or Zeus connection.",
        );
      contexts.set(v.preview_token, { campaignId: id, csrf });
      return v;
    },
    async confirm(token: string): Promise<SensitivitySubmissionResult> {
      const c = contexts.get(token);
      if (!c)
        throw new Error(
          "The Sensitivity submission review is no longer active.",
        );
      contexts.delete(token);
      const v = parseSensitivitySubmissionResult(
        await postData(
          "/api/v1/zeus/submissions/sensitivity/confirm",
          { preview_token: token },
          c.csrf,
          (e) => new SensitivitySubmissionApiError(e.code, e.message),
        ),
      );
      if (v.campaign_id !== c.campaignId)
        throw new Error(
          "Sensitivity submission result did not match the reviewed campaign.",
        );
      return v;
    },
    reset() {
      contexts.clear();
    },
  };
}
export type SensitivityApi = ReturnType<typeof createSensitivityApi>;
export type SensitivitySubmissionApi = ReturnType<
  typeof createSensitivitySubmissionApi
>;
export const sensitivityApi = createSensitivityApi(() => creationApi.session());
export const sensitivitySubmissionApi = createSensitivitySubmissionApi(() =>
  creationApi.session(),
);

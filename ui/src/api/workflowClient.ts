import { campaignApi, creationApi } from "./clients/campaign";
import { createRefinementLifecycleApi, createRefinementSubmissionApi } from "./clients/refinement";
import { createScreeningLifecycleApi, createScreeningSubmissionApi } from "./clients/screening";
import { createSmokeLifecycleApi, createSubmissionApi } from "./clients/smoke";
import { createTransferApi, createZeusApi } from "./clients/zeus";
import { createIndividualZeemanApi } from "./clients/individualZeeman";
import { createIndividualMot2DApi } from "./clients/individualMot2D";

export class WorkflowApiClient {
  readonly campaign=campaignApi; readonly creation=creationApi;
  readonly zeus; readonly transfer; readonly submission; readonly smokeLifecycle; readonly screeningSubmission; readonly screeningLifecycle; readonly refinementSubmission; readonly refinementLifecycle; readonly individualZeeman; readonly individualMot2D;
  constructor(){const session=()=>this.creation.session();this.zeus=createZeusApi(session);this.transfer=createTransferApi(session);this.submission=createSubmissionApi(session);this.smokeLifecycle=createSmokeLifecycleApi(session);this.screeningSubmission=createScreeningSubmissionApi(session);this.screeningLifecycle=createScreeningLifecycleApi(session);this.refinementSubmission=createRefinementSubmissionApi(session);this.refinementLifecycle=createRefinementLifecycleApi(session);this.individualZeeman=createIndividualZeemanApi(session);this.individualMot2D=createIndividualMot2DApi(session);}
  reset(){this.transfer.reset();this.submission.reset();this.smokeLifecycle.reset();this.screeningSubmission.reset();this.screeningLifecycle.reset();this.refinementSubmission.reset();this.refinementLifecycle.reset();this.individualZeeman.reset();this.individualMot2D.reset();}
}
export const createWorkflowApiClient=()=>new WorkflowApiClient();

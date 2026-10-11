import { campaignApi, creationApi } from "./clients/campaign";
import { createConfirmationSubmissionApi, createRefinementLifecycleApi, createRefinementSubmissionApi } from "./clients/refinement";
import { createScreeningLifecycleApi, createScreeningSubmissionApi } from "./clients/screening";
import { createSmokeLifecycleApi, createSubmissionApi } from "./clients/smoke";
import { createTransferApi, createZeusApi } from "./clients/zeus";
import { createIndividualZeemanApi } from "./clients/individualZeeman";
import { createIndividualMot2DApi } from "./clients/individualMot2D";
import { createSensitivityApi, createSensitivitySubmissionApi } from "./clients/sensitivity";
import { createFinalizationApi, createProductionApi, createProductionSubmissionApi } from "./clients/production";
import { createMot3DBootstrapApi } from "./clients/mot3d";
import { createMot3DDiscoveryApi } from "./clients/mot3dDiscovery";

export class WorkflowApiClient {
  readonly campaign=campaignApi; readonly creation=creationApi;
  readonly zeus; readonly transfer; readonly submission; readonly smokeLifecycle; readonly screeningSubmission; readonly screeningLifecycle; readonly refinementSubmission; readonly refinementLifecycle; readonly confirmationSubmission; readonly sensitivity; readonly sensitivitySubmission; readonly production; readonly productionSubmission; readonly finalization; readonly individualZeeman; readonly individualMot2D; readonly mot3DBootstrap; readonly mot3DDiscovery;
  constructor(){const session=()=>this.creation.session();this.zeus=createZeusApi(session);this.transfer=createTransferApi(session);this.submission=createSubmissionApi(session);this.smokeLifecycle=createSmokeLifecycleApi(session);this.screeningSubmission=createScreeningSubmissionApi(session);this.screeningLifecycle=createScreeningLifecycleApi(session);this.refinementSubmission=createRefinementSubmissionApi(session);this.refinementLifecycle=createRefinementLifecycleApi(session);this.confirmationSubmission=createConfirmationSubmissionApi(session);this.sensitivity=createSensitivityApi(session);this.sensitivitySubmission=createSensitivitySubmissionApi(session);this.production=createProductionApi(session);this.productionSubmission=createProductionSubmissionApi(session);this.finalization=createFinalizationApi(session);this.individualZeeman=createIndividualZeemanApi(session);this.individualMot2D=createIndividualMot2DApi(session);this.mot3DBootstrap=createMot3DBootstrapApi(session);this.mot3DDiscovery=createMot3DDiscoveryApi(session);}
  reset(){this.transfer.reset();this.submission.reset();this.smokeLifecycle.reset();this.screeningSubmission.reset();this.screeningLifecycle.reset();this.refinementSubmission.reset();this.refinementLifecycle.reset();this.confirmationSubmission.reset();this.sensitivity.reset();this.sensitivitySubmission.reset();this.production.reset();this.productionSubmission.reset();this.finalization.reset();this.individualZeeman.reset();this.individualMot2D.reset();this.mot3DBootstrap.reset();this.mot3DDiscovery.reset();}
}
export const createWorkflowApiClient=()=>new WorkflowApiClient();

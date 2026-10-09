/**
 * Transitional compatibility barrel.
 *
 * New product code should import focused clients from `api/clients/*` or create
 * one `WorkflowApiClient` per mounted application. Existing callers keep their
 * stable import path while the UI is migrated incrementally.
 */
export * from "./schema/domain";
export * from "./http/envelope";
export * from "./http/errors";
export * from "./clients/campaign";
export * from "./clients/zeus";
export * from "./clients/smoke";
export * from "./clients/screening";
export * from "./clients/refinement";
export * from "./workflowClient";

# Simulation control center UI

This directory contains the local web interface. It can create and inspect a
frozen 2D campaign, prepare its exact inputs on Zeus, and guide the guarded
Smoke, Screening, Refinement, and Confirmation workflow. Every mutation or
scheduler submission requires a separate review and explicit confirmation.
Nothing submits automatically, arbitrary commands are unavailable, and an
uncertain scheduler outcome blocks retry until Zeus is checked manually.

## Development

With Node.js and npm installed, use the committed lockfile. The development
command starts both the localhost workflow API and the Vite interface:

```bash
cd ui
npm ci
npm run dev
```

To run only the browser frontend (for example, when the API is managed by a
debugger), use:

```bash
npm run dev:ui
```

Vite proxies `/api` to `http://127.0.0.1:8765`. Creation uses a short-lived,
same-origin preview token and revalidates the frozen inputs and repository
snapshot immediately before an atomic local write.

Every guarded flow uses a separate short-lived review-token context owned by
the current application client. CSRF acquisition is also client-scoped, while
the HTTP-only same-origin session cookie is browser-scoped and may be shared by
tabs. The backend revalidates the remote commit, working tree, campaign inputs,
and canonical PBS immediately before each action. Scheduler submissions use
durable remote intent and receipt records so refreshes, restarts, and uncertain
network results cannot silently submit a job twice.

Successful API responses use the strict v1 `{api_version: 1, data: ...}`
envelope. V1 error responses intentionally remain unversioned and retain the
server-provided message. The UI validates every response exactly and uses a
generated, message-free error catalog only to decide safe interaction behavior.

## Structure

- `src/api/http/` — envelopes, requests, and typed errors;
- `src/api/schema/` — exact runtime response validation;
- `src/api/clients/` — per-application campaign and Zeus-stage clients;
- `src/features/campaign/` — stage-specific workflow views;
- `src/features/shared/` — reusable status, review, resource, candidate, and
  manual-verification components;
- `src/content/` — static product content; and
- `src/generated/` — checked-in generated views. Do not edit these by hand.

## Checks

```bash
npm test
npm run build
npm run test:e2e
```

From the repository root, verify generated contracts with:

```bash
python scripts/generate_workflow_error_catalog.py --check
python scripts/generate_ui_error_catalog.py --check
python -m pytest -q tests/test_mot_2d_specification.py::test_checked_in_typescript_artifact_matches_generator_exactly
```

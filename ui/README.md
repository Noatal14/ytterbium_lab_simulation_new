# Simulation control center UI

This directory contains the local web interface. Milestone 1 is fixture-only
and read-only: it cannot create a campaign, connect to Zeus, run a simulation,
or submit a job.

## Development

With Node.js and npm installed, use the committed lockfile:

```bash
cd ui
npm ci
npm run dev
```

The optional local API bridge runs from the repository root:

```bash
python -m workflow_api.server
```

Vite proxies `/api` to `http://127.0.0.1:8765`. The current onboarding page
uses fixtures; the bridge exposes only the read-only workflow catalog.

## Checks

```bash
npm test
npm run build
npm run test:e2e
```

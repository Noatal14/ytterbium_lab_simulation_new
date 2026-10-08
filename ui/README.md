# Simulation control center UI

This directory contains the local web interface. Campaign inspection is
read-only. Milestone 3 adds an explicitly confirmed, local-only 2D campaign
creation flow. It can create the frozen campaign record and initial smoke PBS
file, but it cannot connect to Zeus, run a simulation, or submit a job.

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

## Checks

```bash
npm test
npm run build
npm run test:e2e
```

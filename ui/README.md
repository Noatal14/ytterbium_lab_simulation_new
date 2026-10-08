# Simulation control center UI

This directory contains the local web interface. Campaign inspection remains
read-only. The application can create a frozen 2D campaign locally, prepare its
exact inputs on Zeus after an explicit review, and submit only the initial
smoke check after a second explicit review. It cannot submit later stages,
execute arbitrary commands, or retry an uncertain scheduler submission.

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

Zeus preparation and smoke submission use separate short-lived review tokens.
The backend revalidates the remote commit, working tree, campaign inputs, and
canonical PBS immediately before each action. Smoke submission uses a durable
remote intent and receipt so refreshes, restarts, and uncertain network results
cannot silently submit the job twice.

## Checks

```bash
npm test
npm run build
npm run test:e2e
```

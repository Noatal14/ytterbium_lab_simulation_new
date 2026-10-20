import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { probeWorkflowApi, requireUnusedWorkflowApi, superviseChildren, waitForWorkflowApi } from "./dev-lib.mjs";

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(uiRoot, "..");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const vite = path.join(uiRoot, "node_modules", "vite", "bin", "vite.js");
const children = [];
const apiState = await probeWorkflowApi();
try {
  requireUnusedWorkflowApi(apiState);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
children.push(spawn(python, ["-m", "workflow_api.server"], { cwd: repositoryRoot, stdio: "inherit", env: process.env }));

const supervisor = superviseChildren(children, {
  onFailure: (message) => console.error(message),
  onStopped: (exitCode) => { process.exitCode = exitCode; },
});
const stop = supervisor.stop;
process.on("SIGINT", () => { void stop(0); });
process.on("SIGTERM", () => { void stop(0); });

try {
  console.log("Waiting for the workflow API to become ready…");
  await waitForWorkflowApi({ isStopped: supervisor.isStopping });
  if (!supervisor.isStopping()) supervisor.add(spawn(process.execPath, [vite, "--strictPort", ...(process.argv.includes("--zeus-test") ? ["--mode", "zeus-test", "--port", "5174"] : [])], { cwd: uiRoot, stdio: "inherit", env: process.env }));
} catch (error) {
  console.error(error.message);
  await stop(1);
}

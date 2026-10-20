import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { probeWorkflowApi, requireUnusedWorkflowApi, superviseChildren, waitForWorkflowApi } from "./dev-lib.mjs";

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(uiRoot, "..");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const vite = path.join(uiRoot, "node_modules", "vite", "bin", "vite.js");
const children = [];
const acceptance = process.argv.includes("--ui-acceptance");
if (acceptance && process.argv.includes("--zeus-test")) {
  throw new Error("Choose either individual Zeus test mode or campaign acceptance mode.");
}
const apiState = await probeWorkflowApi();
try {
  requireUnusedWorkflowApi(apiState);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
const backendArgs = ["-m", "workflow_api.server"];
if (acceptance) backendArgs.push("--acceptance-profile", "ui_acceptance_v1");
children.push(spawn(python, backendArgs, { cwd: repositoryRoot, stdio: "inherit", env: process.env }));

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
  if (!supervisor.isStopping()) supervisor.add(spawn(process.execPath, [vite, "--strictPort", ...(acceptance ? ["--mode", "ui-acceptance", "--port", "5175"] : process.argv.includes("--zeus-test") ? ["--mode", "zeus-test", "--port", "5174"] : [])], { cwd: uiRoot, stdio: "inherit", env: process.env }));
} catch (error) {
  console.error(error.message);
  await stop(1);
}

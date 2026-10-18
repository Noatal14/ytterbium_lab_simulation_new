import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { probeWorkflowApi, superviseChildren, waitForWorkflowApi } from "./dev-lib.mjs";

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(uiRoot, "..");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const vite = path.join(uiRoot, "node_modules", "vite", "bin", "vite.js");
const children = [];
const apiState = await probeWorkflowApi();
if (apiState === "compatible") {
  console.log("Using the workflow API already running on http://127.0.0.1:8765");
} else if (apiState === "absent") {
  children.push(spawn(python, ["-m", "workflow_api.server"], { cwd: repositoryRoot, stdio: "inherit", env: process.env }));
} else {
  console.error("Port 8765 is occupied by a service that is not the expected workflow API. Nothing was started.");
  process.exit(1);
}

const supervisor = superviseChildren(children, {
  onFailure: (message) => console.error(message),
  onStopped: (exitCode) => { process.exitCode = exitCode; },
});
const stop = supervisor.stop;
process.on("SIGINT", () => { void stop(0); });
process.on("SIGTERM", () => { void stop(0); });

try {
  if (apiState === "absent") {
    console.log("Waiting for the workflow API to become ready…");
    await waitForWorkflowApi({ isStopped: supervisor.isStopping });
  }
  if (!supervisor.isStopping()) supervisor.add(spawn(process.execPath, [vite, "--strictPort", ...(process.argv.includes("--zeus-test") ? ["--mode", "zeus-test", "--port", "5174"] : [])], { cwd: uiRoot, stdio: "inherit", env: process.env }));
} catch (error) {
  console.error(error.message);
  await stop(1);
}

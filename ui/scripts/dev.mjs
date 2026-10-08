import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { probeWorkflowApi, superviseChildren } from "./dev-lib.mjs";

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(uiRoot, "..");
const python = process.env.PYTHON || "python3";
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
children.push(spawn(process.execPath, [vite, "--strictPort"], { cwd: uiRoot, stdio: "inherit", env: process.env }));

const supervisor = superviseChildren(children, {
  onFailure: (message) => console.error(message),
  onStopped: (exitCode) => { process.exitCode = exitCode; },
});
const stop = supervisor.stop;
process.on("SIGINT", () => { void stop(0); });
process.on("SIGTERM", () => { void stop(0); });

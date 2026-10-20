import http from "node:http";

export function isCompatibleHealth(status, contentType, body) {
  if (status !== 200 || !String(contentType).toLowerCase().startsWith("application/json")) return false;
  try {
    const payload = JSON.parse(body);
    return payload && Object.keys(payload).sort().join(",") === "api_version,status" && payload.api_version === 1 && payload.status === "ok";
  } catch { return false; }
}

export function probeWorkflowApi() {
  return new Promise((resolve) => {
    const request = http.get("http://127.0.0.1:8765/api/health", { timeout: 500 }, (response) => {
      const chunks = []; let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > 8192) request.destroy(); else chunks.push(chunk);
      });
      response.on("end", () => resolve(isCompatibleHealth(response.statusCode, response.headers["content-type"], Buffer.concat(chunks).toString("utf8")) ? "compatible" : "occupied"));
    });
    request.on("error", (error) => resolve(error && error.code === "ECONNREFUSED" ? "absent" : "occupied"));
    request.on("timeout", () => { request.destroy(); resolve("occupied"); });
  });
}

export async function waitForWorkflowApi({ probe = probeWorkflowApi, timeoutMs = 120000, intervalMs = 100, isStopped = () => false } = {}) {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    if (isStopped()) throw new Error("The workflow API stopped during startup.");
    const state = await probe();
    if (isStopped()) throw new Error("The workflow API stopped during startup.");
    if (state === "compatible") return;
    if (state !== "absent") throw new Error("Port 8765 does not provide the expected workflow API.");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("The workflow API did not become ready within the startup time limit.");
}

function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => child.once("exit", resolve));
}

export async function terminateChildren(children, graceMs = 2000) {
  const alive = () => children.filter((child) => child.exitCode === null && child.signalCode === null);
  for (const child of alive()) child.kill("SIGTERM");
  await Promise.race([
    Promise.all(alive().map(waitForExit)),
    new Promise((resolve) => setTimeout(resolve, graceMs)),
  ]);
  for (const child of alive()) child.kill("SIGKILL");
  await Promise.race([
    Promise.all(alive().map(waitForExit)),
    new Promise((resolve) => setTimeout(resolve, graceMs)),
  ]);
}

export function superviseChildren(children, { graceMs = 2000, onFailure = () => {}, onStopped = () => {} } = {}) {
  let stopping = false;
  let stopPromise = null;

  const stop = (exitCode = 0) => {
    if (stopPromise) return stopPromise;
    stopping = true;
    stopPromise = terminateChildren(children, graceMs).then(() => onStopped(exitCode));
    return stopPromise;
  };

  function watch(child) {
    child.on("error", (error) => {
      if (stopping) return;
      onFailure(error.message);
      void stop(1);
    });
    child.on("exit", (code, signal) => {
      if (stopping) return;
      onFailure(`Local development service stopped (${signal ?? code ?? "unknown"}).`);
      void stop(code || 1);
    });
  }

  for (const child of children) watch(child);
  return { stop, isStopping: () => stopping, add(child) { children.push(child); watch(child); if (stopping) void terminateChildren([child], graceMs); } };
}

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { isCompatibleHealth, requireUnusedWorkflowApi, superviseChildren, terminateChildren, waitForWorkflowApi } from "./dev-lib.mjs";

test("accepts only the exact workflow health response", () => {
  assert.equal(isCompatibleHealth(200, "application/json; charset=utf-8", '{"api_version":1,"status":"ok"}'), true);
  assert.equal(isCompatibleHealth(200, "text/html", '{"api_version":1,"status":"ok"}'), false);
  assert.equal(isCompatibleHealth(200, "application/json", '{"status":"ok"}'), false);
  assert.equal(isCompatibleHealth(200, "application/json", '{"api_version":1,"status":"ok","foreign":true}'), false);
});

test("startup refuses an existing compatible backend before creating any children", () => {
  assert.doesNotThrow(() => requireUnusedWorkflowApi("absent"));
  assert.throws(() => requireUnusedWorkflowApi("compatible"), /active local simulation.*existing application.*another checkout/);
  assert.throws(() => requireUnusedWorkflowApi("occupied"), /another service.*Nothing was started/);
  assert.throws(() => requireUnusedWorkflowApi(undefined), /Nothing was started/);
});

class FakeChild extends EventEmitter {
  exitCode = null; signalCode = null; signals = [];
  constructor({ ignoreTerm = false } = {}) { super(); this.ignoreTerm = ignoreTerm; }
  kill(signal) {
    this.signals.push(signal);
    if (signal === "SIGKILL" || !this.ignoreTerm) {
      this.signalCode = signal; queueMicrotask(() => this.emit("exit", null, signal));
    }
    return true;
  }
}

test("shutdown awaits graceful exit and escalates a stubborn sibling", async () => {
  const graceful = new FakeChild(); const stubborn = new FakeChild({ ignoreTerm: true });
  await terminateChildren([graceful, stubborn], 5);
  assert.deepEqual(graceful.signals, ["SIGTERM"]);
  assert.deepEqual(stubborn.signals, ["SIGTERM", "SIGKILL"]);
  assert.notEqual(graceful.signalCode, null); assert.notEqual(stubborn.signalCode, null);
});

test("a startup failure tears down its sibling and leaves no managed child alive", async () => {
  const failed = new FakeChild();
  const sibling = new FakeChild({ ignoreTerm: true });
  const stopped = new Promise((resolve) => {
    superviseChildren([failed, sibling], { graceMs: 5, onStopped: resolve });
  });

  failed.exitCode = 1;
  failed.emit("exit", 1, null);
  assert.equal(await stopped, 1);
  assert.deepEqual(sibling.signals, ["SIGTERM", "SIGKILL"]);
  assert.notEqual(sibling.signalCode, null);
});

test("startup waits through refused connections before exposing the UI", async () => {
  const states = ["absent", "absent", "compatible"];
  await waitForWorkflowApi({ probe: async () => states.shift(), intervalMs: 1 });
  assert.equal(states.length, 0);
});

test("startup rejects an incompatible service, a timeout, and a stopped backend", async () => {
  await assert.rejects(waitForWorkflowApi({ probe: async () => "occupied" }), /expected workflow API/);
  await assert.rejects(waitForWorkflowApi({ probe: async () => "absent", timeoutMs: 5, intervalMs: 1 }), /startup time limit/);
  await assert.rejects(waitForWorkflowApi({ isStopped: () => true }), /stopped during startup/);
});

test("a Vite child added after backend readiness is supervised and stopped", async () => {
  const api = new FakeChild(), vite = new FakeChild();
  const supervisor = superviseChildren([api], { graceMs: 5 });
  supervisor.add(vite);
  await supervisor.stop();
  assert.deepEqual(api.signals, ["SIGTERM"]);
  assert.deepEqual(vite.signals, ["SIGTERM"]);
});

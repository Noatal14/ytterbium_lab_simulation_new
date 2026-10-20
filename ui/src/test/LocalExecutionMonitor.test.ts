import { describe, expect, it } from "vitest";
import { monitorCopy } from "../components/IndividualZeemanRun";
import { mot2dMonitorCopy } from "../components/IndividualMot2DRun";
import { mot3dMonitorCopy } from "../components/IndividualMot3DRun";

describe.each([monitorCopy, mot2dMonitorCopy, mot3dMonitorCopy])(
  "local execution monitor",
  (copy) => {
    it("does not claim a local worker is active after telemetry is lost", () => {
      const observed = copy("running", "local", false);
      expect(observed.title).toBe("Local execution needs inspection");
      expect(JSON.stringify(observed)).toContain("Do not resubmit");
      expect(observed.attention).toBe(true);
    });
    it("describes uncertain local outcomes without referring to Zeus", () => {
      const observed = copy("outcome_unknown", "local", false);
      expect(JSON.stringify(observed)).not.toContain("Zeus");
      expect(observed.attention).toBe(true);
    });
    it("keeps actual local progress and Zeus monitoring separate", () => {
      expect(copy("running", "local", true).title).toBe("Run is in progress");
      expect(copy("running", "zeus", false).title).toBe("Run is in progress");
    });
  },
);

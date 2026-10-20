import { describe, expect, it } from "vitest";
import { isIndividualZeusResources } from "../api/clients/individualZeusResources";

describe("reviewed scalar reservation boundary", () => {
  const valid = { queue: "zeus_combined_q", cores: 200, memory_bytes: 68719476736, walltime_seconds: 28800 };
  it("accepts validated quantities", () => expect(isIndividualZeusResources(valid)).toBe(true));
  it.each([null, {}, { ...valid, cores: 0 }, { ...valid, cores: 1.5 },
    { ...valid, memory_bytes: NaN }, { ...valid, walltime_seconds: -1 },
    { ...valid, queue: "x; qsub" }, { ...valid, command: "qsub" }])(
    "rejects incomplete or unsafe reservations %j", (value) => expect(isIndividualZeusResources(value)).toBe(false),
  );
});

import { expect, it } from "vitest";
import { localWorkerMaximum } from "../features/individual/localWorkerAdmission";
it("bounds advisory workers per host and particles with safe unknown-CPU fallback", () => {
  expect(localWorkerMaximum(1, 256, 16)).toBe(1);
  expect(localWorkerMaximum(20, 256, 4)).toBe(4);
  expect(localWorkerMaximum(1000, 256, 512)).toBe(256);
  for (const cpu of [0, -1, NaN, 1.5])
    expect(localWorkerMaximum(20, 256, cpu)).toBe(1);
  for (const count of [0, -1, NaN, 1.5])
    expect(localWorkerMaximum(count, 256, 4)).toBe(4);
});

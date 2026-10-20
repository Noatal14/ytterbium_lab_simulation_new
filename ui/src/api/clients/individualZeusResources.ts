import { exactKeys, isRecord } from "../http/envelope";

export type IndividualZeusResources = {
  queue: string;
  cores: number;
  memory_bytes: number;
  walltime_seconds: number;
  vnode?: "gd002";
};

export function isIndividualZeusResources(value: unknown): value is IndividualZeusResources {
  return isRecord(value) && (exactKeys(value, ["queue", "cores", "memory_bytes", "walltime_seconds"]) || (exactKeys(value, ["queue", "cores", "memory_bytes", "walltime_seconds", "vnode"]) && value.vnode === "gd002"))
    && typeof value.queue === "string" && /^[A-Za-z0-9_]+$/.test(value.queue)
    && [value.cores, value.memory_bytes, value.walltime_seconds].every(
      (number) => typeof number === "number" && Number.isSafeInteger(number) && number > 0,
    );
}

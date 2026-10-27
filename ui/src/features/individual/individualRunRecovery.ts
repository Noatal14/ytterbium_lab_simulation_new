import { individualZeusConfirmWasDefinitelyRejected } from "../../api/clients/individualZeusRecovery";

export type RecoverableRunFamily = "zeeman" | "mot_2d" | "mot_3d";
export type RecoverableExecutionMode = "local" | "zeus";

type StoredRun = {
  version: 1;
  family: RecoverableRunFamily;
  display_name: string;
  execution_mode: RecoverableExecutionMode;
  username?: string;
};

export type RememberedIndividualRun = StoredRun;

export type RecoverableRun = {
  id: string;
  display_name: string;
  lifecycle: string;
  record_state: string;
  execution: {
    mode: RecoverableExecutionMode;
    locally_scheduled?: boolean;
    progress?: unknown;
  };
};

export function recoveredRunStep(
  run: RecoverableRun,
): "run" | "monitor" | "results" {
  if (run.lifecycle === "results_ready") return "results";
  if (run.execution.mode === "local" && run.execution.locally_scheduled)
    return "monitor";
  if (["configured", "validated", "reviewed"].includes(run.record_state))
    return "run";
  return "monitor";
}

const key = (family: RecoverableRunFamily) =>
  `ytterbium.individual-run.${family}.v1`;
const identifiers: Record<RecoverableRunFamily, RegExp> = {
  zeeman: /^zeeman-[a-z0-9-]{1,120}$/,
  mot_2d: /^mot2d-[a-z0-9-]{1,120}$/,
  mot_3d: /^mot3d-[a-z0-9-]{1,120}$/,
};

const usernamePattern = /^[A-Za-z][A-Za-z0-9._-]{0,31}$/;

export const individualRunStorageWarning =
  "Browser recovery storage is unavailable. Keep this page open and record the run identity before leaving.";

export function rememberIndividualRun(
  family: RecoverableRunFamily,
  displayName: string,
  executionMode: RecoverableExecutionMode,
  username?: string,
) {
  if (!identifiers[family].test(displayName))
    throw new Error("The run identity is not safe to remember.");
  if (
    executionMode === "zeus" &&
    (!username || !usernamePattern.test(username))
  )
    throw new Error("The Zeus profile is not safe to remember.");
  if (executionMode === "local" && username !== undefined)
    throw new Error("A local run cannot remember a Zeus profile.");
  const value: StoredRun = {
    version: 1,
    family,
    display_name: displayName,
    execution_mode: executionMode,
    ...(username ? { username } : {}),
  };
  try {
    window.localStorage.setItem(key(family), JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function forgetIndividualRun(family: RecoverableRunFamily) {
  try {
    window.localStorage.removeItem(key(family));
  } catch {
    /* Storage may be disabled. */
  }
}

export async function confirmRememberedZeusRun(
  family: RecoverableRunFamily,
  displayName: string,
  username: string,
  confirm: () => Promise<unknown>,
) {
  if (!rememberIndividualRun(family, displayName, "zeus", username))
    throw new Error(
      individualRunStorageWarning + " Zeus submission was not attempted.",
    );
  try {
    return await confirm();
  } catch (cause) {
    if (individualZeusConfirmWasDefinitelyRejected(cause))
      forgetIndividualRun(family);
    throw cause;
  }
}

export function readRememberedIndividualRun(
  family: RecoverableRunFamily,
): RememberedIndividualRun | null {
  let encoded: string | null;
  try {
    encoded = window.localStorage.getItem(key(family));
  } catch {
    return null;
  }
  if (!encoded) return null;
  try {
    const value = JSON.parse(encoded) as Partial<StoredRun>;
    if (
      value.version !== 1 ||
      value.family !== family ||
      !identifiers[family].test(String(value.display_name)) ||
      !["local", "zeus"].includes(String(value.execution_mode)) ||
      (value.execution_mode === "zeus"
        ? !usernamePattern.test(String(value.username))
        : value.username !== undefined)
    )
      throw new Error("invalid");
    return value as StoredRun;
  } catch {
    forgetIndividualRun(family);
    return null;
  }
}

export async function recoverIndividualRun<Run extends RecoverableRun>(
  family: RecoverableRunFamily,
  api: {
    runs(): Promise<Run[]>;
    catalog?: () => Promise<{
      runs: Run[];
      invalid_count: number;
      total: number;
      truncated: boolean;
    }>;
    run(id: string): Promise<Run>;
  },
  isCurrent: () => boolean = () => true,
) {
  const stored = readRememberedIndividualRun(family);
  if (!stored) return null;
  const catalog = api.catalog
    ? await api.catalog()
    : { runs: await api.runs(), invalid_count: 0, total: 0, truncated: false };
  // A retired mount must not start a detail read and supersede the active
  // mount's SDK request. Catalog reads can finish after StrictMode cleanup.
  if (!isCurrent()) return null;
  const matches = catalog.runs.filter(
    (row) => row.display_name === stored.display_name,
  );
  if (matches.length === 0) {
    const incomplete = catalog.truncated || catalog.invalid_count > 0;
    throw new Error(
      incomplete
        ? "The run catalog is incomplete, so the remembered run cannot be verified yet. It remains remembered and was not restarted. Retry after resolving the catalog warning."
        : "The remembered run is not visible in the current verified catalog. It remains remembered and was not restarted.",
    );
  }
  if (
    matches.length !== 1 ||
    matches[0].execution.mode !== stored.execution_mode
  ) {
    forgetIndividualRun(family);
    throw new Error(
      "The remembered run could not be matched to one verified run record. It was not restarted.",
    );
  }
  const summary = matches[0];
  if (summary.lifecycle !== "results_ready") return summary;
  if (!isCurrent()) return null;
  const detail = await api.run(summary.id);
  if (!isCurrent()) return null;
  if (
    detail.id !== summary.id ||
    detail.display_name !== stored.display_name ||
    detail.execution.mode !== stored.execution_mode
  ) {
    forgetIndividualRun(family);
    throw new Error(
      "The verified run details did not match the remembered run. It was not restarted.",
    );
  }
  return detail;
}

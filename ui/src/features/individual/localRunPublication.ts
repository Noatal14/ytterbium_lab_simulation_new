import { useEffect, useRef, useState } from "react";
export const localRunPublicationMessage =
  "Verifying the new local run. Do not start it again.";

/** Only an acknowledged new local start can open this short observation window. */
export class LocalRunPublication {
  private startedAt: number | null = null;
  private missingReads = 0;
  private runId: string | null = null;
  private generation = 0;
  get revision() {
    return this.generation;
  }
  matches(runId: string) {
    return this.active && this.runId === runId;
  }
  start(runId: string, now = Date.now()) {
    this.generation += 1;
    this.runId = runId;
    this.startedAt = now;
    this.missingReads = 0;
  }
  get active() {
    return this.startedAt !== null;
  }
  finish() {
    this.generation += 1;
    this.startedAt = null;
    this.runId = null;
  }
  missing(cleanCatalog: boolean, now = Date.now()) {
    if (this.startedAt === null) return false;
    this.missingReads += 1;
    if (
      !cleanCatalog ||
      now < this.startedAt ||
      now - this.startedAt >= 5000 ||
      this.missingReads >= 3
    ) {
      this.finish();
      return false;
    }
    return true;
  }
}

type Catalog<T> = { runs: T[]; invalid_count: number; truncated: boolean };
export async function observeNewLocalRun<T extends { display_name: string }>(
  api: { runs: () => Promise<T[]>; catalog?: () => Promise<Catalog<T>> },
  runId: string,
  publication: LocalRunPublication = new LocalRunPublication(),
  isCurrent: () => boolean,
  mode: "local" | "zeus" = "local",
): Promise<{ summary: T | null; waiting: boolean; retired?: boolean }> {
  if (mode !== "local" || (publication.active && !publication.matches(runId)))
    publication.finish();
  const revision = publication.revision;
  let catalog: Catalog<T> | null;
  let rows: T[];
  try {
    catalog = publication.active && api.catalog ? await api.catalog() : null;
    rows = catalog ? catalog.runs : await api.runs();
  } catch (error) {
    if (!isCurrent() || revision !== publication.revision)
      return { summary: null, waiting: false, retired: true };
    throw error;
  }
  if (!isCurrent() || revision !== publication.revision)
    return { summary: null, waiting: false, retired: true };
  const summary = rows.find((row) => row.display_name === runId) ?? null;
  if (summary) publication.finish();
  return {
    summary,
    waiting:
      !summary &&
      publication.missing(
        catalog?.invalid_count === 0 && catalog.truncated === false,
      ),
  };
}

/** Context changes retire all outstanding publication observations. */
export function useLocalRunPublication(
  api: object,
  mode: "local" | "zeus",
  runId: string | null,
) {
  const publication = useRef(new LocalRunPublication());
  const [publicationPending, setPublicationPending] = useState(false);
  useEffect(() => {
    const lease = publication.current;
    lease.finish();
    setPublicationPending(false);
    return () => lease.finish();
  }, [api, mode, runId]);
  return { publication, publicationPending, setPublicationPending };
}

/** Real SDK/parsers and captured public DTOs; only fetch timing is controlled. */
import { StrictMode, useEffect, useState } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createIndividualZeemanApi } from "../api/clients/individualZeeman";
import { createIndividualMot2DApi } from "../api/clients/individualMot2D";
import { createIndividualMot3DApi } from "../api/clients/individualMot3D";
import { IndividualZeemanRun } from "../components/IndividualZeemanRun";
import { IndividualMot3DRun } from "../components/IndividualMot3DRun";
import { IndividualMot2DRun } from "../components/IndividualMot2DRun";
import {
  forgetIndividualRun,
  rememberIndividualRun,
  recoverIndividualRun,
  type RecoverableRun,
} from "../features/individual/individualRunRecovery";
import fixtures from "./fixtures/individualRecovery.actual-public-v1.json";

const clients = [
  ["zeeman", createIndividualZeemanApi],
  ["mot_2d", createIndividualMot2DApi],
  ["mot_3d", createIndividualMot3DApi],
] as const;
type Family = (typeof clients)[number][0];
type RecoveryApi = {
  runs(): Promise<RecoverableRun[]>;
  catalog(): Promise<{
    runs: RecoverableRun[];
    invalid_count: number;
    total: number;
    truncated: boolean;
  }>;
  run(id: string): Promise<RecoverableRun>;
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const envelope = (data: unknown) =>
  new Response(JSON.stringify({ api_version: 1, data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
function controlledReads(family: Family) {
  const fixture = fixtures[family],
    retiredCatalog = deferred<Response>(),
    activeCatalog = deferred<Response>(),
    activeDetail = deferred<Response>();
  let catalogs = 0,
    details = 0;
  const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    expect(init?.method ?? "GET").toBe("GET");
    const pathname = new URL(String(input), "http://localhost").pathname;
    if (pathname.endsWith("/sources"))
      return Promise.resolve(
        envelope({
          contract_version: `${family === "mot_2d" ? "mot-2d" : "mot-3d"}-individual-source-catalog-v1`,
          sources: [],
          invalid_count: 0,
          total: 0,
          truncated: false,
        }),
      );
    if (pathname === "/api/v1/individual-runs")
      return ++catalogs === 1 ? retiredCatalog.promise : activeCatalog.promise;
    if (pathname === "/api/v1/individual-runs/" + fixture.summary.id)
      return ++details === 1
        ? activeDetail.promise
        : Promise.resolve(envelope(fixture.detail));
    throw new Error("Unexpected request " + pathname);
  });
  vi.stubGlobal("fetch", fetcher);
  rememberIndividualRun(family, fixture.detail.display_name, "zeus", "tal.noa");
  const catalog = () =>
    envelope({
      runs: [fixture.summary],
      invalid_count: 0,
      total: 1,
      truncated: false,
    });
  return {
    fixture,
    retiredCatalog,
    activeCatalog,
    activeDetail,
    catalog,
    catalogCount: () => catalogs,
    detailCount: () => details,
    fetcher,
  };
}
function RecoveryMount({ family, api }: { family: Family; api: RecoveryApi }) {
  const [found, setFound] = useState<RecoverableRun | null>(null),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    void recoverIndividualRun(family, api, () => current)
      .then((row) => {
        if (current) setFound(row);
      })
      .catch((e) => {
        if (current) setError(String(e));
      });
    return () => {
      current = false;
    };
  }, [family, api]);
  return (
    <>
      {found?.lifecycle === "results_ready" && (
        <h1>Verified results are ready</h1>
      )}
      {error && <p role="alert">{error}</p>}
    </>
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  for (const [family] of clients) forgetIndividualRun(family);
});
for (const [family, create] of clients)
  describe(family + " inactive recovery timing with real SDK", () => {
    it("shares the StrictMode catalog while only the active recovery reads detail", async () => {
      const reads = controlledReads(family),
        api: RecoveryApi = create(async () => "unused-readonly");
      render(
        <StrictMode>
          <RecoveryMount family={family} api={api} />
        </StrictMode>,
      );
      await waitFor(() => expect(reads.catalogCount()).toBe(1));
      await act(async () => {
        reads.retiredCatalog.resolve(reads.catalog());
      });
      await waitFor(() => expect(reads.detailCount()).toBe(1));
      expect(reads.catalogCount()).toBe(1);
      expect(reads.detailCount()).toBe(1);
      await act(async () => {
        reads.activeDetail.resolve(envelope(reads.fixture.detail));
      });
      expect(
        await screen.findByRole("heading", {
          name: "Verified results are ready",
        }),
      ).toBeTruthy();
      expect(screen.queryByRole("alert")).toBeNull();
    });
    it("returns null for a retired helper without issuing its detail request", async () => {
      const reads = controlledReads(family),
        api: RecoveryApi = create(async () => "unused-readonly");
      let current = true;
      const result = recoverIndividualRun(family, api, () => current);
      current = false;
      reads.retiredCatalog.resolve(reads.catalog());
      await expect(result).resolves.toBeNull();
      expect(reads.detailCount()).toBe(0);
    });
    it("keeps the real SDK exact public-ID rejection", async () => {
      const reads = controlledReads(family),
        api: RecoveryApi = create(async () => "unused-readonly");
      const result = recoverIndividualRun(family, api);
      reads.retiredCatalog.resolve(reads.catalog());
      await waitFor(() => expect(reads.detailCount()).toBe(1));
      reads.activeDetail.resolve(
        envelope({
          ...reads.fixture.detail,
          id: "individual-run-" + "f".repeat(24),
        }),
      );
      await expect(result).rejects.toThrow();
    });
  });
for (const [family] of clients)
  it(
    "the actual " +
      family +
      " component shares the StrictMode catalog and retires inactive detail reads",
    async () => {
      const reads = controlledReads(family);
      const ui =
        family === "zeeman" ? (
          <IndividualZeemanRun
            api={createIndividualZeemanApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        ) : family === "mot_2d" ? (
          <IndividualMot2DRun
            api={createIndividualMot2DApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        ) : (
          <IndividualMot3DRun
            api={createIndividualMot3DApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        );
      render(<StrictMode>{ui}</StrictMode>);
      await waitFor(() => expect(reads.catalogCount()).toBe(1));
      await act(async () => {
        reads.retiredCatalog.resolve(reads.catalog());
      });
      await waitFor(() => expect(reads.detailCount()).toBe(1));
      expect(reads.catalogCount()).toBe(1);
      expect(reads.detailCount()).toBe(1);
      await act(async () => {
        reads.activeDetail.resolve(envelope(reads.fixture.detail));
      });
      expect(
        await screen.findByRole("heading", {
          name: "Verified results are ready",
        }),
      ).toBeTruthy();
      expect(
        screen.queryByRole("button", {
          name: "Confirm and submit one Zeus job",
        }),
      ).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Start on this computer" }),
      ).toBeNull();
    },
  );
for (const [family, create] of clients)
  it(
    family + " unmount retires a pending catalog without a detail read",
    async () => {
      const reads = controlledReads(family),
        api: RecoveryApi = create(async () => "unused-readonly");
      const mounted = render(<RecoveryMount family={family} api={api} />);
      await waitFor(() => expect(reads.catalogCount()).toBe(1));
      mounted.unmount();
      await act(async () => {
        reads.retiredCatalog.resolve(reads.catalog());
      });
      expect(reads.detailCount()).toBe(0);
    },
  );

for (const [family] of clients)
  it(
    "the actual " +
      family +
      " component does not issue an old detail read after leaving the page",
    async () => {
      const reads = controlledReads(family);
      const ui =
        family === "zeeman" ? (
          <IndividualZeemanRun
            api={createIndividualZeemanApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        ) : family === "mot_2d" ? (
          <IndividualMot2DRun
            api={createIndividualMot2DApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        ) : (
          <IndividualMot3DRun
            api={createIndividualMot3DApi(async () => "unused-readonly")}
            onBack={() => {}}
          />
        );
      const mounted = render(ui);
      await waitFor(() => expect(reads.catalogCount()).toBe(1));
      mounted.unmount();
      await act(async () => {
        reads.retiredCatalog.resolve(reads.catalog());
      });
      expect(reads.detailCount()).toBe(0);
    },
  );

for (const [family] of clients)
  it(`${family} returns to configuration when its old local bookmark was removed`, async () => {
    rememberIndividualRun(
      family,
      fixtures[family].detail.display_name,
      "local",
    );
    const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/v1/individual-runs")
        return Promise.resolve(
          envelope({ runs: [], total: 0, invalid_count: 0, truncated: false }),
        );
      if (path.endsWith("/sources"))
        return Promise.resolve(
          envelope({
            contract_version: `${family === "mot_2d" ? "mot-2d" : "mot-3d"}-individual-source-catalog-v1`,
            sources: [],
            invalid_count: 0,
            total: 0,
            truncated: false,
          }),
        );
      throw new Error(`Unexpected request ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);
    const ui =
      family === "zeeman" ? (
        <IndividualZeemanRun
          api={createIndividualZeemanApi(async () => "unused")}
          onBack={() => {}}
        />
      ) : family === "mot_2d" ? (
        <IndividualMot2DRun
          api={createIndividualMot2DApi(async () => "unused")}
          onBack={() => {}}
        />
      ) : (
        <IndividualMot3DRun
          api={createIndividualMot3DApi(async () => "unused")}
          onBack={() => {}}
        />
      );
    render(<StrictMode>{ui}</StrictMode>);
    await waitFor(() =>
      expect(
        screen.getByRole("spinbutton", { name: /Particle count/ }),
      ).toBeVisible(),
    );
    expect(
      screen.queryByRole("button", { name: "Check status" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET"),
    ).toBe(true);
  });

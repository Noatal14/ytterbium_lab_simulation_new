import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import contract from "./teamContractFixture";
import captured from "../../../tests/contracts/v1/finalization_collection_v1.json";
import { createFinalizationCollectionApi } from "../api/clients/production";
import {
  parseFinalizationCollectionPreview,
  parseFinalizationCollectionResult,
  parseFinalizationStatus,
  parseFinalizationPreview,
  parseProductionPreview,
  parseProductionResult,
  parseProductionStatus,
  parseProductionSubmissionPreview,
  parseProductionSubmissionResult,
  parseProductionSubmissionStatus,
  parseZeusSnapshot,
} from "../api/schema/domain";
import { useProductionController } from "../features/campaign/controllers/useProductionController";
import { ProductionStage } from "../features/campaign/ProductionStage";

const data = (id: string) =>
  structuredClone(
    contract.cases.find((row) => row.id === id)!.body.data,
  ) as Record<string, unknown>;
const snapshot = parseZeusSnapshot(data("zeus-snapshot"));
const manifest = "data/optimization/mot_2d/campaign/campaign.json";
function previewValue() {
  const files = [
    { path: manifest, sha256: "a".repeat(64), size: 100 },
    {
      path: "data/optimization/mot_2d/campaign/final_report.json",
      sha256: "b".repeat(64),
      size: 50,
    },
    {
      path: "data/optimization/mot_2d/campaign/production/s0_1p300000/states.npy",
      sha256: "c".repeat(64),
      size: 128,
    },
  ];
  return {
    preview_token: "collection-token",
    expires_in_seconds: 300,
    campaign: {
      id: "campaign-id",
      name: "Campaign",
      git_commit: "a".repeat(40),
      stage: "complete",
    },
    source: {
      finalization_receipt_sha256: "b".repeat(64),
      complete_manifest_sha256: "a".repeat(64),
      registry_sha256: "c".repeat(64),
      bundle_sha256: "d".repeat(64),
    },
    artifacts: {
      files,
      file_count: 3,
      total_bytes: 278,
      maximum_file_bytes: 128,
      create: [files[1].path],
      identical: [files[2].path],
      update: [manifest],
    },
    effects: {
      collect_verified_outputs: true,
      submit_job: false,
      start_simulation: false,
    },
    local_sync: { status: "not_synchronized" },
  };
}
const resultValue = () => ({
  status: "collected",
  campaign_id: "campaign-id",
  stage: "complete",
  submitted_to_zeus: false,
  simulation_started: false,
  local_sync: { status: "synchronized", receipt_sha256: "e".repeat(64) },
  artifacts: { created: 1, identical: 1, updated: 1 },
});
function completeValue(synchronized = false) {
  const v = data("finalization-status");
  v.campaign = { ...(v.campaign as object), stage: "complete" };
  (v.production as Record<string, unknown>).status = "campaign_complete";
  v.results = data("finalization-confirm").results;
  v.next_action = "none";
  if (synchronized)
    v.local_sync = { status: "synchronized", receipt_sha256: "e".repeat(64) };
  return v;
}
const envelope = (v: unknown, status = 200) =>
  new Response(JSON.stringify({ api_version: 1, data: v }), { status });
const deferred = <T,>() => {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
};
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("strict local collection contracts", () => {
  it("accepts exact descriptor totals/partition and only receipt-bound synchronized results", () => {
    expect(
      parseFinalizationCollectionPreview(previewValue()).artifacts.total_bytes,
    ).toBe(278);
    expect(
      parseFinalizationCollectionResult(resultValue()).local_sync.status,
    ).toBe("synchronized");
    expect(parseFinalizationStatus(completeValue(true)).local_sync).toEqual(
      resultValue().local_sync,
    );
    expect(() =>
      parseFinalizationStatus({
        ...data("finalization-status"),
        local_sync: resultValue().local_sync,
      }),
    ).toThrow();
    expect(() =>
      parseFinalizationCollectionResult({
        ...resultValue(),
        local_sync: { status: "synchronized" },
      }),
    ).toThrow();
    expect(() =>
      parseFinalizationCollectionResult({
        ...resultValue(),
        simulation_started: true,
      }),
    ).toThrow();
  });
  it.each([
    [
      "count",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.file_count++;
      },
    ],
    [
      "total",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.total_bytes++;
      },
    ],
    [
      "maximum",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.maximum_file_bytes++;
      },
    ],
    [
      "duplicate",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.files[1] = v.artifacts.files[0];
      },
    ],
    [
      "missing partition",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.create = [];
      },
    ],
    [
      "extra partition",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.create.push("foreign.json");
      },
    ],
    [
      "overlapping partition",
      (v: ReturnType<typeof previewValue>) => {
        v.artifacts.identical = [...v.artifacts.create];
      },
    ],
    [
      "manifest hash",
      (v: ReturnType<typeof previewValue>) => {
        v.source.complete_manifest_sha256 = "f".repeat(64);
      },
    ],
    [
      "extra field",
      (v: ReturnType<typeof previewValue>) => {
        Object.assign(v.effects, { overwrite: true });
      },
    ],
  ] as const)("rejects %s drift", (_name, mutate) => {
    const v = previewValue();
    mutate(v);
    expect(() => parseFinalizationCollectionPreview(v)).toThrow();
  });
  it.each(["D:foo", "/absolute", "a\\b", "a//b", "a/./b", "a/../b", "a\0b"])(
    "rejects unsafe path %s",
    (path) => {
      const v = previewValue();
      v.artifacts.files[1].path = path;
      v.artifacts.create = [path];
      expect(() => parseFinalizationCollectionPreview(v)).toThrow();
    },
  );
  it.each([true, "128", 1.5, -1, 8388609])(
    "rejects non-integer/oversized file bytes %s",
    (size) => {
      const v = previewValue();
      Object.assign(v.artifacts.files[1], { size });
      expect(() => parseFinalizationCollectionPreview(v)).toThrow();
    },
  );
});

it("binds explicit profile and reviewed counts, consumes confirm once, and labels malformed replies unknown", async () => {
  const api = createFinalizationCollectionApi(async () => "csrf");
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(envelope(previewValue()))
    .mockResolvedValueOnce(
      new Response('{"api_version":1,"data":', { status: 201 }),
    );
  vi.stubGlobal("fetch", fetch);
  const p = await api.preview("campaign-id", snapshot.profile);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    campaign_id: "campaign-id",
    username: snapshot.profile.username,
    project_directory: snapshot.profile.project_directory,
  });
  await expect(api.confirm(p.preview_token)).rejects.toMatchObject({
    code: "collection_outcome_unknown",
  });
  await expect(api.confirm(p.preview_token)).rejects.toThrow(
    /no longer active/,
  );
  expect(fetch).toHaveBeenCalledTimes(2);
});
it.each(["campaign", "counts"])(
  "rejects a collected response with mismatched %s without claiming synchronization",
  async (kind) => {
    const api = createFinalizationCollectionApi(async () => "csrf"),
      result = resultValue();
    if (kind === "campaign") result.campaign_id = "other";
    else result.artifacts.created++;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(envelope(previewValue()))
        .mockResolvedValueOnce(envelope(result, 201)),
    );
    const p = await api.preview("campaign-id", snapshot.profile);
    await expect(api.confirm(p.preview_token)).rejects.toMatchObject({
      code: "collection_outcome_unknown",
    });
  },
);
it("retires an in-flight client review after reset without leaving a confirmable token", async () => {
  const d = deferred<Response>(),
    api = createFinalizationCollectionApi(async () => "csrf");
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(d.promise));
  const p = api.preview("campaign-id", snapshot.profile);
  await Promise.resolve();
  api.reset();
  d.resolve(envelope(previewValue()));
  await expect(p).rejects.toThrow(/stale/);
  await expect(api.confirm("collection-token")).rejects.toThrow(
    /no longer active/,
  );
});

function setup() {
  const api = {
    status: vi
      .fn()
      .mockResolvedValue(parseProductionStatus(data("production-status"))),
    preview: vi
      .fn()
      .mockResolvedValue(parseProductionPreview(data("production-preview"))),
    confirm: vi
      .fn()
      .mockResolvedValue(parseProductionResult(data("production-confirm"))),
    reset: vi.fn(),
  };
  const submissionApi = {
    status: vi
      .fn()
      .mockResolvedValue(
        parseProductionSubmissionStatus(data("production-submit-status")),
      ),
    preview: vi
      .fn()
      .mockResolvedValue(
        parseProductionSubmissionPreview(data("production-submit-preview")),
      ),
    confirm: vi
      .fn()
      .mockResolvedValue(
        parseProductionSubmissionResult(data("production-submit-confirm")),
      ),
    reset: vi.fn(),
  };
  const finalizationApi = {
    status: vi.fn().mockResolvedValue(parseFinalizationStatus(completeValue())),
    preview: vi
      .fn()
      .mockResolvedValue(
        parseFinalizationPreview(data("finalization-preview")),
      ),
    confirm: vi.fn(),
    reset: vi.fn(),
  };
  const collectionApi = {
    status: vi.fn().mockResolvedValue(parseFinalizationStatus(completeValue())),
    preview: vi
      .fn()
      .mockResolvedValue(parseFinalizationCollectionPreview(previewValue())),
    confirm: vi
      .fn()
      .mockResolvedValue(parseFinalizationCollectionResult(resultValue())),
    reset: vi.fn(),
  };
  const hook = renderHook(
    ({ profile, id }) =>
      useProductionController({
        campaignId: id,
        snapshot: profile,
        enabled: true,
        api,
        submissionApi,
        finalizationApi,
        collectionApi,
      }),
    { initialProps: { profile: snapshot, id: "campaign-id" } },
  );
  async function ready() {
    await act(() => hook.result.current.preparation.review());
    await act(() => hook.result.current.preparation.confirm());
    await act(() => hook.result.current.submission.refresh());
    await act(() => hook.result.current.finalization.refresh());
  }
  return { hook, api, submissionApi, finalizationApi, collectionApi, ready };
}
it("offers collection only after remote completion, shows exact review, and confirms once", async () => {
  const { hook, collectionApi, finalizationApi, ready } = setup();
  await act(() => hook.result.current.collection.review());
  expect(collectionApi.preview).not.toHaveBeenCalled();
  await ready();
  const view = render(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(
    screen.getByText("Completed on Zeus — local collection not verified"),
  ).toBeVisible();
  expect(collectionApi.preview).not.toHaveBeenCalled();
  await act(() => hook.result.current.collection.review());
  view.rerender(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(
    screen.getByRole("button", { name: "Collect verified outputs" }),
  ).toBeEnabled();
  expect(screen.getByText("278")).toBeVisible();
  expect(screen.getByText("d".repeat(64))).toBeVisible();
  const confirm = hook.result.current.collection.confirm;
  await act(async () => {
    await Promise.all([confirm(), confirm()]);
  });
  await act(() => confirm());
  expect(collectionApi.confirm).toHaveBeenCalledTimes(1);
  expect(finalizationApi.confirm).not.toHaveBeenCalled();
  view.rerender(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(screen.getByText("Local collection verified")).toBeVisible();
});
it("keeps an unknown confirm blocked until status reconciliation, without automatically retrying", async () => {
  const { hook, collectionApi, ready } = setup();
  await ready();
  await act(() => hook.result.current.collection.review());
  collectionApi.confirm.mockRejectedValueOnce(
    new Error("The operation outcome is unknown. Do not retry automatically."),
  );
  await act(() => hook.result.current.collection.confirm());
  const retired = hook.result.current.collection.review;
  await act(() => retired());
  await act(() => hook.result.current.collection.confirm());
  expect(collectionApi.preview).toHaveBeenCalledTimes(1);
  expect(collectionApi.confirm).toHaveBeenCalledTimes(1);
  const view = render(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("outcome is unknown");
  expect(
    screen.queryByText("Local collection verified"),
  ).not.toBeInTheDocument();
  collectionApi.status.mockResolvedValueOnce(
    parseFinalizationStatus(completeValue(true)),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Check current status" }),
  );
  view.rerender(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(screen.getByText("Local collection verified")).toBeVisible();
  expect(collectionApi.confirm).toHaveBeenCalledTimes(1);
});
it.each(["profile", "campaign"])(
  "discards late collection previews and retired callbacks after %s changes",
  async (kind) => {
    const { hook, collectionApi, ready } = setup();
    await ready();
    const d = deferred<ReturnType<typeof parseFinalizationCollectionPreview>>();
    collectionApi.preview.mockReturnValueOnce(d.promise);
    let pending!: Promise<void>;
    const oldReview = hook.result.current.collection.review;
    act(() => {
      pending = oldReview();
    });
    hook.rerender({
      profile:
        kind === "profile"
          ? {
              ...snapshot,
              remote: { ...snapshot.remote, git_commit: "b".repeat(40) },
            }
          : snapshot,
      id: kind === "campaign" ? "other" : "campaign-id",
    });
    await act(async () => {
      d.resolve(parseFinalizationCollectionPreview(previewValue()));
      await pending;
    });
    await act(() => oldReview());
    expect(hook.result.current.collection.preview).toBeNull();
    expect(collectionApi.preview).toHaveBeenCalledTimes(1);
    expect(collectionApi.confirm).not.toHaveBeenCalled();
  },
);

it("retires an older synchronized receipt while checking and after an authoritative invalid output observation", async () => {
  const { hook, finalizationApi, collectionApi, ready } = setup();
  finalizationApi.status.mockResolvedValue(
    parseFinalizationStatus(completeValue(true)),
  );
  await ready();
  const view = render(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(screen.getByText("Local collection verified")).toBeVisible();
  const retiredReview = hook.result.current.collection.review;
  const pending = deferred<ReturnType<typeof parseFinalizationStatus>>();
  collectionApi.status.mockReturnValueOnce(pending.promise);
  let reading!: Promise<void>;
  act(() => {
    reading = hook.result.current.collection.refresh();
  });
  view.rerender(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(
    screen.queryByText("Local collection verified"),
  ).not.toBeInTheDocument();
  const value = data("finalization-status");
  (value.production as Record<string, unknown>).status = "outputs_invalid";
  value.validation = {
    status: "invalid",
    completed_ensembles: 0,
    expected_ensembles: 20,
  };
  value.next_action = "wait";
  await act(async () => {
    pending.resolve(parseFinalizationStatus(value));
    await reading;
  });
  view.rerender(
    <ProductionStage visible flow={hook.result.current} onViewJobs={vi.fn()} />,
  );
  expect(
    screen.queryByText("Local collection verified"),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Local collection could not be verified",
  );
  await act(() => hook.result.current.collection.review());
  await act(() => retiredReview());
  expect(collectionApi.preview).not.toHaveBeenCalled();
});

it("accepts the captured hermetic backend producer DTOs with complete registry and receipt crosslinks", () => {
  vi.stubEnv("MODE", "ui-acceptance");
  const preview = parseFinalizationCollectionPreview(captured.preview);
  const result = parseFinalizationCollectionResult(captured.confirm);
  const status = parseFinalizationStatus(captured.status);
  expect(preview.artifacts.file_count).toBe(133);
  expect(preview.artifacts.files).toHaveLength(preview.artifacts.file_count);
  expect(preview.campaign.id).toBe(result.campaign_id);
  expect(result.artifacts.created).toBe(preview.artifacts.create.length);
  expect(result.artifacts.identical).toBe(preview.artifacts.identical.length);
  expect(status.local_sync).toEqual(result.local_sync);
  expect(status.production.status).toBe("campaign_complete");
  expect(status.campaign.id).toBe(result.campaign_id);
});

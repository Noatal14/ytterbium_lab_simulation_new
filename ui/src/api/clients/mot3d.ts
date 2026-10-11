import { postData } from "../http/envelope";
import { boundedPrintable, exactKeys, text } from "../schema/common";

export type Mot3DSource = {
  source_id: string;
  campaign_name: string;
  s0: number;
  sealed_ensemble_count: 20;
  completion: "complete";
  provenance_fingerprint: string;
};

export type Mot3DBootstrapStatus = {
  lifecycle: "ready" | "blocked_missing_approved_timestep";
  sources: Mot3DSource[];
  reason: string | null;
  evidence_requirement: string | null;
};

export type Mot3DBootstrapPreview = {
  preview_token: string;
  expires_in_seconds: number;
  campaign: { name: string; stage: "discovery" };
  source: Mot3DSource;
  discovery: {
    families: ["angled_donut", "single_pass"];
    solver: string;
    screening_dt_s: number;
    production_dt_s: number;
    input_role_counts: { discovery: 12; refinement: 4; preliminary_check: 4 };
  };
  artifacts: { create: string[] };
  effects: {
    create_campaign: true;
    submit_job: false;
    start_simulation: false;
    prepare_dt_validation: false;
  };
};

export type Mot3DBootstrapResult = {
  lifecycle: "discovery_prepared";
  campaign_name: string;
  stage: "discovery";
  submitted_to_zeus: false;
  bootstrap_key: string;
};

const SHA256 = /^[0-9a-f]{64}$/;
const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const FILES = [
  "campaign.json",
  "jobs/01_smoke_angled_donut.pbs",
  "jobs/01_smoke_single_pass.pbs",
  "jobs/02_submit_discovery_chain.sh",
  "jobs/angled_donut/round_01.pbs",
  "jobs/angled_donut/round_02.pbs",
  "jobs/single_pass/round_01.pbs",
  "jobs/single_pass/round_02.pbs",
  "jobs/single_pass/round_03.pbs",
] as const;

function exactObject(
  value: unknown,
  keys: string[],
  message: string,
): Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, keys)
  )
    throw new Error(message);
  return value as Record<string, unknown>;
}

const finitePositive = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value > 0;
const integer = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value);

function nullableText(value: unknown): value is string | null {
  return value === null || boundedPrintable(value, 512);
}

function parseSource(value: unknown): Mot3DSource {
  const row = exactObject(
    value,
    [
      "source_id",
      "campaign_name",
      "s0",
      "sealed_ensemble_count",
      "completion",
      "provenance_fingerprint",
    ],
    "Invalid 3D source response.",
  );
  if (
    !text(row.source_id) ||
    !SHA256.test(row.source_id) ||
    !boundedPrintable(row.campaign_name, 128) ||
    row.campaign_name.length === 0 ||
    !finitePositive(row.s0) ||
    row.sealed_ensemble_count !== 20 ||
    row.completion !== "complete" ||
    !text(row.provenance_fingerprint) ||
    !SHA256.test(row.provenance_fingerprint)
  )
    throw new Error("Invalid 3D source response.");
  return row as Mot3DSource;
}

export function parseMot3DBootstrapStatus(
  value: unknown,
): Mot3DBootstrapStatus {
  const row = exactObject(
    value,
    ["lifecycle", "sources", "reason", "evidence_requirement"],
    "Invalid 3D bootstrap status.",
  );
  if (
    (row.lifecycle !== "ready" &&
      row.lifecycle !== "blocked_missing_approved_timestep") ||
    !Array.isArray(row.sources) ||
    !nullableText(row.reason) ||
    !nullableText(row.evidence_requirement)
  )
    throw new Error("Invalid 3D bootstrap status.");
  const sources = row.sources.map(parseSource);
  if (
    new Set(sources.map((source) => source.source_id)).size !== sources.length
  )
    throw new Error("Invalid 3D bootstrap status.");
  if (
    row.lifecycle === "ready"
      ? row.reason !== null || row.evidence_requirement !== null
      : row.reason === null || row.evidence_requirement === null
  )
    throw new Error("Invalid 3D bootstrap status.");
  return { ...row, sources } as Mot3DBootstrapStatus;
}

export function parseMot3DBootstrapPreview(
  value: unknown,
  expected: { sourceId: string; campaignName: string },
): Mot3DBootstrapPreview {
  const row = exactObject(
    value,
    [
      "preview_token",
      "expires_in_seconds",
      "campaign",
      "source",
      "discovery",
      "artifacts",
      "effects",
    ],
    "Invalid 3D bootstrap preview.",
  );
  const campaign = exactObject(
    row.campaign,
    ["name", "stage"],
    "Invalid 3D bootstrap preview.",
  );
  const discovery = exactObject(
    row.discovery,
    [
      "families",
      "solver",
      "screening_dt_s",
      "production_dt_s",
      "input_role_counts",
    ],
    "Invalid 3D bootstrap preview.",
  );
  const counts = exactObject(
    discovery.input_role_counts,
    ["discovery", "refinement", "preliminary_check"],
    "Invalid 3D bootstrap preview.",
  );
  const artifacts = exactObject(
    row.artifacts,
    ["create"],
    "Invalid 3D bootstrap preview.",
  );
  const effects = exactObject(
    row.effects,
    [
      "create_campaign",
      "submit_job",
      "start_simulation",
      "prepare_dt_validation",
    ],
    "Invalid 3D bootstrap preview.",
  );
  const source = parseSource(row.source);
  if (
    !text(row.preview_token) ||
    !integer(row.expires_in_seconds) ||
    row.expires_in_seconds <= 0 ||
    !text(campaign.name) ||
    !NAME.test(campaign.name) ||
    campaign.name !== expected.campaignName ||
    campaign.stage !== "discovery" ||
    source.source_id !== expected.sourceId ||
    !Array.isArray(discovery.families) ||
    discovery.families.length !== 2 ||
    discovery.families[0] !== "angled_donut" ||
    discovery.families[1] !== "single_pass" ||
    discovery.solver !== "RK4StHybridCustom" ||
    !finitePositive(discovery.screening_dt_s) ||
    !finitePositive(discovery.production_dt_s) ||
    discovery.screening_dt_s < discovery.production_dt_s ||
    counts.discovery !== 12 ||
    counts.refinement !== 4 ||
    counts.preliminary_check !== 4 ||
    !Array.isArray(artifacts.create) ||
    artifacts.create.length !== FILES.length ||
    artifacts.create.some((name, index) => name !== FILES[index]) ||
    effects.create_campaign !== true ||
    effects.submit_job !== false ||
    effects.start_simulation !== false ||
    effects.prepare_dt_validation !== false
  )
    throw new Error("Invalid 3D bootstrap preview.");
  return {
    ...row,
    campaign,
    source,
    discovery: { ...discovery, input_role_counts: counts },
    artifacts,
    effects,
  } as Mot3DBootstrapPreview;
}

export function parseMot3DBootstrapResult(
  value: unknown,
  expectedName: string,
): Mot3DBootstrapResult {
  const row = exactObject(
    value,
    [
      "lifecycle",
      "campaign_name",
      "stage",
      "submitted_to_zeus",
      "bootstrap_key",
    ],
    "Invalid 3D bootstrap result.",
  );
  if (
    row.lifecycle !== "discovery_prepared" ||
    row.campaign_name !== expectedName ||
    row.stage !== "discovery" ||
    row.submitted_to_zeus !== false ||
    !text(row.bootstrap_key) ||
    !SHA256.test(row.bootstrap_key)
  )
    throw new Error("Invalid 3D bootstrap result.");
  return row as Mot3DBootstrapResult;
}

export function createMot3DBootstrapApi(session: () => Promise<string>) {
  let generation = 0;
  const current = () => generation;
  return {
    reset() {
      generation += 1;
    },
    async status() {
      const request = current();
      const csrf = await session();
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      const result = parseMot3DBootstrapStatus(
        await postData("/api/v1/campaigns/3d/bootstrap/status", {}, csrf),
      );
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      return result;
    },
    async preview(sourceId: string, campaignName: string) {
      const request = current();
      const csrf = await session();
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      const result = parseMot3DBootstrapPreview(
        await postData(
          "/api/v1/campaigns/3d/bootstrap/preview",
          { source_id: sourceId, campaign_name: campaignName },
          csrf,
        ),
        { sourceId, campaignName },
      );
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      return result;
    },
    async confirm(token: string, campaignName: string) {
      const request = current();
      const csrf = await session();
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      const result = parseMot3DBootstrapResult(
        await postData(
          "/api/v1/campaigns/3d/bootstrap/confirm",
          { preview_token: token },
          csrf,
        ),
        campaignName,
      );
      if (request !== current())
        throw new Error("A newer 3D request replaced this response.");
      return result;
    },
  };
}

export type Mot3DBootstrapApi = ReturnType<typeof createMot3DBootstrapApi>;

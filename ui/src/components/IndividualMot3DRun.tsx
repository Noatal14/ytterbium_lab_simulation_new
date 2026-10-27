import {
  localRunNeedsInspection,
  SavedLocalRunNotice,
  useLocalRunInspection,
} from "../features/individual/localRunInspection";
import {
  LocalRunPublication,
  observeNewLocalRun,
  localRunPublicationMessage,
  useLocalRunPublication,
} from "../features/individual/localRunPublication";
import { localWorkerMaximum } from "../features/individual/localWorkerAdmission";
import type { IndividualZeusResources } from "../api/clients/individualZeusResources";
import {
  ArrowLeft,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
  Play,
  Server,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AngledDonutParameters,
  IndividualMot3DApi,
  Mot3DFamily,
  Mot3DMode,
  Mot3DPreview,
  Mot3DRequest,
  Mot3DRun,
  Mot3DSource,
  SinglePassParameters,
} from "../api/clients/individualMot3D";
import { MOT_3D_INDIVIDUAL_SPECIFICATION_V1 as spec } from "../generated/mot3dIndividualSpec.v1";
import { RunProgressPanel } from "./RunProgressPanel";
import {
  individualRunStorageWarning,
  confirmRememberedZeusRun,
  forgetIndividualRun,
  readRememberedIndividualRun,
  recoveredRunStep,
  recoverIndividualRun,
  rememberIndividualRun,
} from "../features/individual/individualRunRecovery";

type Step = "configure" | "validate" | "review" | "run" | "monitor" | "results";
const steps: [Step, string][] = [
  ["configure", "Configure"],
  ["validate", "Validate"],
  ["review", "Review"],
  ["run", "Run"],
  ["monitor", "Monitor"],
  ["results", "Results"],
];
const Help = ({ text }: { text: string }) => (
  <span className="help">
    <button type="button" aria-label="More information">
      <CircleHelp aria-hidden="true" />
    </button>
    <span role="tooltip">{text}</span>
  </span>
);
const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The request could not be completed safely.";

type NumericField = {
  key: keyof AngledDonutParameters | keyof SinglePassParameters;
  label: string;
  unit?: string;
  scale?: number;
  help?: string;
};
const commonFields: NumericField[] = [
  { key: "green_s0", label: "Green intensity (s₀)" },
  { key: "green_detuning_gamma", label: "Green detuning", unit: "Γ" },
  {
    key: "green_waist_m",
    label: "Green waist radius",
    unit: "mm",
    scale: 1000,
    help: "The Gaussian 1/e² radius before the fixed chamber aperture is applied.",
  },
  { key: "blue_s0", label: "Blue intensity (s₀)" },
  {
    key: "blue_waist_m",
    label: "Blue waist radius",
    unit: "mm",
    scale: 1000,
    help: "The Gaussian 1/e² radius before the fixed chamber aperture is applied.",
  },
  { key: "magnetic_gradient_G_cm", label: "Magnetic gradient", unit: "G/cm" },
];
const familyFields: Record<Mot3DFamily, NumericField[]> = {
  angled_donut: [
    { key: "blue_detuning_gamma", label: "Blue detuning", unit: "Γ" },
    {
      key: "core_shell_split_radius_m",
      label: "Core–shell split radius",
      unit: "mm",
      scale: 1000,
      help: "Green light fills the core and blue light begins at this shared boundary.",
    },
  ],
  single_pass: [
    {
      key: "blue_detuning_anchor_gamma",
      label: "Blue detuning anchor",
      unit: "Γ",
      help: "The reviewed reference detuning. The effective detuning is derived from geometry and field.",
    },
    { key: "blue_crossing_angle_deg", label: "Blue crossing angle", unit: "°" },
    {
      key: "blue_crossing_z_offset_m",
      label: "Blue crossing z offset",
      unit: "mm",
      scale: 1000,
    },
  ],
};

const format = (value: number, digits = 6) =>
  Number(value.toPrecision(digits)).toLocaleString("en-US", {
    maximumFractionDigits: 8,
  });

export function mot3dMonitorCopy(
  state: string | undefined,
  executionMode?: string,
  hasLiveProgress = true,
  locallyScheduled = false,
) {
  if (
    executionMode === "local" &&
    locallyScheduled &&
    ["configured", "validated", "reviewed"].includes(state ?? "")
  )
    return {
      title: "Waiting for a local worker",
      message:
        "This run is queued on this computer and will start automatically. Do not submit it again.",
      attention: false,
    };
  if (
    executionMode === "local" &&
    (state === "outcome_unknown" ||
      (state === "running" && !hasLiveProgress && !locallyScheduled))
  )
    return {
      title: "Local execution needs inspection",
      body: "The saved run has no verified active local worker. Do not resubmit. Inspect the original run and its saved results before continuing.",
      attention: true,
    };
  if (state === "held")
    return {
      title: "Zeus job is held",
      body: "Zeus has held this job. Open Zeus jobs to inspect the scheduler reason before continuing.",
      attention: true,
    };
  if (!state)
    return {
      title: "Status has not been checked",
      body: "Select Check status to read the verified run record.",
      attention: true,
    };
  if (state === "configured")
    return {
      title: "Nothing is running yet",
      body: "Action is required: start the reviewed run.",
      attention: true,
    };
  if (state === "queued" || state === "submitted")
    return {
      title: "Run is queued",
      body: "The run is waiting for an execution slot. No action is required.",
      attention: false,
    };
  if (state === "running")
    return {
      title: "Run is in progress",
      body: "The 3D-MOT simulation is running. No action is required.",
      attention: false,
    };
  if (state === "succeeded")
    return {
      title: "Run completed",
      body: "The verified results are ready.",
      attention: false,
    };
  if (state === "failed")
    return {
      title: "Run failed safely",
      body: "Action is required: inspect the failure before deciding whether to create a new run.",
      attention: true,
    };
  if (state === "outcome_unknown")
    return {
      title: "Zeus outcome needs attention",
      body: "Do not resubmit. Inspect the original Zeus job first.",
      attention: true,
    };
  if (state === "cancelled")
    return {
      title: "Run was cancelled",
      body: "No result was produced. Create a new reviewed run if needed.",
      attention: true,
    };
  return {
    title: "Status is not recognized",
    body: "Stop and inspect the verified run record.",
    attention: true,
  };
}

export async function refreshMot3DTransaction(
  api: IndividualMot3DApi,
  mode: Mot3DMode,
  runId: string,
  username: string,
  isCurrent: () => boolean,
  onSchedulerState?: (state: string) => void,
  publication?: LocalRunPublication,
): Promise<Mot3DRun | null> {
  if (mode === "zeus") {
    const scheduler = await api.refreshZeus(runId, username);
    if (!isCurrent()) return null;
    onSchedulerState?.(scheduler.state);
  }
  const { summary, waiting, retired } = await observeNewLocalRun(
    api,
    runId,
    publication ?? new LocalRunPublication(),
    isCurrent,
    mode,
  );
  if (!isCurrent() || waiting || retired) return null;
  if (!summary)
    throw new Error("The run is not visible in the verified run list yet.");
  const next =
    summary.lifecycle === "results_ready" ? await api.run(summary.id) : summary;
  return isCurrent() ? next : null;
}

export function IndividualMot3DRun({
  api,
  onBack,
  onViewZeusJobs,
}: {
  api: IndividualMot3DApi;
  onBack: () => void;
  onViewZeusJobs?: () => void;
}) {
  const title = useRef<HTMLHeadingElement>(null),
    requestSequence = useRef(0),
    mounted = useRef(true);
  const [recoveryPending, setRecoveryPending] = useState(false);
  const { inspectionRun, holdForInspection } =
    useLocalRunInspection<Mot3DRun>(api);

  const [zeusHeld, setZeusHeld] = useState(false);
  const [zeusResources, setZeusResources] =
    useState<IndividualZeusResources | null>(null);
  const [step, setStep] = useState<Step>("configure"),
    [sources, setSources] = useState<Mot3DSource[]>([]),
    [sourceId, setSourceId] = useState("");
  const [family, setFamily] = useState<Mot3DFamily>("angled_donut"),
    [mode, setMode] = useState<Mot3DMode>("local");
  const [particles, setParticles] = useState<number>(
      spec.particle_count.default,
    ),
    [selectionSeed, setSelectionSeed] = useState<number>(
      spec.selection_seed.default,
    ),
    [simulationSeed, setSimulationSeed] = useState<number>(
      spec.simulation_seed.default,
    ),
    [npools, setNpools] = useState<number>(() =>
      Math.min(
        spec.local_worker_count.default,
        localWorkerMaximum(spec.particle_count.default),
      ),
    );
  const [donut, setDonut] = useState<AngledDonutParameters>({
    ...spec.defaults.angled_donut,
  });
  const [singlePass, setSinglePass] = useState<SinglePassParameters>({
    ...spec.defaults.single_pass,
  });
  const [retain, setRetain] = useState(true),
    [preview, setPreview] = useState<Mot3DPreview | null>(null),
    [runId, setRunId] = useState<string | null>(null);
  const [username, setUsername] = useState(""),
    [zeusToken, setZeusToken] = useState<string | null>(null),
    [zeusReconciliation, setZeusReconciliation] = useState(false),
    [run, setRun] = useState<Mot3DRun | null>(null);
  const [busy, setBusy] = useState(false),
    [sourcesLoaded, setSourcesLoaded] = useState(false),
    [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    const sequence = ++requestSequence.current;
    api
      .sources()
      .then((rows) => {
        if (mounted.current && sequence === requestSequence.current) {
          setSources(rows);
          setSourceId(rows[0]?.id ?? "");
          setSourcesLoaded(true);
        }
      })
      .catch((caught) => {
        if (mounted.current && sequence === requestSequence.current) {
          setSourcesLoaded(true);
          setError(errorMessage(caught));
        }
      });
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, [api]);
  useEffect(() => {
    title.current?.focus();
  }, [step]);
  useEffect(() => {
    let active = true;
    const sequence = requestSequence.current;
    const isCurrent = () =>
      active && mounted.current && sequence === requestSequence.current;
    void (async () => {
      const remembered = readRememberedIndividualRun("mot_3d");
      if (remembered) {
        setRunId(remembered.display_name);
        setMode(remembered.execution_mode);
        setUsername(remembered.username ?? "");
        setStep("monitor");
        setRecoveryPending(remembered.execution_mode === "zeus");
      }
      const found = await recoverIndividualRun("mot_3d", api, isCurrent);
      if (!isCurrent() || !found) return;
      if (holdForInspection(found as Mot3DRun)) {
        setRunId(null);
        setRun(null);
        setRecoveryPending(false);
        setStep("configure");
        return;
      }
      setRunId(found.display_name);
      setMode(found.execution.mode);
      setRun(found as Mot3DRun);
      setRecoveryPending(
        found.execution.mode === "zeus" && found.lifecycle !== "results_ready",
      );
      setStep(
        found.execution.mode === "zeus" && found.lifecycle !== "results_ready"
          ? "monitor"
          : recoveredRunStep(found),
      );
      if (
        found.execution.mode === "zeus" &&
        found.lifecycle !== "results_ready"
      ) {
        setStep("monitor");
        setUsername(remembered?.username ?? "");
        setRecoveryPending(true);
        if (!remembered?.username || !api.recoverZeus)
          throw new Error(
            "The remembered Zeus run cannot be verified safely yet. It was not restarted.",
          );
        const recoveredStatus = await api.recoverZeus(
          found.display_name,
          remembered.username,
        );
        if (!isCurrent()) return;
        setZeusHeld(recoveredStatus?.scheduler_state === "held");
        setUsername(remembered.username);
        setRecoveryPending(false);
      }
      setRunId(found.display_name);
      setMode(found.execution.mode);
      setRun(found as Mot3DRun);
      setStep(
        found.execution.mode === "zeus" && found.lifecycle !== "results_ready"
          ? "monitor"
          : recoveredRunStep(found),
      );
    })().catch((caught) => {
      if (isCurrent()) setError(errorMessage(caught));
    });
    return () => {
      active = false;
    };
  }, [api, holdForInspection]);

  const selected = sources.find((row) => row.id === sourceId);
  const maximumParticles = Math.min(
    spec.particle_count.maximum_by_execution_mode[mode],
    selected?.available_particle_count.pooled ?? 0,
  );
  useEffect(() => {
    if (maximumParticles > 0)
      setParticles((current) =>
        Number.isInteger(current) && current > 0
          ? Math.min(current, maximumParticles)
          : current,
      );
  }, [maximumParticles]);
  const workerMaximum = localWorkerMaximum(
    particles,
    spec.local_worker_count.maximum,
  );
  useEffect(() => {
    if (mode === "local")
      setNpools((current) =>
        Number.isInteger(current) && current > 0
          ? Math.min(current, workerMaximum)
          : current,
      );
  }, [mode, workerMaximum]);
  const parameters = family === "angled_donut" ? donut : singlePass;
  const parameterBounds = {
    ...spec.common_controls,
    ...spec.family_controls[family],
  } as Record<string, { minimum: number; maximum: number }>;
  const valid =
    !!selected &&
    Number.isInteger(particles) &&
    particles >= spec.particle_count.minimum &&
    particles <= maximumParticles &&
    Number.isInteger(selectionSeed) &&
    selectionSeed >= spec.selection_seed.minimum &&
    selectionSeed <= spec.selection_seed.maximum &&
    Number.isInteger(simulationSeed) &&
    simulationSeed >= spec.simulation_seed.minimum &&
    simulationSeed <= spec.simulation_seed.maximum &&
    Object.entries(parameterBounds).every(
      ([key, bounds]) =>
        Number.isFinite(parameters[key as keyof typeof parameters]) &&
        parameters[key as keyof typeof parameters] >= bounds.minimum &&
        parameters[key as keyof typeof parameters] <= bounds.maximum,
    ) &&
    Number.isInteger(npools) &&
    (mode === "local"
      ? npools >= spec.local_worker_count.minimum && npools <= workerMaximum
      : npools === spec.workers_by_execution_mode.zeus);
  const request = useMemo<Mot3DRequest>(
    () =>
      family === "angled_donut"
        ? {
            source_id: sourceId,
            geometry_family: family,
            particle_count: particles,
            selection_seed: selectionSeed,
            simulation_seed: simulationSeed,
            parameters: donut,
            npools,
            retain_particle_states: retain,
            execution_mode: mode,
          }
        : {
            source_id: sourceId,
            geometry_family: family,
            particle_count: particles,
            selection_seed: selectionSeed,
            simulation_seed: simulationSeed,
            parameters: singlePass,
            npools,
            retain_particle_states: retain,
            execution_mode: mode,
          },
    [
      sourceId,
      family,
      particles,
      selectionSeed,
      simulationSeed,
      donut,
      singlePass,
      npools,
      retain,
      mode,
    ],
  );

  function updateParameter(field: NumericField, displayValue: number) {
    const value = displayValue / (field.scale ?? 1);
    if (family === "angled_donut")
      setDonut((current) => ({ ...current, [field.key]: value }));
    else setSinglePass((current) => ({ ...current, [field.key]: value }));
  }
  function changeMode(next: Mot3DMode) {
    setMode(next);
    setNpools(
      next === "local"
        ? Math.min(
            spec.local_worker_count.default,
            localWorkerMaximum(particles, spec.local_worker_count.maximum),
          )
        : spec.workers_by_execution_mode.zeus,
    );
    const nextMaximum = Math.min(
      spec.particle_count.maximum_by_execution_mode[next],
      selected?.available_particle_count.pooled ?? 0,
    );
    if (nextMaximum > 0)
      setParticles((current) => Math.min(current, nextMaximum));
  }
  async function validate() {
    const sequence = ++requestSequence.current;
    setStep("validate");
    setBusy(true);
    setError(null);
    try {
      const next = await api.preview(request);
      if (mounted.current && sequence === requestSequence.current) {
        setPreview(next);
        setStep("review");
      }
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current) {
        setError(errorMessage(caught));
        setStep("configure");
      }
    } finally {
      if (mounted.current && sequence === requestSequence.current)
        setBusy(false);
    }
  }
  async function create() {
    if (!preview) return;
    const sequence = ++requestSequence.current;
    setBusy(true);
    setError(null);
    try {
      const created = await api.confirm(preview.preview_token);
      if (mounted.current && sequence === requestSequence.current) {
        setRunId(created.run_id);
        if (mode === "local")
          if (!rememberIndividualRun("mot_3d", created.run_id, "local"))
            setError(`${individualRunStorageWarning} Run: ${created.run_id}`);
        setStep("run");
      }
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current)
        setError(errorMessage(caught));
    } finally {
      if (mounted.current && sequence === requestSequence.current)
        setBusy(false);
    }
  }
  async function start() {
    if (!runId) return;
    const sequence = ++requestSequence.current;
    setBusy(true);
    setError(null);
    try {
      if (mode === "local") {
        const publicationRevision = publication.current.revision;
        await api.startLocal(runId);
        if (mounted.current && sequence === requestSequence.current) {
          if (publication.current.revision === publicationRevision) {
            publication.current.start(runId);
            setPublicationPending(true);
          }
        }
        if (!rememberIndividualRun("mot_3d", runId, "local"))
          setError(`${individualRunStorageWarning} Run: ${runId}`);
      } else if (!zeusToken) {
        const reviewed = await api.previewZeus(runId, username);
        if (run && !reviewed.effects.reconcile_existing_job)
          throw new Error(
            "No existing Zeus job could be verified. No new submission was authorized; inspect Zeus before continuing.",
          );
        if (mounted.current && sequence === requestSequence.current) {
          {
            setZeusResources(reviewed.job?.resources ?? null);
            setZeusToken(reviewed.preview_token);
          }
          setZeusReconciliation(reviewed.effects.reconcile_existing_job);
        }
        return;
      } else {
        await confirmRememberedZeusRun("mot_3d", runId, username, () =>
          api.confirmZeus(zeusToken),
        );
      }
      if (mounted.current && sequence === requestSequence.current)
        setStep("monitor");
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current)
        setError(errorMessage(caught));
    } finally {
      if (mounted.current && sequence === requestSequence.current)
        setBusy(false);
    }
  }
  const { publication, publicationPending, setPublicationPending } =
    useLocalRunPublication(api, mode, runId);

  async function refresh() {
    if (!runId || busy || recoveryPending) return;
    const sequence = ++requestSequence.current;
    setBusy(true);
    setError(null);
    try {
      const next = await refreshMot3DTransaction(
        api,
        mode,
        runId,
        username,
        () => mounted.current && sequence === requestSequence.current,
        (state) => setZeusHeld(state === "held"),
        mode === "local" ? publication.current : undefined,
      );
      if (next && mounted.current && sequence === requestSequence.current) {
        setPublicationPending(false);
        setRun(next);
        if (next.lifecycle === "results_ready") setStep("results");
      }
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current) {
        publication.current.finish();
        setPublicationPending(false);
        setError(errorMessage(caught));
      }
    } finally {
      if (mounted.current && sequence === requestSequence.current)
        setBusy(false);
    }
  }
  useEffect(() => {
    if (step !== "monitor" || mode !== "local" || !runId) return;
    let active = true,
      inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const { summary, waiting, retired } = await observeNewLocalRun(
          api,
          runId,
          publication.current,
          () => active,
        );
        if (!active || waiting || retired) return;
        setPublicationPending(false);
        if (!summary)
          throw new Error(
            "The run has not appeared in the verified run list yet. Try checking again shortly.",
          );
        if (active) {
          const found =
            summary.lifecycle === "results_ready"
              ? await api.run(summary.id)
              : summary;
          if (active) {
            setError(null);
            setRun(found);
            if (found.lifecycle === "results_ready") setStep("results");
          }
        }
      } catch (caught) {
        if (active) {
          publication.current.finish();
          setPublicationPending(false);
          setError(errorMessage(caught));
        }
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api, mode, runId, step, publication, setPublicationPending]);
  const currentStep = steps.findIndex(([id]) => id === step);

  async function reconcileRememberedRun() {
    if (!runId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const reviewed = await api.previewZeus(runId, username);
      if (run && !reviewed.effects.reconcile_existing_job)
        throw new Error(
          "No existing Zeus job could be verified. No new submission was authorized; inspect Zeus before continuing.",
        );
      if (!reviewed.effects.reconcile_existing_job)
        throw new Error(
          "No existing Zeus job could be verified. No new submission was authorized; inspect Zeus before continuing.",
        );
      {
        setZeusResources(reviewed.job?.resources ?? null);
        setZeusToken(reviewed.preview_token);
      }
      setZeusReconciliation(true);
      setRecoveryPending(false);
      setStep("run");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main id="main" className="individual-run-page">
      <button
        className="text-button back-button"
        disabled={busy}
        type="button"
        onClick={onBack}
      >
        <ArrowLeft aria-hidden="true" /> Back to home
      </button>
      <header className="detail-hero">
        <p className="eyebrow">Individual simulation · 3D MOT</p>
        <h1 ref={title} tabIndex={-1}>
          Configure one 3D-MOT simulation
        </h1>
        <p>
          Select saved 2D-MOT survivors and review one geometry. Creating the
          record does not start a simulation.
        </p>
      </header>
      <ol className="run-stepper" aria-label="Run progress">
        {steps.map(([id, label], index) => (
          <li
            key={id}
            className={
              index < currentStep
                ? "complete"
                : index === currentStep
                  ? "current"
                  : "pending"
            }
            aria-current={index === currentStep ? "step" : undefined}
          >
            <span>
              {index < currentStep ? (
                <CheckCircle2 aria-hidden="true" />
              ) : (
                index + 1
              )}
            </span>
            {label}
          </li>
        ))}
      </ol>
      {recoveryPending && (
        <section className="state-panel" role="status">
          <strong>Existing Zeus run needs verification</strong>
          <p>
            {runId} remains selected. Its submission outcome is uncertain.
            Inspect Zeus or review linking its existing job before continuing.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void reconcileRememberedRun()}
          >
            Review existing Zeus job
          </button>
        </section>
      )}
      {publicationPending && !error && (
        <p role="status">{localRunPublicationMessage}</p>
      )}
      {error && (
        <div className="state-panel state-panel--error" role="alert">
          <strong>Action needed</strong>
          <p>{error}</p>
        </div>
      )}
      {sourcesLoaded && !error && sources.length === 0 && (
        <div className="state-panel" role="status">
          <strong>No eligible 2D-MOT survivors were found</strong>
          <p>
            Complete a canonical 2D-MOT campaign or retain the states from an
            individual 2D-MOT result, then return here.
          </p>
        </div>
      )}
      <div className="sr-only" aria-live="polite">
        {busy ? "Validating the reviewed setup" : `Current step: ${step}`}
      </div>

      {step === "configure" && inspectionRun && (
        <SavedLocalRunNotice
          run={inspectionRun}
          disabled={busy || recoveryPending}
          onInspect={() => {
            setRunId(inspectionRun.display_name);
            setRun(inspectionRun);
            setMode("local");
            setStep("monitor");
          }}
        />
      )}
      {step === "configure" && (
        <form
          className="creation-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid && !busy) void validate();
          }}
        >
          <div className="form-field">
            <label htmlFor="mot3d-source">
              2D-MOT survivor source{" "}
              <Help text="A verified saved result is pooled without exposing private file paths. Particle selection is reproducible and without replacement." />
            </label>
            <select
              id="mot3d-source"
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
            >
              <option value="" disabled>
                Select a verified source
              </option>
              {(
                [
                  "bundled_2d_ensemble",
                  "canonical_2d_campaign",
                  "retained_individual_mot_2d",
                ] as const
              ).map((kind) => {
                const rows = sources.filter((row) => row.source_kind === kind);
                return rows.length ? (
                  <optgroup
                    key={kind}
                    label={
                      kind === "bundled_2d_ensemble"
                        ? "Included 2D-MOT input populations"
                        : kind === "canonical_2d_campaign"
                          ? "Completed 2D-MOT campaigns"
                          : "Saved individual 2D-MOT results"
                    }
                  >
                    {rows.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.label} ·{" "}
                        {row.available_particle_count.pooled.toLocaleString()}{" "}
                        particles
                      </option>
                    ))}
                  </optgroup>
                ) : null;
              })}
            </select>
          </div>
          <fieldset>
            <legend>3D-MOT geometry</legend>
            <div className="geometry-choice-grid">
              <label
                className={
                  family === "angled_donut"
                    ? "geometry-choice selected"
                    : "geometry-choice"
                }
              >
                <input
                  type="radio"
                  name="mot3d-family"
                  checked={family === "angled_donut"}
                  onChange={() => setFamily("angled_donut")}
                />
                <span>
                  <strong>Angled donut</strong>
                  <small>
                    Green core and blue shell share a hard radial boundary.
                  </small>
                </span>
              </label>
              <label
                className={
                  family === "single_pass"
                    ? "geometry-choice selected"
                    : "geometry-choice"
                }
              >
                <input
                  type="radio"
                  name="mot3d-family"
                  checked={family === "single_pass"}
                  onChange={() => setFamily("single_pass")}
                />
                <span>
                  <strong>Single pass</strong>
                  <small>
                    Crossed blue slowing beam with geometry-dependent effective
                    detuning.
                  </small>
                </span>
              </label>
            </div>
          </fieldset>
          <div className="run-form-grid">
            {[...commonFields, ...familyFields[family]].map((field) => {
              const bounds = parameterBounds[field.key];
              const scale = field.scale ?? 1;
              return (
                <div className="form-field" key={field.key}>
                  <label htmlFor={`mot3d-${field.key}`}>
                    {field.label}
                    {field.unit ? ` (${field.unit})` : ""}{" "}
                    {field.help && <Help text={field.help} />}
                  </label>
                  <input
                    id={`mot3d-${field.key}`}
                    type="number"
                    min={bounds.minimum * scale}
                    max={bounds.maximum * scale}
                    step="any"
                    value={
                      parameters[field.key as keyof typeof parameters] * scale
                    }
                    onChange={(event) =>
                      updateParameter(field, event.currentTarget.valueAsNumber)
                    }
                  />
                </div>
              );
            })}
          </div>
          <div className="run-form-grid">
            <div className="form-field">
              <label htmlFor="mot3d-particles">
                Particle count{" "}
                <Help
                  text={`Maximum here is ${maximumParticles.toLocaleString()}, limited by the selected source and execution location.`}
                />
              </label>
              <input
                id="mot3d-particles"
                type="number"
                min={spec.particle_count.minimum}
                max={maximumParticles}
                value={particles}
                onChange={(event) =>
                  setParticles(event.currentTarget.valueAsNumber)
                }
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot3d-selection-seed">
                Selection seed{" "}
                <Help text="Reproducibly selects particles from the pooled source without replacement." />
              </label>
              <input
                id="mot3d-selection-seed"
                type="number"
                min={spec.selection_seed.minimum}
                max={spec.selection_seed.maximum}
                value={selectionSeed}
                onChange={(event) =>
                  setSelectionSeed(event.currentTarget.valueAsNumber)
                }
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot3d-simulation-seed">
                Simulation seed{" "}
                <Help text="Controls stochastic photon sampling during this 3D-MOT simulation." />
              </label>
              <input
                id="mot3d-simulation-seed"
                type="number"
                min={spec.simulation_seed.minimum}
                max={spec.simulation_seed.maximum}
                value={simulationSeed}
                onChange={(event) =>
                  setSimulationSeed(event.currentTarget.valueAsNumber)
                }
              />
            </div>
          </div>
          <fieldset>
            <legend>Where should it run?</legend>
            <div className="choice-row">
              <label>
                <input
                  type="radio"
                  name="mot3d-mode"
                  checked={mode === "local"}
                  onChange={() => changeMode("local")}
                />{" "}
                This computer
              </label>
              <label>
                <input
                  type="radio"
                  name="mot3d-mode"
                  checked={mode === "zeus"}
                  onChange={() => changeMode("zeus")}
                />{" "}
                Zeus
              </label>
            </div>
            {mode === "local" && (
              <div className="form-field local-worker-field">
                <label htmlFor="mot3d-npools">
                  CPU workers{" "}
                  <Help text="Choose no more workers than this computer’s CPU count or the number of particles." />
                </label>
                <input
                  id="mot3d-npools"
                  type="number"
                  min={spec.local_worker_count.minimum}
                  max={workerMaximum}
                  value={npools}
                  onChange={(event) =>
                    setNpools(event.currentTarget.valueAsNumber)
                  }
                />
              </div>
            )}
          </fieldset>
          <label className="check-control">
            <input
              type="checkbox"
              checked={retain}
              onChange={(event) => setRetain(event.currentTarget.checked)}
            />
            <span>
              <strong>Keep survivor particle states</strong>
              <small>
                Saved states remain suitable for individual analysis only.
              </small>
            </span>
          </label>
          <div className="form-actions">
            <button className="primary-button" disabled={!valid || busy}>
              {busy ? "Validating…" : "Validate setup"}
            </button>
          </div>
        </form>
      )}

      {step === "validate" && (
        <section className="run-stage">
          <div className="action-banner action-banner--running">
            <LoaderCircle className="spin" aria-hidden="true" />
            <div>
              <strong>Validating the complete setup</strong>
              <p>
                The source, particle selection, geometry, fixed science, and
                repository state are being checked.
              </p>
            </div>
          </div>
        </section>
      )}

      {step === "review" && preview && (
        <section className="run-stage">
          <div className="scientific-role-note">
            <strong>Scientific role: individual only</strong>
            <p>
              This run can inspect one setup. Its result does not become
              campaign evidence automatically.
            </p>
          </div>
          <div className="review-grid">
            <article className="review-card">
              <h2>Your choices</h2>
              <dl>
                <div>
                  <dt>Source</dt>
                  <dd>{selected?.label}</dd>
                </div>
                <div>
                  <dt>Geometry</dt>
                  <dd>
                    {family === "angled_donut" ? "Angled donut" : "Single pass"}
                  </dd>
                </div>
                <div>
                  <dt>Particles and seeds</dt>
                  <dd>
                    {particles.toLocaleString()} particles · selection{" "}
                    {selectionSeed} · simulation {simulationSeed}
                  </dd>
                </div>
                <div>
                  <dt>CPU workers</dt>
                  <dd>{preview.plan.locked_settings.workers}</dd>
                </div>
                <div>
                  <dt>Execution and retention</dt>
                  <dd>
                    {mode === "local" ? "This computer" : "Zeus"} ·{" "}
                    {retain ? "keep survivor states" : "summary only"}
                  </dd>
                </div>
              </dl>
            </article>
            <article className="review-card">
              <h2>
                Locked science{" "}
                <Help text="These settings are fixed by the reviewed scientific policy and cannot be changed from this form." />
              </h2>
              <p>
                RK4StHybridCustom ·{" "}
                {format(preview.plan.locked_settings.timestep_s * 1e6)} µs
                timestep · {format(preview.plan.locked_settings.t_max_s * 1000)}{" "}
                ms simulated duration.
              </p>
              <p>
                <strong>Convergence:</strong> not established. This is the
                explicitly approved pragmatic timestep.
              </p>
              <dl>
                <div>
                  <dt>Capture radius</dt>
                  <dd>
                    {format(
                      preview.plan.locked_settings.capture.capture_radius_m *
                        1000,
                    )}{" "}
                    mm
                  </dd>
                </div>
                <div>
                  <dt>Maximum final speed</dt>
                  <dd>
                    {format(
                      preview.plan.locked_settings.capture
                        .maximum_final_speed_m_s,
                    )}{" "}
                    m/s
                  </dd>
                </div>
                <div>
                  <dt>Minimum residence time</dt>
                  <dd>
                    {format(
                      preview.plan.locked_settings.capture
                        .minimum_residence_time_s * 1000,
                    )}{" "}
                    ms
                  </dd>
                </div>
              </dl>
            </article>
          </div>
          <article className="review-card parameter-review">
            <h2>
              {preview.plan.geometry.family === "angled_donut"
                ? "Angled-donut parameters"
                : "Single-pass parameters"}
            </h2>
            <dl>
              {[
                ...commonFields,
                ...familyFields[preview.plan.geometry.family],
              ].map((field) => (
                <div key={field.key}>
                  <dt>{field.label}</dt>
                  <dd>
                    {format(
                      (
                        preview.plan.geometry.parameters as unknown as Record<
                          string,
                          number
                        >
                      )[field.key] * (field.scale ?? 1),
                    )}
                    {field.unit ? ` ${field.unit}` : ""}
                  </dd>
                </div>
              ))}
            </dl>
            {preview.plan.geometry.family === "single_pass" && (
              <>
                <h3>Derived single-pass values</h3>
                <p className="field-help">
                  These exact values were calculated and validated by the
                  scientific backend. They are not re-created in the browser.
                </p>
                <dl>
                  <div>
                    <dt>Effective blue detuning</dt>
                    <dd>
                      {format(
                        preview.plan.geometry.derived_parameters
                          .blue_detuning_gamma,
                      )}{" "}
                      Γ
                    </dd>
                  </div>
                  <div>
                    <dt>Effective slowing z offset</dt>
                    <dd>
                      {format(
                        preview.plan.geometry.derived_parameters
                          .effective_slowing_z_offset_m * 1000,
                      )}{" "}
                      mm
                    </dd>
                  </div>
                  <div>
                    <dt>Effective slowing field</dt>
                    <dd>
                      {format(
                        preview.plan.geometry.derived_parameters
                          .effective_slowing_field_G,
                      )}{" "}
                      G
                    </dd>
                  </div>
                  <div>
                    <dt>Reference slowing field</dt>
                    <dd>
                      {format(
                        preview.plan.geometry.derived_parameters
                          .reference_slowing_field_G,
                      )}{" "}
                      G
                    </dd>
                  </div>
                </dl>
              </>
            )}
          </article>
          <div className="form-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={busy}
              onClick={() => {
                requestSequence.current += 1;
                setPreview(null);
                setStep("configure");
              }}
            >
              Change choices
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={() => void create()}
            >
              {busy ? "Creating…" : "Create run record"}
            </button>
          </div>
        </section>
      )}

      {step === "run" && runId && (
        <section className="run-stage">
          <div className="action-banner">
            <Play aria-hidden="true" />
            <div>
              <strong>
                {run && mode === "zeus"
                  ? "Existing Zeus run selected"
                  : "Reviewed run is ready"}
              </strong>
              <p>
                {run && mode === "zeus"
                  ? "Review linking the verified existing job. No new job will be submitted."
                  : "Nothing is running yet. Starting requires this explicit action."}
              </p>
            </div>
          </div>
          <code className="run-record-id">{runId}</code>
          {mode === "zeus" && (
            <>
              <div className="form-field zeus-run-profile">
                <label htmlFor="mot3d-zeus-username">
                  Technion username
                  <span>
                    Used with the SSH key already configured on this computer.
                    The remote project directory is derived automatically.
                  </span>
                </label>
                <input
                  id="mot3d-zeus-username"
                  value={username}
                  placeholder="for example, tal.noa"
                  pattern="[A-Za-z][A-Za-z0-9._-]{0,31}"
                  disabled={zeusToken !== null}
                  onChange={(event) => setUsername(event.currentTarget.value)}
                />
              </div>
              {zeusToken && (
                <div className="submission-attention" role="status">
                  <strong>
                    {zeusReconciliation
                      ? "An existing Zeus job is ready to be linked"
                      : "One scalar Zeus job is ready for confirmation"}
                  </strong>
                  <p>
                    {zeusReconciliation
                      ? "The reviewed package matches an existing job. Confirm below to link it; no new job will be submitted."
                      : "The frozen package was checked. Confirm below to submit exactly one job; no later job is submitted automatically."}
                  </p>
                  {zeusResources && (
                    <dl aria-label="Reviewed Zeus reservation">
                      <div>
                        <dt>Queue</dt>
                        <dd>{zeusResources.queue}</dd>
                      </div>
                      <div>
                        <dt>CPU cores</dt>
                        <dd>{zeusResources.cores}</dd>
                      </div>
                      <div>
                        <dt>Memory</dt>
                        <dd>{zeusResources.memory_bytes / 1024 ** 3} GiB</dd>
                      </div>
                      <div>
                        <dt>Time limit</dt>
                        <dd>{zeusResources.walltime_seconds / 3600} hours</dd>
                      </div>
                      {zeusResources.vnode && (
                        <div>
                          <dt>Test compute node</dt>
                          <dd>{zeusResources.vnode}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                </div>
              )}
            </>
          )}
          <div className="form-actions">
            {mode === "zeus" && zeusToken && (
              <button
                className="secondary-button"
                type="button"
                disabled={busy}
                onClick={() => {
                  setZeusToken(null);
                  setZeusReconciliation(false);
                }}
              >
                Change connection
              </button>
            )}
            <button
              className="primary-button"
              type="button"
              disabled={
                busy ||
                Boolean(run?.execution.locally_scheduled) ||
                (mode === "zeus" &&
                  !/^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(username))
              }
              onClick={() => void start()}
            >
              {mode === "local" ? (
                <Play aria-hidden="true" />
              ) : (
                <Server aria-hidden="true" />
              )}
              {busy
                ? "Working…"
                : mode === "local"
                  ? "Start on this computer"
                  : zeusToken
                    ? zeusReconciliation
                      ? "Confirm and link existing Zeus job"
                      : "Confirm and submit one Zeus job"
                    : "Review Zeus submission"}
            </button>
          </div>
        </section>
      )}

      {step === "monitor" && (
        <section className="run-stage">
          {(() => {
            const copy = mot3dMonitorCopy(
              zeusHeld ? "held" : run?.record_state,
              run?.execution.mode ?? mode,
              Boolean(run?.execution.progress),
              run?.execution.locally_scheduled ?? false,
            );
            return (
              <div
                className={`action-banner ${copy.attention ? "action-banner--attention" : "action-banner--running"}`}
              >
                <LoaderCircle
                  className={busy ? "spin" : ""}
                  aria-hidden="true"
                />
                <div>
                  <strong>{copy.title}</strong>
                  <p>{copy.body}</p>
                </div>
              </div>
            );
          })()}
          {zeusHeld &&
            (onViewZeusJobs ? (
              <button
                type="button"
                className="secondary-button"
                onClick={onViewZeusJobs}
              >
                Open Zeus jobs
              </button>
            ) : (
              <p>Open Zeus jobs from the navigation to inspect this hold.</p>
            ))}
          {mode === "local" && run?.execution.progress && (
            <RunProgressPanel progress={run.execution.progress} />
          )}
          {localRunNeedsInspection(run) && (
            <button
              type="button"
              className="secondary-button"
              disabled={busy || recoveryPending}
              onClick={() => {
                if (!run || !holdForInspection(run)) return;
                setRunId(null);
                setRun(null);
                setPreview(null);
                setError(null);
                setStep("configure");
              }}
            >
              Configure a separate simulation
            </button>
          )}
          <div className="form-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={busy || recoveryPending}
              onClick={() => void refresh()}
            >
              {busy ? "Checking…" : "Check status"}
            </button>
          </div>
        </section>
      )}

      {step === "results" && run && (
        <section className="run-stage">
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              forgetIndividualRun("mot_3d");
              onBack();
            }}
          >
            Configure another simulation
          </button>
          <div className="success-panel">
            <CheckCircle2 aria-hidden="true" />
            <h2>Verified results are ready</h2>
          </div>
          <div className="scientific-role-note">
            <strong>Scientific role: individual only</strong>
            <p>This result does not become campaign evidence automatically.</p>
          </div>
          <article className="review-card">
            <h3>Summary</h3>
            <dl>
              <div>
                <dt>Geometry</dt>
                <dd>
                  {run.metrics?.provenance.geometry_family === "angled_donut"
                    ? "Angled donut"
                    : run.metrics?.provenance.geometry_family === "single_pass"
                      ? "Single pass"
                      : "—"}
                </dd>
              </div>
              <div>
                <dt>Selected 2D-MOT survivors</dt>
                <dd>{run.metrics?.n_input.toLocaleString() ?? "—"}</dd>
              </div>
              <div>
                <dt>Usable at simulation end</dt>
                <dd>
                  {run.metrics
                    ? `${run.metrics.usable_at_end_count.toLocaleString()} (${(100 * run.metrics.usable_at_end_fraction).toFixed(3)}%)`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Residence-qualified captured</dt>
                <dd>
                  {run.metrics
                    ? `${run.metrics.residence_qualified_captured_count.toLocaleString()} (${(100 * run.metrics.residence_qualified_captured_fraction).toFixed(3)}%)`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Runtime</dt>
                <dd>
                  {run.metrics ? `${run.metrics.elapsed_s.toFixed(3)} s` : "—"}
                </dd>
              </div>
              <div>
                <dt>Particle states</dt>
                <dd>{run.retention.status.replaceAll("_", " ")}</dd>
              </div>
            </dl>
            <details>
              <summary>Technical provenance</summary>
              <pre className="settings-json">
                {JSON.stringify(
                  {
                    run_id: run.display_name,
                    execution: run.execution,
                    completed_at: run.results.completed_at,
                    provenance: run.metrics?.provenance,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </article>
        </section>
      )}
    </main>
  );
}

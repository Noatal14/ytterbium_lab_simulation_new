import specification from "../../../workflow_api/specifications/mot_2d_individual_v1.json";
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
  IndividualMot2DApi,
  Mot2DMode,
  Mot2DPreview,
  Mot2DRun,
  Mot2DSource,
} from "../api/clients/individualMot2D";
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

const particlePolicy = specification.particle_count;
const localWorkerPolicy = specification.local_worker_count;
const controls = specification.controls;
const MILLIMETRES_PER_METRE = 1000;
const radiusMmPolicy = {
  minimum: controls.magnet_radius_m.minimum * MILLIMETRES_PER_METRE,
  maximum: controls.magnet_radius_m.maximum * MILLIMETRES_PER_METRE,
  default: controls.magnet_radius_m.default * MILLIMETRES_PER_METRE,
};
function withinBounds(
  value: number,
  policy: { minimum: number; maximum: number },
) {
  return (
    Number.isFinite(value) && value >= policy.minimum && value <= policy.maximum
  );
}
function integerWithinBounds(
  value: number,
  policy: { minimum: number; maximum: number },
) {
  return Number.isInteger(value) && withinBounds(value, policy);
}

type Step = "configure" | "review" | "run" | "monitor" | "results";
const labels: [Step, string][] = [
  ["configure", "Configure"],
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
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The request could not be completed safely.";
const ActionError = ({ error }: { error: string | null }) =>
  error ? (
    <p className="action-error" role="alert">
      {error}
    </p>
  ) : null;
export function mot2dMonitorCopy(
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
      attention: false,
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
      body: "The 2D-MOT simulation is running. No action is required.",
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

export async function refreshMot2DTransaction(
  api: IndividualMot2DApi,
  mode: Mot2DMode,
  runId: string,
  username: string,
  isCurrent: () => boolean,
  onSchedulerState?: (state: string) => void,
  publication?: LocalRunPublication,
): Promise<Mot2DRun | null> {
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

export function IndividualMot2DRun({
  api,
  onBack,
  onViewZeusJobs,
}: {
  api: IndividualMot2DApi;
  onBack: () => void;
  onViewZeusJobs?: () => void;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  const refreshRequest = useRef(0);
  const [recoveryPending, setRecoveryPending] = useState(false);
  const { inspectionRun, holdForInspection } =
    useLocalRunInspection<Mot2DRun>(api);

  const [zeusHeld, setZeusHeld] = useState(false);
  const [step, setStep] = useState<Step>("configure"),
    [sources, setSources] = useState<Mot2DSource[]>([]),
    [source, setSource] = useState("");
  const [mode, setMode] = useState<Mot2DMode>("local"),
    [npools, setNpools] = useState(() =>
      Math.min(
        localWorkerPolicy.default,
        localWorkerMaximum(particlePolicy.default, localWorkerPolicy.maximum),
      ),
    ),
    [particles, setParticles] = useState<number>(particlePolicy.default),
    [selectionSeed, setSelectionSeed] = useState(
      specification.selection_seed.default,
    ),
    [motSeed, setMotSeed] = useState(specification.mot_seed.default);
  const [s0, setS0] = useState(controls.s0.default),
    [detuning, setDetuning] = useState(controls.detuning_gamma.default),
    [radiusMm, setRadiusMm] = useState(radiusMmPolicy.default),
    [retain, setRetain] = useState(true);
  const [preview, setPreview] = useState<Mot2DPreview | null>(null),
    [runId, setRunId] = useState<string | null>(null),
    [username, setUsername] = useState(""),
    [zeusToken, setZeusToken] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Mot2DRun | null>(null);
  const [zeusResources, setZeusResources] =
    useState<IndividualZeusResources | null>(null);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api
      .sources()
      .then((rows) => {
        if (active) {
          setSources(rows);
          setSource(rows[0]?.id ?? "");
          const available = rows[0]?.available_particle_count.pooled ?? 0;
          if (available > 0)
            setParticles((current) => Math.min(current, available));
        }
      })
      .catch((e) => active && setError(message(e)));
    return () => {
      active = false;
    };
  }, [api]);
  useEffect(() => {
    title.current?.focus();
  }, [step]);
  useEffect(() => {
    refreshRequest.current += 1;
    setBusy(false);
    return () => {
      refreshRequest.current += 1;
    };
  }, [api]);
  useEffect(() => {
    let active = true;
    const id = refreshRequest.current;
    void (async () => {
      const remembered = readRememberedIndividualRun("mot_2d");
      if (remembered) {
        setRunId(remembered.display_name);
        setMode(remembered.execution_mode);
        setUsername(remembered.username ?? "");
        setStep("monitor");
        setRecoveryPending(remembered.execution_mode === "zeus");
      }
      const found = await recoverIndividualRun(
        "mot_2d",
        api,
        () => active && id === refreshRequest.current,
      );
      if (!active || id !== refreshRequest.current || !found) return;
      if (holdForInspection(found as Mot2DRun)) {
        setRunId(null);
        setRun(null);
        setRecoveryPending(false);
        setStep("configure");
        return;
      }
      setRunId(found.display_name);
      setMode(found.execution.mode);
      setRun(found as Mot2DRun);
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
        if (!active || id !== refreshRequest.current) return;
        setZeusHeld(recoveredStatus?.scheduler_state === "held");
        setUsername(remembered.username);
        setRecoveryPending(false);
      }
      setRunId(found.display_name);
      setMode(found.execution.mode);
      setRun(found as Mot2DRun);
      setStep(
        found.execution.mode === "zeus" && found.lifecycle !== "results_ready"
          ? "monitor"
          : recoveredRunStep(found),
      );
    })().catch((caught) => {
      if (active && id === refreshRequest.current) setError(message(caught));
    });
    return () => {
      active = false;
    };
  }, [api, holdForInspection]);
  const selected = sources.find((row) => row.id === source),
    max = Math.min(
      particlePolicy.maximum_by_execution_mode[mode],
      selected?.available_particle_count.pooled ?? 0,
    );
  useEffect(() => {
    if (max > 0)
      setParticles((current) =>
        Number.isInteger(current) && current > 0
          ? Math.min(current, max)
          : current,
      );
  }, [max]);
  const workerMaximum = localWorkerMaximum(
    particles,
    localWorkerPolicy.maximum,
  );
  useEffect(() => {
    if (mode === "local")
      setNpools((current) =>
        Number.isInteger(current) && current > 0
          ? Math.min(current, workerMaximum)
          : current,
      );
  }, [mode, workerMaximum]);
  const valid =
    !!selected &&
    Number.isInteger(particles) &&
    particles >= particlePolicy.minimum &&
    particles <= max &&
    integerWithinBounds(selectionSeed, specification.selection_seed) &&
    integerWithinBounds(motSeed, specification.mot_seed) &&
    withinBounds(s0, controls.s0) &&
    withinBounds(detuning, controls.detuning_gamma) &&
    withinBounds(radiusMm, radiusMmPolicy) &&
    Number.isInteger(npools) &&
    (mode === "local"
      ? npools >= localWorkerPolicy.minimum && npools <= workerMaximum
      : npools === specification.workers_by_execution_mode.zeus);
  const request = useMemo(
    () => ({
      source_id: source,
      particle_count: particles,
      selection_seed: selectionSeed,
      mot_seed: motSeed,
      s0,
      detuning_gamma: detuning,
      magnet_radius_m: radiusMm / MILLIMETRES_PER_METRE,
      npools,
      retain_particle_states: retain,
      execution_mode: mode,
    }),
    [
      source,
      particles,
      selectionSeed,
      motSeed,
      s0,
      detuning,
      radiusMm,
      npools,
      retain,
      mode,
    ],
  );
  function changeMode(next: Mot2DMode) {
    setMode(next);
    const nextMaximum = Math.min(
      particlePolicy.maximum_by_execution_mode[next],
      selected?.available_particle_count.pooled ?? 0,
    );
    const nextParticles =
      nextMaximum > 0 && Number.isInteger(particles) && particles > 0
        ? Math.min(particles, nextMaximum)
        : particles;
    setParticles(nextParticles);
    setNpools(
      next === "local"
        ? Math.min(
            localWorkerPolicy.default,
            localWorkerMaximum(nextParticles, localWorkerPolicy.maximum),
          )
        : specification.workers_by_execution_mode.zeus,
    );
  }
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function review() {
    await act(async () => {
      setPreview(await api.preview(request));
      setStep("review");
    });
  }
  async function create() {
    if (preview)
      await act(async () => {
        const row = await api.confirm(preview.preview_token);
        setRunId(row.run_id);
        if (mode === "local")
          if (!rememberIndividualRun("mot_2d", row.run_id, "local"))
            setError(`${individualRunStorageWarning} Run: ${row.run_id}`);
        setStep("run");
      });
  }
  async function start() {
    if (!runId) return;
    await act(async () => {
      if (mode === "local") {
        const publicationRevision = publication.current.revision;
        await api.startLocal(runId);
        {
          if (publication.current.revision === publicationRevision) {
            publication.current.start(runId);
            setPublicationPending(true);
          }
        }
        if (!rememberIndividualRun("mot_2d", runId, "local"))
          setError(`${individualRunStorageWarning} Run: ${runId}`);
      } else if (!zeusToken) {
        const reviewed = await api.previewZeus(runId, username);
        if (run && !reviewed.effects.reconcile_existing_job)
          throw new Error(
            "No existing Zeus job could be verified. No new submission was authorized; inspect Zeus before continuing.",
          );
        setZeusResources(reviewed.job.resources);
        setZeusToken(reviewed.preview_token);
      } else {
        await confirmRememberedZeusRun("mot_2d", runId, username, async () => {
          const result = await api.confirmZeus(zeusToken);
          setSubmittedJobId(result.job_id);
          return result;
        });
      }
      if (mode === "local" || zeusToken) setStep("monitor");
    });
  }
  const { publication, publicationPending, setPublicationPending } =
    useLocalRunPublication(api, mode, runId);

  async function refresh() {
    if (!runId || busy || recoveryPending) return;
    const requestId = ++refreshRequest.current;
    setBusy(true);
    setError(null);
    try {
      const next = await refreshMot2DTransaction(
        api,
        mode,
        runId,
        username,
        () => requestId === refreshRequest.current,
        (state) => setZeusHeld(state === "held"),
        mode === "local" ? publication.current : undefined,
      );
      if (!next) return;
      setPublicationPending(false);
      setRun(next);
      if (next.lifecycle === "results_ready") setStep("results");
    } catch (caught) {
      if (requestId === refreshRequest.current) {
        publication.current.finish();
        setPublicationPending(false);
        setError(message(caught));
      }
    } finally {
      if (requestId === refreshRequest.current) setBusy(false);
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
          setError(message(caught));
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
      setZeusResources(reviewed.job.resources);
      setZeusToken(reviewed.preview_token);
      setRecoveryPending(false);
      setStep("run");
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  const current = labels.findIndex(([id]) => id === step);
  return (
    <main id="main" className="individual-run-page">
      <button
        className="text-button back-button"
        disabled={busy}
        onClick={onBack}
      >
        <ArrowLeft /> Back to home
      </button>
      <header className="detail-hero">
        <p className="eyebrow">Individual simulation · 2D MOT</p>
        <h1 ref={title} tabIndex={-1}>
          Run one 2D-MOT simulation
        </h1>
        <p>
          Choose a verified Zeeman source and the approved run controls. The
          application guides every review and execution step.
        </p>
      </header>
      <ol className="run-stepper" aria-label="Run progress">
        {labels.map(([id, label], i) => (
          <li
            key={id}
            className={
              i < current ? "complete" : i === current ? "current" : "pending"
            }
            aria-current={i === current ? "step" : undefined}
          >
            <span>{i < current ? <CheckCircle2 /> : i + 1}</span>
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
      <div className="sr-only" aria-live="polite">
        {busy ? "Working" : `Current step: ${step}`}
      </div>
      {publicationPending && !error && (
        <p role="status">{localRunPublicationMessage}</p>
      )}
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
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !busy) void review();
          }}
        >
          <div className="form-field">
            <label htmlFor="mot2d-source">
              Zeeman survivor source{" "}
              <Help text="A verified folder is pooled across all of its validated ensembles. Private file paths are never exposed." />
            </label>
            <select
              id="mot2d-source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="" disabled>
                Select a verified source
              </option>
              {["canonical_folder", "retained_individual_zeeman"].map(
                (kind) => {
                  const rows = sources.filter(
                    (row) => row.source_kind === kind,
                  );
                  return rows.length ? (
                    <optgroup
                      key={kind}
                      label={
                        kind === "canonical_folder"
                          ? "Validated ensemble folders"
                          : "Saved individual Zeeman results"
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
                },
              )}
            </select>
          </div>
          <div className="run-form-grid">
            <div className="form-field">
              <label htmlFor="mot2d-particles">
                Particle count{" "}
                <Help
                  text={`Maximum here is ${max.toLocaleString()}, limited by the selected execution mode and source pool.`}
                />
              </label>
              <input
                id="mot2d-particles"
                type="number"
                min={particlePolicy.minimum}
                max={max}
                value={particles}
                onChange={(e) => setParticles(e.currentTarget.valueAsNumber)}
                aria-describedby="mot2d-particle-guidance"
                aria-invalid={
                  !!selected &&
                  (!Number.isInteger(particles) ||
                    particles < particlePolicy.minimum ||
                    particles > max)
                }
              />
              <small
                id="mot2d-particle-guidance"
                className={
                  particles > max ||
                  !Number.isInteger(particles) ||
                  particles < particlePolicy.minimum
                    ? "field-error"
                    : undefined
                }
              >
                {selected
                  ? !Number.isInteger(particles) ||
                    particles < particlePolicy.minimum
                    ? `Choose a whole number of particles, starting at ${particlePolicy.minimum}.`
                    : particles > max
                      ? `This source contains only ${max.toLocaleString()} available particles. Choose ${max.toLocaleString()} or fewer.`
                      : `Up to ${max.toLocaleString()} particles are available for this execution mode.`
                  : "Select a Zeeman survivor source first."}
              </small>
            </div>
            <div className="form-field">
              <label htmlFor="mot2d-selection-seed">
                Selection seed{" "}
                <Help text="Reproducibly chooses particles from the pooled source without replacement." />
              </label>
              <input
                id="mot2d-selection-seed"
                type="number"
                min={specification.selection_seed.minimum}
                max={specification.selection_seed.maximum}
                value={selectionSeed}
                onChange={(e) =>
                  setSelectionSeed(e.currentTarget.valueAsNumber)
                }
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot2d-mot-seed">
                MOT seed{" "}
                <Help text="Controls stochastic photon sampling inside the 2D-MOT simulation." />
              </label>
              <input
                id="mot2d-mot-seed"
                type="number"
                min={specification.mot_seed.minimum}
                max={specification.mot_seed.maximum}
                value={motSeed}
                onChange={(e) => setMotSeed(e.currentTarget.valueAsNumber)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot2d-s0">Saturation parameter (s₀)</label>
              <input
                id="mot2d-s0"
                type="number"
                min={controls.s0.minimum}
                max={controls.s0.maximum}
                step="0.01"
                value={s0}
                onChange={(e) => setS0(e.currentTarget.valueAsNumber)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot2d-detuning">Detuning (Γ)</label>
              <input
                id="mot2d-detuning"
                type="number"
                min={controls.detuning_gamma.minimum}
                max={controls.detuning_gamma.maximum}
                step="any"
                value={detuning}
                onChange={(e) => setDetuning(e.currentTarget.valueAsNumber)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="mot2d-radius">Magnet radius (mm)</label>
              <input
                id="mot2d-radius"
                type="number"
                min={radiusMmPolicy.minimum}
                max={radiusMmPolicy.maximum}
                step="any"
                value={radiusMm}
                onChange={(e) => setRadiusMm(e.currentTarget.valueAsNumber)}
              />
            </div>
          </div>
          <fieldset>
            <legend>Where should it run?</legend>
            <div className="choice-row">
              <label>
                <input
                  type="radio"
                  checked={mode === "local"}
                  onChange={() => changeMode("local")}
                />{" "}
                This computer
              </label>
              <label>
                <input
                  type="radio"
                  checked={mode === "zeus"}
                  onChange={() => changeMode("zeus")}
                />{" "}
                Zeus
              </label>
            </div>
            {mode === "local" && (
              <div className="form-field local-worker-field">
                <label htmlFor="mot2d-npools">
                  CPU workers{" "}
                  <Help text="Choose no more workers than this computer’s CPU count or the number of particles." />
                </label>
                <input
                  id="mot2d-npools"
                  type="number"
                  min={localWorkerPolicy.minimum}
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
              onChange={(e) => setRetain(e.currentTarget.checked)}
            />
            <span>
              <strong>Keep survivor particle states</strong>
              <small>
                Saved states remain individual-only unless separately validated
                for campaign use.
              </small>
            </span>
          </label>
          <div className="form-actions">
            <button className="primary-button" disabled={!valid || busy}>
              {busy ? "Validating…" : "Validate and review"}
            </button>
          </div>
          <ActionError error={error} />
        </form>
      )}
      {step === "review" && preview && (
        <section className="run-stage">
          <div className="scientific-role-note">
            <strong>Scientific role: individual only</strong>
            <p>
              Retained states support inspection and individual follow-up; they
              are not automatically valid campaign inputs.
            </p>
          </div>
          <div className="review-grid">
            <article className="review-card">
              <h3>Your choices</h3>
              <dl>
                <div>
                  <dt>Source</dt>
                  <dd>{selected?.label}</dd>
                </div>
                <div>
                  <dt>Particles</dt>
                  <dd>{particles.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>s₀ / detuning / radius</dt>
                  <dd>
                    {s0} / {detuning} Γ / {radiusMm} mm
                  </dd>
                </div>
                <div>
                  <dt>Selection seed</dt>
                  <dd>{preview.plan.selection.seed}</dd>
                </div>
                <div>
                  <dt>MOT seed</dt>
                  <dd>{preview.plan.execution.mot_seed}</dd>
                </div>
                <div>
                  <dt>Execution</dt>
                  <dd>{mode === "local" ? "This computer" : "Zeus"}</dd>
                </div>
              </dl>
            </article>
            <article className="review-card">
              <h3>Locked science</h3>
              <p>
                RK4StHybridCustom · 0.625 µs timestep · 25 ms simulated duration
                · gravity enabled.
              </p>
              <p>
                <strong>Survivor rule:</strong>{" "}
                <code>mot_2d_extract_survivors_v1</code> applies the reviewed
                2D-MOT exit and capture boundaries consistently.
              </p>
              <details>
                <summary>View reviewed settings</summary>
                <pre className="settings-json">
                  {JSON.stringify(preview.plan.locked_settings, null, 2)}
                </pre>
              </details>
            </article>
          </div>
          <div className="form-actions">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => setStep("configure")}
            >
              Change choices
            </button>
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void create()}
            >
              {busy ? "Creating…" : "Create reviewed run"}
            </button>
          </div>
          <ActionError error={error} />
        </section>
      )}
      {step === "run" && runId && (
        <section className="run-stage">
          <div className="action-banner">
            <Play />
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
          {mode === "zeus" && (
            <>
              <div className="form-field">
                <label htmlFor="mot2d-zeus-username">Technion username</label>
                <input
                  id="mot2d-zeus-username"
                  value={username}
                  disabled={zeusToken !== null}
                  pattern="[A-Za-z][A-Za-z0-9._-]{0,31}"
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              {zeusToken && (
                <div className="scientific-role-note">
                  <strong>Zeus submission reviewed</strong>
                  <p>
                    The connection profile is frozen for this reviewed
                    submission.{" "}
                    {run
                      ? "Confirm to link the existing job without submitting new work."
                      : "Confirm to submit exactly one job."}
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
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => {
                      setZeusToken(null);
                      setZeusResources(null);
                    }}
                  >
                    Change connection
                  </button>
                </div>
              )}
            </>
          )}
          <div className="form-actions">
            <button
              className="primary-button"
              disabled={
                busy ||
                Boolean(run?.execution.locally_scheduled) ||
                (mode === "zeus" &&
                  !/^[A-Za-z][A-Za-z0-9._-]{0,31}$/.test(username))
              }
              onClick={() => void start()}
            >
              {mode === "local" ? <Play /> : <Server />}
              {busy
                ? "Working…"
                : mode === "zeus"
                  ? zeusToken
                    ? run && mode === "zeus"
                      ? "Confirm and link existing Zeus job"
                      : "Confirm and submit one Zeus job"
                    : "Review Zeus submission"
                  : "Start on this computer"}
            </button>
          </div>
          <ActionError error={error} />
        </section>
      )}
      {step === "monitor" && (
        <section className="run-stage">
          {(() => {
            const copy = mot2dMonitorCopy(
              zeusHeld ? "held" : run?.record_state,
              run?.execution.mode ?? mode,
              Boolean(run?.execution.progress),
              run?.execution.locally_scheduled ?? false,
            );
            return (
              <div
                className={`action-banner ${copy.attention ? "action-banner--attention" : "action-banner--running"}`}
              >
                <LoaderCircle className={busy ? "spin" : ""} />
                <div>
                  <strong>{copy.title}</strong>
                  <p>{copy.body}</p>
                </div>
              </div>
            );
          })()}
          {mode === "zeus" && (
            <p role="status">
              <strong>Zeus Job ID:</strong>{" "}
              {run?.execution.zeus_job_id ??
                submittedJobId ??
                "Awaiting verified job identity"}
            </p>
          )}
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
              disabled={busy || recoveryPending}
              onClick={() => void refresh()}
            >
              {busy ? "Checking…" : "Check status"}
            </button>
          </div>
          <ActionError error={error} />
        </section>
      )}
      {step === "results" && run && (
        <section className="run-stage">
          <div className="success-panel">
            <CheckCircle2 />
            <h2>Verified results are ready</h2>
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              forgetIndividualRun("mot_2d");
              onBack();
            }}
          >
            Configure another simulation
          </button>
          <div className="scientific-role-note">
            <strong>Scientific role: individual only</strong>
            <p>
              Retained states are not validated campaign inputs unless a
              separate validation accepts them.
            </p>
          </div>
          <article className="review-card">
            <h3>Summary</h3>
            <dl>
              <div>
                <dt>Selected Zeeman survivors</dt>
                <dd>{run.metrics?.n_input?.toLocaleString() ?? "—"}</dd>
              </div>
              <div>
                <dt>2D-MOT survivors</dt>
                <dd>{run.metrics?.n_survivors?.toLocaleString() ?? "—"}</dd>
              </div>
              <div>
                <dt>Conditional capture among selected Zeeman survivors</dt>
                <dd>
                  {run.metrics?.conditional_efficiency === undefined
                    ? "—"
                    : `${(100 * run.metrics.conditional_efficiency).toFixed(3)}%`}
                </dd>
              </div>
              <div>
                <dt>Runtime</dt>
                <dd>
                  {run.metrics?.elapsed_s === undefined
                    ? "—"
                    : `${run.metrics.elapsed_s.toFixed(3)} s`}
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
                    provenance: run.provenance,
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

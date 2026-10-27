import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IndividualZeemanRun } from "../components/IndividualZeemanRun";
import { IndividualMot2DRun } from "../components/IndividualMot2DRun";
import { IndividualMot3DRun } from "../components/IndividualMot3DRun";
import type { IndividualZeemanApi } from "../api/clients/individualZeeman";
import type { IndividualMot2DApi } from "../api/clients/individualMot2D";
import type { IndividualMot3DApi } from "../api/clients/individualMot3D";
import { localRunNeedsInspection } from "../features/individual/localRunInspection";

const families = [
  {
    family: "zeeman",
    name: "zeeman-interrupted",
    Component: IndividualZeemanRun,
  },
  {
    family: "mot_2d",
    name: "mot2d-interrupted",
    Component: IndividualMot2DRun,
  },
  {
    family: "mot_3d",
    name: "mot3d-interrupted",
    Component: IndividualMot3DRun,
  },
] as const;

beforeEach(() => localStorage.clear());

describe.each(families)(
  "$family saved local execution",
  ({ family, name, Component }) => {
    function setup(state = "running", scheduled = false) {
      const saved = {
        id: "individual-run-" + "a".repeat(24),
        display_name: name,
        lifecycle: state,
        record_state: state,
        execution: {
          mode: "local" as const,
          locally_scheduled: scheduled,
          progress: null,
        },
        retention: { status: "pending", particle_states_requested: true },
      };
      const api = {
        sources: vi.fn().mockResolvedValue([]),
        runs: vi.fn().mockResolvedValue([saved]),
        run: vi.fn(),
        preview: vi.fn(),
        confirm: vi.fn(),
        startLocal: vi.fn(),
        previewZeus: vi.fn(),
        confirmZeus: vi.fn(),
        recoverZeus: vi.fn(),
        refreshZeus: vi.fn(),
        reset: vi.fn(),
      };
      const storageKey = `ytterbium.individual-run.${family}.v1`;
      const remembered = JSON.stringify({
        version: 1,
        family,
        display_name: name,
        execution_mode: "local",
      });
      localStorage.setItem(storageKey, remembered);
      // Each component uses only its existing typed API; no production path is mocked globally.
      const element = (
        <Component
          api={
            api as unknown as IndividualZeemanApi &
              IndividualMot2DApi &
              IndividualMot3DApi
          }
          onBack={vi.fn()}
        />
      );
      return { saved, api, storageKey, remembered, element };
    }

    it.each(["running", "outcome_unknown"])(
      "opens configuration for a stale %s record without discarding or restarting it",
      async (state) => {
        const user = userEvent.setup();
        const { api, storageKey, remembered, element, saved } = setup(state);
        const before = structuredClone(saved);
        const view = render(element);
        await screen.findByText("Previous local run needs inspection");
        expect(screen.getByText("Current step: configure")).toBeInTheDocument();
        expect(
          screen.queryByText("Local execution needs inspection"),
        ).not.toBeInTheDocument();
        expect(localStorage.getItem(storageKey)).toBe(remembered);
        await user.click(
          screen.getByRole("button", { name: "Inspect saved run" }),
        );
        await screen.findByText("Local execution needs inspection");
        if (family === "zeeman")
          expect(
            screen.getByText("Needs inspection", { exact: true }),
          ).toBeVisible();
        await user.click(
          screen.getByRole("button", {
            name: "Configure a separate simulation",
          }),
        );
        expect(screen.getByText("Current step: configure")).toBeInTheDocument();
        expect(localStorage.getItem(storageKey)).toBe(remembered);
        expect(saved).toEqual(before);
        expect(api.confirm).not.toHaveBeenCalled();
        expect(api.startLocal).not.toHaveBeenCalled();
        expect(api.confirmZeus).not.toHaveBeenCalled();
        view.unmount();
        render(element);
        await screen.findByText("Previous local run needs inspection");
        expect(screen.getByText("Current step: configure")).toBeInTheDocument();
        expect(api.startLocal).not.toHaveBeenCalled();
      },
    );

    it("ignores retired StrictMode recovery reads without restarting the saved run", async () => {
      const { api, element, saved } = setup();
      let release!: (rows: (typeof saved)[]) => void;
      api.runs.mockReturnValueOnce(
        new Promise((resolve) => {
          release = resolve;
        }),
      );
      render(<StrictMode>{element}</StrictMode>);
      await screen.findByText("Previous local run needs inspection");
      release([
        { ...saved, record_state: "succeeded", lifecycle: "results_ready" },
      ]);
      await waitFor(() => expect(api.runs).toHaveBeenCalledTimes(2));
      expect(screen.getByText("Current step: configure")).toBeInTheDocument();
      expect(api.run).not.toHaveBeenCalled();
      expect(api.startLocal).not.toHaveBeenCalled();
    });

    if (family === "zeeman")
      it("does not switch to saved inspection during a pending new validation", async () => {
        const user = userEvent.setup();
        const { api, element } = setup();
        let reject!: (error: Error) => void;
        api.preview.mockReturnValue(
          new Promise((_resolve, fail) => {
            reject = fail;
          }),
        );
        render(element);
        await screen.findByText("Previous local run needs inspection");
        await user.click(
          screen.getByRole("button", { name: "Validate and review" }),
        );
        await waitFor(() => expect(api.preview).toHaveBeenCalledOnce());
        expect(
          screen.getByRole("button", { name: "Inspect saved run" }),
        ).toBeDisabled();
        await user.click(
          screen.getByRole("button", { name: "Inspect saved run" }),
        );
        expect(
          screen.getByRole("spinbutton", { name: /Particle count/i }),
        ).toBeVisible();
        expect(
          screen.queryByText("Local execution needs inspection"),
        ).not.toBeInTheDocument();
        reject(new Error("Controlled preview failure"));
        await screen.findByText("Controlled preview failure");
        expect(
          screen.getByRole("button", { name: "Inspect saved run" }),
        ).toBeEnabled();
        expect(api.startLocal).not.toHaveBeenCalled();
        expect(api.confirm).not.toHaveBeenCalled();
      });

    it("continues to recover a genuinely scheduled local run automatically", async () => {
      const { api, element } = setup("running", true);
      render(element);
      await waitFor(() =>
        expect(screen.getByText("Current step: monitor")).toBeInTheDocument(),
      );
      await waitFor(() => expect(api.runs).toHaveBeenCalled());
      expect(
        screen.queryByText("Previous local run needs inspection"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", {
          name: "Configure a separate simulation",
        }),
      ).not.toBeInTheDocument();
      expect(api.startLocal).not.toHaveBeenCalled();
    });
  },
);

it("only offers inspection for local running records without worker evidence", () => {
  const base = {
    id: "id",
    display_name: "name",
    lifecycle: "running",
    record_state: "running",
    execution: {
      mode: "local" as const,
      locally_scheduled: false,
      progress: null,
    },
  };
  expect(localRunNeedsInspection(base)).toBe(true);
  expect(
    localRunNeedsInspection({
      ...base,
      execution: { ...base.execution, progress: {} },
    }),
  ).toBe(false);
  expect(
    localRunNeedsInspection({
      ...base,
      execution: { ...base.execution, mode: "zeus" },
    }),
  ).toBe(false);
  expect(
    localRunNeedsInspection({
      ...base,
      record_state: "succeeded",
      lifecycle: "results_ready",
    }),
  ).toBe(false);
  expect(localRunNeedsInspection({ ...base, record_state: "configured" })).toBe(
    false,
  );
});

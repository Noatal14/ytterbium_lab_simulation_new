import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunProgressPanel } from "../components/RunProgressPanel";

describe("RunProgressPanel", () => {
  it("shows reliable particle progress and runtime", () => {
    render(<RunProgressPanel progress={{ completed_particles: 25, total_particles: 100, fraction: 0.25, runtime_s: 8.4 }} />);
    expect(screen.getByRole("progressbar", { name: "Simulation 25 percent complete" })).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("25 of 100 particles")).toBeVisible();
    expect(screen.getByText("Runtime 8 s")).toBeVisible();
  });

  it("does not invent a percentage before telemetry is available", () => {
    render(<RunProgressPanel progress={null} />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(/Waiting for reliable particle progress/)).toBeVisible();
  });
});

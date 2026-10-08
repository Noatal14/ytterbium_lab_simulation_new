import axe from "axe-core";
import { render, screen } from "@testing-library/react";
import { App } from "../App";
import { fixtureApi } from "./campaignFixture";

describe("accessibility contract", () => {
  it("provides landmarks, a single page title, and an explained disabled action", () => {
    render(<App api={fixtureApi} />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText(/completed canonical 2D-MOT campaign has not been selected/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start 2D-MOT campaign/ })).toHaveAccessibleDescription(/read-only milestone/i);
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<App api={fixtureApi} />);
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });
});

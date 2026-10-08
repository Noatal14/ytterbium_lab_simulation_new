import { render, screen } from "@testing-library/react";
import { App } from "../App";

describe("onboarding home", () => {
  it("guides a new operator without enabling later or blocked workflows", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Run a new campaign" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start 2D-MOT campaign/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Start 3D-MOT campaign/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Open existing campaign/ })).toBeDisabled();
    expect(screen.getByText(/read-only preview/i)).toBeInTheDocument();
  });

  it("renders honest sample labels and values as adjacent definition pairs", () => {
    render(<App />);
    const branchLabel = screen.getByText("Branch");
    expect(branchLabel.tagName).toBe("DT");
    expect(branchLabel.nextElementSibling).toHaveTextContent("Unavailable in sample data");
    const zeusLabel = screen.getByText("Zeus connection");
    expect(zeusLabel.tagName).toBe("DT");
    expect(zeusLabel.nextElementSibling).toHaveTextContent("Not configured in sample data");
  });

  it("uses the same icon-and-label pattern for every navigation item", () => {
    render(<App />);
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(navigation.querySelectorAll("svg")).toHaveLength(3);
  });
});

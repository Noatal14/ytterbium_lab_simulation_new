import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { fixtureApi } from "./campaignFixture";
import { afterEach, expect, it, vi } from "vitest";
import { zeusProjectDirectory, zeusTestMode } from "../api/zeusEnvironment";
afterEach(() => vi.unstubAllEnvs());
it("selects the fixed isolated target only in the explicit test mode", () => {
  vi.stubEnv("MODE", "zeus-test");
  expect(zeusTestMode()).toBe(true);
  expect(zeusProjectDirectory("tal.noa")).toBe("/home/tal.noa/ytterbium_lab_simulation_ui_test");
  vi.stubEnv("MODE", "development");
  expect(zeusTestMode()).toBe(false);
  expect(zeusProjectDirectory("tal.noa")).toBe("/home/tal.noa/ytterbium_lab_simulation_new");
});

it("keeps campaign actions out of the isolated environment", async () => {
  vi.stubEnv("MODE", "zeus-test");
  render(<App api={fixtureApi} />);
  expect(screen.getByText("Isolated Zeus test environment")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Start .*campaign/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open campaign" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "Zeus connection" }));
  expect(screen.queryByRole("button", { name: "Inspect campaign" })).not.toBeInTheDocument();
});

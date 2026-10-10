import { expect, test } from "@playwright/test";

test("browser uses the real workflow handler session and CSRF boundary", async ({ page }) => {
  const session = await page.request.get("http://127.0.0.1:8765/api/v1/session", {
    headers: { "Sec-Fetch-Site": "same-origin" },
  });
  expect(session.status()).toBe(200);

  const rejected = await page.request.post("http://127.0.0.1:8765/api/v1/zeus/snapshot", {
    data: {
      username: "tal.noa",
      project_directory: "/home/tal.noa/ytterbium_lab_simulation_new",
    },
    headers: {
      Origin: "http://127.0.0.1:8765",
      "Sec-Fetch-Site": "same-origin",
    },
  });
  expect(rejected.status()).toBe(403);
  await expect(rejected.json()).resolves.toMatchObject({
    error: { code: "invalid_csrf" },
  });

  await page.goto("/");
  await page.getByRole("link", { name: "Zeus jobs" }).click();

  await page.getByLabel("Technion username").fill("tal.noa");
  await expect(page.getByLabel("Remote project directory")).toHaveValue(
    "/home/tal.noa/ytterbium_lab_simulation_new",
  );
  await page.getByRole("button", { name: "Connect and check status" }).click();

  await expect(page.getByText("Connected — read-only snapshot received")).toBeVisible();
  await expect(page.getByText(/Branch integration-fake/)).toBeVisible();
  await expect(page.getByText("No jobs were returned")).toBeVisible();
});

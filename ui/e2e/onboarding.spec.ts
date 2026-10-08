import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("new operator sees the safe starting path", async ({ page, browserName }) => {
  await page.route("**/api/v1/campaigns", (route) => route.fulfill({ json: { api_version: 1, data: { campaigns: [], invalid_count: 0, total: 0 } } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Run or inspect a campaign" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Start 2D-MOT campaign/ })).toBeEnabled();
  await expect(page.getByRole("button", { name: /Start 3D-MOT campaign/ })).toBeDisabled();
  await expect(page.getByText("No campaign records found")).toBeVisible();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflows).toBe(false);

  const homeLink = page.getByRole("link", { name: "Home" });
  if (browserName === "webkit") {
    await homeLink.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(homeLink).toBeFocused();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

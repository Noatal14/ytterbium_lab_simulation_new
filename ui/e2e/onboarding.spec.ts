import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("new operator sees the safe starting path", async ({ page, browserName }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Run a new campaign" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Start 2D-MOT campaign/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Start 3D-MOT campaign/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Open existing campaign/ })).toBeDisabled();
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

import { expect, test } from "@playwright/test";

test("overview reports a healthy stack", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Everything is running" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("CPU worker", { exact: true })).toBeVisible();
});

test("self-test runs end to end from the UI", async ({ page }) => {
  await page.goto("/");
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "System self-test" }) });
  await panel.getByRole("button", { name: /Run (self-test|again)/ }).click();
  await expect(panel.getByText("Done")).toBeVisible({ timeout: 90_000 });
  await expect(panel.getByText(/MP in .* s/)).toBeVisible();
});

test("update center opens with release information", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Update available|Updates and release notes/ }).click();
  const dialog = page.getByRole("dialog", { name: "Updates and release notes" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/up to date|is available/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("command palette navigates", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Go to a page or run an action…").fill("forge");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/forge$/);
  await expect(page.getByRole("heading", { name: "Forge", level: 2 })).toBeVisible();
});

test("unknown pages show a way back", async ({ page }) => {
  await page.goto("/does-not-exist");
  await expect(page.getByText("This page doesn't exist")).toBeVisible();
});

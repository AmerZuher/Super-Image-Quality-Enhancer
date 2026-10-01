/**
 * Captures the README screenshots into ../gallery. Run with `make gallery` (stack must be up).
 * File names are stable so the README never needs editing when screenshots are refreshed.
 */
import { fileURLToPath } from "node:url";
import { expect, type Page, test } from "@playwright/test";

const OUT = fileURLToPath(new URL("../../gallery", import.meta.url));

async function useTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((t) => {
    localStorage.setItem("siqe-ui", JSON.stringify({ state: { theme: t }, version: 0 }));
  }, theme);
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
}

test.describe.configure({ mode: "serial" });

test("prepare: run a self-test so the overview has results @gallery", async ({ request }) => {
  const job = await (await request.post("/api/jobs/self-test")).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).state, { timeout: 120_000 })
    .toBe("succeeded");
});

for (const theme of ["dark", "light"] as const) {
  test(`overview, ${theme} @gallery`, async ({ page }) => {
    await useTheme(page, theme);
    await page.goto("/");
    await expect(page.getByText(/MP in .* s/)).toBeVisible({ timeout: 30_000 });
    await settle(page);
    await page.screenshot({ path: `${OUT}/overview-${theme}.png` });
  });
}

// The README captions this screenshot as an example: it shows how a future release looks.
const EXAMPLE_UPDATE = {
  current_version: "0.1.0",
  latest_version: "0.2.0",
  update_available: true,
  newer: [
    {
      tag: "v0.2.0",
      version: "0.2.0",
      name: "Studio",
      notes:
        "## New\n- **Studio workspace**: non-destructive edit stack with live GPU preview\n- Curves, levels, HSL and `.cube` LUT import\n- Compare viewer with slider, split and difference modes\n\n## Fixed\n- Self-test no longer waits forever when the GPU worker restarts mid-run",
      url: "https://github.com/AmerZuher/Super-Image-Quality-Enhancer/releases/tag/v0.2.0",
      published_at: "2026-10-20T09:00:00Z",
      prerelease: false,
    },
  ],
  current: null,
  checked_at: new Date().toISOString(),
  error: null,
  repo_url: "https://github.com/AmerZuher/Super-Image-Quality-Enhancer",
  releases_url: "https://github.com/AmerZuher/Super-Image-Quality-Enhancer/releases",
};

test("update center @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.route("**/api/updates*", (route) => route.fulfill({ json: EXAMPLE_UPDATE }));
  await page.goto("/");
  await page.getByRole("button", { name: /Update available|Updates and release notes/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/update-center.png` });
});

test("command palette @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto("/");
  await settle(page);
  await page.keyboard.press("Control+k");
  await expect(page.getByPlaceholder("Go to a page or run an action…")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/command-palette.png` });
});

for (const [route, name] of [
  ["/jobs", "jobs"],
  ["/ai-lab", "ai-lab-preview"],
  ["/forge", "forge-preview"],
  ["/settings", "settings"],
] as const) {
  test(`${name} @gallery`, async ({ page }) => {
    await useTheme(page, "dark");
    await page.goto(route);
    await settle(page);
    await page.screenshot({ path: `${OUT}/${name}.png` });
  });
}

test("overview on a phone @gallery", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await useTheme(page, "dark");
  await page.goto("/");
  await expect(page.getByText(/MP in .* s/)).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/overview-phone.png` });
  await context.close();
});

import { type APIRequestContext, expect, type Page, test } from "@playwright/test";
import { uniquePng } from "./images";

test.describe.configure({ mode: "serial" });

const STAMP = Date.now().toString(36);
const made: string[] = [];
const uploaded: string[] = [];

async function upload(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post(`/api/assets?filename=${encodeURIComponent(name)}`, {
    data: uniquePng(),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(response.ok()).toBeTruthy();
  const id = (await response.json()).asset.id as string;
  uploaded.push(id);
  await expect
    .poll(async () => (await (await request.get(`/api/assets/${id}`)).json()).status, { timeout: 60_000 })
    .toBe("ready");
  return id;
}

/** Opens "New flow", wherever the flow list is at this width (docked, in a drawer, or empty state). */
async function openNewFlow(page: Page) {
  await page.goto("/flows");
  const start = page.getByRole("button", { name: /^(New flow|Make your first flow|Flows)$/ }).first();
  await start.click();
  const drawer = page.getByRole("dialog", { name: "Flows" });
  if (await drawer.isVisible()) await drawer.getByRole("button", { name: "New flow" }).click();
}

async function flowId(page: Page): Promise<string> {
  await expect(page).toHaveURL(/flow=/);
  return new URL(page.url()).searchParams.get("flow") as string;
}

test.afterAll(async ({ request }) => {
  for (const id of made) await request.delete(`/api/flows/${id}`);
  await request.post("/api/library/quarantine", { data: { asset_ids: uploaded } });
  await request.post("/api/library/delete", { data: { asset_ids: uploaded } });
});

test("start from a recipe, change a block, and dry-run it", async ({ page, request }) => {
  test.setTimeout(180_000);
  await upload(request, `e2e flow ${STAMP}.png`);
  await openNewFlow(page);
  const dialog = page.getByRole("dialog", { name: "New flow" });
  await dialog.getByLabel("Name").fill(`e2e gallery ${STAMP}`);
  await dialog.getByText("Web gallery", { exact: true }).click();
  await dialog.getByRole("button", { name: "Create flow" }).click();
  made.push(await flowId(page));

  await expect(page.getByRole("heading", { name: `e2e gallery ${STAMP}` })).toBeVisible();
  const resize = page.getByTestId("block-size"); // the recipe's Resize block
  await resize.click();
  const inspector = page.getByTestId("block-inspector");
  await expect(inspector).toBeVisible();
  await inspector.getByLabel("Size").fill("640");
  await expect(resize).toContainText("640 px");
  await expect(page.getByText("Saved", { exact: true })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "Run", exact: true }).click();
  const run = page.getByRole("dialog", { name: /^Run / });
  await run.getByLabel(/Every image in the Library/).check();
  await expect(run.getByLabel(/Dry run first/)).toBeChecked();
  await run.getByLabel("At most this many images").fill("2");
  await run.getByRole("button", { name: "Start dry run" }).click();

  await expect(page).toHaveURL(/tab=runs/);
  const results = page.getByRole("region", { name: "Run results" });
  await expect(results.getByText("Done", { exact: true }).first()).toBeVisible({ timeout: 120_000 });
  await expect(results.getByTestId("run-item")).toHaveCount(2);
  await expect(results.getByRole("link", { name: /Download exported files/ })).toBeVisible();
});

test("build a flow from blocks; problems show until it can run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openNewFlow(page);
  const dialog = page.getByRole("dialog", { name: "New flow" });
  await dialog.getByLabel("Name").fill(`e2e blank ${STAMP}`);
  await dialog.getByText("A blank canvas").click();
  await dialog.getByRole("button", { name: "Create flow" }).click();
  made.push(await flowId(page));

  await expect(page.getByText(/1 problem/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeDisabled();

  // Select the Images block, then add blocks: each new one connects to the selected one.
  await page.getByTestId("block-in").click();
  await page.getByRole("button", { name: "Add block" }).click();
  await page.getByRole("button", { name: "Add Resize" }).click();
  await expect(page.getByTestId("block-resize-1")).toBeVisible();
  await page.getByRole("button", { name: "Add block" }).click();
  await page.getByRole("button", { name: "Add Export" }).click();
  await expect(page.getByTestId("block-export-1")).toBeVisible();

  await expect(page.getByText(/problem/)).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeEnabled();

  // Removing the finish block brings the problem back.
  await page.getByTestId("block-export-1").click();
  await page.getByTestId("block-inspector").getByRole("button", { name: "Remove block" }).click();
  await expect(page.getByText(/1 problem/)).toBeVisible({ timeout: 10_000 });
});

test("the Library's selection opens a run on those images", async ({ page, request }) => {
  const names = [`e2e pick ${STAMP} a.png`, `e2e pick ${STAMP} b.png`];
  for (const name of names) await upload(request, name);
  await page.goto(`/library?q=${encodeURIComponent(`e2e pick ${STAMP}`)}`);
  for (const name of names) await page.getByRole("checkbox", { name: `Select ${name}` }).check();
  await page.getByRole("link", { name: "Run a flow" }).click();
  await expect(page).toHaveURL(/source=selection/);
  const run = page.getByRole("dialog", { name: /^Run / });
  await expect(run.getByLabel(/The 2 images selected in the Library/)).toBeChecked();
  await run.getByRole("button", { name: "Cancel" }).click();
  await expect(page).not.toHaveURL(/source=selection/);
});

test("Settings makes an API key that is shown once", async ({ page, request }) => {
  await page.goto("/settings");
  const name = `e2e key ${STAMP}`;
  await page.getByLabel("New key name").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  await expect(page.getByText(`Key “${name}” created`)).toBeVisible();
  await expect(page.getByRole("status").getByText(/^siqe_.{40,}$/)).toBeVisible();
  const keys = await (await request.get("/api/keys")).json();
  const key = keys.find((k: { name: string }) => k.name === name);
  expect(key).toBeTruthy();
  await page.getByRole("button", { name: `Revoke ${name}` }).click();
  await page.getByRole("button", { name: `Confirm revoking ${name}` }).click();
  await expect(page.getByRole("listitem").filter({ hasText: name }).getByText("Revoked")).toBeVisible();
});

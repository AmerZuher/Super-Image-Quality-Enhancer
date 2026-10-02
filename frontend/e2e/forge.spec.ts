import { type APIRequestContext, expect, type Page, test } from "@playwright/test";
import { uniquePng } from "./images";

test.describe.configure({ mode: "serial" });

const STAMP = Date.now().toString(36);
const projects: string[] = [];
const datasets: string[] = [];
const uploaded: string[] = [];
const models: string[] = [];

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

/** Opens "New model", wherever the model list is at this width. */
async function newModel(page: Page, name: string, template: RegExp) {
  await page.goto("/forge");
  await page
    .getByRole("button", { name: /^(New model|Make your first model|Models)$/ })
    .first()
    .click();
  const list = page.getByRole("dialog", { name: "Models" });
  if (await list.isVisible()) await list.getByRole("button", { name: "New model" }).click();
  const dialog = page.getByRole("dialog", { name: "New model" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByText(template).click();
  await dialog.getByRole("button", { name: "Create model" }).click();
  await expect(page).toHaveURL(/project=/);
  const id = new URL(page.url()).searchParams.get("project") as string;
  projects.push(id);
  return id;
}

test.afterAll(async ({ request }) => {
  for (const id of models) await request.delete(`/api/models/${id}`);
  for (const run of await (await request.get("/api/forge/runs")).json()) {
    if (projects.includes(run.project_id)) {
      await request.post(`/api/forge/runs/${run.id}/stop`);
      await expect
        .poll(async () => (await (await request.get(`/api/forge/runs/${run.id}`)).json()).run.state, {
          timeout: 120_000,
        })
        .not.toMatch(/queued|running/);
      await request.delete(`/api/forge/runs/${run.id}`);
    }
  }
  for (const id of datasets) await request.delete(`/api/forge/datasets/${id}`);
  for (const id of projects) await request.delete(`/api/forge/projects/${id}`);
  await request.post("/api/library/quarantine", { data: { asset_ids: uploaded } });
  await request.post("/api/library/delete", { data: { asset_ids: uploaded } });
});

test("design a model: shapes are checked as you edit, and problems come with a fix", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await newModel(page, `e2e espcn ${STAMP}`, /^ESPCN/);
  const summary = page.getByTestId("forge-summary");
  await expect(summary.getByText("Ready to train")).toBeVisible();
  await expect(summary.getByText("22,729")).toBeVisible();

  await page.getByTestId("forge-block-c3").click();
  const inspector = page.getByTestId("forge-inspector");
  await inspector.getByLabel("Filters").fill("8");
  await expect(page.getByTestId("forge-block-shuffle")).toContainText("divisible by 9");
  await page.getByTestId("forge-block-shuffle").click();
  await inspector.getByRole("button", { name: /Set the block before it to 9 filters/ }).click();
  await expect(page.getByTestId("forge-block-shuffle")).not.toContainText("divisible");
  await expect(page.getByText("Saved", { exact: true })).toBeVisible({ timeout: 10_000 });

  // Adding a block after the selected one keeps the chain linked.
  await page.getByTestId("forge-block-c1").click();
  await page.getByRole("button", { name: "Add block" }).click(); // the palette is docked only on wide screens
  await page.getByRole("button", { name: "Add Channel attention" }).click();
  await expect(page.getByTestId("forge-block-attention1")).toBeVisible();
  await page.locator(".react-flow__pane").click({ position: { x: 20, y: 400 } });
  await expect(summary.getByText("Ready to train")).toBeVisible();

  await page.getByRole("tab", { name: "Code" }).click();
  await expect(page.getByTestId("forge-code")).toContainText("class ");
  await expect(page.getByTestId("forge-code")).toContainText("ChannelAttention");
});

test("build a dataset, train on it, watch it learn, and publish to AI Lab", async ({ page, request }) => {
  test.setTimeout(420_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const ids = [];
  for (let i = 0; i < 3; i++) ids.push(await upload(request, `e2e forge ${STAMP} ${i}.png`));
  const made = await request.post("/api/forge/datasets", {
    data: {
      name: `e2e photos ${STAMP}`,
      source: { kind: "assets", asset_ids: ids },
      settings: { crop: 96, crops_per_image: 3, min_width: 200, min_height: 200, val_every: 2 },
    },
  });
  expect(made.ok()).toBeTruthy();
  const dataset = await made.json();
  datasets.push(dataset.id);

  const project = await newModel(page, `e2e train ${STAMP}`, /^ESPCN/);
  await page.goto(`/forge?project=${project}&tab=data&dataset=${dataset.id}`);
  const detail = page.getByTestId("forge-dataset");
  await expect(detail.getByText("Done", { exact: true })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("forge-preview")).toBeVisible();

  await page.getByRole("tab", { name: "Train" }).click();
  const form = page.getByTestId("forge-train-form");
  await form.getByLabel("Dataset").selectOption(dataset.id);
  await expect(form.getByLabel(/^Patch/)).toHaveValue("32"); // fitted to 96 px crops at ×3
  await form.getByLabel(/^Steps/).fill("40");
  await form.getByLabel(/^Batch/).fill("4");
  await form.getByLabel(/^Check every/).fill("20");
  await form.getByRole("button", { name: "Start training" }).click();
  await expect(page).toHaveURL(/run=/);

  const run = page.getByTestId("forge-run");
  await expect(run.getByText("Done", { exact: true })).toBeVisible({ timeout: 300_000 });
  await expect(run.getByText("Step 40 of 40")).toBeVisible();
  await expect(page.getByTestId("forge-sample")).toBeVisible();
  await expect(run.getByRole("img", { name: /PSNR on held-out crops/ })).toBeVisible();

  const publish = run.getByRole("region", { name: "Publish" });
  await publish.getByLabel("Name in AI Lab").fill(`e2e model ${STAMP}`);
  await publish.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(publish.getByText(/^Added e2e model .* to AI Lab/)).toBeVisible({ timeout: 180_000 });
  await expect(publish.getByText("Published", { exact: true })).toBeVisible();
  const runId = new URL(page.url()).searchParams.get("run") as string;
  const modelId = (await (await request.get(`/api/forge/runs/${runId}`)).json()).run.model_id as string;
  models.push(modelId);

  await page.goto("/ai-lab");
  await page.getByRole("tab", { name: /Models/ }).click();
  const card = page.getByTestId(`model-${modelId}`);
  await expect(card).toBeVisible();
  await expect(card.getByText("Trained in Forge", { exact: true })).toBeVisible();
  await expect(card.getByText(/dB \(/)).toBeVisible();
});

test("works at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/forge");
  await expect(page.getByRole("list", { name: "Models" })).toBeVisible();
  const first = page.getByRole("list", { name: "Models" }).getByRole("button").first();
  await first.click();
  await expect(page.getByRole("tab", { name: "Design" })).toBeVisible();
  await page.getByRole("button", { name: "Model size and problems" }).click();
  await expect(page.getByRole("dialog", { name: "This model" })).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
});

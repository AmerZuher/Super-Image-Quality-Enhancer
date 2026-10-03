/**
 * Captures the README screenshots into ../gallery. Run with `make gallery` (stack must be up).
 * File names are stable so the README never needs editing when screenshots are refreshed.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

const OUT = fileURLToPath(new URL("../../gallery", import.meta.url));
const SAMPLES = fileURLToPath(new URL("../../samples", import.meta.url));

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
        "## New\n- **Studio**: non-destructive editing with a live GPU preview\n- Crop, rotate and flip with aspect presets\n- Compare with split, side-by-side and difference views\n- Export to JPEG, PNG, WebP, AVIF or TIFF with a target file size\n\n## Fixed\n- Self-test no longer waits forever when the GPU worker restarts mid-run",
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

// ---------------------------------------------------------------------------------- Studio

let studioAsset = "";

async function waitForJob(request: APIRequestContext, id: string, timeout = 120_000) {
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).state, { timeout })
    .toBe("succeeded");
}

async function upload(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post(`/api/assets?filename=${encodeURIComponent(name)}`, {
    data: readFileSync(`${SAMPLES}/${name}`),
    headers: { "Content-Type": "application/octet-stream" },
  });
  const body = await response.json();
  if (body.job) await waitForJob(request, body.job.id);
  return body.asset.id as string;
}

test("prepare: images, edits and an export for Studio @gallery", async ({ request }) => {
  for (const name of ["valley.jpg", "rose-blue.jpg", "teton-reflection.jpg", "moose-lake.jpg"]) {
    await upload(request, name);
  }
  studioAsset = await upload(request, "lake-pier.jpg");
  // Start the export list clean so the screenshot shows only this run's export.
  for (const r of await (await request.get(`/api/assets/${studioAsset}/renditions`)).json()) {
    await request.delete(`/api/renditions/${r.id}`);
  }
  const edits = {
    version: 1,
    ops: [
      { id: "exposure", params: { ev: 0.3 } },
      { id: "highlights", params: { amount: -35 } },
      { id: "shadows", params: { amount: 30 } },
      { id: "contrast", params: { amount: 14 } },
      { id: "vibrance", params: { amount: 28 } },
      { id: "vignette", params: { amount: -30, midpoint: 0.45 } },
    ],
  };
  expect((await request.put(`/api/assets/${studioAsset}/edits`, { data: edits })).ok()).toBe(true);
  const started = await (
    await request.post(`/api/assets/${studioAsset}/exports`, { data: { format: "webp", target_kb: 120 } })
  ).json();
  await waitForJob(request, started.job.id);
});

async function openStudio(page: Page) {
  await page.goto(`/studio?asset=${studioAsset}`);
  await expect(page.getByRole("img", { name: "Preview of lake-pier.jpg" })).toBeVisible({ timeout: 30_000 });
  await settle(page);
}

test("studio, split compare @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openStudio(page);
  await page.getByRole("button", { name: "Split", exact: true }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/studio-dark.png` });
});

test("studio, side by side in light @gallery", async ({ page }) => {
  await useTheme(page, "light");
  await openStudio(page);
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/studio-light.png` });
});

test("studio, crop @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openStudio(page);
  await page.getByRole("tab", { name: "Crop" }).click();
  await page.getByRole("button", { name: "4:5" }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/studio-crop.png` });
  // Leave the stored edits as they were.
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible({ timeout: 10_000 });
});

test("studio, export @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openStudio(page);
  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByRole("radio", { name: /WebP/ }).check({ force: true });
  await expect(page.getByRole("link", { name: "Download" }).first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/studio-export.png` });
});

test("studio, inspector @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openStudio(page);
  await page.keyboard.press("i");
  const dialog = page.getByRole("dialog", { name: /Inspect/ });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/studio-inspect.png` });
});

test("studio on a phone @gallery", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await useTheme(page, "dark");
  await openStudio(page);
  await page.screenshot({ path: `${OUT}/studio-phone.png` });
  await context.close();
});

// ---------------------------------------------------------------------------------- AI Lab

type Run = { asset: string; result: string };
const runs: { pier?: Run; car?: Run } = {};

async function install(request: APIRequestContext, modelId: string) {
  const body = await (await request.post(`/api/models/${modelId}/install`)).json();
  if (body.job) await waitForJob(request, body.job.id);
}

async function aiRun(request: APIRequestContext, assetId: string, modelId: string): Promise<string> {
  const existing = await (await request.get(`/api/assets?parent_id=${assetId}`)).json();
  const done = existing.find(
    (a: { derivation?: { model_id?: string } }) => a.derivation?.model_id === modelId,
  );
  if (done) return done.id as string;
  const started = await (
    await request.post("/api/ai/runs", { data: { asset_id: assetId, model_id: modelId } })
  ).json();
  await waitForJob(request, started.job.id, 900_000); // the CPU is slow without a GPU
  const job = await (await request.get(`/api/jobs/${started.job.id}`)).json();
  return job.result.asset_id as string;
}

test("prepare: models and AI results @gallery", async ({ request }) => {
  test.setTimeout(900_000);
  await install(request, "realesrgan-x4plus");
  await install(request, "isnet-general");
  const pier = await upload(request, "lake-pier.jpg");
  runs.pier = { asset: pier, result: await aiRun(request, pier, "realesrgan-x4plus") };
  const car = await upload(request, "car.jpg");
  runs.car = { asset: car, result: await aiRun(request, car, "isnet-general") };
});

async function openLab(page: Page, run: Run | undefined) {
  if (!run) throw new Error("run the prepare step first");
  await page.goto(`/ai-lab?asset=${run.asset}&result=${run.result}`);
  await expect(page.getByText("After", { exact: true })).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.waitForTimeout(1500);
}

test("ai lab, compare @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openLab(page, runs.pier);
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/ailab-compare.png` });
});

test("ai lab, models @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await openLab(page, runs.pier);
  await page.getByRole("tab", { name: /Models/ }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/ailab-models.png` });
});

test("ai lab, cutout @gallery", async ({ page }) => {
  await useTheme(page, "light");
  await openLab(page, runs.car);
  await page.getByRole("button", { name: "Side by side" }).click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/ailab-cutout.png` });
});

test("ai lab, erase @gallery", async ({ page, request }) => {
  test.setTimeout(300_000);
  await install(request, "lama-erase");
  if (!runs.pier) throw new Error("run the prepare step first");
  // Start from no earlier erase results, so the list shows only this one.
  const children: { id: string; derivation?: { task?: string } }[] = await (
    await request.get(`/api/assets?parent_id=${runs.pier.asset}`)
  ).json();
  for (const child of children.filter((c) => c.derivation?.task === "erase")) {
    await request.delete(`/api/assets/${child.id}`);
  }
  await useTheme(page, "dark");
  await page.goto(`/ai-lab?asset=${runs.pier.asset}`);
  await page.getByRole("tab", { name: "Run" }).click();
  await page.getByRole("button", { name: "Erase objects", exact: true }).click();
  const layer = page.getByLabel("Paint over what to erase");
  await expect(layer).toBeVisible();
  await settle(page);
  const box = await layer.boundingBox();
  if (!box) throw new Error("paint layer not visible");
  // The two nearest pier posts.
  for (const x of [0.362, 0.617]) {
    await page.mouse.move(box.x + box.width * x, box.y + box.height * 0.57);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * x, box.y + box.height * 0.91, { steps: 12 });
    await page.mouse.up();
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/ailab-erase.png` });

  await page.getByRole("button", { name: "Erase painted areas" }).click();
  await expect(page.getByText("After", { exact: true })).toBeVisible({ timeout: 240_000 });
  await page.getByRole("button", { name: "Side by side" }).click();
  await settle(page);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/ailab-erase-result.png` });
});

// --------------------------------------------------------------------------------- Library

const LIBRARY_SAMPLES = [
  "lake-pier.jpg",
  "car.jpg",
  "lotus.jpg",
  "valley.jpg",
  "mountain-road.jpg",
  "teton-reflection.jpg",
  "turquoise-lake.jpg",
  "feather-blue.jpg",
  "moose-lake.jpg",
  "rose-blue.jpg",
  "leaf-macro.jpg",
  "lime-splash.jpg",
  "mountain-lake.png",
  "feather-teal.jpg",
];

test("prepare: library with a duplicate and search @gallery", async ({ request }) => {
  test.setTimeout(900_000);
  await install(request, "clip-vit-b32");
  const ids: Record<string, string> = {};
  for (const name of LIBRARY_SAMPLES) ids[name] = await upload(request, name);
  // A smaller, recompressed copy of the pier, made through an export, as a duplicate to find.
  const pier = ids["lake-pier.jpg"] as string;
  const started = await (
    await request.post(`/api/assets/${pier}/exports`, {
      data: { format: "jpeg", quality: 55, max_side: 640, strip_metadata: true },
    })
  ).json();
  await waitForJob(request, started.job.id);
  const copy = await (await request.get(`/api/renditions/${started.rendition.id}/download`)).body();
  await request.post(`/api/assets?filename=${encodeURIComponent("lake-pier (copy).jpg")}`, {
    data: copy,
    headers: { "Content-Type": "application/octet-stream" },
  });
  await expect
    .poll(
      async () => {
        const status = await (await request.get("/api/library/status")).json();
        return status.pending === 0 && status.counts.duplicate_groups > 0;
      },
      { timeout: 600_000, intervals: [2_000] },
    )
    .toBe(true);
});

test("library, grid with details @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto("/library");
  await expect(page.getByTestId("library-card").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /^turquoise-lake\.jpg/ }).click();
  await expect(page.getByTestId("library-inspector")).toBeVisible();
  await settle(page);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/library-dark.png` });
});

test("library, search by description @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/library?q=${encodeURIComponent("mountains reflected in a lake")}`);
  await expect(page.getByText(/Best matches for/)).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/library-search.png` });
});

test("library, duplicates in light @gallery", async ({ page }) => {
  await useTheme(page, "light");
  await page.goto("/library?view=duplicates");
  await expect(page.getByTestId("duplicate-group").first()).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/library-duplicates.png` });
});

test("library, smart album editor @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto("/library");
  await page.getByRole("button", { name: "Edit album Desktop wallpapers" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/library-album.png` });
});

test("library on a phone @gallery", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await useTheme(page, "dark");
  await page.goto("/library");
  await expect(page.getByTestId("library-card").first()).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/library-phone.png` });
  await context.close();
});

// ----------------------------------------------------------------------------------- Flows

const flows: Record<string, string> = {};

async function waitForRun(request: APIRequestContext, id: string, timeout = 600_000) {
  await expect
    .poll(async () => (await (await request.get(`/api/flows/runs/${id}`)).json()).run.state, {
      timeout,
      intervals: [2_000],
    })
    .toBe("succeeded");
}

test("prepare: flows from the recipes, and a run @gallery", async ({ request }) => {
  test.setTimeout(900_000);
  for (const [recipe, name] of [
    ["product-shots", "Product shots"],
    ["wallpapers", "Wallpaper pipeline"],
    ["web-gallery", "Web gallery"],
  ] as const) {
    const flow = await (await request.post("/api/flows", { data: { name, recipe } })).json();
    flows[recipe] = flow.id;
  }
  await request.put(`/api/flows/${flows["web-gallery"]}`, {
    data: { watch_folder: "inbox/web", watch_enabled: true },
  });
  const run = await (
    await request.post(`/api/flows/${flows["web-gallery"]}/runs`, {
      data: { source: { kind: "all" }, dry_run: false },
    })
  ).json();
  await waitForRun(request, run.id);
});

test("flows, editor with an If block @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/flows?flow=${flows.wallpapers}`);
  await page.getByTestId("block-wide").click();
  await expect(page.getByTestId("block-inspector")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/flows-editor.png` });
});

test("flows, a finished run @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/flows?flow=${flows["web-gallery"]}&tab=runs`);
  await expect(page.getByTestId("run-item").first()).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flows-runs.png` });
});

test("flows, watching a folder in light @gallery", async ({ page }) => {
  await useTheme(page, "light");
  await page.setViewportSize({ width: 1680, height: 940 });
  await page.goto(`/flows?flow=${flows["web-gallery"]}`);
  await expect(page.getByTestId("flow-settings")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/flows-light.png` });
});

test("flows, run dialog @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/flows?flow=${flows["product-shots"]}`);
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByRole("dialog", { name: /^Run / })).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/flows-run.png` });
});

test("flows on a phone @gallery", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await useTheme(page, "dark");
  await page.goto(`/flows?flow=${flows["web-gallery"]}&tab=runs`);
  await expect(page.getByTestId("run-item").first()).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/flows-phone.png` });
  await context.close();
});

// ----------------------------------------------------------------------------------- Forge

const forge: Record<string, string> = {};

async function waitFor(request: APIRequestContext, url: string, pick: (body: never) => string, want: string) {
  await expect
    .poll(async () => pick((await (await request.get(url)).json()) as never), {
      timeout: 900_000,
      intervals: [2_000],
    })
    .toBe(want);
}

test("prepare: two models, a dataset, a training run and a published model @gallery", async ({ request }) => {
  test.setTimeout(1_200_000);
  for (const [template, name] of [
    ["siqe-classic", "Detail ×3"],
    ["residual-x4", "Bicubic plus detail ×4"],
  ] as const) {
    const project = await (await request.post("/api/forge/projects", { data: { name, template } })).json();
    forge[template] = project.id;
  }
  const dataset = await (
    await request.post("/api/forge/datasets", {
      data: {
        name: "Landscapes",
        source: { kind: "all" },
        settings: { crop: 192, crops_per_image: 6, min_width: 400, min_height: 300, val_every: 4 },
      },
    })
  ).json();
  forge.dataset = dataset.id;
  await waitFor(
    request,
    "/api/forge/datasets",
    (list: { id: string; state: string }[]) => list.find((d) => d.id === dataset.id)?.state ?? "",
    "succeeded",
  );
  const run = await (
    await request.post(`/api/forge/projects/${forge["siqe-classic"]}/runs`, {
      data: {
        dataset_id: dataset.id,
        settings: { steps: 600, batch: 8, patch: 32, val_every: 60, lr: 0.0005 },
      },
    })
  ).json();
  forge.run = run.id;
  await waitFor(
    request,
    `/api/forge/runs/${run.id}`,
    (d: { run: { state: string } }) => d.run.state,
    "succeeded",
  );
  const published = await (
    await request.post(`/api/forge/runs/${run.id}/publish`, { data: { name: "Detail", summary: "" } })
  ).json();
  await waitForJob(request, published.job.id, 600_000);
});

test("forge, designing a model @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.setViewportSize({ width: 1680, height: 940 });
  await page.goto(`/forge?project=${forge["residual-x4"]}`);
  await page.getByTestId("forge-block-attend").click();
  await expect(page.getByTestId("forge-inspector")).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/forge-design.png` });
});

test("forge, a training run @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/forge?project=${forge["siqe-classic"]}&tab=train&run=${forge.run}`);
  await expect(page.getByTestId("forge-sample")).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/forge-train.png` });
});

test("forge, dataset and damage preview in light @gallery", async ({ page }) => {
  await useTheme(page, "light");
  await page.goto(`/forge?project=${forge["siqe-classic"]}&tab=data&dataset=${forge.dataset}`);
  await expect(page.getByTestId("forge-preview")).toBeVisible({ timeout: 30_000 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/forge-data.png` });
});

test("forge, generated code @gallery", async ({ page }) => {
  await useTheme(page, "dark");
  await page.goto(`/forge?project=${forge["siqe-classic"]}&tab=code`);
  await expect(page.getByTestId("forge-code")).toContainText("class ");
  await settle(page);
  await page.screenshot({ path: `${OUT}/forge-code.png` });
});

test("forge on a phone @gallery", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await useTheme(page, "dark");
  await page.goto(`/forge?project=${forge["siqe-classic"]}&tab=train&run=${forge.run}`);
  await expect(page.getByTestId("forge-run")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("forge-run").scrollIntoViewIfNeeded();
  await settle(page);
  await page.screenshot({ path: `${OUT}/forge-phone.png` });
  await context.close();
});

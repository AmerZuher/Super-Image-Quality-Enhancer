import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const SAMPLE = fileURLToPath(new URL("../../samples/rose-blue.jpg", import.meta.url));

test.describe.configure({ mode: "serial" });

test("download a model, upscale an image and compare the result", async ({ page, request }) => {
  test.setTimeout(600_000);
  await page.goto("/ai-lab");

  // Download the small fast model from the Models tab (skipped if it is already installed).
  await page.getByRole("tab", { name: /Models/ }).click();
  const card = page.getByTestId("model-realesr-general-x4v3");
  const download = card.getByRole("button", { name: /(Download|Retry downloading) Real-ESRGAN General v3/ });
  if (await download.isVisible()) await download.click();
  await expect(card.getByText("Installed")).toBeVisible({ timeout: 300_000 });

  // Upload an image; it becomes the source.
  await page.getByTestId("file-input").or(page.getByTestId("ailab-file-input")).first().setInputFiles(SAMPLE);
  await expect(page.getByText("rose-blue.jpg", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("compare")).toBeVisible({ timeout: 60_000 });

  // Plan, then run.
  await page.getByRole("tab", { name: "Run" }).click();
  await page.getByRole("button", { name: "Upscale", exact: true }).click();
  await page.getByText("Real-ESRGAN General v3").first().click();
  const plan = page.getByTestId("plan");
  await expect(plan).toContainText("2,560 × 1,696");
  await page.getByRole("button", { name: "Upscale ×4" }).click();

  // The finished result is selected for comparison automatically.
  await expect(page.getByTestId("result").first()).toBeVisible({ timeout: 300_000 });
  await expect(page.getByText(/rose-blue ×4 Real-ESRGAN General v3\.png/).first()).toBeVisible({
    timeout: 300_000,
  });
  await expect(page.getByText("After", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Side by side" })).toBeEnabled();
  await page.getByRole("button", { name: "Side by side" }).click();
  await expect(page.getByTestId("compare-after")).toBeVisible();

  // Let this run finish so it doesn't hold the AI worker for later tests.
  await expect
    .poll(
      async () => {
        const jobs: { kind: string; state: string }[] = await (
          await request.get("/api/jobs?limit=50")
        ).json();
        return jobs.filter((j) => j.kind === "ai.run" && (j.state === "queued" || j.state === "running"))
          .length;
      },
      { timeout: 600_000, intervals: [2_000] },
    )
    .toBe(0);

  // Results open in Studio as ordinary images.
  await page
    .getByTestId("result")
    .filter({ hasText: /rose-blue ×4/ })
    .first()
    .getByRole("link", { name: "Edit in Studio" })
    .click();
  await expect(page).toHaveURL(/\/studio\?asset=/);
  await expect(page.getByRole("heading", { name: /rose-blue ×4/ })).toBeVisible();
});

test("paint over part of an image and erase it", async ({ page }) => {
  test.setTimeout(600_000);
  await page.goto("/ai-lab");

  await page.getByRole("tab", { name: /Models/ }).click();
  const card = page.getByTestId("model-lama-erase");
  const download = card.getByRole("button", { name: /(Download|Retry downloading) LaMa object eraser/ });
  if (await download.isVisible()) await download.click();
  await expect(card.getByText("Installed")).toBeVisible({ timeout: 300_000 });

  await page.getByTestId("file-input").or(page.getByTestId("ailab-file-input")).first().setInputFiles(SAMPLE);
  await expect(page.getByText("rose-blue.jpg", { exact: true }).first()).toBeVisible({ timeout: 60_000 });

  // Picking Erase shows the paint layer; nothing can run until something is painted.
  await page.getByRole("tab", { name: "Run" }).click();
  await page.getByRole("button", { name: "Erase objects", exact: true }).click();
  const run = page.getByRole("button", { name: "Erase painted areas" });
  await expect(run).toBeDisabled();
  await expect(page.getByTestId("plan")).toContainText("640 × 424"); // same size as the original
  const box = await page.getByLabel("Paint over what to erase").boundingBox();
  if (!box) throw new Error("paint layer not visible");
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.4);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.45, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();

  await run.click();
  await expect(page.getByText(/rose-blue retouched.*\.png/).first()).toBeVisible({ timeout: 300_000 });
});

// A 202-byte ONNX graph with no weights, the simplest model a user could bring: one Resize op,
// nearest-neighbour ×2 (opset 17, input "input" N×3×h×w). Inline because *.onnx is git-ignored.
const ONNX = {
  name: "nearest-x2.onnx",
  mimeType: "application/octet-stream",
  buffer: Buffer.from(
    "CAkSEVNJUUUgU3R1ZGlvIHRlc3RzOqwBCjUKBWlucHV0CgAKBnNjYWxlcxIGb3V0cHV0IgZSZXNpemUqEgoEbW9kZSIHbmVhcmVzdKABAxIKbmVhcmVzdF94MioeCAQQASIQAACAPwAAgD8AAABAAAAAQEIGc2NhbGVzWiIKBWlucHV0EhkKFwgBEhMKAxIBbgoCCAMKAxIBaAoDEgF3YiMKBm91dHB1dBIZChcIARITCgMSAW4KAggDCgMSAUgKAxIBV0IECgAQEQ==",
    "base64",
  ),
};

test("add your own ONNX model and use it", async ({ page, request }) => {
  test.setTimeout(300_000);
  const name = `Nearest x2 ${Date.now() % 100000}`;
  // Leftovers from an earlier run that stopped half-way.
  const before: { id: string; name: string; source: string }[] = await (
    await request.get("/api/models")
  ).json();
  for (const m of before.filter((m) => m.source === "user" && m.name.startsWith("Nearest x2 "))) {
    await request.delete(`/api/models/${m.id}`);
  }
  await page.goto("/ai-lab");
  await page.getByRole("tab", { name: /Models/ }).click();
  const card = page.getByTestId("add-model");
  await card.getByTestId("onnx-file-input").setInputFiles(ONNX);
  await card.getByLabel("Name").fill(name);
  await card.getByRole("button", { name: "Add ONNX model" }).click();
  await expect(card.getByRole("status")).toContainText(`Added ${name} (×2 upscaler)`, { timeout: 120_000 });

  // It joins the library as your own model, and can be picked for upscaling (always on the CPU).
  const added = page.locator("[data-testid^='model-user-']").filter({ hasText: name });
  await expect(added.getByText("Added by you", { exact: true })).toBeVisible();
  await expect(added.getByText(/CPU · [\d.]+ s per megapixel/)).toBeVisible();
  await page.getByTestId("file-input").or(page.getByTestId("ailab-file-input")).first().setInputFiles(SAMPLE);
  await page.getByRole("tab", { name: "Run" }).click();
  await page.getByRole("button", { name: "Upscale", exact: true }).click();
  await page.getByText(name).first().click();
  await expect(page.getByTestId("plan")).toContainText("1,280 × 848");
  await expect(page.getByLabel("Run on")).toHaveCount(0);

  // Removing it deletes the file; it leaves the list.
  const models: { id: string; name: string }[] = await (await request.get("/api/models")).json();
  const id = models.find((m) => m.name === name)?.id;
  expect(id).toBeTruthy();
  await page.getByRole("tab", { name: /Models/ }).click();
  await added.getByRole("button", { name: `Remove ${name}` }).click();
  await added.getByRole("button", { name: `Confirm removing ${name}` }).click();
  await expect(page.getByTestId(`model-${id}`)).toHaveCount(0);
});

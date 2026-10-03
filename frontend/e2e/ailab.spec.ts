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

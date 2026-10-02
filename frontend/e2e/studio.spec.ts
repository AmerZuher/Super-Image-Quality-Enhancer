import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const SAMPLE = fileURLToPath(new URL("../../samples/turquoise-lake.jpg", import.meta.url));

test.describe.configure({ mode: "serial" });

test("upload, edit, crop and export an image in Studio", async ({ page }) => {
  await page.goto("/studio");
  const input = page.getByTestId("file-input").or(page.getByTestId("empty-file-input"));
  await input.first().setInputFiles(SAMPLE);

  // The new image opens once its preview is ready.
  await expect(page.getByRole("heading", { name: "turquoise-lake.jpg" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("img", { name: "Preview of turquoise-lake.jpg" })).toBeVisible({
    timeout: 60_000,
  });
  // A copy left by an interrupted run may still carry edits: start from the original.
  const reset = page.getByRole("button", { name: "Reset all" });
  if (await reset.isEnabled()) await reset.click();

  // Adjust: the edit lands in the stack and autosaves.
  await page.getByLabel("Exposure", { exact: true }).fill("0.5");
  await page.getByRole("switch", { name: "Black & white" }).check({ force: true });
  const stack = page.getByTestId("edit-stack");
  await expect(stack.getByText("Exposure")).toBeVisible();
  await expect(stack.getByText("Black & white")).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible({ timeout: 10_000 });

  // Undo removes the last step, redo restores it.
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(stack.getByText("Black & white")).toBeHidden();
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(stack.getByText("Black & white")).toBeVisible();

  // Crop: rotate and pick a square.
  await page.getByRole("tab", { name: "Crop" }).click();
  await page.getByRole("button", { name: "Right" }).click();
  await page.getByRole("button", { name: "1:1" }).click();
  await expect(stack.getByText("Rotate")).toBeVisible();
  await expect(stack.getByText("Crop")).toBeVisible();

  // Export a square JPEG at 512 px and download it.
  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByRole("button", { name: "Full size" }).click();
  await page.getByLabel("Custom longest side in pixels").fill("512");
  await expect(page.getByTestId("export-size")).toHaveText("512 × 512");
  await page.getByRole("button", { name: /^Export JPEG/ }).click();
  const row = page.getByTestId("rendition").first();
  const download = row.getByRole("link", { name: "Download" });
  await expect(download).toBeVisible({ timeout: 90_000 });
  await expect(row).toContainText("512 × 512");
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  expect(file.suggestedFilename()).toBe("turquoise-lake-edited.jpg");

  // Compare modes switch without errors.
  for (const mode of ["Split", "Side by side", "Difference", "Edited"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
  }
  await expect(page.getByLabel("Before and after divider")).toHaveCount(0);

  // Clean up so the test can run again.
  await page.getByRole("button", { name: "Delete turquoise-lake.jpg" }).click();
  await page.getByRole("button", { name: "Confirm deleting turquoise-lake.jpg" }).click();
  await expect(page.getByRole("heading", { name: "turquoise-lake.jpg" })).toBeHidden();
});

test("unsupported files are skipped with a message", async ({ page }) => {
  await page.goto("/studio");
  const input = page.getByTestId("file-input").or(page.getByTestId("empty-file-input"));
  await input
    .first()
    .setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.getByRole("alert")).toContainText("notes.txt: not a supported image type");
});

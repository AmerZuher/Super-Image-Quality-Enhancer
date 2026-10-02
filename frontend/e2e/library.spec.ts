import { expect, test } from "@playwright/test";
import { uniquePng } from "./images";

test.describe.configure({ mode: "serial" });

const NAME = `e2e library ${Date.now()}.png`;
const TAG = `e2e-${Date.now().toString(36)}`;

test("upload, tag, filter into a smart album, quarantine and restore", async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.goto("/library");
  await expect(page.getByTestId("library")).toBeVisible();

  // Add an image; it appears in All images once prepared.
  await page
    .getByTestId("library-file-input")
    .setInputFiles({ name: NAME, mimeType: "image/png", buffer: uniquePng() });
  const card = page.getByTestId("library-card").filter({ hasText: NAME });
  await expect(card.getByRole("button", { name: new RegExp(NAME) })).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("Preparing")).toHaveCount(0, { timeout: 60_000 });

  // Select it: the inspector shows its details; add a tag.
  await card.getByRole("button", { name: new RegExp(NAME) }).click();
  const inspector = page.getByTestId("library-inspector");
  await expect(inspector.getByRole("heading", { name: NAME })).toBeVisible();
  await inspector.getByLabel("Add a tag").fill(TAG);
  await inspector.getByRole("button", { name: "Add tag" }).click();
  await expect(inspector.getByRole("button", { name: `Remove tag ${TAG}` })).toBeVisible();

  // Filter by the tag chip, save the filter as a smart album, and open it.
  await page.getByRole("searchbox").fill(TAG);
  await expect(page).toHaveURL(new RegExp(`q=${TAG}`));
  // A tag match ranks above anything CLIP finds for the same words.
  await expect(page.getByTestId("library-card").first()).toContainText(NAME, { timeout: 30_000 });
  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(page).not.toHaveURL(/q=/);
  await page.getByRole("button", { name: "Square", exact: true }).click();
  await expect(page.getByRole("button", { name: "Square", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Save as smart album" }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByLabel("Name").fill(`Squares ${TAG}`);
  await drawer.getByRole("button", { name: "Add rule" }).click();
  await drawer.getByLabel("Field").last().selectOption("tag");
  await drawer.getByLabel("Value").last().fill(TAG);
  await drawer.getByRole("button", { name: "Create album" }).click();
  await expect(drawer).toBeHidden();
  await page.getByRole("button", { name: "Square", exact: true }).click(); // clear the filter
  const albumLink = page
    .getByRole("navigation", { name: "Library views" })
    .first()
    .getByRole("button", {
      name: new RegExp(`^Squares ${TAG}`),
    });
  await expect(albumLink).toContainText("1");
  await albumLink.click();
  await expect(page.getByTestId("library-card")).toHaveCount(1);

  // Delete the album (the image stays).
  await page.getByRole("button", { name: `Edit album Squares ${TAG}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete album" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete album?" }).click();
  await expect(albumLink).toHaveCount(0);

  // Quarantine hides it; restoring brings it back.
  await page.getByRole("button", { name: /^All images/ }).click();
  await card.getByRole("button", { name: new RegExp(NAME) }).click();
  await inspector.getByRole("button", { name: "Move to quarantine" }).click();
  await expect(card).toHaveCount(0);
  await page
    .getByRole("button", { name: /^Quarantine/ })
    .first()
    .click();
  await card.getByRole("button", { name: new RegExp(NAME) }).click();
  await expect(inspector.getByText(/In quarantine/)).toBeVisible();
  await inspector.getByRole("button", { name: "Restore" }).click();
  await expect(card).toHaveCount(0);
  await page.getByRole("button", { name: /^All images/ }).click();
  await expect(card).toHaveCount(1);

  // Clean up through the API.
  const page_ = await (await request.get(`/api/library/assets?q=${encodeURIComponent(NAME)}`)).json();
  const ids = page_.items.map((a: { id: string }) => a.id);
  await request.post("/api/library/quarantine", { data: { asset_ids: ids } });
  await request.post("/api/library/delete", { data: { asset_ids: ids } });
});

test("works at phone width", async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone.goto("/library");
  await expect(phone.getByTestId("library")).toBeVisible();
  await expect(phone.getByRole("button", { name: /^Filters/ })).toBeVisible();
  await phone.getByRole("button", { name: /^Filters/ }).click();
  await expect(phone.getByRole("button", { name: "Landscape", exact: true })).toBeVisible();
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await phone.close();
});

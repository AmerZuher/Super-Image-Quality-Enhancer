import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const CRC = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(data: Buffer): number {
  let c = 0xffffffff;
  for (const byte of data) c = (CRC[(c ^ byte) & 0xff] ?? 0) ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, crc]);
}

/** A square PNG with random rings, new on every run so it is never a duplicate. */
function uniquePng(size = 320): Buffer {
  const seed = Math.random() * 1000;
  const rows: Buffer[] = [];
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 3);
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x - size / 2, y - size / 2);
      row[1 + x * 3] = 128 + 127 * Math.sin(d / 7 + seed);
      row[2 + x * 3] = 128 + 127 * Math.sin(x / 11 + seed * 2);
      row[3 + x * 3] = 128 + 127 * Math.cos(y / 13 + seed * 3);
    }
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

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

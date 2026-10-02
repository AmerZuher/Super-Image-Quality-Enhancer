import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (`make up`). Point SIQE_BASE_URL elsewhere if needed.
// PW_CHROMIUM_PATH lets CI or sandboxes reuse a preinstalled Chromium. On machines without a
// GPU, SwiftShader stands in so the WebGL preview and the shader parity test still run.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  // One file at a time: the stack runs one AI job at a time, so parallel files would queue
  // behind each other's runs and time out.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: process.env.SIQE_BASE_URL ?? "http://localhost:8080",
    viewport: { width: 1600, height: 1000 },
    trace: "retain-on-failure",
    launchOptions: { executablePath, args: ["--enable-unsafe-swiftshader"] },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } } },
  ],
});

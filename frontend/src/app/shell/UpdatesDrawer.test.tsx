import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Release, UpdateStatus } from "@/lib/api/client";
import { UpdatesContent } from "./UpdatesDrawer";

const release = (version: string, notes: string): Release => ({
  tag: `v${version}`,
  version,
  name: `Release ${version}`,
  notes,
  url: `https://github.com/AmerZuher/Super-Image-Quality-Enhancer/releases/tag/v${version}`,
  published_at: "2026-10-01T10:00:00Z",
  prerelease: false,
});

const base: UpdateStatus = {
  current_version: "0.1.0",
  latest_version: null,
  update_available: false,
  newer: [],
  current: null,
  checked_at: "2026-10-01T10:00:00Z",
  error: null,
  repo_url: "https://github.com/AmerZuher/Super-Image-Quality-Enhancer",
  releases_url: "https://github.com/AmerZuher/Super-Image-Quality-Enhancer/releases",
};

describe("UpdatesContent", () => {
  it("lists newer releases with their notes and the update commands", async () => {
    render(
      <UpdatesContent
        status={{
          ...base,
          latest_version: "0.2.0",
          update_available: true,
          newer: [
            release("0.2.0", "## New\n- **AI Lab** with upscaling"),
            release("0.1.1", "- Fixed a crash"),
          ],
        }}
      />,
    );
    expect(screen.getByText("Version 0.2.0 is available")).toBeInTheDocument();
    expect(screen.getByText("docker compose pull && docker compose up -d")).toBeInTheDocument();
    // The Markdown renderer loads lazily: wait for the formatted notes.
    expect(await screen.findByText("AI Lab")).toBeInTheDocument();
    expect(await screen.findByText("Fixed a crash")).toBeInTheDocument();
    expect(screen.getAllByText("View on GitHub")).toHaveLength(2);
  });

  it("says when you are up to date and shows the installed version's notes", async () => {
    render(
      <UpdatesContent
        status={{ ...base, latest_version: "0.1.0", current: release("0.1.0", "First release") }}
      />,
    );
    expect(screen.getByText("You're up to date")).toBeInTheDocument();
    expect(await screen.findByText("First release")).toBeInTheDocument();
    expect(screen.getByText("Installed")).toBeInTheDocument();
  });

  it("does not render raw HTML from release notes", () => {
    render(
      <UpdatesContent
        status={{
          ...base,
          latest_version: "0.2.0",
          update_available: true,
          newer: [release("0.2.0", "<script>alert(1)</script>Safe text")],
        }}
      />,
    );
    expect(document.querySelector("script")).toBeNull();
  });

  it("shows the check error without hiding the cached result", () => {
    render(
      <UpdatesContent
        status={{ ...base, error: "Couldn't reach GitHub (ConnectError). Showing the last known releases." }}
      />,
    );
    expect(screen.getByText(/Couldn't reach GitHub/)).toBeInTheDocument();
    expect(screen.getByText("You're up to date")).toBeInTheDocument();
  });
});

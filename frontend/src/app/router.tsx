import { createRootRoute, createRoute, createRouter, Link, lazyRouteComponent } from "@tanstack/react-router";
import { JobsPage } from "@/features/jobs/JobsPage";
import type { LibrarySearch } from "@/features/library/LibraryPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { WorkspacePreview } from "@/features/workspaces/WorkspacePreview";
import { AppShell } from "./shell/AppShell";

function NotFound() {
  return (
    <div className="mx-auto grid max-w-[560px] gap-3 p-10 text-center">
      <h2 className="font-display text-[22px] font-medium">This page doesn't exist</h2>
      <p className="text-[13px] text-fg-2">The link may be from a newer version of SIQE Studio.</p>
      <Link to="/" className="text-cyan hover:underline">
        Go to the Overview
      </Link>
    </div>
  );
}

const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: "/", component: OverviewPage }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/studio",
    validateSearch: (search: Record<string, unknown>): { asset?: string } =>
      typeof search.asset === "string" ? { asset: search.asset } : {},
    component: lazyRouteComponent(() => import("@/features/studio/StudioPage"), "StudioPage"),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/ai-lab",
    validateSearch: (search: Record<string, unknown>): { asset?: string; result?: string } => ({
      ...(typeof search.asset === "string" ? { asset: search.asset } : {}),
      ...(typeof search.result === "string" ? { result: search.result } : {}),
    }),
    component: lazyRouteComponent(() => import("@/features/ailab/AiLabPage"), "AiLabPage"),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/library",
    validateSearch: (search: Record<string, unknown>): LibrarySearch => {
      const out: LibrarySearch = {};
      if (search.view === "duplicates" || search.view === "quarantine" || search.view === "album") {
        out.view = search.view;
      }
      for (const key of ["album", "q", "similar"] as const) {
        if (typeof search[key] === "string" && search[key]) out[key] = search[key] as string;
      }
      return out;
    },
    component: lazyRouteComponent(() => import("@/features/library/LibraryPage"), "LibraryPage"),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/flows",
    component: () => <WorkspacePreview id="flows" />,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/forge",
    component: () => <WorkspacePreview id="forge" />,
  }),
  createRoute({ getParentRoute: () => rootRoute, path: "/jobs", component: JobsPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsPage }),
]);

export const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

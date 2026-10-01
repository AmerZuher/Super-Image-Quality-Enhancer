import { createRootRoute, createRoute, createRouter, Link } from "@tanstack/react-router";
import { JobsPage } from "@/features/jobs/JobsPage";
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
    component: () => <WorkspacePreview id="studio" />,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/ai-lab",
    component: () => <WorkspacePreview id="ai-lab" />,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/library",
    component: () => <WorkspacePreview id="library" />,
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

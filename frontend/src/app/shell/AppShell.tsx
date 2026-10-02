import { Outlet } from "@tanstack/react-router";
import { useAuthStatus } from "@/features/access/api";
import { SignIn } from "@/features/access/SignIn";
import { CommandPalette } from "./CommandPalette";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";
import { UpdatesDrawer } from "./UpdatesDrawer";

export function AppShell() {
  const { data: auth } = useAuthStatus();
  if (auth?.mode === "keys" && !auth.signed_in) return <SignIn />;
  return (
    <div className="flex h-full min-h-0">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main" className="dot-grid min-h-0 flex-1 overflow-y-auto max-md:pb-16">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
      <UpdatesDrawer />
    </div>
  );
}

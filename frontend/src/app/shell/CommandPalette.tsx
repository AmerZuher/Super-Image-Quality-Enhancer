import { useNavigate } from "@tanstack/react-router";
import { Command } from "cmdk";
import { ArrowUpCircle, BookOpen, ListChecks, Monitor, Moon, Play, Settings, Sun } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { useStartSelfTest } from "@/lib/api/queries";
import { useUi } from "@/lib/ui-store";
import { isAvailable, OVERVIEW, WORKSPACES } from "../workspaces";

function Item({
  onSelect,
  icon,
  children,
  hint,
}: {
  onSelect: () => void;
  icon: ReactNode;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-fg-2 data-[selected=true]:bg-panel-2 data-[selected=true]:text-fg [&_svg]:size-4 [&_svg]:text-muted"
    >
      {icon}
      <span className="flex-1">{children}</span>
      {hint && <span className="text-[11px] text-muted">{hint}</span>}
    </Command.Item>
  );
}

const groupClass =
  "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted [&_[cmdk-group-heading]]:uppercase";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const setTheme = useUi((s) => s.setTheme);
  const setUpdatesOpen = useUi((s) => s.setUpdatesOpen);
  const navigate = useNavigate();
  const selfTest = useStartSelfTest();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useUi.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const run = (action: () => void) => {
    setOpen(false);
    action();
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      overlayClassName="fixed inset-0 z-50 bg-[var(--overlay)]"
      contentClassName="fixed top-[14vh] left-1/2 z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-xl border border-line-2 bg-panel shadow-float"
    >
      <Command.Input
        placeholder="Go to a page or run an action…"
        className="w-full border-b border-line bg-transparent px-4 py-3.5 text-[14px] text-fg outline-none placeholder:text-muted"
      />
      <Command.List className="max-h-[360px] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted">
          Nothing matches that.
        </Command.Empty>
        <Command.Group heading="Go to" className={groupClass}>
          <Item icon={<OVERVIEW.icon />} onSelect={() => run(() => navigate({ to: "/" }))}>
            {OVERVIEW.label}
          </Item>
          {WORKSPACES.map((w) => (
            <Item
              key={w.id}
              icon={<w.icon />}
              onSelect={() => run(() => navigate({ to: w.path }))}
              hint={isAvailable(w) ? undefined : `Phase ${w.phase}`}
            >
              {w.label}
            </Item>
          ))}
          <Item icon={<ListChecks />} onSelect={() => run(() => navigate({ to: "/jobs" }))}>
            Jobs
          </Item>
          <Item icon={<Settings />} onSelect={() => run(() => navigate({ to: "/settings" }))}>
            Settings
          </Item>
        </Command.Group>
        <Command.Group heading="Actions" className={groupClass}>
          <Item icon={<Play />} onSelect={() => run(() => selfTest.mutate())}>
            Run system self-test
          </Item>
          <Item icon={<ArrowUpCircle />} onSelect={() => run(() => setUpdatesOpen(true))}>
            Check for updates and release notes
          </Item>
          <Item
            icon={<BookOpen />}
            onSelect={() => run(() => window.open("/api/docs", "_blank", "noopener"))}
          >
            Open API reference
          </Item>
        </Command.Group>
        <Command.Group heading="Theme" className={groupClass}>
          <Item icon={<Monitor />} onSelect={() => run(() => setTheme("system"))}>
            Match system
          </Item>
          <Item icon={<Moon />} onSelect={() => run(() => setTheme("dark"))}>
            Dark
          </Item>
          <Item icon={<Sun />} onSelect={() => run(() => setTheme("light"))}>
            Light
          </Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}

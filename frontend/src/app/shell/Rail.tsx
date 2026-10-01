import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import { ListChecks, Settings } from "lucide-react";
import type { ComponentType } from "react";
import { Logo } from "@/components/ui/Logo";
import { OVERVIEW, WORKSPACES } from "../workspaces";

function RailLink({
  to,
  label,
  icon: Icon,
  ai = false,
}: {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  ai?: boolean;
}) {
  return (
    <Link
      to={to}
      title={label}
      aria-label={label}
      activeOptions={{ exact: to === "/" }}
      className="group relative grid size-10 place-items-center rounded-[10px] text-muted transition hover:bg-panel-2 hover:text-fg"
      activeProps={{ className: "!text-fg bg-panel-2", "aria-current": "page" }}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className={clsx(
                "absolute top-2.5 bottom-2.5 -left-[11px] w-0.5 rounded-full max-md:hidden",
                ai ? "bg-gold" : "bg-cyan",
              )}
            />
          )}
          <Icon className={clsx("size-[19px]", isActive && ai && "text-gold")} />
        </>
      )}
    </Link>
  );
}

export function Rail() {
  return (
    <nav
      aria-label="Workspaces"
      className={clsx(
        "flex border-line bg-panel",
        "md:h-full md:w-[60px] md:flex-col md:items-center md:gap-1.5 md:border-r md:py-3",
        "max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:z-40 max-md:justify-around max-md:border-t max-md:px-2 max-md:py-1.5 max-md:pb-[max(6px,env(safe-area-inset-bottom))]",
      )}
    >
      <Link to="/" className="mb-3 max-md:hidden" aria-label="SIQE Studio home">
        <Logo className="size-8" />
      </Link>
      <RailLink to={OVERVIEW.path} label={OVERVIEW.label} icon={OVERVIEW.icon} />
      {WORKSPACES.map((w) => (
        <RailLink key={w.id} to={w.path} label={w.label} icon={w.icon} ai={w.ai} />
      ))}
      <span className="flex-1 max-md:hidden" />
      <div className="max-md:hidden">
        <RailLink to="/jobs" label="Jobs" icon={ListChecks} />
      </div>
      <RailLink to="/settings" label="Settings" icon={Settings} />
    </nav>
  );
}

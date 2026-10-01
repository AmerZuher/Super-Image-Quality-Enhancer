import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import { Check } from "lucide-react";
import { Chip } from "@/components/ui/Chip";
import { WORKSPACES, type WorkspaceId } from "../../app/workspaces";

/** Placeholder for workspaces that arrive in later phases: what it will do, and when. */
export function WorkspacePreview({ id }: { id: WorkspaceId }) {
  const workspace = WORKSPACES.find((w) => w.id === id);
  if (!workspace) return null;
  const { icon: Icon, ai } = workspace;
  return (
    <div className="mx-auto grid max-w-[880px] gap-6 p-4 md:p-10">
      <div className="flex items-center gap-4">
        <span
          className={clsx(
            "grid size-14 place-items-center rounded-2xl border",
            ai ? "border-gold/40 bg-gold-soft text-gold" : "border-cyan/40 bg-cyan-soft text-cyan",
          )}
        >
          <Icon className="size-7" />
        </span>
        <div>
          <h2 className="font-display text-[26px] font-medium text-fg">{workspace.label}</h2>
          <p className="text-[14px] text-fg-2">{workspace.summary}</p>
        </div>
      </div>

      <div className="rounded-xl border border-line bg-panel p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Chip tone={ai ? "gold" : "cyan"}>Arrives in Phase {workspace.phase}</Chip>
          {ai && <Chip tone="gold">Uses AI models</Chip>}
        </div>
        <h3 className="mb-2 text-[14px] font-semibold text-fg">What you'll be able to do here</h3>
        <ul className="grid gap-2">
          {workspace.capabilities.map((capability) => (
            <li key={capability} className="flex gap-2.5 text-[13.5px] text-fg-2">
              <Check
                className={clsx("mt-0.5 size-4 shrink-0", ai ? "text-gold" : "text-cyan")}
                aria-hidden="true"
              />
              {capability}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[13px] text-muted">
        Until then, the{" "}
        <Link to="/" className="text-cyan hover:underline">
          Overview
        </Link>{" "}
        shows your hardware and lets you run the system self-test. Updates arrive through the version button
        in the top bar, with release notes.
      </p>
    </div>
  );
}

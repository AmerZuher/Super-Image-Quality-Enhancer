import { clsx } from "clsx";
import { ArrowUpCircle, ExternalLink, Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Kbd } from "@/components/ui/Kbd";
import { Panel } from "@/components/ui/Panel";
import { AccessPanel } from "@/features/access/AccessPanel";
import { useUpdates } from "@/lib/api/queries";
import { relativeTime } from "@/lib/format";
import { type Theme, useUi } from "@/lib/ui-store";

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "Match system", icon: Monitor },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "light", label: "Light", icon: Sun },
];

export function SettingsPage() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const openUpdates = useUi((s) => s.setUpdatesOpen);
  const { data: updates } = useUpdates();

  return (
    <div className="mx-auto grid max-w-[860px] gap-4 p-4 md:p-6">
      <h2 className="font-display text-[22px] font-medium">Settings</h2>

      <Panel title="Appearance">
        <fieldset className="flex flex-wrap gap-2">
          <legend className="sr-only">Theme</legend>
          {THEMES.map(({ value, label, icon: Icon }) => (
            <label
              key={value}
              className={clsx(
                "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[13px] transition",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-cyan",
                theme === value
                  ? "border-cyan bg-cyan-soft text-fg"
                  : "border-line-2 text-fg-2 hover:border-cyan",
              )}
            >
              <input
                type="radio"
                name="theme"
                value={value}
                checked={theme === value}
                onChange={() => setTheme(value)}
                className="sr-only"
              />
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </label>
          ))}
        </fieldset>
      </Panel>

      <Panel
        title="Updates"
        actions={
          <Button size="sm" icon={<ArrowUpCircle />} onClick={() => openUpdates(true)}>
            Release notes
          </Button>
        }
      >
        <dl className="grid grid-cols-[160px_1fr] gap-y-2 text-[13px]">
          <dt className="text-muted">Installed version</dt>
          <dd className="font-mono text-fg">v{updates?.current_version ?? "…"}</dd>
          <dt className="text-muted">Latest release</dt>
          <dd className="font-mono text-fg">
            {updates?.latest_version ? `v${updates.latest_version}` : "None published yet"}
          </dd>
          <dt className="text-muted">Last checked</dt>
          <dd className="text-fg-2">{relativeTime(updates?.checked_at)}</dd>
          <dt className="text-muted">Source</dt>
          <dd>
            <a
              href={updates?.releases_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-cyan hover:underline"
            >
              GitHub releases <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          </dd>
        </dl>
        <p className="mt-3 text-[12px] text-muted">
          SIQE Studio checks GitHub every 6 hours. Change the repository or include pre-releases with
          SIQE_UPDATE_REPO and SIQE_UPDATE_INCLUDE_PRERELEASES in your .env file.
        </p>
      </Panel>

      <AccessPanel />

      <Panel title="Keyboard">
        <ul className="grid gap-2 text-[13px] text-fg-2">
          <li className="flex items-center justify-between">
            Open the command palette <Kbd>Ctrl K</Kbd>
          </li>
          <li className="flex items-center justify-between">
            Close a panel or dialog <Kbd>Esc</Kbd>
          </li>
        </ul>
      </Panel>

      <Panel title="About">
        <div className="grid gap-2 text-[13px] text-fg-2">
          <p>
            SIQE Studio is the successor to the Super Image Quality Enhancer research project by Amer Zuher
            ALriahy and Hisham Maher Sunjaq. MIT licensed.
          </p>
          <div className="flex flex-wrap gap-4">
            <a
              href="/api/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-cyan hover:underline"
            >
              API reference <ExternalLink className="size-3" aria-hidden="true" />
            </a>
            {updates?.repo_url && (
              <a
                href={updates.repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-cyan hover:underline"
              >
                Source code <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}

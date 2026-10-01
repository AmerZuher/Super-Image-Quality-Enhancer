import { CheckCircle2, ExternalLink, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { CopyCommand } from "@/components/ui/CopyCommand";
import { Drawer } from "@/components/ui/Drawer";
import { Markdown } from "@/components/ui/Markdown";
import type { Release, UpdateStatus } from "@/lib/api/client";
import { useRefreshUpdates, useUpdates } from "@/lib/api/queries";
import { formatDate, relativeTime } from "@/lib/format";
import { useUi } from "@/lib/ui-store";

function ReleaseCard({ release, current = false }: { release: Release; current?: boolean }) {
  return (
    <article className="rounded-xl border border-line bg-panel-2/60 p-4">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[13px] font-medium text-fg">v{release.version}</span>
        {release.name && release.name !== release.tag && (
          <span className="text-[13px] font-semibold text-fg">{release.name}</span>
        )}
        {release.prerelease && <Chip tone="warn">Pre-release</Chip>}
        {current && <Chip tone="cyan">Installed</Chip>}
        <span className="ml-auto text-[11.5px] text-muted">{formatDate(release.published_at)}</span>
      </header>
      {release.notes.trim() ? (
        <Markdown>{release.notes}</Markdown>
      ) : (
        <p className="text-[13px] text-muted">No release notes were written for this version.</p>
      )}
      {release.url && (
        <a
          href={release.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-1 text-[12px] text-cyan hover:underline"
        >
          View on GitHub <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      )}
    </article>
  );
}

function HowToUpdate() {
  return (
    <section className="grid gap-2.5 rounded-xl border border-cyan/35 bg-cyan-soft p-4">
      <h3 className="text-[13px] font-semibold text-fg">How to update</h3>
      <p className="text-[12.5px] text-fg-2">
        Run one of these in the folder where you installed SIQE Studio. Your images, models and settings live
        in Docker volumes and are kept. Database changes are applied automatically when the new version
        starts.
      </p>
      <div className="grid gap-1.5">
        <span className="text-[11.5px] text-muted">Pre-built images (default install)</span>
        <CopyCommand label="image update command" command="docker compose pull && docker compose up -d" />
      </div>
      <div className="grid gap-1.5">
        <span className="text-[11.5px] text-muted">Built from source</span>
        <CopyCommand label="source update command" command="git pull && docker compose up -d --build" />
      </div>
    </section>
  );
}

export function UpdatesContent({ status }: { status: UpdateStatus }) {
  return (
    <div className="grid gap-4">
      {status.error && (
        <div className="flex gap-2.5 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2.5 text-[12.5px] text-fg-2">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
          <span>{status.error}</span>
        </div>
      )}

      {status.update_available ? (
        <>
          <div className="grid gap-1">
            <p className="text-[15px] font-semibold text-fg">Version {status.latest_version} is available</p>
            <p className="text-[13px] text-fg-2">
              You're on v{status.current_version}. {status.newer.length} newer{" "}
              {status.newer.length === 1 ? "release" : "releases"} below, newest first.
            </p>
          </div>
          <HowToUpdate />
          <h3 className="eyebrow mt-1">What's new</h3>
          {status.newer.map((release) => (
            <ReleaseCard key={release.tag} release={release} />
          ))}
        </>
      ) : (
        <>
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="size-5 text-ok" aria-hidden="true" />
            <p className="text-[15px] font-semibold text-fg">You're up to date</p>
          </div>
          <p className="text-[13px] text-fg-2">
            SIQE Studio v{status.current_version} is the newest{" "}
            {status.latest_version ? "release" : "version"}.
            {!status.latest_version && " No releases have been published on GitHub yet."}
          </p>
          {status.current ? (
            <>
              <h3 className="eyebrow mt-1">Release notes for this version</h3>
              <ReleaseCard release={status.current} current />
            </>
          ) : (
            <p className="text-[13px] text-muted">There are no published notes for this exact version.</p>
          )}
        </>
      )}
    </div>
  );
}

export function UpdatesDrawer() {
  const open = useUi((s) => s.updatesOpen);
  const setOpen = useUi((s) => s.setUpdatesOpen);
  const { data, isLoading } = useUpdates();
  const refresh = useRefreshUpdates();

  return (
    <Drawer
      open={open}
      onClose={() => setOpen(false)}
      title="Updates and release notes"
      footer={
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11.5px] text-muted">
            {data?.checked_at ? `Checked ${relativeTime(data.checked_at)}` : "Not checked yet"}
          </span>
          <div className="flex items-center gap-2">
            {data?.releases_url && (
              <a
                href={data.releases_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[12px] text-fg-2 hover:text-fg"
              >
                All releases <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            )}
            <Button
              size="sm"
              icon={<RefreshCw />}
              loading={refresh.isPending}
              onClick={() => refresh.mutate()}
            >
              Check now
            </Button>
          </div>
        </div>
      }
    >
      {isLoading || !data ? (
        <p className="text-[13px] text-muted">Checking for updates…</p>
      ) : (
        <UpdatesContent status={data} />
      )}
    </Drawer>
  );
}

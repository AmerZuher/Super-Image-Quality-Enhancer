import { Square } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useCancelJob, useJobs } from "@/lib/api/queries";
import { formatDuration, relativeTime } from "@/lib/format";

export function JobsPage() {
  const { data, isLoading } = useJobs(200);
  const cancel = useCancelJob();
  const jobs = data ?? [];
  return (
    <div className="mx-auto grid max-w-[1200px] gap-4 p-4 md:p-6">
      <div>
        <h2 className="font-display text-[22px] font-medium">Jobs</h2>
        <p className="text-[13px] text-fg-2">
          Everything SIQE Studio has run, newest first. Progress updates live.
        </p>
      </div>
      <div className="overflow-x-auto rounded-xl border border-line bg-panel">
        <table className="w-full min-w-[720px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line text-left font-mono text-[10.5px] tracking-[0.1em] text-muted uppercase">
              <th className="px-4 py-2.5 font-medium">State</th>
              <th className="px-4 py-2.5 font-medium">Job</th>
              <th className="px-4 py-2.5 font-medium">Progress</th>
              <th className="px-4 py-2.5 font-medium">Started</th>
              <th className="px-4 py-2.5 font-medium">Duration</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && jobs.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  No jobs yet. Run the self-test from the Overview to see one.
                </td>
              </tr>
            )}
            {jobs.map((job) => {
              const active = job.state === "queued" || job.state === "running";
              return (
                <tr key={job.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5">
                    <JobStateChip state={job.state} />
                  </td>
                  <td className="max-w-[360px] px-4 py-2.5">
                    <div className="text-fg">{job.title}</div>
                    <div className="truncate text-[12px] text-muted">{job.message}</div>
                  </td>
                  <td className="w-[160px] px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <ProgressBar value={job.progress} label={`${job.title} progress`} className="flex-1" />
                      <span className="w-9 text-right font-mono text-[11px] text-muted tabular-nums">
                        {Math.round(job.progress * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-fg-2">{relativeTime(job.created_at)}</td>
                  <td className="px-4 py-2.5 font-mono text-[12px] whitespace-nowrap text-fg-2 tabular-nums">
                    {formatDuration(job.started_at, job.finished_at)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {active && (
                      <Button
                        size="sm"
                        variant="danger"
                        icon={<Square />}
                        onClick={() => cancel.mutate(job.id)}
                      >
                        Cancel
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

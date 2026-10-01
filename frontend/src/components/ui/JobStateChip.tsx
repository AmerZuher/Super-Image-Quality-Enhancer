import { Ban, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import type { JobState } from "@/lib/api/client";
import { Chip, type Tone } from "./Chip";
import { Spinner } from "./Spinner";

const meta: Record<JobState, { tone: Tone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "cyan", label: "Running" },
  succeeded: { tone: "ok", label: "Done" },
  failed: { tone: "err", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

export function JobStateChip({ state }: { state: JobState }) {
  const { tone, label } = meta[state];
  const icon =
    state === "running" ? (
      <Spinner className="size-3.5" />
    ) : state === "succeeded" ? (
      <CheckCircle2 />
    ) : state === "failed" ? (
      <XCircle />
    ) : state === "cancelled" ? (
      <Ban />
    ) : (
      <CircleDashed />
    );
  return (
    <Chip tone={tone} icon={icon}>
      {label}
    </Chip>
  );
}

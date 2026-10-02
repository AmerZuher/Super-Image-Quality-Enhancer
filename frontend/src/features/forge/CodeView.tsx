import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import type { ForgeProject } from "@/lib/api/client";
import { copyText } from "@/lib/clipboard";
import { useProjectCode } from "./api";

/** The PyTorch module this design compiles to, ready to copy or save. */
export function CodeView({ project }: { project: ForgeProject }) {
  const { data, isLoading } = useProjectCode(project.id, project.updated_at);
  const [copied, setCopied] = useState(false);

  const download = () => {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([data.code], { type: "text/x-python" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = data.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2">
        <span className="font-mono text-[12px] text-fg-2">{data?.filename ?? "model.py"}</span>
        <span className="flex-1 text-[11.5px] text-muted max-md:hidden">
          Plain PyTorch, no SIQE imports. Load a run's weights with safetensors.
        </span>
        <Button
          size="sm"
          icon={copied ? <Check /> : <Copy />}
          disabled={!data}
          onClick={async () => {
            if (data && (await copyText(data.code))) {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button size="sm" icon={<Download />} disabled={!data} onClick={download}>
          Download .py
        </Button>
      </div>
      {isLoading ? (
        <div className="grid flex-1 place-items-center">
          <Spinner />
        </div>
      ) : (
        <pre
          className="min-h-0 flex-1 overflow-auto bg-bg p-4 font-mono text-[12px] leading-relaxed text-fg [font-variant-ligatures:none]"
          data-testid="forge-code"
        >
          <code>{data?.code}</code>
        </pre>
      )}
    </div>
  );
}

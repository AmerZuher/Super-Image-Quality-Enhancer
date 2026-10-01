import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { copyText } from "@/lib/clipboard";

export function CopyCommand({ command, label }: { command: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-stretch overflow-hidden rounded-lg border border-line bg-bg">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-2 font-mono text-[12px] text-fg">
        {command}
      </code>
      <button
        type="button"
        onClick={async () => {
          if (await copyText(command)) {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }
        }}
        className="flex w-10 shrink-0 items-center justify-center border-l border-line text-muted hover:text-fg"
        aria-label={copied ? `${label} copied` : `Copy ${label}`}
        title={copied ? "Copied" : "Copy"}
      >
        {copied ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />}
      </button>
    </div>
  );
}

import type { ReactNode } from "react";

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-b-2 border-line-2 bg-panel-2 px-1.5 font-mono text-[10.5px] text-fg-2">
      {children}
    </kbd>
  );
}

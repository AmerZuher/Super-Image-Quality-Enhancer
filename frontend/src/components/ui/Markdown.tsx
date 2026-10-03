import { lazy, Suspense } from "react";

// The renderer (react-markdown and its parser, about 120 kB) loads only when notes are shown.
const MarkdownRenderer = lazy(() =>
  import("./MarkdownRenderer").then((m) => ({ default: m.MarkdownRenderer })),
);

/** Release notes, rendered without raw HTML. The text shows plainly while the renderer loads. */
export function Markdown({ children }: { children: string }) {
  return (
    <Suspense fallback={<p className="whitespace-pre-wrap text-[13px] text-fg-2">{children}</p>}>
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  );
}

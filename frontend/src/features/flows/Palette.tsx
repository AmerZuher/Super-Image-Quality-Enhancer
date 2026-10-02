import { clsx } from "clsx";
import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { FlowNodeType } from "@/lib/api/client";
import { DRAG_TYPE } from "./graph";

const ORDER: FlowNodeType["category"][] = ["condition", "edit", "ai", "output"];

/** The blocks you can add: click to add next to the selected block, or drag onto the canvas. */
export function Palette({ catalog, onAdd }: { catalog: FlowNodeType[]; onAdd: (type: string) => void }) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (n: FlowNodeType) =>
      !q || n.label.toLowerCase().includes(q) || n.summary.toLowerCase().includes(q);
    return ORDER.map((category) => ({
      category,
      label: catalog.find((n) => n.category === category)?.category_label ?? category,
      blocks: catalog.filter((n) => n.category === category && match(n)),
    })).filter((g) => g.blocks.length > 0);
  }, [catalog, query]);

  return (
    <nav aria-label="Blocks" className="grid content-start gap-3">
      <label className="relative">
        <Search
          className="pointer-events-none absolute top-2 left-2 size-3.5 text-muted"
          aria-hidden="true"
        />
        <input
          className="h-7 w-full rounded-md border border-line-2 bg-panel-2 pr-2 pl-7 text-[12px] text-fg outline-none focus:border-cyan"
          placeholder="Find a block"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Find a block"
        />
      </label>
      {groups.map((group) => (
        <section key={group.category} className="grid gap-1">
          <h3 className="eyebrow">{group.label}</h3>
          {group.blocks.map((block) => (
            <button
              key={block.type}
              type="button"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(DRAG_TYPE, block.type);
                e.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => onAdd(block.type)}
              title={block.summary}
              className={clsx(
                "group flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-left text-[12px] text-fg-2 transition",
                "hover:border-line-2 hover:bg-panel-2 hover:text-fg",
              )}
              aria-label={`Add ${block.label}${block.ai ? " (AI)" : ""}`}
            >
              <span
                aria-hidden="true"
                className={clsx(
                  "size-2 shrink-0",
                  block.category === "output" ? "rounded-full bg-fg-2" : "rounded-[2px]",
                  block.category !== "output" && (block.ai ? "bg-gold" : "bg-cyan"),
                )}
              />
              <span className="min-w-0 flex-1 truncate">{block.label}</span>
              {block.ai && <span className="font-mono text-[9.5px] text-gold">AI</span>}
              <Plus className="size-3.5 opacity-0 transition group-hover:opacity-100" aria-hidden="true" />
            </button>
          ))}
        </section>
      ))}
    </nav>
  );
}

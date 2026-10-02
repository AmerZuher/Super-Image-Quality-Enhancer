import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { ForgeBlockType } from "@/lib/api/client";
import { DRAG_TYPE } from "./graph";

const ORDER: ForgeBlockType["category"][] = ["layers", "blocks", "merge", "resize", "io"];

/** Layers and blocks: click to add after the selected block, or drag onto the canvas. */
export function Palette({ catalog, onAdd }: { catalog: ForgeBlockType[]; onAdd: (type: string) => void }) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (b: ForgeBlockType) =>
      b.type !== "input" && (!q || b.label.toLowerCase().includes(q) || b.summary.toLowerCase().includes(q));
    return ORDER.map((category) => ({
      category,
      label: catalog.find((b) => b.category === category)?.category_label ?? category,
      blocks: catalog.filter((b) => b.category === category && match(b)),
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
              className="group flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-left text-[12px] text-fg-2 transition hover:border-line-2 hover:bg-panel-2 hover:text-fg"
              aria-label={`Add ${block.label}`}
            >
              <span
                aria-hidden="true"
                className={
                  block.category === "io"
                    ? "size-2 shrink-0 rounded-full bg-fg-2"
                    : "size-2 shrink-0 rounded-[2px] bg-cyan"
                }
              />
              <span className="min-w-0 flex-1 truncate">{block.label}</span>
              <Plus className="size-3.5 opacity-0 transition group-hover:opacity-100" aria-hidden="true" />
            </button>
          ))}
        </section>
      ))}
    </nav>
  );
}

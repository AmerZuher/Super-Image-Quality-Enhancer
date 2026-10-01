import {
  Images,
  LayoutDashboard,
  type LucideIcon,
  SlidersHorizontal,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { ComponentType } from "react";
import { ForgeIcon } from "@/components/ui/Logo";

export type WorkspaceId = "studio" | "ai-lab" | "library" | "flows" | "forge";

export interface Workspace {
  id: WorkspaceId;
  path: `/${WorkspaceId}`;
  label: string;
  icon: LucideIcon | ComponentType<{ className?: string }>;
  phase: number;
  /** Runs AI models; drawn with the gold accent. */
  ai: boolean;
  summary: string;
  capabilities: string[];
}

export const OVERVIEW = { path: "/", label: "Overview", icon: LayoutDashboard } as const;

export const WORKSPACES: Workspace[] = [
  {
    id: "studio",
    path: "/studio",
    label: "Studio",
    icon: SlidersHorizontal,
    phase: 1,
    ai: false,
    summary: "A non-destructive editor with a live GPU preview.",
    capabilities: [
      "Edit stack you can reorder, tweak or switch off at any time",
      "Curves, levels, HSL, LUT import and colour grading",
      "Histogram, waveform and vectorscope",
      "Compare before and after with slider, split and difference views",
      "Export with format-limit checks and a target file size",
    ],
  },
  {
    id: "ai-lab",
    path: "/ai-lab",
    label: "AI Lab",
    icon: Sparkles,
    phase: 2,
    ai: true,
    summary: "Run, compare and score AI models.",
    capabilities: [
      "Upscale ×2, ×3 and ×4 with tiled inference: any image size in fixed memory",
      "SIQE Classic, your original model, ported to PyTorch",
      "Face restoration, background removal and object eraser",
      "Colorize, denoise and deblur",
      "VRAM planner and out-of-memory fallback ladder, tuned for your GPU",
    ],
  },
  {
    id: "library",
    path: "/library",
    label: "Library",
    icon: Images,
    phase: 3,
    ai: false,
    summary: "Organise thousands of photos automatically.",
    capabilities: [
      "Duplicate clusters that keep the sharpest copy, with quarantine and undo",
      "Find similar images, or search by describing the photo",
      "Smart albums from rules: orientation, size, colour, tags, faces",
      "EXIF viewer and one-click GPS privacy scrub",
      "Hot-folder import that ignores half-copied files",
    ],
  },
  {
    id: "flows",
    path: "/flows",
    label: "Flows",
    icon: Workflow,
    phase: 4,
    ai: false,
    summary: "Chain operations into pipelines you can reuse.",
    capabilities: [
      "Visual node editor for multi-step pipelines",
      "Batch runs that keep going when one image fails",
      "Branch on orientation, size or tags",
      "Run from the API, the siqe CLI or a hot folder",
      "API keys for automation",
    ],
  },
  {
    id: "forge",
    path: "/forge",
    label: "Forge",
    icon: ForgeIcon,
    phase: 5,
    ai: true,
    summary: "Design and train your own models without writing code.",
    capabilities: [
      "Drag-and-drop architecture with live shape and parameter checks",
      "Generated PyTorch code you can read and export",
      "Dataset builder with a visual degradation chain",
      "Live training charts, checkpoints and exact resume",
      "Publish a trained model to AI Lab as a new version",
    ],
  },
];

export function workspaceByPath(pathname: string): Workspace | undefined {
  return WORKSPACES.find((w) => pathname === w.path || pathname.startsWith(`${w.path}/`));
}

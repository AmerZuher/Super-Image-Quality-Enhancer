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

/** Phases that have shipped; workspaces from later phases show a preview page. */
export const CURRENT_PHASE = 4;

export function isAvailable(workspace: Workspace): boolean {
  return workspace.phase <= CURRENT_PHASE;
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
      "Edit stack you can switch off, tweak or remove at any time",
      "Light, colour, detail and vignette adjustments with a live histogram",
      "Crop, rotate and flip with aspect presets",
      "Compare before and after with split, side-by-side and difference views",
      "Export JPEG, PNG, WebP, AVIF or TIFF with format checks and a target file size",
    ],
  },
  {
    id: "ai-lab",
    path: "/ai-lab",
    label: "AI Lab",
    icon: Sparkles,
    phase: 2,
    ai: true,
    summary: "Run and compare AI models on your images.",
    capabilities: [
      "Upscale ×2, ×3 and ×4 with tiled inference: any image size in fixed memory",
      "SIQE Classic, your original model, ported to PyTorch",
      "Denoise and background removal",
      "Full-resolution before and after compare",
      "Memory planner and out-of-memory fallback ladder, tuned for your GPU",
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
      "Duplicate groups that keep the best copy, with quarantine and undo",
      "Find similar images, or search by describing the photo",
      "Smart albums from rules: orientation, size, colour, tags, sharpness, location",
      "Camera details, and removing location without touching the pixels",
      "An import folder that waits for half-copied files",
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
      "Visual editor: chain edits, AI models and exports, and branch with If",
      "Runs that keep going when one image fails, with a dry run first",
      "Branch on orientation, size, tags, faces or anything a smart album can",
      "Run on a selection, an album or new images in a watched folder",
      "API keys, the REST API and the siqe command line",
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

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Asset } from "@/lib/api/client";
import { useAutoSelect } from "./AiLabPage";

const asset = (id: string, status: Asset["status"] = "ready") => ({ id, status }) as Asset;

describe("useAutoSelect", () => {
  it("ignores results that existed when the page loaded", () => {
    const select = vi.fn();
    const { rerender } = renderHook(({ list }) => useAutoSelect(list, select), {
      initialProps: { list: undefined as Asset[] | undefined },
    });
    rerender({ list: [asset("a"), asset("b")] });
    expect(select).not.toHaveBeenCalled();
  });

  it("selects a result once it becomes ready", () => {
    const select = vi.fn();
    const { rerender } = renderHook(({ list }) => useAutoSelect(list, select), {
      initialProps: { list: [asset("a")] as Asset[] | undefined },
    });
    rerender({ list: [asset("new", "processing"), asset("a")] });
    expect(select).not.toHaveBeenCalled();
    rerender({ list: [asset("new"), asset("a")] });
    expect(select).toHaveBeenCalledWith("new");
  });
});

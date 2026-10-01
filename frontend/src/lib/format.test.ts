import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, relativeTime, usageSeverity } from "./format";

describe("formatBytes", () => {
  it("picks a readable unit", () => {
    expect(formatBytes(24 * 1024 ** 3)).toBe("24.0 GB");
    expect(formatBytes(1536 * 1024 ** 2)).toBe("1.5 GB");
    expect(formatBytes(300 * 1024 ** 2)).toBe("300 MB");
    expect(formatBytes(null)).toBe("–");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-10-01T12:00:00Z");
  it("describes recent and older times", () => {
    expect(relativeTime("2026-10-01T11:59:58Z", now)).toBe("just now");
    expect(relativeTime("2026-10-01T11:59:30Z", now)).toBe("30 s ago");
    expect(relativeTime("2026-10-01T11:45:00Z", now)).toBe("15 min ago");
    expect(relativeTime("2026-09-29T12:00:00Z", now)).toBe("2 d ago");
    expect(relativeTime(null, now)).toBe("never");
  });
});

describe("formatDuration", () => {
  it("formats short and long durations", () => {
    expect(formatDuration("2026-10-01T12:00:00Z", "2026-10-01T12:00:02.500Z")).toBe("2.5 s");
    expect(formatDuration("2026-10-01T12:00:00Z", "2026-10-01T12:02:05Z")).toBe("2 min 5 s");
    expect(formatDuration(null)).toBe("–");
  });
});

describe("usageSeverity", () => {
  it("escalates at 70% and 90%", () => {
    expect(usageSeverity(0.5)).toBe("ok");
    expect(usageSeverity(0.75)).toBe("warn");
    expect(usageSeverity(0.95)).toBe("err");
  });
});

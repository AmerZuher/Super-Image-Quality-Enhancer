import { describe, expect, it } from "vitest";
import { defaultRule, describeRule, FIELDS, hasRule, QUICK_FILTERS, shapeLabel, toggleRule } from "./rules";

describe("library rules", () => {
  it("describes rules in plain words", () => {
    expect(describeRule({ field: "width", op: "gte", value: 1920 })).toBe("Width at least 1,920 px");
    expect(describeRule({ field: "orientation", op: "is", value: "portrait" })).toBe("Portrait");
    expect(describeRule({ field: "color", op: "is_not", value: "blue" })).toBe("Not blue");
    expect(describeRule({ field: "has_gps", op: "is", value: true })).toBe("Has location");
    expect(describeRule({ field: "has_gps", op: "is", value: false })).toBe("Not: has location");
    expect(describeRule({ field: "tag", op: "has", value: "lake" })).toBe("Tag has “lake”");
    expect(describeRule({ field: "sharpness", op: "lte", value: 0.3 })).toBe("Sharpness at most 0.3");
    expect(describeRule({ field: "added_days", op: "lte", value: 7 })).toBe("Added in the last 7 days");
  });

  it("makes a valid default rule for every field", () => {
    for (const field of Object.keys(FIELDS) as (keyof typeof FIELDS)[]) {
      const rule = defaultRule(field);
      expect(FIELDS[field].ops).toContain(rule.op);
      const kind = FIELDS[field].kind;
      if (kind === "number") expect(typeof rule.value).toBe("number");
      if (kind === "boolean") expect(rule.value).toBe(true);
    }
  });

  it("toggles quick filters, one choice per single-choice field", () => {
    const [landscape, portrait, , , blurry] = QUICK_FILTERS as [
      (typeof QUICK_FILTERS)[number],
      (typeof QUICK_FILTERS)[number],
      unknown,
      unknown,
      (typeof QUICK_FILTERS)[number],
    ];
    let set = toggleRule({ match: "all", rules: [] }, landscape.rule);
    expect(hasRule(set, landscape.rule)).toBe(true);
    set = toggleRule(set, portrait.rule);
    expect(hasRule(set, landscape.rule)).toBe(false);
    expect(hasRule(set, portrait.rule)).toBe(true);
    set = toggleRule(set, blurry.rule);
    expect(set.rules).toHaveLength(2);
    set = toggleRule(set, portrait.rule);
    expect(set.rules).toEqual([blurry.rule]);
  });

  it("labels shapes like the wallpaper albums", () => {
    expect(shapeLabel(1920, 1080)).toBe("desktop");
    expect(shapeLabel(1080, 2340)).toBe("phone");
    expect(shapeLabel(1000, 1010)).toBe("square");
    expect(shapeLabel(800, 1000)).toBeNull();
    expect(shapeLabel(0, 10)).toBeNull();
  });
});

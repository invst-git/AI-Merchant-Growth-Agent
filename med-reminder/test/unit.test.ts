import { describe, expect, it } from "vitest";
import { config as realConfig } from "../meds.config";
import { parseButtonId, parseText } from "../src/commands";
import { validateConfig } from "../src/config";
import { addDays, formatDuration, localParts, zonedToUtc } from "../src/time";
import { makeConfig } from "./helpers";

describe("time", () => {
  it("converts local wall-clock time to UTC", () => {
    expect(new Date(zonedToUtc("2026-10-19", "08:00", "Asia/Kolkata")).toISOString()).toBe("2026-10-19T02:30:00.000Z");
    expect(new Date(zonedToUtc("2026-07-01", "08:00", "America/New_York")).toISOString()).toBe("2026-07-01T12:00:00.000Z");
    expect(new Date(zonedToUtc("2026-12-01", "08:00", "America/New_York")).toISOString()).toBe("2026-12-01T13:00:00.000Z");
  });

  it("handles DST transitions", () => {
    // London springs forward 01:00 -> 02:00 on 2026-03-29; 01:30 doesn't exist.
    expect(new Date(zonedToUtc("2026-03-29", "01:30", "Europe/London")).toISOString()).toBe("2026-03-29T01:30:00.000Z");
    expect(new Date(zonedToUtc("2026-03-29", "08:00", "Europe/London")).toISOString()).toBe("2026-03-29T07:00:00.000Z");
    expect(new Date(zonedToUtc("2026-03-28", "08:00", "Europe/London")).toISOString()).toBe("2026-03-28T08:00:00.000Z");
    expect(new Date(zonedToUtc("2026-10-25", "08:00", "Europe/London")).toISOString()).toBe("2026-10-25T08:00:00.000Z");
  });

  it("reads local parts and weekdays", () => {
    const p = localParts(Date.parse("2026-10-18T20:00:00Z"), "Asia/Kolkata");
    expect(p).toEqual({ date: "2026-10-19", time: "01:30", weekday: "mon" });
    expect(localParts(Date.parse("2026-10-19T00:00:00Z"), "UTC").time).toBe("00:00");
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("formats durations", () => {
    expect(formatDuration(5 * 60_000)).toBe("5 min");
    expect(formatDuration(60 * 60_000)).toBe("1 h");
    expect(formatDuration(70 * 60_000)).toBe("1 h 10 min");
  });
});

describe("config", () => {
  it("the shipped meds.config.ts is valid", () => {
    expect(validateConfig(realConfig)).toEqual([]);
  });

  it("reports mistakes", () => {
    const errors = validateConfig(
      makeConfig({
        timezone: "Mars/Olympus",
        meds: [
          { name: "A", times: ["8:00", "25:00"] },
          { name: "a", times: ["09:00"], days: ["funday" as "mon"] },
        ],
      }),
    );
    expect(errors.join("\n")).toMatch(/timezone/);
    expect(errors.join("\n")).toMatch(/"8:00"/);
    expect(errors.join("\n")).toMatch(/"25:00"/);
    expect(errors.join("\n")).toMatch(/two meds/);
    expect(errors.join("\n")).toMatch(/funday/);
  });
});

describe("commands", () => {
  it("parses button ids", () => {
    expect(parseButtonId("taken:12")).toEqual({ kind: "taken", doseId: 12 });
    expect(parseButtonId("skip:3")).toEqual({ kind: "skip", doseId: 3 });
    expect(parseButtonId("snooze:4:15")).toEqual({ kind: "snooze", doseId: 4, minutes: 15 });
    expect(parseButtonId("bogus:1")).toBeNull();
    expect(parseButtonId("taken:abc")).toBeNull();
  });

  it("parses free text", () => {
    expect(parseText("Taken")).toEqual({ kind: "taken", filter: undefined });
    expect(parseText("took my metformin!")).toEqual({ kind: "taken", filter: "metformin" });
    expect(parseText("✅")).toEqual({ kind: "taken", filter: undefined });
    expect(parseText("skip vitamin d")).toEqual({ kind: "skip", filter: "vitamin d" });
    expect(parseText("snooze")).toEqual({ kind: "snooze", minutes: 30, filter: undefined });
    expect(parseText("snooze 15 min")).toEqual({ kind: "snooze", minutes: 15, filter: undefined });
    expect(parseText("snooze 1h thyroxine")).toEqual({ kind: "snooze", minutes: 60, filter: "thyroxine" });
    expect(parseText("snooze 99999")).toEqual({ kind: "snooze", minutes: 720, filter: undefined });
    expect(parseText("today")).toEqual({ kind: "status" });
    expect(parseText("hello there")).toEqual({ kind: "help" });
  });
});

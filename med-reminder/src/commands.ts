export type Command =
  | { kind: "taken" | "skip"; doseId?: number; filter?: string }
  | { kind: "snooze"; doseId?: number; filter?: string; minutes: number }
  | { kind: "status" }
  | { kind: "help" };

const MAX_SNOOZE_MIN = 12 * 60;

/** Parses a button id / template payload such as "taken:12" or "snooze:12:30". */
export function parseButtonId(id: string): Command | null {
  const [action, doseStr, minStr] = id.split(":");
  const doseId = Number(doseStr);
  if (!Number.isInteger(doseId) || doseId <= 0) return null;
  if (action === "taken" || action === "skip") return { kind: action, doseId };
  if (action === "snooze") return { kind: "snooze", doseId, minutes: clampSnooze(Number(minStr) || 30) };
  return null;
}

const TAKEN_WORDS = new Set(["taken", "take", "took", "done", "yes", "y", "ok", "okay", "✅", "👍", "tk"]);
const SKIP_WORDS = new Set(["skip", "skipped", "skipping", "⏭"]);
const SNOOZE_WORDS = new Set(["snooze", "later", "remind", "💤"]);
const STATUS_WORDS = new Set(["today", "status", "list", "log"]);

export function parseText(body: string): Command {
  const words = body.trim().toLowerCase().replace(/[.!,]+$/g, "").split(/\s+/).filter(Boolean);
  const [first = "", ...rest] = words;
  const filter = (ws: string[]) => {
    const f = ws.filter((w) => !["it", "my", "the", "pill", "pills", "meds", "med", "medicine"].includes(w)).join(" ");
    return f || undefined;
  };

  if (TAKEN_WORDS.has(first)) return { kind: "taken", filter: filter(rest) };
  if (SKIP_WORDS.has(first)) return { kind: "skip", filter: filter(rest) };
  if (SNOOZE_WORDS.has(first)) {
    let minutes = 30;
    const others: string[] = [];
    for (const w of rest) {
      const m = /^(\d+)(m|min|mins|minutes?|h|hr|hrs|hours?)?$/.exec(w);
      if (m) minutes = Number(m[1]) * (m[2]?.startsWith("h") ? 60 : 1);
      else if (!["min", "mins", "minutes", "for", "in", "me"].includes(w)) others.push(w);
    }
    return { kind: "snooze", minutes: clampSnooze(minutes), filter: filter(others) };
  }
  if (STATUS_WORDS.has(first)) return { kind: "status" };
  return { kind: "help" };
}

function clampSnooze(minutes: number): number {
  return Math.min(Math.max(Math.round(minutes), 1), MAX_SNOOZE_MIN);
}

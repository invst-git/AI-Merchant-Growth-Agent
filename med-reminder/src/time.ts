import type { Weekday } from "./config";

export interface LocalParts {
  date: string; // YYYY-MM-DD
  time: string; // HH:MM
  weekday: Weekday;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(tz: string): Intl.DateTimeFormat {
  let f = formatters.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(tz, f);
  }
  return f;
}

function parts(ms: number, tz: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of formatter(tz).formatToParts(ms)) out[p.type] = p.value;
  return out;
}

export function localParts(ms: number, tz: string): LocalParts {
  const p = parts(ms, tz);
  return {
    date: `${p.year}-${p.month}-${p.day}`,
    time: `${p.hour}:${p.minute}`,
    weekday: p.weekday!.toLowerCase() as Weekday,
  };
}

/** Offset of `tz` from UTC at instant `ms`, in ms (positive east of Greenwich). */
function offsetMs(ms: number, tz: string): number {
  const p = parts(ms, tz);
  const asUtc = Date.UTC(+p.year!, +p.month! - 1, +p.day!, +p.hour!, +p.minute!, +p.second!);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/**
 * The UTC instant of a local wall-clock time. A time skipped by a DST jump
 * resolves to the equivalent instant just after the jump.
 */
export function zonedToUtc(date: string, time: string, tz: string): number {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  const [h, mi] = time.split(":").map(Number) as [number, number];
  const naive = Date.UTC(y, mo - 1, d, h, mi);
  const first = naive - offsetMs(naive, tz);
  const second = naive - offsetMs(first, tz);
  return second;
}

export function addDays(date: string, days: number): string {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, mo - 1, d + days)).toISOString().slice(0, 10);
}

export function formatDuration(ms: number): string {
  const totalMin = Math.max(0, Math.round(ms / 60_000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

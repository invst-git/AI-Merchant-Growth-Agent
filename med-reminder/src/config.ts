export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Weekday = (typeof WEEKDAYS)[number];

export interface Med {
  name: string;
  /** Local times in 24h "HH:MM" format. */
  times: string[];
  /** Restrict to these weekdays. Omit for every day. */
  days?: Weekday[];
  /** Shown under the name in every reminder, e.g. "with food". */
  note?: string;
  /** Stop reminding and mark the dose missed this many minutes after it was due. */
  maxLateMin?: number;
}

export interface Config {
  /** IANA timezone, e.g. "Asia/Kolkata" or "Europe/London". */
  timezone: string;
  /** Repeat an unacknowledged reminder this often. */
  nagIntervalMin: number;
  /** After this many unacknowledged minutes, every reminder also goes out by email. null disables. */
  emailFallbackAfterMin: number | null;
  /** After this many unacknowledged minutes, alert the caregiver once. null disables. */
  escalateAfterMin: number | null;
  /** Used when a med has no maxLateMin of its own. */
  defaultMaxLateMin: number;
  /** Local "HH:MM" for the end-of-day summary. null disables. */
  digestTime: string | null;
  meds: Med[];
}

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export function medKey(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/** Returns a list of human-readable problems; empty means the config is usable. */
export function validateConfig(c: Config): string[] {
  const errors: string[] = [];
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: c.timezone });
  } catch {
    errors.push(`timezone "${c.timezone}" is not a valid IANA timezone`);
  }
  if (!(c.nagIntervalMin >= 1)) errors.push("nagIntervalMin must be at least 1");
  if (!(c.defaultMaxLateMin > 0)) errors.push("defaultMaxLateMin must be positive");
  if (c.digestTime !== null && !HHMM.test(c.digestTime)) errors.push(`digestTime "${c.digestTime}" must be HH:MM`);
  if (c.meds.length === 0) errors.push("add at least one med");

  const keys = new Set<string>();
  for (const med of c.meds) {
    const key = medKey(med.name);
    if (!key) errors.push(`med name "${med.name}" needs letters or digits`);
    if (keys.has(key)) errors.push(`two meds are named "${med.name}"`);
    keys.add(key);
    if (med.times.length === 0) errors.push(`${med.name}: add at least one time`);
    for (const t of med.times) {
      if (!HHMM.test(t)) errors.push(`${med.name}: time "${t}" must be 24h HH:MM, e.g. "08:00" or "21:30"`);
    }
    if (new Set(med.times).size !== med.times.length) errors.push(`${med.name}: duplicate times`);
    for (const d of med.days ?? []) {
      if (!WEEKDAYS.includes(d)) errors.push(`${med.name}: day "${d}" must be one of ${WEEKDAYS.join(", ")}`);
    }
    if (med.maxLateMin !== undefined && !(med.maxLateMin > 0)) errors.push(`${med.name}: maxLateMin must be positive`);
  }
  return errors;
}

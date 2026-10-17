import { cutoffAt, type Dose } from "./db";
import type { Button } from "./whatsapp";
import { formatDuration, localParts } from "./time";

export const DEFAULT_SNOOZE_MIN = 30;

export function doseLabel(dose: Dose): string {
  return `${dose.med_name} (${dose.local_time})`;
}

export function reminderText(dose: Dose, now: number): string {
  const late = now - dose.due_at;
  const timing = late < 60_000 ? `Due now (${dose.local_time})` : `Due ${dose.local_time} · ${formatDuration(late)} late`;
  const lines = [`💊 *${dose.med_name}*`];
  if (dose.note) lines.push(`_${dose.note}_`);
  lines.push(dose.send_count > 1 ? `${timing} · reminder #${dose.send_count}` : timing);
  return lines.join("\n");
}

export function reminderButtons(dose: Dose): Button[] {
  return [
    { id: `taken:${dose.id}`, title: "✅ Taken" },
    { id: `snooze:${dose.id}:${DEFAULT_SNOOZE_MIN}`, title: `💤 Snooze ${DEFAULT_SNOOZE_MIN} min` },
    { id: `skip:${dose.id}`, title: "⏭ Skip" },
  ];
}

export function missedText(dose: Dose): string {
  return `⚠️ No reply for ${doseLabel(dose)}, so it's logged as *missed* and the reminders have stopped. Check your instructions before taking a late dose.`;
}

export function escalationText(patientName: string, dose: Dose, now: number): string {
  return `🔔 ${patientName} hasn't confirmed taking ${dose.med_name}, due at ${dose.local_time} (${formatDuration(now - dose.due_at)} ago).`;
}

const STATUS_ICON: Record<string, string> = { taken: "✅", skipped: "⏭", missed: "❌", pending: "⏳" };

export function statusLine(dose: Dose, now: number, tz: string): string {
  if (dose.status === "pending" && dose.due_at > now) return `🕗 ${dose.local_time} ${dose.med_name}: upcoming`;
  const icon = STATUS_ICON[dose.status] ?? "•";
  if (dose.status === "pending") return `${icon} ${dose.local_time} ${dose.med_name}: waiting for you`;
  const when = dose.acked_at && dose.status !== "missed" ? ` at ${localParts(dose.acked_at, tz).time}` : "";
  return `${icon} ${dose.local_time} ${dose.med_name}: ${dose.status}${when}`;
}

export function statusText(title: string, doses: Dose[], now: number, tz: string): string {
  if (doses.length === 0) return `📋 ${title}\nNo doses scheduled.`;
  return [`📋 ${title}`, ...doses.map((d) => statusLine(d, now, tz))].join("\n");
}

export function digestText(date: string, doses: Dose[], now: number, tz: string): string {
  const done = doses.filter((d) => d.status === "taken").length;
  const counted = doses.filter((d) => d.due_at <= now).length;
  return `${statusText(`Summary for ${date}`, doses, now, tz)}\n\n${done}/${counted} taken so far.`;
}

export function snoozeText(dose: Dose, until: number, tz: string): string {
  let text = `💤 ${doseLabel(dose)}: I'll remind you again at ${localParts(until, tz).time}.`;
  if (until >= cutoffAt(dose)) {
    text += ` ⚠️ It will be logged as missed at ${localParts(cutoffAt(dose), tz).time}.`;
  }
  return text;
}

export const HELP_TEXT = [
  "💊 I'm your medication reminder. Reply with:",
  "• *taken*: log what's due now (or *taken metformin*)",
  "• *skip*: skip what's due now",
  "• *snooze 15*: remind me again in 15 min",
  "• *today*: show today's doses",
  "",
  "Tip: reply directly to a reminder, or tap its buttons, to act on that dose.",
].join("\n");
